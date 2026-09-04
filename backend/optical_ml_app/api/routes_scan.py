

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import success
from shared_contracts.parameters import ParameterChange
from shared_contracts.project import ProjectSnapshot
from shared_contracts.scan import ScanMode, ScanParameter, ScanRequest

router = APIRouter()


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


@router.post("/scan/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_scan(payload: ScanJobRequest, request: Request):

    services = request.app.state.services

    from shared_contracts.scan import ScanParameter, ScanRequest as ScanReq
    from shared_contracts.simulation import SimulationRequest

    scan_params = list(payload.scan_parameters)

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

    scan_request = ScanReq(
        request_id=f"{payload.request_id}:scan",
        mode=payload.scan_mode,  
        parameters=scan_params,
        response_metrics=payload.scan_response_metrics,
        analyses=payload.analyses,
        precision=payload.precision,  
        random_seed=payload.random_seed,
        options=payload.scan_options,
    )

    job_id = services["scan_app"].submit(base_request, scan_request)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
