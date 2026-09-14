
from __future__ import annotations

from math import isfinite, log, log10, pi, sqrt
from typing import Any, Mapping

import numpy as np

from machine_learning.explainability.physics_features import (
    PhysicsFeatureError,
    compute_physics_features,
)
from optical_core.physics.geometric.analyses.first_order import system_matrix_to_image
from optical_core.physics.geometric.formulas.paraxial import (
    beam_size_and_radius,
    propagate_q,
    q_from_waist,
    translation_matrix,
)
from optical_core.models.project_mapper import build_optical_system
from shared_contracts.metrics import canonical_metric_name, read_metric
from shared_contracts.project import ProjectSnapshot

PHYSICS_RESIDUAL_FEATURE_PATHS: tuple[str, ...] = (
    "size_log_mismatch",
    "size_log_signed",
    "size_ratio",
    "fiber_mode_radius_um",
    "beam_radius_at_receiver_um",
    "lateral_mismatch",
    "angular_mismatch",
    "axial_mismatch",
    "curvature_mismatch",
)

PHYSICS_RESIDUAL_FEATURE_UNITS: dict[str, str] = {
    "size_log_mismatch": "1",
    "size_log_signed": "1",
    "size_ratio": "1",
    "fiber_mode_radius_um": "um",
    "beam_radius_at_receiver_um": "um",
    "lateral_mismatch": "1",
    "angular_mismatch": "1",
    "axial_mismatch": "1",
    "curvature_mismatch": "1",
}


def derive_coupling_physics_features(
    project: ProjectSnapshot,
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, float]:

    del metrics
    receiver = project.receiver
    if receiver is None:
        raise PhysicsFeatureError("耦合物理特征需要receiver配置")

    wavelength_mm = float(project.source.wavelength_nm) * 1.0e-6
    wavelength_um = float(project.source.wavelength_nm) / 1000.0
    if wavelength_mm <= 0.0:
        raise PhysicsFeatureError("波长必须大于0")

    system = build_optical_system(project)
    matrices, n_input, n_output = _base_matrix(project, system)
    x_state = _axis_state(
        project,
        matrices["x"],
        n_input,
        n_output,
        wavelength_mm,
        axis="x",
    )
    y_state = _axis_state(
        project,
        matrices["y"],
        n_input,
        n_output,
        wavelength_mm,
        axis="y",
    )

    beam_radius_um = sqrt(x_state["beam_radius_um"] * y_state["beam_radius_um"])
    fiber_radius_um = 0.5 * sqrt(
        float(receiver.mode_field_diameter_x_um)
        * float(receiver.mode_field_diameter_y_um)
    )
    beam_curvature_um = _equivalent_curvature(
        x_state["curvature_um"], y_state["curvature_um"]
    )

    raw = {
        "beam_radius_um": beam_radius_um,
        "fiber_mode_radius_um": fiber_radius_um,
        "offset_x_um": 1000.0 * float(receiver.offset_x_mm) - x_state["centroid_um"],
        "offset_y_um": 1000.0 * float(receiver.offset_y_mm) - y_state["centroid_um"],
        "tilt_x_rad": float(receiver.tilt_x_deg) * pi / 180.0 - x_state["angle_rad"],
        "tilt_y_rad": float(receiver.tilt_y_deg) * pi / 180.0 - y_state["angle_rad"],
        "axial_offset_um": 1000.0 * float(receiver.axial_offset_z_mm),
        "wavelength_um": wavelength_um,
        "beam_curvature_radius_um": beam_curvature_um,
        "fiber_curvature_radius_um": float("inf"),
    }
    physics = compute_physics_features(raw)
    ratio = float(physics["size_ratio"])
    signed_log = log(ratio)
    output = {
        "size_log_mismatch": abs(signed_log),
        "size_log_signed": signed_log,
        "size_ratio": ratio,
        "fiber_mode_radius_um": fiber_radius_um,
        "beam_radius_at_receiver_um": beam_radius_um,
        "lateral_mismatch": float(physics["lateral_mismatch"]),
        "angular_mismatch": float(physics["angular_mismatch"]),
        "axial_mismatch": float(physics["axial_mismatch"]),
        "curvature_mismatch": float(physics["curvature_mismatch"]),
    }
    for key, value in output.items():
        if not isfinite(value):
            raise PhysicsFeatureError(f"派生耦合特征不是有限数: {key}={value!r}")
    return output


def coupling_loss_db(metrics: Mapping[str, Any], *, floor: float = 1.0e-15) -> float | None:

    efficiency = read_metric(metrics, "coupling_efficiency")
    if not isinstance(efficiency, (int, float)) or not isfinite(float(efficiency)):
        return None
    raw = float(efficiency)
    if raw < 0.0 or raw > 1.0:
        return None
    return float(-10.0 * log10(max(raw, floor)))


def coupling_efficiency_from_loss_db(metrics: Mapping[str, Any]) -> float | None:
    loss = read_metric(metrics, "coupling_loss_db")
    if not isinstance(loss, (int, float)) or not isfinite(float(loss)):
        return None
    return float(10.0 ** (-float(loss) / 10.0))


def paired_coupling_targets(targets) -> list[str]:
    """Keep coupling efficiency and dB loss together so XGBoost can train on datasets saved as η."""
    names = [canonical_metric_name(target) for target in (targets or [])]
    result = list(dict.fromkeys(name for name in names if name))
    has_efficiency = "coupling_efficiency" in result
    has_loss = "coupling_loss_db" in result
    if has_efficiency and not has_loss:
        result.append("coupling_loss_db")
    elif has_loss and not has_efficiency:
        result.append("coupling_efficiency")
    return result


