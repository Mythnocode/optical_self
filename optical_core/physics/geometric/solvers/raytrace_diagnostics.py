# 追迹诊断。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class RaySegmentState:
    surface_index: int
    positions_mm: list[list[float]]
    directions: list[list[float]]
    valid_mask: list[bool]
    normal_vectors: list[list[float]] = field(default_factory=list)
    incidence_angle_deg: list[float] = field(default_factory=list)
    refraction_angle_deg: list[float] = field(default_factory=list)
    blocked_reason: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RayAimingContext:

    object_na_x: float
    object_na_y: float
    pupil_radius_mm: float
    field_x_deg: float = 0.0
    field_y_deg: float = 0.0


@dataclass(frozen=True, slots=True)
class RayTraceDiagnosticReport:
    segment_count: int
    ray_count: int
    surface_valid_counts: dict[int, int]
    blocked_reason_counts: dict[str, int]
    final_valid_count: int
    final_rms_radius_mm: float
    memory_plan: dict[str, int]
    segments: list[RaySegmentState]

    def as_metrics(self) -> dict[str, Any]:
        return {
            "trace_segment_count": self.segment_count,
            "trace_ray_count": self.ray_count,
            "trace_final_valid_count": self.final_valid_count,
            "trace_final_rms_radius_mm": self.final_rms_radius_mm,
            "trace_memory_estimated_state_bytes": self.memory_plan.get("estimated_state_bytes", 0),
            "trace_memory_recommended_batch_size": self.memory_plan.get("recommended_batch_size", self.ray_count),
        }


def build_segment_history(trace: Any) -> list[RaySegmentState]:


    positions = _read(trace, "surface_positions_mm", "positions_by_surface_mm", default=None)
    directions = _read(trace, "surface_directions", "directions_by_surface", default=None)
    valid = _read(trace, "surface_valid_mask", "valid_by_surface", default=None)

    if positions is not None:
        pos_arr = np.asarray(positions, dtype=float)
        if pos_arr.ndim == 2:
            pos_arr = pos_arr[None, :, :]
        dir_arr = np.asarray(directions if directions is not None else np.zeros_like(pos_arr), dtype=float)
        if dir_arr.ndim == 2:
            dir_arr = dir_arr[None, :, :]
        valid_arr = _valid_by_surface(valid, pos_arr.shape[0], pos_arr.shape[1])
        return [
            RaySegmentState(
                surface_index=i,
                positions_mm=pos_arr[i].tolist(),
                directions=dir_arr[min(i, dir_arr.shape[0] - 1)].tolist(),
                valid_mask=valid_arr[i].tolist(),
                blocked_reason=_blocked_reasons_from_mask(valid_arr[i]),
            )
            for i in range(pos_arr.shape[0])
        ]

    final_positions = np.asarray(_read(trace, "final_positions_mm", default=[]), dtype=float)
    final_directions = np.asarray(_read(trace, "final_directions", default=np.zeros_like(final_positions)), dtype=float)
    if final_positions.ndim == 1 and final_positions.size:
        final_positions = final_positions.reshape(1, -1)
    if final_directions.ndim == 1 and final_directions.size:
        final_directions = final_directions.reshape(1, -1)
    ray_count = int(final_positions.shape[0]) if final_positions.ndim == 2 else 0
    valid_mask = np.asarray(_read(trace, "valid_mask", default=np.ones(ray_count, dtype=bool)), dtype=bool)
    return [
        RaySegmentState(
            surface_index=0,
            positions_mm=final_positions.tolist() if ray_count else [],
            directions=final_directions.tolist() if final_directions.size else [[0.0, 0.0, 1.0] for _ in range(ray_count)],
            valid_mask=valid_mask.tolist(),
            blocked_reason=_blocked_reasons_from_mask(valid_mask),
        )
    ]


def build_trace_diagnostic_report(trace: Any, *, memory_budget_bytes: int = 64_000_000) -> RayTraceDiagnosticReport:
    segments = build_segment_history(trace)
    final_positions = np.asarray(_read(trace, "final_positions_mm", default=[]), dtype=float)
    if final_positions.ndim == 1 and final_positions.size:
        final_positions = final_positions.reshape(1, -1)
    ray_count = int(final_positions.shape[0]) if final_positions.ndim == 2 else _segment_ray_count(segments)
    valid_mask = np.asarray(_read(trace, "valid_mask", default=[]), dtype=bool)
    if valid_mask.size == 0 and segments:
        valid_mask = np.asarray(segments[-1].valid_mask, dtype=bool)
    final_valid = int(np.count_nonzero(valid_mask)) if valid_mask.size else ray_count
    rms = _rms_radius(final_positions, valid_mask) if final_positions.size else 0.0
    surface_counts = summarize_surface_valid_counts(segments)
    blocked = classify_blocked_reasons(segments)
    memory_plan = estimate_raytrace_memory_plan(ray_count=ray_count, surface_count=max(1, len(segments)), memory_budget_bytes=memory_budget_bytes)
    return RayTraceDiagnosticReport(
        segment_count=len(segments),
        ray_count=ray_count,
        surface_valid_counts=surface_counts,
        blocked_reason_counts=blocked,
        final_valid_count=final_valid,
        final_rms_radius_mm=float(rms),
        memory_plan=memory_plan,
        segments=segments,
    )


