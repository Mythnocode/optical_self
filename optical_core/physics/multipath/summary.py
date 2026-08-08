from __future__ import annotations

import math
from typing import Any


def resolve_summary_objective(summary_metric: str, requested: str = "auto") -> str:
    requested_normalized = str(requested or "auto").strip().lower()
    if requested_normalized in {"maximize", "minimize"}:
        return requested_normalized
    if requested_normalized not in {"", "auto"}:
        raise ValueError("summary_objective must be 'auto', 'maximize', or 'minimize'")

    metric = summary_metric.lower()
    if any(marker in metric for marker in ("rms", "error", "loss", "radius", "diameter", "spot", "residual")):
        return "minimize"
    if any(marker in metric for marker in ("efficiency", "throughput", "power", "strehl", "snr", "sbr")):
        return "maximize"
    return "maximize"


def summarize_independent_paths(
    path_results: dict[str, dict[str, Any]],
    *,
    summary_metric: str = "coupling_efficiency",
    summary_objective: str = "auto",
) -> dict[str, Any]:
    objective = resolve_summary_objective(summary_metric, summary_objective)
    values: dict[str, float] = {}
    weighted_sum = 0.0
    weight_sum = 0.0

    for path_id, result in path_results.items():
        if result.get("status") != "completed":
            continue
        metrics = dict(result.get("metrics", {}) or {})
        raw_value = metrics.get(summary_metric)
        if raw_value is None:
            continue
        try:
            value = float(raw_value)
            weight = float(result.get("weight", 1.0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or not math.isfinite(weight) or weight < 0.0:
            continue
        values[path_id] = value
        weighted_sum += weight * value
        weight_sum += weight

    if not values:
        best_path_id = None
    elif objective == "minimize":
        best_path_id = min(values, key=values.get)
    else:
        best_path_id = max(values, key=values.get)

    return {
        "mode": "independent",
        "summary_metric": summary_metric,
        "summary_objective": objective,
        "path_count": len(path_results),
        "completed_path_count": sum(1 for item in path_results.values() if item.get("status") == "completed"),
        "failed_path_count": sum(1 for item in path_results.values() if item.get("status") == "failed"),
        "skipped_path_count": sum(1 for item in path_results.values() if item.get("status") == "skipped"),
        "summary_metric_by_path": values,
        "best_path_id": best_path_id,
        "best_summary_metric": values.get(best_path_id) if best_path_id is not None else None,
        "weighted_summary_metric": weighted_sum / weight_sum if weight_sum > 0.0 else None,
    }
