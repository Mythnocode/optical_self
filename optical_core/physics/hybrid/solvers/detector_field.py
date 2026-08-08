
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.solvers.cartesian_pupil_propagation import (
    solve_cartesian_pupil_propagation,
)
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions


@dataclass(frozen=True, slots=True)
class DetectorFieldOptions:


    wavelength_nm: float = 550.0
    grid_size: int = 129
    field_extent_mm: float | None = None
    size_x_mm: float | None = None
    size_y_mm: float | None = None
    axial_offset_z_mm: float = 0.0
    propagation_distance_mm: float | None = None
    propagation_model: str = "angular_spectrum"
    normalize: bool = False


@dataclass(slots=True)
class DetectorFieldResult:
    field: ScalarField2D
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _centroid_and_rms(field: ScalarField2D) -> tuple[float, float, float, float, float]:
    intensity = np.asarray(np.abs(field.values) ** 2, dtype=float)
    total = float(np.sum(intensity))
    if total <= 0.0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    x_axis = np.asarray(field.grid.x_mm, dtype=float)
    y_axis = np.asarray(field.grid.y_mm, dtype=float)
    xx, yy = np.meshgrid(x_axis, y_axis, indexing="xy")
    cx = float(np.sum(xx * intensity) / total)
    cy = float(np.sum(yy * intensity) / total)
    rms_x = float(np.sqrt(max(np.sum(((xx - cx) ** 2) * intensity) / total, 0.0)))
    rms_y = float(np.sqrt(max(np.sum(((yy - cy) ** 2) * intensity) / total, 0.0)))
    rms_r = float(
        np.sqrt(max(np.sum((((xx - cx) ** 2) + ((yy - cy) ** 2)) * intensity) / total, 0.0))
    )
    return cx, cy, rms_x, rms_y, rms_r


def solve_detector_field(trace: TraceBundle, options: DetectorFieldOptions) -> DetectorFieldResult:
    extent_x = options.field_extent_mm
    extent_y = options.field_extent_mm
    if options.size_x_mm is not None:
        extent_x = 0.5 * float(options.size_x_mm)
    if options.size_y_mm is not None:
        extent_y = 0.5 * float(options.size_y_mm)

    formal = solve_cartesian_pupil_propagation(
        trace,
        CouplingOptions(
            wavelength_nm=float(options.wavelength_nm),
            grid_size=int(options.grid_size),
            pupil_grid_size=int(options.grid_size),
            output_grid_size=int(options.grid_size),
            output_extent_x_mm=extent_x,
            output_extent_y_mm=extent_y,
            propagation_distance_mm=options.propagation_distance_mm,
            receiver_axial_offset_z_mm=float(options.axial_offset_z_mm),
            propagation_model=str(options.propagation_model),
            auto_expand_output=False,
            sampling_convergence_enabled=False,
            include_breakdown=False,
        ),
    )
    field_obj = formal.field
    intensity = np.asarray(np.abs(field_obj.values) ** 2, dtype=float)
    cx, cy, rms_x, rms_y, rms_r = _centroid_and_rms(field_obj)
    valid = np.asarray(trace.valid_mask, dtype=bool)
    metrics = {
        **dict(formal.metrics),
        "detector_total_power_a.u.": float(field_obj.integrated_power),
        "detector_peak_intensity_a.u.": float(np.max(intensity)) if intensity.size else 0.0,
        "detector_mean_intensity_a.u.": float(np.mean(intensity)) if intensity.size else 0.0,
        "detector_centroid_x_mm": cx,
        "detector_centroid_y_mm": cy,
        "detector_rms_x_mm": rms_x,
        "detector_rms_y_mm": rms_y,
        "detector_rms_radius_mm": rms_r,
        "detector_valid_ray_count": int(np.count_nonzero(valid)),
        "detector_total_ray_count": int(valid.size),
    }
    arrays = {
        **dict(formal.arrays),
        "detector_intensity_a.u.": intensity.tolist(),
        "detector_phase_rad": np.angle(field_obj.values).tolist(),
        "detector_grid_x_mm": field_obj.grid.x_mm.tolist(),
        "detector_grid_y_mm": field_obj.grid.y_mm.tolist(),
    }
    return DetectorFieldResult(
        field=field_obj,
        metrics=metrics,
        arrays=arrays,
        warnings=list(formal.warnings),
        metadata={
            **dict(formal.metadata),
            "solver": "detector_field",
            "formal_complex_field_chain": "cartesian_exit_pupil",
            "independent_ray_deposition_removed": True,
        },
    )


__all__ = ["DetectorFieldOptions", "DetectorFieldResult", "solve_detector_field"]
