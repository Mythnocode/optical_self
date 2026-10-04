
"""3D 光学场景的数据模型。

数据类描述元件、光线、标注和场景范围，便于适配器与渲染器之间传递结构化
信息，避免在 Matplotlib artist 上直接承载业务状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

RayRole = Literal["chief", "marginal", "regular", "failed"]
ObjectKind = Literal["aperture", "detector", "image", "fiber", "focus", "section"]


@dataclass(frozen=True, slots=True)
class SceneSurface:
    index: int
    name: str
    surface_type: str
    group_id: str
    material: str
    z_physical_mm: float
    z_display_mm: float
    radius_mm: float
    conic: float
    aperture_radius_mm: float
    decenter_x_mm: float = 0.0
    decenter_y_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    tilt_z_deg: float = 0.0
    selected: bool = False
    enabled: bool = True

    @property
    def is_plane(self) -> bool:
        return not np.isfinite(self.radius_mm) or abs(self.radius_mm) > 1.0e12 or abs(self.radius_mm) < 1.0e-12


@dataclass(frozen=True, slots=True)
class SceneRay:
    index: int
    points_physical_mm: np.ndarray
    points_display_mm: np.ndarray
    role: RayRole = "regular"
    status_code: int = 0
    wavelength_nm: float | None = None
    power_weight: float = 1.0

    def __post_init__(self) -> None:
        physical = np.asarray(self.points_physical_mm, dtype=float)
        display = np.asarray(self.points_display_mm, dtype=float)
        if physical.ndim != 2 or physical.shape[1] != 3 or display.shape != physical.shape:
            raise ValueError("Scene ray points must have shape (N, 3).")
        physical = np.ascontiguousarray(physical)
        display = np.ascontiguousarray(display)
        physical.setflags(write=False)
        display.setflags(write=False)
        object.__setattr__(self, "points_physical_mm", physical)
        object.__setattr__(self, "points_display_mm", display)


@dataclass(frozen=True, slots=True)
class SceneObject:
    kind: ObjectKind
    name: str
    z_display_mm: float
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    radius_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0
    selected: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OpticalScene:
    surfaces: tuple[SceneSurface, ...]
    rays: tuple[SceneRay, ...]
    objects: tuple[SceneObject, ...]
    optical_axis: tuple[float, float]
    scale_mode: str
    scale_label: str
    full_ray_count: int
    selected_surface_index: int | None = None
    section_plane_vertices: tuple[tuple[float, float, float], ...] = ()
    show_section_plane: bool = False

    @property
    def display_points(self) -> np.ndarray:
        chunks = [ray.points_display_mm for ray in self.rays]
        if not chunks:
            return np.empty((0, 3), dtype=float)
        return np.vstack(chunks)


__all__ = [
    "ObjectKind",
    "OpticalScene",
    "RayRole",
    "SceneObject",
    "SceneRay",
    "SceneSurface",
]
