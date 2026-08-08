# 几何分析的公共辅助工具。


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import math

import numpy as np

from optical_core.coordinates import X_INDEX, Y_INDEX, Z_INDEX
from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray_bundle import RayBundle
from optical_core.physics.geometric.solvers.batch_raytrace import trace_ray_batch
from optical_core.physics.geometric.solvers.trace_options import TraceOptions


F_LINE_NM = 486.1327
D_LINE_NM = 587.5618
C_LINE_NM = 656.2725


@dataclass(slots=True)
class AnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def finite_positive(value: Any, default: float, minimum: float = 1.0e-12) -> float:
    out = finite_float(value, default)
    return out if out > minimum else float(default)


def option_value(options: dict[str, Any] | None, key: str, default: Any) -> Any:
    return default if options is None else options.get(key, default)


def system_length_mm(system: SequentialOpticalSystem) -> float:
    if not system.surfaces:
        return 0.0
    vertices = system.surface_vertex_z_positions()
    return float(vertices[-1] + system.image_distance_mm)


def last_vertex_mm(system: SequentialOpticalSystem) -> float:
    if not system.surfaces:
        return 0.0
    return float(system.surface_vertex_z_positions()[-1])


def image_plane_z_mm(system: SequentialOpticalSystem) -> float:
    return last_vertex_mm(system) + float(system.image_distance_mm)


def field_direction(field_x_deg: float = 0.0, field_y_deg: float = 0.0) -> np.ndarray:
    dx = math.tan(math.radians(float(field_x_deg)))
    dy = math.tan(math.radians(float(field_y_deg)))
    vec = np.array([dx, dy, 1.0], dtype=float)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0.0 else np.array([0.0, 0.0, 1.0], dtype=float)


def make_ray_bundle(
    pupil_x_mm: Iterable[float],
    pupil_y_mm: Iterable[float],
    *,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    start_z_mm: float = -1.0e-6,
) -> RayBundle:
    x = np.asarray(list(pupil_x_mm), dtype=float).reshape(-1)
    y = np.asarray(list(pupil_y_mm), dtype=float).reshape(-1)
    if x.shape != y.shape:
        raise ValueError("pupil_x_mm 和 pupil_y_mm 必须长度一致。")
    positions = np.column_stack([x, y, np.full_like(x, float(start_z_mm))])
    direction = field_direction(field_x_deg, field_y_deg)
    directions = np.tile(direction.reshape(1, 3), (positions.shape[0], 1))
    return RayBundle.from_positions_and_directions(positions, directions)


def trace_custom_rays(
    system: SequentialOpticalSystem,
    pupil_x_mm: Iterable[float],
    pupil_y_mm: Iterable[float],
    *,
    wavelength_nm: float | None = None,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    propagate_to_image: bool = True,
    evaluate_apertures: bool = True,
) -> Any:
    wl = float(wavelength_nm or system.wavelength_nm)
    rays = make_ray_bundle(
        pupil_x_mm,
        pupil_y_mm,
        field_x_deg=field_x_deg,
        field_y_deg=field_y_deg,
    )
    options = TraceOptions(
        wavelength_nm=wl,
        pupil_sample_count=len(rays.valid_mask),
        record_surfaces=False,
        propagate_to_image=bool(propagate_to_image),
        evaluate_apertures=bool(evaluate_apertures),
    )
    return trace_ray_batch(system, rays, options)


def trace_single_terminal(
    system: SequentialOpticalSystem,
    pupil_x_mm: float,
    pupil_y_mm: float,
    *,
    wavelength_nm: float | None = None,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    propagate_to_image: bool = False,
) -> tuple[np.ndarray, np.ndarray, bool]:
    trace = trace_custom_rays(
        system,
        [pupil_x_mm],
        [pupil_y_mm],
        wavelength_nm=wavelength_nm,
        field_x_deg=field_x_deg,
        field_y_deg=field_y_deg,
        propagate_to_image=propagate_to_image,
    )
    return (
        np.asarray(trace.final_positions_mm[0], dtype=float),
        np.asarray(trace.final_directions[0], dtype=float),
        bool(np.asarray(trace.valid_mask, dtype=bool)[0]),
    )


def focus_z_from_terminal(point_mm: np.ndarray, direction: np.ndarray, transverse_axis: int = X_INDEX) -> float:


    p = np.asarray(point_mm, dtype=float)
    d = np.asarray(direction, dtype=float)
    if transverse_axis not in (X_INDEX, Y_INDEX):
        raise ValueError("transverse_axis must be X_INDEX or Y_INDEX")
    if abs(float(d[transverse_axis])) < 1.0e-14:
        return float("inf")
    return float(p[Z_INDEX] - p[transverse_axis] * d[Z_INDEX] / d[transverse_axis])


def pair_focus_z(
    p1: np.ndarray,
    d1: np.ndarray,
    p2: np.ndarray,
    d2: np.ndarray,
    *,
    transverse_axis: int,
) -> float:


    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    d1 = np.asarray(d1, dtype=float)
    d2 = np.asarray(d2, dtype=float)
    if transverse_axis not in (X_INDEX, Y_INDEX):
        raise ValueError("transverse_axis must be X_INDEX or Y_INDEX")
    if abs(d1[Z_INDEX]) < 1.0e-14 or abs(d2[Z_INDEX]) < 1.0e-14:
        return float("nan")
    s1 = d1[transverse_axis] / d1[Z_INDEX]
    s2 = d2[transverse_axis] / d2[Z_INDEX]
    denom = s1 - s2
    if abs(float(denom)) < 1.0e-14:
        return float("inf")
    return float(
        (p2[transverse_axis] - p1[transverse_axis]
         + s1 * p1[Z_INDEX] - s2 * p2[Z_INDEX]) / denom
    )


def project_to_z(point_mm: np.ndarray, direction: np.ndarray, target_z_mm: float) -> np.ndarray:
    p = np.asarray(point_mm, dtype=float)
    d = np.asarray(direction, dtype=float)
    if abs(float(d[Z_INDEX])) < 1.0e-14:
        return np.full(3, np.nan, dtype=float)
    t = (float(target_z_mm) - p[Z_INDEX]) / d[Z_INDEX]
    return p + t * d


def tolist_array(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [tolist_array(item) for item in value]
    if isinstance(value, dict):
        return {str(k): tolist_array(v) for k, v in value.items()}
    return value
