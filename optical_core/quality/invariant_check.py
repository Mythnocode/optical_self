from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle


@dataclass(frozen=True, slots=True)
class InvariantAudit:
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings


def audit_trace_invariants(trace: TraceBundle, *, direction_norm_tolerance: float = 1e-6) -> InvariantAudit:
    warnings: list[str] = []
    valid = np.asarray(trace.valid_mask, dtype=bool)
    total = int(valid.size)
    valid_count = int(valid.sum())
    valid_fraction = valid_count / total if total else 0.0

    directions = np.asarray(trace.final_directions, dtype=float)
    if directions.size and valid_count:
        norms = np.linalg.norm(directions[valid], axis=1)
        max_norm_error = float(np.max(np.abs(norms - 1.0))) if norms.size else 0.0
        if max_norm_error > direction_norm_tolerance:
            warnings.append(f"有效出射光线方向向量未严格归一化，最大误差 {max_norm_error:.3g}。")
    else:
        max_norm_error = 0.0

    if total and valid_fraction < 0.1:
        warnings.append("有效光线比例低于 10%，请检查孔径、视场或系统参数。")

    opd = np.asarray(trace.optical_paths_mm, dtype=float)
    finite_opd_fraction = float(np.isfinite(opd[valid]).mean()) if valid_count else 0.0
    if valid_count and finite_opd_fraction < 1.0:
        warnings.append("部分有效光线的光程不是有限数值。")

    return InvariantAudit(
        metrics={
            "trace_total_ray_count": total,
            "trace_valid_ray_count": valid_count,
            "trace_valid_fraction": valid_fraction,
            "trace_direction_norm_max_error": max_norm_error,
            "trace_finite_opd_fraction": finite_opd_fraction,
        },
        warnings=tuple(warnings),
    )


__all__ = ["InvariantAudit", "audit_trace_invariants"]
