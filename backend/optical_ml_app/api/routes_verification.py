

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import success
from shared_contracts.project import ProjectSnapshot


router = APIRouter()


class VerificationCandidate(BaseModel):


    overrides: Dict[str, float] = Field(
        default_factory=dict,
        description="Dotted parameter paths and their values, "
        "e.g. ``{\"receiver.offset_x_mm\": 0.002}``",
    )


class VerificationJobRequest(BaseModel):


    request_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    project: ProjectSnapshot
    candidates: List[VerificationCandidate] = Field(
        default_factory=lambda: [VerificationCandidate()],
        description="One or more parameter sets to verify. "
        "If omitted a single baseline verification is run.",
    )


@router.post(
    "/verification/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit model-vs-simulation verification",
    description="For each candidate parameter set, runs both model prediction and "
    "headless optical simulation, returning per-target error metrics.",
)
def submit_verification(payload: VerificationJobRequest, request: Request):
    services = request.app.state.services
    service = services.get("verification_app")
    if service is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "SERVICE_UNAVAILABLE", "detail": "verification service not configured"},
        )

    parameter_sets = [c.overrides for c in payload.candidates]
    job_id = service.submit(
        model_id=payload.model_id,
        base_project=payload.project,
        parameter_sets=parameter_sets,
    )
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/verification/single",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Quick single-parameter verification",
    description="Convenience endpoint for verifying one parameter change.",
)
def submit_single_verification(payload: VerificationJobRequest, request: Request):
    services = request.app.state.services
    service = services.get("verification_app")
    if service is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"code": "SERVICE_UNAVAILABLE", "detail": "verification service not configured"},
        )

    overrides = payload.candidates[0].overrides if payload.candidates else {}
    job_id = service.submit_single(
        model_id=payload.model_id,
        base_project=payload.project,
        overrides=overrides,
    )
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
