# 计算反射光线方向。
# 计算光线在球面、圆锥面或非球面上的法向量，再根据反射定律生成反射后的新光线。
from __future__ import annotations

import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.formulas.reflection import reflect_direction
from optical_core.physics.geometric.formulas.surface_normal import surface_normal_from_point


def reflect_ray_at_surface(ray: Ray, surface: OpticalSurface, *, hit_point_mm: np.ndarray) -> Ray:
    normal = surface_normal_from_point(
        np.asarray(hit_point_mm, dtype=float),
        radius_mm=surface.radius_mm,
        conic=surface.conic,
        asphere_a2=surface.asphere_a2,
        asphere_coefficients=surface.asphere_coefficients,
        surface_type=surface.surface_type,
        cylinder_axis_deg=surface.cylinder_axis_deg,
    )
    direction = reflect_direction(np.asarray(ray.direction, dtype=float), normal)
    return Ray(
        position_mm=tuple(hit_point_mm),
        direction=tuple(direction),
        wavelength_nm=ray.wavelength_nm,
        field_amplitude=ray.field_amplitude,
        power_weight=ray.power_weight,
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=ray.optical_path_mm,
        valid=True,
        polarization_xyz=ray.polarization_xyz,
        phase_offset_rad=ray.phase_offset_rad,
    )
