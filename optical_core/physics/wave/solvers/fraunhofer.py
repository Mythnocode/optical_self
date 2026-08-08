from __future__ import annotations

from dataclasses import replace
import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.operators.fft_operator import fft2_centered


def propagate_fraunhofer(field: ScalarField2D, distance_mm: float, *, normalize: bool = False) -> ScalarField2D:


    if distance_mm <= 0:
        raise ValueError("夫琅禾费传播 distance_mm 必须为正数。")

    wavelength_mm = field.wavelength_nm * 1e-6 / field.refractive_index
    ny, nx = field.values.shape
    fx = np.fft.fftshift(np.fft.fftfreq(nx, d=field.grid.dx_mm))
    fy = np.fft.fftshift(np.fft.fftfreq(ny, d=field.grid.dy_mm))
    out_x = wavelength_mm * distance_mm * fx
    out_y = wavelength_mm * distance_mm * fy

    output = fft2_centered(field.values) * field.grid.dx_mm * field.grid.dy_mm
    if normalize:
        peak = float(np.max(np.abs(output) ** 2))
        if peak > 0:
            output = output / np.sqrt(peak)

    dx = float(out_x[1] - out_x[0]) if nx > 1 else 0.0
    dy = float(out_y[1] - out_y[0]) if ny > 1 else 0.0
    return replace(
        field,
        values=output,
        grid=SamplingGrid2D(x_mm=out_x, y_mm=out_y, dx_mm=dx, dy_mm=dy),
        z_mm=field.z_mm + distance_mm,
    )
