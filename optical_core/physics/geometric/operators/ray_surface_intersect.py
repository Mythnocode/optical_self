# 求光线与表面交点。采用顶点平面初值和牛顿迭代，并判断未收敛、反向交点等异常
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.formulas.surface_sag import sag_conic_asphere, sag_derivative_conic_asphere
from optical_core.physics.geometric.formulas.surface_normal import cylindrical_power_axis


@dataclass(frozen=True, slots=True)
class SurfaceIntersection:
    point_mm: np.ndarray
    distance_mm: float
    valid: bool
    reason: str | None = None


def intersect_ray_with_surface(
    ray: Ray,
    surface: OpticalSurface,
    *,
    vertex_z_mm: float,
    max_iterations: int = 12,
    tolerance_mm: float = 1.0e-10,
) -> SurfaceIntersection:
    p0 = np.asarray(ray.position_mm, dtype=float)
    d = np.asarray(ray.direction, dtype=float)
    norm = np.linalg.norm(d)
    if not ray.valid:
        return SurfaceIntersection(p0, 0.0, False, ray.reason or "输入光线无效")
    if not np.isfinite(norm) or norm <= 0.0:
        return SurfaceIntersection(p0, 0.0, False, "光线方向无效")
    d = d / norm
    if abs(d[2]) < 1.0e-14:
        return SurfaceIntersection(p0, 0.0, False, "光线近似平行于局部顶点平面")
    t = (float(vertex_z_mm) - p0[2]) / d[2]
    if not np.isfinite(t):
        return SurfaceIntersection(p0, 0.0, False, "初值求交失败")
    for _ in range(max_iterations):
        point = p0 + t * d
        if surface.is_cylindrical:
            power_axis = cylindrical_power_axis(surface.cylinder_axis_deg)
            signed_profile = float(np.dot(power_axis, point[:2]))
            radial = abs(signed_profile)
            radial_rate = float(np.sign(signed_profile) * np.dot(power_axis, d[:2]))
        else:
            radial = float(np.hypot(point[0], point[1]))
            radial_rate = (
                0.0
                if radial <= 1.0e-15
                else float((point[0] * d[0] + point[1] * d[1]) / radial)
            )
        sag = float(sag_conic_asphere(
            radial,
            radius_mm=surface.radius_mm,
            conic=surface.conic,
            asphere_a2=surface.asphere_a2,
            asphere_coefficients=surface.asphere_coefficients,
        ))
        residual = point[2] - (float(vertex_z_mm) + sag)
        if abs(residual) <= tolerance_mm:
            if t < -tolerance_mm:
                return SurfaceIntersection(point, t, False, "交点位于光线反向延长线上")
            return SurfaceIntersection(point, t, True)
        derivative = float(sag_derivative_conic_asphere(
            radial,
            radius_mm=surface.radius_mm,
            conic=surface.conic,
            asphere_a2=surface.asphere_a2,
            asphere_coefficients=surface.asphere_coefficients,
        ))
        jacobian = d[2] - derivative * radial_rate
        if abs(jacobian) <= 1.0e-14:
            break
        t -= residual / jacobian
    return SurfaceIntersection(p0 + t * d, t, False, "曲面求交未收敛")
