# 孔径裁剪。
# 判断光线与表面的交点是否位于圆形通光孔径内，未在通光孔径的光线视为无效。用于识别有效光线和被孔径截断的光线。
from __future__ import annotations

import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.physics.geometric.formulas.aperture_test import inside_circular_aperture


def point_passes_surface_aperture(point_mm: np.ndarray, surface: OpticalSurface) -> bool:
    point = np.asarray(point_mm, dtype=float)
    return bool(inside_circular_aperture(point[..., 0], point[..., 1], surface.clear_aperture_mm))
