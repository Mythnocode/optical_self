from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.solvers.propagation_options import PropagationOptions
from optical_core.quality.aliasing_check import audit_field_edge_energy
from optical_core.quality.energy_check import audit_field_energy
from optical_core.quality.sampling_check import audit_uniform_grid_sampling
from optical_core.physics.wave.solvers.scalar_diffraction import field_from_aperture_options, propagate_scalar_field


@dataclass(slots=True)
class DiffractionAnalysisResult:
    field: ScalarField2D
    intensity: np.ndarray
    phase_rad: np.ndarray
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _field_arrays(field: ScalarField2D, *, prefix: str = "diffraction") -> dict[str, Any]:
    intensity = np.abs(field.values) ** 2
    return {
        f"{prefix}_x_mm": field.grid.x_mm.tolist(),
        f"{prefix}_y_mm": field.grid.y_mm.tolist(),
        f"{prefix}_intensity": intensity.tolist(),
        f"{prefix}_phase_rad": np.angle(field.values).tolist(),
    }


def evaluate_diffraction(options: PropagationOptions, input_field: ScalarField2D | None = None) -> DiffractionAnalysisResult:


    options.validate()
    field = input_field if input_field is not None else field_from_aperture_options(options)
    output = propagate_scalar_field(field, options)
    intensity = np.abs(output.values) ** 2
    phase_rad = np.angle(output.values)
    total_power = float(np.sum(intensity) * abs(output.grid.dx_mm * output.grid.dy_mm))
    peak = float(np.max(intensity)) if intensity.size else 0.0

    sampling_audit = audit_uniform_grid_sampling(
        grid_size=options.grid_size,
        extent_mm=options.extent_mm,
        wavelength_nm=options.wavelength_nm,
        propagation_distance_mm=options.propagation_distance_mm,
        aperture_diameter_mm=options.aperture_diameter_mm,
    )
    energy_audit = audit_field_energy(field, output)
    aliasing_audit = audit_field_edge_energy(output)
    metrics = {
        "diffraction_peak_intensity": peak,
        "diffraction_total_power_a.u.": total_power,
        "diffraction_grid_size": int(output.values.shape[0]),
        "diffraction_z_mm": float(output.z_mm),
    }
    metrics.update(sampling_audit.metrics)
    metrics.update(energy_audit.metrics)
    metrics.update(aliasing_audit.metrics)
    warnings = [*sampling_audit.warnings, *energy_audit.warnings, *aliasing_audit.warnings]

    return DiffractionAnalysisResult(
        field=output,
        intensity=intensity,
        phase_rad=phase_rad,
        metrics=metrics,
        arrays=_field_arrays(output),
        warnings=warnings,
        metadata={
            "analysis": "diffraction",
            "method": options.method,
            "aperture_type": options.aperture_type,
            "wavelength_nm": float(options.wavelength_nm),
            "quality_audits": ["sampling", "energy", "aliasing"],
        },
    )
