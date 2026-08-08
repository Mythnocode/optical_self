
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class JitterTimeSeries:
    time_s: np.ndarray
    parameters: Mapping[str, np.ndarray]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DynamicCouplingResult:
    time_s: np.ndarray
    efficiency: np.ndarray
    metrics: Mapping[str, Any]
    parameters: Mapping[str, np.ndarray]


def generate_gaussian_jitter(
    *,
    sample_count: int,
    sample_rate_hz: float,
    standard_deviation_by_parameter: Mapping[str, float],
    mean_by_parameter: Mapping[str, float] | None = None,
    correlation_matrix: np.ndarray | None = None,
    random_seed: int = 0,
) -> JitterTimeSeries:
    if sample_count < 2 or sample_rate_hz <= 0.0:
        raise ValueError("jitter sample count and rate must be positive")
    names = tuple(standard_deviation_by_parameter)
    sigma = np.asarray([float(standard_deviation_by_parameter[name]) for name in names], dtype=float)
    if np.any(sigma < 0.0):
        raise ValueError("jitter standard deviations must be non-negative")
    mean_mapping = dict(mean_by_parameter or {})
    mean = np.asarray([float(mean_mapping.get(name, 0.0)) for name in names], dtype=float)
    correlation = np.eye(len(names)) if correlation_matrix is None else np.asarray(correlation_matrix, dtype=float)
    if correlation.shape != (len(names), len(names)) or not np.allclose(correlation, correlation.T, atol=1e-12):
        raise ValueError("correlation matrix shape/symmetry is invalid")
    covariance = np.diag(sigma) @ correlation @ np.diag(sigma)
    if float(np.min(np.linalg.eigvalsh(covariance))) < -1e-12:
        raise ValueError("jitter covariance must be positive semidefinite")
    rng = np.random.default_rng(int(random_seed))
    samples = rng.multivariate_normal(mean, covariance, size=int(sample_count), check_valid="raise")
    time = np.arange(sample_count, dtype=float) / float(sample_rate_hz)
    return JitterTimeSeries(
        time_s=time,
        parameters={name: samples[:, index] for index, name in enumerate(names)},
        metadata={"distribution": "correlated_gaussian", "random_seed": int(random_seed)},
    )


def generate_sinusoidal_jitter(
    *,
    duration_s: float,
    sample_rate_hz: float,
    amplitude_by_parameter: Mapping[str, float],
    frequency_hz_by_parameter: Mapping[str, float],
    phase_rad_by_parameter: Mapping[str, float] | None = None,
) -> JitterTimeSeries:
    if duration_s <= 0.0 or sample_rate_hz <= 0.0:
        raise ValueError("duration and sample rate must be positive")
    count = max(int(round(duration_s * sample_rate_hz)), 2)
    time = np.arange(count, dtype=float) / float(sample_rate_hz)
    phases = dict(phase_rad_by_parameter or {})
    parameters = {}
    for name, amplitude in amplitude_by_parameter.items():
        frequency = float(frequency_hz_by_parameter[name])
        parameters[name] = float(amplitude) * np.sin(2.0 * math.pi * frequency * time + float(phases.get(name, 0.0)))
    return JitterTimeSeries(time_s=time, parameters=parameters, metadata={"distribution": "sinusoidal"})


def evaluate_dynamic_coupling(
    jitter: JitterTimeSeries,
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    threshold: float | None = None,
) -> DynamicCouplingResult:
    names = tuple(jitter.parameters)
    count = jitter.time_s.size
    if any(np.asarray(jitter.parameters[name]).size != count for name in names):
        raise ValueError("all jitter parameter arrays must match the time axis")
    efficiency = np.empty(count, dtype=float)
    for index in range(count):
        value = float(evaluator({name: float(np.asarray(jitter.parameters[name])[index]) for name in names}))
        if not np.isfinite(value):
            raise ValueError("dynamic coupling evaluator returned non-finite efficiency")
        efficiency[index] = value
    metrics: dict[str, Any] = {
        "sample_count": count,
        "mean_efficiency": float(np.mean(efficiency)),
        "std_efficiency": float(np.std(efficiency, ddof=0)),
        "minimum_efficiency": float(np.min(efficiency)),
        "p05_efficiency": float(np.quantile(efficiency, 0.05)),
        "p50_efficiency": float(np.quantile(efficiency, 0.50)),
        "p95_efficiency": float(np.quantile(efficiency, 0.95)),
    }
    if threshold is not None:
        below = efficiency < float(threshold)
        dt = float(np.median(np.diff(jitter.time_s))) if count > 1 else 0.0
        metrics.update(
            {
                "threshold": float(threshold),
                "dropout_probability": float(np.mean(below)),
                "time_below_threshold_s": float(np.sum(below) * dt),
                "longest_dropout_s": _longest_run(below) * dt,
            }
        )
    return DynamicCouplingResult(jitter.time_s, efficiency, metrics, jitter.parameters)


