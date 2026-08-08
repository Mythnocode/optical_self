from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optical_core.physics.wave.formulas.coherence import (
    estimate_coherence_length_mm,
    spatial_visibility_uniform_source,
    temporal_visibility_from_opd,
)


@dataclass(frozen=True, slots=True)
class CoherenceAnalysisOptions:
    center_wavelength_nm: float = 550.0
    bandwidth_nm: float = 1.0
    opd_mm: float = 0.0
    source_width_mm: float = 0.0
    aperture_separation_mm: float = 0.0
    source_distance_mm: float = 1000.0


@dataclass(slots=True)
class CoherenceAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_coherence(options: CoherenceAnalysisOptions) -> CoherenceAnalysisResult:
    coherence_length = estimate_coherence_length_mm(
        center_wavelength_nm=options.center_wavelength_nm,
        bandwidth_nm=options.bandwidth_nm,
    )
    temporal_visibility = temporal_visibility_from_opd(
        options.opd_mm,
        center_wavelength_nm=options.center_wavelength_nm,
        bandwidth_nm=options.bandwidth_nm,
    )
    spatial_visibility = spatial_visibility_uniform_source(
        source_width_mm=options.source_width_mm,
        aperture_separation_mm=options.aperture_separation_mm,
        source_distance_mm=options.source_distance_mm,
        wavelength_nm=options.center_wavelength_nm,
    )
    return CoherenceAnalysisResult(
        metrics={
            "coherence_length_mm": float(coherence_length),
            "temporal_visibility": float(temporal_visibility),
            "spatial_visibility": float(spatial_visibility),
        },
        metadata={"analysis": "coherence"},
    )
