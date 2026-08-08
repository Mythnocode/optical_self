from __future__ import annotations

from dataclasses import replace
import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.operators.fft_operator import fft2_centered, ifft2_centered


def propagate_fresnel(field: ScalarField2D, distance_mm: float) -> ScalarField2D:
    """基于传递函数形式的菲涅尔传播。"""

    if distance_mm < 0:
        raise ValueError("distance_mm 不能为负数。")
    if distance_mm == 0:
        return replace(field)

    wavelength_mm = field.wavelength_nm * 1e-6 / field.refractive_index
    ny, nx = field.values.shape
    fx = np.fft.fftshift(np.fft.fftfreq(nx, d=field.grid.dx_mm))
    fy = np.fft.fftshift(np.fft.fftfreq(ny, d=field.grid.dy_mm))
    fxx, fyy = np.meshgrid(fx, fy, indexing="xy")

    k = 2.0 * np.pi / wavelength_mm
    transfer = np.exp(1j * k * distance_mm) * np.exp(-1j * np.pi * wavelength_mm * distance_mm * (fxx**2 + fyy**2))
    output = ifft2_centered(fft2_centered(field.values) * transfer)
    return replace(field, values=output, z_mm=field.z_mm + distance_mm)
