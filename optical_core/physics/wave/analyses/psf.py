from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.analyses.diffraction import evaluate_diffraction
from optical_core.physics.wave.solvers.propagation_options import PropagationOptions


@dataclass(slots=True)
class PsfAnalysisResult:
    psf: np.ndarray
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _second_moment_radius(x: np.ndarray, y: np.ndarray, intensity: np.ndarray) -> float:
    total = float(np.sum(intensity))
    if total <= 0:
        return 0.0
    xx, yy = np.meshgrid(x, y, indexing="xy")
    cx = float(np.sum(xx * intensity) / total)
    cy = float(np.sum(yy * intensity) / total)
    radius2 = float(np.sum(((xx - cx) ** 2 + (yy - cy) ** 2) * intensity) / total)
    return float(np.sqrt(max(radius2, 0.0)))


def evaluate_psf(options: PropagationOptions, input_field: ScalarField2D | None = None) -> PsfAnalysisResult:


    diffraction = evaluate_diffraction(options, input_field=input_field)
    intensity = diffraction.intensity.astype(float)
    peak = float(np.max(intensity)) if intensity.size else 0.0
    psf = intensity / peak if peak > 0 else intensity
    radius_rms = _second_moment_radius(diffraction.field.grid.x_mm, diffraction.field.grid.y_mm, psf)
    return PsfAnalysisResult(
        psf=psf,
        metrics={
            "psf_peak_normalized": float(np.max(psf)) if psf.size else 0.0,
            "psf_rms_radius_mm": radius_rms,
        },
        arrays={
            "psf_x_mm": diffraction.field.grid.x_mm.tolist(),
            "psf_y_mm": diffraction.field.grid.y_mm.tolist(),
            "psf_intensity": psf.tolist(),
        },
        warnings=list(diffraction.warnings),
        metadata={"analysis": "psf", **diffraction.metadata},
    )
