from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class GaussianBeamParameters:


    wavelength_nm: float
    waist_x_mm: float
    waist_y_mm: float
    amplitude: complex = 1.0 + 0.0j
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    phase_rad: float = 0.0
    refractive_index: float = 1.0
    beam_quality_m2: float = 1.0

    def __post_init__(self) -> None:
        if float(self.beam_quality_m2) < 1.0:
            raise ValueError("beam_quality_m2 must be >= 1.0")

    @property
    def wavelength_mm(self) -> float:
        return float(self.wavelength_nm) * 1e-6 / float(self.refractive_index)

    @property
    def circular_waist_mm(self) -> float:
        return math.sqrt(max(self.waist_x_mm, 0.0) * max(self.waist_y_mm, 0.0))


def waist_from_divergence(
    *,
    wavelength_nm: float,
    divergence_half_angle_rad: float,
    refractive_index: float = 1.0,
    beam_quality_m2: float = 1.0,
) -> float:
    theta = max(float(divergence_half_angle_rad), 1e-15)
    wavelength_mm = float(wavelength_nm) * 1e-6 / float(refractive_index)
    m2 = max(float(beam_quality_m2), 1.0)
    return float(m2 * wavelength_mm / (math.pi * theta))


def rayleigh_range_mm(
    *,
    waist_mm: float,
    wavelength_nm: float,
    refractive_index: float = 1.0,
    beam_quality_m2: float = 1.0,
) -> float:
    wavelength_mm = float(wavelength_nm) * 1e-6 / float(refractive_index)
    m2 = max(float(beam_quality_m2), 1.0)
    return float(math.pi * float(waist_mm) ** 2 / (m2 * wavelength_mm))


def beam_radius_mm(
    *,
    z_mm: float,
    waist_mm: float,
    wavelength_nm: float,
    refractive_index: float = 1.0,
    beam_quality_m2: float = 1.0,
) -> float:
    zr = rayleigh_range_mm(
        waist_mm=waist_mm,
        wavelength_nm=wavelength_nm,
        refractive_index=refractive_index,
        beam_quality_m2=beam_quality_m2,
    )
    return float(waist_mm * math.sqrt(1.0 + (float(z_mm) / zr) ** 2))


def radius_curvature_mm(
    *,
    z_mm: float,
    waist_mm: float,
    wavelength_nm: float,
    refractive_index: float = 1.0,
    beam_quality_m2: float = 1.0,
) -> float:
    z = float(z_mm)
    if abs(z) < 1e-15:
        return math.inf
    zr = rayleigh_range_mm(
        waist_mm=waist_mm,
        wavelength_nm=wavelength_nm,
        refractive_index=refractive_index,
        beam_quality_m2=beam_quality_m2,
    )
    return float(z * (1.0 + (zr / z) ** 2))


def gouy_phase_rad(
    *,
    z_mm: float,
    waist_mm: float,
    wavelength_nm: float,
    refractive_index: float = 1.0,
    beam_quality_m2: float = 1.0,
) -> float:
    zr = rayleigh_range_mm(
        waist_mm=waist_mm,
        wavelength_nm=wavelength_nm,
        refractive_index=refractive_index,
        beam_quality_m2=beam_quality_m2,
    )
    return float(math.atan2(float(z_mm), zr))


