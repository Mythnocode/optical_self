import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError

from backend.optical_ml_app.api.responses import failure


logger = logging.getLogger(__name__)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return failure(
        request,
        status_code=422,
        code="INVALID_REQUEST",
        stage="api.validation",
        message="request parameters are invalid",
        context={"errors": exc.errors()},
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
