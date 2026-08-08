
from __future__ import annotations

from collections import deque
from dataclasses import replace
import math

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.operators.ray_aperture_clip import point_passes_surface_aperture
from optical_core.physics.geometric.operators.ray_surface_intersect import intersect_ray_with_surface
from optical_core.physics.nonsequential.models import RayNode, RayTreeOptions, RayTreeResult
from optical_core.physics.surface_interaction.service import interact_ray_with_surface


def _copy_at_hit(ray: Ray, point: np.ndarray, optical_path_mm: float) -> Ray:
    return Ray(
        position_mm=tuple(float(v) for v in point),
        direction=ray.direction,
        wavelength_nm=ray.wavelength_nm,
        field_amplitude=ray.field_amplitude,
        power_weight=ray.power_weight,
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=optical_path_mm,
        valid=True,
        polarization_xyz=ray.polarization_xyz,
        phase_offset_rad=ray.phase_offset_rad,
    )


def _reverse_surface(surface):
    return replace(
        surface,
        material_before=surface.material_after,
        material_after=surface.material_before,
        coating_layers=tuple(reversed(surface.coating_layers)),
    )


def _roulette(ray: Ray, root_power: float, options: RayTreeOptions, rng) -> Ray | None:
    fraction = float(ray.power_weight) / max(float(root_power), 1.0e-30)
    if fraction >= options.min_power_fraction:
        return ray
    if not options.russian_roulette or fraction <= 0.0:
        return None
    threshold = max(float(options.roulette_threshold_fraction), options.min_power_fraction)
    survival_probability = min(max(fraction / threshold, 0.0), 1.0)
    if rng.random() > survival_probability:
        return None
    return Ray(
        position_mm=ray.position_mm,
        direction=ray.direction,
        wavelength_nm=ray.wavelength_nm,
        field_amplitude=ray.field_amplitude / math.sqrt(max(survival_probability, 1.0e-30)),
        power_weight=float(ray.power_weight) / max(survival_probability, 1.0e-30),
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=ray.optical_path_mm,
        valid=ray.valid,
        reason=ray.reason,
        polarization_xyz=ray.polarization_xyz,
        phase_offset_rad=ray.phase_offset_rad,
    )


def trace_ray_tree(
    system: SequentialOpticalSystem,
    ray: Ray,
    options: RayTreeOptions | None = None,
) -> RayTreeResult:
    options = options or RayTreeOptions()
    if not system.surfaces:
        raise ValueError("non-sequential ray tree requires at least one surface")
    root_power = float(ray.power_weight)
    if root_power <= 0.0:
        raise ValueError("input ray power must be positive")
    vertices = system.surface_vertex_z_positions()
    detector_z = float(
        options.detector_z_mm
        if options.detector_z_mm is not None
        else vertices[-1] + system.image_distance_mm
    )
    rng = np.random.default_rng(int(options.random_seed))
    root = RayNode(
        node_id="0",
        parent_id=None,
        ray=ray,
        next_surface_index=0,
        propagation_sign=1,
    )
    queue = deque([root])
    nodes: list[RayNode] = []
    detector_nodes: list[RayNode] = []
    warnings: list[str] = []
    next_id = 1

    def spawn(parent: RayNode, child_ray: Ray, *, branch: str, next_index: int, sign: int, reflected: bool) -> None:
        nonlocal next_id
        survivor = _roulette(child_ray, root_power, options, rng)
        if survivor is None:
            return
        queue.append(
            RayNode(
                node_id=str(next_id),
                parent_id=parent.node_id,
                ray=survivor,
                next_surface_index=int(next_index),
                propagation_sign=int(sign),
                interaction_count=parent.interaction_count + 1,
                reflection_count=parent.reflection_count + int(reflected),
                surface_sequence=parent.surface_sequence,
                path_signature=parent.path_signature + branch,
            )
        )
        next_id += 1

    while queue and len(nodes) < int(options.max_nodes):
        node = queue.popleft()
        nodes.append(node)
        if node.interaction_count >= int(options.max_interactions):
            node.termination_reason = "max_interactions"
            continue
        if node.reflection_count > int(options.max_reflections):
            node.termination_reason = "max_reflections"
            continue

        index = int(node.next_surface_index)
        if index >= len(system.surfaces):
            if node.propagation_sign > 0:
                direction = np.asarray(node.ray.direction, dtype=float)
                if abs(direction[2]) <= 1.0e-14:
                    node.termination_reason = "parallel_to_detector"
                    continue
                distance = (detector_z - float(node.ray.position_mm[2])) / float(direction[2])
                if distance < -1.0e-12:
                    node.termination_reason = "detector_behind_ray"
                    continue
                point = np.asarray(node.ray.position_mm, dtype=float) + distance * direction
                last_medium = system.surfaces[-1].material_after
                n_medium = system.material_index(last_medium, node.ray.wavelength_nm)
                node.ray = _copy_at_hit(
                    node.ray,
                    point,
                    float(node.ray.optical_path_mm + abs(distance) * n_medium),
                )
                node.detector_position_mm = tuple(float(v) for v in point)
                node.detector_direction = node.ray.direction
                node.termination_reason = "detector"
                detector_nodes.append(node)
            else:
                node.termination_reason = "escaped_rearward"
            continue
        if index < 0:
            node.termination_reason = "escaped_frontward"
            continue

        surface_original = system.surfaces[index]
        surface = surface_original if node.propagation_sign > 0 else _reverse_surface(surface_original)
        vertex_z = vertices[index]
        hit = intersect_ray_with_surface(node.ray, surface_original, vertex_z_mm=vertex_z)
        if not hit.valid or hit.distance_mm < -1.0e-10:
            node.termination_reason = "intersection_failed"
            continue
        if not point_passes_surface_aperture(np.asarray(hit.point_mm), surface_original):
            node.termination_reason = "aperture_clipped"
            continue
        incident_material = surface.material_before
        exit_material = surface.material_after
        n_before = system.material_index(incident_material, node.ray.wavelength_nm)
        n_after = system.material_index(exit_material, node.ray.wavelength_nm)
        hit_ray = _copy_at_hit(
            node.ray,
            np.asarray(hit.point_mm, dtype=float),
            float(node.ray.optical_path_mm + abs(hit.distance_mm) * n_before),
        )
        interaction = interact_ray_with_surface(
            hit_ray,
            surface,
            hit_point_mm=np.asarray(hit.point_mm),
            n_before=n_before,
            n_after=n_after,
            temperature_c=options.environment_temperature_c,
        )
        node.surface_sequence = (*node.surface_sequence, int(index))
        node.diagnostics.update(interaction.diagnostics)

        if interaction.transmitted_ray is not None:
            spawn(
                node,
                interaction.transmitted_ray,
                branch="T",
                next_index=index + node.propagation_sign,
                sign=node.propagation_sign,
                reflected=False,
            )
        if interaction.reflected_ray is not None:
            reflected_sign = -node.propagation_sign
            spawn(
                node,
                interaction.reflected_ray,
                branch="R",
                next_index=index + reflected_sign,
                sign=reflected_sign,
                reflected=True,
            )
        if options.include_diffraction_orders:
            for diffracted, order in zip(
                interaction.diffraction_rays, interaction.diffraction_orders, strict=True
            ):
                sign = 1 if float(diffracted.direction[2]) >= 0.0 else -1
                spawn(
                    node,
                    diffracted,
                    branch=f"D{order}",
                    next_index=index + sign,
                    sign=sign,
                    reflected=False,
                )

    if queue:
        warnings.append("Ray tree reached max_nodes; remaining branches were truncated.")
    metrics, arrays = summarize_ray_tree(root_power, detector_nodes, nodes)
    return RayTreeResult(
        root_power=root_power,
        nodes=nodes,
        detector_nodes=detector_nodes,
        metrics=metrics,
        arrays=arrays,
        warnings=warnings,
        metadata={
            "solver": "native_ray_tree",
            "geometry": "ordered_surface_stack_with_bidirectional_reflections",
            "reference_data_used_as_input": False,
            "zemax_data_used_as_input": False,
        },
    )


