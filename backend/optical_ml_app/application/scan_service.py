

from __future__ import annotations

from typing import Any

import numpy as np

from shared_contracts.errors import ApplicationError
from shared_contracts.parameters import ParameterChange
from shared_contracts.scan import ScanRequest, ScanResult
from shared_contracts.simulation import SimulationRequest

from backend.optical_ml_app.application.ports import EngineResolverPort, TaskManagerPort
from backend.optical_ml_app.runtime_env import configured_batch_worker_count


def _build_sweep_points(request: ScanRequest) -> list[dict]:

    params = list(request.parameters or [])
    if not params:
        raise ValueError("扫描至少需要一个有效参数")
    spacing = np.geomspace if request.options.get('sampling_strategy') == 'log' else np.linspace

    if request.mode == "line_1d":
        param = params[0]
        xs = spacing(param.start, param.stop, param.points).tolist()
        return [{"paths": [param.path], "values": [float(x)]} for x in xs]

    if request.mode == "grid_2d":
        if len(params) < 2:
            raise ValueError("二维扫描至少需要两个有效参数")
        p0, p1 = params[:2]
        xs = spacing(p0.start, p0.stop, p0.points).tolist()
        ys = spacing(p1.start, p1.stop, p1.points).tolist()
        return [
            {"paths": [p0.path, p1.path], "values": [float(x), float(y)]}
            for x in xs
            for y in ys
        ]

    
    from scipy.stats import qmc

    d = len(params)
    n = min(50000, int(request.options.get("max_samples", 4096)))
    rng = np.random.default_rng(request.random_seed)

    if request.mode == "lhs":
        uniforms = qmc.LatinHypercube(d=d, seed=request.random_seed).random(n)
    elif request.mode == "sobol":
        sampler = qmc.Sobol(d=d, scramble=True, seed=request.random_seed)
        uniforms = sampler.random_base2(int(np.ceil(np.log2(max(n, 1)))))[:n]
    else:
        uniforms = rng.random((n, d))

    points = []
    for row in uniforms:
        values = []
        for col, param in enumerate(params):
            if request.options.get('sampling_strategy') == 'log':
                value = float(np.sign(param.start) * np.exp(np.log(abs(param.start)) + row[col] * (np.log(abs(param.stop)) - np.log(abs(param.start)))))
            else:
                value = float(param.start + row[col] * (param.stop - param.start))
            values.append(value)
        points.append({"paths": [p.path for p in params], "values": values})
    return points


