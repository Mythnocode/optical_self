from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from backend.optical_ml_app.infrastructure.json_utils import to_jsonable


def request_id_for(request: Any) -> str | None:
    state = getattr(request, "state", None)
    return getattr(state, "request_id", None)


def success(
    request: Any,
    data: Any,
    *,
    status_code: int = 200,
    message: str = "success",
) -> JSONResponse:
    state = getattr(request, "state", None)
    if state is not None and isinstance(data, dict) and isinstance(data.get("job_id"), str):
        state.job_id = data["job_id"]
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "code": "OK",
                "message": message,
                "data": to_jsonable(data),
                "error": None,
                "request_id": request_id_for(request),
            }
        ),
    )


def failure(
    request: Any,
    *,
    status_code: int,
    code: str,
    stage: str,
    message: str,
    retryable: bool = False,
    context: dict[str, Any] | None = None,
) -> JSONResponse:
    error = {
        "code": code,
        "stage": stage,
        "message": message,
        "retryable": retryable,
        "context": context or {},
    }
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "code": code,
                "message": message,
                "data": None,
                "error": error,
                "request_id": request_id_for(request),
            }
        ),
    )
