# 定义膜层
# 包括折射率、消光系数、膜层厚度、温度系数和热膨胀系数。
# 可计算不同温度下的复折射率和膜厚。
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoatingLayerSpec:


    name: str = "layer"
    refractive_index: float = 1.0
    extinction_coefficient: float = 0.0
    thickness_nm: float = 0.0
    dn_dt_per_c: float = 0.0
    dk_dt_per_c: float = 0.0
    cte_per_c: float = 0.0
    reference_temperature_c: float = 20.0

    def __post_init__(self) -> None:
        if self.refractive_index <= 0.0:
            raise ValueError("coating refractive_index must be positive")
        if self.extinction_coefficient < 0.0:
            raise ValueError("coating extinction_coefficient must be non-negative")
        if self.thickness_nm < 0.0:
            raise ValueError("coating thickness_nm must be non-negative")

    def index_at_temperature(self, temperature_c: float) -> complex:
        delta = float(temperature_c) - float(self.reference_temperature_c)
        n = float(self.refractive_index) + float(self.dn_dt_per_c) * delta
        k = max(
            float(self.extinction_coefficient) + float(self.dk_dt_per_c) * delta,
            0.0,
        )
        return complex(n, -k)

    def thickness_at_temperature_nm(self, temperature_c: float) -> float:
        delta = float(temperature_c) - float(self.reference_temperature_c)
        return float(self.thickness_nm) * (1.0 + float(self.cte_per_c) * delta)


__all__ = ["CoatingLayerSpec"]
