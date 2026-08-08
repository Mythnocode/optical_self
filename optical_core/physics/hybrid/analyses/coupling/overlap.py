# 实现入射复场与光纤模式的归一化复场重叠积分。
import numpy as np


def normalized_mode_overlap(field, mode, pixel_area):
    numerator = abs(np.sum(field * np.conjugate(mode)) * pixel_area) ** 2
    denominator = (np.sum(abs(field) ** 2) * pixel_area) * (np.sum(abs(mode) ** 2) * pixel_area)
    return float(numerator / denominator) if denominator > 0 else 0.0
