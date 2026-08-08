# 温度和热膨胀修正
# 内置显式热光效应与线性热膨胀模型。
# 原生材料库仅存储波长色散参数；温度修正属于可选工程输入项，对于无文档记载的系数，不会从验证数据或外部光学设计软件中随意推定补全。

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ThermalOpticModel:
    reference_temperature_c: float = 20.0
    dn_dt_per_c: float = 0.0
    d2n_dt2_per_c2: float = 0.0
    cte_per_c: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ThermalOpticModel":
        raw = dict(value or {})
        cte = raw.get("cte_per_c")
        if cte is None:
            cte = float(raw.get("cte_ppm_per_c", 0.0)) * 1.0e-6
        model = cls(
            reference_temperature_c=float(raw.get("reference_temperature_c", 20.0)),
            dn_dt_per_c=float(raw.get("dn_dt_per_c", raw.get("dn_dT_per_c", 0.0))),
            d2n_dt2_per_c2=float(raw.get("d2n_dt2_per_c2", 0.0)),
            cte_per_c=float(cte),
        )
        if not all(math.isfinite(item) for item in (
            model.reference_temperature_c,
            model.dn_dt_per_c,
            model.d2n_dt2_per_c2,
            model.cte_per_c,
        )):
            raise ValueError("thermal-optic coefficients must be finite")
        return model


def refractive_index_at_temperature(
    reference_index: float,
    temperature_c: float,
    model: ThermalOpticModel,
) -> float:
    delta = float(temperature_c) - float(model.reference_temperature_c)
    result = (
        float(reference_index)
        + float(model.dn_dt_per_c) * delta
        + float(model.d2n_dt2_per_c2) * delta * delta
    )
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError("temperature-corrected refractive index must be positive and finite")
    return result


def linear_thermal_scale(temperature_c: float, model: ThermalOpticModel) -> float:
    delta = float(temperature_c) - float(model.reference_temperature_c)
    scale = 1.0 + float(model.cte_per_c) * delta
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("thermal expansion produced a non-positive length scale")
    return scale


__all__ = [
    "ThermalOpticModel",
    "refractive_index_at_temperature",
    "linear_thermal_scale",
]
