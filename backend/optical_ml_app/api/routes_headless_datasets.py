from fastapi import APIRouter, Request, status

from backend.optical_ml_app.api.responses import success


router = APIRouter()


@router.post("/headless-datasets/coupling/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_headless_coupling_dataset(payload: dict, request: Request):
    job_id = request.app.state.services["headless_dataset_app"].submit_coupling_dataset(payload)
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)
