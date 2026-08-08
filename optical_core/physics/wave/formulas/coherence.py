from __future__ import annotations

import math

import numpy as np


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite.")
    return value


def _validate_non_negative(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be non-negative and finite.")
    return value


def _validate_fraction(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be in [0, 1].")
    return value


def _as_finite_array(name: str, value: float | np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values.")
    return array


def _maybe_scalar(original: float | np.ndarray, value: np.ndarray) -> float | np.ndarray:
    if np.asarray(original).ndim == 0:
        return float(value)
    return value


def estimate_coherence_length_mm(
    *,
    center_wavelength_nm: float,
    bandwidth_nm: float,
) -> float:


    center_wavelength_nm = _validate_positive(
        "center_wavelength_nm",
        center_wavelength_nm,
    )
    bandwidth_nm = _validate_non_negative("bandwidth_nm", bandwidth_nm)

    if bandwidth_nm == 0.0:
        return math.inf

    wavelength_mm = center_wavelength_nm * 1.0e-6
    bandwidth_mm = bandwidth_nm * 1.0e-6

    return float(wavelength_mm * wavelength_mm / bandwidth_mm)


def estimate_bandwidth_nm_from_coherence_length(
    *,
    center_wavelength_nm: float,
    coherence_length_mm: float,
) -> float:
    """由相干长度反推带宽估计值。"""

    center_wavelength_nm = _validate_positive(
        "center_wavelength_nm",
        center_wavelength_nm,
    )
    coherence_length_mm = _validate_positive(
        "coherence_length_mm",
        coherence_length_mm,
    )

    wavelength_mm = center_wavelength_nm * 1.0e-6
    bandwidth_mm = wavelength_mm * wavelength_mm / coherence_length_mm

    return float(bandwidth_mm / 1.0e-6)


def estimate_coherence_time_s_from_bandwidth_hz(*, bandwidth_hz: float) -> float:


    bandwidth_hz = _validate_non_negative("bandwidth_hz", bandwidth_hz)

    if bandwidth_hz == 0.0:
        return math.inf

    return float(1.0 / bandwidth_hz)


def max_aperture_separation_for_spatial_coherence_mm(
    *,
    source_width_mm: float,
    source_distance_mm: float,
    wavelength_nm: float,
) -> float:


    source_width_mm = _validate_non_negative("source_width_mm", source_width_mm)
    source_distance_mm = _validate_positive("source_distance_mm", source_distance_mm)
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)

    if source_width_mm == 0.0:
        return math.inf

    wavelength_mm = wavelength_nm * 1.0e-6

    return float(source_distance_mm * wavelength_mm / source_width_mm)


def spatial_visibility_uniform_source(
    *,
    source_width_mm: float,
    aperture_separation_mm: float,
    source_distance_mm: float,
    wavelength_nm: float,
) -> float:


    source_width_mm = _validate_non_negative("source_width_mm", source_width_mm)
    aperture_separation_mm = _validate_non_negative(
        "aperture_separation_mm",
        aperture_separation_mm,
    )
    source_distance_mm = _validate_positive("source_distance_mm", source_distance_mm)
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)

    if source_width_mm == 0.0 or aperture_separation_mm == 0.0:
        return 1.0

    wavelength_mm = wavelength_nm * 1.0e-6

    argument = (
        source_width_mm
        * aperture_separation_mm
        / (wavelength_mm * source_distance_mm)
    )

    return float(abs(np.sinc(argument)))


def temporal_visibility_from_opd(
    opd_mm: float | np.ndarray,
    *,
    center_wavelength_nm: float,
    bandwidth_nm: float,
) -> float | np.ndarray:


    opd_array = _as_finite_array("opd_mm", opd_mm)

    coherence_length = estimate_coherence_length_mm(
        center_wavelength_nm=center_wavelength_nm,
        bandwidth_nm=bandwidth_nm,
    )

    if math.isinf(coherence_length):
        result = np.ones_like(opd_array, dtype=float)
        return _maybe_scalar(opd_mm, result)

    result = np.abs(np.sinc(opd_array / coherence_length))
    return _maybe_scalar(opd_mm, result)


def is_opd_within_coherence_length(
    opd_mm: float | np.ndarray,
    *,
    center_wavelength_nm: float,
    bandwidth_nm: float,
    threshold: float = 1.0,
) -> bool | np.ndarray:


    threshold = _validate_positive("threshold", threshold)
    opd_array = _as_finite_array("opd_mm", opd_mm)

    coherence_length = estimate_coherence_length_mm(
        center_wavelength_nm=center_wavelength_nm,
        bandwidth_nm=bandwidth_nm,
    )

    if math.isinf(coherence_length):
        result = np.ones_like(opd_array, dtype=bool)
        if np.asarray(opd_mm).ndim == 0:
            return bool(result)
        return result

    result = np.abs(opd_array) <= threshold * coherence_length

    if np.asarray(opd_mm).ndim == 0:
        return bool(result)

    return result


def visibility_from_intensities(
    *,
    intensity1: float,
    intensity2: float,
    degree_of_coherence: float = 1.0,
    polarization_factor: float = 1.0,
) -> float:


    intensity1 = _validate_non_negative("intensity1", intensity1)
    intensity2 = _validate_non_negative("intensity2", intensity2)
    degree_of_coherence = _validate_fraction(
        "degree_of_coherence",
        degree_of_coherence,
    )
    polarization_factor = _validate_fraction("polarization_factor", polarization_factor)

    denominator = intensity1 + intensity2

    if denominator == 0.0:
        return 0.0

    base_visibility = 2.0 * math.sqrt(intensity1 * intensity2) / denominator

    return float(base_visibility * degree_of_coherence * polarization_factor)


def combined_visibility(
    *,
    intensity1: float,
    intensity2: float,
    spatial_visibility: float = 1.0,
    temporal_visibility: float = 1.0,
    polarization_factor: float = 1.0,
) -> float:
    """组合振幅不等、空间相干、时间相干、偏振因素后的可见度。"""

    spatial_visibility = _validate_fraction("spatial_visibility", spatial_visibility)
    temporal_visibility = _validate_fraction("temporal_visibility", temporal_visibility)
    polarization_factor = _validate_fraction("polarization_factor", polarization_factor)

    return visibility_from_intensities(
        intensity1=intensity1,
        intensity2=intensity2,
        degree_of_coherence=spatial_visibility * temporal_visibility,
        polarization_factor=polarization_factor,
    )