from fastapi import APIRouter, Request

from backend.optical_ml_app.api.responses import failure, success
from backend.optical_ml_app.domain.errors import BackendApplicationError
from shared_contracts.prediction import PredictionRequest
from shared_contracts.project import ProjectSnapshot
from pydantic import BaseModel, Field


router = APIRouter()


class ProjectFeaturesRequest(BaseModel):
    project: ProjectSnapshot
    feature_paths: list[str] = Field(min_length=1, max_length=256)


@router.post("/models/project-features")
def read_project_features(payload: ProjectFeaturesRequest, request: Request):
    from backend.optical_ml_app.application.project_features import project_features
    try:
        features = project_features(payload.project, payload.feature_paths)
    except (TypeError, ValueError) as exc:
        return failure(request, status_code=422, code="MODEL_FEATURE_MISSING", stage="model.project_features", message=str(exc))
    return success(request, {"features": features})


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
