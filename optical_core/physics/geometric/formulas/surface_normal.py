# 计算法向量。

from __future__ import annotations

import numpy as np

from optical_core.physics.geometric.formulas.surface_sag import sag_derivative_conic_asphere


_CYLINDRICAL_TYPES = {"cylindrical", "cylinder", "cylindrical_surface", "柱面", "柱面镜"}


def cylindrical_power_axis(cylinder_axis_deg: float) -> np.ndarray:
    """Unit vector of the powered meridian in local x-y coordinates.

    ``cylinder_axis_deg`` is the zero-power/cylinder-axis azimuth, matching the
    optical prescription convention: power acts 90 degrees from that axis.
    """
    angle = np.deg2rad(float(cylinder_axis_deg))
    return np.asarray([-np.sin(angle), np.cos(angle)], dtype=float)


def surface_normal_from_point(
    point_mm: np.ndarray,
    *,
    radius_mm: float | None,
    conic: float = 0.0,
    asphere_a2: float = 0.0,
    asphere_coefficients: tuple[float, ...] = (),
    surface_type: str = "spherical",
    cylinder_axis_deg: float = 0.0,
) -> np.ndarray:

    p = np.asarray(point_mm, dtype=float)
    x = p[..., 0]
    y = p[..., 1]
    cylindrical = str(surface_type).strip().lower() in _CYLINDRICAL_TYPES
    if cylindrical:
        power_axis = cylindrical_power_axis(cylinder_axis_deg)
        signed_profile = power_axis[0] * x + power_axis[1] * y
        radial = np.abs(signed_profile)
    else:
        signed_profile = None
        power_axis = None
        radial = np.sqrt(x * x + y * y)
    derivative = sag_derivative_conic_asphere(
        radial,
        radius_mm=radius_mm,
        conic=conic,
        asphere_a2=asphere_a2,
        asphere_coefficients=asphere_coefficients,
    )
    normal = np.zeros(p.shape, dtype=float)
    normal[..., 2] = 1.0
    if cylindrical:
        signed_derivative = derivative * np.sign(signed_profile)
        normal[..., 0] = -signed_derivative * power_axis[0]
        normal[..., 1] = -signed_derivative * power_axis[1]
    else:
        nonzero = radial > 1.0e-15
        scale = np.zeros_like(radial, dtype=float)
        np.divide(-derivative, radial, out=scale, where=nonzero)
        normal[..., 0] = scale * x
        normal[..., 1] = scale * y
    norm = np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal / np.maximum(norm, 1.0e-30)


__all__ = ["cylindrical_power_axis", "surface_normal_from_point"]
