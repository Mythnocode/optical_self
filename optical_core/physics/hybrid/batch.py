
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import hashlib
import struct
import json
import os
import platform
import sys
import time

import numpy as np


CACHE_SCHEMA_VERSION = "optical-batch-v2"


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _hash_update(hasher: Any, value: Any) -> None:

    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        hasher.update(b"A")
        hasher.update(array.dtype.str.encode("ascii"))
        hasher.update(repr(tuple(array.shape)).encode("ascii"))
        hasher.update(memoryview(array).cast("B"))
        return
    if isinstance(value, np.generic):
        _hash_update(hasher, value.item())
        return
    if hasattr(value, "__dataclass_fields__"):
        _hash_update(hasher, asdict(value))
        return
    if isinstance(value, Mapping):
        hasher.update(b"{")
        for key in sorted(value, key=lambda item: str(item)):
            _hash_update(hasher, str(key))
            _hash_update(hasher, value[key])
        hasher.update(b"}")
        return
    if isinstance(value, tuple):
        hasher.update(b"(")
        for item in value:
            _hash_update(hasher, item)
        hasher.update(b")")
        return
    if isinstance(value, list):
        hasher.update(b"[")
        for item in value:
            _hash_update(hasher, item)
        hasher.update(b"]")
        return
    if value is None:
        hasher.update(b"N")
    elif isinstance(value, bool):
        hasher.update(b"T" if value else b"F")
    elif isinstance(value, int):
        hasher.update(b"I" + str(value).encode("ascii"))
    elif isinstance(value, float):
        hasher.update(b"D" + struct.pack("!d", float(value)))
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        hasher.update(b"S" + str(len(encoded)).encode("ascii") + b":" + encoded)
    else:
        _hash_update(hasher, repr(value))