def gaussian_field_at_plane(
    x_mm: Any,
    y_mm: Any,
    params: GaussianBeamParameters,
    *,
    axial_z_mm: float = 0.0,
    include_carrier_phase: bool = False,
) -> np.ndarray:


    x = np.asarray(x_mm, dtype=float) - params.center_x_mm
    y = np.asarray(y_mm, dtype=float) - params.center_y_mm

    wx = beam_radius_mm(
        z_mm=axial_z_mm,
        waist_mm=params.waist_x_mm,
        wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index,
        beam_quality_m2=params.beam_quality_m2,
    )
    wy = beam_radius_mm(
        z_mm=axial_z_mm,
        waist_mm=params.waist_y_mm,
        wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index,
        beam_quality_m2=params.beam_quality_m2,
    )
    safe_wx = max(wx, 1e-15)
    safe_wy = max(wy, 1e-15)
    amplitude_scale = math.sqrt(
        max(float(params.waist_x_mm), 0.0)
        * max(float(params.waist_y_mm), 0.0)
        / (safe_wx * safe_wy)
    )
    envelope = amplitude_scale * np.exp(-((x / safe_wx) ** 2 + (y / safe_wy) ** 2))

    phase: np.ndarray | float = float(params.phase_rad)
    if abs(axial_z_mm) > 1e-15:
        k = 2.0 * math.pi / params.wavelength_mm
        rc_x = radius_curvature_mm(
            z_mm=axial_z_mm,
            waist_mm=params.waist_x_mm,
            wavelength_nm=params.wavelength_nm,
            refractive_index=params.refractive_index,
            beam_quality_m2=params.beam_quality_m2,
        )
        rc_y = radius_curvature_mm(
            z_mm=axial_z_mm,
            waist_mm=params.waist_y_mm,
            wavelength_nm=params.wavelength_nm,
            refractive_index=params.refractive_index,
            beam_quality_m2=params.beam_quality_m2,
        )
        phase = np.full(np.broadcast(x, y).shape, float(params.phase_rad), dtype=float)
        if include_carrier_phase:
            phase += k * float(axial_z_mm)
        if math.isfinite(rc_x):
            phase += k * x**2 / (2.0 * rc_x)
        if math.isfinite(rc_y):
            phase += k * y**2 / (2.0 * rc_y)
        phase -= 0.5 * (
            gouy_phase_rad(
                z_mm=axial_z_mm,
                waist_mm=params.waist_x_mm,
                wavelength_nm=params.wavelength_nm,
                refractive_index=params.refractive_index,
                beam_quality_m2=params.beam_quality_m2,
            )
            + gouy_phase_rad(
                z_mm=axial_z_mm,
                waist_mm=params.waist_y_mm,
                wavelength_nm=params.wavelength_nm,
                refractive_index=params.refractive_index,
                beam_quality_m2=params.beam_quality_m2,
            )
        )
    return params.amplitude * envelope * np.exp(1j * phase)


def gaussian_intensity_at_plane(
    x_mm: Any,
    y_mm: Any,
    params: GaussianBeamParameters,
    *,
    axial_z_mm: float = 0.0,
) -> np.ndarray:
    
    field = gaussian_field_at_plane(x_mm, y_mm, params, axial_z_mm=axial_z_mm)
    return np.abs(field) ** 2


def intensity_integral_mm2(intensity: Any, *, dx_mm: float, dy_mm: float) -> float:
    return float(np.sum(np.asarray(intensity, dtype=float)) * float(dx_mm) * float(dy_mm))


def sample_gaussian_beam(
    params: GaussianBeamParameters,
    *,
    grid_size: int = 65,
    extent_x_mm: float | None = None,
    extent_y_mm: float | None = None,
    axial_z_mm: float = 0.0,
    include_carrier_phase: bool = False,
) -> dict[str, np.ndarray]:
    n = max(3, int(grid_size))
    current_wx = beam_radius_mm(
        z_mm=axial_z_mm,
        waist_mm=params.waist_x_mm,
        wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index,
        beam_quality_m2=params.beam_quality_m2,
    )
    current_wy = beam_radius_mm(
        z_mm=axial_z_mm,
        waist_mm=params.waist_y_mm,
        wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index,
        beam_quality_m2=params.beam_quality_m2,
    )
    extent_x = float(extent_x_mm if extent_x_mm is not None else 6.0 * current_wx)
    extent_y = float(extent_y_mm if extent_y_mm is not None else 6.0 * current_wy)
    x = np.linspace(-extent_x / 2.0, extent_x / 2.0, n)
    y = np.linspace(-extent_y / 2.0, extent_y / 2.0, n)
    xx, yy = np.meshgrid(x, y, indexing="xy")
    field = gaussian_field_at_plane(
        xx,
        yy,
        params,
        axial_z_mm=axial_z_mm,
        include_carrier_phase=include_carrier_phase,
    )
    intensity = np.abs(field) ** 2
    return {
        "x_mm": x,
        "y_mm": y,
        "field": field,
        "intensity": intensity,
        "axial_z_mm": np.asarray(float(axial_z_mm)),
        "carrier_phase_included": np.asarray(bool(include_carrier_phase)),
        "field_normalization": np.asarray("axial_power_conserving"),
    }
