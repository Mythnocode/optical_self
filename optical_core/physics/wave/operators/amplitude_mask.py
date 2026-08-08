from dataclasses import replace
import numpy as np
from optical_core.models.representations.scalar_field import ScalarField2D


def apply_amplitude_mask(field: ScalarField2D, amplitude: np.ndarray) -> ScalarField2D:
    return replace(field, values=field.values * amplitude)
