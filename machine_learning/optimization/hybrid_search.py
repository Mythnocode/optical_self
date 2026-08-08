
from __future__ import annotations

from dataclasses import dataclass, field
import warnings
from math import ceil, log2
from typing import Callable, Sequence

import numpy as np
from scipy.optimize import differential_evolution, minimize
from scipy.stats import norm, qmc
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

Objective = Callable[[np.ndarray], float]


@dataclass
class HybridSearchResult:
    coarse_method: str
    coarse_x: np.ndarray
    coarse_value: float
    refined_x: np.ndarray
    refined_value: float
    final_x: np.ndarray
    final_value: float
    coarse_evaluations: int = 0
    refinement_evaluations: int = 0
    coarse_verified_value: float | None = None
    verification_evaluations: int = 1
    warnings: list[str] = field(default_factory=list)


def select_coarse_method(dimension: int, requested: str) -> str:
    requested = str(requested).strip().lower()
    if requested == "auto":
        return "bayesian" if dimension <= 5 else "differential_evolution"
    if requested not in {"bayesian", "differential_evolution"}:
        raise ValueError(f"不支持的粗搜索算法: {requested}")
    return requested


def _lhs(bounds: Sequence[tuple[float, float]], count: int, seed: int) -> np.ndarray:
    lower = np.asarray([item[0] for item in bounds], dtype=float)
    upper = np.asarray([item[1] for item in bounds], dtype=float)
    unit = qmc.LatinHypercube(d=len(bounds), seed=seed).random(n=count)
    return lower + unit * (upper - lower)


def _sobol_pool(
    bounds: Sequence[tuple[float, float]], count: int, seed: int
) -> np.ndarray:
    power = max(0, int(ceil(log2(max(1, count)))))
    unit = qmc.Sobol(d=len(bounds), scramble=True, seed=seed).random_base2(power)[:count]
    lower = np.asarray([item[0] for item in bounds], dtype=float)
    upper = np.asarray([item[1] for item in bounds], dtype=float)
    return lower + unit * (upper - lower)


def bayesian_coarse_search(
    objective: Objective,
    bounds: Sequence[tuple[float, float]],
    *,
    seed: int,
    max_evaluations: int,
    initial_x: np.ndarray | None = None,
) -> tuple[np.ndarray, float, int]:
    dimension = len(bounds)
    if max_evaluations < 3:
        raise ValueError("贝叶斯粗搜至少需要3次评估")
    initial_count = min(max_evaluations, max(2 * dimension + 2, 8))
    points = _lhs(bounds, initial_count, seed)
    if initial_x is not None:
        points[0] = np.asarray(initial_x, dtype=float)
    values = np.asarray([objective(point) for point in points], dtype=float)

    kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(
        length_scale=np.ones(dimension), nu=2.5
    ) + WhiteKernel(noise_level=1e-8, noise_level_bounds=(1e-12, 1e-2))

    while len(values) < max_evaluations:
        lower = np.asarray([item[0] for item in bounds], dtype=float)
        upper = np.asarray([item[1] for item in bounds], dtype=float)
        span = np.maximum(upper - lower, 1e-12)
        normalized = (points - lower) / span
        gp = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            random_state=seed,
            n_restarts_optimizer=1,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            gp.fit(normalized, values)
        pool = _sobol_pool(bounds, max(512, 128 * dimension), seed + len(values))
        pool_normalized = (pool - lower) / span
        mean, std = gp.predict(pool_normalized, return_std=True)
        best = float(np.min(values))
        improvement = best - mean
        safe_std = np.maximum(std, 1e-12)
        z = improvement / safe_std
        expected_improvement = improvement * norm.cdf(z) + safe_std * norm.pdf(z)
        candidate = pool[int(np.argmax(expected_improvement))]
        points = np.vstack([points, candidate])
        values = np.append(values, objective(candidate))

    best_index = int(np.argmin(values))
    return points[best_index], float(values[best_index]), len(values)


