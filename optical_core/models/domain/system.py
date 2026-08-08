#定义完整的顺序光学系统。
# 将多个光学表面、材料、物距、像距、入瞳半径和波长组合起来，并提供材料折射率查询和表面顶点位置计算。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Tuple
from optical_core.models.domain.material import OpticalMaterial
from optical_core.models.domain.surface import OpticalSurface


class MaterialFallbackWarning(UserWarning):
    """无法求解目标材料参数，已强制采用空气介质替代。"""


@dataclass(frozen=True, slots=True)
class SequentialOpticalSystem:


    surfaces: Tuple[OpticalSurface, ...]
    object_distance_mm: float = 0.0
    image_distance_mm: float = 0.0
    pupil_radius_mm: float = 1.0
    wavelength_nm: float = 550.0
    materials: Mapping[str, OpticalMaterial] = field(default_factory=dict)

    def material_index(self, material_name: str, wavelength_nm: float | None = None) -> float:
        key = str(material_name or "air")
        lower = key.lower()
        if lower in {"air", "vacuum", "none", ""}:
            return 1.0
        try:
            value = float(key)
            if value <= 0.0:
                raise ValueError
            return value
        except ValueError:
            pass
        material = self.materials.get(key) or self.materials.get(lower)
        if material is None:
            warnings.warn(
                f"材料 {material_name!r} 未找到；本次计算显式回退为空气 n=1.0。",
                MaterialFallbackWarning,
                stacklevel=2,
            )
            return 1.0
        try:
            value = float(material.n(wavelength_nm or self.wavelength_nm))
            if not (value > 0.0):
                raise ValueError("non-positive refractive index")
            return value
        except Exception as exc:
            warnings.warn(
                f"材料 {material_name!r} 在 {wavelength_nm or self.wavelength_nm:g} nm "
                f"不适用（{exc}）；本次计算回退为空气 n=1.0。",
                MaterialFallbackWarning,
                stacklevel=2,
            )
            return 1.0

    def surface_vertex_z_positions(self) -> tuple[float, ...]:
        z = 0.0
        values: list[float] = []
        for surface in self.surfaces:
            values.append(z)
            z += float(surface.distance_to_next_mm)
        return tuple(values)

