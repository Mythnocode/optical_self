from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from optical_core.physics.wave.formulas.scalar_diffraction import DiffractionGrid


@dataclass(frozen=True)
class InterferenceResult:
    grid: DiffractionGrid
    complex_amplitude: np.ndarray
    amplitude: np.ndarray
    phase_rad: np.ndarray
    intensity: np.ndarray
    wavelength_nm: float
    visibility: float
    metadata: dict[str, Any]


def intensity_from_complex_field(field: np.ndarray) -> np.ndarray:
    field = np.asarray(field, dtype=np.complex128)
    return np.abs(field) ** 2


def _validate_fields(fields: Sequence[np.ndarray]) -> list[np.ndarray]:
    if not fields:
        raise ValueError("fields must not be empty.")

    arrays = [np.asarray(field, dtype=np.complex128) for field in fields]
    first_shape = arrays[0].shape

    for array in arrays:
        if array.shape != first_shape:
            raise ValueError("all fields must have the same shape.")

    return arrays


def coherent_sum(fields: Sequence[np.ndarray]) -> np.ndarray:
    """相干叠加：先加复振幅，再取强度。"""

    arrays = _validate_fields(fields)
    total = np.zeros_like(arrays[0], dtype=np.complex128)

    for field in arrays:
        total = total + field

    return total


def incoherent_sum(fields: Sequence[np.ndarray]) -> np.ndarray:
    """非相干叠加：直接加光强。"""

    arrays = _validate_fields(fields)
    total_intensity = np.zeros(arrays[0].shape, dtype=float)

    for field in arrays:
        total_intensity = total_intensity + intensity_from_complex_field(field)

    return total_intensity


def visibility_from_amplitudes(amplitude1: float, amplitude2: float) -> float:
    """两束完全相干、同偏振光的条纹可见度。"""

    if amplitude1 < 0 or amplitude2 < 0:
        raise ValueError("amplitudes must be non-negative.")

    denominator = amplitude1 * amplitude1 + amplitude2 * amplitude2
    if denominator == 0:
        return 0.0

    return float(2.0 * amplitude1 * amplitude2 / denominator)


def two_plane_wave_interference(
    *,
    grid: DiffractionGrid,
    wavelength_nm: float,
    amplitude1: float = 1.0,
    amplitude2: float = 1.0,
    theta1_x_rad: float = 0.0,
    theta2_x_rad: float = 0.0,
    theta1_y_rad: float = 0.0,
    theta2_y_rad: float = 0.0,
    phase1_rad: float = 0.0,
    phase2_rad: float = 0.0,
    normalize: bool = True,
) -> InterferenceResult:
    """两列平面波干涉。

    适合作为干涉核心的第一个具体模型。
    """

    if wavelength_nm <= 0:
        raise ValueError("wavelength_nm must be positive.")
    if amplitude1 < 0 or amplitude2 < 0:
        raise ValueError("amplitudes must be non-negative.")

    wavelength_mm = wavelength_nm * 1.0e-6
    k = 2.0 * math.pi / wavelength_mm

    phase1 = (
        k
        * (
            grid.x_mm * math.sin(theta1_x_rad)
            + grid.y_mm * math.sin(theta1_y_rad)
        )
        + phase1_rad
    )

    phase2 = (
        k
        * (
            grid.x_mm * math.sin(theta2_x_rad)
            + grid.y_mm * math.sin(theta2_y_rad)
        )
        + phase2_rad
    )

    field1 = amplitude1 * np.exp(1j * phase1)
    field2 = amplitude2 * np.exp(1j * phase2)

    complex_amplitude = coherent_sum([field1, field2])
    intensity = intensity_from_complex_field(complex_amplitude)

    if normalize:
        peak = float(np.max(intensity))
        if peak > 0:
            complex_amplitude = complex_amplitude / math.sqrt(peak)
            intensity = intensity_from_complex_field(complex_amplitude)

    amplitude = np.abs(complex_amplitude)
    phase_rad = np.angle(complex_amplitude)
    visibility = visibility_from_amplitudes(amplitude1, amplitude2)

    delta_sin_x = math.sin(theta2_x_rad) - math.sin(theta1_x_rad)
    if abs(delta_sin_x) > 1.0e-15:
        fringe_spacing_x_mm = wavelength_mm / abs(delta_sin_x)
    else:
        fringe_spacing_x_mm = math.inf

    metadata = {
        "model": "two_plane_wave_interference",
        "coherence_mode": "coherent",
        "wavelength_nm": float(wavelength_nm),
        "wavelength_mm": float(wavelength_mm),
        "theta1_x_rad": float(theta1_x_rad),
        "theta2_x_rad": float(theta2_x_rad),
        "theta1_y_rad": float(theta1_y_rad),
        "theta2_y_rad": float(theta2_y_rad),
        "phase1_rad": float(phase1_rad),
        "phase2_rad": float(phase2_rad),
        "fringe_spacing_x_mm": float(fringe_spacing_x_mm),
        "intensity_normalized": bool(normalize),
        "not_physical_result": False,
    }

    return InterferenceResult(
        grid=grid,
        complex_amplitude=complex_amplitude,
        amplitude=amplitude,
        phase_rad=phase_rad,
        intensity=intensity,
        wavelength_nm=wavelength_nm,
        visibility=visibility,
        metadata=metadata,
    )