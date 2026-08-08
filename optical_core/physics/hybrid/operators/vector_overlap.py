# 计算两个标量复场的归一化重叠和耦合效率。
from __future__ import annotations

import numpy as np

from optical_core.models.representations.vector_field import VectorField2D


def normalized_vector_overlap(field: VectorField2D, mode: VectorField2D) -> complex:
    if field.ex.shape != mode.ex.shape:
        raise ValueError("vector field and mode shapes must match")
    if not np.array_equal(field.grid.x_mm, mode.grid.x_mm) or not np.array_equal(field.grid.y_mm, mode.grid.y_mm):
        raise ValueError("vector field and mode must use the same coordinates")
    area = abs(float(field.grid.dx_mm) * float(field.grid.dy_mm))
    numerator = np.sum(
        field.ex * np.conj(mode.ex)
        + field.ey * np.conj(mode.ey)
        + field.ez * np.conj(mode.ez)
    ) * area
    field_norm = np.sum(field.intensity) * area
    mode_norm = np.sum(mode.intensity) * area
    denominator = np.sqrt(field_norm * mode_norm)
    return 0.0 + 0.0j if denominator <= 0.0 else complex(numerator / denominator)


def vector_coupling_efficiency(field: VectorField2D, mode: VectorField2D) -> float:
    return float(abs(normalized_vector_overlap(field, mode)) ** 2)


__all__ = ["normalized_vector_overlap", "vector_coupling_efficiency"]