def _run_scan_task(
    context: Any,
    base_request: SimulationRequest,
    scan_request: ScanRequest,
) -> ScanResult:

    from optical_runtime import create_optical_simulation_engine

    engine = context.get_or_create_resource(
        "optical_engine", create_optical_simulation_engine
    )

    sweep_points = _build_sweep_points(scan_request)
    total = len(sweep_points)

    if context.cancellation.is_cancelled:
        return ScanResult(
            request_id=scan_request.request_id,
            status="cancelled",
            mode=scan_request.mode,
        )

    simulation_requests = []
    for index, point in enumerate(sweep_points):
        sim_req = base_request.model_copy(
            deep=True,
            update={
                "request_id": f"{scan_request.request_id}:{index:06d}",
                "analyses": list(scan_request.analyses),
                "precision": scan_request.precision,
                "random_seed": scan_request.random_seed + index,
                "options": {**dict(base_request.options), **dict(scan_request.options)},
            },
        )
        for path, value in zip(point["paths"], point["values"]):
            sim_req.parameter_changes.append(
                ParameterChange(path=path, value=float(value))
            )
        simulation_requests.append(sim_req)

    context.progress.update(0.03, "scan.preparing", 0, total)

    response_values: dict[str, list[float]] = {
        metric: [] for metric in scan_request.response_metrics
    }
    parameter_grid: list[list[float]] = []
    failed = 0
    succeeded = 0
    failure_examples: list[dict] = []

    # A coupling SimulationResult can own multiple dense 2-D arrays. Holding
    # hundreds of complete results until the end of a long scan can therefore
    # grow a worker into multi-GB memory and let the OS kill it. The scan needs
    # only the requested scalar response metrics, so evaluate in small bounded
    # batches and immediately discard each full SimulationResult after extracting
    # its metrics. This changes orchestration/memory use only; every optical point
    # is still evaluated by the same engine with the same request.
    batch_workers = configured_batch_worker_count()
    chunk_size = max(1, min(total or 1, max(1, batch_workers) * 2))
    completed = 0
    for chunk_start in range(0, total, chunk_size):
        if context.cancellation.is_cancelled:
            break
        chunk_requests = simulation_requests[chunk_start:chunk_start + chunk_size]
        chunk_points = sweep_points[chunk_start:chunk_start + chunk_size]
        chunk_results = engine.batch_evaluate(
            chunk_requests,
            cancellation=context.cancellation,
            progress=None,
            max_workers=batch_workers,
        )
        for point, result in zip(chunk_points, chunk_results):
            if context.cancellation.is_cancelled:
                break
            parameter_grid.append(list(point["values"]))
            if result.status == "completed":
                succeeded += 1
            else:
                failed += 1
                if len(failure_examples) < 8:
                    failure_examples.append({'point': list(point['values']), 'errors': [error.model_dump(mode='python') for error in result.errors]})
            for metric in scan_request.response_metrics:
                value = result.metrics.get(metric)
                if isinstance(value, (int, float)):
                    response_values[metric].append(float(value))
                else:
                    response_values[metric].append(float("nan"))
            completed += 1
            if total:
                context.progress.update(
                    0.03 + 0.93 * completed / total,
                    "scan.batch.evaluate",
                    completed_items=completed,
                    total_items=total,
                )
        # Drop references to dense arrays before moving to the next chunk.
        del chunk_results
        # Prepared coupling problems cache receiver modes/evaluations to accelerate
        # repeated interactive calls.  During a sweep those entries are generally
        # one-shot values, and each may own a dense complex field.  Release that
        # transient cache after reducing the batch to scalar scan metrics while
        # deliberately preserving the engine's shared ray-trace cache.
        clear_prepared = getattr(engine, "clear_prepared_coupling_cache", None)
        if callable(clear_prepared):
            clear_prepared()

    evaluated = succeeded + failed
    warnings: list[str] = []
    if failed:
        warnings.append(f"{failed} of {evaluated} simulation(s) failed.")

    all_failed = bool(evaluated) and failed == evaluated
    errors: list[ApplicationError] = []
    if all_failed:
        errors.append(
            ApplicationError(
                code="SCAN_ALL_SIMULATIONS_FAILED",
                stage="scan.evaluate",
                message="参数扫描中的所有子仿真均失败，本次任务没有产生可作为正式结果使用的扫描数据。",
                retryable=False,
                context={
                    "total_points": evaluated,
                    "failed_points": failed,
                    "successful_points": succeeded,
                },
            )
        )

    context.progress.update(
        1.0,
        "scan.failed" if all_failed else "scan.completed",
        len(parameter_grid),
        total,
    )
    return ScanResult(
        request_id=scan_request.request_id,
        status=(
            "cancelled"
            if context.cancellation.is_cancelled
            else "failed"
            if all_failed
            else "completed"
        ),
        mode=scan_request.mode,
        parameter_paths=[p.path for p in scan_request.parameters],
        parameter_labels=[p.label or p.path for p in scan_request.parameters],
        parameter_units=[p.unit for p in scan_request.parameters],
        parameter_grid=parameter_grid,
        response_metrics=list(scan_request.response_metrics),
        response_values=response_values,
        warnings=warnings,
        errors=errors,
        metadata={
            "total_points": total,
            "completed_points": len(parameter_grid),
            "successful_points": succeeded,
            "failed_points": failed,
            "failure_examples": failure_examples,
        },
    )


class ScanApplicationService:


    def __init__(
        self,
        task_manager: TaskManagerPort,
    ) -> None:
        self.task_manager = task_manager

    def submit(
        self,
        base_request: SimulationRequest,
        scan_request: ScanRequest,
    ) -> str:
        return self.task_manager.submit(
            "scan",
            _run_scan_task,
            base_request,
            scan_request,
            idempotency_key=f"scan:{scan_request.request_id}",
        )
