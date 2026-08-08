from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SamplingAudit:
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings


def audit_uniform_grid_sampling(
    *,
    grid_size: int,
    extent_mm: float,
    wavelength_nm: float,
    propagation_distance_mm: float | None = None,
    aperture_diameter_mm: float | None = None,
) -> SamplingAudit:


    warnings: list[str] = []
    grid_size = int(grid_size)
    extent_mm = float(extent_mm)
    wavelength_mm = float(wavelength_nm) * 1e-6
    dx_mm = 2.0 * extent_mm / max(grid_size - 1, 1)

    if grid_size < 17:
        warnings.append("采样点数过低，结果可能只能用于连通性测试，不能用于精确光学评价。")
    if grid_size % 2 == 0:
        warnings.append("grid_size 建议使用奇数，便于中心光轴落在网格中心。")
    if aperture_diameter_mm is not None and aperture_diameter_mm > 0:
        fill_ratio = float(aperture_diameter_mm) / max(2.0 * extent_mm, 1e-12)
        if fill_ratio > 0.9:
            warnings.append("孔径直径接近计算窗口宽度，边界截断风险较高。")
    else:
        fill_ratio = None

    fresnel_number = None
    if aperture_diameter_mm is not None and propagation_distance_mm and propagation_distance_mm > 0 and wavelength_mm > 0:
        radius_mm = float(aperture_diameter_mm) / 2.0
        fresnel_number = radius_mm * radius_mm / (wavelength_mm * float(propagation_distance_mm))
        if fresnel_number > 1e3 and grid_size < 257:
            warnings.append("Fresnel 数较大且网格偏粗，近场细节可能采样不足。")

    return SamplingAudit(
        metrics={
            "sampling_grid_size": grid_size,
            "sampling_extent_mm": extent_mm,
            "sampling_dx_mm": dx_mm,
            "sampling_wavelength_mm": wavelength_mm,
            "sampling_aperture_fill_ratio": fill_ratio,
            "sampling_fresnel_number": fresnel_number,
        },
        warnings=tuple(warnings),
    )


__all__ = ["SamplingAudit", "audit_uniform_grid_sampling"]
