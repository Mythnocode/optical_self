
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

_GEOMETRIC_ONLY = frozenset({"raytrace", "spot", "throughput", "focus_search"})
_WAVE_ONLY = frozenset({"psf", "mtf", "diffraction"})


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def request_fingerprint(payload: Mapping[str, Any]) -> str:
    normalized = deepcopy(dict(payload))
    normalized.pop("request_id", None)
    return _digest(normalized)


def physical_fingerprint(payload: Mapping[str, Any]) -> str:


    normalized = deepcopy(dict(payload))
    normalized.pop("request_id", None)
    analyses = _requested_analyses(normalized)
    normalized.pop("analyses", None)

    for path in normalized.get("paths", []) or []:
        if isinstance(path, dict):
            path.pop("analyses", None)

    project = normalized.get("project")
    if isinstance(project, dict):
        
        
        project.pop("fingerprint", None)
        settings = project.get("analysis_settings")
        if isinstance(settings, dict):
            settings.pop("requested_analyses", None)

    options = normalized.get("options")
    if isinstance(options, dict):
        geometric = options.get("geometric")
        if isinstance(geometric, dict):
            geometric.pop("record_surfaces", None)
        hybrid = options.get("hybrid")
        if isinstance(hybrid, dict):
            hybrid.pop("include_diagnostic_arrays", None)
            hybrid.pop("result_array_policy", None)
            hybrid.pop("return_history", None)

    if analyses and analyses.issubset(_GEOMETRIC_ONLY):
        if isinstance(project, dict):
            project.pop("receiver", None)
        if isinstance(options, dict):
            options.pop("wave", None)
            options.pop("hybrid", None)
    elif analyses and analyses.issubset(_WAVE_ONLY):
        if isinstance(project, dict):
            project.pop("receiver", None)
        if isinstance(options, dict):
            options.pop("hybrid", None)

    return _digest(normalized)


def _requested_analyses(payload: Mapping[str, Any]) -> frozenset[str]:
    values = payload.get("analyses", ())
    if isinstance(values, (list, tuple, set, frozenset)):
        return frozenset(str(item) for item in values if str(item))
    return frozenset()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["canonical_json", "physical_fingerprint", "request_fingerprint"]