def summarize_surface_valid_counts(segments: Sequence[RaySegmentState]) -> dict[int, int]:
    return {int(seg.surface_index): int(np.count_nonzero(np.asarray(seg.valid_mask, dtype=bool))) for seg in segments}


def classify_blocked_reasons(segments: Sequence[RaySegmentState]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for seg in segments:
        reasons = seg.blocked_reason or _blocked_reasons_from_mask(np.asarray(seg.valid_mask, dtype=bool))
        for reason in reasons:
            key = str(reason or "valid")
            counts[key] = counts.get(key, 0) + 1
    return counts


def estimate_raytrace_memory_plan(
    *,
    ray_count: int,
    surface_count: int,
    state_components: int = 8,
    dtype_bytes: int = 8,
    memory_budget_bytes: int = 64_000_000,
) -> dict[str, int]:
    ray_count = max(0, int(ray_count))
    surface_count = max(1, int(surface_count))
    bytes_per_ray = max(1, int(surface_count * state_components * dtype_bytes))
    estimated = int(ray_count * bytes_per_ray)
    recommended = max(1, int(memory_budget_bytes // bytes_per_ray))
    return {
        "ray_count": ray_count,
        "surface_count": surface_count,
        "bytes_per_ray": bytes_per_ray,
        "estimated_state_bytes": estimated,
        "memory_budget_bytes": int(memory_budget_bytes),
        "recommended_batch_size": min(ray_count, recommended) if ray_count else recommended,
        "estimated_batches": int(np.ceil(ray_count / recommended)) if ray_count and recommended else 0,
    }


def ray_aiming_coordinates(context: RayAimingContext, sample_count: int = 5) -> dict[str, Any]:

    sample_count = max(1, int(sample_count))
    x = np.linspace(-context.pupil_radius_mm, context.pupil_radius_mm, sample_count)
    y = np.linspace(-context.pupil_radius_mm, context.pupil_radius_mm, sample_count)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    rr = np.sqrt(xx * xx + yy * yy)
    mask = rr <= float(context.pupil_radius_mm) + 1e-12
    field_x = np.tan(np.deg2rad(context.field_x_deg))
    field_y = np.tan(np.deg2rad(context.field_y_deg))
    directions = np.column_stack([
        np.full(np.count_nonzero(mask), field_x),
        np.full(np.count_nonzero(mask), field_y),
        np.ones(np.count_nonzero(mask)),
    ])
    directions = directions / np.linalg.norm(directions, axis=1, keepdims=True)
    return {
        "aim_x_mm": xx[mask].tolist(),
        "aim_y_mm": yy[mask].tolist(),
        "direction_cosines": directions.tolist(),
        "sample_count": int(np.count_nonzero(mask)),
    }


def _valid_by_surface(valid: Any, surfaces: int, rays: int) -> np.ndarray:
    if valid is None:
        return np.ones((surfaces, rays), dtype=bool)
    arr = np.asarray(valid, dtype=bool)
    if arr.ndim == 1:
        return np.tile(arr[None, :], (surfaces, 1))
    if arr.shape[0] != surfaces:
        arr = np.resize(arr, (surfaces, rays))
    return arr


def _blocked_reasons_from_mask(mask: np.ndarray) -> list[str]:
    return ["valid" if bool(v) else "blocked_or_missed" for v in np.asarray(mask, dtype=bool)]


def _rms_radius(positions: np.ndarray, valid_mask: np.ndarray | None = None) -> float:
    if positions.ndim != 2 or positions.shape[0] == 0:
        return 0.0
    pts = positions
    if valid_mask is not None and valid_mask.size == positions.shape[0]:
        pts = positions[np.asarray(valid_mask, dtype=bool)]
    if pts.size == 0:
        return 0.0
    xy = pts[:, :2]
    center = np.mean(xy, axis=0)
    radii2 = np.sum((xy - center) ** 2, axis=1)
    return float(np.sqrt(np.mean(radii2)))


def _segment_ray_count(segments: Sequence[RaySegmentState]) -> int:
    if not segments:
        return 0
    return len(segments[-1].valid_mask)


def _read(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


__all__ = [
    "RaySegmentState",
    "RayAimingContext",
    "RayTraceDiagnosticReport",
    "build_segment_history",
    "build_trace_diagnostic_report",
    "summarize_surface_valid_counts",
    "classify_blocked_reasons",
    "estimate_raytrace_memory_plan",
    "ray_aiming_coordinates",
]
