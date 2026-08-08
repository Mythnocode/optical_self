from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optical_core.physics.wave.formulas.polarization import (
    apply_jones_matrix,
    degree_of_polarization,
    validate_jones_vector,
)


@dataclass(frozen=True)
class FresnelAmplitudeCoefficients:
    rp: complex
    rs: complex
    tp: complex
    ts: complex
    theta_t_rad: complex
    total_internal_reflection: bool


@dataclass(frozen=True)
class FresnelPowerCoefficients:
    Rp: float
    Rs: float
    Tp: float
    Ts: float
    total_internal_reflection: bool


def fresnel_amplitude_coefficients(
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> FresnelAmplitudeCoefficients:
    if n1 <= 0:
        raise ValueError("n1 must be positive")
    if n2 <= 0:
        raise ValueError("n2 must be positive")
    if incident_angle_rad < 0:
        raise ValueError("incident_angle_rad must be non-negative")
    if incident_angle_rad >= np.pi / 2:
        raise ValueError("incident_angle_rad must be smaller than pi/2")

    sin_i = np.sin(incident_angle_rad)
    cos_i = np.cos(incident_angle_rad)

    sin_t = (n1 / n2) * sin_i
    total_internal_reflection = bool(abs(sin_t) > 1.0)

    cos_t = np.sqrt(1.0 - sin_t**2 + 0j)
    theta_t_rad = np.arcsin(sin_t + 0j)

    rs = (n1 * cos_i - n2 * cos_t) / (n1 * cos_i + n2 * cos_t)
    rp = (n2 * cos_i - n1 * cos_t) / (n2 * cos_i + n1 * cos_t)

    ts = 2.0 * n1 * cos_i / (n1 * cos_i + n2 * cos_t)
    tp = 2.0 * n1 * cos_i / (n2 * cos_i + n1 * cos_t)

    return FresnelAmplitudeCoefficients(
        rp=complex(rp),
        rs=complex(rs),
        tp=complex(tp),
        ts=complex(ts),
        theta_t_rad=complex(theta_t_rad),
        total_internal_reflection=total_internal_reflection,
    )


def fresnel_power_coefficients(
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> FresnelPowerCoefficients:
    coeffs = fresnel_amplitude_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
    )

    cos_i = np.cos(incident_angle_rad)
    cos_t = np.cos(coeffs.theta_t_rad)

    Rp = float(abs(coeffs.rp) ** 2)
    Rs = float(abs(coeffs.rs) ** 2)

    if coeffs.total_internal_reflection:
        Tp = 0.0
        Ts = 0.0
    else:
        power_factor = float(np.real(n2 * cos_t) / (n1 * cos_i))
        Tp = float(power_factor * abs(coeffs.tp) ** 2)
        Ts = float(power_factor * abs(coeffs.ts) ** 2)

    return FresnelPowerCoefficients(
        Rp=Rp,
        Rs=Rs,
        Tp=Tp,
        Ts=Ts,
        total_internal_reflection=coeffs.total_internal_reflection,
    )


def fresnel_jones_reflection(
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> np.ndarray:

    coeffs = fresnel_amplitude_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
    )

    return np.asarray(
        [
            [coeffs.rp, 0.0],
            [0.0, coeffs.rs],
        ],
        dtype=np.complex128,
    )


def fresnel_jones_transmission(
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> np.ndarray:

    coeffs = fresnel_amplitude_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
    )

    return np.asarray(
        [
            [coeffs.tp, 0.0],
            [0.0, coeffs.ts],
        ],
        dtype=np.complex128,
    )


def apply_fresnel_reflection_to_jones(
    jones_ps: np.ndarray,
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> np.ndarray:
    jones_ps = validate_jones_vector(jones_ps)
    matrix = fresnel_jones_reflection(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
    )

    return apply_jones_matrix(matrix, jones_ps)


def apply_fresnel_transmission_to_jones(
    jones_ps: np.ndarray,
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> np.ndarray:
    jones_ps = validate_jones_vector(jones_ps)
    matrix = fresnel_jones_transmission(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
    )

    return apply_jones_matrix(matrix, jones_ps)


def brewster_angle(n1: float, n2: float) -> float:
    if n1 <= 0:
        raise ValueError("n1 must be positive")
    if n2 <= 0:
        raise ValueError("n2 must be positive")

    return float(np.arctan(n2 / n1))


def critical_angle(n1: float, n2: float) -> float | None:
    if n1 <= 0:
        raise ValueError("n1 must be positive")
    if n2 <= 0:
        raise ValueError("n2 must be positive")

    if n1 <= n2:
        return None

    return float(np.arcsin(n2 / n1))


def reflected_stokes_from_unpolarized(
    n1: float,
    n2: float,
    incident_angle_rad: float,
    input_intensity: float = 1.0,
) -> np.ndarray:

    if input_intensity < 0:
        raise ValueError("input_intensity must be non-negative")

    powers = fresnel_power_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
    )

    reflected_p = 0.5 * input_intensity * powers.Rp
    reflected_s = 0.5 * input_intensity * powers.Rs

    return np.asarray(
        [
            reflected_p + reflected_s,
            reflected_p - reflected_s,
            0.0,
            0.0,
        ],
        dtype=float,
    )


def degree_of_polarization_after_reflection_unpolarized(
    n1: float,
    n2: float,
    incident_angle_rad: float,
) -> float:
    stokes = reflected_stokes_from_unpolarized(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        input_intensity=1.0,
    )

    return degree_of_polarization(stokes)


def parallel_plate_transmission(
    n_air: float,
    n_plate: float,
    incident_angle_rad: float,
    polarization: str,
    plate_count: int = 1,
) -> float:

    if plate_count < 1:
        raise ValueError("plate_count must be at least 1")

    polarization_name = polarization.lower()

    first = fresnel_power_coefficients(
        n1=n_air,
        n2=n_plate,
        incident_angle_rad=incident_angle_rad,
    )

    transmitted_angle_rad = float(np.real(
        fresnel_amplitude_coefficients(
            n1=n_air,
            n2=n_plate,
            incident_angle_rad=incident_angle_rad,
        ).theta_t_rad
    ))

    second = fresnel_power_coefficients(
        n1=n_plate,
        n2=n_air,
        incident_angle_rad=transmitted_angle_rad,
    )

    if polarization_name in {"s", "sigma"}:
        single_plate = first.Ts * second.Ts
    elif polarization_name in {"p", "pi"}:
        single_plate = first.Tp * second.Tp
    elif polarization_name in {"unpolarized", "natural"}:
        single_plate = 0.5 * (first.Tp * second.Tp + first.Ts * second.Ts)
    else:
        raise ValueError("polarization must be 's', 'p', or 'unpolarized'")

    return float(single_plate**plate_count)


def glass_stack_transmission(
    n_air: float,
    n_glass: float,
    incident_angle_rad: float,
    plate_count: int,
    polarization: str,
) -> float:
    return parallel_plate_transmission(
        n_air=n_air,
        n_plate=n_glass,
        incident_angle_rad=incident_angle_rad,
        polarization=polarization,
        plate_count=plate_count,
    )