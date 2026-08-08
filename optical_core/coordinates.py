
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

X_INDEX: Final[int] = 0
Y_INDEX: Final[int] = 1
Z_INDEX: Final[int] = 2
TRANSVERSE_INDICES: Final[tuple[int, int]] = (X_INDEX, Y_INDEX)
OPTICAL_AXIS_INDEX: Final[int] = Z_INDEX
OPTICAL_AXIS_NAME: Final[str] = "z"
HANDEDNESS: Final[str] = "right_handed"
COORDINATE_SYSTEM_ID: Final[str] = "RH_XYZ_Z_OPTICAL_AXIS"


@dataclass(frozen=True, slots=True)
class CoordinateConvention:
    coordinate_system_id: str = COORDINATE_SYSTEM_ID
    handedness: str = HANDEDNESS
    handedness_label: str = "right-handed"
    optical_axis: str = OPTICAL_AXIS_NAME
    propagation_sign: int = 1
    transverse_axes: tuple[str, str] = ("x", "y")


DEFAULT_COORDINATE_CONVENTION = CoordinateConvention()


def transverse_xy(points_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:


    points = np.asarray(points_mm, dtype=float)
    if points.shape[-1] != 3:
        raise ValueError("points_mm 的最后一维必须为 3，对应 (x, y, z)。")
    return points[..., X_INDEX], points[..., Y_INDEX]


def axial_z(points_mm: np.ndarray) -> np.ndarray:


    points = np.asarray(points_mm, dtype=float)
    if points.shape[-1] != 3:
        raise ValueError("points_mm 的最后一维必须为 3，对应 (x, y, z)。")
    return points[..., Z_INDEX]

