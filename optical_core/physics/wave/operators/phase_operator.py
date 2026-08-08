from dataclasses import replace
import numpy as np
from optical_core.models.representations.scalar_field import ScalarField2D


def apply_phase_mask(field: ScalarField2D, phase_rad: np.ndarray) -> ScalarField2D:
    return replace(field, values=field.values * np.exp(1j * phase_rad))
