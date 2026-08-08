
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from optical_core.models.representations.ray import Ray


@dataclass(slots=True)
class RayNode:
    node_id: str
    parent_id: str | None
    ray: Ray
    next_surface_index: int
    propagation_sign: int
    interaction_count: int = 0
    reflection_count: int = 0
    surface_sequence: tuple[int, ...] = ()
    path_signature: str = ""
    termination_reason: str | None = None
    detector_position_mm: tuple[float, float, float] | None = None
    detector_direction: tuple[float, float, float] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def power(self) -> float:
        return float(self.ray.power_weight)


@dataclass(frozen=True, slots=True)
class RayTreeOptions:
    min_power_fraction: float = 1.0e-8
    max_interactions: int = 20
    max_reflections: int = 6
    max_nodes: int = 100_000
    russian_roulette: bool = False
    roulette_threshold_fraction: float = 1.0e-5
    random_seed: int = 0
    detector_z_mm: float | None = None
    include_diffraction_orders: bool = True
    environment_temperature_c: float = 20.0


@dataclass(slots=True)
class RayTreeResult:
    root_power: float
    nodes: list[RayNode]
    detector_nodes: list[RayNode]
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["RayNode", "RayTreeOptions", "RayTreeResult"]
