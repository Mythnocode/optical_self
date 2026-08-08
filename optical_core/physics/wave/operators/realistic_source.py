
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence
import math
import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.operators.gaussian_beam import (
    beam_radius_mm,
    radius_curvature_mm,
    gouy_phase_rad,
)


MapLike = np.ndarray | Callable[[np.ndarray, np.ndarray], np.ndarray] | None


@dataclass(frozen=True, slots=True)
class RealisticGaussianSourceParameters:
    wavelength_nm: float
    waist_x_mm: float
    waist_y_mm: float
    waist_position_x_mm: float = 0.0
    waist_position_y_mm: float = 0.0
    beam_quality_m2_x: float = 1.0
    beam_quality_m2_y: float = 1.0
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    axis_tilt_x_rad: float = 0.0
    axis_tilt_y_rad: float = 0.0
    refractive_index: float = 1.0
    total_power: float = 1.0
    power_drift_fraction: float = 0.0
    phase_offset_rad: float = 0.0
    amplitude_map: MapLike = None
    phase_map_rad: MapLike = None

    def __post_init__(self) -> None:
        for name in ("wavelength_nm", "waist_x_mm", "waist_y_mm", "refractive_index"):
            if not np.isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive and finite")
        if float(self.beam_quality_m2_x) < 1.0 or float(self.beam_quality_m2_y) < 1.0:
            raise ValueError("beam_quality_m2_x/y must be >= 1")
        if float(self.total_power) < 0.0 or float(self.power_drift_fraction) <= -1.0:
            raise ValueError("source power must remain non-negative")


def _map_values(model: MapLike, x: np.ndarray, y: np.ndarray, *, default: float) -> np.ndarray:
    if model is None:
        return np.full(np.broadcast(x, y).shape, default, dtype=float)
    values = model(x, y) if callable(model) else np.asarray(model)
    values = np.asarray(values, dtype=float)
    if values.shape != np.broadcast(x, y).shape:
        raise ValueError("measured amplitude/phase map shape must match the requested grid")
    return values


def realistic_gaussian_field(
    grid: SamplingGrid2D,
    params: RealisticGaussianSourceParameters,
    *,
    axial_z_mm: float = 0.0,
    normalize_to_power: bool = True,
) -> ScalarField2D:

    yy, xx = np.meshgrid(grid.y_mm, grid.x_mm, indexing="ij")
    z = float(axial_z_mm)
    zx = z - float(params.waist_position_x_mm)
    zy = z - float(params.waist_position_y_mm)
    cx = float(params.center_x_mm) + z * math.tan(float(params.axis_tilt_x_rad))
    cy = float(params.center_y_mm) + z * math.tan(float(params.axis_tilt_y_rad))
    x = xx - cx
    y = yy - cy
    wx = beam_radius_mm(
        z_mm=zx, waist_mm=params.waist_x_mm, wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index, beam_quality_m2=params.beam_quality_m2_x,
    )
    wy = beam_radius_mm(
        z_mm=zy, waist_mm=params.waist_y_mm, wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index, beam_quality_m2=params.beam_quality_m2_y,
    )
    envelope = math.sqrt(params.waist_x_mm * params.waist_y_mm / max(wx * wy, 1.0e-30)) * np.exp(
        -(x / max(wx, 1.0e-30)) ** 2 - (y / max(wy, 1.0e-30)) ** 2
    )
    amplitude_map = np.maximum(_map_values(params.amplitude_map, xx, yy, default=1.0), 0.0)
    wavelength_mm = float(params.wavelength_nm) * 1.0e-6 / float(params.refractive_index)
    k = 2.0 * math.pi / wavelength_mm
    phase = np.full(xx.shape, float(params.phase_offset_rad), dtype=float)
    rx = radius_curvature_mm(
        z_mm=zx, waist_mm=params.waist_x_mm, wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index, beam_quality_m2=params.beam_quality_m2_x,
    )
    ry = radius_curvature_mm(
        z_mm=zy, waist_mm=params.waist_y_mm, wavelength_nm=params.wavelength_nm,
        refractive_index=params.refractive_index, beam_quality_m2=params.beam_quality_m2_y,
    )
    if math.isfinite(rx):
        phase += k * x**2 / (2.0 * rx)
    if math.isfinite(ry):
        phase += k * y**2 / (2.0 * ry)
    phase -= 0.5 * (
        gouy_phase_rad(z_mm=zx, waist_mm=params.waist_x_mm, wavelength_nm=params.wavelength_nm,
                       refractive_index=params.refractive_index, beam_quality_m2=params.beam_quality_m2_x)
        + gouy_phase_rad(z_mm=zy, waist_mm=params.waist_y_mm, wavelength_nm=params.wavelength_nm,
                         refractive_index=params.refractive_index, beam_quality_m2=params.beam_quality_m2_y)
    )
    phase += k * (math.sin(params.axis_tilt_x_rad) * xx + math.sin(params.axis_tilt_y_rad) * yy)
    phase += _map_values(params.phase_map_rad, xx, yy, default=0.0)
    values = envelope * amplitude_map * np.exp(1j * phase)
    requested_power = float(params.total_power) * (1.0 + float(params.power_drift_fraction))
    current_power = float(np.sum(np.abs(values) ** 2) * abs(grid.dx_mm * grid.dy_mm))
    if normalize_to_power and current_power > 0.0:
        values *= math.sqrt(max(requested_power, 0.0) / current_power)
        current_power = requested_power
    return ScalarField2D(
        values=np.asarray(values, dtype=np.complex128), grid=grid,
        wavelength_nm=float(params.wavelength_nm), refractive_index=float(params.refractive_index),
        z_mm=z, integrated_power=float(current_power),
    )


__all__ = ["RealisticGaussianSourceParameters", "realistic_gaussian_field"]