def differential_evolution_coarse_search(
    objective: Objective,
    bounds: Sequence[tuple[float, float]],
    *,
    seed: int,
    max_evaluations: int,
) -> tuple[np.ndarray, float, int]:
    dimension = len(bounds)
    evaluations = 0

    def counted(x: np.ndarray) -> float:
        nonlocal evaluations
        evaluations += 1
        return float(objective(x))

    
    
    
    
    if max_evaluations < 5:
        points = _lhs(bounds, max_evaluations, seed)
        values = np.asarray([counted(point) for point in points], dtype=float)
        best = int(np.argmin(values))
        return points[best], float(values[best]), evaluations

    population_count = min(
        max_evaluations,
        max(5, min(4 * dimension, 16)),
    )
    initial_population = _lhs(bounds, population_count, seed)
    maxiter = max(0, max_evaluations // population_count - 1)

    result = differential_evolution(
        counted,
        bounds,
        seed=seed,
        maxiter=maxiter,
        popsize=1,  
        init=initial_population,
        polish=False,
        updating="immediate",
        workers=1,
    )
    return np.asarray(result.x, dtype=float), float(result.fun), evaluations


def powell_refine(
    objective: Objective,
    x0: np.ndarray,
    bounds: Sequence[tuple[float, float]],
    *,
    max_evaluations: int,
    tolerance: float,
) -> tuple[np.ndarray, float, int]:
    evaluations = 0

    def counted(x: np.ndarray) -> float:
        nonlocal evaluations
        evaluations += 1
        return float(objective(x))

    result = minimize(
        counted,
        np.asarray(x0, dtype=float),
        method="Powell",
        bounds=list(bounds),
        options={
            "maxfev": max(1, int(max_evaluations)),
            "xtol": float(tolerance),
            "ftol": float(tolerance),
        },
    )
    return np.asarray(result.x, dtype=float), float(result.fun), evaluations


def run_hybrid_search(
    objective: Objective,
    bounds: Sequence[tuple[float, float]],
    initial_x: np.ndarray,
    *,
    coarse_method: str = "auto",
    seed: int = 42,
    max_evaluations: int = 200,
    tolerance: float = 1e-4,
    coarse_fraction: float = 0.7,
    refinement_objective: Objective | None = None,
    verification_objective: Objective | None = None,
) -> HybridSearchResult:

    if not bounds:
        raise ValueError("至少需要一个优化变量")
    if max_evaluations < 8:
        raise ValueError("混合优化至少需要8次函数评估")

    method = select_coarse_method(len(bounds), coarse_method)
    formal_objective = refinement_objective or objective
    verify_objective = verification_objective or formal_objective

    
    
    
    coarse_verification_reserve = 0 if formal_objective is objective else 1
    final_verification_reserve = 1
    search_budget = max_evaluations - (
        coarse_verification_reserve + final_verification_reserve
    )
    if search_budget < 5:
        raise ValueError("总评估预算不足以完成粗搜、精调和独立复核")
    coarse_budget = max(3, int(search_budget * coarse_fraction))
    refine_budget = max(2, search_budget - coarse_budget)
    if coarse_budget + refine_budget > search_budget:
        coarse_budget = max(3, search_budget - refine_budget)

    if method == "bayesian":
        coarse_x, coarse_value, coarse_evaluations = bayesian_coarse_search(
            objective,
            bounds,
            seed=seed,
            max_evaluations=coarse_budget,
            initial_x=initial_x,
        )
    else:
        coarse_x, coarse_value, coarse_evaluations = differential_evolution_coarse_search(
            objective,
            bounds,
            seed=seed,
            max_evaluations=coarse_budget,
        )

    if formal_objective is objective:
        coarse_verified_value = float(coarse_value)
    else:
        coarse_verified_value = float(
            formal_objective(np.asarray(coarse_x, dtype=float))
        )

    refined_x, refined_value, refinement_evaluations = powell_refine(
        formal_objective,
        coarse_x,
        bounds,
        max_evaluations=refine_budget,
        tolerance=tolerance,
    )
    if refined_value <= coarse_verified_value:
        final_x = refined_x
    else:
        final_x = coarse_x

    
    
    verified_value = float(verify_objective(np.asarray(final_x, dtype=float)))
    return HybridSearchResult(
        coarse_method=method,
        coarse_x=np.asarray(coarse_x, dtype=float),
        coarse_value=float(coarse_value),
        refined_x=np.asarray(refined_x, dtype=float),
        refined_value=float(refined_value),
        final_x=np.asarray(final_x, dtype=float),
        final_value=verified_value,
        coarse_evaluations=coarse_evaluations,
        refinement_evaluations=refinement_evaluations,
        coarse_verified_value=coarse_verified_value,
        verification_evaluations=1,
    )

