
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from .evaluator import PreparedToleranceEvaluator
from .models import FiberToleranceOptions, MonteCarloOptions, ReceiverToleranceDistribution


_RECEIVER_NAMES = ("dx_um", "dy_um", "dz_um", "tilt_x_urad", "tilt_y_urad", "mfd_x_um", "mfd_y_um")


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    metrics: dict[str, Any]
    arrays: dict[str, Any]
    warnings: list[str]
    metadata: dict[str, Any]


def _unit_samples(options: MonteCarloOptions, dimension: int) -> np.ndarray:
    from scipy.stats import qmc

    count = int(options.sample_count)
    method = str(options.sampling_method)
    if method == "sobol":
        sampler = qmc.Sobol(d=dimension, scramble=True, seed=int(options.random_seed))
        power = int(math.ceil(math.log2(max(count, 1))))
        values = sampler.random_base2(power)[:count]
    elif method == "lhs":
        values = qmc.LatinHypercube(d=dimension, seed=int(options.random_seed)).random(count)
    else:
        values = np.random.default_rng(int(options.random_seed)).random((count, dimension))
    eps = np.finfo(float).eps
    return np.clip(values, eps, 1.0 - eps)


def _correlated_standard_normals(
    options: MonteCarloOptions,
    distribution: ReceiverToleranceDistribution,
) -> np.ndarray:
    from scipy.stats import norm

    unit = _unit_samples(options, len(_RECEIVER_NAMES))
    normals = norm.ppf(unit)
    if distribution.correlation_matrix is None:
        return normals
    correlation = np.asarray(distribution.correlation_matrix, dtype=float)
    n = len(_RECEIVER_NAMES)
    if correlation.shape != (n, n):
        raise ValueError(f"receiver_correlation_matrix must have shape {(n, n)}")
    if not np.allclose(correlation, correlation.T, atol=1.0e-10):
        raise ValueError("receiver_correlation_matrix must be symmetric")
    eigenvalues, eigenvectors = np.linalg.eigh(correlation)
    if float(np.min(eigenvalues)) < -1.0e-10:
        raise ValueError("receiver_correlation_matrix must be positive semidefinite")
    root = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0.0))) @ eigenvectors.T
    return normals @ root.T


def _wilson_interval(successes: int, total: int, confidence: float) -> tuple[float, float]:
    from scipy.stats import norm

    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    z = float(norm.ppf(0.5 + float(confidence) / 2.0))
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denom
    return max(0.0, center - half), min(1.0, center + half)


