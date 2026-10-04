

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Query, status
from pydantic import BaseModel, Field, model_validator

from backend.optical_ml_app.api.responses import success, failure
from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot
from shared_contracts.scan import ScanMode, ScanParameter, ScanRequest
from shared_contracts.simulation import SimulationRequest

router = APIRouter()


@router.get('/scan/jobs/{job_id}/presentation')
def read_scan_result_presentation(job_id: str, request: Request, width: int = Query(default=900,ge=160,le=4096), height: int = Query(default=400,ge=100,le=4096)):
    from backend.optical_ml_app.application.scan_results import result_presentation
    try:
        result = request.app.state.services['task_manager'].get_result(job_id)
        return success(request, result_presentation(result,width,height))
    except FileNotFoundError:
        return failure(request,status_code=404,code='JOB_NOT_FOUND',stage='scan.presentation',message='未找到任务')
    except RuntimeError as exc:
        return failure(request,status_code=409,code='JOB_RESULT_NOT_AVAILABLE',stage='scan.presentation',message=str(exc))


class ScanPrepareRequest(BaseModel):
    simulation: SimulationRequest
    config: Dict[str, Any] = Field(default_factory=dict)
    variables: List[Dict[str, Any]] = Field(default_factory=list,max_length=2)


@router.post('/scan/prepare')
def prepare_scan(payload: ScanPrepareRequest, request: Request):
    from backend.optical_ml_app.application.scan_presentation import scan_payload
    try:
        prepared = scan_payload(payload.simulation.model_dump(mode='python',exclude_unset=True),payload.config,payload.variables)
        ScanJobRequest.model_validate(prepared)
        return success(request,prepared)
    except (ValueError,TypeError,KeyError) as exc:
        return failure(request,status_code=422,code='SCAN_PARAMETERS_INVALID',stage='scan.prepare',message=str(exc))


class ScanJobRequest(BaseModel):


    schema_version: str = "1.0"
    request_id: str = Field(min_length=1)
    project: ProjectSnapshot
    analyses: List[str] = Field(default_factory=lambda: ["coupling"])
    parameter_changes: List[ParameterChange] = Field(default_factory=list)
    precision: str = "standard"
    random_seed: int = 42
    engine: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)

    
    scan_mode: ScanMode = "line_1d"
    scan_parameters: List[ScanParameter] = Field(default_factory=list, min_length=1, max_length=8)
    scan_response_metrics: List[str] = Field(
        default_factory=lambda: ["coupling_efficiency"]
    )
    scan_options: Dict[str, Any] = Field(default_factory=dict)
    scan_sampling_strategy: str = 'linear'

    @model_validator(mode='after')
    def validate_scan(self):
        self.to_scan_request()
        return self

    def to_scan_request(self) -> ScanRequest:
        strategy = self.scan_sampling_strategy if 'scan_sampling_strategy' in self.model_fields_set else self.scan_options.get('sampling_strategy','linear')
        return ScanRequest(request_id=f'{self.request_id}:scan',mode=self.scan_mode,parameters=self.scan_parameters,response_metrics=self.scan_response_metrics,analyses=self.analyses,precision=self.precision,random_seed=self.random_seed,options={**self.scan_options,'sampling_strategy':strategy})


@router.post("/scan/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_scan(payload: ScanJobRequest, request: Request):

    services = request.app.state.services

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

    scan_request = payload.to_scan_request()

    job_id = services["scan_app"].submit(base_request, scan_request)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
