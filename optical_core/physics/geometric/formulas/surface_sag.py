
from __future__ import annotations

import math
import numpy as np


def is_plane_radius(radius_mm: float | None) -> bool:
    return radius_mm is None or math.isinf(float(radius_mm))


def sag_conic_asphere(
    radial_mm: float | np.ndarray,
    *,
    radius_mm: float | None,
    conic: float = 0.0,
    asphere_a2: float = 0.0,
    asphere_coefficients: tuple[float, ...] = (),
) -> np.ndarray:

    radial = np.asarray(radial_mm, dtype=float)
    if is_plane_radius(radius_mm):
        base = np.zeros_like(radial, dtype=float)
    else:
        c = 1.0 / float(radius_mm)
        q = 1.0 + float(conic)
        radicand = 1.0 - q * (c * radial) ** 2
        if np.any(radicand < -1.0e-12):
            raise ValueError("半口径超出二次曲面矢高有效范围。")
        root = np.sqrt(np.maximum(radicand, 0.0))
        base = c * radial * radial / (1.0 + root)
    
    
    
    polynomial = float(asphere_a2) * radial**2
    for order, coeff in enumerate(asphere_coefficients, start=2):
        polynomial += float(coeff) * radial ** (2 * order)
    return base + polynomial


def sag_derivative_conic_asphere(
    radial_mm: float | np.ndarray,
    *,
    radius_mm: float | None,
    conic: float = 0.0,
    asphere_a2: float = 0.0,
    asphere_coefficients: tuple[float, ...] = (),
) -> np.ndarray:

    radial = np.asarray(radial_mm, dtype=float)
    derivative = np.zeros_like(radial, dtype=float)
    derivative += 2.0 * float(asphere_a2) * radial
    nonzero = np.abs(radial) > 1.0e-16
    valid = np.ones_like(radial, dtype=bool)
    if not is_plane_radius(radius_mm):
        c = 1.0 / float(radius_mm)
        q = 1.0 + float(conic)
        radicand = 1.0 - q * (c * radial) ** 2
        valid = radicand > 0.0
        usable = valid & nonzero
        derivative[usable] += c * radial[usable] / np.sqrt(radicand[usable])
    for order, coeff in enumerate(asphere_coefficients, start=2):
        derivative += 2.0 * order * float(coeff) * radial ** (2 * order - 1)
    derivative = np.where(nonzero, derivative, 0.0)
    derivative = np.where((~valid) & nonzero, np.nan, derivative)
    return np.asarray(derivative, dtype=float)