def _longest_run(mask: np.ndarray) -> int:
    best = current = 0
    for value in np.asarray(mask, dtype=bool):
        current = current + 1 if value else 0
        best = max(best, current)
    return best


__all__ = [
    "JitterTimeSeries",
    "DynamicCouplingResult",
    "generate_gaussian_jitter",
    "generate_sinusoidal_jitter",
    "generate_rician_lateral_jitter",
    "generate_psd_jitter",
    "jitter_from_measured_time_series",
    "evaluate_dynamic_coupling",
]


def generate_rician_lateral_jitter(
    *,
    sample_count: int,
    sample_rate_hz: float,
    static_offset_x: float,
    static_offset_y: float,
    random_sigma: float,
    x_name: str = "dx_um",
    y_name: str = "dy_um",
    random_seed: int = 0,
) -> JitterTimeSeries:

    return generate_gaussian_jitter(
        sample_count=sample_count,
        sample_rate_hz=sample_rate_hz,
        standard_deviation_by_parameter={x_name: random_sigma, y_name: random_sigma},
        mean_by_parameter={x_name: static_offset_x, y_name: static_offset_y},
        random_seed=random_seed,
    )


def generate_psd_jitter(
    *,
    sample_count: int,
    sample_rate_hz: float,
    frequency_hz: np.ndarray,
    one_sided_psd_by_parameter: Mapping[str, np.ndarray],
    random_seed: int = 0,
) -> JitterTimeSeries:

    if sample_count < 4 or sample_rate_hz <= 0.0:
        raise ValueError("PSD jitter requires sample_count >= 4 and positive sample rate")
    target_frequency = np.fft.rfftfreq(int(sample_count), d=1.0 / float(sample_rate_hz))
    source_frequency = np.asarray(frequency_hz, dtype=float).reshape(-1)
    if source_frequency.size < 2 or not np.all(np.diff(source_frequency) > 0.0):
        raise ValueError("PSD frequency axis must be strictly increasing")
    rng = np.random.default_rng(int(random_seed))
    parameters: dict[str, np.ndarray] = {}
    df = float(sample_rate_hz) / int(sample_count)
    for name, source_psd in one_sided_psd_by_parameter.items():
        psd = np.asarray(source_psd, dtype=float).reshape(-1)
        if psd.shape != source_frequency.shape or np.any(psd < 0.0) or not np.all(np.isfinite(psd)):
            raise ValueError(f"PSD for {name!r} must be finite, non-negative and match frequency")
        interpolated = np.interp(target_frequency, source_frequency, psd, left=0.0, right=0.0)
        phases = rng.uniform(0.0, 2.0 * math.pi, target_frequency.size)
        spectrum = np.sqrt(np.maximum(interpolated * df * sample_count**2 / 2.0, 0.0)) * np.exp(1j * phases)
        spectrum[0] = 0.0
        if sample_count % 2 == 0:
            spectrum[-1] = complex(float(np.real(spectrum[-1])), 0.0)
        values = np.fft.irfft(spectrum, n=int(sample_count))
        parameters[str(name)] = np.asarray(values, dtype=float)
    time = np.arange(sample_count, dtype=float) / float(sample_rate_hz)
    return JitterTimeSeries(
        time_s=time,
        parameters=parameters,
        metadata={"distribution": "psd_synthesized_gaussian", "random_seed": int(random_seed)},
    )


def jitter_from_measured_time_series(
    time_s: np.ndarray,
    parameters: Mapping[str, np.ndarray],
) -> JitterTimeSeries:
    time = np.asarray(time_s, dtype=float).reshape(-1)
    if time.size < 2 or not np.all(np.diff(time) > 0.0):
        raise ValueError("measured jitter time axis must be strictly increasing")
    parsed = {str(name): np.asarray(values, dtype=float).reshape(-1) for name, values in parameters.items()}
    if not parsed or any(values.size != time.size for values in parsed.values()):
        raise ValueError("measured jitter arrays must match the time axis")
    if any(not np.all(np.isfinite(values)) for values in parsed.values()):
        raise ValueError("measured jitter arrays must be finite")
    return JitterTimeSeries(time_s=time, parameters=parsed, metadata={"distribution": "measured"})
