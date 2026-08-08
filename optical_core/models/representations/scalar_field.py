

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D


class PowerUnit(str, Enum):
    W = "W"
    MW = "mW"
    ARBITRARY = "a.u."


class FieldNormalization(str, Enum):
    ABSOLUTE_POWER = "absolute_power"
    UNIT_POWER = "unit_power"
    PEAK_AMPLITUDE = "peak_amplitude"
    ARBITRARY = "arbitrary"


@dataclass(frozen=True, slots=True, init=False)
class ScalarField2D:


    values: np.ndarray
    grid: SamplingGrid2D
    wavelength_nm: float
    refractive_index: float
    z_mm: float
    integrated_power: float
    power_unit: PowerUnit
    normalization: FieldNormalization

    def __init__(
        self,
        values: np.ndarray,
        grid: SamplingGrid2D,
        wavelength_nm: float,
        refractive_index: float,
        z_mm: float,
        integrated_power: float | None = None,
        power_unit: PowerUnit | str = PowerUnit.ARBITRARY,
        normalization: FieldNormalization | str = FieldNormalization.ARBITRARY,
    ) -> None:
        if integrated_power is None:
            integrated_power = float(
                np.sum(np.abs(np.asarray(values, dtype=np.complex128)) ** 2)
                * grid.cell_area_mm2
            )
            power_unit = PowerUnit.ARBITRARY
            normalization = FieldNormalization.ARBITRARY

        unit = PowerUnit(power_unit)
        norm = FieldNormalization(normalization)
        if unit in {PowerUnit.W, PowerUnit.MW} and norm is not FieldNormalization.ABSOLUTE_POWER:
            raise ValueError("物理功率单位 W/mW 必须使用 normalization='absolute_power'.")
        if unit is PowerUnit.ARBITRARY and norm is FieldNormalization.ABSOLUTE_POWER:
            raise ValueError("a.u. 不能标记为 absolute_power。")
        power = float(integrated_power)
        if not np.isfinite(power) or power < 0.0:
            raise ValueError("integrated_power 必须为非负有限数。")

        array = np.asarray(values, dtype=np.complex128)
        if array.shape != grid.shape:
            raise ValueError(
                f"field values shape {array.shape} 与 grid shape {grid.shape} 不一致。"
            )
        if not np.isfinite(wavelength_nm) or float(wavelength_nm) <= 0.0:
            raise ValueError("wavelength_nm 必须为正有限数。")
        if not np.isfinite(refractive_index) or float(refractive_index) <= 0.0:
            raise ValueError("refractive_index 必须为正有限数。")

        object.__setattr__(self, "values", array)
        object.__setattr__(self, "grid", grid)
        object.__setattr__(self, "wavelength_nm", float(wavelength_nm))
        object.__setattr__(self, "refractive_index", float(refractive_index))
        object.__setattr__(self, "z_mm", float(z_mm))
        object.__setattr__(self, "integrated_power", power)
        object.__setattr__(self, "power_unit", unit)
        object.__setattr__(self, "normalization", norm)

    @property
    def power_label(self) -> str:
        return self.power_unit.value

    def normalized(self) -> "ScalarField2D":

        power = float(
            np.sum(np.abs(self.values) ** 2) * abs(self.grid.dx_mm * self.grid.dy_mm)
        )
        if power <= 0.0 or not np.isfinite(power):
            return self
        return ScalarField2D(
            values=self.values / np.sqrt(power),
            grid=self.grid,
            wavelength_nm=self.wavelength_nm,
            refractive_index=self.refractive_index,
            z_mm=self.z_mm,
            integrated_power=1.0,
            power_unit=PowerUnit.ARBITRARY,
            normalization=FieldNormalization.UNIT_POWER,
        )

    def power_in(self, unit: PowerUnit | str) -> float:
        target = PowerUnit(unit)
        if self.power_unit is PowerUnit.ARBITRARY or target is PowerUnit.ARBITRARY:
            if target is self.power_unit:
                return self.integrated_power
            raise ValueError("a.u. 与物理功率单位之间不能无标定换算。")
        watts = self.integrated_power if self.power_unit is PowerUnit.W else self.integrated_power / 1000.0
        return watts if target is PowerUnit.W else watts * 1000.0
