from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis_registry import (
    AnalysisCategory,
    DEFAULT_ANALYSIS_REGISTRY,
)


@dataclass(frozen=True, slots=True)
class AnalysisSpec:
    name: str
    options: dict[str, Any]


GEOMETRIC_ANALYSES = DEFAULT_ANALYSIS_REGISTRY.names(AnalysisCategory.GEOMETRIC)
WAVE_ANALYSES = DEFAULT_ANALYSIS_REGISTRY.names(AnalysisCategory.WAVE)
HYBRID_ANALYSES = DEFAULT_ANALYSIS_REGISTRY.names(AnalysisCategory.HYBRID)


def normalize_analyses(request: Any) -> list[AnalysisSpec]:
    raw_analyses = getattr(request, "analyses", None)
    if raw_analyses is None and isinstance(request, dict):
        raw_analyses = request.get("analyses", [])
    result: list[AnalysisSpec] = []
    for item in raw_analyses or []:
        if isinstance(item, str):
            name, options = item, {}
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("analysis") or "")
            options = dict(item.get("options", {}) or {})
        else:
            name = str(getattr(item, "name", getattr(item, "analysis", "")))
            options = dict(getattr(item, "options", {}) or {})
        canonical = DEFAULT_ANALYSIS_REGISTRY.canonical_name(name)
        if canonical:
            result.append(AnalysisSpec(canonical, options))
    return result


def split_analyses(analyses: list[AnalysisSpec]):
    geometric: list[AnalysisSpec] = []
    wave: list[AnalysisSpec] = []
    hybrid: list[AnalysisSpec] = []
    unsupported: list[AnalysisSpec] = []
    for analysis in analyses:
        definition = DEFAULT_ANALYSIS_REGISTRY.get(analysis.name)
        if definition is None:
            unsupported.append(analysis)
        elif definition.category is AnalysisCategory.GEOMETRIC:
            geometric.append(analysis)
        elif definition.category is AnalysisCategory.WAVE:
            wave.append(analysis)
        else:
            hybrid.append(analysis)
    return geometric, wave, hybrid, unsupported
