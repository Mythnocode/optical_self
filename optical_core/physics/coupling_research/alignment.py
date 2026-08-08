
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.optimize import minimize


@dataclass(frozen=True, slots=True)
class AlignmentBenchmarkResult:
    method: str
    initial_parameters: np.ndarray
    best_parameters: np.ndarray
    initial_efficiency: float
    best_efficiency: float
    function_evaluations: int
    iterations: int
    converged: bool
    message: str


def optimize_alignment(
    evaluator: Callable[[np.ndarray], float],
    initial_parameters: np.ndarray,
    *,
    method: str = "Powell",
    bounds: tuple[tuple[float, float], ...] | None = None,
    max_iterations: int = 200,
) -> AlignmentBenchmarkResult:
    initial = np.asarray(initial_parameters, dtype=float).reshape(-1)
    initial_eta = float(evaluator(initial))
    scipy_method = str(method)
    supported = {"Powell", "Nelder-Mead", "L-BFGS-B", "SLSQP"}
    if scipy_method not in supported:
        raise ValueError(f"alignment method must be one of {sorted(supported)}")
    result = minimize(
        lambda vector: -float(evaluator(np.asarray(vector, dtype=float))),
        initial,
        method=scipy_method,
        bounds=bounds if scipy_method in {"Powell", "L-BFGS-B", "SLSQP"} else None,
        options={"maxiter": int(max_iterations)},
    )
    return AlignmentBenchmarkResult(
        method=scipy_method,
        initial_parameters=initial,
        best_parameters=np.asarray(result.x, dtype=float),
        initial_efficiency=initial_eta,
        best_efficiency=-float(result.fun),
        function_evaluations=int(getattr(result, "nfev", 0) or 0),
        iterations=int(getattr(result, "nit", 0) or 0),
        converged=bool(result.success),
        message=str(result.message),
    )


def compare_alignment_methods(
    evaluator: Callable[[np.ndarray], float],
    initial_parameters: np.ndarray,
    *,
    methods: tuple[str, ...] = ("Powell", "Nelder-Mead", "L-BFGS-B"),
    bounds: tuple[tuple[float, float], ...] | None = None,
    max_iterations: int = 200,
) -> tuple[AlignmentBenchmarkResult, ...]:
    results = [
        optimize_alignment(
            evaluator,
            initial_parameters,
            method=method,
            bounds=bounds,
            max_iterations=max_iterations,
        )
        for method in methods
    ]
    return tuple(sorted(results, key=lambda item: (-item.best_efficiency, item.function_evaluations)))


__all__ = ["AlignmentBenchmarkResult", "optimize_alignment", "compare_alignment_methods"]
