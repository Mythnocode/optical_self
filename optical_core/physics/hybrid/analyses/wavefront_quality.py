
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.operators.zernike import fit_zernike_coefficients
from optical_core.physics.hybrid.solvers.wavefront_from_rays import (
    WavefrontFromRaysOptions,
    solve_wavefront_from_rays,
)


@dataclass(frozen=True, slots=True)
class WavefrontQualityOptions:
    wavelength_nm: float = 550.0
    grid_size: int = 65
    field_extent_mm: float | None = None
    reference: str = "reference_sphere"
    image_refractive_index: float = 1.0
    reference_image_point_mm: tuple[float, float, float] | None = None
    fit_zernike: bool = True
    zernike_normalization: str = "noll"


@dataclass(slots=True)
class WavefrontQualityResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_wavefront_quality(
    trace: TraceBundle,
    options: WavefrontQualityOptions | dict[str, Any] | None = None,
) -> WavefrontQualityResult:
    if isinstance(options, WavefrontQualityOptions):
        opts = options
    else:
        raw = dict(options or {})
        point = raw.get("reference_image_point_mm", None)
        opts = WavefrontQualityOptions(
            wavelength_nm=float(raw.get("wavelength_nm", 550.0)),
            grid_size=int(raw.get("grid_size", 65)),
            field_extent_mm=raw.get("field_extent_mm", raw.get("extent_mm", None)),
            reference=str(raw.get("reference", "reference_sphere")),
            image_refractive_index=float(raw.get("image_refractive_index", 1.0)),
            reference_image_point_mm=(None if point is None else tuple(float(v) for v in point)),
            fit_zernike=bool(raw.get("fit_zernike", True)),
            zernike_normalization=str(raw.get("zernike_normalization", "noll")),
        )

    solved = solve_wavefront_from_rays(
        trace,
        WavefrontFromRaysOptions(
            wavelength_nm=opts.wavelength_nm,
            grid_size=opts.grid_size,
            field_extent_mm=opts.field_extent_mm,
            reference=opts.reference,
            image_refractive_index=opts.image_refractive_index,
            reference_image_point_mm=opts.reference_image_point_mm,
        ),
    )
    metrics = dict(solved.metrics)
    arrays = dict(solved.arrays)
    warnings = list(solved.warnings)

    rms_waves = float(metrics.get("wavefront_rms_waves", 0.0))
    strehl = float(np.exp(-((2.0 * np.pi * rms_waves) ** 2))) if np.isfinite(rms_waves) else 0.0
    metrics["strehl_estimate_marechal"] = float(np.clip(strehl, 0.0, 1.0))

    if opts.fit_zernike:
        pupil = arrays.get("wavefront_sample_pupil_coordinates_normalized")
        sample_opd = arrays.get("wavefront_sample_opd_nm")
        sample_mask = arrays.get("wavefront_sample_valid_mask")
        sample_integration_weights = arrays.get("wavefront_sample_integration_weights")
        if pupil is None or sample_opd is None:
            warnings.append("Zernike fit skipped: explicit normalized pupil samples unavailable.")
        else:
            pupil_arr = np.asarray(pupil, dtype=float)
            opd_arr = np.asarray(sample_opd, dtype=float)
            mask_arr = np.asarray(sample_mask, dtype=bool) if sample_mask is not None else None
            fit_weights_arr = (
                np.asarray(sample_integration_weights, dtype=float)
                if sample_integration_weights is not None
                else None
            )
            coeffs = fit_zernike_coefficients(
                pupil_arr[:, 0],
                pupil_arr[:, 1],
                opd_arr,
                mask=mask_arr,
                weights=fit_weights_arr,
                normalization=opts.zernike_normalization,
            )
            for name, value in coeffs.items():
                metrics[f"zernike_{name}_nm"] = value
            arrays["zernike_names"] = list(coeffs.keys())
            arrays["zernike_coefficients_nm"] = list(coeffs.values())
            metrics["zernike_coordinate_radius_max"] = float(
                np.nanmax(np.linalg.norm(pupil_arr, axis=1))
            )
            metrics["zernike_normalized_pupil"] = True
            metrics["zernike_normalization"] = opts.zernike_normalization

    return WavefrontQualityResult(
        metrics=metrics,
        arrays=arrays,
        warnings=warnings,
        metadata={
            "analysis": "wavefront_quality",
            "reference": opts.reference,
            "zernike_normalization": opts.zernike_normalization,
            **dict(solved.metadata),
        },
    )
