# 对点坐标进行变换。

from __future__ import annotations

import numpy as np


def translate(points_mm: np.ndarray, offset_mm: tuple[float, float, float]) -> np.ndarray:
    return np.asarray(points_mm, dtype=float) + np.asarray(offset_mm, dtype=float)
