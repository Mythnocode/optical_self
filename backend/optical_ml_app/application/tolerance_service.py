

from __future__ import annotations

from typing import Any

from optical_runtime.system_tolerance import SystemToleranceRunner
from shared_contracts.simulation import SimulationRequest
from shared_contracts.tolerance import ToleranceAnalysisRequest, ToleranceAnalysisResult

from backend.optical_ml_app.application.ports import EngineResolverPort, TaskManagerPort
from backend.optical_ml_app.jobs.progress import ScaledProgressReporter
from backend.optical_ml_app.runtime_env import configured_batch_worker_count


def _run_tolerance_task(
    context: Any,
    base_request: SimulationRequest,
    tolerance_request: ToleranceAnalysisRequest,
) -> Any:

    from optical_runtime import create_optical_simulation_engine

    engine = context.get_or_create_resource(
        "optical_engine", create_optical_simulation_engine
    )
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
        max_workers=configured_batch_worker_count(),
        progress=ScaledProgressReporter(
            context.progress, 0.03, 0.99, stage_prefix="tolerance"
        ),
        cancellation=context.cancellation,
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
            idempotency_key=f"tolerance:{tolerance_request.request_id}",
        )
