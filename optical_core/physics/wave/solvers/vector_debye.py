
from __future__ import annotations

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.models.representations.vector_field import VectorField2D


def vectorial_debye_focus(
    pupil_field: ScalarField2D,
    *,
    focal_length_mm: float,
    numerical_aperture: float,
    jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j),
) -> VectorField2D:


    focal_length = float(focal_length_mm)
    n_medium = float(pupil_field.refractive_index)
    na = float(numerical_aperture)
    if focal_length <= 0.0:
        raise ValueError("focal_length_mm must be positive")
    if not 0.0 < na <= n_medium:
        raise ValueError("numerical_aperture must lie in (0, refractive_index]")
    jones = np.asarray(jones_vector, dtype=np.complex128).reshape(-1)
    if jones.shape != (2,) or np.linalg.norm(jones) <= 0.0:
        raise ValueError("jones_vector must contain two non-zero finite components")
    jones = jones / np.linalg.norm(jones)

    xx, yy = np.meshgrid(pupil_field.grid.x_mm, pupil_field.grid.y_mm, indexing="xy")
    rho = np.sqrt(xx * xx + yy * yy)
    pupil_radius = focal_length * na / n_medium
    mask = rho <= pupil_radius
    sx = np.zeros_like(xx)
    sy = np.zeros_like(yy)
    sx[mask] = xx[mask] / focal_length
    sy[mask] = yy[mask] / focal_length
    transverse2 = sx * sx + sy * sy
    sz = np.sqrt(np.maximum(1.0 - transverse2, 0.0))

    
    
    px = np.full_like(xx, jones[0], dtype=np.complex128)
    py = np.full_like(yy, jones[1], dtype=np.complex128)
    pz = np.zeros_like(px)
    dot = px * sx + py * sy + pz * sz
    ex_pupil = px - dot * sx
    ey_pupil = py - dot * sy
    ez_pupil = pz - dot * sz
    apodization = np.sqrt(np.maximum(sz, 0.0))
    scalar = np.asarray(pupil_field.values, dtype=np.complex128)
    ex_pupil = np.where(mask, scalar * apodization * ex_pupil, 0.0)
    ey_pupil = np.where(mask, scalar * apodization * ey_pupil, 0.0)
    ez_pupil = np.where(mask, scalar * apodization * ez_pupil, 0.0)

    def transform(values: np.ndarray) -> np.ndarray:
        return np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(values))) * abs(
            pupil_field.grid.dx_mm * pupil_field.grid.dy_mm
        )

    ex = transform(ex_pupil)
    ey = transform(ey_pupil)
    ez = transform(ez_pupil)
    wavelength_mm = float(pupil_field.wavelength_nm) * 1.0e-6
    fx = np.fft.fftshift(np.fft.fftfreq(xx.shape[1], d=float(pupil_field.grid.dx_mm)))
    fy = np.fft.fftshift(np.fft.fftfreq(yy.shape[0], d=float(pupil_field.grid.dy_mm)))
    x_focus = wavelength_mm * focal_length / n_medium * fx
    y_focus = wavelength_mm * focal_length / n_medium * fy
    grid = SamplingGrid2D(
        x_mm=x_focus,
        y_mm=y_focus,
        dx_mm=float(x_focus[1] - x_focus[0]),
        dy_mm=float(y_focus[1] - y_focus[0]),
    )
    return VectorField2D(
        ex=ex,
        ey=ey,
        ez=ez,
        grid=grid,
        wavelength_nm=pupil_field.wavelength_nm,
        refractive_index=n_medium,
        z_mm=pupil_field.z_mm + focal_length,
    ).normalized()


__all__ = ["vectorial_debye_focus"]