def evaluate_receiver_monte_carlo(
    evaluator: PreparedToleranceEvaluator,
    request: FiberToleranceOptions,
    *,
    threshold_efficiency: float,
) -> MonteCarloResult:
    options = request.monte_carlo
    distribution = request.receiver_distribution
    normals = _correlated_standard_normals(options, distribution)
    sigmas = np.asarray(
        [
            distribution.dx_sigma_um,
            distribution.dy_sigma_um,
            distribution.dz_sigma_um,
            distribution.tilt_x_sigma_urad,
            distribution.tilt_y_sigma_urad,
            distribution.mfd_x_sigma_um,
            distribution.mfd_y_sigma_um,
        ],
        dtype=float,
    )
    perturbations = normals * sigmas[None, :]
    base = evaluator.problem.options
    efficiencies = np.empty(int(options.sample_count), dtype=float)
    for start in range(0, perturbations.shape[0], int(options.batch_size)):
        batch = perturbations[start : start + int(options.batch_size)]
        for local_index, row in enumerate(batch):
            index = start + local_index
            efficiencies[index] = evaluator.problem.efficiency(
                offset_x_mm=evaluator.base_x_mm + float(row[0]) * 1.0e-3,
                offset_y_mm=evaluator.base_y_mm + float(row[1]) * 1.0e-3,
                receiver_axial_offset_z_mm=evaluator.base_z_mm + float(row[2]) * 1.0e-3,
                tilt_x_rad=evaluator.base_tx_rad + float(row[3]) * 1.0e-6,
                tilt_y_rad=evaluator.base_ty_rad + float(row[4]) * 1.0e-6,
                mode_field_diameter_x_um=max(base.mode_field_diameter_x_um + float(row[5]), 1.0e-9),
                mode_field_diameter_y_um=max(base.mode_field_diameter_y_um + float(row[6]), 1.0e-9),
            )
    finite = np.isfinite(efficiencies)
    warnings: list[str] = []
    if not np.all(finite):
        warnings.append(f"Discarded {int(np.count_nonzero(~finite))} non-finite Monte Carlo samples.")
    values = efficiencies[finite]
    if values.size == 0:
        raise FloatingPointError("all Monte Carlo coupling samples were non-finite")
    passed = values >= float(threshold_efficiency)
    success_count = int(np.count_nonzero(passed))
    yield_value = float(success_count / values.size)
    low, high = _wilson_interval(success_count, int(values.size), options.confidence_level)
    quantiles = np.quantile(values, [0.01, 0.05, 0.5, 0.95, 0.99])
    correlations: list[float] = []
    for column in range(perturbations.shape[1]):
        x = perturbations[finite, column]
        if float(np.std(x)) <= 0.0 or float(np.std(values)) <= 0.0:
            correlations.append(0.0)
        else:
            correlations.append(float(np.corrcoef(x, values)[0, 1]))
    worst_index = int(np.nanargmin(efficiencies))
    return MonteCarloResult(
        metrics={
            "fiber_tolerance_monte_carlo_sample_count": int(values.size),
            "fiber_tolerance_monte_carlo_mean_efficiency": float(np.mean(values)),
            "fiber_tolerance_monte_carlo_std_efficiency": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
            "fiber_tolerance_monte_carlo_min_efficiency": float(np.min(values)),
            "fiber_tolerance_monte_carlo_p01_efficiency": float(quantiles[0]),
            "fiber_tolerance_monte_carlo_p05_efficiency": float(quantiles[1]),
            "fiber_tolerance_monte_carlo_p50_efficiency": float(quantiles[2]),
            "fiber_tolerance_monte_carlo_p95_efficiency": float(quantiles[3]),
            "fiber_tolerance_monte_carlo_p99_efficiency": float(quantiles[4]),
            "fiber_tolerance_monte_carlo_threshold_efficiency": float(threshold_efficiency),
            "fiber_tolerance_monte_carlo_yield": yield_value,
            "fiber_tolerance_monte_carlo_failure_rate": 1.0 - yield_value,
            "fiber_tolerance_monte_carlo_yield_ci_low": low,
            "fiber_tolerance_monte_carlo_yield_ci_high": high,
            "fiber_tolerance_monte_carlo_worst_sample_index": worst_index,
        },
        arrays={
            "fiber_tolerance_monte_carlo_parameter_names": list(_RECEIVER_NAMES),
            "fiber_tolerance_monte_carlo_perturbations": perturbations.tolist(),
            "fiber_tolerance_monte_carlo_efficiency": efficiencies.tolist(),
            "fiber_tolerance_monte_carlo_parameter_efficiency_correlation": correlations,
            "fiber_tolerance_monte_carlo_worst_perturbation": perturbations[worst_index].tolist(),
        },
        warnings=warnings,
        metadata={
            "monte_carlo_sampling_method": str(options.sampling_method),
            "monte_carlo_random_seed": int(options.random_seed),
            "monte_carlo_confidence_interval": "Wilson score interval",
            "monte_carlo_parameter_correlation_supported": distribution.correlation_matrix is not None,
        },
    )


def linear_rss_and_worst_case(
    gradient: np.ndarray,
    sigma_dimensionless: np.ndarray,
    *,
    worst_case_sigma: float = 3.0,
) -> dict[str, float]:


    g = np.asarray(gradient, dtype=float)
    sigma = np.asarray(sigma_dimensionless, dtype=float)
    if g.shape != sigma.shape:
        raise ValueError("gradient and sigma_dimensionless must have the same shape")
    rss = float(np.sqrt(np.sum((g * sigma) ** 2)))
    worst = float(np.sum(np.abs(g) * sigma) * float(worst_case_sigma))
    return {
        "fiber_tolerance_rss_natural_log_loss_sigma": rss,
        "fiber_tolerance_worst_case_natural_log_loss": worst,
        "fiber_tolerance_rss_estimated_efficiency_ratio_p1sigma": float(math.exp(-rss)),
        "fiber_tolerance_worst_case_estimated_efficiency_ratio": float(math.exp(-worst)),
    }
