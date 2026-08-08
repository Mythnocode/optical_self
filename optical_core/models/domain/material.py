# 定义光学材料
# 保存材料名称和折射率，并提供折射率查询接口，不计算色散
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpticalMaterial:
    name: str
    refractive_index: float = 1.0

    def n(self, wavelength_nm: float | None = None) -> float:
        return float(self.refractive_index)

