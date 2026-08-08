

from __future__ import annotations

from typing import Any

import numpy as np

from shared_contracts.parameters import ParameterChange
from shared_contracts.scan import ScanRequest, ScanResult
from shared_contracts.simulation import SimulationRequest

from backend.optical_ml_app.application.ports import EngineResolverPort, TaskManagerPort


def _build_sweep_points(request: ScanRequest) -> list[dict]:

    params = list(request.parameters or [])
    if not params:
        raise ValueError("扫描至少需要一个有效参数")

    if request.mode == "line_1d":
        param = params[0]
        xs = np.linspace(param.start, param.stop, param.points).tolist()
        return [{"paths": [param.path], "values": [float(x)]} for x in xs]

    if request.mode == "grid_2d":
        if len(params) < 2:
            raise ValueError("二维扫描至少需要两个有效参数")
        p0, p1 = params[:2]
        xs = np.linspace(p0.start, p0.stop, p0.points).tolist()
        ys = np.linspace(p1.start, p1.stop, p1.points).tolist()
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

    engine = create_optical_simulation_engine()

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

    results = engine.batch_evaluate(simulation_requests)

    response_values: dict[str, list[float]] = {
        metric: [] for metric in scan_request.response_metrics
    }
    parameter_grid: list[list[float]] = []

    for index, (point, result) in enumerate(zip(sweep_points, results)):
        if context.cancellation.is_cancelled:
            break
        parameter_grid.append(list(point["values"]))
        for metric in scan_request.response_metrics:
            value = result.metrics.get(metric)
            if isinstance(value, (int, float)):
                response_values[metric].append(float(value))
            else:
                response_values[metric].append(float("nan"))

        if total > 1:
            context.progress.update(
                (index + 1) / total,
                f"scan.{scan_request.mode}",
                completed_items=index + 1,
                total_items=total,
            )

    warnings: list[str] = []
    failed = sum(1 for r in results if r.status != "completed")
    if failed:
        warnings.append(f"{failed} of {len(results)} simulation(s) failed.")

    return ScanResult(
        request_id=scan_request.request_id,
        status="completed" if not context.cancellation.is_cancelled else "cancelled",
        mode=scan_request.mode,
        parameter_paths=[p.path for p in scan_request.parameters],
        parameter_labels=[p.label or p.path for p in scan_request.parameters],
        parameter_units=[p.unit for p in scan_request.parameters],
        parameter_grid=parameter_grid,
        response_metrics=list(scan_request.response_metrics),
        response_values=response_values,
        warnings=warnings,
        metadata={
            "total_points": total,
            "completed_points": len(parameter_grid),
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
        )
