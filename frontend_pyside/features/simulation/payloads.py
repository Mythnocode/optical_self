
from __future__ import annotations

from typing import Any
from uuid import uuid4

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState


def build_simulation_payload(
    project: Any,
    state: SimulationFormState,
    *,
    request_id: str | None = None,
    random_seed: int = 42,
) -> dict[str, Any]:
    project_payload = serialize_project(project, state)
    return {
        "request_id": request_id or f"sim-{uuid4().hex[:8]}",
        "project": project_payload,
        "analyses": list(state.calculation.analyses),
        "precision": state.calculation.precision,
        "random_seed": int(random_seed),
        "options": state.request_options(),
    }


def build_multipath_payload(
    project: Any,
    state: SimulationFormState,
    *,
    request_id: str | None = None,
    random_seed: int = 42,
) -> dict[str, Any]:
    project_payload = serialize_project(project, state)
    analyses = list(state.calculation.analyses)
    options = state.request_options()
    return {
        "request_id": request_id or f"multipath-{uuid4().hex[:8]}",
        "simulation_type": "multi_path",
        "paths": [
            {
                "path_id": "path_1",
                "label": "当前光学路径",
                "weight": 1.0,
                "project": project_payload,
                "analyses": analyses,
                "precision": state.calculation.precision,
                "options": options,
                "include_large_arrays": state.calculation.save_large_arrays,
            }
        ],
        "analyses": analyses,
        "precision": state.calculation.precision,
        "random_seed": int(random_seed),
        "options": options,
    }


def restrict_payload(payload: dict[str, Any], analyses) -> dict[str, Any]:
    """Restrict a simulation payload to a selected analysis subset."""
    names = sorted({str(item) for item in analyses if str(item)})
    restricted = dict(payload)
    restricted["analyses"] = names
    project = dict(payload.get("project") or {})
    settings = dict(project.get("analysis_settings") or {})
    settings["requested_analyses"] = list(names)
    project["analysis_settings"] = settings
    restricted["project"] = project
    return restricted


__all__ = ["build_multipath_payload", "build_simulation_payload", "restrict_payload"]
