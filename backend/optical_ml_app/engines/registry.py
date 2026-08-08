from __future__ import annotations

from typing import Any

from optical_runtime import DEFAULT_ANALYSIS_REGISTRY, create_optical_simulation_engine
from shared_ports.simulation import SimulationPort


class EngineUnavailableError(RuntimeError):
    pass


SUPPORTED_ANALYSES: tuple[str, ...] = DEFAULT_ANALYSIS_REGISTRY.public_names()


class EngineRegistry:


    def __init__(self, settings: Any):
        self.settings = settings
        self._engines: dict[str, SimulationPort] = {
            "headless": create_optical_simulation_engine(),
        }

    def resolve(self, requested: str | None = None) -> SimulationPort:
        name = (requested or "headless").strip().lower()
        if name not in self._engines:
            raise EngineUnavailableError(f"引擎不可用: {name}")
        return self._engines[name]

    def capabilities(self) -> dict[str, dict[str, Any]]:
        return {
            "headless": {
                "enabled": True,
                "availability": "available",
                "engine_class": "optical_runtime.OpticalSimulationEngine",
                "source_runtime": "optical_runtime",
                "source_core": "modular_optical_core",
                "legacy_runtime": False,
                "uses_optical_core_headless": False,
                "uses_legacy_v8116": False,
                "analyses": SUPPORTED_ANALYSES,
            },
        }
