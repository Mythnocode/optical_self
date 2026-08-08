# 判断光线落点是否位于圆形通光孔径内，用于确定光线是否被光阑或透镜边缘截断
from __future__ import annotations

import numpy as np


def inside_circular_aperture(y_mm: np.ndarray, z_mm: np.ndarray, radius_mm: float | None) -> np.ndarray:
    if radius_mm is None:
        return np.ones_like(np.asarray(y_mm, dtype=float), dtype=bool)
    radius = float(radius_mm)
    return np.asarray(y_mm, dtype=float) ** 2 + np.asarray(z_mm, dtype=float) ** 2 <= radius * radius + 1.0e-12
