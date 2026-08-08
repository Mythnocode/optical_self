import numpy as np
from optical_core.models.representations.scalar_field import ScalarField2D


def validate_scalar_field(field: ScalarField2D) -> None:
    if not np.iscomplexobj(field.values):
        raise ValueError("ScalarField2D.values 必须是复数数组")
    if field.values.ndim != 2:
        raise ValueError("ScalarField2D.values 必须是二维数组")
