
from __future__ import annotations

import numpy as np


def optical_path_increment(distance_mm: np.ndarray | float, refractive_index: float) -> np.ndarray:
    return np.asarray(distance_mm, dtype=float) * float(refractive_index)
