

from __future__ import annotations

from typing import Any

from optical_runtime.system_tolerance import SystemToleranceRunner
from shared_contracts.simulation import SimulationRequest
from shared_contracts.tolerance import ToleranceAnalysisRequest, ToleranceAnalysisResult

from backend.optical_ml_app.application.ports import EngineResolverPort, TaskManagerPort


def _run_tolerance_task(
    context: Any,
    base_request: SimulationRequest,
    tolerance_request: ToleranceAnalysisRequest,
) -> Any:

    from optical_runtime import create_optical_simulation_engine

    engine = create_optical_simulation_engine()
    runner = SystemToleranceRunner(engine)

    if context.cancellation.is_cancelled:
        return ToleranceAnalysisResult(
            request_id=tolerance_request.request_id,
            status="cancelled",
            warnings=["tolerance job was cancelled before execution"],
            metadata={"stage": "tolerance.preflight"},
        )

    result = runner.run(
        base_request=base_request,
        request=tolerance_request,
    )

    context.progress.update(1.0, "tolerance.completed")
    return result


class ToleranceApplicationService:


    def __init__(
        self,
        task_manager: TaskManagerPort,
    ) -> None:
        self.task_manager = task_manager

    def submit(
        self,
        base_request: SimulationRequest,
        tolerance_request: ToleranceAnalysisRequest,
    ) -> str:
        return self.task_manager.submit(
            "tolerance",
            _run_tolerance_task,
            base_request,
            tolerance_request,
        )
