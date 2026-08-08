# 计算法向量。

from __future__ import annotations

import numpy as np

from optical_core.physics.geometric.formulas.surface_sag import sag_derivative_conic_asphere


def surface_normal_from_point(
    point_mm: np.ndarray,
    *,
    radius_mm: float | None,
    conic: float = 0.0,
    asphere_a2: float = 0.0,
    asphere_coefficients: tuple[float, ...] = (),
) -> np.ndarray:

    p = np.asarray(point_mm, dtype=float)
    x = p[..., 0]
    y = p[..., 1]
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
    nonzero = radial > 1.0e-15
    scale = np.zeros_like(radial, dtype=float)
    np.divide(-derivative, radial, out=scale, where=nonzero)
    normal[..., 0] = scale * x
    normal[..., 1] = scale * y
    norm = np.linalg.norm(normal, axis=-1, keepdims=True)
    return normal / np.maximum(norm, 1.0e-30)
