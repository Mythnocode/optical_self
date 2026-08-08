from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from shared_ports.simulation import SimulationPort


class TaskManagerPort(Protocol):
    def submit(
        self,
        job_type: str,
        function: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> str: ...


class EngineResolverPort(Protocol):
    def resolve(self, name: str | None) -> SimulationPort: ...


class SimulationEvaluatorPort(Protocol):
    def evaluate(
        self,
        request: Any,
        cancellation: Any = None,
        progress: Any = None,
    ) -> Any: ...


class DatasetRegistryPort(Protocol):
    def register(self, manifest: Any) -> Any: ...

    def validate_for_training(
        self,
        dataset_id: str,
        target_names: list[str],
    ) -> str: ...
