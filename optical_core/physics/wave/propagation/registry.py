
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class PropagationPlan:
    method: str
    distance_mm: float
    output_x_mm: np.ndarray | None = None
    output_y_mm: np.ndarray | None = None
    options: dict[str, Any] = field(default_factory=dict)


class PropagationStrategy(Protocol):
    name: str

    def propagate(self, field: ScalarField2D, plan: PropagationPlan) -> Any:
        ...


class PropagationStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, PropagationStrategy] = {}
        self._aliases: dict[str, str] = {}

    def register(self, strategy: PropagationStrategy, *, aliases: tuple[str, ...] = ()) -> None:
        name = str(strategy.name).strip().lower()
        if not name:
            raise ValueError("propagation strategy name cannot be empty")
        if name in self._strategies:
            raise KeyError(f"propagation strategy already registered: {name}")
        self._strategies[name] = strategy
        for alias in aliases:
            key = str(alias).strip().lower()
            if key in self._aliases or key in self._strategies:
                raise KeyError(f"propagation alias already registered: {key}")
            self._aliases[key] = name

    def resolve(self, name: str) -> PropagationStrategy:
        key = str(name or "").strip().lower().replace("-", "_")
        key = self._aliases.get(key, key)
        try:
            return self._strategies[key]
        except KeyError as exc:
            available = ", ".join(sorted(self._strategies))
            raise KeyError(f"unknown propagation method {name!r}; available: {available}") from exc

    def propagate(self, field: ScalarField2D, plan: PropagationPlan) -> Any:
        return self.resolve(plan.method).propagate(field, plan)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))


@dataclass(frozen=True, slots=True)
class _SimpleStrategy:
    name: str

    def propagate(self, field: ScalarField2D, plan: PropagationPlan) -> Any:
        if self.name == "angular_spectrum":
            from optical_core.physics.wave.solvers.angular_spectrum import (
                propagate_angular_spectrum_with_diagnostics,
            )
            return propagate_angular_spectrum_with_diagnostics(
                field,
                plan.distance_mm,
                zero_padding_factor=float(plan.options.get("zero_padding_factor", 1.0)),
                edge_power_threshold=float(plan.options.get("edge_power_threshold", 1.0e-4)),
                energy_closure_threshold=float(plan.options.get("energy_closure_threshold", 5.0e-3)),
                nyquist_margin_min=float(plan.options.get("nyquist_margin_min", 1.0)),
            )
        if self.name == "fresnel":
            from optical_core.physics.wave.solvers.fresnel import propagate_fresnel
            return propagate_fresnel(field, plan.distance_mm)
        if self.name == "fraunhofer":
            from optical_core.physics.wave.solvers.fraunhofer import propagate_fraunhofer
            return propagate_fraunhofer(field, plan.distance_mm, normalize=bool(plan.options.get("normalize", False)))
        raise KeyError(self.name)


@dataclass(frozen=True, slots=True)
class _AdvancedStrategy:
    name: str

    def propagate(self, field: ScalarField2D, plan: PropagationPlan) -> Any:
        from optical_core.physics.wave.solvers.advanced_propagation import propagate_complex_field
        return propagate_complex_field(
            field,
            plan.distance_mm,
            method=self.name,
            output_x_mm=plan.output_x_mm,
            output_y_mm=plan.output_y_mm,
            zero_padding_factor=float(plan.options.get("zero_padding_factor", 2.0)),
            edge_power_threshold=float(plan.options.get("edge_power_threshold", 1.0e-4)),
            energy_closure_threshold=float(plan.options.get("energy_closure_threshold", 5.0e-3)),
            nyquist_margin_min=float(plan.options.get("nyquist_margin_min", 1.0)),
            issc_oversampling_factor=float(plan.options.get("issc_oversampling_factor", 2.0)),
            issc_padding_factor=float(plan.options.get("issc_padding_factor", 2.0)),
            issc_max_virtual_grid=int(plan.options.get("issc_max_virtual_grid", 2049)),
            scaled_angular_spectrum_transfer_model=str(
                plan.options.get("scaled_angular_spectrum_transfer_model", "fresnel")
            ),
        )




@dataclass(frozen=True, slots=True)
class _MatrixFresnelStrategy:
    name: str = "matrix_fresnel"

    def propagate(self, field: ScalarField2D, plan: PropagationPlan) -> Any:
        if plan.output_x_mm is None or plan.output_y_mm is None:
            raise ValueError("matrix_fresnel requires explicit output axes")
        from optical_core.physics.wave.solvers.matrix_fresnel import propagate_matrix_fresnel
        return propagate_matrix_fresnel(
            field,
            plan.distance_mm,
            output_x_mm=plan.output_x_mm,
            output_y_mm=plan.output_y_mm,
            edge_power_threshold=float(plan.options.get("edge_power_threshold", 2.0e-3)),
            energy_closure_threshold=float(plan.options.get("energy_closure_threshold", 1.5e-2)),
        )

@lru_cache(maxsize=1)
def default_propagation_registry() -> PropagationStrategyRegistry:
    registry = PropagationStrategyRegistry()
    registry.register(_SimpleStrategy("angular_spectrum"), aliases=("asm",))
    registry.register(_SimpleStrategy("fresnel"))
    registry.register(_SimpleStrategy("fraunhofer"))
    registry.register(_MatrixFresnelStrategy())
    for name in (
        "band_limited_angular_spectrum",
        "scaled_angular_spectrum",
        "scaled_fresnel",
        "issc",
    ):
        registry.register(_AdvancedStrategy(name))
    return registry
