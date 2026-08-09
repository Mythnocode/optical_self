# 计算法向量。

from __future__ import annotations

import numpy as np

from typing import Any, Mapping

from optical_core.physics.geometric.formulas.surface_sag import sag_derivative_conic_asphere


def surface_normal_from_point(
    point_mm: np.ndarray,
    *,
    radius_mm: float | None,
    conic: float = 0.0,
    asphere_a2: float = 0.0,
    asphere_coefficients: tuple[float, ...] = (),
    surface_type: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> np.ndarray:

    p = np.asarray(point_mm, dtype=float)
    x = p[..., 0]
    y = p[..., 1]
    kind = str(surface_type).strip().lower()
    cylindrical = kind in {"cylindrical", "cylinder", "cylindrical_refractive"}
    normal = np.zeros(p.shape, dtype=float)
    normal[..., 2] = 1.0

    if cylindrical:
        info = dict(metadata or {})
        if "cylinder_power_axis_deg" in info:
            power_axis_deg = float(90.0 if info.get("cylinder_power_axis_deg") is None else info.get("cylinder_power_axis_deg"))
        else:
            cylinder_axis_deg = float(info.get("cylinder_axis_deg", info.get("axis_angle_deg", 0.0)) or 0.0)
            power_axis_deg = cylinder_axis_deg + 90.0
        angle = np.radians(power_axis_deg % 180.0)
        c = float(np.cos(angle))
        s = float(np.sin(angle))
        signed_coordinate = x * c + y * s
        radial = np.abs(signed_coordinate)
        derivative = sag_derivative_conic_asphere(
            radial,
            radius_mm=radius_mm,
            conic=conic,
            asphere_a2=asphere_a2,
            asphere_coefficients=asphere_coefficients,
        )
        sign = np.sign(signed_coordinate)
        slope = -derivative * sign
        normal[..., 0] = slope * c
        normal[..., 1] = slope * s
    else:
        radial = np.sqrt(x * x + y * y)
        derivative = sag_derivative_conic_asphere(
            radial,
            radius_mm=radius_mm,
            conic=conic,
            asphere_a2=asphere_a2,
            asphere_coefficients=asphere_coefficients,
        )
        nonzero = radial > 1.0e-15
        scale = np.zeros_like(radial, dtype=float)
        np.divide(-derivative, radial, out=scale, where=nonzero)
        normal[..., 0] = scale * x
        normal[..., 1] = scale * y

    norm = np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal / np.maximum(norm, 1.0e-30)
