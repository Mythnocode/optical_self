
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from typing import Any, Iterable

import numpy as np
from scipy.stats import norm, qmc

from shared_contracts.parameters import ParameterChange
from shared_contracts.simulation import SimulationRequest
from shared_contracts.tolerance import (
    ToleranceAnalysisRequest,
    ToleranceAnalysisResult,
    ToleranceParameter,
)
from shared_ports.simulation import SimulationPort


class SystemToleranceRunner:


    algorithm_version = "system-tolerance-1.0"

    def __init__(self, simulator: SimulationPort) -> None:
        self.simulator = simulator

    def run(
        self,
        base_request: SimulationRequest,
        request: ToleranceAnalysisRequest,
        *,
        max_workers: int = 1,
    ) -> ToleranceAnalysisResult:
        parameters = [item for item in request.parameters if item.enabled]
        samples = sample_tolerance_parameters(
            parameters,
            sample_count=request.sample_count,
            method=request.sampling_method,
            random_seed=request.random_seed,
            correlation_matrix=request.correlation_matrix,
        )
        simulation_requests = [
            self._sample_request(base_request, request, parameters, row, index)
            for index, row in enumerate(samples)
        ]
        if max_workers > 1:
            with ThreadPoolExecutor(max_workers=int(max_workers)) as pool:
                results = list(pool.map(self.simulator.evaluate, simulation_requests))
        else:
            results = [self.simulator.evaluate(item) for item in simulation_requests]

        metric_name = str(request.options.get("response_metric", "coupling_efficiency"))
        accepted_values: list[float] = []
        accepted_rows: list[np.ndarray] = []
        rejected: list[dict[str, Any]] = []
        for index, (row, result) in enumerate(zip(samples, results, strict=True)):
            reason = _quality_rejection_reason(result, request.options)
            value = _extract_metric(result.metrics, metric_name)
            if reason is None and value is not None and np.isfinite(value):
                accepted_values.append(float(value))
                accepted_rows.append(np.asarray(row, dtype=float))
            else:
                rejected.append(
                    {
                        "sample_index": index,
                        "reason": reason or f"metric {metric_name!r} unavailable",
                        "status": result.status,
                    }
                )

        values = np.asarray(accepted_values, dtype=float)
        rows = np.asarray(accepted_rows, dtype=float)
        threshold = _resolve_yield_threshold(values, request)
        metrics, arrays = _summarise_samples(parameters, rows, values, threshold)
        deterministic_warnings: list[str] = []
        if bool(request.options.get("include_deterministic_budget", False)):
            budget_metrics, budget_arrays, deterministic_warnings = self._deterministic_budget(
                base_request, request, parameters, metric_name
            )
            metrics.update(budget_metrics)
            arrays.update(budget_arrays)
        metrics.update(
            {
                "system_tolerance_requested_sample_count": int(request.sample_count),
                "system_tolerance_accepted_sample_count": int(values.size),
                "system_tolerance_rejected_sample_count": int(len(rejected)),
                "system_tolerance_acceptance_ratio": float(values.size / max(request.sample_count, 1)),
                "system_tolerance_threshold_efficiency": threshold,
            }
        )
        arrays["system_tolerance_rejected_samples"] = rejected
        metadata = {
            "algorithm_version": self.algorithm_version,
            "sampling_method": request.sampling_method,
            "random_seed": request.random_seed,
            "parameter_paths": [item.path for item in parameters],
            "response_metric": metric_name,
            "quality_filter": {
                "require_converged": bool(request.options.get("require_converged", False)),
                "reject_energy_failure": bool(request.options.get("reject_energy_failure", True)),
                "reject_edge_failure": bool(request.options.get("reject_edge_failure", True)),
                "reject_nyquist_failure": bool(request.options.get("reject_nyquist_failure", True)),
            },
            "reference_data_used_as_input": False,
            "zemax_data_used_as_input": False,
        }
        warnings: list[str] = list(deterministic_warnings)
        if max_workers > 1:
            warnings.append(
                "System tolerance used thread-level parallelism; configure numerical-library "
                "thread counts to avoid oversubscription."
            )
        if values.size == 0:
            warnings.append("No system-tolerance sample passed the simulation quality filter.")
        elif len(rejected) / max(request.sample_count, 1) > 0.05:
            warnings.append("More than 5% of system-tolerance samples were rejected by quality checks.")
        return ToleranceAnalysisResult(
            request_id=request.request_id,
            status="completed" if values.size else "failed",
            metrics=metrics,
            arrays=arrays,
            warnings=warnings,
            metadata=metadata,
        )

    def _deterministic_budget(
        self,
        base_request: SimulationRequest,
        tolerance: ToleranceAnalysisRequest,
        parameters: list[ToleranceParameter],
        metric_name: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:


        warnings: list[str] = []
        base_result = self.simulator.evaluate(
            base_request.model_copy(
                deep=True,
                update={
                    "request_id": f"{tolerance.request_id}:deterministic:nominal",
                    "analyses": list(tolerance.analyses),
                    "precision": tolerance.precision,
                    "options": {
                        **dict(base_request.options),
                        **dict(tolerance.options.get("simulation_options", {})),
                    },
                },
            )
        )
        rejection = _quality_rejection_reason(base_result, tolerance.options)
        nominal_value = _extract_metric(base_result.metrics, metric_name)
        if rejection is not None or nominal_value is None or not np.isfinite(nominal_value):
            warnings.append(
                "Deterministic tolerance budget was skipped because the nominal "
                f"simulation was invalid: {rejection or 'response metric unavailable'}."
            )
            return {}, {}, warnings

        step_fraction = float(tolerance.options.get("linear_budget_step_sigma", 0.25))
        if not math.isfinite(step_fraction) or step_fraction <= 0.0:
            raise ValueError("linear_budget_step_sigma must be positive and finite")
        worst_sigma = float(tolerance.options.get("worst_case_sigma", 3.0))
        if not math.isfinite(worst_sigma) or worst_sigma <= 0.0:
            raise ValueError("worst_case_sigma must be positive and finite")

        derivatives: list[float] = []
        standard_deviations: list[float] = []
        half_ranges: list[float] = []
        valid_parameters: list[ToleranceParameter] = []
        adverse_values: list[float] = []
        for index, parameter in enumerate(parameters):
            sigma, half_range = _distribution_scales(parameter)
            if parameter.distribution.name == "normal":
                half_range = worst_sigma * sigma
            if sigma <= 0.0 or half_range <= 0.0:
                continue
            step = max(step_fraction * sigma, abs(parameter.nominal) * 1.0e-9, 1.0e-12)
            pair_values = np.asarray([parameter.nominal + step, parameter.nominal - step], dtype=float)
            pair_requests = [
                self._sample_request(
                    base_request,
                    tolerance,
                    [parameter],
                    np.asarray([value], dtype=float),
                    10_000_000 + 2 * index + offset,
                )
                for offset, value in enumerate(pair_values)
            ]
            pair_results = [self.simulator.evaluate(item) for item in pair_requests]
            pair_metrics: list[float] = []
            pair_ok = True
            for pair_result in pair_results:
                reason = _quality_rejection_reason(pair_result, tolerance.options)
                value = _extract_metric(pair_result.metrics, metric_name)
                if reason is not None or value is None or not np.isfinite(value):
                    pair_ok = False
                    break
                pair_metrics.append(float(value))
            if not pair_ok:
                warnings.append(
                    f"Skipped deterministic derivative for {parameter.path!r}; "
                    "one finite-difference simulation failed quality checks."
                )
                continue
            derivative = (pair_metrics[0] - pair_metrics[1]) / (2.0 * step)
            derivatives.append(float(derivative))
            standard_deviations.append(float(sigma))
            half_ranges.append(float(half_range))
            valid_parameters.append(parameter)
            direction = -1.0 if derivative > 0.0 else 1.0
            adverse_values.append(float(parameter.nominal + direction * half_range))

        if not valid_parameters:
            warnings.append("No non-degenerate parameter was available for the deterministic budget.")
            return {"system_tolerance_nominal_response": float(nominal_value)}, {}, warnings

        derivative_array = np.asarray(derivatives, dtype=float)
        sigma_array = np.asarray(standard_deviations, dtype=float)
        range_array = np.asarray(half_ranges, dtype=float)
        rss_response_sigma = float(np.sqrt(np.sum((derivative_array * sigma_array) ** 2)))
        linear_worst_loss = float(np.sum(np.abs(derivative_array) * range_array))

        corner_request = self._sample_request(
            base_request,
            tolerance,
            valid_parameters,
            np.asarray(adverse_values, dtype=float),
            20_000_000,
        )
        corner_result = self.simulator.evaluate(corner_request)
        corner_reason = _quality_rejection_reason(corner_result, tolerance.options)
        corner_value = _extract_metric(corner_result.metrics, metric_name)
        if corner_reason is not None or corner_value is None or not np.isfinite(corner_value):
            warnings.append(
                "The adverse-corner optical simulation failed quality checks; only the "
                "first-order worst-case estimate is reported."
            )
            corner_value = None

        metrics: dict[str, Any] = {
            "system_tolerance_nominal_response": float(nominal_value),
            "system_tolerance_linear_rss_response_sigma": rss_response_sigma,
            "system_tolerance_linear_worst_case_loss": linear_worst_loss,
            "system_tolerance_linear_worst_case_response_estimate": float(nominal_value - linear_worst_loss),
            "system_tolerance_deterministic_parameter_count": len(valid_parameters),
            "system_tolerance_worst_case_sigma": worst_sigma,
        }
        if corner_value is not None:
            metrics["system_tolerance_adverse_corner_response"] = float(corner_value)
            metrics["system_tolerance_adverse_corner_loss"] = float(nominal_value - corner_value)
        arrays = {
            "system_tolerance_deterministic_parameter_paths": [item.path for item in valid_parameters],
            "system_tolerance_local_derivatives": derivatives,
            "system_tolerance_parameter_standard_deviations": standard_deviations,
            "system_tolerance_parameter_worst_half_ranges": half_ranges,
            "system_tolerance_adverse_corner_parameter_values": adverse_values,
        }
        return metrics, arrays, warnings

    @staticmethod
    def _sample_request(
        base: SimulationRequest,
        tolerance: ToleranceAnalysisRequest,
        parameters: list[ToleranceParameter],
        values: np.ndarray,
        sample_index: int,
    ) -> SimulationRequest:
        changes = list(base.parameter_changes) + list(tolerance.nominal_changes)
        simulation_options = {**dict(base.options), **dict(tolerance.options.get("simulation_options", {}))}
        for item, value in zip(parameters, values, strict=True):
            if item.path.startswith("options."):
                _set_mapping_path(simulation_options, item.path.removeprefix("options."), float(value))
            else:
                changes.append(ParameterChange(path=item.path, value=float(value), unit=item.unit or None))
        return base.model_copy(
            deep=True,
            update={
                "request_id": f"{tolerance.request_id}:sample:{sample_index:06d}",
                "analyses": list(tolerance.analyses),
                "parameter_changes": changes,
                "precision": tolerance.precision,
                "random_seed": int(tolerance.random_seed + sample_index),
                "options": simulation_options,
            },
        )



def _set_mapping_path(mapping: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        raise ValueError("options tolerance path cannot be empty")
    current = mapping
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value

def sample_tolerance_parameters(
    parameters: Iterable[ToleranceParameter],
    *,
    sample_count: int,
    method: str,
    random_seed: int,
    correlation_matrix: list[list[float]] | None = None,
) -> np.ndarray:


    params = list(parameters)
    n = int(sample_count)
    d = len(params)
    if d == 0:
        return np.empty((n, 0), dtype=float)
    rng = np.random.default_rng(int(random_seed))
    method_key = str(method).lower()
    if method_key == "lhs":
        uniforms = qmc.LatinHypercube(d=d, seed=int(random_seed)).random(n)
    elif method_key == "sobol":
        sampler = qmc.Sobol(d=d, scramble=True, seed=int(random_seed))
        power = int(math.ceil(math.log2(max(n, 1))))
        uniforms = sampler.random_base2(power)[:n]
    elif method_key == "random":
        uniforms = rng.random((n, d))
    else:
        raise ValueError(f"unsupported tolerance sampling method: {method!r}")
    uniforms = np.clip(uniforms, 1.0e-12, 1.0 - 1.0e-12)

    if correlation_matrix is not None:
        corr = np.asarray(correlation_matrix, dtype=float)
        if corr.shape != (d, d):
            raise ValueError("correlation_matrix must match the number of enabled parameters")
        corr = 0.5 * (corr + corr.T)
        eigenvalues, eigenvectors = np.linalg.eigh(corr)
        if float(np.min(eigenvalues)) < -1.0e-8:
            raise ValueError("correlation_matrix must be positive semidefinite")
        root = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0.0))) @ eigenvectors.T
        gaussian = norm.ppf(uniforms) @ root.T
        uniforms = np.clip(norm.cdf(gaussian), 1.0e-12, 1.0 - 1.0e-12)

    samples = np.empty((n, d), dtype=float)
    for column, parameter in enumerate(params):
        dist = parameter.distribution
        u = uniforms[:, column]
        nominal = float(parameter.nominal)
        if dist.name == "fixed":
            samples[:, column] = nominal
        elif dist.name == "normal":
            samples[:, column] = nominal + float(dist.sigma or 0.0) * norm.ppf(u)
        elif dist.name == "uniform":
            samples[:, column] = float(dist.lower) + u * (float(dist.upper) - float(dist.lower))
        elif dist.name == "triangular":
            lo, hi = float(dist.lower), float(dist.upper)
            mode_value = nominal if dist.mode is None else float(dist.mode)
            fraction = (mode_value - lo) / max(hi - lo, 1.0e-30)
            left = lo + np.sqrt(u * (hi - lo) * (mode_value - lo))
            right = hi - np.sqrt((1.0 - u) * (hi - lo) * (hi - mode_value))
            samples[:, column] = np.where(u < fraction, left, right)
        else:  
            raise ValueError(f"unsupported distribution {dist.name!r}")
    return samples


