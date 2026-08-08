from fastapi import APIRouter, Request

from backend.optical_ml_app.api.responses import success
from shared_contracts.prediction import PredictionRequest


router = APIRouter()


@router.get("/models")
def list_models(request: Request):
    return success(request, {"models": request.app.state.services["model_registry"].list_models()})


@router.post("/models/{model_id}/predict")
def predict(model_id: str, payload: PredictionRequest, request: Request):
    payload.model_id = model_id
    return success(request, request.app.state.services["prediction_app"].predict(payload))
