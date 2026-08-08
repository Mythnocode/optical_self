# 实现部分相干光场和光谱脉冲的核心计算。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import math

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class CoherentMode:
    field: ScalarField2D
    weight: float
    label: str = ""

    def __post_init__(self) -> None:
        if not np.isfinite(self.weight) or float(self.weight) < 0.0:
            raise ValueError("coherent-mode weight must be non-negative and finite")


@dataclass(frozen=True, slots=True)
class CoherenceEnsembleResult:
    intensity: np.ndarray
    total_power: float
    effective_mode_number: float
    normalized_weights: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)


def incoherent_mode_sum(modes: Iterable[CoherentMode]) -> CoherenceEnsembleResult:
    items = tuple(modes)
    if not items:
        raise ValueError("at least one coherent mode is required")
    reference = items[0].field
    intensity = np.zeros_like(np.abs(reference.values) ** 2, dtype=float)
    weights = np.asarray([float(item.weight) for item in items], dtype=float)
    if float(np.sum(weights)) <= 0.0:
        raise ValueError("coherent-mode weights cannot all be zero")
    weights = weights / np.sum(weights)
    for item, weight in zip(items, weights, strict=True):
        if item.field.values.shape != reference.values.shape:
            raise ValueError("coherent modes must share a grid")
        intensity += weight * np.abs(item.field.values) ** 2
    area = abs(float(reference.grid.dx_mm) * float(reference.grid.dy_mm))
    total_power = float(np.sum(intensity) * area)
    effective_mode_number = float(1.0 / np.sum(weights**2))
    return CoherenceEnsembleResult(
        intensity=intensity,
        total_power=total_power,
        effective_mode_number=effective_mode_number,
        normalized_weights=weights,
        metadata={"model": "coherent_mode_decomposition", "mode_count": len(items)},
    )


def gaussian_schell_mode_weights(
    *,
    beam_radius_mm: float,
    coherence_radius_mm: float,
    max_order: int = 12,
    weight_floor: float = 1e-10,
) -> np.ndarray:
    """
    返回可分离厄米 - 高斯相干模态权重。
    几何谱是高斯谢尔模型光源稳定的工程表征形式。当相干半径极大时，系统退化为单一相干模态；随着空间相干性降低，模态数量会增多。
    """
    if beam_radius_mm <= 0.0 or coherence_radius_mm <= 0.0:
        raise ValueError("beam and coherence radii must be positive")
    ratio = float(beam_radius_mm) / float(coherence_radius_mm)
    q = (math.sqrt(1.0 + 2.0 * ratio * ratio) - 1.0) / (math.sqrt(1.0 + 2.0 * ratio * ratio) + 1.0)
    one_d = np.asarray([(1.0 - q) * q**n for n in range(max_order + 1)], dtype=float)
    two_d = np.outer(one_d, one_d)
    two_d[two_d < weight_floor] = 0.0
    return two_d / np.sum(two_d)


@dataclass(frozen=True, slots=True)
class PulsePropagationResult:
    time_s: np.ndarray
    temporal_field: np.ndarray
    temporal_intensity: np.ndarray
    spectral_field_out: np.ndarray
    rms_duration_s: float
    peak_time_s: float
    energy_frequency_domain: float
    energy_time_domain: float
    metadata: dict[str, Any] = field(default_factory=dict)


def propagate_spectral_pulse(
    *,
    angular_frequency_rad_s: np.ndarray,
    spectral_field: np.ndarray,
    length_m: float = 0.0,
    beta0_rad_per_m: float = 0.0,
    beta1_s_per_m: float = 0.0,
    beta2_s2_per_m: float = 0.0,
    beta3_s3_per_m: float = 0.0,
    transfer_function: np.ndarray | None = None,
) -> PulsePropagationResult:
    omega = np.asarray(angular_frequency_rad_s, dtype=float).reshape(-1)
    spectrum = np.asarray(spectral_field, dtype=np.complex128).reshape(-1)
    if omega.size != spectrum.size or omega.size < 4:
        raise ValueError("frequency and spectrum arrays must have equal length >= 4")
    differences = np.diff(omega)
    if not np.all(differences > 0.0) or not np.allclose(differences, differences[0], rtol=1e-7, atol=0.0):
        raise ValueError("angular frequency grid must be strictly increasing and uniform")
    omega0 = float(np.sum(omega * np.abs(spectrum) ** 2) / max(np.sum(np.abs(spectrum) ** 2), 1e-30))
    detuning = omega - omega0
    phase = float(length_m) * (
        float(beta0_rad_per_m)
        + float(beta1_s_per_m) * detuning
        + 0.5 * float(beta2_s2_per_m) * detuning**2
        + (1.0 / 6.0) * float(beta3_s3_per_m) * detuning**3
    )
    output = spectrum * np.exp(1j * phase)
    if transfer_function is not None:
        transfer = np.asarray(transfer_function, dtype=np.complex128).reshape(-1)
        if transfer.shape != output.shape:
            raise ValueError("transfer function shape must match spectrum")
        output *= transfer
    delta_omega = float(differences[0])
    n = omega.size
    delta_t = 2.0 * math.pi / (n * delta_omega)
    time = (np.arange(n) - n // 2) * delta_t
    temporal = np.fft.fftshift(np.fft.ifft(np.fft.ifftshift(output))) * n * delta_omega / (2.0 * math.pi)
    intensity = np.abs(temporal) ** 2
    norm = float(np.sum(intensity) * delta_t)
    centroid = float(np.sum(time * intensity) * delta_t / max(norm, 1e-30))
    variance = float(np.sum((time - centroid) ** 2 * intensity) * delta_t / max(norm, 1e-30))
    energy_frequency = float(np.sum(np.abs(output) ** 2) * delta_omega / (2.0 * math.pi))
    return PulsePropagationResult(
        time_s=time,
        temporal_field=temporal,
        temporal_intensity=intensity,
        spectral_field_out=output,
        rms_duration_s=math.sqrt(max(variance, 0.0)),
        peak_time_s=float(time[int(np.argmax(intensity))]),
        energy_frequency_domain=energy_frequency,
        energy_time_domain=norm,
        metadata={
            "model": "spectral_phase_propagation",
            "length_m": float(length_m),
            "beta1_s_per_m": float(beta1_s_per_m),
            "beta2_s2_per_m": float(beta2_s2_per_m),
            "beta3_s3_per_m": float(beta3_s3_per_m),
            "parseval_relative_error": abs(norm - energy_frequency) / max(energy_frequency, 1e-30),
        },
    )


__all__ = [
    "CoherentMode",
    "CoherenceEnsembleResult",
    "PulsePropagationResult",
    "incoherent_mode_sum",
    "gaussian_schell_mode_weights",
    "propagate_spectral_pulse",
]
