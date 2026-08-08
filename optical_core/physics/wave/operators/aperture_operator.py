from dataclasses import replace
import numpy as np
from optical_core.models.representations.scalar_field import ScalarField2D


def apply_circular_aperture(field: ScalarField2D, radius_mm: float) -> ScalarField2D:
    x, y = np.meshgrid(field.grid.x_mm, field.grid.y_mm, indexing="xy")
    mask = (x * x + y * y) <= radius_mm * radius_mm
    return replace(field, values=field.values * mask)
