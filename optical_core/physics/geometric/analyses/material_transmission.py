# 材料和界面透射分析。

from __future__ import annotations

from typing import Any

import numpy as np

from optical_core.physics.geometric.formulas.throughput import sequence_transmission_budget


def evaluate_material_transmission(system: Any, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = dict(options or {})
    wavelength_nm = float(opts.get("wavelength_nm", getattr(system, "wavelength_nm", 550.0)))
    rows = sequence_transmission_budget(system, wavelength_nm)

    interface_total = float(np.prod([row.interface_transmission for row in rows], dtype=np.float64)) if rows else 1.0
    bulk_total = float(np.prod([row.bulk_transmission for row in rows], dtype=np.float64)) if rows else 1.0
    total = float(interface_total * bulk_total)

    return {
        "metrics": {
            "material_interface_transmission": interface_total,
            "material_bulk_transmission": bulk_total,
            "material_total_transmission": total,
            "material_surface_count": float(len(rows)),
        },
        "arrays": {
            "material_surface_index": [row.surface_index for row in rows],
            "material_n_before": [row.n_before for row in rows],
            "material_n_after": [row.n_after for row in rows],
            "material_distance_to_next_mm": [row.distance_to_next_mm for row in rows],
            "material_interface_transmission_by_surface": [row.interface_transmission for row in rows],
            "material_bulk_transmission_by_surface": [row.bulk_transmission for row in rows],
            "material_cumulative_transmission_by_surface": [row.cumulative_transmission for row in rows],
        },
        "metadata": {
            "wavelength_nm": wavelength_nm,
            "model": "normal_incidence_fresnel_plus_optional_bulk_absorption",
        },
    }
