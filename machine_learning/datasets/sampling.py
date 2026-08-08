from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2
from typing import List

import numpy as np

from shared_contracts.datasets import ParameterDefinition


@dataclass(frozen=True)
class SamplingPlan:
    sample_ids: List[str]
    values: np.ndarray


def _unit_samples(dimension: int, sample_count: int, method: str, seed: int) -> np.ndarray:
    if dimension < 1:
        raise ValueError("至少需要一个采样参数")
    if sample_count < 1:
        raise ValueError("sample_count必须为正整数")

    method = str(method).strip().lower()
    try:
        from scipy.stats import qmc
    except ImportError as exc:  
        raise RuntimeError("LHS/Sobol采样需要scipy") from exc

    if method == "latin_hypercube":
        return qmc.LatinHypercube(d=dimension, seed=seed).random(n=sample_count)
    if method == "sobol":
        power = max(0, int(ceil(log2(sample_count))))
        return qmc.Sobol(d=dimension, scramble=True, seed=seed).random_base2(power)[:sample_count]
    raise ValueError(f"不支持的采样方法: {method}")


def create_sampling_plan(
    parameters: list[ParameterDefinition],
    sample_count: int,
    method: str,
    seed: int,
) -> SamplingPlan:
    lower = np.array([parameter.lower_bound for parameter in parameters], dtype=float)
    upper = np.array([parameter.upper_bound for parameter in parameters], dtype=float)
    if np.any(~np.isfinite(lower)) or np.any(~np.isfinite(upper)):
        raise ValueError("采样边界必须为有限数")
    if np.any(lower >= upper):
        raise ValueError("每个参数都必须满足lower_bound < upper_bound")

    unit = _unit_samples(len(parameters), sample_count, method, seed)
    values = lower + unit * (upper - lower)
    sample_ids = [f"sample-{index + 1:06d}" for index in range(sample_count)]
    return SamplingPlan(sample_ids=sample_ids, values=values)
