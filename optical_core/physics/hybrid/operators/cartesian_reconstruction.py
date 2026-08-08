# 探测器截面。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import FieldNormalization, PowerUnit, ScalarField2D


@dataclass(slots=True)
class CartesianReconstructionResult:
    field: ScalarField2D
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def reconstruct_cartesian_field(
    field: ScalarField2D,
    *,
    normalize_power: bool = False,
) -> CartesianReconstructionResult:


    values = np.asarray(field.values, dtype=np.complex128)
    if normalize_power:
        power = float(np.sum(np.abs(values) ** 2) * abs(field.grid.dx_mm * field.grid.dy_mm))
        if power > 0.0:
            values = values / np.sqrt(power)
            field = ScalarField2D(
                values=values,
                grid=field.grid,
                wavelength_nm=field.wavelength_nm,
                refractive_index=field.refractive_index,
                z_mm=field.z_mm,
                integrated_power=1.0,
                power_unit=PowerUnit.ARBITRARY,
                normalization=FieldNormalization.UNIT_POWER,
            )

    amplitude = np.abs(values)
    intensity = amplitude**2
    phase = np.angle(values)

    return CartesianReconstructionResult(
        field=field,
        metrics={
            "cartesian_grid_size_x": int(values.shape[1]) if values.ndim == 2 else 0,
            "cartesian_grid_size_y": int(values.shape[0]) if values.ndim == 2 else 0,
            "cartesian_power_a.u.": float(field.integrated_power),
            "cartesian_peak_intensity": float(np.max(intensity)) if intensity.size else 0.0,
        },
        arrays={
            "cartesian_amplitude": amplitude.tolist(),
            "cartesian_intensity": intensity.tolist(),
            "cartesian_phase_rad": phase.tolist(),
            "cartesian_grid_x_mm": field.grid.x_mm.tolist(),
            "cartesian_grid_y_mm": field.grid.y_mm.tolist(),
        },
        metadata={"operator": "reconstruct_cartesian_field", "coordinate_system": "right-handed XYZ; optical axis +z"},
    )
