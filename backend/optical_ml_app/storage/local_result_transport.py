
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import math
import os
import re
import shutil
import time
from typing import Any
import uuid

import numpy as np

from backend.optical_ml_app.infrastructure.json_utils import to_storage_value
from backend.optical_ml_app.storage.atomic_files import atomic_write_via

ARRAY_THRESHOLD = 256


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value)).strip("._")
    return cleaned[:120] or "array"


def _numeric_array(value: Any) -> np.ndarray | None:
    if isinstance(value, np.ndarray):
        return value if value.dtype.kind in "biufc" else None
    if isinstance(value, (list, tuple)) and value:
        try:
            array = np.asarray(value)
        except Exception:
            return None
        if array.dtype.kind in "biufc" and array.size >= ARRAY_THRESHOLD:
            return array
    return None


def _write_npy(path: Path, array: np.ndarray) -> None:
    with Path(path).open("wb") as handle:
        np.save(handle, array, allow_pickle=False)


def _encode(value: Any, directory: Path, path: str, files: list[Path]) -> Any:
    array = _numeric_array(value)
    if array is not None and array.size >= ARRAY_THRESHOLD:
        if array.dtype.kind == "f" and array.dtype.itemsize > 4:
            array = array.astype(np.float32, copy=False)
        array = np.ascontiguousarray(array)
        stem = _safe_name(path or f"array_{len(files)}")
        target = directory / f"{stem}.npy"
        suffix = 1
        while target.exists():
            target = directory / f"{stem}_{suffix}.npy"
            suffix += 1
        atomic_write_via(target, lambda tmp: _write_npy(tmp, array))
        files.append(target)
        stat = target.stat()
        return {
            "__local_npy__": str(target.resolve()),
            "shape": list(array.shape),
            "dtype": str(array.dtype),
            "readonly": True,
            "file_size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {
            str(key): _encode(item, directory, f"{path}.{key}" if path else str(key), files)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _encode(item, directory, f"{path}.{index}" if path else str(index), files)
            for index, item in enumerate(value)
        ]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _prune_generations(root: Path, *, keep: int) -> None:
    generations = sorted(
        (item for item in root.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in generations[max(1, int(keep)):]:
        try:
            shutil.rmtree(old)
        except OSError:
            
            
            continue


def create_local_result_view(job_dir: Path, payload: Any) -> dict[str, Any]:
    root = Path(job_dir) / "live_arrays"
    root.mkdir(parents=True, exist_ok=True)
    generation = f"g-{time.time_ns()}-{uuid.uuid4().hex[:8]}"
    directory = root / generation
    directory.mkdir(parents=True, exist_ok=False)
    raw = to_storage_value(payload)
    files: list[Path] = []
    try:
        encoded = _encode(raw, directory, "result", files)
    except BaseException:
        try:
            shutil.rmtree(directory)
        except OSError:
            pass
        raise
    if not isinstance(encoded, dict):
        encoded = {"result": encoded}
    encoded.setdefault("metadata", {})
    if isinstance(encoded["metadata"], dict):
        encoded["metadata"].update({
            "local_array_transport": "numpy_memmap",
            "local_array_count": len(files),
            "local_array_generation": generation,
            "local_array_created_at": datetime.now(timezone.utc).isoformat(),
            "archival_persistence_pending": True,
        })
    _prune_generations(root, keep=max(2, int(os.getenv("OPTICAL_LIVE_VIEW_KEEP_GENERATIONS", "4"))))
    return encoded


def materialize_local_result(value: Any) -> Any:
    if isinstance(value, dict) and "__local_npy__" in value:
        path = Path(str(value["__local_npy__"]))
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        expected_size = int(value.get("file_size", 0) or 0)
        expected_mtime = int(value.get("mtime_ns", 0) or 0)
        if expected_size and stat.st_size != expected_size:
            raise RuntimeError(f"local array size changed: {path}")
        if expected_mtime and stat.st_mtime_ns != expected_mtime:
            raise RuntimeError(f"local array generation changed: {path}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        expected_shape = tuple(int(item) for item in value.get("shape", array.shape))
        expected_dtype = str(value.get("dtype", array.dtype))
        if tuple(array.shape) != expected_shape or str(array.dtype) != expected_dtype:
            close = getattr(getattr(array, "_mmap", None), "close", None)
            if callable(close):
                close()
            raise RuntimeError(f"local array descriptor mismatch: {path}")
        return array
    if isinstance(value, dict):
        return {key: materialize_local_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [materialize_local_result(item) for item in value]
    return value


__all__ = ["create_local_result_view", "materialize_local_result"]
