from __future__ import annotations

import math
from typing import Any

import numpy as np

from optical_core.physics.wave.formulas.scalar_diffraction import DiffractionGrid, ScalarField


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite.")
    return value


def _validate_non_negative(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be non-negative and finite.")
    return value


def _validate_finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")
    return value


def _phase_array_for_grid(grid: DiffractionGrid, phase_rad: float | np.ndarray) -> np.ndarray:
    phase = np.asarray(phase_rad, dtype=float)

    if phase.ndim == 0:
        return np.full(grid.shape, float(phase), dtype=float)

    if phase.shape != grid.shape:
        raise ValueError("phase_rad shape must match grid shape.")

    if not np.isfinite(phase).all():
        raise ValueError("phase_rad must contain only finite values.")

    return phase


def phase_to_complex_transmission(
    phase_rad: float | np.ndarray,
    *,
    amplitude: float = 1.0,
) -> np.ndarray:


    amplitude = _validate_non_negative("amplitude", amplitude)
    phase = np.asarray(phase_rad, dtype=float)

    if not np.isfinite(phase).all():
        raise ValueError("phase_rad must contain only finite values.")

    return amplitude * np.exp(1j * phase)


def apply_phase(
    field: ScalarField,
    *,
    phase_rad: float | np.ndarray,
    element_type: str = "phase_element",
    metadata: dict[str, Any] | None = None,
) -> ScalarField:


    phase = _phase_array_for_grid(field.grid, phase_rad)
    transmission = phase_to_complex_transmission(phase, amplitude=1.0)

    new_metadata = {
        **field.metadata,
        "phase_element_type": element_type,
        "input_aperture_type": field.aperture_type,
        "wavelength_nm": float(field.wavelength_nm),
        "preserves_intensity": True,
    }

    if metadata:
        new_metadata.update(metadata)

    new_metadata["not_physical_result"] = False

    return ScalarField(
        grid=field.grid,
        complex_amplitude=field.complex_amplitude * transmission,
        wavelength_nm=field.wavelength_nm,
        aperture_type=f"{field.aperture_type}+{element_type}",
        metadata=new_metadata,
    )


def tilt_phase(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    theta_x_rad: float = 0.0,
    theta_y_rad: float = 0.0,
) -> np.ndarray:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    theta_x_rad = _validate_finite("theta_x_rad", theta_x_rad)
    theta_y_rad = _validate_finite("theta_y_rad", theta_y_rad)

    wavelength_mm = wavelength_nm * 1.0e-6
    k = 2.0 * math.pi / wavelength_mm

    return k * (
        grid.x_mm * math.sin(theta_x_rad)
        + grid.y_mm * math.sin(theta_y_rad)
    )


def thin_lens_phase(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    focal_length_mm: float,
    center_x_mm: float = 0.0,
    center_y_mm: float = 0.0,
) -> np.ndarray:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    focal_length_mm = _validate_positive("focal_length_mm", focal_length_mm)
    center_x_mm = _validate_finite("center_x_mm", center_x_mm)
    center_y_mm = _validate_finite("center_y_mm", center_y_mm)

    wavelength_mm = wavelength_nm * 1.0e-6
    r2_mm = (grid.x_mm - center_x_mm) ** 2 + (grid.y_mm - center_y_mm) ** 2

    return -math.pi * r2_mm / (wavelength_mm * focal_length_mm)


def fresnel_lens_phase(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    focal_length_mm: float,
    center_x_mm: float = 0.0,
    center_y_mm: float = 0.0,
    wrap_to_2pi: bool = True,
) -> np.ndarray:


    phase = thin_lens_phase(
        grid=grid,
        wavelength_nm=wavelength_nm,
        focal_length_mm=focal_length_mm,
        center_x_mm=center_x_mm,
        center_y_mm=center_y_mm,
    )

    if wrap_to_2pi:
        return np.mod(phase, 2.0 * math.pi)

    return phase


def binary_phase_zone_plate_phase(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    focal_length_mm: float,
    center_x_mm: float = 0.0,
    center_y_mm: float = 0.0,
) -> np.ndarray:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    focal_length_mm = _validate_positive("focal_length_mm", focal_length_mm)
    center_x_mm = _validate_finite("center_x_mm", center_x_mm)
    center_y_mm = _validate_finite("center_y_mm", center_y_mm)

    wavelength_mm = wavelength_nm * 1.0e-6

    r2_mm = (grid.x_mm - center_x_mm) ** 2 + (grid.y_mm - center_y_mm) ** 2
    zone_index = np.floor(r2_mm / (wavelength_mm * focal_length_mm)).astype(int)

    return np.where(zone_index % 2 == 0, 0.0, math.pi)