#功率审计。
# 统计输入功率、有效光线功率、被遮挡功率、几何通光率、界面损耗、材料吸收损耗、估算系统总透过率和功率闭合误差
from __future__ import annotations

from typing import Any

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.geometric.formulas.throughput import (
    power_closure_error,
    sequence_transmission_budget,
)


def evaluate_power_audit(trace: TraceBundle, system: Any, options: dict[str, Any] | None = None) -> dict[str, Any]:

    opts = dict(options or {})
    power_weights = np.asarray(trace.power_weights, dtype=float)
    quadrature_weights = np.asarray(trace.quadrature_weights, dtype=float)
    valid_mask = np.asarray(trace.valid_mask, dtype=bool)
    integration_weights = power_weights * quadrature_weights

    if integration_weights.size == 0:
        input_power = 0.0
        valid_power = 0.0
        geometric = 0.0
    else:
        input_power = float(np.sum(integration_weights, dtype=np.float64))
        valid_power = float(np.sum(integration_weights[valid_mask], dtype=np.float64))
        geometric = valid_power / input_power if input_power > 0.0 else 0.0

    wavelength_nm = float(opts.get("wavelength_nm", getattr(system, "wavelength_nm", 550.0)))
    rows = sequence_transmission_budget(system, wavelength_nm)
    interface_transmission = float(np.prod([row.interface_transmission for row in rows], dtype=np.float64)) if rows else 1.0
    bulk_transmission = float(np.prod([row.bulk_transmission for row in rows], dtype=np.float64)) if rows else 1.0
    sequence_transmission = float(interface_transmission * bulk_transmission)

    weighted_ray_power_throughput = valid_power / input_power if input_power > 0.0 else 0.0
    estimated_system_throughput = float(np.clip(geometric * sequence_transmission, 0.0, 1.0))
    loss_fraction = float(np.clip(1.0 - estimated_system_throughput, 0.0, 1.0))
    closure = power_closure_error(1.0, estimated_system_throughput, loss_fraction)

    return {
        "metrics": {
            "power_input_a.u.": input_power,
            "power_valid_a.u.": valid_power,
            "power_blocked_a.u.": max(0.0, input_power - valid_power),
            "geometric_throughput": geometric,
            "weighted_ray_power_throughput": float(np.clip(weighted_ray_power_throughput, 0.0, 1.0)),
            "sequence_interface_transmission": interface_transmission,
            "sequence_bulk_transmission": bulk_transmission,
            "sequence_transmission": sequence_transmission,
            "estimated_system_throughput": estimated_system_throughput,
            "power_loss_fraction": loss_fraction,
            "power_closure_error": closure,
        },
        "arrays": {
            "surface_interface_transmission": [row.interface_transmission for row in rows],
            "surface_bulk_transmission": [row.bulk_transmission for row in rows],
            "surface_cumulative_transmission": [row.cumulative_transmission for row in rows],
        },
        "metadata": {
            "power_audit_model": "explicit_power_times_quadrature_weight",
            "surface_count": len(rows),
        },
    }