def _distribution_scales(parameter: ToleranceParameter) -> tuple[float, float]:


    distribution = parameter.distribution
    nominal = float(parameter.nominal)
    if distribution.name == "fixed":
        return 0.0, 0.0
    if distribution.name == "normal":
        sigma = float(distribution.sigma or 0.0)
        return sigma, 3.0 * sigma
    lower = float(distribution.lower)
    upper = float(distribution.upper)
    half_range = max(abs(lower - nominal), abs(upper - nominal))
    if distribution.name == "uniform":
        sigma = (upper - lower) / math.sqrt(12.0)
    elif distribution.name == "triangular":
        mode_value = nominal if distribution.mode is None else float(distribution.mode)
        variance = (
            lower * lower
            + upper * upper
            + mode_value * mode_value
            - lower * upper
            - lower * mode_value
            - upper * mode_value
        ) / 18.0
        sigma = math.sqrt(max(variance, 0.0))
    else:
        raise ValueError(f"unsupported tolerance distribution: {distribution.name!r}")
    return float(sigma), float(half_range)


def _extract_metric(metrics: dict[str, Any], requested: str) -> float | None:
    if requested in metrics and isinstance(metrics[requested], (int, float)):
        return float(metrics[requested])
    matches = [
        float(value)
        for key, value in metrics.items()
        if key.endswith(f".{requested}") and isinstance(value, (int, float))
    ]
    return matches[0] if len(matches) == 1 else None


