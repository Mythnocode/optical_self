# 探测器平面分析。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.solvers.cartesian_pupil_propagation import solve_cartesian_pupil_propagation
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions


@dataclass(frozen=True, slots=True)
class DetectorAnalysisOptions:
    wavelength_nm: float = 550.0
    grid_size: int = 129
    field_extent_mm: float | None = None
    size_x_mm: float | None = None
    size_y_mm: float | None = None
    normalize: bool = True
    propagation_model: str = "angular_spectrum"
    propagation_distance_mm: float | None = None
    axial_offset_z_mm: float = 0.0


@dataclass(slots=True)
class DetectorAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _moments(values: np.ndarray, x_axis: np.ndarray, y_axis: np.ndarray) -> tuple[float, float, float, float, float]:
    intensity = np.abs(values) ** 2
    total = float(np.sum(intensity))
    if total <= 0.0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    xx, yy = np.meshgrid(x_axis, y_axis, indexing="xy")
    cx = float(np.sum(xx * intensity) / total)
    cy = float(np.sum(yy * intensity) / total)
    vx = float(np.sum((xx - cx) ** 2 * intensity) / total)
    vy = float(np.sum((yy - cy) ** 2 * intensity) / total)
    return cx, cy, float(np.sqrt(max(vx, 0.0))), float(np.sqrt(max(vy, 0.0))), float(np.sqrt(max(vx + vy, 0.0)))


def evaluate_detector(trace: TraceBundle, options: DetectorAnalysisOptions | dict[str, Any] | None = None) -> DetectorAnalysisResult:
    if isinstance(options, DetectorAnalysisOptions):
        opts = options
    else:
        raw = dict(options or {})
        opts = DetectorAnalysisOptions(
            wavelength_nm=float(raw.get("wavelength_nm", 550.0)),
            grid_size=int(raw.get("grid_size", raw.get("pixels", 129))),
            field_extent_mm=raw.get("field_extent_mm", raw.get("extent_mm")),
            size_x_mm=raw.get("size_x_mm"),
            size_y_mm=raw.get("size_y_mm"),
            normalize=bool(raw.get("normalize", True)),
            propagation_model=str(raw.get("propagation_model", "angular_spectrum")),
            propagation_distance_mm=raw.get("propagation_distance_mm"),
            axial_offset_z_mm=float(raw.get("axial_offset_z_mm", 0.0) or 0.0),
        )
    extent_x = 0.5 * float(opts.size_x_mm) if opts.size_x_mm else opts.field_extent_mm
    extent_y = 0.5 * float(opts.size_y_mm) if opts.size_y_mm else opts.field_extent_mm
    propagated = solve_cartesian_pupil_propagation(
        trace,
        CouplingOptions(
            wavelength_nm=opts.wavelength_nm,
            grid_size=opts.grid_size,
            field_extent_mm=opts.field_extent_mm,
            output_grid_size=opts.grid_size,
            output_extent_x_mm=extent_x,
            output_extent_y_mm=extent_y,
            propagation_model=opts.propagation_model,
            propagation_distance_mm=opts.propagation_distance_mm,
            receiver_axial_offset_z_mm=opts.axial_offset_z_mm,
            sampling_convergence_enabled=False,
            include_breakdown=False,
            include_convergence=False,
        ),
    )
    field_obj = propagated.field
    intensity = np.abs(field_obj.values) ** 2
    cx, cy, rms_x, rms_y, rms_r = _moments(field_obj.values, field_obj.grid.x_mm, field_obj.grid.y_mm)
    metrics = {
        **propagated.metrics,
        "detector_total_power_a.u.": float(field_obj.integrated_power),
        "detector_peak_intensity_a.u.": float(np.max(intensity)) if intensity.size else 0.0,
        "detector_mean_intensity_a.u.": float(np.mean(intensity)) if intensity.size else 0.0,
        "detector_centroid_x_mm": cx,
        "detector_centroid_y_mm": cy,
        "detector_rms_x_mm": rms_x,
        "detector_rms_y_mm": rms_y,
        "detector_rms_radius_mm": rms_r,
    }
    arrays = {
        **propagated.arrays,
        "detector_intensity_a.u.": intensity.tolist(),
        "detector_phase_rad": np.angle(field_obj.values).tolist(),
        "detector_grid_x_mm": field_obj.grid.x_mm.tolist(),
        "detector_grid_y_mm": field_obj.grid.y_mm.tolist(),
    }
    return DetectorAnalysisResult(
        metrics=metrics,
        arrays=arrays,
        warnings=list(propagated.warnings),
        metadata={
            "analysis": "detector",
            **propagated.metadata,
            "field_chain": "cartesian_exit_pupil_to_registered_propagator",
            "ray_deposition_used": False,
        },
    )
