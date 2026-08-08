from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class EnergyAudit:
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings


def power_closure_error(input_power: float, output_power: float) -> float:
    if input_power == 0:
        return 0.0 if output_power == 0 else float("inf")
    return abs(output_power - input_power) / abs(input_power)


def field_power(field: ScalarField2D) -> float:
    return float(np.sum(np.abs(field.values) ** 2) * abs(field.grid.dx_mm * field.grid.dy_mm))


def audit_field_energy(input_field: ScalarField2D, output_field: ScalarField2D, *, tolerance: float = 0.15) -> EnergyAudit:
    input_power = field_power(input_field)
    output_power = field_power(output_field)
    error = power_closure_error(input_power, output_power)
    warnings: list[str] = []
    if np.isfinite(error) and error > tolerance:
        warnings.append(f"输入/输出场能量闭合误差 {error:.3g}，可能存在归一化、截断或采样问题。")
    elif not np.isfinite(error):
        warnings.append("输入场功率为零但输出场非零，能量闭合异常。")
    return EnergyAudit(
        metrics={
            "energy_input_power_a.u.": input_power,
            "energy_output_power_a.u.": output_power,
            "energy_closure_error": float(error),
        },
        warnings=tuple(warnings),
    )


__all__ = ["EnergyAudit", "power_closure_error", "field_power", "audit_field_energy"]
