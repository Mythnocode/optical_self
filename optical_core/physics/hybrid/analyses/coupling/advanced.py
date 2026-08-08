
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions
from optical_core.physics.hybrid.solvers.fiber_coupling import (
    PreparedCouplingProblem,
    solve_coupling_convergence,
    solve_fiber_coupling,
)


@dataclass(slots=True)
class AdvancedCouplingResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_advanced_coupling(
    trace: TraceBundle,
    options: CouplingOptions,
    prepared_problem: PreparedCouplingProblem | None = None,
) -> AdvancedCouplingResult:
    base = solve_fiber_coupling(trace, options, prepared_problem=prepared_problem)
    metrics = dict(base.metrics)
    arrays = dict(base.arrays)
    warnings = list(base.warnings)
    metadata = {"analysis": "advanced_coupling", **dict(base.metadata)}

    if options.include_convergence:
        convergence = solve_coupling_convergence(trace, options)
        metrics.update(convergence["metrics"])
        arrays.update(convergence["arrays"])
        metadata.update(convergence["metadata"])

    return AdvancedCouplingResult(metrics=metrics, arrays=arrays, warnings=warnings, metadata=metadata)
