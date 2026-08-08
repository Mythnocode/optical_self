
from __future__ import annotations

from dataclasses import dataclass, field
import math
import sys
from typing import Any, Iterable, Mapping

import numpy as np

from optical_core.coordinates import X_INDEX, Y_INDEX, Z_INDEX


@dataclass(frozen=True, slots=True)
class RayTraceMemoryPlan:
    ray_count: int
    surface_count: int
    batch_size: int
    batch_count: int
    bytes_per_ray_state: int
    estimated_state_bytes: int
    estimated_state_mib: float
    recommended_batch_size: int


@dataclass(frozen=True, slots=True)
class MultiPlaneTraceResult:

    plane_z_mm: tuple[float, ...]
    positions_by_plane_mm: tuple[tuple[tuple[float, float, float], ...], ...]
    valid_mask_by_plane: tuple[tuple[bool, ...], ...]
    centroid_xy_by_plane_mm: tuple[tuple[float, float], ...]
    rms_radius_by_plane_mm: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RayTraceEngineeringReport:
    ray_count: int
    valid_ray_count: int
    blocked_ray_count: int
    valid_ray_ratio: float
    blocked_reasons: Mapping[str, int] = field(default_factory=dict)
    surface_valid_counts: tuple[int, ...] = ()
    final_centroid_xy_mm: tuple[float, float] = (0.0, 0.0)
    final_rms_radius_mm: float = 0.0
    multi_plane: MultiPlaneTraceResult | None = None
    memory_plan: RayTraceMemoryPlan | None = None

    @property
    def metrics(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "engineering_ray_count": self.ray_count,
            "engineering_valid_ray_count": self.valid_ray_count,
            "engineering_blocked_ray_count": self.blocked_ray_count,
            "engineering_valid_ray_ratio": self.valid_ray_ratio,
            "engineering_final_centroid_x_mm": self.final_centroid_xy_mm[0],
            "engineering_final_centroid_y_mm": self.final_centroid_xy_mm[1],
            "engineering_final_rms_radius_mm": self.final_rms_radius_mm,
        }
        for reason, count in self.blocked_reasons.items():
            data[f"blocked_reason_{reason}"] = int(count)
        if self.memory_plan is not None:
            data.update(
                {
                    "raytrace_memory_estimated_state_bytes": self.memory_plan.estimated_state_bytes,
                    "raytrace_memory_estimated_state_mib": self.memory_plan.estimated_state_mib,
                    "raytrace_memory_batch_count": self.memory_plan.batch_count,
                    "raytrace_memory_recommended_batch_size": self.memory_plan.recommended_batch_size,
                }
            )
        if self.multi_plane is not None:
            data["multi_plane_count"] = len(self.multi_plane.plane_z_mm)
        return data

    @property
    def arrays(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "surface_valid_counts": list(self.surface_valid_counts),
            "blocked_reason_labels": list(self.blocked_reasons.keys()),
            "blocked_reason_counts": list(self.blocked_reasons.values()),
        }
        if self.multi_plane is not None:
            data.update(
                {
                    "multi_plane_z_mm": list(self.multi_plane.plane_z_mm),
                    "multi_plane_positions_mm": [
                        [list(point) for point in plane]
                        for plane in self.multi_plane.positions_by_plane_mm
                    ],
                    "multi_plane_valid_mask": [
                        list(mask) for mask in self.multi_plane.valid_mask_by_plane
                    ],
                    "multi_plane_centroid_xy_mm": [
                        list(item) for item in self.multi_plane.centroid_xy_by_plane_mm
                    ],
                    "multi_plane_rms_radius_mm": list(self.multi_plane.rms_radius_by_plane_mm),
                }
            )
        return data


