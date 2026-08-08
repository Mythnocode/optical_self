# 反射定理。
# 根据反射定律计算光线在表面的反射方向，使用入射方向和表面法向量得到反射矢量。
from __future__ import annotations

import numpy as np


def reflect_direction(incident_dir: np.ndarray, normal: np.ndarray) -> np.ndarray:
    incident = np.asarray(incident_dir, dtype=float)
    n = np.asarray(normal, dtype=float)
    incident = incident / np.maximum(np.linalg.norm(incident, axis=-1, keepdims=True), 1.0e-30)
    n = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1.0e-30)
    dot = np.sum(incident * n, axis=-1, keepdims=True)
    return incident - 2.0 * dot * n
