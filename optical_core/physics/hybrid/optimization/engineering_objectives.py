# 优化目标函数工具箱

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Callable, Mapping, Sequence
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class EfficiencyBreakdown:
    field_overlap: float
    transmission: float = 1.0
    facet: float = 1.0
    polarization: float = 1.0
    propagation: float = 1.0
    connector: float = 1.0

    @property
    def total(self) -> float:
        return float(np.prod([
            max(self.field_overlap, 0.0), max(self.transmission, 0.0),
            max(self.facet, 0.0), max(self.polarization, 0.0),
            max(self.propagation, 0.0), max(self.connector, 0.0),
        ]))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "EfficiencyBreakdown":
        return cls(
            field_overlap=float(values.get("field_overlap", values.get("complex_field_overlap_efficiency", values.get("efficiency", 0.0)))),
            transmission=float(values.get("transmission", values.get("transmission_efficiency", 1.0))),
            facet=float(values.get("facet", values.get("fiber_facet_transmission", 1.0))),
            polarization=float(values.get("polarization", values.get("polarization_overlap_efficiency", 1.0))),
            propagation=float(values.get("propagation", values.get("fiber_propagation_transmission", 1.0))),
            connector=float(values.get("connector", values.get("fiber_connector_transmission", 1.0))),
        )


@dataclass(frozen=True, slots=True)
class EfficiencyUpperBound:


    total_efficiency_upper_bound: float
    transmission: float
    facet: float
    polarization: float
    propagation: float
    connector: float


def total_efficiency_upper_bound(
    *,
    transmission: float = 1.0,
    facet: float = 1.0,
    polarization: float = 1.0,
    propagation: float = 1.0,
    connector: float = 1.0,
) -> EfficiencyUpperBound:


    factors = tuple(float(np.clip(value, 0.0, 1.0)) for value in (
        transmission, facet, polarization, propagation, connector,
    ))
    return EfficiencyUpperBound(
        total_efficiency_upper_bound=float(np.prod(factors)),
        transmission=factors[0], facet=factors[1], polarization=factors[2],
        propagation=factors[3], connector=factors[4],
    )


def can_prune_by_efficiency_upper_bound(
    bound: EfficiencyUpperBound | float,
    *,
    minimum_required_efficiency: float,
    tolerance: float = 0.0,
) -> bool:
    value = (
        float(bound.total_efficiency_upper_bound)
        if isinstance(bound, EfficiencyUpperBound)
        else float(bound)
    )
    return bool(value + max(float(tolerance), 0.0) < float(minimum_required_efficiency))


