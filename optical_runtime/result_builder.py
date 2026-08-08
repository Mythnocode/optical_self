from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from shared_contracts.errors import ApplicationError
from shared_contracts.simulation import SimulationResult


def _to_application_error(
    item: Any,
    *,
    default_stage: str,
) -> ApplicationError:
    if isinstance(item, ApplicationError):
        return item

    if isinstance(item, dict):
        return ApplicationError(
            code=str(item.get("code", "OPTICAL_ENGINE_ERROR")),
            stage=str(item.get("stage", default_stage)),
            message=str(item.get("message", item)),
            retryable=bool(item.get("retryable", False)),
            trace_id=item.get("trace_id"),
            context=dict(item.get("context", {}) or {}),
        )

    return ApplicationError(
        code="OPTICAL_ENGINE_ERROR",
        stage=default_stage,
        message=str(item),
        retryable=False,
        context={},
    )


def _normalize_errors(
    errors: list[Any],
    *,
    default_stage: str,
) -> list[ApplicationError]:
    return [
        _to_application_error(item, default_stage=default_stage)
        for item in errors
    ]


def build_completed_result(
    *,
    request: Any,
    engine_name: str,
    engine_version: str,
    algorithm_version: str,
    started_at: float,
    partial: Any,
) -> SimulationResult:
    project = getattr(request, "project", None)

    return SimulationResult(
        request_id=str(getattr(request, "request_id", "unknown")),
        project_fingerprint=_project_fingerprint(request, project),
        engine_name=engine_name,
        engine_version=engine_version,
        algorithm_version=algorithm_version,
        status="completed",
        metrics=dict(partial.metrics),
        arrays=dict(partial.arrays),
        warnings=list(partial.warnings),
        errors=_normalize_errors(
            list(getattr(partial, "errors", []) or []),
            default_stage="optical_runtime",
        ),
        elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
        converged=bool(partial.converged),
        metadata={
            **dict(partial.metadata),
            "source_core": "modular_optical_core",
            "runtime_chain": "optical_runtime_to_optical_core_physics",
            "not_physical_result": False,
        },
    )


def build_failed_result(
    *,
    request: Any,
    engine_name: str,
    engine_version: str,
    algorithm_version: str,
    started_at: float,
    error: Exception,
) -> SimulationResult:
    project = getattr(request, "project", None)

    app_error = _error_from_exception(error)

    return SimulationResult(
        request_id=str(getattr(request, "request_id", "unknown")),
        project_fingerprint=_project_fingerprint(request, project),
        engine_name=engine_name,
        engine_version=engine_version,
        algorithm_version=algorithm_version,
        status="failed",
        metrics={},
        arrays={},
        warnings=[],
        errors=[app_error],
        elapsed_ms=(time.perf_counter() - started_at) * 1000.0,
        converged=False,
        metadata={
            "source_core": "modular_optical_core",
            "runtime_chain": "optical_runtime_to_optical_core_physics",
            "not_physical_result": False,
            "error_type": type(error).__name__,
        },
    )


def _error_from_exception(error: Exception) -> ApplicationError:
    context = dict(getattr(error, "context", {}) or {})
    context.setdefault("error_type", type(error).__name__)

    return ApplicationError(
        code=str(getattr(error, "code", "OPTICAL_ENGINE_ERROR")),
        stage=str(getattr(error, "stage", "optical_runtime")),
        message=str(error),
        retryable=bool(getattr(error, "retryable", False)),
        trace_id=getattr(error, "trace_id", None),
        context=context,
    )


def _project_fingerprint(request: Any, project: Any) -> str:
    fingerprint = getattr(project, "fingerprint", None)
    if fingerprint:
        return str(fingerprint)

    paths = getattr(request, "paths", None)
    if not paths:
        return "unknown"

    path_fingerprints: list[dict[str, str]] = []
    for index, path in enumerate(paths):
        path_id = str(getattr(path, "path_id", f"path_{index + 1}"))
        path_project = getattr(path, "project", None)
        path_system = getattr(path, "system", None)
        value = getattr(path_project, "fingerprint", None)
        if value is None and isinstance(path_system, dict):
            value = path_system.get("fingerprint")
        path_fingerprints.append({"path_id": path_id, "fingerprint": str(value or "")})

    encoded = json.dumps(path_fingerprints, ensure_ascii=True, sort_keys=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"multipath:{digest}"
