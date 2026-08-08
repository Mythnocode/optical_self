from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from optical_core.physics.wave.formulas.materials import OpticalMaterial


@dataclass(frozen=True)
class FabryPerotSpectrumResult:
    wavelength_nm: np.ndarray
    phase_difference_rad: np.ndarray
    transmission: np.ndarray
    reflection: np.ndarray
    mirror_reflectance: float
    metadata: dict[str, Any]


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be positive and finite.")
    return value


def _validate_non_negative(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be non-negative and finite.")
    return value


def _validate_angle(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    if value < 0.0 or value >= math.pi / 2.0:
        raise ValueError(f"{name} must be in [0, pi/2).")
    return value


def _validate_mirror_reflectance(value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError("mirror_reflectance must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < 0.0 or value >= 1.0:
        raise ValueError("mirror_reflectance must be in [0, 1).")
    return value


def _as_positive_array(name: str, value: float | np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values.")
    if np.any(array <= 0.0):
        raise ValueError(f"{name} must be positive.")
    return array


def _as_finite_array(name: str, value: float | np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values.")
    return array


def _maybe_scalar(original: float | np.ndarray, value: np.ndarray) -> float | np.ndarray:
    if np.asarray(original).ndim == 0:
        return float(np.asarray(value))
    return value


def _n_medium_array(
    n_medium: float | OpticalMaterial,
    *,
    wavelength_nm: float | np.ndarray,
) -> np.ndarray:
    wavelength = _as_positive_array("wavelength_nm", wavelength_nm)

    if hasattr(n_medium, "n_complex"):
        value = np.asarray(n_medium.n_complex(wavelength_nm), dtype=np.complex128)  
    else:
        value = np.full_like(wavelength, complex(float(n_medium), 0.0), dtype=np.complex128)

    if not np.isfinite(value.real).all() or not np.isfinite(value.imag).all():
        raise ValueError("n_medium must produce finite refractive index values.")

    if np.any(np.abs(value.imag) > 1.0e-14):
        raise ValueError(
            "fabry_perot core currently supports lossless cavity media only."
        )

    if np.any(value.real <= 0.0):
        raise ValueError("n_medium must be positive.")

    return np.asarray(value.real, dtype=float)


def _n_medium_scalar(
    n_medium: float | OpticalMaterial,
    *,
    wavelength_nm: float,
) -> float:
    return float(_n_medium_array(n_medium, wavelength_nm=wavelength_nm))


def finesse_coefficient(*, mirror_reflectance: float) -> float:


    mirror_reflectance = _validate_mirror_reflectance(mirror_reflectance)

    if mirror_reflectance == 0.0:
        return 0.0

    return float(
        4.0
        * mirror_reflectance
        / ((1.0 - mirror_reflectance) ** 2)
    )


def finesse_from_reflectance(*, mirror_reflectance: float) -> float:


    mirror_reflectance = _validate_mirror_reflectance(mirror_reflectance)

    if mirror_reflectance == 0.0:
        return 0.0

    return float(
        math.pi
        * math.sqrt(mirror_reflectance)
        / (1.0 - mirror_reflectance)
    )


def phase_hwhm_rad(*, mirror_reflectance: float) -> float:


    mirror_reflectance = _validate_mirror_reflectance(mirror_reflectance)
    coefficient = finesse_coefficient(mirror_reflectance=mirror_reflectance)

    if coefficient < 1.0:
        raise ValueError(
            "mirror_reflectance is too low for a half-maximum width "
            "inside one free spectral range."
        )

    return float(2.0 * math.asin(1.0 / math.sqrt(coefficient)))


def phase_fwhm_rad(*, mirror_reflectance: float) -> float:
    """透射峰半高全宽，单位为相位弧度。"""

    return float(2.0 * phase_hwhm_rad(mirror_reflectance=mirror_reflectance))


def approximate_phase_fwhm_rad(*, mirror_reflectance: float) -> float:


    mirror_reflectance = _validate_mirror_reflectance(mirror_reflectance)

    if mirror_reflectance <= 0.0:
        raise ValueError("mirror_reflectance must be positive.")

    return float(
        2.0
        * (1.0 - mirror_reflectance)
        / math.sqrt(mirror_reflectance)
    )


def fabry_perot_phase_difference_rad(
    *,
    wavelength_nm: float | np.ndarray,
    cavity_length_mm: float,
    n_medium: float | OpticalMaterial = 1.0,
    internal_angle_rad: float = 0.0,
) -> float | np.ndarray:


    wavelength = _as_positive_array("wavelength_nm", wavelength_nm)
    cavity_length_mm = _validate_positive("cavity_length_mm", cavity_length_mm)
    internal_angle_rad = _validate_angle("internal_angle_rad", internal_angle_rad)

    n_value = _n_medium_array(n_medium, wavelength_nm=wavelength_nm)
    wavelength_mm = wavelength * 1.0e-6

    phase = (
        4.0
        * math.pi
        * n_value
        * cavity_length_mm
        * math.cos(internal_angle_rad)
        / wavelength_mm
    )

    return _maybe_scalar(wavelength_nm, phase)


def airy_transmission(
    phase_difference_rad: float | np.ndarray,
    *,
    mirror_reflectance: float,
) -> float | np.ndarray:


    phase = _as_finite_array("phase_difference_rad", phase_difference_rad)
    coefficient = finesse_coefficient(mirror_reflectance=mirror_reflectance)

    transmission = 1.0 / (
        1.0
        + coefficient * (np.sin(phase / 2.0) ** 2)
    )

    return _maybe_scalar(phase_difference_rad, transmission)


def airy_reflection(
    phase_difference_rad: float | np.ndarray,
    *,
    mirror_reflectance: float,
) -> float | np.ndarray:


    transmission = np.asarray(
        airy_transmission(
            phase_difference_rad,
            mirror_reflectance=mirror_reflectance,
        ),
        dtype=float,
    )

    reflection = 1.0 - transmission

    return _maybe_scalar(phase_difference_rad, reflection)


def longitudinal_order(
    *,
    center_wavelength_nm: float,
    cavity_length_mm: float,
    n_medium: float | OpticalMaterial = 1.0,
    internal_angle_rad: float = 0.0,
) -> float:


    center_wavelength_nm = _validate_positive(
        "center_wavelength_nm",
        center_wavelength_nm,
    )
    cavity_length_mm = _validate_positive("cavity_length_mm", cavity_length_mm)
    internal_angle_rad = _validate_angle("internal_angle_rad", internal_angle_rad)

    n_value = _n_medium_scalar(n_medium, wavelength_nm=center_wavelength_nm)
    wavelength_mm = center_wavelength_nm * 1.0e-6

    return float(
        2.0
        * n_value
        * cavity_length_mm
        * math.cos(internal_angle_rad)
        / wavelength_mm
    )


def free_spectral_range_nm(
    *,
    center_wavelength_nm: float,
    cavity_length_mm: float,
    n_medium: float | OpticalMaterial = 1.0,
    internal_angle_rad: float = 0.0,
) -> float:


    center_wavelength_nm = _validate_positive(
        "center_wavelength_nm",
        center_wavelength_nm,
    )
    cavity_length_mm = _validate_positive("cavity_length_mm", cavity_length_mm)
    internal_angle_rad = _validate_angle("internal_angle_rad", internal_angle_rad)

    n_value = _n_medium_scalar(n_medium, wavelength_nm=center_wavelength_nm)

    numerator = (center_wavelength_nm * 1.0e-6) ** 2
    denominator = 2.0 * n_value * cavity_length_mm * math.cos(internal_angle_rad)

    fsr_mm = numerator / denominator

    return float(fsr_mm / 1.0e-6)


def linewidth_nm(
    *,
    center_wavelength_nm: float,
    cavity_length_mm: float,
    mirror_reflectance: float,
    n_medium: float | OpticalMaterial = 1.0,
    internal_angle_rad: float = 0.0,
) -> float:


    fsr = free_spectral_range_nm(
        center_wavelength_nm=center_wavelength_nm,
        cavity_length_mm=cavity_length_mm,
        n_medium=n_medium,
        internal_angle_rad=internal_angle_rad,
    )

    phase_width = phase_fwhm_rad(mirror_reflectance=mirror_reflectance)

    return float(fsr * phase_width / (2.0 * math.pi))


def resolving_power(
    *,
    center_wavelength_nm: float,
    cavity_length_mm: float,
    mirror_reflectance: float,
    n_medium: float | OpticalMaterial = 1.0,
    internal_angle_rad: float = 0.0,
) -> float:


    width = linewidth_nm(
        center_wavelength_nm=center_wavelength_nm,
        cavity_length_mm=cavity_length_mm,
        mirror_reflectance=mirror_reflectance,
        n_medium=n_medium,
        internal_angle_rad=internal_angle_rad,
    )

    return float(center_wavelength_nm / width)


def fabry_perot_spectrum(
    *,
    wavelength_nm: float | np.ndarray,
    cavity_length_mm: float,
    mirror_reflectance: float,
    n_medium: float | OpticalMaterial = 1.0,
    internal_angle_rad: float = 0.0,
) -> FabryPerotSpectrumResult:
    """计算法布里-珀罗透射/反射谱。"""

    wavelength = _as_positive_array("wavelength_nm", wavelength_nm)
    cavity_length_mm = _validate_positive("cavity_length_mm", cavity_length_mm)
    mirror_reflectance = _validate_mirror_reflectance(mirror_reflectance)
    internal_angle_rad = _validate_angle("internal_angle_rad", internal_angle_rad)

    phase = np.asarray(
        fabry_perot_phase_difference_rad(
            wavelength_nm=wavelength,
            cavity_length_mm=cavity_length_mm,
            n_medium=n_medium,
            internal_angle_rad=internal_angle_rad,
        ),
        dtype=float,
    )

    transmission = np.asarray(
        airy_transmission(
            phase,
            mirror_reflectance=mirror_reflectance,
        ),
        dtype=float,
    )

    reflection = 1.0 - transmission

    metadata = {
        "model": "fabry_perot_spectrum",
        "method": "airy_formula",
        "approximation": "lossless_symmetric_cavity",
        "cavity_length_mm": float(cavity_length_mm),
        "mirror_reflectance": float(mirror_reflectance),
        "internal_angle_rad": float(internal_angle_rad),
        "finesse_coefficient": finesse_coefficient(
            mirror_reflectance=mirror_reflectance,
        ),
        "finesse": finesse_from_reflectance(
            mirror_reflectance=mirror_reflectance,
        ),
        "not_physical_result": False,
    }

    return FabryPerotSpectrumResult(
        wavelength_nm=wavelength,
        phase_difference_rad=phase,
        transmission=transmission,
        reflection=reflection,
        mirror_reflectance=mirror_reflectance,
        metadata=metadata,
    )