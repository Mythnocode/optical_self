from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ConvergenceAudit:
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings


def relative_change(previous: float, current: float) -> float:
    scale = max(abs(previous), 1e-30)
    return abs(current - previous) / scale


def audit_scalar_convergence(previous: float, current: float, *, tolerance: float = 1e-3, name: str = "metric") -> ConvergenceAudit:
    change = relative_change(previous, current)
    warnings: list[str] = []
    if change > tolerance:
        warnings.append(f"{name} 相对变化 {change:.3g}，尚未达到收敛阈值 {tolerance:.3g}。")
    return ConvergenceAudit(metrics={f"{name}_relative_change": float(change)}, warnings=tuple(warnings))


__all__ = ["ConvergenceAudit", "relative_change", "audit_scalar_convergence"]
