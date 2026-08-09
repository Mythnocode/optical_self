# 求光线与表面交点。采用顶点平面初值和牛顿迭代，并判断未收敛、反向交点等异常
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.formulas.surface_sag import sag_conic_asphere, sag_derivative_conic_asphere


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
    surface_type = str(getattr(surface, "surface_type", "")).strip().lower()
    metadata = dict(getattr(surface, "metadata", {}) or {})
    cylindrical = surface_type in {"cylindrical", "cylinder", "cylindrical_refractive"}
    if "cylinder_power_axis_deg" in metadata:
        power_axis_deg = float(90.0 if metadata.get("cylinder_power_axis_deg") is None else metadata.get("cylinder_power_axis_deg"))
    else:
        cylinder_axis_deg = float(metadata.get("cylinder_axis_deg", metadata.get("axis_angle_deg", 0.0)) or 0.0)
        power_axis_deg = cylinder_axis_deg + 90.0
    power_axis_rad = np.radians(power_axis_deg % 180.0)
    cylinder_cos = float(np.cos(power_axis_rad))
    cylinder_sin = float(np.sin(power_axis_rad))

    for _ in range(max_iterations):
        point = p0 + t * d
        if cylindrical:
            signed_coordinate = float(point[0] * cylinder_cos + point[1] * cylinder_sin)
            radial = abs(signed_coordinate)
        else:
            signed_coordinate = 0.0
            radial = float(np.hypot(point[0], point[1]))
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
        if cylindrical:
            sign = 0.0 if abs(signed_coordinate) <= 1.0e-15 else (1.0 if signed_coordinate > 0.0 else -1.0)
            coordinate_rate = float(d[0] * cylinder_cos + d[1] * cylinder_sin)
            sag_rate = derivative * sign * coordinate_rate
        else:
            radial_rate = 0.0 if radial <= 1.0e-15 else (point[0] * d[0] + point[1] * d[1]) / radial
            sag_rate = derivative * radial_rate
        jacobian = d[2] - sag_rate
        if abs(jacobian) <= 1.0e-14:
            break
        t -= residual / jacobian
    return SurfaceIntersection(p0 + t * d, t, False, "曲面求交未收敛")
