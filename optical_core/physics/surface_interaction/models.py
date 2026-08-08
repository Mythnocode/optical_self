
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.ray import Ray


@dataclass(frozen=True, slots=True)
class CoatingAmplitudeResult:


    rs: complex
    rp: complex
    ts: complex
    tp: complex
    Rs: float
    Rp: float
    Ts: float
    Tp: float
    absorption_s: float
    absorption_p: float
    incident_angle_rad: float
    transmitted_angle_rad: complex | None
    total_internal_reflection: bool
    group_delay_reflection_s: float = 0.0
    group_delay_reflection_p: float = 0.0
    group_delay_transmission_s: float = 0.0
    group_delay_transmission_p: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def energy_error_s(self) -> float:
        return float(abs(self.Rs + self.Ts + self.absorption_s - 1.0))

    @property
    def energy_error_p(self) -> float:
        return float(abs(self.Rp + self.Tp + self.absorption_p - 1.0))


@dataclass(frozen=True, slots=True)
class SurfaceInteractionResult:


    transmitted_ray: Ray | None
    reflected_ray: Ray | None
    transmission_jones: np.ndarray
    reflection_jones: np.ndarray
    transmitted_power: float
    reflected_power: float
    absorbed_power: float
    phase_delay_rad: float
    incident_angle_rad: float
    total_internal_reflection: bool
    diffraction_rays: tuple[Ray, ...] = ()
    diffraction_orders: tuple[int, ...] = ()
    energy_error: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)


__all__ = ["CoatingAmplitudeResult", "SurfaceInteractionResult"]
