from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.physics.wave.formulas.scalar_diffraction import make_uniform_grid
from optical_core.physics.wave.formulas.interference import two_plane_wave_interference


@dataclass(frozen=True, slots=True)
class InterferenceAnalysisOptions:
    wavelength_nm: float = 550.0
    grid_size: int = 129
    extent_mm: float = 1.0
    amplitude1: float = 1.0
    amplitude2: float = 1.0
    theta1_x_rad: float = 0.0
    theta2_x_rad: float = 0.01
    theta1_y_rad: float = 0.0
    theta2_y_rad: float = 0.0
    phase1_rad: float = 0.0
    phase2_rad: float = 0.0
    normalize: bool = True


@dataclass(slots=True)
class InterferenceAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_interference(options: InterferenceAnalysisOptions) -> InterferenceAnalysisResult:
    grid = make_uniform_grid(grid_size=options.grid_size, extent_mm=options.extent_mm)
    result = two_plane_wave_interference(
        grid=grid,
        wavelength_nm=options.wavelength_nm,
        amplitude1=options.amplitude1,
        amplitude2=options.amplitude2,
        theta1_x_rad=options.theta1_x_rad,
        theta2_x_rad=options.theta2_x_rad,
        theta1_y_rad=options.theta1_y_rad,
        theta2_y_rad=options.theta2_y_rad,
        phase1_rad=options.phase1_rad,
        phase2_rad=options.phase2_rad,
        normalize=options.normalize,
    )
    intensity = np.asarray(result.intensity, dtype=float)
    return InterferenceAnalysisResult(
        metrics={
            "interference_visibility": float(result.visibility),
            "interference_peak_intensity": float(np.max(intensity)) if intensity.size else 0.0,
            "interference_min_intensity": float(np.min(intensity)) if intensity.size else 0.0,
        },
        arrays={
            "interference_x_mm": grid.x_mm[0, :].tolist(),
            "interference_y_mm": grid.y_mm[:, 0].tolist(),
            "interference_intensity": intensity.tolist(),
            "interference_phase_rad": np.asarray(result.phase_rad).tolist(),
        },
        metadata={"analysis": "interference", **result.metadata},
    )
