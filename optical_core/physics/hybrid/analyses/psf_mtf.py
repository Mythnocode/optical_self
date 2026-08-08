
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.reconstruction import (
    ComplexFieldReconstructionRequest,
    formal_complex_field_reconstructor,
)


@dataclass(frozen=True, slots=True)
class HybridPsfMtfOptions:
    wavelength_nm: float = 550.0
    grid_size: int = 129
    field_extent_mm: float | None = None
    normalize: bool = True


@dataclass(slots=True)
class HybridPsfMtfResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_psf_mtf_from_trace(trace: TraceBundle, options: HybridPsfMtfOptions | dict[str, Any] | None = None) -> HybridPsfMtfResult:
    if isinstance(options, HybridPsfMtfOptions):
        opts = options
    else:
        raw = dict(options or {})
        opts = HybridPsfMtfOptions(
            wavelength_nm=float(raw.get("wavelength_nm", 550.0)),
            grid_size=int(raw.get("grid_size", 129)),
            field_extent_mm=raw.get("field_extent_mm", raw.get("extent_mm", None)),
            normalize=bool(raw.get("normalize", True)),
        )

    pupil = formal_complex_field_reconstructor().reconstruct(
        trace,
        ComplexFieldReconstructionRequest(
            wavelength_nm=opts.wavelength_nm,
            grid_size=opts.grid_size,
            normalize_power=opts.normalize,
        ),
    )
    field = np.asarray(pupil.field.values, dtype=np.complex128)
    fft = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(field)))
    psf = np.abs(fft) ** 2
    peak = float(np.max(psf)) if psf.size else 0.0
    if peak > 0.0:
        psf = psf / peak
    otf = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(psf)))
    mtf = np.abs(otf)
    dc = float(np.max(mtf)) if mtf.size else 0.0
    if dc > 0.0:
        mtf = mtf / dc
    center = mtf.shape[0] // 2
    mtf_cut = mtf[center, :]

    return HybridPsfMtfResult(
        metrics={
            "hybrid_psf_peak_normalized": float(np.max(psf)) if psf.size else 0.0,
            "hybrid_psf_energy": float(np.sum(psf)),
            "hybrid_mtf_dc": float(mtf[center, center]) if mtf.size else 0.0,
            "hybrid_mtf_mean": float(np.mean(mtf)) if mtf.size else 0.0,
        },
        arrays={
            "hybrid_psf_intensity": psf.tolist(),
            "hybrid_mtf_values": mtf.tolist(),
            "hybrid_mtf_center_cut": mtf_cut.tolist(),
        },
        warnings=list(pupil.warnings),
        metadata={
            "analysis": "hybrid_psf_mtf",
            "model": "fft_of_formal_cartesian_exit_pupil",
            "formal_complex_field_chain": "cartesian_exit_pupil",
            "independent_ray_deposition_removed": True,
        },
    )
