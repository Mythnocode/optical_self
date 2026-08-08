

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True, slots=True)
class ZernikeTerm:
    index: int
    name: str
    n: int
    m: int


STANDARD_TERMS: tuple[ZernikeTerm, ...] = (
    ZernikeTerm(1, "piston", 0, 0),
    ZernikeTerm(2, "tilt_y", 1, -1),
    ZernikeTerm(3, "tilt_x", 1, 1),
    ZernikeTerm(4, "defocus", 2, 0),
    ZernikeTerm(5, "astigmatism_45", 2, -2),
    ZernikeTerm(6, "astigmatism_0", 2, 2),
    ZernikeTerm(7, "coma_y", 3, -1),
    ZernikeTerm(8, "coma_x", 3, 1),
    ZernikeTerm(9, "trefoil_y", 3, -3),
    ZernikeTerm(10, "trefoil_x", 3, 3),
    ZernikeTerm(11, "spherical", 4, 0),
)


def _radial(n: int, m_abs: int, rho: np.ndarray) -> np.ndarray:
    if (n - m_abs) % 2:
        return np.zeros_like(rho, dtype=float)
    values = np.zeros_like(rho, dtype=float)
    for k in range((n - m_abs) // 2 + 1):
        coeff = (-1.0) ** k * float(math.factorial(n - k))
        coeff /= float(
            math.factorial(k)
            * math.factorial((n + m_abs) // 2 - k)
            * math.factorial((n - m_abs) // 2 - k)
        )
        values += coeff * rho ** (n - 2 * k)
    return values


def zernike(
    term: ZernikeTerm,
    rho: np.ndarray,
    theta: np.ndarray,
    *,
    normalization: str = "noll",
) -> np.ndarray:
    m_abs = abs(term.m)
    radial = _radial(term.n, m_abs, rho)
    if term.m == 0:
        values = radial
    elif term.m < 0:
        values = radial * np.sin(m_abs * theta)
    else:
        values = radial * np.cos(m_abs * theta)
    mode = str(normalization).lower()
    if mode in {"noll", "orthonormal", "rms"}:
        factor = math.sqrt(term.n + 1.0) if term.m == 0 else math.sqrt(2.0 * (term.n + 1.0))
        values = factor * values
    elif mode not in {"none", "raw", "fringe"}:
        raise ValueError(f"unknown Zernike normalization: {normalization!r}")
    return values


def fit_zernike_coefficients(
    x: np.ndarray,
    y: np.ndarray,
    values: np.ndarray,
    *,
    terms: tuple[ZernikeTerm, ...] = STANDARD_TERMS,
    mask: np.ndarray | None = None,
    weights: np.ndarray | None = None,
    normalization: str = "noll",
) -> dict[str, float]:


    x = np.asarray(x, dtype=float).reshape(-1)
    y = np.asarray(y, dtype=float).reshape(-1)
    values = np.asarray(values, dtype=float).reshape(-1)
    if x.shape != y.shape or x.shape != values.shape:
        raise ValueError("Zernike x/y/values 必须长度一致。")
    radius = np.sqrt(x * x + y * y)
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(values) & (radius <= 1.0 + 1.0e-12)
    if mask is not None:
        valid &= np.asarray(mask, dtype=bool).reshape(-1)
    if weights is None:
        w = np.ones_like(values)
    else:
        w = np.asarray(weights, dtype=float).reshape(-1)
        if w.shape != values.shape:
            raise ValueError("Zernike weights 长度不一致。")
        valid &= np.isfinite(w) & (w > 0.0)
    if np.count_nonzero(valid) < max(3, len(terms)):
        return {term.name: 0.0 for term in terms}

    rho = np.clip(radius[valid], 0.0, 1.0)
    theta = np.arctan2(y[valid], x[valid])
    matrix = np.vstack(
        [zernike(term, rho, theta, normalization=normalization) for term in terms]
    ).T
    sqrt_w = np.sqrt(w[valid])
    coeffs, *_ = np.linalg.lstsq(matrix * sqrt_w[:, None], values[valid] * sqrt_w, rcond=None)
    return {term.name: float(coeff) for term, coeff in zip(terms, coeffs)}


__all__ = ["ZernikeTerm", "STANDARD_TERMS", "zernike", "fit_zernike_coefficients"]
