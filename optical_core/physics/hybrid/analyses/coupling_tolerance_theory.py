
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np


_MIN_POSITIVE = float(np.finfo(float).tiny)


@dataclass(frozen=True, slots=True)
class GaussianToleranceScales:


    wavelength_vacuum_nm: float
    refractive_index: float
    mode_radius_x_um: float
    mode_radius_y_um: float
    divergence_x_rad: float
    divergence_y_rad: float
    rayleigh_range_x_um: float
    rayleigh_range_y_um: float

    @property
    def wavelength_medium_um(self) -> float:
        return float(self.wavelength_vacuum_nm * 1.0e-3 / self.refractive_index)

    @property
    def effective_rayleigh_range_um(self) -> float:
        return float(math.sqrt(self.rayleigh_range_x_um * self.rayleigh_range_y_um))

    def as_dict(self) -> dict[str, float]:
        return {
            "wavelength_vacuum_nm": float(self.wavelength_vacuum_nm),
            "refractive_index": float(self.refractive_index),
            "mode_radius_x_um": float(self.mode_radius_x_um),
            "mode_radius_y_um": float(self.mode_radius_y_um),
            "divergence_x_rad": float(self.divergence_x_rad),
            "divergence_y_rad": float(self.divergence_y_rad),
            "divergence_x_urad": float(self.divergence_x_rad * 1.0e6),
            "divergence_y_urad": float(self.divergence_y_rad * 1.0e6),
            "rayleigh_range_x_um": float(self.rayleigh_range_x_um),
            "rayleigh_range_y_um": float(self.rayleigh_range_y_um),
            "effective_rayleigh_range_um": float(self.effective_rayleigh_range_um),
        }


def gaussian_tolerance_scales(
    *,
    wavelength_nm: float,
    mode_field_diameter_x_um: float,
    mode_field_diameter_y_um: float | None = None,
    refractive_index: float = 1.0,
) -> GaussianToleranceScales:


    wavelength_vacuum_nm = _positive(wavelength_nm, "wavelength_nm")
    n = _positive(refractive_index, "refractive_index")
    mfd_x = _positive(mode_field_diameter_x_um, "mode_field_diameter_x_um")
    mfd_y = _positive(
        mode_field_diameter_y_um if mode_field_diameter_y_um is not None else mfd_x,
        "mode_field_diameter_y_um",
    )
    wx = 0.5 * mfd_x
    wy = 0.5 * mfd_y
    wavelength_medium_um = wavelength_vacuum_nm * 1.0e-3 / n
    theta_x = wavelength_medium_um / (math.pi * wx)
    theta_y = wavelength_medium_um / (math.pi * wy)
    zr_x = math.pi * wx * wx / wavelength_medium_um
    zr_y = math.pi * wy * wy / wavelength_medium_um
    return GaussianToleranceScales(
        wavelength_vacuum_nm=wavelength_vacuum_nm,
        refractive_index=n,
        mode_radius_x_um=wx,
        mode_radius_y_um=wy,
        divergence_x_rad=theta_x,
        divergence_y_rad=theta_y,
        rayleigh_range_x_um=zr_x,
        rayleigh_range_y_um=zr_y,
    )


def gaussian_lateral_relative_efficiency(offset_um: Any, mode_radius_um: float) -> np.ndarray | float:


    radius = _positive(mode_radius_um, "mode_radius_um")
    values = np.asarray(offset_um, dtype=float)
    result = np.exp(-np.square(values / radius))
    return _restore_scalar(offset_um, result)


def gaussian_angular_relative_efficiency(
    tilt_rad: Any,
    *,
    wavelength_nm: float,
    mode_radius_um: float,
    refractive_index: float = 1.0,
) -> np.ndarray | float:


    wavelength_medium_um = _positive(wavelength_nm, "wavelength_nm") * 1.0e-3 / _positive(
        refractive_index, "refractive_index"
    )
    radius = _positive(mode_radius_um, "mode_radius_um")
    theta0 = wavelength_medium_um / (math.pi * radius)
    values = np.asarray(tilt_rad, dtype=float)
    result = np.exp(-np.square(values / theta0))
    return _restore_scalar(tilt_rad, result)


def gaussian_axial_relative_efficiency(
    offset_z_um: Any,
    *,
    rayleigh_range_x_um: float,
    rayleigh_range_y_um: float | None = None,
) -> np.ndarray | float:


    zrx = _positive(rayleigh_range_x_um, "rayleigh_range_x_um")
    zry = _positive(rayleigh_range_y_um if rayleigh_range_y_um is not None else zrx, "rayleigh_range_y_um")
    values = np.asarray(offset_z_um, dtype=float)
    factor_x = 1.0 + np.square(values / (2.0 * zrx))
    factor_y = 1.0 + np.square(values / (2.0 * zry))
    result = 1.0 / np.sqrt(factor_x * factor_y)
    return _restore_scalar(offset_z_um, result)


def relative_efficiency_for_loss_db(loss_db: float) -> float:


    loss = float(loss_db)
    if not math.isfinite(loss) or loss < 0.0:
        raise ValueError("loss_db must be finite and non-negative")
    return float(10.0 ** (-loss / 10.0))


def lateral_tolerance_um(*, mode_radius_um: float, relative_efficiency: float) -> float:
    q = _unit_interval_open(relative_efficiency, "relative_efficiency")
    return float(_positive(mode_radius_um, "mode_radius_um") * math.sqrt(-math.log(q)))


def angular_tolerance_rad(
    *,
    wavelength_nm: float,
    mode_radius_um: float,
    relative_efficiency: float,
    refractive_index: float = 1.0,
) -> float:
    q = _unit_interval_open(relative_efficiency, "relative_efficiency")
    wavelength_medium_um = _positive(wavelength_nm, "wavelength_nm") * 1.0e-3 / _positive(
        refractive_index, "refractive_index"
    )
    theta0 = wavelength_medium_um / (math.pi * _positive(mode_radius_um, "mode_radius_um"))
    return float(theta0 * math.sqrt(-math.log(q)))


def axial_tolerance_um(
    *,
    rayleigh_range_um: float,
    relative_efficiency: float,
) -> float:


    q = _unit_interval_open(relative_efficiency, "relative_efficiency")
    zr = _positive(rayleigh_range_um, "rayleigh_range_um")
    return float(2.0 * zr * math.sqrt(1.0 / q - 1.0))


def efficiency_ratio_to_loss_db(relative_efficiency: Any) -> np.ndarray | float:
    values = np.asarray(relative_efficiency, dtype=float)
    safe = np.maximum(values, _MIN_POSITIVE)
    result = -10.0 * np.log10(safe)
    return _restore_scalar(relative_efficiency, result)


def _positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def _unit_interval_open(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return number


def _restore_scalar(original: Any, result: np.ndarray) -> np.ndarray | float:
    if np.isscalar(original):
        return float(result)
    return result
