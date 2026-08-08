from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FraunhoferGratingResult:
    theta_rad: np.ndarray
    complex_amplitude: np.ndarray
    intensity: np.ndarray
    single_slit_envelope: np.ndarray
    single_slit_intensity: np.ndarray
    multi_slit_factor: np.ndarray
    multi_slit_intensity: np.ndarray
    wavelength_nm: float
    slit_width_mm: float
    period_mm: float
    slit_count: int
    metadata: dict[str, Any]


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite.")
    return value


def _validate_finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    return value


def _validate_slit_count(slit_count: int) -> int:
    if not isinstance(slit_count, int):
        raise TypeError("slit_count must be an integer.")
    if slit_count < 1:
        raise ValueError("slit_count must be at least 1.")
    return slit_count


def make_theta_axis(
    *,
    theta_min_rad: float,
    theta_max_rad: float,
    sample_count: int,
) -> np.ndarray:
    """生成一维衍射角采样轴。"""

    theta_min_rad = _validate_finite("theta_min_rad", theta_min_rad)
    theta_max_rad = _validate_finite("theta_max_rad", theta_max_rad)

    if theta_max_rad <= theta_min_rad:
        raise ValueError("theta_max_rad must be greater than theta_min_rad.")
    if not isinstance(sample_count, int):
        raise TypeError("sample_count must be an integer.")
    if sample_count < 5:
        raise ValueError("sample_count must be at least 5.")
    if sample_count % 2 == 0:
        raise ValueError("sample_count must be odd so that theta=0 can be sampled.")

    return np.linspace(theta_min_rad, theta_max_rad, sample_count, dtype=float)


def single_slit_envelope(
    theta_rad: np.ndarray,
    *,
    wavelength_nm: float,
    slit_width_mm: float,
    incident_angle_rad: float = 0.0,
) -> np.ndarray:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    slit_width_mm = _validate_positive("slit_width_mm", slit_width_mm)
    incident_angle_rad = _validate_finite("incident_angle_rad", incident_angle_rad)

    theta_rad = np.asarray(theta_rad, dtype=float)
    wavelength_mm = wavelength_nm * 1.0e-6

    u = (
        math.pi
        * slit_width_mm
        / wavelength_mm
        * (np.sin(theta_rad) - math.sin(incident_angle_rad))
    )

    return np.sinc(u / math.pi)


def _multi_slit_factor_from_beta(beta: np.ndarray, slit_count: int) -> np.ndarray:


    slit_count = _validate_slit_count(slit_count)
    beta = np.asarray(beta, dtype=float)

    numerator = np.sin(slit_count * beta)
    denominator = np.sin(beta)

    factor = np.empty_like(beta, dtype=float)
    regular = np.abs(denominator) > 1.0e-12

    factor[regular] = numerator[regular] / denominator[regular]

    singular_indices = np.where(~regular)
    if singular_indices[0].size > 0:
        m_values = np.rint(beta[singular_indices] / math.pi).astype(int)
        signs = np.where(((slit_count - 1) * m_values) % 2 == 0, 1.0, -1.0)
        factor[singular_indices] = slit_count * signs

    return factor


def multi_slit_interference_factor(
    theta_rad: np.ndarray,
    *,
    wavelength_nm: float,
    period_mm: float,
    slit_count: int,
    incident_angle_rad: float = 0.0,
) -> np.ndarray:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    period_mm = _validate_positive("period_mm", period_mm)
    slit_count = _validate_slit_count(slit_count)
    incident_angle_rad = _validate_finite("incident_angle_rad", incident_angle_rad)

    theta_rad = np.asarray(theta_rad, dtype=float)
    wavelength_mm = wavelength_nm * 1.0e-6

    beta = (
        math.pi
        * period_mm
        / wavelength_mm
        * (np.sin(theta_rad) - math.sin(incident_angle_rad))
    )

    return _multi_slit_factor_from_beta(beta, slit_count)


