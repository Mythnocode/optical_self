# 场曲与像散分析。
# 分别计算子午焦面和弧矢焦面随视场的变化，并给出两者焦面差、实际像高和畸变曲线。
from __future__ import annotations

from typing import Any
import math

import numpy as np

from optical_core.coordinates import X_INDEX, Y_INDEX
from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.physics.geometric.analyses._native_helpers import (
    AnalysisResult,
    pair_focus_z,
    trace_custom_rays,
)
from optical_core.physics.geometric.analyses.first_order import effective_focal_length_mm, paraxial_focus_position_mm


def _field_components(field_abs_deg: float, field_x_deg: float, field_y_deg: float) -> tuple[float, float]:
    norm = math.hypot(float(field_x_deg), float(field_y_deg))
    if norm <= 1.0e-12:
        return float(field_abs_deg), 0.0
    return float(field_abs_deg) * float(field_x_deg) / norm, float(field_abs_deg) * float(field_y_deg) / norm


def field_curvature_distortion_profiles(
    system: SequentialOpticalSystem,
    *,
    field_x_deg: float = 0.2,
    field_y_deg: float = 0.0,
    wavelength_nm: float | None = None,
    field_samples: int = 9,
    pupil_radius_mm: float | None = None,
) -> dict[str, Any]:
    wl = float(wavelength_nm or system.wavelength_nm)
    radius = float(system.pupil_radius_mm if pupil_radius_mm is None else pupil_radius_mm)
    edge_field = float(math.hypot(field_x_deg, field_y_deg))
    field_note = "使用当前视场"
    if edge_field <= 1.0e-12:
        edge_field = 0.2
        field_x_deg, field_y_deg = 0.2, 0.0
        field_note = "当前轴上视场，场曲/畸变使用 0.2° 演示视场"
    count = max(5, int(field_samples))
    field_grid = np.linspace(0.0, edge_field, count)
    tangential = np.full(count, np.nan, dtype=float)
    sagittal = np.full(count, np.nan, dtype=float)
    image_height = np.full(count, np.nan, dtype=float)
    distortion = np.full(count, np.nan, dtype=float)
    paraxial_focus_z = paraxial_focus_position_mm(system, wl)
    efl = effective_focal_length_mm(system, wl) if system.surfaces else float("inf")

    for i, field_abs in enumerate(field_grid):
        fx_deg, fy_deg = _field_components(float(field_abs), field_x_deg, field_y_deg)
        tangential_trace = trace_custom_rays(
            system, [-radius, radius], [0.0, 0.0], wavelength_nm=wl,
            field_x_deg=fx_deg, field_y_deg=fy_deg, propagate_to_image=False,
        )
        sagittal_trace = trace_custom_rays(
            system, [0.0, 0.0], [-radius, radius], wavelength_nm=wl,
            field_x_deg=fx_deg, field_y_deg=fy_deg, propagate_to_image=False,
        )
        chief_trace = trace_custom_rays(
            system, [0.0], [0.0], wavelength_nm=wl,
            field_x_deg=fx_deg, field_y_deg=fy_deg, propagate_to_image=True,
        )
        tp = np.asarray(tangential_trace.final_positions_mm, dtype=float)
        td = np.asarray(tangential_trace.final_directions, dtype=float)
        sp = np.asarray(sagittal_trace.final_positions_mm, dtype=float)
        sd = np.asarray(sagittal_trace.final_directions, dtype=float)
        tv = np.asarray(tangential_trace.valid_mask, dtype=bool)
        sv = np.asarray(sagittal_trace.valid_mask, dtype=bool)
        if np.all(tv):
            focus_z = pair_focus_z(tp[0], td[0], tp[1], td[1], transverse_axis=X_INDEX)
            tangential[i] = (focus_z - paraxial_focus_z) * 1000.0 if np.isfinite(focus_z) else np.nan
        if np.all(sv):
            focus_z = pair_focus_z(sp[0], sd[0], sp[1], sd[1], transverse_axis=Y_INDEX)
            sagittal[i] = (focus_z - paraxial_focus_z) * 1000.0 if np.isfinite(focus_z) else np.nan
        valid = bool(np.asarray(chief_trace.valid_mask, dtype=bool)[0])
        point = np.asarray(chief_trace.final_positions_mm[0], dtype=float)
        if valid and np.isfinite(point).all():
            image_height[i] = math.hypot(float(point[X_INDEX]), float(point[Y_INDEX])) * 1000.0
            ideal = abs(float(efl) * math.tan(math.radians(float(field_abs)))) * 1000.0 if np.isfinite(efl) else np.nan
            distortion[i] = 0.0 if i == 0 or not np.isfinite(ideal) or abs(ideal) < 1.0e-12 else 100.0 * (image_height[i] - ideal) / ideal

    return {
        "field_grid_deg": field_grid,
        "tangential_focus_um": tangential,
        "sagittal_focus_um": sagittal,
        "distortion_percent": distortion,
        "image_height_um": image_height,
        "field_used_deg": float(edge_field),
        "field_note": field_note,
        "paraxial_focus_z_mm": float(paraxial_focus_z),
        "marginal_radius_mm": float(radius),
    }


def evaluate_field_curvature(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> AnalysisResult:
    opts = dict(options or {})
    raw = field_curvature_distortion_profiles(
        system,
        field_x_deg=float(opts.get("field_x_deg", 0.2)),
        field_y_deg=float(opts.get("field_y_deg", 0.0)),
        wavelength_nm=opts.get("wavelength_nm", system.wavelength_nm),
        field_samples=int(opts.get("field_samples", 9)),
        pupil_radius_mm=opts.get("pupil_radius_mm"),
    )
    tan = np.asarray(raw["tangential_focus_um"], dtype=float)
    sag = np.asarray(raw["sagittal_focus_um"], dtype=float)
    metrics = {
        "field_curvature_tangential_edge_um": float(tan[-1]) if tan.size else float("nan"),
        "field_curvature_sagittal_edge_um": float(sag[-1]) if sag.size else float("nan"),
        "field_curvature_astigmatic_difference_edge_um": float(tan[-1] - sag[-1]) if tan.size and sag.size else float("nan"),
        "field_curvature_field_used_deg": float(raw["field_used_deg"]),
    }
    arrays = {key: np.asarray(raw[key]).tolist() for key in ("field_grid_deg", "tangential_focus_um", "sagittal_focus_um", "image_height_um", "distortion_percent")}
    return AnalysisResult(metrics=metrics, arrays=arrays, metadata={"field_curvature_done": True, "field_note": raw["field_note"], "optical_axis": "+z"})


__all__ = ["evaluate_field_curvature", "field_curvature_distortion_profiles"]
