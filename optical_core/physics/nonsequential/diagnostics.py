
from __future__ import annotations

import math

import numpy as np

from optical_core.physics.nonsequential.models import RayTreeResult


def estimate_fiber_stray_coupling(
    result: RayTreeResult,
    *,
    mode_field_diameter_um: float,
    wavelength_nm: float,
    fiber_x_mm: float = 0.0,
    fiber_y_mm: float = 0.0,
    fiber_direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> dict[str, float]:

    waist_mm = max(float(mode_field_diameter_um) * 0.5e-3, 1.0e-15)
    wavelength_mm = float(wavelength_nm) * 1.0e-6
    k = 2.0 * math.pi / wavelength_mm
    fiber_direction_array = np.asarray(fiber_direction, dtype=float)
    fiber_direction_array /= np.linalg.norm(fiber_direction_array)
    primary_coupled = 0.0
    ghost_coupled = 0.0
    for node in result.detector_nodes:
        x, y, _ = node.detector_position_mm
        radius2 = (x - fiber_x_mm) ** 2 + (y - fiber_y_mm) ** 2
        direction = np.asarray(node.detector_direction, dtype=float)
        direction /= np.linalg.norm(direction)
        angle = math.acos(float(np.clip(np.dot(direction, fiber_direction_array), -1.0, 1.0)))
        acceptance = math.exp(-2.0 * radius2 / waist_mm**2) * math.exp(
            -0.5 * (k * waist_mm * angle) ** 2
        )
        coupled = node.power * acceptance
        if "R" in node.path_signature or "D" in node.path_signature:
            ghost_coupled += coupled
        else:
            primary_coupled += coupled
    return {
        "ray_tree_primary_fiber_coupled_power_estimate": float(primary_coupled),
        "ray_tree_ghost_fiber_coupled_power_estimate": float(ghost_coupled),
        "ray_tree_ghost_to_primary_fiber_coupling_estimate": float(
            ghost_coupled / max(primary_coupled, 1.0e-30)
        ),
    }


__all__ = ["estimate_fiber_stray_coupling"]
