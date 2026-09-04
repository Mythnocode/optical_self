from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import math
from typing import Any

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.operators.ray_aperture_clip import point_passes_surface_aperture
from optical_core.physics.geometric.operators.ray_surface_intersect import intersect_ray_with_surface
from optical_core.physics.surface_interaction.service import interact_ray_with_surface


@dataclass(slots=True)
class SceneRayPath:
    path_id: str
    parent_id: str | None
    signature: str
    power_fraction: float
    points_mm: list[tuple[float, float, float]] = field(default_factory=list)
    surface_indices: list[int] = field(default_factory=list)
    node_ids: list[str | None] = field(default_factory=list)
    directions: list[tuple[float, float, float]] = field(default_factory=list)
    termination_reason: str = ""


@dataclass(slots=True)
class SceneRayTraceResult:
    paths: list[SceneRayPath]
    interaction_count: int
    warnings: list[str] = field(default_factory=list)


def _normalise(values: tuple[float, float, float] | np.ndarray) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1.0e-15:
        raise ValueError("光线方向必须为有限非零向量。")
    return vector / norm


def _surface_pose(surface: Any, vertex_z_mm: float) -> tuple[np.ndarray, np.ndarray]:
    rx, ry, rz = np.radians([
        float(getattr(surface, "tilt_x_deg", 0.0)),
        float(getattr(surface, "tilt_y_deg", 0.0)),
        float(getattr(surface, "tilt_z_deg", 0.0)),
    ])
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    rotation_x = np.asarray([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]], dtype=float)
    rotation_y = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=float)
    rotation_z = np.asarray([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]], dtype=float)
    rotation = rotation_z @ rotation_y @ rotation_x
    origin = np.asarray([
        float(getattr(surface, "decenter_x_mm", 0.0)),
        float(getattr(surface, "decenter_y_mm", 0.0)),
        float(vertex_z_mm),
    ], dtype=float)
    return rotation, origin


def _transform_ray(ray: Ray, rotation: np.ndarray, origin: np.ndarray, *, to_local: bool) -> Ray:
    position = np.asarray(ray.position_mm, dtype=float)
    direction = np.asarray(ray.direction, dtype=float)
    polarization = np.asarray(ray.polarization_xyz, dtype=np.complex128)
    if to_local:
        matrix = rotation.T
        position = matrix @ (position - origin)
        direction = matrix @ direction
        polarization = matrix @ polarization
    else:
        position = origin + rotation @ position
        direction = rotation @ direction
        polarization = rotation @ polarization
    return Ray(
        position_mm=tuple(float(v) for v in position),
        direction=tuple(float(v) for v in _normalise(direction)),
        wavelength_nm=ray.wavelength_nm,
        field_amplitude=ray.field_amplitude,
        power_weight=ray.power_weight,
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=ray.optical_path_mm,
        valid=ray.valid,
        reason=ray.reason,
        polarization_xyz=tuple(complex(v) for v in polarization),
        phase_offset_rad=ray.phase_offset_rad,
    )


def _copy_ray(
    ray: Ray,
    *,
    position_mm: tuple[float, float, float] | None = None,
    direction: tuple[float, float, float] | np.ndarray | None = None,
    field_amplitude: float | None = None,
    power_weight: float | None = None,
    optical_path_mm: float | None = None,
) -> Ray:
    return Ray(
        position_mm=ray.position_mm if position_mm is None else position_mm,
        direction=ray.direction if direction is None else tuple(float(v) for v in _normalise(direction)),
        wavelength_nm=ray.wavelength_nm,
        field_amplitude=ray.field_amplitude if field_amplitude is None else float(field_amplitude),
        power_weight=ray.power_weight if power_weight is None else float(power_weight),
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=ray.optical_path_mm if optical_path_mm is None else float(optical_path_mm),
        valid=True,
        polarization_xyz=ray.polarization_xyz,
        phase_offset_rad=ray.phase_offset_rad,
    )


