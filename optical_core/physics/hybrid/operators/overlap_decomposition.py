
# 将复场耦合分解为强度匹配和相位匹配两部分
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class OverlapDecomposition:
    complex_overlap: complex
    complex_efficiency: float
    intensity_only_efficiency: float
    phase_matching_efficiency: float
    field_power: float
    mode_power: float


def decompose_scalar_overlap(
    field: ScalarField2D,
    mode: ScalarField2D,
) -> OverlapDecomposition:
    if field.values.shape != mode.values.shape:
        raise ValueError("field and mode shapes must match")
    if not np.array_equal(field.grid.x_mm, mode.grid.x_mm) or not np.array_equal(
        field.grid.y_mm, mode.grid.y_mm
    ):
        raise ValueError("field and mode must use identical coordinates")
    area = abs(float(field.grid.dx_mm) * float(field.grid.dy_mm))
    field_values = np.asarray(field.values, dtype=np.complex128)
    mode_values = np.asarray(mode.values, dtype=np.complex128)
    field_power = float(np.sum(np.abs(field_values) ** 2) * area)
    mode_power = float(np.sum(np.abs(mode_values) ** 2) * area)
    denominator = max(field_power * mode_power, 0.0)
    if denominator <= 0.0:
        return OverlapDecomposition(0.0 + 0.0j, 0.0, 0.0, 0.0, field_power, mode_power)
    complex_overlap = complex(
        np.sum(field_values * np.conj(mode_values)) * area / np.sqrt(denominator)
    )
    complex_efficiency = float(abs(complex_overlap) ** 2)
    amplitude_integral = float(
        np.sum(np.abs(field_values) * np.abs(mode_values)) * area
    )
    intensity_efficiency = float(
        np.clip(amplitude_integral * amplitude_integral / denominator, 0.0, 1.0)
    )
    phase_efficiency = (
        float(np.clip(complex_efficiency / intensity_efficiency, 0.0, 1.0))
        if intensity_efficiency > 1.0e-30
        else 0.0
    )
    return OverlapDecomposition(
        complex_overlap=complex_overlap,
        complex_efficiency=complex_efficiency,
        intensity_only_efficiency=intensity_efficiency,
        phase_matching_efficiency=phase_efficiency,
        field_power=field_power,
        mode_power=mode_power,
    )


__all__ = ["OverlapDecomposition", "decompose_scalar_overlap"]
