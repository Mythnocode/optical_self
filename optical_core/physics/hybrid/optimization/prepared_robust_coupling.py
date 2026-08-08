# 复用一次准备好的耦合问题，快速评价接收器扰动下的稳健性
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence, Mapping, Any
import numpy as np

from optical_core.physics.hybrid.solvers.fiber_coupling import PreparedCouplingProblem


@dataclass(frozen=True, slots=True)
class PreparedRobustCouplingResult:
    objective: float
    nominal_efficiency: float
    median_efficiency: float
    p05_efficiency: float
    p95_efficiency: float
    failure_probability: float
    efficiencies: tuple[float, ...]
    cache_metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_prepared_receiver_robustness(
    problem: PreparedCouplingProblem,
    perturbations: Sequence[Mapping[str, float]],
    *,
    minimum_efficiency: float = 0.5,
    beta_spread: float = 0.25,
    gamma_failure: float = 1.0,
) -> PreparedRobustCouplingResult:

    base = problem.options
    nominal = problem.efficiency()
    efficiencies: list[float] = []
    for delta in perturbations:
        efficiencies.append(problem.efficiency(
            offset_x_mm=float(base.offset_x_mm) + float(delta.get("fiber_x_mm", 0.0)),
            offset_y_mm=float(base.offset_y_mm) + float(delta.get("fiber_y_mm", 0.0)),
            receiver_axial_offset_z_mm=float(base.receiver_axial_offset_z_mm) + float(delta.get("fiber_z_mm", 0.0)),
            tilt_x_rad=float(base.tilt_x_rad) + float(delta.get("fiber_tilt_x_rad", 0.0)),
            tilt_y_rad=float(base.tilt_y_rad) + float(delta.get("fiber_tilt_y_rad", 0.0)),
            mode_field_diameter_x_um=float(base.mode_field_diameter_x_um) + float(delta.get("mfd_x_um", 0.0)),
            mode_field_diameter_y_um=float(base.mode_field_diameter_y_um) + float(delta.get("mfd_y_um", 0.0)),
        ))
    if not efficiencies:
        efficiencies = [nominal]
    values = np.asarray(efficiencies, dtype=float)
    p05, median, p95 = np.quantile(values, [0.05, 0.5, 0.95])
    failure = float(np.mean(values < float(minimum_efficiency)))
    objective = -float(median) + float(beta_spread) * float(p95-p05) + float(gamma_failure) * failure
    return PreparedRobustCouplingResult(
        objective=float(objective), nominal_efficiency=float(nominal), median_efficiency=float(median),
        p05_efficiency=float(p05), p95_efficiency=float(p95), failure_probability=failure,
        efficiencies=tuple(float(v) for v in values), cache_metrics=problem.cache_metrics(),
    )


__all__ = ["PreparedRobustCouplingResult", "evaluate_prepared_receiver_robustness"]
