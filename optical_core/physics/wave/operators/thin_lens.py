from dataclasses import replace
import numpy as np
from optical_core.models.representations.scalar_field import ScalarField2D


def apply_thin_lens(field: ScalarField2D, focal_length_mm: float) -> ScalarField2D:
    wavelength_mm = field.wavelength_nm * 1e-6
    k = 2.0 * np.pi * field.refractive_index / wavelength_mm
    x, y = np.meshgrid(field.grid.x_mm, field.grid.y_mm, indexing="xy")
    phase = np.exp(-1j * k * (x * x + y * y) / (2.0 * focal_length_mm))
    return replace(field, values=field.values * phase)
