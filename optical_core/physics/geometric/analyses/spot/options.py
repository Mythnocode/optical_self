# 定义点列图分析配置。

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpotAnalysisOptions:
    output_unit: str = "um"
    wavelength_nm: float | None = None
    numerical_aperture: float | None = None
    f_number: float | None = None
    focal_length_mm: float | None = None
    aperture_diameter_mm: float | None = None
    refractive_index: float = 1.0
    include_real_ray_airy: bool = True
