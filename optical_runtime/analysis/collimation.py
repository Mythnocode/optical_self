
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, pi, sqrt
from typing import Any, Mapping

import numpy as np

from optical_core.physics.geometric.formulas.paraxial import (
    beam_size_and_radius,
    propagate_q,
    q_from_waist,
    refraction_matrix,
    translation_matrix,
)
from optical_runtime.project_mapper import build_optical_system
from shared_contracts.metrics import read_metric
from shared_contracts.optimization import CollimationConstraint
from shared_contracts.project import ProjectSnapshot


class CollimationConstraintError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CollimationAssessment:


    feasible: bool
    score: float
    penalty: float
    metrics: dict[str, Any]
    violations: dict[str, float]
    warnings: tuple[str, ...] = ()


def active_collimation_constraint(
    constraints: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> CollimationConstraint | None:

    for raw in constraints:
        if str(raw.get("type", "")).strip().lower() != "collimation":
            continue
        parsed = CollimationConstraint.model_validate(raw)
        if parsed.enabled:
            return parsed
    return None


def evaluate_collimation_constraint(
    project: ProjectSnapshot,
    constraint: CollimationConstraint | Mapping[str, Any],
    *,
    formal_metrics: Mapping[str, Any] | None = None,
) -> CollimationAssessment:

    config = (
        constraint
        if isinstance(constraint, CollimationConstraint)
        else CollimationConstraint.model_validate(constraint)
    )
    system = build_optical_system(project)
    selected_position, selected_index = _select_surface(system, config)
    warnings: list[str] = []

    clear_span_violation = 0.0
    available_span = _available_clear_span_mm(system, selected_position, project)
    requested_end = config.plane_start_offset_mm + config.evaluation_span_mm
    if (
        config.require_clear_span
        and available_span is not None
        and requested_end > available_span + 1.0e-12
    ):
        clear_span_violation = (
            requested_end - available_span
        ) / max(config.evaluation_span_mm, 1.0e-12)
        warnings.append(
            "准直评价区间越过下一光学表面；请缩短evaluation_span_mm或选择正确的准直输出表面"
        )

    wavelength_mm = float(project.source.wavelength_nm) * 1.0e-6
    if wavelength_mm <= 0.0:
        raise CollimationConstraintError("准直约束要求波长大于0")

    partial_matrix, n_input, n_output = _matrix_to_selected_surface(
        system, selected_position, project.source.wavelength_nm
    )
    x_state = _axis_planes(
        project,
        partial_matrix,
        n_input,
        n_output,
        wavelength_mm,
        config,
        axis="x",
    )
    y_state = _axis_planes(
        project,
        partial_matrix,
        n_input,
        n_output,
        wavelength_mm,
        config,
        axis="y",
    )

    radius_change_x = _relative_change(x_state["w1_mm"], x_state["w2_mm"])
    radius_change_y = _relative_change(y_state["w1_mm"], y_state["w2_mm"])
    radius_change = max(radius_change_x, radius_change_y)

    normalized_curvature_x = max(
        _normalized_curvature(
            x_state["w1_mm"], x_state["r1_mm"], wavelength_mm, n_output
        ),
        _normalized_curvature(
            x_state["w2_mm"], x_state["r2_mm"], wavelength_mm, n_output
        ),
    )
    normalized_curvature_y = max(
        _normalized_curvature(
            y_state["w1_mm"], y_state["r1_mm"], wavelength_mm, n_output
        ),
        _normalized_curvature(
            y_state["w2_mm"], y_state["r2_mm"], wavelength_mm, n_output
        ),
    )
    normalized_curvature = max(normalized_curvature_x, normalized_curvature_y)

    centroid_drift_mm = sqrt(
        (x_state["c2_mm"] - x_state["c1_mm"]) ** 2
        + (y_state["c2_mm"] - y_state["c1_mm"]) ** 2
    )
    reference_radius_mm = max(
        sqrt(x_state["w1_mm"] * y_state["w1_mm"]),
        sqrt(x_state["w2_mm"] * y_state["w2_mm"]),
        1.0e-15,
    )
    centroid_drift_fraction = centroid_drift_mm / reference_radius_mm
    axis_tilt_mrad = 1000.0 * sqrt(
        x_state["angle_rad"] ** 2 + y_state["angle_rad"] ** 2
    )

    ratios = {
        "radius_change": radius_change / config.max_radius_change_fraction,
        "normalized_curvature": normalized_curvature
        / config.max_normalized_curvature,
        "centroid_drift": centroid_drift_fraction
        / config.max_centroid_drift_fraction,
        "axis_tilt": axis_tilt_mrad / config.max_axis_tilt_mrad,
    }
    
    
    score = float(exp(-0.05 * np.mean(np.square(list(ratios.values())))))

    violations = {
        name: max(0.0, float(ratio) - 1.0) for name, ratio in ratios.items()
    }
    if clear_span_violation > 0.0:
        violations["clear_span"] = float(clear_span_violation)
    if score < config.minimum_score:
        violations["minimum_score"] = (
            config.minimum_score - score
        ) / max(config.minimum_score, 1.0e-12)

    edge_power = None
    if config.max_edge_power_fraction is not None and formal_metrics is not None:
        raw_edge = read_metric(formal_metrics, "propagation_edge_power_fraction")
        if isinstance(raw_edge, (int, float)) and isfinite(float(raw_edge)):
            edge_power = float(raw_edge)
            violations["edge_power"] = max(
                0.0,
                edge_power / max(config.max_edge_power_fraction, 1.0e-15) - 1.0,
            )
        else:
            warnings.append("正式仿真未返回边缘功率，未执行准直边缘功率约束")

    finite = all(
        isfinite(float(value))
        for value in (
            radius_change,
            normalized_curvature,
            centroid_drift_fraction,
            axis_tilt_mrad,
            score,
        )
    )
    if not finite:
        violations["non_finite"] = 1.0

    violation_energy = float(sum(value * value for value in violations.values()))
    penalty = float(config.penalty_weight * violation_energy)
    feasible = finite and not any(value > 0.0 for value in violations.values())
    if config.hard and not feasible:
        penalty += 1.0e6

    metrics: dict[str, Any] = {
        "collimation_feasible": 1.0 if feasible else 0.0,
        "collimation_score": score,
        "collimation_surface_index": float(selected_index),
        "collimation_plane_start_offset_mm": config.plane_start_offset_mm,
        "collimation_evaluation_span_mm": config.evaluation_span_mm,
        "collimation_available_clear_span_mm": (
            None if available_span is None else float(available_span)
        ),
        "collimation_radius_change_fraction": radius_change,
        "collimation_radius_change_fraction_x": radius_change_x,
        "collimation_radius_change_fraction_y": radius_change_y,
        "collimation_normalized_curvature": normalized_curvature,
        "collimation_normalized_curvature_x": normalized_curvature_x,
        "collimation_normalized_curvature_y": normalized_curvature_y,
        "collimation_centroid_drift_mm": centroid_drift_mm,
        "collimation_centroid_drift_fraction": centroid_drift_fraction,
        "collimation_axis_tilt_mrad": axis_tilt_mrad,
        "collimation_beam_radius_x_plane1_mm": x_state["w1_mm"],
        "collimation_beam_radius_x_plane2_mm": x_state["w2_mm"],
        "collimation_beam_radius_y_plane1_mm": y_state["w1_mm"],
        "collimation_beam_radius_y_plane2_mm": y_state["w2_mm"],
        "collimation_wavefront_radius_x_plane1_mm": _finite_or_none(x_state["r1_mm"]),
        "collimation_wavefront_radius_x_plane2_mm": _finite_or_none(x_state["r2_mm"]),
        "collimation_wavefront_radius_y_plane1_mm": _finite_or_none(y_state["r1_mm"]),
        "collimation_wavefront_radius_y_plane2_mm": _finite_or_none(y_state["r2_mm"]),
        "collimation_penalty": penalty,
        "collimation_violation_count": float(
            sum(value > 0.0 for value in violations.values())
        ),
    }
    if edge_power is not None:
        metrics["collimation_edge_power_fraction"] = edge_power

    return CollimationAssessment(
        feasible=feasible,
        score=score,
        penalty=penalty,
        metrics=metrics,
        violations=violations,
        warnings=tuple(warnings),
    )


def _select_surface(system, config: CollimationConstraint) -> tuple[int | None, int]:
    if not system.surfaces:
        if config.after_surface_index is not None:
            raise CollimationConstraintError("空光学系统不能指定after_surface_index")
        return None, -1

    if config.after_surface_index is not None:
        for position, surface in enumerate(system.surfaces):
            if int(surface.index) == int(config.after_surface_index):
                return position, int(surface.index)
        raise CollimationConstraintError(
            f"未找到准直约束指定表面: {config.after_surface_index}"
        )

    accepted_roles = {"collimation_end", "collimator_output", "collimator"}
    for position in range(len(system.surfaces) - 1, -1, -1):
        surface = system.surfaces[position]
        role = str(dict(surface.metadata or {}).get("role", "")).strip().lower()
        if role in accepted_roles:
            return position, int(surface.index)
    return len(system.surfaces) - 1, int(system.surfaces[-1].index)


def _available_clear_span_mm(system, position: int | None, project: ProjectSnapshot):
    if position is None:
        return None
    if position < len(system.surfaces) - 1:
        return max(0.0, float(system.surfaces[position].distance_to_next_mm))
    
    
    
    del project
    return None


def _matrix_to_selected_surface(system, position: int | None, wavelength_nm: float):
    if position is None or not system.surfaces:
        return np.eye(2, dtype=float), 1.0, 1.0
    n_input = float(
        system.material_index(system.surfaces[0].material_before, wavelength_nm)
    )
    matrix = np.eye(2, dtype=float)
    n_output = n_input
    for index, surface in enumerate(system.surfaces):
        n_before = float(system.material_index(surface.material_before, wavelength_nm))
        n_after = float(system.material_index(surface.material_after, wavelength_nm))
        matrix = refraction_matrix(surface, n_before, n_after) @ matrix
        n_output = n_after
        if index == position:
            break
        matrix = translation_matrix(surface.distance_to_next_mm, n_after) @ matrix
    return matrix, n_input, n_output


def _axis_planes(
    project: ProjectSnapshot,
    partial_matrix: np.ndarray,
    n_input: float,
    n_output: float,
    wavelength_mm: float,
    config: CollimationConstraint,
    *,
    axis: str,
) -> dict[str, float]:
    source = project.source
    waist_mm = float(getattr(source, f"waist_{axis}_mm"))
    m2 = float(getattr(source, f"beam_quality_m2_{axis}") or source.beam_quality_m2)
    effective_wavelength_mm = m2 * wavelength_mm
    na = max(float(getattr(source, f"object_na_{axis}")), 1.0e-12)
    if waist_mm <= 0.0:
        waist_mm = effective_wavelength_mm / (pi * na)

    waist_position_mm = float(getattr(source, f"waist_position_{axis}_mm"))
    distance_to_first_mm = float(project.object_distance_mm) - waist_position_mm
    to_selected = partial_matrix @ translation_matrix(distance_to_first_mm, n_input)
    q_selected = propagate_q(
        to_selected, q_from_waist(waist_mm, effective_wavelength_mm)
    )
    plane1 = config.plane_start_offset_mm
    plane2 = plane1 + config.evaluation_span_mm
    q1 = propagate_q(translation_matrix(plane1, n_output), q_selected)
    q2 = propagate_q(translation_matrix(plane2, n_output), q_selected)
    w1, r1 = beam_size_and_radius(q1, effective_wavelength_mm, n_output)
    w2, r2 = beam_size_and_radius(q2, effective_wavelength_mm, n_output)

    input_ray = np.asarray(
        [
            float(getattr(source, f"center_{axis}_mm")),
            n_input * float(getattr(source, f"axis_tilt_{axis}_rad")),
        ],
        dtype=float,
    )
    ray_selected = to_selected @ input_ray
    ray1 = translation_matrix(plane1, n_output) @ ray_selected
    ray2 = translation_matrix(plane2, n_output) @ ray_selected
    return {
        "w1_mm": float(w1),
        "w2_mm": float(w2),
        "r1_mm": float(r1),
        "r2_mm": float(r2),
        "c1_mm": float(ray1[0]),
        "c2_mm": float(ray2[0]),
        "angle_rad": float(ray_selected[1]) / max(n_output, 1.0e-15),
    }


def _finite_or_none(value: float) -> float | None:
    return float(value) if isfinite(float(value)) else None


def _relative_change(first: float, second: float) -> float:
    return abs(float(second) - float(first)) / max(
        0.5 * (abs(float(first)) + abs(float(second))), 1.0e-15
    )


def _normalized_curvature(
    beam_radius_mm: float,
    curvature_radius_mm: float,
    wavelength_mm: float,
    refractive_index: float,
) -> float:
    if not isfinite(curvature_radius_mm):
        return 0.0
    k = 2.0 * pi * float(refractive_index) / max(float(wavelength_mm), 1.0e-15)
    return abs(k * float(beam_radius_mm) ** 2 / (2.0 * curvature_radius_mm))


__all__ = [
    "CollimationAssessment",
    "CollimationConstraintError",
    "active_collimation_constraint",
    "evaluate_collimation_constraint",
]
