import logging
import math

from fastapi import Request
from fastapi.exceptions import RequestValidationError

from backend.optical_ml_app.api.responses import failure


logger = logging.getLogger(__name__)


def _validation_json(value):
    """Keep invalid nonfinite inputs and validator exceptions JSON serializable."""
    if isinstance(value, dict):
        return {key: _validation_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_validation_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return failure(
        request,
        status_code=422,
        code="INVALID_REQUEST",
        stage="api.validation",
        message="request parameters are invalid",
        context={"errors": _validation_json(exc.errors())},
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "unhandled API exception",
        extra={
            "event": "api_unhandled_exception",
            "stage": "api",
            "error_code": "INTERNAL_ERROR",
        },
    )
    return failure(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        stage="api",
        message="internal server error",
    )
