
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.operators.ray_aperture_clip import point_passes_surface_aperture
from optical_core.physics.geometric.operators.ray_reflect import reflect_ray_at_surface
from optical_core.physics.geometric.operators.ray_refract import refract_ray_at_surface
from optical_core.physics.geometric.operators.ray_surface_intersect import intersect_ray_with_surface
from optical_core.physics.geometric.solvers.trace_options import TraceOptions
from optical_core.physics.surface_interaction.service import interact_ray_with_surface


@dataclass(slots=True)
class DetailedRayTrace:
    final_ray: Ray
    path_points_mm: list[tuple[float, float, float]] = field(default_factory=list)
    path_surface_indices: list[int] = field(default_factory=list)
    surface_points_mm: list[tuple[float, float, float]] = field(default_factory=list)
    surface_directions: list[tuple[float, float, float]] = field(default_factory=list)
    segment_lengths_mm: list[float] = field(default_factory=list)
    segment_refractive_indices: list[float] = field(default_factory=list)
    segment_opl_mm: list[float] = field(default_factory=list)
    cumulative_opl_mm: list[float] = field(default_factory=list)
    surface_interactions: list[dict[str, Any]] = field(default_factory=list)
    status_code: str = "REACHED_IMAGE"
    termination_reason: str = ""


def _normalise_direction(direction) -> tuple[float, float, float]:
    values = np.asarray(direction, dtype=float)
    norm = np.linalg.norm(values)
    if not np.isfinite(norm) or norm <= 0.0:
        raise ValueError("ray direction is invalid")
    return tuple(float(v) for v in values / norm)


def _copy_ray_at(
    current: Ray,
    *,
    position_mm: tuple[float, float, float],
    optical_path_mm: float,
    valid: bool = True,
    reason: str | None = None,
) -> Ray:
    return Ray(
        position_mm=position_mm,
        direction=current.direction,
        wavelength_nm=current.wavelength_nm,
        field_amplitude=current.field_amplitude,
        power_weight=current.power_weight,
        quadrature_weight=current.quadrature_weight,
        optical_path_mm=optical_path_mm,
        valid=valid,
        reason=reason,
        polarization_xyz=current.polarization_xyz,
        phase_offset_rad=current.phase_offset_rad,
    )


def _invalid_ray(current: Ray, reason: str) -> Ray:
    return _copy_ray_at(
        current,
        position_mm=current.position_mm,
        optical_path_mm=current.optical_path_mm,
        valid=False,
        reason=reason,
    )




