# 定义单个光学表面。
# 包括曲率半径、表面间距、前后材料、通光孔径、圆锥系数、非球面系数、膜层、吸收、粗糙度和光栅参数。
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple
import math

from optical_core.models.domain.coating import CoatingLayerSpec


@dataclass(frozen=True, slots=True)
class OpticalSurface:


    index: int
    surface_type: str = "refractive"
    radius_mm: Optional[float] = None
    distance_to_next_mm: float = 0.0
    material_before: str = "air"
    material_after: str = "air"
    clear_aperture_mm: Optional[float] = None
    conic: float = 0.0
    asphere_a2: float = 0.0
    asphere_coefficients: Tuple[float, ...] = ()
    coating_layers: Tuple[CoatingLayerSpec, ...] = ()
    surface_absorption_fraction: float = 0.0
    roughness_rms_nm: float = 0.0
    grating_period_um: Optional[float] = None
    grating_orders: Tuple[int, ...] = ()
    grating_efficiencies: Tuple[float, ...] = ()
    aperture_type: str = "circular"
    mechanical_diameter_mm: Optional[float] = None
    enabled: bool = True
    decenter_x_mm: float = 0.0
    decenter_y_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    tilt_z_deg: float = 0.0
    metadata: Mapping[str, Any] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.surface_absorption_fraction) < 1.0:
            raise ValueError("surface_absorption_fraction must be in [0, 1)")
        if float(self.roughness_rms_nm) < 0.0:
            raise ValueError("roughness_rms_nm must be non-negative")
        if self.grating_period_um is not None and float(self.grating_period_um) <= 0.0:
            raise ValueError("grating_period_um must be positive")
        if self.grating_efficiencies and len(self.grating_efficiencies) != len(self.grating_orders):
            raise ValueError("grating_orders and grating_efficiencies must have equal length")
        if any(float(value) < 0.0 for value in self.grating_efficiencies):
            raise ValueError("grating efficiencies must be non-negative")
        if sum(float(value) for value in self.grating_efficiencies) > 1.0 + 1.0e-12:
            raise ValueError("grating efficiencies must sum to at most one")
        if self.mechanical_diameter_mm is not None and float(self.mechanical_diameter_mm) <= 0.0:
            raise ValueError("mechanical_diameter_mm must be positive")
        for name in ("decenter_x_mm", "decenter_y_mm", "tilt_x_deg", "tilt_y_deg", "tilt_z_deg"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        object.__setattr__(self, "enabled", bool(self.enabled))
        if isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", {})
        else:
            object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def has_pose_transform(self) -> bool:
        return any(
            abs(float(value)) > 1.0e-15
            for value in (
                self.decenter_x_mm,
                self.decenter_y_mm,
                self.tilt_x_deg,
                self.tilt_y_deg,
                self.tilt_z_deg,
            )
        )

    @property
    def is_plane(self) -> bool:
        return self.radius_mm is None or math.isinf(float(self.radius_mm))

    @property
    def curvature(self) -> float:
        return 0.0 if self.is_plane else 1.0 / float(self.radius_mm)