@dataclass(frozen=True, slots=True)
class BroadbandObjectiveWeights:
    mean_total_efficiency: float = 1.0
    spectral_range: float = 0.25
    best_focus_std_mm: float = 0.1
    surface_count: float = 0.0
    engineering_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class BroadbandObjectiveResult:
    objective: float
    fixed_plane_z_mm: float
    mean_total_efficiency: float
    min_total_efficiency: float
    max_total_efficiency: float
    spectral_efficiency_range: float
    best_focus_std_mm: float
    wavelengths_nm: tuple[float, ...]
    spectral_weights: tuple[float, ...]
    total_efficiencies: tuple[float, ...]
    field_overlap_efficiencies: tuple[float, ...]
    best_focus_z_mm: tuple[float, ...]
    loss_breakdowns: tuple[dict[str, float], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_fixed_plane_broadband(
    wavelengths_nm: Sequence[float],
    evaluator: Callable[[float, float], Mapping[str, Any] | EfficiencyBreakdown],
    *,
    fixed_plane_z_mm: float,
    spectral_weights: Sequence[float] | None = None,
    best_focus_finder: Callable[[float], float] | None = None,
    weights: BroadbandObjectiveWeights = BroadbandObjectiveWeights(),
    surface_count: int = 0,
    engineering_cost: float = 0.0,
) -> BroadbandObjectiveResult:
    wavelengths = np.asarray(wavelengths_nm, dtype=float).reshape(-1)
    if wavelengths.size == 0 or np.any(~np.isfinite(wavelengths)) or np.any(wavelengths <= 0):
        raise ValueError("wavelengths_nm must contain positive finite values")
    if spectral_weights is None:
        power = np.ones(wavelengths.size, dtype=float)
    else:
        power = np.asarray(spectral_weights, dtype=float).reshape(-1)
        if power.size != wavelengths.size or np.any(~np.isfinite(power)) or np.any(power < 0):
            raise ValueError("spectral_weights must match wavelengths and be non-negative")
    power = power / max(float(np.sum(power)), 1.0e-30)

    breakdowns: list[EfficiencyBreakdown] = []
    best_z: list[float] = []
    for wavelength in wavelengths:
        raw = evaluator(float(wavelength), float(fixed_plane_z_mm))
        breakdowns.append(raw if isinstance(raw, EfficiencyBreakdown) else EfficiencyBreakdown.from_mapping(raw))
        best_z.append(float(fixed_plane_z_mm if best_focus_finder is None else best_focus_finder(float(wavelength))))
    totals = np.asarray([item.total for item in breakdowns], dtype=float)
    fields = np.asarray([item.field_overlap for item in breakdowns], dtype=float)
    mean_total = float(np.dot(power, totals))
    spectral_range = float(np.max(totals) - np.min(totals))
    focus_std = float(np.std(best_z))
    objective = (
        -float(weights.mean_total_efficiency) * mean_total
        + float(weights.spectral_range) * spectral_range
        + float(weights.best_focus_std_mm) * focus_std
        + float(weights.surface_count) * int(surface_count)
        + float(weights.engineering_cost) * float(engineering_cost)
    )
    return BroadbandObjectiveResult(
        objective=float(objective), fixed_plane_z_mm=float(fixed_plane_z_mm),
        mean_total_efficiency=mean_total, min_total_efficiency=float(np.min(totals)),
        max_total_efficiency=float(np.max(totals)), spectral_efficiency_range=spectral_range,
        best_focus_std_mm=focus_std, wavelengths_nm=tuple(float(v) for v in wavelengths),
        spectral_weights=tuple(float(v) for v in power), total_efficiencies=tuple(float(v) for v in totals),
        field_overlap_efficiencies=tuple(float(v) for v in fields), best_focus_z_mm=tuple(best_z),
        loss_breakdowns=tuple({**asdict(item), "total": item.total} for item in breakdowns),
    )


@dataclass(frozen=True, slots=True)
class EngineeringCostWeights:
    lens: float = 1.0
    asphere: float = 3.0
    material: float = 0.5
    coating: float = 0.5
    small_radius: float = 1.0
    asphere_departure: float = 1.0
    surface_slope: float = 1.0
    air_gap_difficulty: float = 1.0
    fiber_positioning: float = 1.0


def engineering_cost(
    *,
    lens_count: int,
    asphere_count: int = 0,
    material_count: int = 1,
    coating_count: int = 0,
    minimum_radius_mm: float | None = None,
    max_asphere_departure_um: float = 0.0,
    max_surface_slope: float = 0.0,
    minimum_air_gap_mm: float | None = None,
    required_fiber_positioning_um: float | None = None,
    weights: EngineeringCostWeights = EngineeringCostWeights(),
) -> tuple[float, dict[str, float]]:
    small_radius_penalty = 0.0 if minimum_radius_mm is None else 1.0 / max(abs(float(minimum_radius_mm)), 1.0e-6)
    gap_penalty = 0.0 if minimum_air_gap_mm is None else 1.0 / max(float(minimum_air_gap_mm), 1.0e-6)
    fiber_penalty = 0.0 if required_fiber_positioning_um is None else 1.0 / max(float(required_fiber_positioning_um), 1.0e-6)
    components = {
        "lens": float(weights.lens) * int(lens_count),
        "asphere": float(weights.asphere) * int(asphere_count),
        "material": float(weights.material) * int(material_count),
        "coating": float(weights.coating) * int(coating_count),
        "small_radius": float(weights.small_radius) * small_radius_penalty,
        "asphere_departure": float(weights.asphere_departure) * max(float(max_asphere_departure_um), 0.0),
        "surface_slope": float(weights.surface_slope) * max(float(max_surface_slope), 0.0),
        "air_gap_difficulty": float(weights.air_gap_difficulty) * gap_penalty,
        "fiber_positioning": float(weights.fiber_positioning) * fiber_penalty,
    }
    return float(sum(components.values())), components


@dataclass(frozen=True, slots=True)
class RobustObjectiveResult:
    objective: float
    median_efficiency: float
    p05_efficiency: float
    p95_efficiency: float
    spread_p95_p05: float
    failure_probability: float
    efficiencies: tuple[float, ...]
    perturbations: tuple[dict[str, float], ...]


def evaluate_low_cost_robust_objective(
    nominal_design: Mapping[str, float],
    perturbations: Sequence[Mapping[str, float]],
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    beta_spread: float = 0.25,
    gamma_failure: float = 1.0,
    minimum_efficiency: float = 0.5,
) -> RobustObjectiveResult:
    samples: list[float] = []
    realized: list[dict[str, float]] = []
    for delta in perturbations:
        candidate = {str(k): float(v) for k, v in nominal_design.items()}
        for name, change in delta.items():
            candidate[str(name)] = candidate.get(str(name), 0.0) + float(change)
        samples.append(float(evaluator(candidate)))
        realized.append({str(k): float(v) for k, v in delta.items()})
    if not samples:
        samples.append(float(evaluator(nominal_design)))
        realized.append({})
    values = np.asarray(samples, dtype=float)
    p05, median, p95 = np.quantile(values, [0.05, 0.5, 0.95])
    failure = float(np.mean(values < float(minimum_efficiency)))
    objective = -float(median) + float(beta_spread) * float(p95 - p05) + float(gamma_failure) * failure
    return RobustObjectiveResult(
        objective=float(objective), median_efficiency=float(median), p05_efficiency=float(p05),
        p95_efficiency=float(p95), spread_p95_p05=float(p95-p05), failure_probability=failure,
        efficiencies=tuple(float(v) for v in values), perturbations=tuple(realized),
    )



def default_low_cost_perturbations(scales: Mapping[str, float]) -> list[dict[str, float]]:

    names = [str(name) for name, value in scales.items() if float(value) != 0.0]
    if not names:
        return [{}]
    count = min(8, max(4, 2 * min(len(names), 4)))
    points: list[dict[str, float]] = []
    for index in range(count):
        point: dict[str, float] = {}
        for column, name in enumerate(names):
            
            sign = 1.0 if ((index >> (column % 3)) & 1) == 0 else -1.0
            point[name] = sign * abs(float(scales[name]))
        points.append(point)
    return points


@dataclass(frozen=True, slots=True)
class MonteCarloRobustnessResult:
    sample_count: int
    mean_efficiency: float
    median_efficiency: float
    p05_efficiency: float
    p95_efficiency: float
    minimum_efficiency: float
    yield_probability: float
    failure_probability: float
    efficiencies: tuple[float, ...]


def run_formal_robust_monte_carlo(
    nominal_design: Mapping[str, float],
    standard_deviations: Mapping[str, float],
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    sample_count: int = 256,
    minimum_efficiency: float = 0.5,
    seed: int = 42,
    sampling_method: str = "sobol",
) -> MonteCarloRobustnessResult:

    from scipy.stats import norm, qmc

    names = [str(name) for name, sigma in standard_deviations.items() if float(sigma) != 0.0]
    n = max(int(sample_count), 1)
    if not names:
        values = np.full(n, float(evaluator(nominal_design)), dtype=float)
    else:
        method = str(sampling_method).lower()
        if method == "sobol":
            sampler = qmc.Sobol(d=len(names), scramble=True, seed=int(seed))
            exponent = int(math.ceil(math.log2(n)))
            unit = sampler.random_base2(exponent)[:n]
        elif method == "lhs":
            unit = qmc.LatinHypercube(d=len(names), seed=int(seed)).random(n)
        else:
            unit = np.random.default_rng(seed).random((n, len(names)))
        normal_samples = norm.ppf(np.clip(unit, 1.0e-12, 1.0 - 1.0e-12))
        results: list[float] = []
        for row in normal_samples:
            candidate = {str(k): float(v) for k, v in nominal_design.items()}
            for name, standard, draw in zip(names, (standard_deviations[name] for name in names), row):
                candidate[name] = candidate.get(name, 0.0) + float(standard) * float(draw)
            results.append(float(evaluator(candidate)))
        values = np.asarray(results, dtype=float)
    p05, median, p95 = np.quantile(values, [0.05, 0.5, 0.95])
    yield_probability = float(np.mean(values >= float(minimum_efficiency)))
    return MonteCarloRobustnessResult(
        sample_count=n, mean_efficiency=float(np.mean(values)), median_efficiency=float(median),
        p05_efficiency=float(p05), p95_efficiency=float(p95), minimum_efficiency=float(np.min(values)),
        yield_probability=yield_probability, failure_probability=1.0-yield_probability,
        efficiencies=tuple(float(v) for v in values),
    )

def pareto_front(records: Sequence[Mapping[str, float]], objectives: Sequence[tuple[str, str]]) -> list[int]:

    if not objectives:
        return list(range(len(records)))
    values = np.asarray([
        [float(row[name]) * (1.0 if direction == "min" else -1.0) for name, direction in objectives]
        for row in records
    ], dtype=float)
    keep: list[int] = []
    for i in range(len(records)):
        dominated = False
        for j in range(len(records)):
            if i == j:
                continue
            if np.all(values[j] <= values[i]) and np.any(values[j] < values[i]):
                dominated = True
                break
        if not dominated:
            keep.append(i)
    return keep


__all__ = [
    "EfficiencyBreakdown", "BroadbandObjectiveWeights", "BroadbandObjectiveResult",
    "evaluate_fixed_plane_broadband", "EngineeringCostWeights", "engineering_cost",
    "RobustObjectiveResult", "evaluate_low_cost_robust_objective",
    "default_low_cost_perturbations", "MonteCarloRobustnessResult",
    "run_formal_robust_monte_carlo", "pareto_front",
]
