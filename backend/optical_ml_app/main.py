import logging
import threading
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware

from backend.optical_ml_app.api import (
    routes_datasets,
    routes_health,
    routes_headless_datasets,
    routes_jobs,
    routes_model_extensions,
    routes_models,
    routes_optimization,
    routes_scan,
    routes_simulation,
    routes_structure_models,
    routes_tolerance,
    routes_training,
    routes_verification,
    routes_validation,
    routes_ws,
)
from backend.optical_ml_app.api.error_handlers import (
    unhandled_exception_handler,
    validation_exception_handler,
)
from backend.optical_ml_app.bootstrap import create_services
from backend.optical_ml_app.infrastructure.log_context import log_context
from shared_contracts.versions import APP_VERSION


def create_app() -> FastAPI:
    services_dict = create_services()
    owned_task_manager = services_dict.get("task_manager")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current_services = getattr(app.state, "services", {})
        current_manager = (
            current_services.get("task_manager")
            if isinstance(current_services, dict)
            else None
        )
        start_workers = getattr(current_manager, "start_persistent_workers", None)
        if callable(start_workers):
            # Do not block API readiness on worker construction.  Jobs can be
            # queued immediately while the persistent simulation worker warms
            # in the background; this removes the several-second blank startup
            # pause without changing any numerical calculation.
            start_workers(
                wait_ready=False,
                ready_job_types={"simulation"},
            )

        def _background_ml_prewarm() -> None:
            try:
                # Import-only warmup.  No model/data result is precomputed here;
                # it simply removes first-use import latency from prediction and
                # explainability routes.
                import numpy  # noqa: F401
                import sklearn  # noqa: F401
                try:
                    import xgboost  # noqa: F401
                except Exception:
                    pass
                try:
                    import shap  # noqa: F401
                except Exception:
                    pass
            except Exception:
                logging.getLogger(__name__).debug(
                    "background ML import warmup skipped", exc_info=True
                )

        threading.Thread(
            target=_background_ml_prewarm,
            name="backend-ml-import-warmup",
            daemon=True,
        ).start()
        try:
            yield
        finally:
            
            
            
            managers = []
            current_services = getattr(app.state, "services", {})
            if isinstance(current_services, dict):
                managers.append(current_services.get("task_manager"))
            managers.append(owned_task_manager)

            seen: set[int] = set()
            for manager in managers:
                if manager is None or id(manager) in seen:
                    continue
                seen.add(id(manager))
                shutdown = getattr(manager, "shutdown", None)
                if callable(shutdown):
                    shutdown(wait=True)

    app = FastAPI(
        title="Optical ML Platform API",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.services = services_dict
    app.state.event_bus = services_dict["event_bus"]
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    @app.middleware("http")
    async def attach_request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex}"
        request.state.request_id = request_id
        with log_context(request_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    for router in (
        routes_health.router,
        routes_simulation.router,
        routes_jobs.router,
        routes_datasets.router,
        routes_headless_datasets.router,
        routes_training.router,
        routes_models.router,
        routes_model_extensions.router,
        routes_structure_models.router,
        routes_tolerance.router,
        routes_scan.router,
        routes_optimization.router,
        routes_verification.router,
        routes_validation.router,
    ):
        app.include_router(router, prefix="/api/v1")

    app.include_router(routes_ws.router)

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