def resolve_stored_target(target_values: Mapping[str, Any], target: str) -> float:
    """Read a sample target, deriving the coupling η ↔ dB pair when only one is stored."""
    values = dict(target_values or {})
    canonical = canonical_metric_name(target)
    direct = read_metric(values, canonical)
    if isinstance(direct, (int, float)) and isfinite(float(direct)):
        return float(direct)
    if canonical == "coupling_loss_db":
        derived = coupling_loss_db(values)
        if derived is not None:
            return derived
    if canonical == "coupling_efficiency":
        derived = coupling_efficiency_from_loss_db(values)
        if derived is not None:
            return derived
    available = ", ".join(sorted(str(key) for key in values)) or "无"
    raise ValueError(
        f"数据集样本缺少目标列 {canonical}，现有列：{available}。"
        "XGBoost 物理残差需要 coupling_loss_db；若样本只有 coupling_efficiency，"
        "请重新生成数据集，或使用已含耦合效率的样本以便自动换算。"
    )


def enrich_candidate_features(
    base_project: ProjectSnapshot,
    raw_features: Mapping[str, float],
) -> dict[str, float]:

    from machine_learning.datasets.generator import apply_parameter_changes
    from shared_contracts.parameters import ParameterChange

    changes = [
        ParameterChange(path=str(path), value=float(value))
        for path, value in raw_features.items()
        if path not in PHYSICS_RESIDUAL_FEATURE_PATHS
    ]
    candidate = apply_parameter_changes(base_project, changes) if changes else base_project
    output = {str(key): float(value) for key, value in raw_features.items()}
    output.update(derive_coupling_physics_features(candidate))
    return output


def _base_matrix(project: ProjectSnapshot, system) -> tuple[dict[str, np.ndarray], float, float]:
    if system.surfaces:
        n_input = float(
            system.material_index(
                system.surfaces[0].material_before, project.source.wavelength_nm
            )
        )
        n_output = float(
            system.material_index(
                system.surfaces[-1].material_after, project.source.wavelength_nm
            )
        )
        matrices = {
            axis: np.asarray(
                system_matrix_to_image(system, project.source.wavelength_nm, axis=axis),
                dtype=float,
            )
            for axis in ("x", "y")
        }
    else:
        n_input = n_output = 1.0
        matrix = translation_matrix(
            float(project.object_distance_mm) + float(project.image_distance_mm),
            1.0,
        )
        matrices = {"x": matrix.copy(), "y": matrix.copy()}
    receiver_shift = translation_matrix(float(project.receiver.axial_offset_z_mm), n_output)
    matrices = {axis: receiver_shift @ matrix for axis, matrix in matrices.items()}
    return matrices, n_input, n_output


def _axis_state(
    project: ProjectSnapshot,
    base_matrix: np.ndarray,
    n_input: float,
    n_output: float,
    wavelength_mm: float,
    *,
    axis: str,
) -> dict[str, float]:
    source = project.source
    waist_mm = float(getattr(source, f"waist_{axis}_mm"))
    m2 = float(getattr(source, f"beam_quality_m2_{axis}") or source.beam_quality_m2)
    na = max(float(getattr(source, f"object_na_{axis}")), 1.0e-12)
    effective_wavelength_mm = m2 * wavelength_mm
    if waist_mm <= 0.0:
        waist_mm = effective_wavelength_mm / (pi * na)

    waist_position_mm = float(getattr(source, f"waist_position_{axis}_mm"))
    distance_to_first_mm = float(project.object_distance_mm) - waist_position_mm
    total_matrix = base_matrix @ translation_matrix(distance_to_first_mm, n_input)
    q_output = propagate_q(
        total_matrix,
        q_from_waist(waist_mm, effective_wavelength_mm),
    )
    beam_radius_mm, curvature_mm = beam_size_and_radius(
        q_output, effective_wavelength_mm, n_output
    )

    center_mm = float(getattr(source, f"center_{axis}_mm"))
    input_angle_rad = float(getattr(source, f"axis_tilt_{axis}_rad"))
    ray_out = total_matrix @ np.asarray(
        [center_mm, n_input * input_angle_rad], dtype=float
    )
    return {
        "beam_radius_um": 1000.0 * float(beam_radius_mm),
        "curvature_um": (
            float("inf") if not isfinite(curvature_mm) else 1000.0 * float(curvature_mm)
        ),
        "centroid_um": 1000.0 * float(ray_out[0]),
        "angle_rad": float(ray_out[1]) / n_output,
    }


def _equivalent_curvature(x_um: float, y_um: float) -> float:
    inverse_x = 0.0 if not isfinite(x_um) else 1.0 / x_um
    inverse_y = 0.0 if not isfinite(y_um) else 1.0 / y_um
    inverse_mean = 0.5 * (inverse_x + inverse_y)
    return float("inf") if abs(inverse_mean) < 1.0e-18 else 1.0 / inverse_mean


__all__ = [
    "PHYSICS_RESIDUAL_FEATURE_PATHS",
    "PHYSICS_RESIDUAL_FEATURE_UNITS",
    "coupling_efficiency_from_loss_db",
    "coupling_loss_db",
    "derive_coupling_physics_features",
    "enrich_candidate_features",
    "paired_coupling_targets",
    "resolve_stored_target",
]
