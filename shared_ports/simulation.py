from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from shared_contracts.simulation import SimulationRequest, SimulationResult
from shared_ports.progress import CancellationTokenPort, ProgressReporterPort


@runtime_checkable
class SimulationPort(Protocol):


    def evaluate(
        self,
        request: SimulationRequest,
        cancellation: CancellationTokenPort | None = None,
        progress: ProgressReporterPort | None = None,
    ) -> SimulationResult: ...

    def batch_evaluate(
        self,
        requests: Sequence[SimulationRequest],
        cancellation: CancellationTokenPort | None = None,
        progress: ProgressReporterPort | None = None,
    ) -> Sequence[SimulationResult]: ...
