from fastapi import APIRouter, Request, status

from backend.optical_ml_app.api.responses import success
from backend.optical_ml_app.api.responses import failure
from backend.optical_ml_app.application.training_service import TrainingPreflightError
from shared_contracts.training import JointTrainingRequest, TrainingRequest


router = APIRouter()


@router.post("/training/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_training(payload: TrainingRequest, request: Request):
    job_id = request.app.state.services["training_app"].submit(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/training/joint/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_joint_training(payload: JointTrainingRequest, request: Request):
    try:
        job_id = request.app.state.services["training_app"].submit_joint(payload)
    except TrainingPreflightError as exc:
        return failure(
            request,
            status_code=409,
            code="TRAINING_PREFLIGHT_FAILED",
            stage="training.preflight",
            message=str(exc),
            retryable=False,
        )
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
