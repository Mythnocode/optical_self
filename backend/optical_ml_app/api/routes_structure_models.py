
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import success

router = APIRouter()


class BiLSTMTrainingConfig(BaseModel):
    embedding_dim: int = Field(default=16, ge=2, le=256)
    hidden_dim: int = Field(default=64, ge=8, le=512)
    num_layers: int = Field(default=2, ge=1, le=6)
    dropout: float = Field(default=0.15, ge=0.0, lt=1.0)
    learning_rate: float = Field(default=1e-3, gt=0.0)
    weight_decay: float = Field(default=1e-4, ge=0.0)
    batch_size: int = Field(default=32, ge=1, le=1024)
    max_epochs: int = Field(default=200, ge=1, le=5000)
    patience: int = Field(default=20, ge=1, le=500)
    random_seed: int = 42


class BiLSTMTrainRequest(BaseModel):
    dataset_path: str
    system_id_column: str = "system_id"
    order_column: str = "element_index"
    element_type_column: str = "element_type"
    numeric_feature_columns: list[str] = Field(min_length=1)
    target_columns: list[str] = Field(min_length=1)
    config: BiLSTMTrainingConfig = Field(default_factory=BiLSTMTrainingConfig)


class BiLSTMPredictRequest(BaseModel):
    element_types: list[str] = Field(min_length=1)
    numeric_values: list[list[float]] = Field(min_length=1)


@router.post("/structure-models/bilstm/jobs", status_code=status.HTTP_202_ACCEPTED)
def submit_bilstm_training(payload: BiLSTMTrainRequest, request: Request):
    job_id = request.app.state.services["structure_model_app"].submit_training(
        payload.model_dump()
    )
    return success(request, {"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)


@router.post("/structure-models/{model_id}/predict")
def predict_bilstm_structure(
    model_id: str,
    payload: BiLSTMPredictRequest,
    request: Request,
):
    result = request.app.state.services["structure_model_app"].predict(
        model_id,
        payload.model_dump(),
    )
    return success(request, result)
