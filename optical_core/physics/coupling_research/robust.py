
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
from scipy.optimize import differential_evolution, minimize


@dataclass(frozen=True, slots=True)
class RobustCouplingScore:
    peak_efficiency: float
    mean_efficiency: float
    p05_efficiency: float
    yield_probability: float
    tolerance_score: float
    objective: float


def score_robust_coupling(
    peak_efficiency: float,
    perturbed_efficiencies: np.ndarray,
    *,
    minimum_efficiency: float,
    tolerance_values: Mapping[str, float] | None = None,
    weights: Mapping[str, float] | None = None,
) -> RobustCouplingScore:
    values = np.asarray(perturbed_efficiencies, dtype=float).reshape(-1)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError("robust coupling score requires finite perturbed samples")
    weight = {
        "peak": 0.25,
        "mean": 0.30,
        "p05": 0.25,
        "yield": 0.20,
        "tolerance": 0.0,
        **dict(weights or {}),
    }
    tolerance = dict(tolerance_values or {})
    tolerance_score = float(np.mean([max(float(value), 0.0) for value in tolerance.values()])) if tolerance else 0.0
    mean = float(np.mean(values))
    p05 = float(np.quantile(values, 0.05))
    yield_probability = float(np.mean(values >= float(minimum_efficiency)))
    objective = (
        weight["peak"] * float(peak_efficiency)
        + weight["mean"] * mean
        + weight["p05"] * p05
        + weight["yield"] * yield_probability
        + weight["tolerance"] * tolerance_score
    )
    return RobustCouplingScore(float(peak_efficiency), mean, p05, yield_probability, tolerance_score, float(objective))


@dataclass(frozen=True, slots=True)
class RobustOptimizationResult:
    parameters: np.ndarray
    score: RobustCouplingScore
    evaluations: int
    converged: bool
    message: str


def optimize_robust_coupling(
    evaluator: Callable[[np.ndarray], RobustCouplingScore],
    *,
    bounds: tuple[tuple[float, float], ...],
    method: str = "differential_evolution",
    initial: np.ndarray | None = None,
    max_iterations: int = 100,
    random_seed: int = 0,
) -> RobustOptimizationResult:
    calls = 0
    best_score: RobustCouplingScore | None = None

    def objective(parameters: np.ndarray) -> float:
        nonlocal calls, best_score
        calls += 1
        score = evaluator(np.asarray(parameters, dtype=float))
        if best_score is None or score.objective > best_score.objective:
            best_score = score
        return -float(score.objective)

    mode = str(method).lower()
    if mode == "differential_evolution":
        result = differential_evolution(objective, bounds, maxiter=int(max_iterations), seed=int(random_seed), polish=True)
    elif mode in {"powell", "l-bfgs-b"}:
        if initial is None:
            initial = np.asarray([(low + high) * 0.5 for low, high in bounds], dtype=float)
        result = minimize(objective, np.asarray(initial, dtype=float), method="Powell" if mode == "powell" else "L-BFGS-B", bounds=bounds, options={"maxiter": int(max_iterations)})
    else:
        raise ValueError("robust optimization method must be differential_evolution, powell, or l-bfgs-b")
    final_score = evaluator(np.asarray(result.x, dtype=float))
    calls += 1
    return RobustOptimizationResult(np.asarray(result.x, dtype=float), final_score, calls, bool(result.success), str(result.message))


__all__ = ["RobustCouplingScore", "score_robust_coupling", "RobustOptimizationResult", "optimize_robust_coupling"]
