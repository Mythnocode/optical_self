from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.analyses.psf import evaluate_psf
from optical_core.physics.wave.solvers.propagation_options import PropagationOptions


@dataclass(slots=True)
class MtfAnalysisResult:
    mtf: np.ndarray
    fx_cycles_per_mm: np.ndarray
    fy_cycles_per_mm: np.ndarray
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_mtf(options: PropagationOptions, input_field: ScalarField2D | None = None) -> MtfAnalysisResult:


    psf_result = evaluate_psf(options, input_field=input_field)
    psf = np.asarray(psf_result.psf, dtype=float)
    otf = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(psf)))
    mtf = np.abs(otf)
    peak = float(np.max(mtf)) if mtf.size else 0.0
    if peak > 0:
        mtf = mtf / peak

    ny, nx = mtf.shape
    dx = float(abs(psf_result.arrays["psf_x_mm"][1] - psf_result.arrays["psf_x_mm"][0])) if nx > 1 else 1.0
    dy = float(abs(psf_result.arrays["psf_y_mm"][1] - psf_result.arrays["psf_y_mm"][0])) if ny > 1 else 1.0
    fx = np.fft.fftshift(np.fft.fftfreq(nx, d=dx))
    fy = np.fft.fftshift(np.fft.fftfreq(ny, d=dy))

    center_y = ny // 2
    center_x = nx // 2
    return MtfAnalysisResult(
        mtf=mtf,
        fx_cycles_per_mm=fx,
        fy_cycles_per_mm=fy,
        metrics={
            "mtf_dc": float(mtf[center_y, center_x]) if mtf.size else 0.0,
            "mtf_grid_size": int(nx),
        },
        arrays={
            "mtf_fx_cycles_per_mm": fx.tolist(),
            "mtf_fy_cycles_per_mm": fy.tolist(),
            "mtf_values": mtf.tolist(),
            "mtf_x_cut": mtf[center_y, :].tolist(),
            "mtf_y_cut": mtf[:, center_x].tolist(),
        },
        warnings=list(psf_result.warnings),
        metadata={"analysis": "mtf", **psf_result.metadata},
    )