def fraunhofer_grating_intensity(
    *,
    theta_rad: np.ndarray,
    wavelength_nm: float,
    slit_width_mm: float,
    period_mm: float,
    slit_count: int,
    incident_angle_rad: float = 0.0,
    normalize: bool = True,
) -> FraunhoferGratingResult:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    slit_width_mm = _validate_positive("slit_width_mm", slit_width_mm)
    period_mm = _validate_positive("period_mm", period_mm)
    slit_count = _validate_slit_count(slit_count)
    incident_angle_rad = _validate_finite("incident_angle_rad", incident_angle_rad)

    if slit_width_mm > period_mm:
        raise ValueError("slit_width_mm must not be greater than period_mm.")

    theta_rad = np.asarray(theta_rad, dtype=float)

    envelope = single_slit_envelope(
        theta_rad,
        wavelength_nm=wavelength_nm,
        slit_width_mm=slit_width_mm,
        incident_angle_rad=incident_angle_rad,
    )

    multi_factor = multi_slit_interference_factor(
        theta_rad,
        wavelength_nm=wavelength_nm,
        period_mm=period_mm,
        slit_count=slit_count,
        incident_angle_rad=incident_angle_rad,
    )

    complex_amplitude = envelope.astype(np.complex128) * multi_factor
    intensity = np.abs(complex_amplitude) ** 2

    raw_peak_intensity = float(np.max(intensity)) if intensity.size else 0.0

    if normalize and raw_peak_intensity > 0:
        complex_amplitude = complex_amplitude / math.sqrt(raw_peak_intensity)
        intensity = np.abs(complex_amplitude) ** 2

    single_slit_intensity = envelope**2
    multi_slit_intensity = multi_factor**2

    metadata = {
        "model": "fraunhofer_grating_1d",
        "method": "analytic",
        "approximation": "far_field",
        "wavelength_nm": float(wavelength_nm),
        "wavelength_mm": float(wavelength_nm * 1.0e-6),
        "slit_width_mm": float(slit_width_mm),
        "period_mm": float(period_mm),
        "slit_count": int(slit_count),
        "incident_angle_rad": float(incident_angle_rad),
        "raw_peak_intensity": raw_peak_intensity,
        "intensity_normalized": bool(normalize),
        "not_physical_result": False,
    }

    return FraunhoferGratingResult(
        theta_rad=theta_rad,
        complex_amplitude=complex_amplitude,
        intensity=intensity,
        single_slit_envelope=envelope,
        single_slit_intensity=single_slit_intensity,
        multi_slit_factor=multi_factor,
        multi_slit_intensity=multi_slit_intensity,
        wavelength_nm=wavelength_nm,
        slit_width_mm=slit_width_mm,
        period_mm=period_mm,
        slit_count=slit_count,
        metadata=metadata,
    )


def grating_orders(
    *,
    wavelength_nm: float,
    period_mm: float,
    incident_angle_rad: float = 0.0,
    max_order: int | None = None,
) -> list[dict[str, float | int]]:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    period_mm = _validate_positive("period_mm", period_mm)
    incident_angle_rad = _validate_finite("incident_angle_rad", incident_angle_rad)

    wavelength_mm = wavelength_nm * 1.0e-6
    sin_theta0 = math.sin(incident_angle_rad)

    natural_max = int(math.floor(period_mm / wavelength_mm + 1.0))
    if max_order is None:
        max_order = natural_max
    else:
        if not isinstance(max_order, int):
            raise TypeError("max_order must be an integer or None.")
        if max_order < 0:
            raise ValueError("max_order must be non-negative.")

    orders: list[dict[str, float | int]] = []

    for order in range(-max_order, max_order + 1):
        sin_theta = sin_theta0 + order * wavelength_mm / period_mm

        if abs(sin_theta) <= 1.0:
            theta_rad = math.asin(max(-1.0, min(1.0, sin_theta)))
            orders.append(
                {
                    "order": order,
                    "theta_rad": theta_rad,
                    "sin_theta": sin_theta,
                }
            )

    return orders


def missing_orders(
    *,
    slit_width_mm: float,
    period_mm: float,
    max_order: int,
    tolerance: float = 1.0e-12,
) -> list[int]:


    slit_width_mm = _validate_positive("slit_width_mm", slit_width_mm)
    period_mm = _validate_positive("period_mm", period_mm)

    if not isinstance(max_order, int):
        raise TypeError("max_order must be an integer.")
    if max_order < 1:
        raise ValueError("max_order must be at least 1.")

    ratio = period_mm / slit_width_mm
    missing: set[int] = set()

    max_n = int(math.ceil(max_order / ratio)) + 1

    for n in range(1, max_n + 1):
        order_float = n * ratio
        nearest = int(round(order_float))

        if nearest != 0 and nearest <= max_order:
            if abs(order_float - nearest) <= tolerance:
                missing.add(nearest)
                missing.add(-nearest)

    return sorted(missing)


def angular_dispersion_rad_per_nm(
    *,
    order: int,
    period_mm: float,
    theta_rad: float,
) -> float:


    if not isinstance(order, int):
        raise TypeError("order must be an integer.")
    period_mm = _validate_positive("period_mm", period_mm)
    theta_rad = _validate_finite("theta_rad", theta_rad)

    cos_theta = math.cos(theta_rad)
    if abs(cos_theta) <= 1.0e-15:
        raise ValueError("angular dispersion is singular at cos(theta)=0.")

    return float(order * 1.0e-6 / (period_mm * cos_theta))


def resolving_power(*, order: int, slit_count: int) -> int:


    if not isinstance(order, int):
        raise TypeError("order must be an integer.")
    slit_count = _validate_slit_count(slit_count)

    return abs(order) * slit_count


def spectral_resolution_nm(
    *,
    wavelength_nm: float,
    order: int,
    slit_count: int,
) -> float:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)

    power = resolving_power(order=order, slit_count=slit_count)
    if power <= 0:
        raise ValueError("order must not be zero for spectral resolution.")

    return float(wavelength_nm / power)