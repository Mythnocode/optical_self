# 计算折射光线方向。

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.formulas.snell import refract_direction
from optical_core.physics.geometric.formulas.surface_normal import surface_normal_from_point


@dataclass(frozen=True, slots=True)
class RefractResult:
    ray: Ray
    valid: bool
    reason: str | None = None


def refract_ray_at_surface(ray: Ray, surface: OpticalSurface, *, hit_point_mm: np.ndarray, n1: float, n2: float) -> RefractResult:
    normal = surface_normal_from_point(
        np.asarray(hit_point_mm, dtype=float),
        radius_mm=surface.radius_mm,
        conic=surface.conic,
        asphere_a2=surface.asphere_a2,
        asphere_coefficients=surface.asphere_coefficients,
        surface_type=surface.surface_type,
        metadata=surface.metadata,
    )
    new_direction, ok = refract_direction(np.asarray(ray.direction, dtype=float), normal, n1, n2)
    if not ok:
        return RefractResult(
            Ray(
                position_mm=tuple(hit_point_mm),
                direction=tuple(ray.direction),
                wavelength_nm=ray.wavelength_nm,
                field_amplitude=ray.field_amplitude,
                power_weight=ray.power_weight,
                quadrature_weight=ray.quadrature_weight,
                optical_path_mm=ray.optical_path_mm,
                valid=False,
                polarization_xyz=ray.polarization_xyz,
                phase_offset_rad=ray.phase_offset_rad,
                reason="全反射或折射方向无效",
            ),
            False,
            "全反射或折射方向无效",
        )
    return RefractResult(
        Ray(
            position_mm=tuple(float(v) for v in hit_point_mm),
            direction=tuple(float(v) for v in new_direction),
            wavelength_nm=ray.wavelength_nm,
            field_amplitude=ray.field_amplitude,
            power_weight=ray.power_weight,
            quadrature_weight=ray.quadrature_weight,
            optical_path_mm=ray.optical_path_mm,
            valid=True,
            polarization_xyz=ray.polarization_xyz,
            phase_offset_rad=ray.phase_offset_rad,
        ),
        True,
    )
