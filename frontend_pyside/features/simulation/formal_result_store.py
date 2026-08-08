
from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any

from .ray_data_model import FormalRayDataset
from .ray_view_adapters import RayViewOptions, build_ray_view_plots
from .result_adapter import formal_result_to_plots


RAY_VIEW_KEYS = frozenset({"光路", "3D光路"})


class FormalResultStore:


    def __init__(
        self,
        result: Mapping[str, Any],
        project: Mapping[str, Any],
        *,
        section_options: Mapping[str, Any] | None = None,
    ):
        self.result = _clone_result(dict(result))
        self.project = deepcopy(dict(project))
        self.ray_dataset = FormalRayDataset.from_backend(
            dict(self.result.get("arrays", {}) or {}),
            self.project,
        )
        self.section_options = RayViewOptions.from_mapping(dict(section_options or {}))
        self._plots: dict[str, dict[str, Any]] = {}
        self._source_token = _source_token(self.result, self.project)

    @property
    def cached_keys(self) -> frozenset[str]:
        return frozenset(self._plots)

    def ensure(self, keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        requested = {str(key) for key in keys if str(key)}
        missing = requested - set(self._plots)
        ray_missing = missing & RAY_VIEW_KEYS
        if ray_missing and self.ray_dataset is not None:
            ray_plots = build_ray_view_plots(self.ray_dataset, self.section_options)
            self._store({key: value for key, value in ray_plots.items() if key in ray_missing})
            missing -= RAY_VIEW_KEYS
        if missing:
            plots = formal_result_to_plots(
                self.result,
                self.project,
                requested_keys=missing,
            )
            self._store(plots)
        return {key: self._plots[key] for key in requested if key in self._plots}

    def update_section(
        self,
        options: Mapping[str, Any],
        *,
        requested_keys: Iterable[str] = RAY_VIEW_KEYS,
    ) -> dict[str, dict[str, Any]]:
        new_options = RayViewOptions.from_mapping(dict(options or {}))
        requested = {str(key) for key in requested_keys if str(key)} & RAY_VIEW_KEYS
        if new_options == self.section_options:
            return self.ensure(requested)

        old = self.section_options
        self.section_options = new_options
        changed = _changed_ray_views(old, new_options)
        for key in changed:
            self._plots.pop(key, None)
        return self.ensure(requested)

    def has_view(self, key: str) -> bool:
        return str(key) in self._plots

    def _store(self, plots: Mapping[str, Mapping[str, Any]]) -> None:
        for key, raw in plots.items():
            plot = dict(raw or {})
            plot["render_key"] = _render_key(
                self._source_token,
                str(key),
                plot.get("section_options"),
            )
            self._plots[str(key)] = plot


def _changed_ray_views(old: RayViewOptions, new: RayViewOptions) -> frozenset[str]:
    two_d_fields = (
        "plane",
        "position_mm",
        "half_thickness_mm",
        "custom_azimuth_deg",
        "max_section_rays",
        "scale_mode",
        "selected_surface_index",
        "selected_group_id",
    )
    three_d_fields = (
        "plane",
        "position_mm",
        "custom_azimuth_deg",
        "max_3d_rays",
        "scale_mode",
        "selected_surface_index",
        "selected_group_id",
    )
    changed: set[str] = set()
    if any(getattr(old, name) != getattr(new, name) for name in two_d_fields):
        changed.add("光路")
    if any(getattr(old, name) != getattr(new, name) for name in three_d_fields):
        changed.add("3D光路")
    return frozenset(changed)


def _source_token(result: Mapping[str, Any], project: Mapping[str, Any]) -> str:
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("request_id", "result_id", "project_fingerprint"):
            if metadata.get(key):
                return str(metadata[key])
    compact = {
        "status": result.get("status"),
        "elapsed_ms": result.get("elapsed_ms"),
        "project": project.get("fingerprint", project.get("project_id")),
        "array_keys": sorted((result.get("arrays") or {}).keys()),
    }
    return hashlib.sha256(
        json.dumps(compact, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def _render_key(source: str, key: str, options: Any) -> str:
    payload = json.dumps(options or {}, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"formal:{source}:{key}:{digest}"


__all__ = ["FormalResultStore", "RAY_VIEW_KEYS"]


def _clone_result(value: Any) -> Any:
    if type(value).__module__ == "numpy" or hasattr(value, "__array_interface__"):
        return value
    if isinstance(value, dict):
        return {key: _clone_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_result(item) for item in value)
    return deepcopy(value)