def _reverse_surface(surface: Any) -> Any:
    return replace(
        surface,
        material_before=surface.material_after,
        material_after=surface.material_before,
        coating_layers=tuple(reversed(surface.coating_layers)),
    )


def _scaled_branch(ray: Ray, fraction: float) -> Ray | None:
    value = min(1.0, max(0.0, float(fraction)))
    if value <= 0.0:
        return None
    return _copy_ray(
        ray,
        field_amplitude=float(ray.field_amplitude) * math.sqrt(value),
        power_weight=float(ray.power_weight) * value,
    )


def _nudge(ray: Ray, epsilon_mm: float) -> Ray:
    direction = _normalise(ray.direction)
    point = np.asarray(ray.position_mm, dtype=float) + float(epsilon_mm) * direction
    return _copy_ray(ray, position_mm=tuple(float(v) for v in point))


def _sphere_intersection(
    ray: Ray,
    center_mm: np.ndarray,
    radius_mm: float,
    *,
    epsilon_mm: float,
) -> tuple[np.ndarray, float] | None:
    """Nearest forward intersection of a unit ray with a sphere."""
    direction = _normalise(ray.direction)
    origin = np.asarray(ray.position_mm, dtype=float)
    offset = origin - np.asarray(center_mm, dtype=float)
    radius = max(1.0e-6, float(radius_mm))
    half_b = float(np.dot(direction, offset))
    c_term = float(np.dot(offset, offset) - radius * radius)
    discriminant = half_b * half_b - c_term
    if discriminant < 0.0:
        return None
    root = math.sqrt(discriminant)
    # Prefer the nearer forward root; fall back to the far side if needed.
    for distance in (-half_b - root, -half_b + root):
        if distance > float(epsilon_mm) and np.isfinite(distance):
            point = origin + direction * distance
            return point, float(distance)
    return None


def _candidate_hit(
    system: SequentialOpticalSystem,
    ray: Ray,
    surface_index: int,
    vertex_z_mm: float,
    *,
    epsilon_mm: float,
) -> dict[str, Any] | None:
    surface = system.surfaces[surface_index]
    rotation, origin = _surface_pose(surface, vertex_z_mm)
    metadata = dict(getattr(surface, "metadata", {}) or {})
    hit_shape = str(metadata.get("hit_shape", "") or "").strip().lower()

    if hit_shape == "sphere":
        radius = float(
            metadata.get(
                "hit_radius_mm",
                getattr(surface, "clear_aperture_mm", None) or 5.0,
            )
            or 5.0
        )
        sphere_hit = _sphere_intersection(ray, origin, radius, epsilon_mm=epsilon_mm)
        if sphere_hit is None:
            return None
        global_point, distance = sphere_hit
        local_point = rotation.T @ (global_point - origin)
        local_ray = _transform_ray(ray, rotation, origin, to_local=True)
        return {
            "surface_index": int(surface_index),
            "surface": surface,
            "rotation": rotation,
            "origin": origin,
            "local_ray": local_ray,
            "local_point": local_point,
            "global_point": global_point,
            "distance_mm": float(distance),
            "inside_aperture": True,
            "metadata": metadata,
        }

    local_ray = _transform_ray(ray, rotation, origin, to_local=True)
    try:
        hit = intersect_ray_with_surface(local_ray, surface, vertex_z_mm=0.0)
    except (ValueError, FloatingPointError, ArithmeticError):
        return None
    if not hit.valid or not np.isfinite(float(hit.distance_mm)) or float(hit.distance_mm) <= float(epsilon_mm):
        return None
    local_point = np.asarray(hit.point_mm, dtype=float)
    inside = bool(point_passes_surface_aperture(local_point, surface))
    if not inside and not bool(metadata.get("block_outside_aperture", False)):
        return None
    global_point = origin + rotation @ local_point
    return {
        "surface_index": int(surface_index),
        "surface": surface,
        "rotation": rotation,
        "origin": origin,
        "local_ray": local_ray,
        "local_point": local_point,
        "global_point": global_point,
        "distance_mm": float(hit.distance_mm),
        "inside_aperture": inside,
        "metadata": metadata,
    }


