
# 保存位置、方向、波长、复场振幅、功率权重、积分权重、光程、相位、偏振、有效状态及失效原因，可以自动归一化光线方向和偏振方向
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True, slots=True)
class Ray:


    position_mm: Tuple[float, float, float]
    direction: Tuple[float, float, float]
    wavelength_nm: float
    field_amplitude: float = 1.0
    power_weight: float | None = None
    quadrature_weight: float = 1.0
    optical_path_mm: float = 0.0
    valid: bool = True
    reason: str | None = None
    polarization_xyz: Tuple[complex, complex, complex] | None = None
    phase_offset_rad: float = 0.0

    def __post_init__(self) -> None:
        field_amplitude = float(self.field_amplitude)
        power_weight = field_amplitude**2 if self.power_weight is None else float(self.power_weight)
        quadrature_weight = float(self.quadrature_weight)
        if field_amplitude < 0.0:
            raise ValueError("field_amplitude must be non-negative")
        if power_weight < 0.0:
            raise ValueError("power_weight must be non-negative")
        if quadrature_weight < 0.0:
            raise ValueError("quadrature_weight must be non-negative")
        object.__setattr__(self, "position_mm", tuple(float(v) for v in self.position_mm))
        object.__setattr__(self, "direction", tuple(float(v) for v in self.direction))
        object.__setattr__(self, "wavelength_nm", float(self.wavelength_nm))
        object.__setattr__(self, "field_amplitude", field_amplitude)
        object.__setattr__(self, "power_weight", power_weight)
        object.__setattr__(self, "quadrature_weight", quadrature_weight)
        object.__setattr__(self, "optical_path_mm", float(self.optical_path_mm))
        object.__setattr__(self, "valid", bool(self.valid))
        phase = float(self.phase_offset_rad)
        if not np.isfinite(phase):
            raise ValueError("phase_offset_rad must be finite")
        object.__setattr__(self, "phase_offset_rad", phase)
        direction = np.asarray(self.direction, dtype=float)
        norm_direction = float(np.linalg.norm(direction))
        if not np.isfinite(norm_direction) or norm_direction <= 0.0:
            raise ValueError("direction must be finite and non-zero")
        direction = direction / norm_direction
        object.__setattr__(self, "direction", tuple(float(v) for v in direction))
        if self.polarization_xyz is None:
            reference = np.asarray([1.0, 0.0, 0.0], dtype=float)
            if abs(float(np.dot(reference, direction))) > 0.95:
                reference = np.asarray([0.0, 1.0, 0.0], dtype=float)
            polarization = reference - np.dot(reference, direction) * direction
            polarization = polarization.astype(np.complex128)
        else:
            polarization = np.asarray(self.polarization_xyz, dtype=np.complex128).reshape(-1)
            if polarization.shape != (3,) or not np.all(np.isfinite(polarization)):
                raise ValueError("polarization_xyz must contain three finite complex components")
            polarization = polarization - np.vdot(direction, polarization) * direction
        norm_pol = float(np.linalg.norm(polarization))
        if norm_pol <= 1.0e-15:
            raise ValueError("polarization_xyz must have a transverse non-zero component")
        polarization = polarization / norm_pol
        object.__setattr__(self, "polarization_xyz", tuple(complex(v) for v in polarization))