def _quality_rejection_reason(result: Any, options: dict[str, Any]) -> str | None:
    if result.status != "completed":
        return f"simulation status={result.status}"
    if bool(options.get("require_converged", False)) and not bool(result.converged):
        return "simulation did not converge"
    checks = (
        ("reject_energy_failure", "coupling_propagation_energy_pass"),
        ("reject_edge_failure", "coupling_propagation_edge_pass"),
        ("reject_nyquist_failure", "coupling_propagation_nyquist_pass"),
    )
    for option_name, metric_name in checks:
        if not bool(options.get(option_name, True)):
            continue
        value = _extract_metric(result.metrics, metric_name)
        if value is not None and not bool(value):
            return f"quality check failed: {metric_name}"
    return None


def _resolve_yield_threshold(values: np.ndarray, request: ToleranceAnalysisRequest) -> float | None:
    if request.threshold_efficiency is not None:
        return float(request.threshold_efficiency)
    if values.size and request.threshold_loss_db is not None:
        nominal = float(request.options.get("nominal_efficiency", np.max(values)))
        return nominal * 10.0 ** (-float(request.threshold_loss_db) / 10.0)
    return None


def _summarise_samples(
    parameters: list[ToleranceParameter],
    rows: np.ndarray,
    values: np.ndarray,
    threshold: float | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    arrays: dict[str, Any] = {
        "system_tolerance_parameter_samples": rows.tolist(),
        "system_tolerance_response_samples": values.tolist(),
    }
    if values.size == 0:
        return metrics, arrays
    quantiles = np.quantile(values, [0.01, 0.05, 0.5, 0.95, 0.99])
    metrics.update(
        {
            "system_tolerance_mean": float(np.mean(values)),
            "system_tolerance_std": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
            "system_tolerance_min": float(np.min(values)),
            "system_tolerance_max": float(np.max(values)),
            "system_tolerance_p01": float(quantiles[0]),
            "system_tolerance_p05": float(quantiles[1]),
            "system_tolerance_p50": float(quantiles[2]),
            "system_tolerance_p95": float(quantiles[3]),
            "system_tolerance_p99": float(quantiles[4]),
        }
    )
    if threshold is not None:
        passed = int(np.count_nonzero(values >= threshold))
        metrics["system_tolerance_yield"] = float(passed / values.size)
        low, high = _wilson_interval(passed, int(values.size), 0.95)
        metrics["system_tolerance_yield_ci_low"] = low
        metrics["system_tolerance_yield_ci_high"] = high
    worst = int(np.argmin(values))
    arrays["system_tolerance_worst_parameter_values"] = rows[worst].tolist()
    metrics["system_tolerance_worst_sample_index"] = worst
    if rows.shape[0] > 2 and rows.shape[1]:
        correlations = []
        for column in range(rows.shape[1]):
            if np.std(rows[:, column]) <= 0.0 or np.std(values) <= 0.0:
                correlations.append(0.0)
            else:
                correlations.append(float(np.corrcoef(rows[:, column], values)[0, 1]))
        arrays["system_tolerance_parameter_response_correlations"] = correlations
        arrays["system_tolerance_parameter_paths"] = [item.path for item in parameters]
    return metrics, arrays


def _wilson_interval(successes: int, total: int, confidence: float) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    z = float(norm.ppf(0.5 + confidence / 2.0))
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total)) / denominator
    return float(max(0.0, centre - radius)), float(min(1.0, centre + radius))


__all__ = ["SystemToleranceRunner", "sample_tolerance_parameters"]
