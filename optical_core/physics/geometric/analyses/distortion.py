# 畸变分析入口。输出不同视场下的畸变百分比、边缘视场畸变、最大绝对畸变和实际像高。
from __future__ import annotations

from typing import Any
import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.physics.geometric.analyses._native_helpers import AnalysisResult
from optical_core.physics.geometric.analyses.field_curvature import field_curvature_distortion_profiles


def evaluate_distortion(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> AnalysisResult:
    opts = dict(options or {})
    raw = field_curvature_distortion_profiles(
        system,
        field_x_deg=float(opts.get("field_x_deg", 0.2)),
        field_y_deg=float(opts.get("field_y_deg", 0.0)),
        wavelength_nm=opts.get("wavelength_nm", system.wavelength_nm),
        field_samples=int(opts.get("field_samples", 9)),
        pupil_radius_mm=opts.get("pupil_radius_mm", None),
    )
    distortion = np.asarray(raw["distortion_percent"], dtype=float)
    finite = distortion[np.isfinite(distortion)]
    metrics = {
        "distortion_edge_percent": float(distortion[-1]) if distortion.size else float("nan"),
        "distortion_max_abs_percent": float(np.nanmax(np.abs(finite))) if finite.size else float("nan"),
        "distortion_field_used_deg": float(raw["field_used_deg"]),
    }
    arrays = {
        "distortion_field_grid_deg": np.asarray(raw["field_grid_deg"], dtype=float).tolist(),
        "distortion_percent": distortion.tolist(),
        "distortion_image_height_um": np.asarray(raw["image_height_um"], dtype=float).tolist(),
    }
    return AnalysisResult(metrics=metrics, arrays=arrays, metadata={"distortion_done": True, "field_note": raw["field_note"], "optical_axis": "+z"})


__all__ = ["evaluate_distortion"]
