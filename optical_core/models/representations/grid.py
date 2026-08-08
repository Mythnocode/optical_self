

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SamplingGrid2D:


    x_mm: np.ndarray
    y_mm: np.ndarray
    dx_mm: float
    dy_mm: float

    def __post_init__(self) -> None:
        x = np.asarray(self.x_mm, dtype=float).reshape(-1)
        y = np.asarray(self.y_mm, dtype=float).reshape(-1)
        if x.size == 0 or y.size == 0:
            raise ValueError("SamplingGrid2D axes must be non-empty.")
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValueError("SamplingGrid2D axes must be finite.")
        if not np.isfinite(self.dx_mm) or float(self.dx_mm) <= 0.0:
            raise ValueError("dx_mm must be a positive finite transverse x spacing.")
        if not np.isfinite(self.dy_mm) or float(self.dy_mm) <= 0.0:
            raise ValueError("dy_mm must be a positive finite transverse y spacing.")
        object.__setattr__(self, "x_mm", x)
        object.__setattr__(self, "y_mm", y)
        object.__setattr__(self, "dx_mm", float(self.dx_mm))
        object.__setattr__(self, "dy_mm", float(self.dy_mm))

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.y_mm.size), int(self.x_mm.size))

    @property
    def cell_area_mm2(self) -> float:
        return abs(float(self.dx_mm) * float(self.dy_mm))
