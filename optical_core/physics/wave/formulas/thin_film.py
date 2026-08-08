from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from optical_core.physics.wave.formulas.interfaces import (
    fresnel_coefficients,
    refractive_index_value,
    snell_angle_rad,
)
from optical_core.physics.wave.formulas.materials import OpticalMaterial


@dataclass(frozen=True)
class ThinFilmInterferenceResult:
    complex_amplitude: complex
    intensity: float
    optical_path_difference_mm: float
    phase_difference_rad: float
    film_angle_rad: float
    wavelength_nm: float
    thickness_mm: float
    polarization: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ThinFilmPatternResult:
    coordinate: np.ndarray
    thickness_mm: np.ndarray
    intensity: np.ndarray
    phase_difference_rad: np.ndarray
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


def _as_array(name: str, value: float | np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values.")
    return array


def _real_index(
    index: float | OpticalMaterial,
    *,
    wavelength_nm: float,
    name: str,
) -> float:
    return refractive_index_value(index, wavelength_nm=wavelength_nm)


def film_angle_rad(
    *,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    incident_angle_rad: float,
    wavelength_nm: float,
) -> float:


    return snell_angle_rad(
        n1=n_incident,
        n2=n_film,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )


def optical_path_difference_mm(
    *,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    thickness_mm: float,
    incident_angle_rad: float,
    wavelength_nm: float,
) -> float:


    thickness_mm = _validate_non_negative("thickness_mm", thickness_mm)
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    incident_angle_rad = _validate_angle("incident_angle_rad", incident_angle_rad)

    n_film_value = _real_index(
        n_film,
        wavelength_nm=wavelength_nm,
        name="n_film",
    )

    theta_film = film_angle_rad(
        n_incident=n_incident,
        n_film=n_film,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )

    return float(2.0 * n_film_value * thickness_mm * math.cos(theta_film))


def thin_film_phase_difference_rad(
    *,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    thickness_mm: float,
    incident_angle_rad: float,
    wavelength_nm: float,
    extra_phase_rad: float = 0.0,
) -> float:


    extra_phase_rad = float(extra_phase_rad)
    if not math.isfinite(extra_phase_rad):
        raise ValueError("extra_phase_rad must be finite.")

    opd = optical_path_difference_mm(
        n_incident=n_incident,
        n_film=n_film,
        thickness_mm=thickness_mm,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )

    wavelength_mm = wavelength_nm * 1.0e-6

    return float(2.0 * math.pi * opd / wavelength_mm + extra_phase_rad)


def two_beam_reflected_thin_film(
    *,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    n_exit: float | OpticalMaterial,
    thickness_mm: float,
    wavelength_nm: float,
    incident_angle_rad: float = 0.0,
    polarization: str = "s",
) -> ThinFilmInterferenceResult:


    thickness_mm = _validate_non_negative("thickness_mm", thickness_mm)
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    incident_angle_rad = _validate_angle("incident_angle_rad", incident_angle_rad)
    polarization = polarization.lower().strip()

    theta_film = film_angle_rad(
        n_incident=n_incident,
        n_film=n_film,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )

    top = fresnel_coefficients(
        n1=n_incident,
        n2=n_film,
        incident_angle_rad=incident_angle_rad,
        polarization=polarization,
        wavelength_nm=wavelength_nm,
    )

    bottom = fresnel_coefficients(
        n1=n_film,
        n2=n_exit,
        incident_angle_rad=theta_film,
        polarization=polarization,
        wavelength_nm=wavelength_nm,
    )

    film_to_incident = fresnel_coefficients(
        n1=n_film,
        n2=n_incident,
        incident_angle_rad=theta_film,
        polarization=polarization,
        wavelength_nm=wavelength_nm,
    )

    opd = optical_path_difference_mm(
        n_incident=n_incident,
        n_film=n_film,
        thickness_mm=thickness_mm,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )

    wavelength_mm = wavelength_nm * 1.0e-6
    phase = 2.0 * math.pi * opd / wavelength_mm

    first_reflected = top.r
    second_reflected = top.t * bottom.r * film_to_incident.t * np.exp(1j * phase)

    complex_amplitude = complex(first_reflected + second_reflected)
    intensity = float(abs(complex_amplitude) ** 2)

    metadata = {
        "model": "two_beam_reflected_thin_film",
        "approximation": "two_beam",
        "uses_fresnel_amplitude_coefficients": True,
        "n_incident": top.n1,
        "n_film": top.n2,
        "n_exit": bottom.n2,
        "incident_angle_rad": incident_angle_rad,
        "film_angle_rad": theta_film,
        "first_reflected_amplitude": complex(first_reflected),
        "second_reflected_amplitude_without_phase": complex(
            top.t * bottom.r * film_to_incident.t
        ),
        "not_physical_result": False,
    }

    return ThinFilmInterferenceResult(
        complex_amplitude=complex_amplitude,
        intensity=intensity,
        optical_path_difference_mm=opd,
        phase_difference_rad=float(phase),
        film_angle_rad=theta_film,
        wavelength_nm=wavelength_nm,
        thickness_mm=thickness_mm,
        polarization=polarization,
        metadata=metadata,
    )


def two_beam_transmitted_thin_film(
    *,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    n_exit: float | OpticalMaterial,
    thickness_mm: float,
    wavelength_nm: float,
    incident_angle_rad: float = 0.0,
    polarization: str = "s",
) -> ThinFilmInterferenceResult:
    """双光束近似下的透射薄膜干涉。

    第一束：
        进入薄膜后直接从下表面透射。

    第二束：
        在薄膜内多经历一次往返后再透射。
    """

    thickness_mm = _validate_non_negative("thickness_mm", thickness_mm)
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    incident_angle_rad = _validate_angle("incident_angle_rad", incident_angle_rad)
    polarization = polarization.lower().strip()

    theta_film = film_angle_rad(
        n_incident=n_incident,
        n_film=n_film,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )

    top = fresnel_coefficients(
        n1=n_incident,
        n2=n_film,
        incident_angle_rad=incident_angle_rad,
        polarization=polarization,
        wavelength_nm=wavelength_nm,
    )

    bottom = fresnel_coefficients(
        n1=n_film,
        n2=n_exit,
        incident_angle_rad=theta_film,
        polarization=polarization,
        wavelength_nm=wavelength_nm,
    )

    film_to_incident = fresnel_coefficients(
        n1=n_film,
        n2=n_incident,
        incident_angle_rad=theta_film,
        polarization=polarization,
        wavelength_nm=wavelength_nm,
    )

    opd = optical_path_difference_mm(
        n_incident=n_incident,
        n_film=n_film,
        thickness_mm=thickness_mm,
        incident_angle_rad=incident_angle_rad,
        wavelength_nm=wavelength_nm,
    )

    wavelength_mm = wavelength_nm * 1.0e-6
    phase = 2.0 * math.pi * opd / wavelength_mm

    first_transmitted = top.t * bottom.t
    second_transmitted = (
        top.t
        * bottom.r
        * film_to_incident.r
        * bottom.t
        * np.exp(1j * phase)
    )

    complex_amplitude = complex(first_transmitted + second_transmitted)
    intensity = float(abs(complex_amplitude) ** 2)

    metadata = {
        "model": "two_beam_transmitted_thin_film",
        "approximation": "two_beam",
        "uses_fresnel_amplitude_coefficients": True,
        "n_incident": top.n1,
        "n_film": top.n2,
        "n_exit": bottom.n2,
        "incident_angle_rad": incident_angle_rad,
        "film_angle_rad": theta_film,
        "not_physical_result": False,
    }

    return ThinFilmInterferenceResult(
        complex_amplitude=complex_amplitude,
        intensity=intensity,
        optical_path_difference_mm=opd,
        phase_difference_rad=float(phase),
        film_angle_rad=theta_film,
        wavelength_nm=wavelength_nm,
        thickness_mm=thickness_mm,
        polarization=polarization,
        metadata=metadata,
    )


def wedge_film_thickness_mm(
    position_mm: float | np.ndarray,
    *,
    wedge_angle_rad: float,
    initial_thickness_mm: float = 0.0,
) -> float | np.ndarray:


    position = _as_array("position_mm", position_mm)
    wedge_angle_rad = _validate_angle("wedge_angle_rad", wedge_angle_rad)
    initial_thickness_mm = _validate_non_negative(
        "initial_thickness_mm",
        initial_thickness_mm,
    )

    thickness = initial_thickness_mm + position * math.sin(wedge_angle_rad)

    if np.any(thickness < -1.0e-15):
        raise ValueError("wedge film thickness must not be negative.")

    thickness = np.maximum(thickness, 0.0)

    if np.asarray(position_mm).ndim == 0:
        return float(thickness)

    return thickness


def wedge_fringe_spacing_mm(
    *,
    wavelength_nm: float,
    n_film: float | OpticalMaterial,
    wedge_angle_rad: float,
    wavelength_for_material_nm: float | None = None,
) -> float:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    wedge_angle_rad = _validate_angle("wedge_angle_rad", wedge_angle_rad)

    if wedge_angle_rad == 0.0:
        return math.inf

    material_wavelength = (
        wavelength_nm if wavelength_for_material_nm is None else wavelength_for_material_nm
    )

    n_value = _real_index(
        n_film,
        wavelength_nm=material_wavelength,
        name="n_film",
    )

    wavelength_mm = wavelength_nm * 1.0e-6

    return float(wavelength_mm / (2.0 * n_value * math.sin(wedge_angle_rad)))


def equal_thickness_reflected_intensity(
    *,
    thickness_mm: float | np.ndarray,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    n_exit: float | OpticalMaterial,
    wavelength_nm: float,
    incident_angle_rad: float = 0.0,
    polarization: str = "s",
) -> ThinFilmPatternResult:
    """等厚干涉反射强度。

    输入厚度数组，输出对应的反射干涉强度。
    """

    thickness = _as_array("thickness_mm", thickness_mm)

    intensities = np.empty_like(thickness, dtype=float)
    phases = np.empty_like(thickness, dtype=float)

    flat_thickness = thickness.ravel()
    flat_intensity = intensities.ravel()
    flat_phase = phases.ravel()

    for i, h in enumerate(flat_thickness):
        result = two_beam_reflected_thin_film(
            n_incident=n_incident,
            n_film=n_film,
            n_exit=n_exit,
            thickness_mm=float(h),
            wavelength_nm=wavelength_nm,
            incident_angle_rad=incident_angle_rad,
            polarization=polarization,
        )
        flat_intensity[i] = result.intensity
        flat_phase[i] = result.phase_difference_rad

    metadata = {
        "model": "equal_thickness_reflected_intensity",
        "wavelength_nm": float(wavelength_nm),
        "incident_angle_rad": float(incident_angle_rad),
        "polarization": polarization,
        "not_physical_result": False,
    }

    return ThinFilmPatternResult(
        coordinate=thickness.copy(),
        thickness_mm=thickness.copy(),
        intensity=intensities,
        phase_difference_rad=phases,
        metadata=metadata,
    )


def wedge_reflected_intensity(
    *,
    position_mm: float | np.ndarray,
    n_incident: float | OpticalMaterial,
    n_film: float | OpticalMaterial,
    n_exit: float | OpticalMaterial,
    wavelength_nm: float,
    wedge_angle_rad: float,
    initial_thickness_mm: float = 0.0,
    incident_angle_rad: float = 0.0,
    polarization: str = "s",
) -> ThinFilmPatternResult:
    """楔形薄膜等厚反射条纹。"""

    position = _as_array("position_mm", position_mm)

    thickness = wedge_film_thickness_mm(
        position,
        wedge_angle_rad=wedge_angle_rad,
        initial_thickness_mm=initial_thickness_mm,
    )

    pattern = equal_thickness_reflected_intensity(
        thickness_mm=thickness,
        n_incident=n_incident,
        n_film=n_film,
        n_exit=n_exit,
        wavelength_nm=wavelength_nm,
        incident_angle_rad=incident_angle_rad,
        polarization=polarization,
    )

    return ThinFilmPatternResult(
        coordinate=position,
        thickness_mm=pattern.thickness_mm,
        intensity=pattern.intensity,
        phase_difference_rad=pattern.phase_difference_rad,
        metadata={
            **pattern.metadata,
            "model": "wedge_reflected_intensity",
            "wedge_angle_rad": float(wedge_angle_rad),
            "initial_thickness_mm": float(initial_thickness_mm),
        },
    )