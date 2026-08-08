

from __future__ import annotations

from fastapi import APIRouter, Request, status

from backend.optical_ml_app.api.responses import success
from backend.optical_ml_app.api.tolerance_models import ToleranceJobRequest
from shared_contracts.simulation import SimulationRequest
from shared_contracts.tolerance import ToleranceAnalysisRequest

router = APIRouter()


@router.post("/tolerance/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_tolerance(payload: ToleranceJobRequest, request: Request):

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

    tolerance_request = ToleranceAnalysisRequest(
        request_id=f"{payload.request_id}:tolerance",
        parameters=payload.tolerance_parameters,
        analyses=payload.analyses,
        sampling_method=payload.tolerance_sampling_method,
        sample_count=payload.tolerance_sample_count,
        random_seed=payload.random_seed,
        precision=payload.precision,
        threshold_efficiency=payload.tolerance_threshold_efficiency,
        threshold_loss_db=payload.tolerance_threshold_loss_db,
        confidence_level=payload.tolerance_confidence_level,
        correlation_matrix=payload.tolerance_correlation_matrix,
        options=payload.tolerance_options,
    )

    tolerance_service = services["tolerance_app"]
    job_id = tolerance_service.submit(base_request, tolerance_request)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
