
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.operators.ray_to_wavefront import WavefrontMap, trace_to_wavefront_map


@dataclass(frozen=True, slots=True)
class WavefrontFromRaysOptions:
    wavelength_nm: float = 550.0
    grid_size: int = 65
    field_extent_mm: float | None = None
    reference: str = "reference_sphere"
    image_refractive_index: float = 1.0
    reference_image_point_mm: tuple[float, float, float] | None = None


@dataclass(slots=True)
class WavefrontFromRaysResult:
    wavefront: WavefrontMap
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def solve_wavefront_from_rays(trace: TraceBundle, options: WavefrontFromRaysOptions) -> WavefrontFromRaysResult:
    wavefront = trace_to_wavefront_map(
        trace,
        wavelength_nm=options.wavelength_nm,
        grid_size=options.grid_size,
        extent_mm=options.field_extent_mm,
        reference=options.reference,
        image_refractive_index=options.image_refractive_index,
        reference_image_point_mm=(
            None
            if options.reference_image_point_mm is None
            else np.asarray(options.reference_image_point_mm, dtype=float)
        ),
    )
    return WavefrontFromRaysResult(
        wavefront=wavefront,
        metrics=dict(wavefront.metrics),
        arrays=dict(wavefront.arrays),
        warnings=list(wavefront.warnings),
        metadata={"solver": "wavefront_from_rays", **dict(wavefront.metadata)},
    )
