from __future__ import annotations

import math
from typing import Any


_POWER_SCALE_TO_W = {
    "w": 1.0,
    "mw": 1.0e-3,
    "uw": 1.0e-6,
    "µw": 1.0e-6,
    "nw": 1.0e-9,
}
_THROUGHPUT_KEYS = (
    "estimated_system_throughput",
    "weighted_ray_power_throughput",
    "geometric_throughput",
    "coupling_valid_ray_fraction",
    "valid_ray_ratio",
    "engineering_valid_ray_ratio",
)


def _read(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if value is not None:
                return value
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _object_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_non_negative_finite(value: Any, *, name: str) -> float:
    number = _finite_float(value)
    if number is None or number < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def power_to_w(value: Any, unit: Any, *, name: str) -> float:
    number = validate_non_negative_finite(value, name=name)
    key = str(unit or "").strip().lower().replace("μ", "µ")
    if key not in _POWER_SCALE_TO_W:
        supported = ", ".join(("W", "mW", "uW", "nW"))
        raise ValueError(f"{name}_unit must be one of {supported}")
    return number * _POWER_SCALE_TO_W[key]


def input_power_w_from_path(path: Any, *, default_w: float = 1.0e-3) -> tuple[float, str]:


    default_w = validate_non_negative_finite(default_w, name="default_input_power_w")
    containers: list[tuple[str, dict[str, Any], tuple[str, str]]] = [
        ("path", _object_to_dict(path), ("input_power_value", "input_power_unit")),
        ("source", _object_to_dict(_read(path, "source", default=None)), ("power_value", "power_unit")),
        ("options", _object_to_dict(_read(path, "options", default=None)), ("input_power_value", "input_power_unit")),
    ]
    for container_name, container, (value_key, unit_key) in containers:
        if value_key in container or unit_key in container:
            if value_key not in container or unit_key not in container:
                raise ValueError(
                    f"{container_name} must provide both {value_key} and {unit_key}"
                )
            return (
                power_to_w(container[value_key], container[unit_key], name=f"{container_name}.{value_key}"),
                f"{container_name}.{value_key}/{unit_key}",
            )
    return float(default_w), "default_input_power_w"


def _clamp_unit_interval_with_warning(value: float, *, label: str, warnings: list[str]) -> float:
    if value < 0.0 or value > 1.0:
        clamped = float(max(0.0, min(1.0, value)))
        warnings.append(f"{label} {value} is outside [0,1]; clamped to {clamped}")
        return clamped
    return float(value)


def throughput_from_metrics(metrics: dict[str, Any], *, path_id: str | None = None) -> tuple[float, str, list[str]]:
    warnings: list[str] = []
    label_prefix = f"path {path_id}" if path_id else "path"
    for key in _THROUGHPUT_KEYS:
        if key in metrics:
            value = _finite_float(metrics.get(key))
            if value is not None:
                throughput = _clamp_unit_interval_with_warning(
                    value,
                    label=f"{label_prefix} throughput {key}=",
                    warnings=warnings,
                )
                return throughput, key, warnings
    return 1.0, "default_1", warnings


def coupling_efficiency_from_metrics(metrics: dict[str, Any], *, path_id: str | None = None) -> tuple[float | None, str, list[str]]:
    warnings: list[str] = []
    value = _finite_float(metrics.get("coupling_efficiency"))
    if value is None:
        return None, "missing_coupling_efficiency", warnings
    label_prefix = f"path {path_id}" if path_id else "path"
    eta = _clamp_unit_interval_with_warning(
        value,
        label=f"{label_prefix} coupling_efficiency=",
        warnings=warnings,
    )
    return eta, "coupling_efficiency", warnings


def summarize_incoherent_power_sum(
    path_results: dict[str, dict[str, Any]],
    *,
    paths: list[Any],
    default_input_power_w: float = 1.0e-3,
) -> dict[str, Any]:


    default_input_power_w = validate_non_negative_finite(
        default_input_power_w,
        name="default_input_power_w",
    )
    path_by_id = {str(_read(path, "path_id", "id", default="")).strip(): path for path in paths}
    input_power_w_by_path: dict[str, float] = {}
    throughput_by_path: dict[str, float] = {}
    coupling_efficiency_by_path: dict[str, float] = {}
    transmitted_power_w_by_path: dict[str, float] = {}
    coupled_power_w_by_path: dict[str, float] = {}
    power_detail_by_path: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    total_input_power_w = 0.0
    total_transmitted_power_w = 0.0
    total_coupled_power_w = 0.0
    included_path_count = 0
    skipped_path_count = 0
    completed_path_count = 0
    best_coupled_power_path_id: str | None = None
    best_coupled_power_w: float | None = None

    for path_id, result in path_results.items():
        if result.get("status") != "completed":
            skipped_path_count += 1
            power_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": f"path status is {result.get('status')}",
            }
            continue

        completed_path_count += 1
        path = path_by_id.get(path_id)
        input_power_w, input_source = input_power_w_from_path(path, default_w=default_input_power_w)
        total_input_power_w += input_power_w
        input_power_w_by_path[path_id] = input_power_w

        metrics = dict(result.get("metrics", {}) or {})
        throughput, throughput_source, throughput_warnings = throughput_from_metrics(metrics, path_id=path_id)
        coupling_efficiency, coupling_source, coupling_warnings = coupling_efficiency_from_metrics(metrics, path_id=path_id)
        warnings.extend(throughput_warnings)
        warnings.extend(coupling_warnings)
        throughput_by_path[path_id] = throughput

        if coupling_efficiency is None:
            skipped_path_count += 1
            warnings.append(f"path {path_id} skipped in incoherent power sum: missing coupling_efficiency")
            power_detail_by_path[path_id] = {
                "status": "skipped",
                "reason": "missing_coupling_efficiency",
                "input_power_w": input_power_w,
                "input_power_source": input_source,
                "throughput": throughput,
                "throughput_source": throughput_source,
            }
            continue

        transmitted_power_w = input_power_w * throughput
        coupled_power_w = transmitted_power_w * coupling_efficiency
        coupling_efficiency_by_path[path_id] = coupling_efficiency
        transmitted_power_w_by_path[path_id] = transmitted_power_w
        coupled_power_w_by_path[path_id] = coupled_power_w
        power_detail_by_path[path_id] = {
            "status": "included",
            "input_power_w": input_power_w,
            "input_power_source": input_source,
            "throughput": throughput,
            "throughput_source": throughput_source,
            "coupling_efficiency": coupling_efficiency,
            "coupling_efficiency_source": coupling_source,
            "transmitted_power_w": transmitted_power_w,
            "coupled_power_w": coupled_power_w,
        }
        total_transmitted_power_w += transmitted_power_w
        total_coupled_power_w += coupled_power_w
        included_path_count += 1
        if best_coupled_power_w is None or coupled_power_w > best_coupled_power_w:
            best_coupled_power_path_id = path_id
            best_coupled_power_w = coupled_power_w

    power_summary_complete = skipped_path_count == 0 and included_path_count == completed_path_count
    overall_efficiency = (
        total_coupled_power_w / total_input_power_w
        if power_summary_complete and total_input_power_w > 0.0
        else None
    )
    return {
        "mode": "incoherent_power_sum",
        "power_unit": "W",
        "formula": "sum(input_power_w_i * throughput_i * coupling_efficiency_i)",
        "model_note": "Compatibility power-only sum for mutually incoherent paths; use coherent_network when phase, polarization, delay, or partial coherence matters.",
        "power_summary_complete": power_summary_complete,
        "included_path_count": included_path_count,
        "skipped_power_path_count": skipped_path_count,
        "total_input_power_w": total_input_power_w,
        "total_transmitted_power_w": total_transmitted_power_w,
        "total_coupled_power_w": total_coupled_power_w,
        "overall_power_combining_efficiency": overall_efficiency,
        "best_coupled_power_path_id": best_coupled_power_path_id,
        "best_coupled_power_w": best_coupled_power_w,
        "input_power_w_by_path": input_power_w_by_path,
        "throughput_by_path": throughput_by_path,
        "coupling_efficiency_by_path": coupling_efficiency_by_path,
        "transmitted_power_w_by_path": transmitted_power_w_by_path,
        "coupled_power_w_by_path": coupled_power_w_by_path,
        "power_detail_by_path": power_detail_by_path,
        "warnings": warnings,
    }


__all__ = [
    "power_to_w",
    "input_power_w_from_path",
    "validate_non_negative_finite",
    "throughput_from_metrics",
    "coupling_efficiency_from_metrics",
    "summarize_incoherent_power_sum",
]