def _surface_pose(surface, vertex_z_mm: float) -> tuple[np.ndarray, np.ndarray]:

    rx, ry, rz = np.radians(
        [
            float(getattr(surface, "tilt_x_deg", 0.0)),
            float(getattr(surface, "tilt_y_deg", 0.0)),
            float(getattr(surface, "tilt_z_deg", 0.0)),
        ]
    )
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    rotation_x = np.asarray([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    rotation_y = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rotation_z = np.asarray([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    rotation = rotation_z @ rotation_y @ rotation_x
    origin = np.asarray(
        [
            float(getattr(surface, "decenter_x_mm", 0.0)),
            float(getattr(surface, "decenter_y_mm", 0.0)),
            float(vertex_z_mm),
        ],
        dtype=float,
    )
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
        direction=tuple(float(v) for v in direction),
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


def _append_segment(
    detail: DetailedRayTrace,
    *,
    point_mm: np.ndarray,
    surface_index: int,
    direction: tuple[float, float, float],
    geometric_length_mm: float,
    refractive_index: float,
    cumulative_opl_mm: float,
) -> None:
    segment_length = abs(float(geometric_length_mm))
    n = float(refractive_index)
    detail.path_points_mm.append(tuple(float(v) for v in point_mm))
    detail.path_surface_indices.append(int(surface_index))
    detail.surface_points_mm.append(tuple(float(v) for v in point_mm))
    detail.surface_directions.append(tuple(float(v) for v in direction))
    detail.segment_lengths_mm.append(segment_length)
    detail.segment_refractive_indices.append(n)
    detail.segment_opl_mm.append(segment_length * n)
    detail.cumulative_opl_mm.append(float(cumulative_opl_mm))


def trace_single_ray_detailed(
    system: SequentialOpticalSystem,
    ray: Ray,
    options: TraceOptions | None = None,
) -> DetailedRayTrace:


    options = options or TraceOptions()
    wavelength_nm = float(options.wavelength_nm or ray.wavelength_nm or system.wavelength_nm)
    current = Ray(
        position_mm=ray.position_mm,
        direction=_normalise_direction(ray.direction),
        wavelength_nm=wavelength_nm,
        field_amplitude=ray.field_amplitude,
        power_weight=ray.power_weight,
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=ray.optical_path_mm,
        valid=ray.valid,
        reason=ray.reason,
        polarization_xyz=ray.polarization_xyz,
        phase_offset_rad=ray.phase_offset_rad,
    )
    detail = DetailedRayTrace(
        final_ray=current,
        path_points_mm=[tuple(float(v) for v in current.position_mm)],
        path_surface_indices=[-1],
        status_code="IN_PROGRESS",
    )

    if not current.valid:
        detail.status_code = "INVALID_INPUT"
        detail.termination_reason = current.reason or "invalid input ray"
        return detail

    vertices = system.surface_vertex_z_positions()
    for surface_index, (surface, vertex_z) in enumerate(zip(system.surfaces, vertices)):
        n_before = system.material_index(surface.material_before, wavelength_nm)
        rotation, origin = _surface_pose(surface, vertex_z)
        local_current = _transform_ray(current, rotation, origin, to_local=True)
        hit = intersect_ray_with_surface(
            local_current,
            surface,
            vertex_z_mm=0.0,
            max_iterations=options.max_intersection_iterations,
        )
        if not hit.valid:
            reason = hit.reason or "surface intersection failed"
            detail.final_ray = _invalid_ray(current, reason)
            detail.status_code = "INTERSECTION_FAILED"
            detail.termination_reason = reason
            return detail

        local_hit_point = np.asarray(hit.point_mm, dtype=float)
        global_hit_point = origin + rotation @ local_hit_point
        cumulative = float(current.optical_path_mm + abs(hit.distance_mm) * n_before)
        current = _copy_ray_at(
            current,
            position_mm=tuple(float(v) for v in global_hit_point),
            optical_path_mm=cumulative,
        )
        local_current = _copy_ray_at(
            local_current,
            position_mm=tuple(float(v) for v in local_hit_point),
            optical_path_mm=cumulative,
        )
        _append_segment(
            detail,
            point_mm=global_hit_point,
            surface_index=surface_index,
            direction=current.direction,
            geometric_length_mm=hit.distance_mm,
            refractive_index=n_before,
            cumulative_opl_mm=cumulative,
        )

        if options.evaluate_apertures and not point_passes_surface_aperture(
            local_hit_point, surface
        ):
            reason = "clipped by clear aperture"
            detail.final_ray = _invalid_ray(current, reason)
            detail.status_code = "APERTURE_CLIPPED"
            detail.termination_reason = reason
            return detail

        surface_type = str(surface.surface_type).lower()
        n_after = system.material_index(surface.material_after, wavelength_nm)
        local_output: Ray | None
        if options.apply_surface_physics:
            interaction = interact_ray_with_surface(
                local_current,
                surface,
                hit_point_mm=local_hit_point,
                n_before=n_before,
                n_after=n_after,
                temperature_c=options.environment_temperature_c,
                include_group_delay=options.include_group_delay,
            )
            diagnostics = dict(interaction.diagnostics)
            diagnostics["surface_pose"] = {
                "decenter_x_mm": float(getattr(surface, "decenter_x_mm", 0.0)),
                "decenter_y_mm": float(getattr(surface, "decenter_y_mm", 0.0)),
                "tilt_x_deg": float(getattr(surface, "tilt_x_deg", 0.0)),
                "tilt_y_deg": float(getattr(surface, "tilt_y_deg", 0.0)),
                "tilt_z_deg": float(getattr(surface, "tilt_z_deg", 0.0)),
            }
            detail.surface_interactions.append(diagnostics)
            if surface_type in {"mirror", "reflective", "reflection"}:
                local_output = interaction.reflected_ray
                if local_output is None:
                    reason = "mirror reflection branch has zero power"
                    detail.final_ray = _invalid_ray(current, reason)
                    detail.status_code = "REFLECTION_FAILED"
                    detail.termination_reason = reason
                    return detail
            else:
                local_output = interaction.transmitted_ray
                if local_output is None:
                    reason = "total internal reflection or zero transmitted power"
                    detail.final_ray = _invalid_ray(current, reason)
                    detail.status_code = "REFRACTION_FAILED"
                    detail.termination_reason = reason
                    return detail
        elif surface_type in {"mirror", "reflective", "reflection"}:
            local_output = reflect_ray_at_surface(
                local_current, surface, hit_point_mm=local_hit_point
            )
        else:
            refracted = refract_ray_at_surface(
                local_current,
                surface,
                hit_point_mm=local_hit_point,
                n1=n_before,
                n2=n_after,
            )
            local_output = refracted.ray
            if not refracted.valid:
                current = _transform_ray(local_output, rotation, origin, to_local=False)
                detail.final_ray = current
                detail.status_code = "REFRACTION_FAILED"
                detail.termination_reason = current.reason or "refraction failed"
                return detail

        current = _transform_ray(local_output, rotation, origin, to_local=False)
        detail.surface_directions[-1] = tuple(float(v) for v in current.direction)

    if options.propagate_to_image and system.surfaces:
        direction = np.asarray(current.direction, dtype=float)
        if abs(direction[2]) < 1.0e-14:
            reason = "cannot propagate to image plane"
            detail.final_ray = _invalid_ray(current, reason)
            detail.status_code = "IMAGE_PROPAGATION_FAILED"
            detail.termination_reason = reason
            return detail
        image_z = float(vertices[-1] + system.image_distance_mm)
        distance = (image_z - float(current.position_mm[2])) / direction[2]
        if not np.isfinite(distance):
            reason = "invalid image propagation distance"
            detail.final_ray = _invalid_ray(current, reason)
            detail.status_code = "IMAGE_PROPAGATION_FAILED"
            detail.termination_reason = reason
            return detail
        point = np.asarray(current.position_mm, dtype=float) + distance * direction
        n_image = system.material_index(system.surfaces[-1].material_after, wavelength_nm)
        cumulative = float(current.optical_path_mm + abs(distance) * n_image)
        current = _copy_ray_at(
            current,
            position_mm=tuple(float(v) for v in point),
            optical_path_mm=cumulative,
        )
        _append_segment(
            detail,
            point_mm=point,
            surface_index=len(system.surfaces),
            direction=current.direction,
            geometric_length_mm=distance,
            refractive_index=n_image,
            cumulative_opl_mm=cumulative,
        )
        detail.status_code = "REACHED_IMAGE"
    else:
        detail.status_code = "REACHED_LAST_SURFACE"

    detail.final_ray = current
    detail.termination_reason = current.reason or ""
    return detail


def trace_single_ray(
    system: SequentialOpticalSystem,
    ray: Ray,
    options: TraceOptions | None = None,
) -> Ray:


    return trace_single_ray_detailed(system, ray, options).final_ray


__all__ = ["DetailedRayTrace", "trace_single_ray", "trace_single_ray_detailed"]
