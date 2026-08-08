
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
from scipy.stats import qmc


@dataclass(frozen=True, slots=True)
class SobolSensitivityResult:
    parameter_names: tuple[str, ...]
    first_order: np.ndarray
    total_order: np.ndarray
    output_variance: float
    sample_count: int
    evaluations: int


def sobol_coupling_sensitivity(
    evaluator: Callable[[Mapping[str, float]], float],
    parameter_bounds: Mapping[str, tuple[float, float]],
    *,
    base_sample_power: int = 8,
    random_seed: int = 0,
) -> SobolSensitivityResult:

    names = tuple(parameter_bounds)
    if not names:
        raise ValueError("at least one sensitivity parameter is required")
    bounds = np.asarray([parameter_bounds[name] for name in names], dtype=float)
    if bounds.shape != (len(names), 2) or np.any(bounds[:, 1] <= bounds[:, 0]):
        raise ValueError("each parameter requires finite increasing bounds")
    sample_count = 2 ** int(base_sample_power)
    engine = qmc.Sobol(d=2 * len(names), scramble=True, seed=int(random_seed))
    raw = engine.random_base2(int(base_sample_power))
    a_unit = raw[:, : len(names)]
    b_unit = raw[:, len(names) :]
    lower = bounds[:, 0]
    span = bounds[:, 1] - bounds[:, 0]
    a = lower + a_unit * span
    b = lower + b_unit * span

    def evaluate_matrix(matrix: np.ndarray) -> np.ndarray:
        return np.asarray(
            [float(evaluator({name: float(row[index]) for index, name in enumerate(names)})) for row in matrix],
            dtype=float,
        )

    f_a = evaluate_matrix(a)
    f_b = evaluate_matrix(b)
    all_values = np.concatenate([f_a, f_b])
    variance = float(np.var(all_values, ddof=1))
    if variance <= 1e-30:
        return SobolSensitivityResult(names, np.zeros(len(names)), np.zeros(len(names)), variance, sample_count, 2 * sample_count)
    first = np.empty(len(names), dtype=float)
    total = np.empty(len(names), dtype=float)
    evaluations = 2 * sample_count
    for index in range(len(names)):
        ab = a.copy()
        ab[:, index] = b[:, index]
        f_ab = evaluate_matrix(ab)
        evaluations += sample_count
        first[index] = float(np.mean(f_b * (f_ab - f_a)) / variance)
        total[index] = float(0.5 * np.mean((f_a - f_ab) ** 2) / variance)
    return SobolSensitivityResult(
        parameter_names=names,
        first_order=np.clip(first, -1.0, 1.0),
        total_order=np.clip(total, 0.0, 1.5),
        output_variance=variance,
        sample_count=sample_count,
        evaluations=evaluations,
    )


@dataclass(frozen=True, slots=True)
class CouplingYieldResult:
    mean_efficiency: float
    std_efficiency: float
    p05_efficiency: float
    p50_efficiency: float
    p95_efficiency: float
    yield_probability: float
    failure_probability: float
    worst_efficiency: float
    worst_index: int
    confidence_interval_95: tuple[float, float]


def summarize_coupling_yield(efficiency: np.ndarray, *, minimum_efficiency: float) -> CouplingYieldResult:
    values = np.asarray(efficiency, dtype=float).reshape(-1)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError("coupling yield requires finite samples")
    passed = values >= float(minimum_efficiency)
    probability = float(np.mean(passed))
    standard_error = np.sqrt(max(probability * (1.0 - probability) / values.size, 0.0))
    interval = (max(probability - 1.96 * standard_error, 0.0), min(probability + 1.96 * standard_error, 1.0))
    worst_index = int(np.argmin(values))
    return CouplingYieldResult(
        mean_efficiency=float(np.mean(values)),
        std_efficiency=float(np.std(values, ddof=0)),
        p05_efficiency=float(np.quantile(values, 0.05)),
        p50_efficiency=float(np.quantile(values, 0.50)),
        p95_efficiency=float(np.quantile(values, 0.95)),
        yield_probability=probability,
        failure_probability=1.0 - probability,
        worst_efficiency=float(values[worst_index]),
        worst_index=worst_index,
        confidence_interval_95=interval,
    )


__all__ = ["SobolSensitivityResult", "sobol_coupling_sensitivity", "CouplingYieldResult", "summarize_coupling_yield"]
