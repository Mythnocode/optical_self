

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import failure, success
from backend.optical_ml_app.domain.errors import BackendApplicationError

router = APIRouter()


class ShapExplainRequest(BaseModel):
    dataset_id: str | None = None
    features: dict[str, float] | None = None
    target_name: str | None = None
    target_names: list[str] = Field(default_factory=list)
    sample_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=100)
    max_samples: int = Field(default=100, ge=1, le=1000)
    background_sample_count: int = Field(default=100, ge=1, le=2000)
    random_seed: int = 42


def _get_ext(request: Request) -> Any:
    ext = request.app.state.services.get("model_extension_app")
    if ext is None:
        return None
    return ext


@router.post("/models/{model_id}/shap/explain")
def shap_explain(model_id: str, payload: ShapExplainRequest, request: Request):

    ext = _get_ext(request)
    if ext is None:
        return failure(request, status_code=501, code="MODEL_EXTENSION_NOT_CONFIGURED",
                       stage="model.shap", message="model extension service not configured")

    try:
        result = ext.explain_shap(model_id, payload)
    except BackendApplicationError as exc:
        status_code = 501 if exc.code == "SHAP_BACKEND_NOT_CONFIGURED" else 422
        return failure(request, status_code=status_code, **exc.to_dict())
    return success(request, result)
