# 光线扇形图分析。

from __future__ import annotations

from typing import Any
import numpy as np

from optical_core.coordinates import X_INDEX, Y_INDEX
from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.physics.geometric.analyses._native_helpers import AnalysisResult, trace_custom_rays


def ray_fan_profiles(
    system: SequentialOpticalSystem,
    *,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    wavelength_nm: float | None = None,
    samples: int = 41,
    pupil_radius_mm: float | None = None,
) -> dict[str, Any]:
    wl = float(wavelength_nm or system.wavelength_nm)
    radius = float(system.pupil_radius_mm if pupil_radius_mm is None else pupil_radius_mm)
    count = max(5, int(samples))
    rho = np.linspace(-1.0, 1.0, count)
    chief = trace_custom_rays(system, [0.0], [0.0], wavelength_nm=wl, field_x_deg=field_x_deg, field_y_deg=field_y_deg, propagate_to_image=True)
    chief_pos = np.asarray(chief.final_positions_mm[0], dtype=float)
    chief_valid = bool(np.asarray(chief.valid_mask, dtype=bool)[0])
    x_fan_trace = trace_custom_rays(system, rho * radius, np.zeros_like(rho), wavelength_nm=wl, field_x_deg=field_x_deg, field_y_deg=field_y_deg, propagate_to_image=True)
    y_fan_trace = trace_custom_rays(system, np.zeros_like(rho), rho * radius, wavelength_nm=wl, field_x_deg=field_x_deg, field_y_deg=field_y_deg, propagate_to_image=True)
    x_pos = np.asarray(x_fan_trace.final_positions_mm, dtype=float)
    y_pos = np.asarray(y_fan_trace.final_positions_mm, dtype=float)
    x_valid = np.asarray(x_fan_trace.valid_mask, dtype=bool)
    y_valid = np.asarray(y_fan_trace.valid_mask, dtype=bool)
    x_ref = float(chief_pos[X_INDEX]) if chief_valid and np.isfinite(chief_pos).all() else 0.0
    y_ref = float(chief_pos[Y_INDEX]) if chief_valid and np.isfinite(chief_pos).all() else 0.0
    x_fan_um = np.full(count, np.nan)
    y_fan_um = np.full(count, np.nan)
    cross_xy_um = np.full(count, np.nan)
    cross_yx_um = np.full(count, np.nan)
    x_fan_um[x_valid] = (x_pos[x_valid, X_INDEX] - x_ref) * 1000.0
    cross_xy_um[x_valid] = (x_pos[x_valid, Y_INDEX] - y_ref) * 1000.0
    y_fan_um[y_valid] = (y_pos[y_valid, Y_INDEX] - y_ref) * 1000.0
    cross_yx_um[y_valid] = (y_pos[y_valid, X_INDEX] - x_ref) * 1000.0
    field_note = "使用当前视场" if abs(field_x_deg) > 1e-12 or abs(field_y_deg) > 1e-12 else "轴上视场"
    return {
        "rho": rho,
        "curves": [{"wavelength_nm": wl, "radius_mm": radius, "x_fan_um": x_fan_um, "y_fan_um": y_fan_um, "cross_xy_um": cross_xy_um, "cross_yx_um": cross_yx_um}],
        "field_x_deg": float(field_x_deg), "field_y_deg": float(field_y_deg), "field_note": field_note,
    }


def evaluate_ray_fan(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> AnalysisResult:
    opts = dict(options or {})
    raw = ray_fan_profiles(system, field_x_deg=float(opts.get("field_x_deg", 0.0)), field_y_deg=float(opts.get("field_y_deg", 0.0)), wavelength_nm=opts.get("wavelength_nm", system.wavelength_nm), samples=int(opts.get("samples", opts.get("fan_samples", 41))), pupil_radius_mm=opts.get("pupil_radius_mm"))
    curve = raw["curves"][0]
    arrays = {
        "ray_fan_rho": np.asarray(raw["rho"]).tolist(),
        "ray_fan_x_um": np.asarray(curve["x_fan_um"]).tolist(),
        "ray_fan_y_um": np.asarray(curve["y_fan_um"]).tolist(),
        "ray_fan_cross_xy_um": np.asarray(curve["cross_xy_um"]).tolist(),
        "ray_fan_cross_yx_um": np.asarray(curve["cross_yx_um"]).tolist(),
    }
    x = np.asarray(curve["x_fan_um"], dtype=float)
    y = np.asarray(curve["y_fan_um"], dtype=float)
    combined = np.concatenate([x[np.isfinite(x)], y[np.isfinite(y)]])
    metrics = {
        "ray_fan_max_abs_um": float(np.nanmax(np.abs(combined))) if combined.size else float("nan"),
        "ray_fan_rms_um": float(np.sqrt(np.nanmean(combined**2))) if combined.size else float("nan"),
        "ray_fan_field_x_deg": float(raw["field_x_deg"]), "ray_fan_field_y_deg": float(raw["field_y_deg"]),
    }
    return AnalysisResult(metrics=metrics, arrays=arrays, metadata={"ray_fan_done": True, "field_note": raw["field_note"], "optical_axis": "+z"})


__all__ = ["evaluate_ray_fan", "ray_fan_profiles"]