def build_engineering_trace_report(
    trace: Any,
    *,
    plane_z_mm: Iterable[float] | None = None,
    surface_count: int | None = None,
    batch_size: int | None = None,
    memory_budget_mib: float = 128.0,
) -> RayTraceEngineeringReport:
    final_positions = _as_2d_float_array(getattr(trace, "final_positions_mm", []), columns=3)
    final_directions = _as_2d_float_array(getattr(trace, "final_directions", []), columns=3)
    valid_mask = _as_bool_mask(getattr(trace, "valid_mask", None), len(final_positions))

    ray_count = int(valid_mask.size)
    valid_ray_count = int(np.count_nonzero(valid_mask))
    blocked_ray_count = int(ray_count - valid_ray_count)
    valid_ray_ratio = float(valid_ray_count / ray_count) if ray_count else 0.0

    blocked_reasons = classify_blocked_reasons(trace, valid_mask=valid_mask)
    surface_valid_counts = summarize_surface_valid_counts(trace, ray_count=ray_count)
    centroid_xy, rms_radius = _centroid_and_rms(final_positions, valid_mask)

    if surface_count is None:
        surface_count = len(surface_valid_counts) if surface_valid_counts else int(getattr(trace, "surface_count", 1) or 1)
    if batch_size is None:
        batch_size = ray_count if ray_count > 0 else 1
    memory_plan = estimate_raytrace_memory_plan(
        ray_count=ray_count,
        surface_count=surface_count,
        batch_size=batch_size,
        memory_budget_mib=memory_budget_mib,
    )

    multi_plane = None
    if plane_z_mm is not None:
        multi_plane = build_multi_plane_trace(
            trace,
            plane_z_mm=tuple(float(z) for z in plane_z_mm),
            final_positions=final_positions,
            final_directions=final_directions,
            valid_mask=valid_mask,
        )

    return RayTraceEngineeringReport(
        ray_count=ray_count,
        valid_ray_count=valid_ray_count,
        blocked_ray_count=blocked_ray_count,
        valid_ray_ratio=valid_ray_ratio,
        blocked_reasons=blocked_reasons,
        surface_valid_counts=surface_valid_counts,
        final_centroid_xy_mm=centroid_xy,
        final_rms_radius_mm=rms_radius,
        multi_plane=multi_plane,
        memory_plan=memory_plan,
    )


def classify_blocked_reasons(trace: Any, *, valid_mask: np.ndarray | None = None) -> dict[str, int]:
    if valid_mask is None:
        final_positions = _as_2d_float_array(getattr(trace, "final_positions_mm", []), columns=3)
        valid_mask = _as_bool_mask(getattr(trace, "valid_mask", None), len(final_positions))
    raw_reasons = getattr(trace, "blocked_reasons", None)
    if raw_reasons is None:
        raw_reasons = getattr(trace, "blocked_reason", None)
    if raw_reasons is None:
        raw_reasons = getattr(trace, "termination_reasons", None)
    blocked = ~np.asarray(valid_mask, dtype=bool)
    if raw_reasons is None:
        return {"unknown": int(np.count_nonzero(blocked))} if np.any(blocked) else {}
    values = list(raw_reasons)
    counts: dict[str, int] = {}
    for index, is_blocked in enumerate(blocked.tolist()):
        if not is_blocked:
            continue
        reason = values[index] if index < len(values) else "unknown"
        key = _normalize_reason(reason)
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize_surface_valid_counts(trace: Any, *, ray_count: int | None = None) -> tuple[int, ...]:
    surface_masks = getattr(trace, "surface_valid_masks", None)
    if surface_masks is None:
        surface_masks = getattr(trace, "valid_mask_by_surface", None)
    if surface_masks is not None:
        arr = np.asarray(surface_masks, dtype=bool)
        if arr.ndim == 1:
            return (int(np.count_nonzero(arr)),)
        return tuple(int(np.count_nonzero(row)) for row in arr)
    history = getattr(trace, "surface_history", None)
    if history is not None:
        counts = []
        for entry in history:
            mask = getattr(entry, "valid_mask", None)
            if mask is not None:
                counts.append(int(np.count_nonzero(np.asarray(mask, dtype=bool))))
        if counts:
            return tuple(counts)
    if ray_count is None:
        mask = getattr(trace, "valid_mask", None)
        if mask is not None:
            ray_count = len(mask)
    return (int(ray_count or 0),)


