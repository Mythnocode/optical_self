# 定义追迹配置。
# 包括波长、孔径检查、像面传播、表面记录、物理效应、求交迭代次数和输出等级。
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TraceOptions:
    wavelength_nm: float | None = None
    pupil_sample_count: int = 64
    record_surfaces: bool = False
    propagate_to_image: bool = True
    evaluate_apertures: bool = True
    max_intersection_iterations: int = 12
    apply_surface_physics: bool = True
    environment_temperature_c: float = 20.0
    include_group_delay: bool = False
    output_level: Literal["full", "planes", "final"] = "full"
