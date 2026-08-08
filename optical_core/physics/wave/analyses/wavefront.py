from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(slots=True)
class WavefrontAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_wavefront(phase_rad: np.ndarray, wavelength_nm: float) -> WavefrontAnalysisResult:
    phase = np.asarray(phase_rad, dtype=float)
    wavelength_um = wavelength_nm * 1e-3
    opd_um = phase / (2.0 * np.pi) * wavelength_um
    opd_centered = opd_um - float(np.nanmean(opd_um))
    return WavefrontAnalysisResult(
        metrics={
            "wavefront_rms_um": float(np.sqrt(np.nanmean(opd_centered**2))),
            "wavefront_pv_um": float(np.nanmax(opd_centered) - np.nanmin(opd_centered)),
        },
        arrays={"wavefront_opd_um": opd_centered.tolist()},
        metadata={"analysis": "wavefront"},
    )
