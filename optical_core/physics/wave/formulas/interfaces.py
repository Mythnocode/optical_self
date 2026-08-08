from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from optical_core.physics.wave.formulas.materials import OpticalMaterial


@dataclass(frozen=True)
class FresnelCoefficients:


    polarization: str
    n1: float
    n2: float
    incident_angle_rad: float
    transmitted_angle_rad: float | None
    r: complex
    t: complex
    reflectance: float
    transmittance: float
    total_internal_reflection: bool
    reflection_phase_rad: float
    transmission_phase_rad: float
    metadata: dict[str, Any]


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be positive and finite.")
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


def _as_real_index(
    index: float | OpticalMaterial,
    *,
    wavelength_nm: float | None = None,
    name: str,
) -> float:
    """把数值折射率或材料对象转换为实折射率。"""

    if hasattr(index, "n_complex"):
        if wavelength_nm is None:
            raise ValueError("wavelength_nm is required when index is a material.")
        value = complex(index.n_complex(wavelength_nm))  
    else:
        value = complex(index)  

    if not math.isfinite(value.real) or not math.isfinite(value.imag):
        raise ValueError(f"{name} must be finite.")

    if abs(value.imag) > 1.0e-14:
        raise ValueError(
            f"{name} must be lossless in this Fresnel core version; "
            "absorbing-interface support should be added separately."
        )

    if value.real <= 0.0:
        raise ValueError(f"{name} must be positive.")

    return float(value.real)


def refractive_index_value(
    index: float | OpticalMaterial,
    *,
    wavelength_nm: float | None = None,
) -> float:
    """读取数值折射率或材料对象折射率。"""

    return _as_real_index(index, wavelength_nm=wavelength_nm, name="index")


def snell_angle_rad(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    incident_angle_rad: float,
    wavelength_nm: float | None = None,
) -> float:


    n1_value = _as_real_index(n1, wavelength_nm=wavelength_nm, name="n1")
    n2_value = _as_real_index(n2, wavelength_nm=wavelength_nm, name="n2")
    incident_angle_rad = _validate_angle("incident_angle_rad", incident_angle_rad)

    sin_t = n1_value * math.sin(incident_angle_rad) / n2_value

    if abs(sin_t) > 1.0:
        raise ValueError("total internal reflection: transmitted angle is not real.")

    sin_t = max(-1.0, min(1.0, sin_t))
    return float(math.asin(sin_t))


def critical_angle_rad(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    wavelength_nm: float | None = None,
) -> float | None:


    n1_value = _as_real_index(n1, wavelength_nm=wavelength_nm, name="n1")
    n2_value = _as_real_index(n2, wavelength_nm=wavelength_nm, name="n2")

    if n1_value <= n2_value:
        return None

    return float(math.asin(n2_value / n1_value))


def brewster_angle_rad(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    wavelength_nm: float | None = None,
) -> float:


    n1_value = _as_real_index(n1, wavelength_nm=wavelength_nm, name="n1")
    n2_value = _as_real_index(n2, wavelength_nm=wavelength_nm, name="n2")

    return float(math.atan(n2_value / n1_value))


def normal_incidence_reflectance(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    wavelength_nm: float | None = None,
) -> float:
    """正入射反射率。"""

    n1_value = _as_real_index(n1, wavelength_nm=wavelength_nm, name="n1")
    n2_value = _as_real_index(n2, wavelength_nm=wavelength_nm, name="n2")

    r = (n1_value - n2_value) / (n1_value + n2_value)
    return float(r * r)


def _phase(value: complex) -> float:
    return float(math.atan2(value.imag, value.real))


def fresnel_coefficients(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    incident_angle_rad: float,
    polarization: str,
    wavelength_nm: float | None = None,
) -> FresnelCoefficients:


    n1_value = _as_real_index(n1, wavelength_nm=wavelength_nm, name="n1")
    n2_value = _as_real_index(n2, wavelength_nm=wavelength_nm, name="n2")
    incident_angle_rad = _validate_angle("incident_angle_rad", incident_angle_rad)

    polarization = polarization.lower().strip()
    if polarization not in {"s", "p"}:
        raise ValueError('polarization must be "s" or "p".')

    sin_i = math.sin(incident_angle_rad)
    cos_i = math.cos(incident_angle_rad)

    sin_t = n1_value * sin_i / n2_value

    total_internal_reflection = abs(sin_t) > 1.0

    if total_internal_reflection:
        transmitted_angle_rad = None
        cos_t_complex = 1j * math.sqrt(sin_t * sin_t - 1.0)
    else:
        sin_t = max(-1.0, min(1.0, sin_t))
        transmitted_angle_rad = float(math.asin(sin_t))
        cos_t_complex = complex(math.sqrt(max(0.0, 1.0 - sin_t * sin_t)), 0.0)

    cos_i_complex = complex(cos_i, 0.0)

    if polarization == "s":
        denominator = n1_value * cos_i_complex + n2_value * cos_t_complex
        r = (n1_value * cos_i_complex - n2_value * cos_t_complex) / denominator
        t = (2.0 * n1_value * cos_i_complex) / denominator
    else:
        denominator = n2_value * cos_i_complex + n1_value * cos_t_complex
        r = (n2_value * cos_i_complex - n1_value * cos_t_complex) / denominator
        t = (2.0 * n1_value * cos_i_complex) / denominator

    reflectance = float(abs(r) ** 2)

    if total_internal_reflection:
        transmittance = 0.0
        reflectance = 1.0
    else:
        cos_t = float(cos_t_complex.real)
        transmittance = float(
            (n2_value * cos_t) / (n1_value * cos_i) * abs(t) ** 2
        )

        if abs(reflectance + transmittance - 1.0) < 1.0e-12:
            transmittance = 1.0 - reflectance

    metadata = {
        "model": "fresnel_single_interface",
        "n1": float(n1_value),
        "n2": float(n2_value),
        "incident_angle_rad": float(incident_angle_rad),
        "transmitted_angle_rad": transmitted_angle_rad,
        "polarization": polarization,
        "total_internal_reflection": bool(total_internal_reflection),
        "wavelength_nm": wavelength_nm,
        "lossless_media_only": True,
        "not_physical_result": False,
    }

    return FresnelCoefficients(
        polarization=polarization,
        n1=n1_value,
        n2=n2_value,
        incident_angle_rad=incident_angle_rad,
        transmitted_angle_rad=transmitted_angle_rad,
        r=complex(r),
        t=complex(t),
        reflectance=reflectance,
        transmittance=transmittance,
        total_internal_reflection=bool(total_internal_reflection),
        reflection_phase_rad=_phase(complex(r)),
        transmission_phase_rad=_phase(complex(t)),
        metadata=metadata,
    )


def fresnel_unpolarized_reflectance(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    incident_angle_rad: float,
    wavelength_nm: float | None = None,
) -> float:


    s = fresnel_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        polarization="s",
        wavelength_nm=wavelength_nm,
    )
    p = fresnel_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        polarization="p",
        wavelength_nm=wavelength_nm,
    )

    return float(0.5 * (s.reflectance + p.reflectance))


def fresnel_unpolarized_transmittance(
    *,
    n1: float | OpticalMaterial,
    n2: float | OpticalMaterial,
    incident_angle_rad: float,
    wavelength_nm: float | None = None,
) -> float:


    s = fresnel_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        polarization="s",
        wavelength_nm=wavelength_nm,
    )
    p = fresnel_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        polarization="p",
        wavelength_nm=wavelength_nm,
    )

    return float(0.5 * (s.transmittance + p.transmittance))