def build_multi_plane_trace(
    trace: Any,
    *,
    plane_z_mm: Iterable[float],
    final_positions: np.ndarray | None = None,
    final_directions: np.ndarray | None = None,
    valid_mask: np.ndarray | None = None,
) -> MultiPlaneTraceResult:
    if final_positions is None:
        final_positions = _as_2d_float_array(getattr(trace, "final_positions_mm", []), columns=3)
    if final_directions is None:
        final_directions = _as_2d_float_array(getattr(trace, "final_directions", []), columns=3)
    if valid_mask is None:
        valid_mask = _as_bool_mask(getattr(trace, "valid_mask", None), len(final_positions))

    planes = tuple(float(item) for item in plane_z_mm)
    positions_by_plane: list[tuple[tuple[float, float, float], ...]] = []
    valid_by_plane: list[tuple[bool, ...]] = []
    centroids: list[tuple[float, float]] = []
    rms_values: list[float] = []
    if final_positions.size == 0 or final_directions.size == 0:
        empty = tuple(() for _ in planes)
        return MultiPlaneTraceResult(planes, empty, empty, tuple((0.0, 0.0) for _ in planes), tuple(0.0 for _ in planes))

    dz = final_directions[:, Z_INDEX]
    safe_dz = np.where(np.abs(dz) < 1e-15, np.nan, dz)
    for plane in planes:
        t = (plane - final_positions[:, Z_INDEX]) / safe_dz
        positions = final_positions + final_directions * t[:, None]
        plane_valid = np.asarray(valid_mask, dtype=bool) & np.isfinite(positions).all(axis=1)
        centroid, rms = _centroid_and_rms(positions, plane_valid)
        positions_by_plane.append(tuple(tuple(float(v) for v in row) for row in positions))
        valid_by_plane.append(tuple(bool(v) for v in plane_valid))
        centroids.append(centroid)
        rms_values.append(rms)
    return MultiPlaneTraceResult(
        plane_z_mm=planes,
        positions_by_plane_mm=tuple(positions_by_plane),
        valid_mask_by_plane=tuple(valid_by_plane),
        centroid_xy_by_plane_mm=tuple(centroids),
        rms_radius_by_plane_mm=tuple(float(v) for v in rms_values),
    )


def estimate_raytrace_memory_plan(
    *, ray_count: int, surface_count: int, batch_size: int | None = None,
    memory_budget_mib: float = 128.0, bytes_per_float: int = 8,
) -> RayTraceMemoryPlan:
    ray_count = max(0, int(ray_count))
    surface_count = max(1, int(surface_count))
    floats_per_ray_state = 8
    bytes_per_ray_state = int(floats_per_ray_state * bytes_per_float)
    estimated_state_bytes = int(ray_count * surface_count * bytes_per_ray_state)
    estimated_state_mib = float(estimated_state_bytes / (1024.0 * 1024.0))
    budget_bytes = max(1.0, float(memory_budget_mib) * 1024.0 * 1024.0)
    recommended_batch_size = max(1, int(budget_bytes // (surface_count * bytes_per_ray_state)))
    if ray_count:
        recommended_batch_size = min(recommended_batch_size, ray_count)
    if batch_size is None:
        batch_size = recommended_batch_size
    batch_size = max(1, int(batch_size))
    batch_count = int(math.ceil(ray_count / batch_size)) if ray_count else 0
    return RayTraceMemoryPlan(
        ray_count, surface_count, batch_size, batch_count, bytes_per_ray_state,
        estimated_state_bytes, estimated_state_mib, recommended_batch_size,
    )


def _centroid_and_rms(positions: np.ndarray, valid_mask: np.ndarray) -> tuple[tuple[float, float], float]:
    if positions.size == 0 or not np.any(valid_mask):
        return (0.0, 0.0), 0.0
    xy = positions[np.asarray(valid_mask, dtype=bool)][:, [X_INDEX, Y_INDEX]]
    centroid = np.mean(xy, axis=0)
    radius = np.sqrt(np.sum((xy - centroid[None, :]) ** 2, axis=1))
    rms = float(np.sqrt(np.mean(radius**2))) if radius.size else 0.0
    return (float(centroid[0]), float(centroid[1])), rms


def _as_bool_mask(value: Any, length: int) -> np.ndarray:
    if value is None:
        return np.ones(int(length), dtype=bool)
    arr = np.asarray(value, dtype=bool).reshape(-1)
    if arr.size == length:
        return arr
    if arr.size > length:
        return arr[:length]
    out = np.zeros(int(length), dtype=bool)
    out[: arr.size] = arr
    return out


def _as_2d_float_array(value: Any, *, columns: int) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.size == 0:
        return np.zeros((0, columns), dtype=float)
    if arr.ndim == 1:
        if arr.size % columns != 0:
            raise ValueError(f"array length {arr.size} is not divisible by {columns}")
        arr = arr.reshape((-1, columns))
    if arr.shape[1] != columns:
        raise ValueError(f"expected {columns} columns, got {arr.shape[1]}")
    return arr


def _normalize_reason(reason: Any) -> str:
    text = str(reason or "unknown").strip().lower().replace(" ", "_")
    text = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "unknown"


__all__ = [
    "MultiPlaneTraceResult", "RayTraceEngineeringReport", "RayTraceMemoryPlan",
    "build_engineering_trace_report", "build_multi_plane_trace",
    "classify_blocked_reasons", "estimate_raytrace_memory_plan",
    "summarize_surface_valid_counts",
]
