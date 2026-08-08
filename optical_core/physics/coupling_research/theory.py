
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class GaussianCouplingReference:
    efficiency: float
    mode_size_efficiency: float
    lateral_efficiency: float
    angular_efficiency: float
    dimensionless_lateral_x: float
    dimensionless_lateral_y: float
    dimensionless_tilt_x: float
    dimensionless_tilt_y: float


def gaussian_mode_coupling_reference(
    *,
    wavelength_nm: float,
    incident_radius_x_um: float,
    incident_radius_y_um: float,
    mode_radius_x_um: float,
    mode_radius_y_um: float,
    offset_x_um: float = 0.0,
    offset_y_um: float = 0.0,
    tilt_x_rad: float = 0.0,
    tilt_y_rad: float = 0.0,
    refractive_index: float = 1.0,
) -> GaussianCouplingReference:

    radii = [incident_radius_x_um, incident_radius_y_um, mode_radius_x_um, mode_radius_y_um]
    if any(float(value) <= 0.0 for value in radii) or wavelength_nm <= 0.0:
        raise ValueError("wavelength and Gaussian radii must be positive")
    wavelength_um = float(wavelength_nm) * 1e-3
    k = 2.0 * math.pi * float(refractive_index) / wavelength_um
    size = 1.0
    lateral = 1.0
    angular = 1.0
    u_values: list[float] = []
    q_values: list[float] = []
    for w1, w2, displacement, tilt in (
        (incident_radius_x_um, mode_radius_x_um, offset_x_um, tilt_x_rad),
        (incident_radius_y_um, mode_radius_y_um, offset_y_um, tilt_y_rad),
    ):
        denominator = float(w1) ** 2 + float(w2) ** 2
        size *= 2.0 * float(w1) * float(w2) / denominator
        lateral *= math.exp(-2.0 * float(displacement) ** 2 / denominator)
        angular *= math.exp(
            -(k * float(tilt)) ** 2 * float(w1) ** 2 * float(w2) ** 2 / (2.0 * denominator)
        )
        u_values.append(float(displacement) / float(w2))
        q_values.append(k * float(w2) * float(tilt))
    efficiency = float(np.clip(size * lateral * angular, 0.0, 1.0))
    return GaussianCouplingReference(
        efficiency=efficiency,
        mode_size_efficiency=float(size),
        lateral_efficiency=float(lateral),
        angular_efficiency=float(angular),
        dimensionless_lateral_x=u_values[0],
        dimensionless_lateral_y=u_values[1],
        dimensionless_tilt_x=q_values[0],
        dimensionless_tilt_y=q_values[1],
    )


def gaussian_axial_coupling_reference(
    *,
    axial_offset_um: float,
    rayleigh_range_um: float,
    peak_efficiency: float = 1.0,
) -> float:

    if rayleigh_range_um <= 0.0:
        raise ValueError("rayleigh_range_um must be positive")
    normalized = float(axial_offset_um) / float(rayleigh_range_um)
    return float(np.clip(float(peak_efficiency) / (1.0 + 0.25 * normalized**2), 0.0, 1.0))


def dimensionless_coupling_coordinates(
    *,
    offset_um: float,
    axial_offset_um: float,
    tilt_rad: float,
    mode_radius_um: float,
    rayleigh_range_um: float,
    wavelength_nm: float,
    refractive_index: float = 1.0,
) -> dict[str, float]:
    if mode_radius_um <= 0.0 or rayleigh_range_um <= 0.0 or wavelength_nm <= 0.0:
        raise ValueError("normalization scales must be positive")
    k_per_um = 2.0 * math.pi * float(refractive_index) / (float(wavelength_nm) * 1e-3)
    return {
        "u_lateral": float(offset_um) / float(mode_radius_um),
        "v_axial": float(axial_offset_um) / float(rayleigh_range_um),
        "q_angular": k_per_um * float(mode_radius_um) * float(tilt_rad),
    }


__all__ = [
    "GaussianCouplingReference",
    "gaussian_mode_coupling_reference",
    "gaussian_axial_coupling_reference",
    "dimensionless_coupling_coordinates",
]