def _encode_array_tree(value: Any, arrays: dict[str, np.ndarray]) -> Any:
    if isinstance(value, np.ndarray):
        key = f"array_{len(arrays)}"
        arrays[key] = np.asarray(value)
        return {"__ndarray__": key}
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "__dataclass_fields__"):
        return _encode_array_tree(asdict(value), arrays)
    if isinstance(value, Mapping):
        return {str(k): _encode_array_tree(v, arrays) for k, v in value.items()}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode_array_tree(v, arrays) for v in value]}
    if isinstance(value, list):
        return [_encode_array_tree(v, arrays) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _decode_array_tree(value: Any, arrays: Mapping[str, np.ndarray]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__ndarray__"}:
            return np.asarray(arrays[str(value["__ndarray__"])]).copy()
        if set(value) == {"__tuple__"}:
            return tuple(_decode_array_tree(v, arrays) for v in value["__tuple__"])
        return {k: _decode_array_tree(v, arrays) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_array_tree(v, arrays) for v in value]
    return value


def cache_key(
    design: Any,
    *,
    wavelength: Any = None,
    source: Any = None,
    fiber: Any = None,
    grid: Any = None,
    pupil_sampling: Any = None,
    propagation_algorithm: Any = None,
    code_version: str | None = None,
) -> str:
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "design": design, "wavelength": wavelength, "source": source,
        "fiber": fiber, "grid": grid, "pupil_sampling": pupil_sampling,
        "propagation_algorithm": propagation_algorithm,
        "code_version": str(code_version or os.environ.get("OPTICAL_CODE_VERSION", "unknown")),
    }
    digest = hashlib.sha256()
    _hash_update(digest, payload)
    return digest.hexdigest()



@dataclass(frozen=True, slots=True)
class BatchEvaluationResult:
    results: tuple[Any, ...]
    cache_hits: int
    evaluated_count: int
    elapsed_s: float
    fidelity: str
    metrics_only: bool
    screened_count: int = 0


class PersistentMetricCache:


    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def array_path_for(self, key: str) -> Path:
        return self.directory / f"{key}.npz"

    def get(self, key: str) -> Any | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("schema") != CACHE_SCHEMA_VERSION:
            return None
        array_names = tuple(payload.get("arrays", ()))
        arrays: dict[str, np.ndarray] = {}
        if array_names:
            array_path = self.array_path_for(key)
            if not array_path.exists():
                return None
            try:
                with np.load(array_path, allow_pickle=False) as archive:
                    arrays = {name: np.asarray(archive[name]) for name in array_names}
            except (OSError, ValueError, KeyError):
                return None
        return _decode_array_tree(payload.get("result"), arrays)

    def put(self, key: str, result: Any) -> None:
        path = self.path_for(key)
        temporary = path.with_suffix(".json.tmp")
        array_path = self.array_path_for(key)
        temporary_array = array_path.with_suffix(".npz.tmp")
        arrays: dict[str, np.ndarray] = {}
        encoded = _encode_array_tree(result, arrays)
        payload = {
            "schema": CACHE_SCHEMA_VERSION, "python": sys.version,
            "platform": platform.platform(), "arrays": list(arrays),
            "result": encoded,
        }
        if arrays:
            with temporary_array.open("wb") as stream:
                np.savez(stream, **arrays)
            temporary_array.replace(array_path)
        elif array_path.exists():
            array_path.unlink()
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


def evaluate_batch(
    designs: Sequence[Any],
    evaluator: Callable[[Any, str, bool], Any],
    *,
    fidelity: str = "medium",
    metrics_only: bool = True,
    max_workers: int = 4,
    cache_directory: str | Path | None = None,
    key_builder: Callable[[Any], str] | None = None,
    cache_context: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    code_version: str | None = None,
    internal_thread_limit: int | None = 1,
    screening_evaluator: Callable[[Any], tuple[bool, Any]] | None = None,
) -> BatchEvaluationResult:

    started = time.perf_counter()
    cache = None if cache_directory is None else PersistentMetricCache(cache_directory)
    results: list[Any] = [None] * len(designs)
    misses: list[tuple[int, Any, str]] = []
    hits = 0
    screened = 0
    for index, design in enumerate(designs):
        if key_builder is not None:
            key = key_builder(design)
        else:
            context = cache_context(design) if callable(cache_context) else dict(cache_context or {})
            algorithm = context.get("propagation_algorithm", {})
            if isinstance(algorithm, Mapping):
                algorithm = {**algorithm, "fidelity": fidelity, "metrics_only": metrics_only}
            key = cache_key(
                design,
                wavelength=context.get("wavelength"),
                source=context.get("source"),
                fiber=context.get("fiber"),
                grid=context.get("grid"),
                pupil_sampling=context.get("pupil_sampling"),
                propagation_algorithm=algorithm,
                code_version=code_version or context.get("code_version"),
            )
        cached = None if cache is None else cache.get(key)
        if cached is not None:
            results[index] = cached
            hits += 1
            continue
        if screening_evaluator is not None:
            skip_expensive, screened_result = screening_evaluator(design)
            if bool(skip_expensive):
                results[index] = screened_result
                screened += 1
                if cache is not None:
                    cache.put(key, screened_result)
                continue
        misses.append((index, design, key))

    def run(item: tuple[int, Any, str]) -> tuple[int, str, Any]:
        index, design, key = item
        limiter = nullcontext()
        if int(max_workers) > 1 and internal_thread_limit is not None:
            try:
                from threadpoolctl import threadpool_limits
                limiter = threadpool_limits(limits=max(1, int(internal_thread_limit)))
            except ImportError:
                limiter = nullcontext()
        with limiter:
            return index, key, evaluator(design, fidelity, metrics_only)

    if misses:
        workers = max(1, int(max_workers))
        if workers == 1:
            completed = map(run, misses)
        else:
            executor = ThreadPoolExecutor(max_workers=workers)
            completed = executor.map(run, misses)
        try:
            for index, key, result in completed:
                results[index] = result
                if cache is not None:
                    cache.put(key, result)
        finally:
            if workers != 1:
                executor.shutdown(wait=True)
    return BatchEvaluationResult(
        results=tuple(results), cache_hits=hits, evaluated_count=len(misses),
        elapsed_s=float(time.perf_counter() - started), fidelity=str(fidelity),
        metrics_only=bool(metrics_only), screened_count=int(screened),
    )


__all__ = [
    "CACHE_SCHEMA_VERSION", "cache_key", "PersistentMetricCache",
    "BatchEvaluationResult", "evaluate_batch",
]
