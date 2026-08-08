# 计算系统的透射率与功率闭合。

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class SurfaceTransmission:
    surface_index: int
    material_before: str
    material_after: str
    n_before: float
    n_after: float
    distance_to_next_mm: float
    interface_transmission: float
    bulk_transmission: float
    cumulative_transmission: float


def fresnel_unpolarized_transmission(
    incidence_angle_rad: float,
    n_before: float,
    n_after: float,
) -> float:
    """
    无损耗介质分界面处非偏振光菲涅尔功率透射率计算。
    """
    n1 = _positive_float(n_before, "n_before")
    n2 = _positive_float(n_after, "n_after")
    theta_i = float(incidence_angle_rad)

    if not np.isfinite(theta_i):
        raise ValueError("incidence_angle_rad must be finite")

    sin_i = math.sin(abs(theta_i))
    sin_t = n1 / n2 * sin_i

    if sin_t >= 1.0:
        return 0.0

    cos_i = math.cos(abs(theta_i))
    cos_t = math.sqrt(max(0.0, 1.0 - sin_t * sin_t))

    denom_s = n1 * cos_i + n2 * cos_t
    denom_p = n2 * cos_i + n1 * cos_t
    if abs(denom_s) < 1.0e-15 or abs(denom_p) < 1.0e-15:
        return 0.0

    rs = (n1 * cos_i - n2 * cos_t) / denom_s
    rp = (n2 * cos_i - n1 * cos_t) / denom_p
    reflectance = 0.5 * (rs * rs + rp * rp)
    return float(min(1.0, max(0.0, 1.0 - reflectance)))


def normal_incidence_transmission(n_before: float, n_after: float) -> float:
    return fresnel_unpolarized_transmission(0.0, n_before, n_after)


def bulk_transmission_from_alpha(
    thickness_mm: float,
    attenuation_per_mm: float | None = None,
) -> float:

    thickness = max(0.0, float(thickness_mm or 0.0))
    if attenuation_per_mm is None:
        return 1.0
    alpha = max(0.0, float(attenuation_per_mm or 0.0))
    return float(math.exp(-alpha * thickness))


def material_attenuation_per_mm(material: Any, wavelength_nm: float) -> float:

    if material is None:
        return 0.0

    def read(name: str, default: Any = None) -> Any:
        if isinstance(material, dict):
            return material.get(name, default)
        return getattr(material, name, default)

    for key in ("attenuation_per_mm", "absorption_per_mm", "alpha_per_mm"):
        value = read(key, None)
        if value is not None:
            return max(0.0, float(value))

    transmission_per_mm = read("transmission_per_mm", None)
    if transmission_per_mm is not None:
        t = min(1.0, max(1.0e-15, float(transmission_per_mm)))
        return float(-math.log(t))

    
    alpha_fn = read("alpha", None)
    if callable(alpha_fn):
        return max(0.0, float(alpha_fn(wavelength_nm)))

    return 0.0


def sequence_transmission_budget(system: Any, wavelength_nm: float | None = None) -> tuple[SurfaceTransmission, ...]:

    wavelength = float(wavelength_nm or getattr(system, "wavelength_nm", 550.0))
    surfaces = tuple(getattr(system, "surfaces", ()) or ())
    materials = getattr(system, "materials", {}) or {}

    cumulative = 1.0
    rows: list[SurfaceTransmission] = []

    for index, surface in enumerate(surfaces):
        material_before = str(getattr(surface, "material_before", "AIR") or "AIR")
        material_after = str(getattr(surface, "material_after", "AIR") or "AIR")
        distance_to_next_mm = float(getattr(surface, "distance_to_next_mm", 0.0) or 0.0)

        try:
            n_before = float(system.material_index(material_before, wavelength))
        except Exception:
            n_before = _coerce_material_index(materials, material_before, wavelength)

        try:
            n_after = float(system.material_index(material_after, wavelength))
        except Exception:
            n_after = _coerce_material_index(materials, material_after, wavelength)

        interface = normal_incidence_transmission(n_before, n_after)
        material = _lookup_material(materials, material_after)
        alpha = material_attenuation_per_mm(material, wavelength)
        bulk = bulk_transmission_from_alpha(distance_to_next_mm, alpha)

        cumulative *= interface * bulk
        rows.append(
            SurfaceTransmission(
                surface_index=int(getattr(surface, "index", index)),
                material_before=material_before,
                material_after=material_after,
                n_before=n_before,
                n_after=n_after,
                distance_to_next_mm=distance_to_next_mm,
                interface_transmission=interface,
                bulk_transmission=bulk,
                cumulative_transmission=float(cumulative),
            )
        )

    return tuple(rows)


def uniform_pupil_transmittance(values: Any) -> float:
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    return float(np.clip(np.mean(finite), 0.0, 1.0))


def gaussian_weighted_transmittance(
    radii_mm: Any,
    transmittance: Any,
    waist_mm: float,
) -> float:
    radii = np.asarray(radii_mm, dtype=float)
    values = np.asarray(transmittance, dtype=float)
    if radii.shape != values.shape:
        radii, values = np.broadcast_arrays(radii, values)

    waist = max(float(waist_mm), 1.0e-15)
    weights = np.exp(-2.0 * (radii / waist) ** 2)
    mask = np.isfinite(weights) & np.isfinite(values)
    if not np.any(mask):
        return 0.0
    numerator = float(np.sum(weights[mask] * values[mask], dtype=np.float64))
    denominator = float(np.sum(weights[mask], dtype=np.float64))
    if denominator <= 0.0:
        return 0.0
    return float(np.clip(numerator / denominator, 0.0, 1.0))


def power_closure_error(input_power: float, output_power: float, loss_power: float) -> float:
    input_value = float(input_power or 0.0)
    output_value = float(output_power or 0.0)
    loss_value = float(loss_power or 0.0)
    scale = max(abs(input_value), 1.0e-15)
    return float(abs(input_value - output_value - loss_value) / scale)


def _positive_float(value: Any, label: str) -> float:
    resolved = float(value)
    if not np.isfinite(resolved) or resolved <= 0.0:
        raise ValueError(f"{label} must be a finite positive value")
    return resolved


def _lookup_material(materials: Any, name: str) -> Any:
    key = str(name or "air")
    lower = key.lower()
    if isinstance(materials, dict):
        return materials.get(key) or materials.get(lower)
    return None


def _coerce_material_index(materials: Any, name: str, wavelength_nm: float) -> float:
    key = str(name or "air")
    lower = key.lower()
    if lower in {"air", "vacuum", "none", ""}:
        return 1.0
    try:
        return float(key)
    except ValueError:
        pass
    material = _lookup_material(materials, key)
    if material is None:
        return 1.0
    n_fn = getattr(material, "n", None)
    if callable(n_fn):
        return float(n_fn(wavelength_nm))
    if isinstance(material, dict):
        return float(material.get("refractive_index", 1.0))
    return float(getattr(material, "refractive_index", 1.0))
