
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable, Mapping, Sequence, Any
import itertools
import numpy as np


@dataclass(frozen=True, slots=True)
class VarianceBudgetResult:
    nominal_value: float
    first_order_variance: dict[str, float]
    second_order_variance: dict[str, float]
    total_approximated_variance: float
    normalized_contribution: dict[str, float]
    category_variance: dict[str, float]
    category_normalized_contribution: dict[str, float]
    step_sizes: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def second_order_variance_budget(
    nominal: Mapping[str, float],
    standard_deviations: Mapping[str, float],
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    interactions: Sequence[tuple[str, str]] | None = None,
    parameter_categories: Mapping[str, str] | None = None,
    step_scale: float = 1.0,
) -> VarianceBudgetResult:

    base = {str(k): float(v) for k, v in nominal.items()}
    sigmas = {str(k): abs(float(v)) for k, v in standard_deviations.items() if float(v) != 0.0}
    f0 = float(evaluator(base))

    def shifted(changes: Mapping[str, float]) -> float:
        values = dict(base)
        for name, delta in changes.items():
            values[name] = values.get(name, 0.0) + float(delta)
        return float(evaluator(values))

    steps = {name: max(sigma * float(step_scale), 1.0e-12) for name, sigma in sigmas.items()}
    first: dict[str, float] = {}
    for name, sigma in sigmas.items():
        h = steps[name]
        derivative = (shifted({name: h}) - shifted({name: -h})) / (2.0 * h)
        first[name] = float((derivative * sigma) ** 2)

    pairs = list(interactions) if interactions is not None else list(itertools.combinations(sigmas, 2))
    second: dict[str, float] = {}
    for left, right in pairs:
        if left not in sigmas or right not in sigmas or left == right:
            continue
        hi, hj = steps[left], steps[right]
        mixed = (
            shifted({left: hi, right: hj})
            - shifted({left: hi, right: -hj})
            - shifted({left: -hi, right: hj})
            + shifted({left: -hi, right: -hj})
        ) / (4.0 * hi * hj)
        
        second[f"{left} x {right}"] = float((mixed * sigmas[left] * sigmas[right]) ** 2)

    total = float(sum(first.values()) + sum(second.values()))
    normalized = {
        **{name: value / max(total, 1.0e-30) for name, value in first.items()},
        **{name: value / max(total, 1.0e-30) for name, value in second.items()},
    }
    categories = {str(k): str(v) for k, v in (parameter_categories or {}).items()}
    category_variance: dict[str, float] = {}
    for name, value in first.items():
        category = categories.get(name, "uncategorized")
        category_variance[category] = category_variance.get(category, 0.0) + value
    for pair, value in second.items():
        left, right = pair.split(" x ", 1)
        left_category = categories.get(left, "uncategorized")
        right_category = categories.get(right, "uncategorized")
        category = left_category if left_category == right_category else f"{left_category} x {right_category}"
        category_variance[category] = category_variance.get(category, 0.0) + value
    category_normalized = {name: value / max(total, 1.0e-30) for name, value in category_variance.items()}
    return VarianceBudgetResult(
        nominal_value=f0,
        first_order_variance=first,
        second_order_variance=second,
        total_approximated_variance=total,
        normalized_contribution=normalized,
        category_variance=category_variance,
        category_normalized_contribution=category_normalized,
        step_sizes=steps,
    )


__all__ = ["VarianceBudgetResult", "second_order_variance_budget"]
