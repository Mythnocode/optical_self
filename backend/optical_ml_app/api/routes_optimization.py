

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Query, status
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import success, failure
from shared_contracts.optimization import (
    OptimizationObjective,
    OptimizationRequest,
    OptimizationVariable,
)
from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot
from shared_contracts.simulation import SimulationRequest

router = APIRouter()


@router.get('/optimization/jobs/{job_id}/presentation')
def read_optimization_result_presentation(job_id: str, request: Request, chart: str = Query(default='过程曲线', pattern='^(过程曲线|候选对照)$'), width: int = Query(default=900,ge=160,le=4096), height: int = Query(default=400,ge=100,le=4096)):
    from backend.optical_ml_app.application.optimization_results import result_presentation
    try:
        result = request.app.state.services['task_manager'].get_result(job_id)
        return success(request, result_presentation(result,chart,width,height))
    except FileNotFoundError:
        return failure(request,status_code=404,code='JOB_NOT_FOUND',stage='optimization.presentation',message='未找到任务')
    except RuntimeError as exc:
        return failure(request,status_code=409,code='JOB_RESULT_NOT_AVAILABLE',stage='optimization.presentation',message=str(exc))


class OptimizationPrepareRequest(BaseModel):
    simulation: SimulationRequest
    config: Dict[str, Any] = Field(default_factory=dict)
    variables: List[Dict[str, Any]] = Field(default_factory=list, max_length=256)


@router.post('/optimization/presentation')
def read_optimization_presentation(payload: ProjectSnapshot, request: Request):
    from backend.optical_ml_app.application.optimization_presentation import optimization_presentation
    try:
        return success(request, optimization_presentation(payload.model_dump(mode='python')))
    except (ValueError, TypeError, KeyError) as exc:
        return failure(request, status_code=422, code='OPTIMIZATION_PROJECT_INVALID', stage='optimization.presentation', message=str(exc))


@router.post('/optimization/prepare')
def prepare_optimization(payload: OptimizationPrepareRequest, request: Request):
    from backend.optical_ml_app.application.optimization_presentation import optimization_payload
    try:
        prepared = optimization_payload(payload.simulation.model_dump(mode='python', exclude_unset=True), payload.config, payload.variables)
        OptimizationJobRequest.model_validate(prepared)
        return success(request, prepared)
    except (ValueError, TypeError, KeyError) as exc:
        return failure(request, status_code=422, code='OPTIMIZATION_PARAMETERS_INVALID', stage='optimization.prepare', message=str(exc))


class OptimizationJobRequest(BaseModel):


    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    project: ProjectSnapshot
    analyses: List[str] = Field(default_factory=lambda: ["coupling"])
    parameter_changes: List[ParameterChange] = Field(default_factory=list)
    precision: str = "standard"
    random_seed: int = 42
    engine: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)

    
    opt_optimizer: str = "auto"
    opt_variables: List[Dict[str, Any]] = Field(default_factory=list)
    opt_objectives: List[Dict[str, Any]] = Field(default_factory=list)
    opt_constraints: List[Dict[str, Any]] = Field(default_factory=list)
    opt_max_iterations: int = Field(default=100, ge=1, le=5000)
    opt_max_evaluations: Optional[int] = Field(default=None, ge=1)
    opt_convergence_tolerance: float = Field(default=1e-4, gt=0.0)
    opt_options: Dict[str, Any] = Field(default_factory=dict)


@router.post("/optimization/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_optimization(payload: OptimizationJobRequest, request: Request):

    services = request.app.state.services

    variables = [
        OptimizationVariable(
            path=v.get("path", ""),
            label=v.get("label", ""),
            unit=v.get("unit", ""),
            lower_bound=v.get("lower_bound", 0.0),
            upper_bound=v.get("upper_bound", 1.0),
            initial_value=v.get("initial_value", 0.5),
            enabled=v.get("enabled", True),
        )
        for v in payload.opt_variables
    ]

    objectives = [
        OptimizationObjective(
            metric=obj.get("metric", "coupling_efficiency"),
            weight=obj.get("weight", 1.0),
            goal=obj.get("goal", "maximize"),
            target_value=obj.get("target_value"),
        )
        for obj in payload.opt_objectives
    ] or [OptimizationObjective(metric="coupling_efficiency", goal="maximize")]

    base_request = SimulationRequest(
        request_id=payload.request_id,
        project=payload.project,
        analyses=payload.analyses,
        parameter_changes=payload.parameter_changes,
        precision=payload.precision,  
        random_seed=payload.random_seed,
        engine=payload.engine,
        options=payload.options,
    )

    opt_request = OptimizationRequest(
        request_id=f"{payload.request_id}:opt",
        optimizer=payload.opt_optimizer,  
        variables=variables,
        objectives=objectives,
        constraints=payload.opt_constraints,
        analyses=payload.analyses,
        precision=payload.precision,  
        random_seed=payload.random_seed,
        max_iterations=payload.opt_max_iterations,
        max_evaluations=payload.opt_max_evaluations,
        convergence_tolerance=payload.opt_convergence_tolerance,
        options=payload.opt_options,
    )

    job_id = services["optimization_app"].submit(base_request, opt_request)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
