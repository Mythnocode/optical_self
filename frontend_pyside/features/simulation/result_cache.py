
from __future__ import annotations

from collections import OrderedDict
import os
from copy import deepcopy
from dataclasses import dataclass, field
from time import time
from typing import Any, Mapping

from optical_runtime.dependency_graph import build_project_dependency_keys


@dataclass(slots=True)
class CachedResult:
    physical_fingerprint: str
    analyses: set[str] = field(default_factory=set)
    result: dict[str, Any] = field(default_factory=dict)
    project: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time)
    dependency_keys: dict[str, Any] = field(default_factory=dict)
    convergence_by_analysis: dict[str, bool] = field(default_factory=dict)
    warnings_by_analysis: dict[str, list[Any]] = field(default_factory=dict)
    errors_by_analysis: dict[str, list[Any]] = field(default_factory=dict)


class SimulationResultCache:
    def __init__(self, max_entries: int = 8):
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(16 * 1024 * 1024, int(os.getenv(
            "OPTICAL_FRONTEND_RESULT_CACHE_MAX_BYTES", str(384 * 1024 * 1024)
        )))
        self.max_entry_bytes = max(8 * 1024 * 1024, int(os.getenv(
            "OPTICAL_FRONTEND_RESULT_CACHE_ENTRY_MAX_BYTES", str(160 * 1024 * 1024)
        )))
        self._entries: OrderedDict[str, CachedResult] = OrderedDict()
        self._entry_bytes: dict[str, int] = {}
        self._total_bytes = 0

    def available_analyses(self, fingerprint: str) -> frozenset[str]:
        entry = self._entries.get(str(fingerprint))
        return frozenset(entry.analyses) if entry else frozenset()

    def missing_analyses(self, fingerprint: str, requested: set[str] | frozenset[str]) -> frozenset[str]:
        return frozenset(set(requested) - set(self.available_analyses(fingerprint)))

    def get_covering(self, fingerprint: str, requested: set[str] | frozenset[str]) -> dict[str, Any] | None:
        key = str(fingerprint)
        entry = self._entries.get(key)
        if entry is None or not set(requested).issubset(entry.analyses):
            return None
        self._entries.move_to_end(key)
        result = _clone_result(entry.result)
        result.setdefault("metadata", {})
        result["metadata"]["frontend_cache_status"] = "hit"
        result["metadata"]["frontend_cached_analyses"] = sorted(entry.analyses)
        return result

    def find_receiver_field_compatible(self, dependency_key: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        wanted = str(dependency_key or "")
        if not wanted:
            return None
        for key in list(reversed(self._entries)):
            entry = self._entries[key]
            
            
            
            
            metadata = entry.result.get("metadata") if isinstance(entry.result, dict) else {}
            if str(entry.result.get("status", "completed")) != "completed":
                continue
            if not bool(entry.result.get("converged", True)):
                continue
            if isinstance(metadata, dict) and bool(metadata.get("preview_only", False)):
                continue
            if str(entry.dependency_keys.get("receiver_field", "")) != wanted:
                continue
            self._entries.move_to_end(key)
            result = _clone_result(entry.result)
            result.setdefault("metadata", {})
            if isinstance(result["metadata"], dict):
                result["metadata"]["frontend_dependency_keys"] = dict(entry.dependency_keys)
            return result, deepcopy(entry.project)
        return None

    def merge(
        self,
        fingerprint: str,
        analyses: set[str] | frozenset[str],
        result: Mapping[str, Any],
        project: Mapping[str, Any],
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = str(fingerprint)
        entry = self._entries.get(key)
        if entry is None:
            entry = CachedResult(physical_fingerprint=key)
            self._entries[key] = entry
        analysis_names = {str(item) for item in analyses}
        entry.analyses.update(analysis_names)
        entry.project = deepcopy(dict(project))
        entry.result = _merge_result_bodies(entry.result, dict(result))
        incoming_converged = bool(result.get("converged", True))
        incoming_warnings = list(result.get("warnings", []) or [])
        incoming_errors = list(result.get("errors", []) or [])
        for analysis_name in analysis_names:
            
            
            
            entry.convergence_by_analysis[analysis_name] = incoming_converged
            entry.warnings_by_analysis[analysis_name] = _clone_result(incoming_warnings)
            entry.errors_by_analysis[analysis_name] = _clone_result(incoming_errors)
        if entry.convergence_by_analysis:
            entry.result["converged"] = all(entry.convergence_by_analysis.values())
        entry.result["warnings"] = _unique_items(
            item for values in entry.warnings_by_analysis.values() for item in values
        )
        entry.result["errors"] = _unique_items(
            item for values in entry.errors_by_analysis.values() for item in values
        )
        metadata = result.get("metadata") if isinstance(result, Mapping) else None
        if options is None and isinstance(metadata, Mapping) and isinstance(metadata.get("dependency_keys"), Mapping):
            entry.dependency_keys = dict(metadata["dependency_keys"])
        else:
            entry.dependency_keys = build_project_dependency_keys(entry.project, dict(options or {}))
        entry.updated_at = time()
        self._entries.move_to_end(key)
        self._update_entry_size(key, entry)
        self._evict_to_budget(protected_key=key)

        
        
        
        remove_after_return = self._entry_bytes.get(key, 0) > min(
            self.max_entry_bytes, self.max_bytes
        )
        merged = _clone_result(entry.result)
        merged.setdefault("metadata", {})
        merged["metadata"]["frontend_cache_status"] = "merged"
        merged["metadata"]["frontend_cached_analyses"] = sorted(entry.analyses)
        if remove_after_return:
            self._drop_entry(key)
            merged["metadata"]["frontend_cache_status"] = "oversized_not_retained"
        return merged

    def invalidate_analyses(self, fingerprint: str, analyses: set[str] | frozenset[str]) -> None:
        entry = self._entries.get(str(fingerprint))
        if entry is None:
            return
        removed = {str(item) for item in analyses}
        entry.analyses.difference_update(removed)
        for analysis_name in removed:
            entry.convergence_by_analysis.pop(analysis_name, None)
            entry.warnings_by_analysis.pop(analysis_name, None)
            entry.errors_by_analysis.pop(analysis_name, None)
        if entry.convergence_by_analysis:
            entry.result["converged"] = all(entry.convergence_by_analysis.values())
        entry.result["warnings"] = _unique_items(
            item for values in entry.warnings_by_analysis.values() for item in values
        )
        entry.result["errors"] = _unique_items(
            item for values in entry.errors_by_analysis.values() for item in values
        )
        if not entry.analyses:
            self._drop_entry(str(fingerprint))
        else:
            self._update_entry_size(str(fingerprint), entry)

    def _update_entry_size(self, key: str, entry: CachedResult) -> None:
        size = _estimate_result_bytes(entry.result)
        previous = self._entry_bytes.get(key, 0)
        self._entry_bytes[key] = size
        self._total_bytes += size - previous

    def _drop_entry(self, key: str) -> None:
        self._entries.pop(key, None)
        self._total_bytes -= self._entry_bytes.pop(key, 0)
        self._total_bytes = max(0, self._total_bytes)

    def _evict_to_budget(self, *, protected_key: str = "") -> None:
        while self._entries and (
            len(self._entries) > self.max_entries or self._total_bytes > self.max_bytes
        ):
            oldest = next(iter(self._entries))
            if oldest == protected_key and len(self._entries) == 1:
                break
            if oldest == protected_key:
                self._entries.move_to_end(oldest)
                oldest = next(iter(self._entries))
            self._drop_entry(oldest)

    def clear(self) -> None:
        self._entries.clear()
        self._entry_bytes.clear()
        self._total_bytes = 0


def _estimate_result_bytes(value: Any, seen: set[int] | None = None) -> int:
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    nbytes = getattr(value, "nbytes", None)
    if isinstance(nbytes, (int, float)):
        return max(0, int(nbytes))
    if isinstance(value, Mapping):
        return sum(_estimate_result_bytes(item, seen) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return sum(_estimate_result_bytes(item, seen) for item in value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)
    return 0


def _unique_items(values) -> list[Any]:
    result: list[Any] = []
    for item in values:
        if item not in result:
            result.append(item)
    return result


def _clone_result(value: Any) -> Any:
    module = type(value).__module__
    if module == "numpy" or hasattr(value, "__array_interface__"):
        return value
    if isinstance(value, dict):
        return {key: _clone_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_result(item) for item in value)
    return deepcopy(value)


def _merge_result_bodies(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    if not old:
        return _clone_result(dict(new))
    merged = _clone_result(dict(old))
    incoming = _clone_result(dict(new))
    for key in ("metrics", "arrays", "metadata"):
        current_value = merged.get(key)
        incoming_value = incoming.get(key)
        if isinstance(current_value, dict) and isinstance(incoming_value, dict):
            current_value.update(incoming_value)
        elif incoming_value is not None:
            merged[key] = incoming_value
    for key in ("warnings", "errors"):
        values: list[Any] = []
        for item in list(merged.get(key, []) or []) + list(incoming.get(key, []) or []):
            if item not in values:
                values.append(item)
        merged[key] = values
    for key, value in incoming.items():
        if key not in {"metrics", "arrays", "metadata", "warnings", "errors"}:
            merged[key] = value
    merged["converged"] = bool(old.get("converged", True)) and bool(new.get("converged", True))
    merged["status"] = str(new.get("status", old.get("status", "completed")))
    merged["elapsed_ms"] = float(old.get("elapsed_ms", 0.0) or 0.0) + float(new.get("elapsed_ms", 0.0) or 0.0)
    return merged


__all__ = ["CachedResult", "SimulationResultCache"]