def _nearest_hit(
    system: SequentialOpticalSystem,
    ray: Ray,
    vertices: tuple[float, ...],
    *,
    epsilon_mm: float,
    last_surface_index: int | None,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for index, vertex_z in enumerate(vertices):
        candidate = _candidate_hit(system, ray, index, vertex_z, epsilon_mm=epsilon_mm)
        if candidate is None:
            continue
        if last_surface_index is not None and index == last_surface_index and candidate["distance_mm"] <= epsilon_mm * 20.0:
            continue
        if best is None or candidate["distance_mm"] < best["distance_mm"]:
            best = candidate
    return best


def _reflected_ray_from_surface(
    local_hit_ray: Ray,
    surface: Any,
    local_point: np.ndarray,
    *,
    n_before: float,
    n_after: float,
    temperature_c: float,
) -> Ray | None:
    mirror_surface = replace(surface, surface_type="mirror", material_after=surface.material_before)
    interaction = interact_ray_with_surface(
        local_hit_ray,
        mirror_surface,
        hit_point_mm=local_point,
        n_before=n_before,
        n_after=n_before,
        temperature_c=temperature_c,
    )
    return interaction.reflected_ray


def trace_scene_ray_tree(
    system: SequentialOpticalSystem,
    *,
    source_position_mm: tuple[float, float, float],
    source_direction: tuple[float, float, float],
    wavelength_nm: float | None = None,
    max_interactions: int = 24,
    max_branches: int = 32,
    min_power_fraction: float = 1.0e-5,
    escape_distance_mm: float = 160.0,
    epsilon_mm: float = 1.0e-5,
    temperature_c: float = 20.0,
) -> SceneRayTraceResult:
    if not system.surfaces:
        endpoint = np.asarray(source_position_mm, dtype=float) + float(escape_distance_mm) * _normalise(source_direction)
        path = SceneRayPath(
            path_id="P0",
            parent_id=None,
            signature="",
            power_fraction=1.0,
            points_mm=[tuple(float(v) for v in source_position_mm), tuple(float(v) for v in endpoint)],
            surface_indices=[-1, -2],
            node_ids=["__source__", None],
            directions=[tuple(float(v) for v in _normalise(source_direction))] * 2,
            termination_reason="escaped_scene",
        )
        return SceneRayTraceResult(paths=[path], interaction_count=0)

    wavelength = float(wavelength_nm or system.wavelength_nm)
    root = Ray(
        position_mm=tuple(float(v) for v in source_position_mm),
        direction=tuple(float(v) for v in _normalise(source_direction)),
        wavelength_nm=wavelength,
        field_amplitude=1.0,
        power_weight=1.0,
        quadrature_weight=1.0,
    )
    vertices = system.surface_vertex_z_positions()
    queue: deque[dict[str, Any]] = deque([
        {
            "path_id": "P0",
            "parent_id": None,
            "signature": "",
            "ray": root,
            "points": [tuple(float(v) for v in root.position_mm)],
            "surface_indices": [-1],
            "node_ids": ["__source__"],
            "directions": [tuple(float(v) for v in root.direction)],
            "depth": 0,
            "last_surface_index": None,
        }
    ])
    completed: list[SceneRayPath] = []
    warnings: list[str] = []
    interaction_total = 0
    next_path_index = 1

    while queue and len(completed) + len(queue) <= int(max_branches):
        state = queue.popleft()
        ray: Ray = state["ray"]
        if float(ray.power_weight) < float(min_power_fraction):
            completed.append(SceneRayPath(
                path_id=state["path_id"],
                parent_id=state["parent_id"],
                signature=state["signature"],
                power_fraction=float(ray.power_weight),
                points_mm=state["points"],
                surface_indices=state["surface_indices"],
                node_ids=state["node_ids"],
                directions=state["directions"],
                termination_reason="power_below_threshold",
            ))
            continue
        if int(state["depth"]) >= int(max_interactions):
            completed.append(SceneRayPath(
                path_id=state["path_id"],
                parent_id=state["parent_id"],
                signature=state["signature"],
                power_fraction=float(ray.power_weight),
                points_mm=state["points"],
                surface_indices=state["surface_indices"],
                node_ids=state["node_ids"],
                directions=state["directions"],
                termination_reason="max_interactions",
            ))
            continue

        hit = _nearest_hit(
            system,
            ray,
            vertices,
            epsilon_mm=float(epsilon_mm),
            last_surface_index=state["last_surface_index"],
        )
        if hit is None:
            direction = _normalise(ray.direction)
            endpoint = np.asarray(ray.position_mm, dtype=float) + float(escape_distance_mm) * direction
            points = [*state["points"], tuple(float(v) for v in endpoint)]
            surface_indices = [*state["surface_indices"], -2]
            node_ids = [*state["node_ids"], None]
            directions = [*state["directions"], tuple(float(v) for v in direction)]
            completed.append(SceneRayPath(
                path_id=state["path_id"],
                parent_id=state["parent_id"],
                signature=state["signature"],
                power_fraction=float(ray.power_weight),
                points_mm=points,
                surface_indices=surface_indices,
                node_ids=node_ids,
                directions=directions,
                termination_reason="escaped_scene",
            ))
            continue

        interaction_total += 1
        surface = hit["surface"]
        metadata = hit["metadata"]
        node_id = str(metadata.get("teaching_node_id", "")) or None
        point = np.asarray(hit["global_point"], dtype=float)
        local_point = np.asarray(hit["local_point"], dtype=float)
        local_ray: Ray = hit["local_ray"]
        current_direction = tuple(float(v) for v in _normalise(ray.direction))
        points = [*state["points"], tuple(float(v) for v in point)]
        surface_indices = [*state["surface_indices"], int(hit["surface_index"])]
        node_ids = [*state["node_ids"], node_id]
        directions = list(state["directions"])

        if not bool(hit["inside_aperture"]):
            completed.append(SceneRayPath(
                path_id=state["path_id"],
                parent_id=state["parent_id"],
                signature=state["signature"],
                power_fraction=float(ray.power_weight),
                points_mm=points,
                surface_indices=surface_indices,
                node_ids=node_ids,
                directions=[*directions, current_direction],
                termination_reason="blocked_by_aperture",
            ))
            continue

        if bool(metadata.get("terminal", False)):
            completed.append(SceneRayPath(
                path_id=state["path_id"],
                parent_id=state["parent_id"],
                signature=state["signature"],
                power_fraction=float(ray.power_weight),
                points_mm=points,
                surface_indices=surface_indices,
                node_ids=node_ids,
                directions=[*directions, current_direction],
                termination_reason="terminal_hit",
            ))
            continue

        local_dz = float(local_ray.direction[2])
        oriented_surface = surface if local_dz >= 0.0 else _reverse_surface(surface)
        n_before = system.material_index(oriented_surface.material_before, wavelength)
        n_after = system.material_index(oriented_surface.material_after, wavelength)
        hit_opl = float(ray.optical_path_mm + abs(float(hit["distance_mm"])) * n_before)
        local_hit_ray = _copy_ray(
            local_ray,
            position_mm=tuple(float(v) for v in local_point),
            optical_path_mm=hit_opl,
        )
        role = str(metadata.get("teaching_role", "refractive"))
        branches: list[tuple[str, Ray]] = []

        if role == "transparent":
            global_ray = _copy_ray(
                ray,
                position_mm=tuple(float(v) for v in point),
                optical_path_mm=hit_opl,
            )
            branches.append(("T", global_ray))
        elif role == "splitter":
            split_ratio = min(0.95, max(0.0, float(metadata.get("split_ratio", 0.05))))
            transmitted_global = _copy_ray(
                ray,
                position_mm=tuple(float(v) for v in point),
                optical_path_mm=hit_opl,
            )
            transmitted_global = _scaled_branch(transmitted_global, 1.0 - split_ratio)
            reflected_local = _reflected_ray_from_surface(
                local_hit_ray,
                oriented_surface,
                local_point,
                n_before=n_before,
                n_after=n_after,
                temperature_c=float(temperature_c),
            )
            reflected_global = None if reflected_local is None else _transform_ray(
                reflected_local, hit["rotation"], hit["origin"], to_local=False
            )
            reflected_global = None if reflected_global is None else _scaled_branch(reflected_global, split_ratio)
            if transmitted_global is not None:
                branches.append(("T", transmitted_global))
            if reflected_global is not None:
                branches.append(("R", reflected_global))
        else:
            interaction = interact_ray_with_surface(
                local_hit_ray,
                oriented_surface,
                hit_point_mm=local_point,
                n_before=n_before,
                n_after=n_after,
                temperature_c=float(temperature_c),
            )
            surface_type = str(oriented_surface.surface_type).strip().lower()
            if surface_type in {"mirror", "reflective", "reflection"}:
                if interaction.reflected_ray is not None:
                    branches.append(("R", _transform_ray(
                        interaction.reflected_ray, hit["rotation"], hit["origin"], to_local=False
                    )))
            elif interaction.transmitted_ray is not None:
                branches.append(("T", _transform_ray(
                    interaction.transmitted_ray, hit["rotation"], hit["origin"], to_local=False
                )))
            elif interaction.reflected_ray is not None:
                branches.append(("R", _transform_ray(
                    interaction.reflected_ray, hit["rotation"], hit["origin"], to_local=False
                )))

        if not branches:
            completed.append(SceneRayPath(
                path_id=state["path_id"],
                parent_id=state["parent_id"],
                signature=state["signature"],
                power_fraction=float(ray.power_weight),
                points_mm=points,
                surface_indices=surface_indices,
                node_ids=node_ids,
                directions=[*directions, current_direction],
                termination_reason="surface_interaction_failed",
            ))
            continue

        for branch_index, (branch_code, child_ray) in enumerate(branches):
            child_ray = _nudge(child_ray, float(epsilon_mm) * 8.0)
            child_id = state["path_id"] if branch_index == 0 else f"P{next_path_index}"
            parent_id = state["parent_id"] if branch_index == 0 else state["path_id"]
            if branch_index > 0:
                next_path_index += 1
            queue.append({
                "path_id": child_id,
                "parent_id": parent_id,
                "signature": state["signature"] + branch_code,
                "ray": child_ray,
                "points": list(points),
                "surface_indices": list(surface_indices),
                "node_ids": list(node_ids),
                "directions": [*directions, tuple(float(v) for v in _normalise(child_ray.direction))],
                "depth": int(state["depth"]) + 1,
                "last_surface_index": int(hit["surface_index"]),
            })

    while queue:
        state = queue.popleft()
        ray = state["ray"]
        completed.append(SceneRayPath(
            path_id=state["path_id"],
            parent_id=state["parent_id"],
            signature=state["signature"],
            power_fraction=float(ray.power_weight),
            points_mm=state["points"],
            surface_indices=state["surface_indices"],
            node_ids=state["node_ids"],
            directions=state["directions"],
            termination_reason="branch_limit",
        ))
    if len(completed) >= int(max_branches):
        warnings.append("场景光线分支达到上限，低优先级分支已截断。")
    completed.sort(key=lambda item: (-float(item.power_fraction), item.path_id))
    return SceneRayTraceResult(paths=completed, interaction_count=interaction_total, warnings=warnings)


__all__ = ["SceneRayPath", "SceneRayTraceResult", "trace_scene_ray_tree"]
