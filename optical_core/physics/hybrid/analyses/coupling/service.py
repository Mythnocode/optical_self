# 光纤耦合分析的统一入口。
# 调用高级耦合求解并整理成标准结果。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.analyses.coupling.advanced import evaluate_advanced_coupling
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions
from optical_core.physics.hybrid.solvers.fiber_coupling import PreparedCouplingProblem


@dataclass(slots=True)
class CouplingAnalysisResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_coupling(
    trace: TraceBundle,
    options: CouplingOptions,
    prepared_problem: PreparedCouplingProblem | None = None,
) -> CouplingAnalysisResult:
    result = evaluate_advanced_coupling(trace, options, prepared_problem=prepared_problem)
    return CouplingAnalysisResult(
        metrics=dict(result.metrics),
        arrays=dict(result.arrays),
        warnings=list(result.warnings),
        metadata={"analysis": "coupling", **dict(result.metadata)},
    )
