from fastapi import APIRouter, Body, Request, status

from backend.optical_ml_app.api.multipath_models import MultiPathSimulationRequest
from backend.optical_ml_app.api.responses import success
from shared_contracts.simulation import SimulationRequest


router = APIRouter()


@router.post("/simulation/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_simulation(payload: SimulationRequest, request: Request):
    job_id = request.app.state.services["simulation_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/simulation/multipath/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_multi_path_simulation(payload: MultiPathSimulationRequest, request: Request):
    job_id = request.app.state.services["simulation_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/simulation/surrogate-preview")
def surrogate_preview(request: Request, payload: dict = Body(...)):
    result = dict(request.app.state.services["surrogate_preview_app"].preview(payload))
    result["request_id"] = str(payload.get("request_id", "") or "")
    return success(request, result)
