from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.physics.wave.formulas.polarization import (
    intensity_from_jones,
    linear_jones,
    linear_polarizer_jones,
    normalize_jones,
)


@dataclass(frozen=True, slots=True)
class PolarizationAnalysisOptions:
    input_angle_rad: float = 0.0
    polarizer_angle_rad: float = 0.0
    amplitude: float = 1.0


@dataclass(slots=True)
class PolarizationAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_polarization(options: PolarizationAnalysisOptions) -> PolarizationAnalysisResult:
    input_jones = linear_jones(options.input_angle_rad, amplitude=options.amplitude)
    polarizer = linear_polarizer_jones(options.polarizer_angle_rad)
    output = polarizer @ input_jones
    input_intensity = intensity_from_jones(input_jones)
    output_intensity = intensity_from_jones(output)
    transmittance = output_intensity / input_intensity if input_intensity > 0 else 0.0
    normalized = normalize_jones(output) if output_intensity > 0 else output
    return PolarizationAnalysisResult(
        metrics={
            "polarization_input_intensity": float(input_intensity),
            "polarization_output_intensity": float(output_intensity),
            "polarization_transmittance": float(transmittance),
        },
        arrays={
            "polarization_output_jones_real": np.real(normalized).tolist(),
            "polarization_output_jones_imag": np.imag(normalized).tolist(),
        },
        metadata={"analysis": "polarization", "model": "linear_polarizer"},
    )
