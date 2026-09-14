from fastapi import APIRouter, Request

from backend.optical_ml_app.api.responses import failure, success
from backend.optical_ml_app.domain.errors import BackendApplicationError
from shared_contracts.prediction import PredictionRequest


router = APIRouter()


@router.get("/models")
def list_models(request: Request):
    return success(request, {"models": request.app.state.services["model_registry"].list_models()})


@router.post("/models/{model_id}/predict")
def predict(model_id: str, payload: PredictionRequest, request: Request):
    payload.model_id = model_id
    try:
        result = request.app.state.services["prediction_app"].predict(payload)
    except BackendApplicationError as exc:
        status_code = 404 if exc.code == "MODEL_NOT_FOUND" else 422
        return failure(request, status_code=status_code, **exc.to_dict())
    return success(request, result)