def summarize_ray_tree(root_power: float, detector_nodes: list[RayNode], nodes: list[RayNode]):
    detector_power = float(sum(node.power for node in detector_nodes))
    primary = [node for node in detector_nodes if "R" not in node.path_signature and "D" not in node.path_signature]
    primary_power = float(sum(node.power for node in primary))
    ghost_power = max(detector_power - primary_power, 0.0)
    strongest_ghost = max(
        (node for node in detector_nodes if node not in primary),
        key=lambda node: node.power,
        default=None,
    )
    ranked = sorted(detector_nodes, key=lambda item: item.power, reverse=True)
    parent_ids = {node.parent_id for node in nodes if node.parent_id is not None}
    leaves = [node for node in nodes if node.node_id not in parent_ids]
    leaf_power = float(sum(node.power for node in leaves))
    return (
        {
            "ray_tree_node_count": len(nodes),
            "ray_tree_detector_path_count": len(detector_nodes),
            "ray_tree_detector_power": detector_power,
            "ray_tree_primary_power": primary_power,
            "ray_tree_total_ghost_power": ghost_power,
            "ray_tree_detector_throughput": detector_power / max(root_power, 1.0e-30),
            "ray_tree_ghost_to_primary_ratio": ghost_power / max(primary_power, 1.0e-30),
            "ray_tree_strongest_ghost_power": 0.0 if strongest_ghost is None else strongest_ghost.power,
            "ray_tree_strongest_ghost_relative_to_primary": (
                0.0 if strongest_ghost is None else strongest_ghost.power / max(primary_power, 1.0e-30)
            ),
            "ray_tree_leaf_power": leaf_power,
            "ray_tree_unaccounted_power": max(float(root_power) - leaf_power, 0.0),
            
            
            "ray_tree_power_remaining_in_nodes": leaf_power,
        },
        {
            "ray_tree_path_id": [node.node_id for node in ranked],
            "ray_tree_parent_id": [node.parent_id for node in ranked],
            "ray_tree_path_signature": [node.path_signature for node in ranked],
            "ray_tree_surface_sequence": [list(node.surface_sequence) for node in ranked],
            "ray_tree_path_power": [node.power for node in ranked],
            "ray_tree_optical_path_mm": [node.ray.optical_path_mm for node in ranked],
            "ray_tree_detector_x_mm": [node.detector_position_mm[0] for node in ranked],
            "ray_tree_detector_y_mm": [node.detector_position_mm[1] for node in ranked],
        },
    )


__all__ = ["trace_ray_tree", "summarize_ray_tree"]
