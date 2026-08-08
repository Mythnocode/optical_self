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


def _make_source_field(
    *,
    grid: DiffractionGrid,
    complex_amplitude: np.ndarray,
    wavelength_nm: float,
    source_type: str,
    metadata: dict[str, Any],
) -> ScalarField:
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    complex_amplitude = np.asarray(complex_amplitude, dtype=np.complex128)

    if complex_amplitude.shape != grid.shape:
        raise ValueError("complex_amplitude shape must match grid shape.")

    return ScalarField(
        grid=grid,
        complex_amplitude=complex_amplitude,
        wavelength_nm=wavelength_nm,
        aperture_type=source_type,
        metadata={
            **metadata,
            "source_type": source_type,
            "not_physical_result": False,
        },
    )


def plane_wave(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    amplitude: float = 1.0,
    phase_rad: float = 0.0,
) -> ScalarField:


    amplitude = _validate_non_negative("amplitude", amplitude)
    phase_rad = _validate_finite("phase_rad", phase_rad)

    complex_amplitude = (
        np.ones(grid.shape, dtype=np.complex128)
        * amplitude
        * np.exp(1j * phase_rad)
    )

    return _make_source_field(
        grid=grid,
        complex_amplitude=complex_amplitude,
        wavelength_nm=wavelength_nm,
        source_type="plane_wave",
        metadata={
            "amplitude": amplitude,
            "phase_rad": phase_rad,
            "model": "uniform_plane_wave",
        },
    )


def tilted_plane_wave(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    theta_x_rad: float = 0.0,
    theta_y_rad: float = 0.0,
    amplitude: float = 1.0,
    phase_rad: float = 0.0,
) -> ScalarField:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    amplitude = _validate_non_negative("amplitude", amplitude)
    theta_x_rad = _validate_finite("theta_x_rad", theta_x_rad)
    theta_y_rad = _validate_finite("theta_y_rad", theta_y_rad)
    phase_rad = _validate_finite("phase_rad", phase_rad)

    wavelength_mm = wavelength_nm * 1.0e-6
    k = 2.0 * math.pi / wavelength_mm

    phase = (
        k
        * (
            grid.x_mm * math.sin(theta_x_rad)
            + grid.y_mm * math.sin(theta_y_rad)
        )
        + phase_rad
    )

    complex_amplitude = amplitude * np.exp(1j * phase)

    return _make_source_field(
        grid=grid,
        complex_amplitude=complex_amplitude,
        wavelength_nm=wavelength_nm,
        source_type="tilted_plane_wave",
        metadata={
            "amplitude": amplitude,
            "phase_rad": phase_rad,
            "theta_x_rad": theta_x_rad,
            "theta_y_rad": theta_y_rad,
            "wavelength_mm": wavelength_mm,
            "model": "paraxial_tilted_plane_wave",
        },
    )


def spherical_wave(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    source_x_mm: float = 0.0,
    source_y_mm: float = 0.0,
    source_z_mm: float = -100.0,
    amplitude: float = 1.0,
    phase_rad: float = 0.0,
    normalize_peak_amplitude: bool = True,
) -> ScalarField:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    source_x_mm = _validate_finite("source_x_mm", source_x_mm)
    source_y_mm = _validate_finite("source_y_mm", source_y_mm)
    source_z_mm = _validate_finite("source_z_mm", source_z_mm)
    amplitude = _validate_non_negative("amplitude", amplitude)
    phase_rad = _validate_finite("phase_rad", phase_rad)

    wavelength_mm = wavelength_nm * 1.0e-6
    k = 2.0 * math.pi / wavelength_mm

    r_mm = np.sqrt(
        (grid.x_mm - source_x_mm) ** 2
        + (grid.y_mm - source_y_mm) ** 2
        + source_z_mm**2
    )

    if float(np.min(r_mm)) <= 0.0:
        raise ValueError("source position must not coincide with a grid point.")

    complex_amplitude = amplitude * np.exp(1j * (k * r_mm + phase_rad)) / r_mm

    peak_amplitude_before_normalization = float(np.max(np.abs(complex_amplitude)))

    if normalize_peak_amplitude and peak_amplitude_before_normalization > 0.0:
        complex_amplitude = complex_amplitude / peak_amplitude_before_normalization

    return _make_source_field(
        grid=grid,
        complex_amplitude=complex_amplitude,
        wavelength_nm=wavelength_nm,
        source_type="spherical_wave",
        metadata={
            "amplitude": amplitude,
            "phase_rad": phase_rad,
            "source_x_mm": source_x_mm,
            "source_y_mm": source_y_mm,
            "source_z_mm": source_z_mm,
            "wavelength_mm": wavelength_mm,
            "normalize_peak_amplitude": bool(normalize_peak_amplitude),
            "peak_amplitude_before_normalization": peak_amplitude_before_normalization,
            "omits_global_scale": bool(normalize_peak_amplitude),
            "model": "point_source_spherical_wave",
        },
    )


def gaussian_beam(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    waist_radius_mm: float,
    center_x_mm: float = 0.0,
    center_y_mm: float = 0.0,
    amplitude: float = 1.0,
    phase_rad: float = 0.0,
) -> ScalarField:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    waist_radius_mm = _validate_positive("waist_radius_mm", waist_radius_mm)
    center_x_mm = _validate_finite("center_x_mm", center_x_mm)
    center_y_mm = _validate_finite("center_y_mm", center_y_mm)
    amplitude = _validate_non_negative("amplitude", amplitude)
    phase_rad = _validate_finite("phase_rad", phase_rad)

    r2_mm = (grid.x_mm - center_x_mm) ** 2 + (grid.y_mm - center_y_mm) ** 2

    envelope = amplitude * np.exp(-r2_mm / (waist_radius_mm**2))
    complex_amplitude = envelope.astype(np.complex128) * np.exp(1j * phase_rad)

    return _make_source_field(
        grid=grid,
        complex_amplitude=complex_amplitude,
        wavelength_nm=wavelength_nm,
        source_type="gaussian_beam",
        metadata={
            "amplitude": amplitude,
            "phase_rad": phase_rad,
            "waist_radius_mm": waist_radius_mm,
            "center_x_mm": center_x_mm,
            "center_y_mm": center_y_mm,
            "model": "waist_plane_scalar_gaussian_beam",
            "omits_curvature_and_gouy_phase": True,
        },
    )