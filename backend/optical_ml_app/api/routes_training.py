from fastapi import APIRouter, Request, status

from backend.optical_ml_app.api.responses import success
from shared_contracts.training import TrainingRequest


router = APIRouter()


@router.post("/training/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_training(payload: TrainingRequest, request: Request):
    job_id = request.app.state.services["training_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
