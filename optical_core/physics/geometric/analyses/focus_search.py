# 最佳焦面搜索。

from __future__ import annotations

from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.geometric.solvers.focus_search import (
    fit_best_focus_continuous,
    rms_radius_at_plane,
)


def evaluate_focus_search(trace: TraceBundle, options: dict[str, Any] | None = None) -> dict[str, Any]:


    opts = dict(options or {})
    if "z_candidates_mm" in opts:
        candidates = np.asarray(opts["z_candidates_mm"], dtype=float)
    else:
        center = float(opts.get("center_z_mm", _default_center_z(trace)))
        span = float(opts.get("span_mm", 2.0))
        sample_count = max(3, int(opts.get("sample_count", 41)))
        candidates = np.linspace(center - 0.5 * span, center + 0.5 * span, sample_count)

    values = np.asarray([rms_radius_at_plane(trace, float(z)) for z in candidates], dtype=float)
    fitted = fit_best_focus_continuous(
        candidates,
        values,
        neighbor_count=int(opts.get("fit_neighbor_count", 5)),
    )
    best_z = float(fitted["best_focus_z_mm"])
    best_rms_mm = float(fitted["best_focus_rms_radius_mm"])

    wavelength_nm = float(opts.get("wavelength_nm", 550.0))
    strehl = _strehl_from_rms_spot(best_rms_mm, wavelength_nm)
    return {
        "metrics": {
            "best_focus_z_mm": best_z,
            "best_focus_rms_radius_mm": best_rms_mm,
            "best_focus_rms_radius_um": best_rms_mm * 1000.0 if np.isfinite(best_rms_mm) else float("nan"),
            "best_focus_candidate_count": float(candidates.size),
            "best_focus_strehl_estimate": strehl,
            "best_focus_fit_success": bool(fitted.get("fit_success", False)),
            "best_focus_fit_point_count": float(fitted.get("fit_point_count", 0)),
            "best_focus_sampled_z_mm": fitted.get("sampled_minimum_z_mm", best_z),
            "best_focus_sampled_rms_radius_um": float(
                fitted.get("sampled_minimum_rms_radius_mm", best_rms_mm)
            ) * 1000.0,
            "best_focus_minimum_at_scan_boundary": bool(
                fitted.get("minimum_at_scan_boundary", False)
            ),
        },
        "arrays": {
            "focus_z_candidates_mm": candidates.tolist(),
            "focus_rms_radius_um": (values * 1000.0).tolist(),
        },
        "metadata": {
            "focus_axis": "+z",
            "focus_metric": "common_weighted_rms_spot_radius",
            "focus_fit": "local_quadratic_fit_of_rms_squared",
            "strehl_model": "engineering estimate only",
        },
    }


def _default_center_z(trace: TraceBundle) -> float:
    positions = np.asarray(getattr(trace, "final_positions_mm", []), dtype=float)
    valid = np.asarray(getattr(trace, "valid_mask", []), dtype=bool)
    if positions.ndim == 2 and positions.shape[1] >= 3 and valid.size == positions.shape[0] and np.any(valid):
        value = float(np.nanmean(positions[valid, 2]))
        if np.isfinite(value):
            return value
    return 0.0


def _strehl_from_rms_spot(rms_radius_mm: float, wavelength_nm: float) -> float:
    if not np.isfinite(rms_radius_mm):
        return 0.0
    wavelength_mm = max(float(wavelength_nm) * 1.0e-6, 1.0e-15)
    ratio = max(0.0, float(rms_radius_mm)) / wavelength_mm
    return float(np.clip(np.exp(-((2.0 * np.pi * ratio) ** 2)), 0.0, 1.0))
