
from __future__ import annotations

from typing import Iterable, Sequence
from math import factorial

import numpy as np


def _zernike_term(n: int, m: int, rho: np.ndarray, theta: np.ndarray) -> np.ndarray:
    m_abs = abs(int(m))
    if (n - m_abs) % 2:
        return np.zeros_like(rho)
    radial = np.zeros_like(rho, dtype=float)
    for k in range((n - m_abs) // 2 + 1):
        num = (-1) ** k * factorial(n - k)
        den = (
            factorial(k)
            * factorial((n + m_abs) // 2 - k)
            * factorial((n - m_abs) // 2 - k)
        )
        radial += (num / den) * rho ** (n - 2 * k)
    if m >= 0:
        return radial * np.cos(m_abs * theta)
    return radial * np.sin(m_abs * theta)


NOLL_LIKE_TERMS: tuple[tuple[int, int], ...] = (
    (0, 0),
    (1, -1),
    (1, 1),
    (2, 0),
    (2, -2),
    (2, 2),
    (3, -1),
    (3, 1),
    (3, -3),
    (3, 3),
    (4, 0),
    (4, -2),
    (4, 2),
    (4, -4),
    (4, 4),
)


def normalized_pupil_coordinates(grid_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-1.0, 1.0, int(grid_size))
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    rho = np.sqrt(xx * xx + yy * yy)
    theta = np.arctan2(yy, xx)
    mask = rho <= 1.0
    return rho, theta, mask, axis


def fit_zernike_map(opd_nm: np.ndarray, *, max_terms: int = 15, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    opd = np.asarray(opd_nm, dtype=float)
    if opd.ndim != 2 or opd.shape[0] != opd.shape[1]:
        raise ValueError("opd_nm must be a square 2-D array")
    rho, theta, pupil_mask, _ = normalized_pupil_coordinates(opd.shape[0])
    if mask is not None:
        pupil_mask &= np.asarray(mask, dtype=bool)
    terms = NOLL_LIKE_TERMS[: max(1, int(max_terms))]
    basis = np.vstack([_zernike_term(n, m, rho, theta)[pupil_mask].ravel() for n, m in terms]).T
    target = opd[pupil_mask].ravel()
    coeff, *_ = np.linalg.lstsq(basis, target, rcond=None)
    fitted = np.zeros_like(opd, dtype=float)
    for c, (n, m) in zip(coeff, terms):
        fitted += float(c) * _zernike_term(n, m, rho, theta)
    fitted = np.where(pupil_mask, fitted, 0.0)
    return coeff.astype(float), fitted


def remove_zernike_modes(opd_nm: np.ndarray, remove_indices: Sequence[int] = (0, 1, 2, 3), *, max_terms: int = 15) -> dict[str, np.ndarray]:
    coeff, fitted = fit_zernike_map(np.asarray(opd_nm, dtype=float), max_terms=max_terms)
    rho, theta, mask, _ = normalized_pupil_coordinates(np.asarray(opd_nm).shape[0])
    removal = np.zeros_like(fitted)
    for idx in remove_indices:
        if 0 <= int(idx) < min(len(coeff), len(NOLL_LIKE_TERMS)):
            n, m = NOLL_LIKE_TERMS[int(idx)]
            removal += coeff[int(idx)] * _zernike_term(n, m, rho, theta)
    residual = np.where(mask, np.asarray(opd_nm, dtype=float) - removal, 0.0)
    return {"coefficients_nm": coeff, "removed_map_nm": removal, "residual_map_nm": residual, "fitted_map_nm": fitted}


def compute_standard_wavefront_map(coefficients_nm: Sequence[float], *, grid_size: int = 65) -> np.ndarray:
    rho, theta, mask, _ = normalized_pupil_coordinates(grid_size)
    wavefront = np.zeros((grid_size, grid_size), dtype=float)
    for coeff, (n, m) in zip(coefficients_nm, NOLL_LIKE_TERMS):
        wavefront += float(coeff) * _zernike_term(n, m, rho, theta)
    return np.where(mask, wavefront, 0.0)


def image_space_numerical_aperture(rms_spot_radius_mm: float, focal_shift_mm: float, *, refractive_index: float = 1.0) -> float:
    r = abs(float(rms_spot_radius_mm))
    d = abs(float(focal_shift_mm))
    if d <= 0:
        return 0.0
    return min(float(refractive_index) * r / np.sqrt(r * r + d * d), float(refractive_index))


def spot_diagram_points_um(y_mm: Iterable[float], z_mm: Iterable[float]) -> np.ndarray:
    y = np.asarray(list(y_mm), dtype=float) * 1000.0
    z = np.asarray(list(z_mm), dtype=float) * 1000.0
    return np.column_stack([y, z])


def fit_gaussian_array(intensity: np.ndarray) -> dict[str, float]:
    arr = np.asarray(intensity, dtype=float)
    if arr.ndim != 2:
        raise ValueError("intensity must be 2-D")
    total = float(np.sum(arr))
    if total <= 0:
        return {"gaussian_center_x_px": 0.0, "gaussian_center_y_px": 0.0, "gaussian_sigma_x_px": 0.0, "gaussian_sigma_y_px": 0.0}
    yy, xx = np.indices(arr.shape)
    cx = float(np.sum(arr * xx) / total)
    cy = float(np.sum(arr * yy) / total)
    sx = float(np.sqrt(np.sum(arr * (xx - cx) ** 2) / total))
    sy = float(np.sqrt(np.sum(arr * (yy - cy) ** 2) / total))
    return {"gaussian_center_x_px": cx, "gaussian_center_y_px": cy, "gaussian_sigma_x_px": sx, "gaussian_sigma_y_px": sy}
