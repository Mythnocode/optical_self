# 一阶近轴光学分析。

from __future__ import annotations

from typing import Any
import math

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.physics.geometric.formulas.paraxial import (
    beam_size_and_radius,
    effective_focal_length_mm,
    matrix_from_first_to_after_last,
    propagate_q,
    q_from_waist,
    refraction_matrix,
    translation_matrix,
)
from optical_core.physics.geometric.analyses._native_helpers import AnalysisResult, last_vertex_mm


def system_matrix_to_after_last(system: SequentialOpticalSystem, wavelength_nm: float | None = None) -> np.ndarray:
    wavelength = float(wavelength_nm or system.wavelength_nm)
    if not system.surfaces:
        return np.eye(2, dtype=float)
    n_input = system.material_index(system.surfaces[0].material_before, wavelength)
    return matrix_from_first_to_after_last(system, wavelength) @ translation_matrix(system.object_distance_mm, n_input)


def system_matrix_to_image(system: SequentialOpticalSystem, wavelength_nm: float | None = None) -> np.ndarray:
    wavelength = float(wavelength_nm or system.wavelength_nm)
    if not system.surfaces:
        return np.eye(2, dtype=float)
    n_output = system.material_index(system.surfaces[-1].material_after, wavelength)
    return translation_matrix(system.image_distance_mm, n_output) @ matrix_from_first_to_after_last(system, wavelength)


def paraxial_image_distance_mm(
    system: SequentialOpticalSystem,
    wavelength_nm: float | None = None,
    *,
    collimated: bool = True,
) -> float:

    wavelength = float(wavelength_nm or system.wavelength_nm)
    if not system.surfaces:
        return float("inf")
    if collimated:
        matrix = matrix_from_first_to_after_last(system, wavelength)
        ray = matrix @ np.array([1.0e-4, 0.0], dtype=float)
    else:
        n_input = system.material_index(system.surfaces[0].material_before, wavelength)
        matrix = system_matrix_to_after_last(system, wavelength)
        ray = matrix @ np.array([0.0, n_input * 1.0e-4], dtype=float)
    n_output = system.material_index(system.surfaces[-1].material_after, wavelength)
    if abs(float(ray[1])) < 1.0e-15:
        return float("inf")
    return float(-n_output * ray[0] / ray[1])


def paraxial_focus_position_mm(
    system: SequentialOpticalSystem,
    wavelength_nm: float | None = None,
    *,
    collimated: bool = True,
) -> float:
    return float(last_vertex_mm(system) + paraxial_image_distance_mm(system, wavelength_nm, collimated=collimated))


def total_track_mm(system: SequentialOpticalSystem) -> float:
    return float(system.object_distance_mm + last_vertex_mm(system) + system.image_distance_mm)


def evaluate_first_order(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> AnalysisResult:
    options = dict(options or {})
    wavelength_nm = float(options.get("wavelength_nm", system.wavelength_nm))
    collimated = bool(options.get("collimated", True))
    matrix = matrix_from_first_to_after_last(system, wavelength_nm)
    image_matrix = system_matrix_to_image(system, wavelength_nm)
    efl = effective_focal_length_mm(system, wavelength_nm) if system.surfaces else float("inf")
    paraxial_image = paraxial_image_distance_mm(system, wavelength_nm, collimated=collimated)
    focus = paraxial_focus_position_mm(system, wavelength_nm, collimated=collimated)
    n_in = system.material_index(system.surfaces[0].material_before, wavelength_nm) if system.surfaces else 1.0
    n_out = system.material_index(system.surfaces[-1].material_after, wavelength_nm) if system.surfaces else 1.0
    power = 0.0 if not np.isfinite(efl) or abs(efl) < 1.0e-15 else 1.0 / efl
    metrics = {
        "first_order_effective_focal_length_mm": float(efl),
        "first_order_paraxial_image_distance_mm": float(paraxial_image),
        "first_order_paraxial_focus_z_mm": float(focus),
        "first_order_back_focal_length_mm": float(paraxial_image),
        "first_order_optical_power_per_mm": float(power),
        "first_order_optical_power_diopter": float(1000.0 * power),
        "first_order_last_vertex_z_mm": float(last_vertex_mm(system)),
        "first_order_total_track_mm": float(total_track_mm(system)),
        "first_order_input_refractive_index": float(n_in),
        "first_order_output_refractive_index": float(n_out),
        "first_order_A": float(matrix[0, 0]),
        "first_order_B": float(matrix[0, 1]),
        "first_order_C": float(matrix[1, 0]),
        "first_order_D": float(matrix[1, 1]),
    }
    arrays = {
        "first_order_matrix": matrix.tolist(),
        "first_order_image_matrix": image_matrix.tolist(),
    }
    return AnalysisResult(metrics=metrics, arrays=arrays, metadata={"first_order_done": True, "optical_axis": "+z"})


__all__ = [
    "beam_size_and_radius",
    "effective_focal_length_mm",
    "evaluate_first_order",
    "matrix_from_first_to_after_last",
    "paraxial_focus_position_mm",
    "paraxial_image_distance_mm",
    "propagate_q",
    "q_from_waist",
    "refraction_matrix",
    "system_matrix_to_after_last",
    "system_matrix_to_image",
    "total_track_mm",
    "translation_matrix",
]
