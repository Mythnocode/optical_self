# 计算两个标量复场的归一化重叠和耦合效率。
from __future__ import annotations

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


def normalized_field_overlap(field: ScalarField2D, mode: ScalarField2D) -> complex:
    """计算两个复光场的归一化重叠积分。"""

    if field.values.shape != mode.values.shape:
        raise ValueError("field 和 mode 的采样形状必须一致。")
    area = abs(field.grid.dx_mm * field.grid.dy_mm)
    numerator = np.sum(field.values * np.conj(mode.values)) * area
    field_norm = np.sum(np.abs(field.values) ** 2) * area
    mode_norm = np.sum(np.abs(mode.values) ** 2) * area
    denom = np.sqrt(field_norm * mode_norm)
    if denom == 0:
        return 0.0 + 0.0j
    return complex(numerator / denom)


def coupling_efficiency(field: ScalarField2D, mode: ScalarField2D) -> float:
    return float(abs(normalized_field_overlap(field, mode)) ** 2)
