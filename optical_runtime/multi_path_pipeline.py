from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

from .result_merger import EnginePartialResult
from optical_core.physics.multipath.coherent_combination import summarize_coherent_field_sum
from optical_core.physics.multipath.ideal_scalar_combiner import summarize_ideal_2x2_scalar_combiner
from optical_core.physics.multipath.jones_polarization import summarize_jones_polarization_combiner
from optical_core.physics.multipath.power_combination import power_to_w, summarize_incoherent_power_sum
from optical_core.physics.multipath.scalar_network import summarize_scalar_optical_network




LARGE_PATH_ARRAY_KEYS = {
    "spot_points_um",
    "spot_x_um",
    "spot_y_um",
    "spot_integration_weights",
    "coupling_offset_map_xy",
    "coupling_field_intensity",
    "coupling_field_phase_rad",
    "coupling_mode_intensity",
    "coupling_mode_phase_rad",
    "psf_intensity",
    "hybrid_psf_intensity",
    "fourier_psf_intensity",
    "mtf_curve",
    "mtf_values",
    "detector_intensity.a.u.",
    "diffraction_intensity",
    "exit_pupil_intensity.a.u.",
    "axisymmetric_intensity_profile",
    "wavefront_tools_map_nm",
    "grating_intensity",
    "polarization_scan_intensity",
    "polarization_phase_scan_intensity",
    "raytrace_final_positions_mm",
    "raytrace_final_directions",
    "raytrace_valid_mask",
}

SMALL_ARRAY_MAX_ITEM_COUNT = 128


@dataclass(slots=True)
class MultiPathItemResult:
    path_id: str
    label: str
    status: str
    weight: float = 1.0
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float | None = None
    converged: bool = True

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path_id": self.path_id,
            "label": self.label,
            "status": self.status,
            "weight": self.weight,
            "metrics": dict(self.metrics),
            "arrays": dict(self.arrays),
            "warnings": list(self.warnings),
            "errors": [str(item) for item in self.errors],
            "metadata": dict(self.metadata),
            "converged": self.converged,
        }
        if self.elapsed_ms is not None:
            result["elapsed_ms"] = self.elapsed_ms
        return result


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


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping from path_id to numeric value")
    return dict(value)


def _default_input_power_w(combination: dict[str, Any]) -> float:


    value = combination.get("default_input_power_value", 1.0)
    unit = combination.get("default_input_power_unit", "mW")
    return power_to_w(value, unit, name="combination.default_input_power_value")


def _analysis_names(analyses: Any) -> list[str]:
    names: list[str] = []
    for item in analyses or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            names.append(str(item.get("name") or item.get("analysis") or ""))
        else:
            names.append(str(getattr(item, "name", getattr(item, "analysis", ""))))
    return [name for name in names if name]


def _path_identifier(path: Any, index: int) -> str:
    raw = _read(path, "path_id", "id", default=f"path_{index + 1}")
    path_id = str(raw).strip()
    if not path_id:
        raise ValueError(f"multi-path path at index {index} has an empty path_id")
    return path_id


def _path_weight(path: Any, *, path_id: str) -> float:
    raw = _read(path, "weight", default=1.0)
    if raw is None:
        raw = 1.0
    try:
        weight = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"multi-path path {path_id} has non-numeric weight {raw!r}") from exc
    if not math.isfinite(weight) or weight < 0.0:
        raise ValueError(f"multi-path path {path_id} weight must be a finite non-negative number")
    return weight


def _validate_path_list(paths: list[Any]) -> list[str]:
    if not paths:
        raise ValueError("multi-path request must contain at least one path")

    seen: set[str] = set()
    duplicates: list[str] = []
    path_order: list[str] = []
    for index, path in enumerate(paths):
        path_id = _path_identifier(path, index)
        if path_id in seen:
            duplicates.append(path_id)
        seen.add(path_id)
        _path_weight(path, path_id=path_id)
        path_order.append(path_id)

    if duplicates:
        duplicate_text = ", ".join(sorted(set(duplicates)))
        raise ValueError(f"multi-path path_id values must be unique; duplicates: {duplicate_text}")
    return path_order


def _resolve_summary_objective(summary_metric: str, requested: str | None = None) -> str:
    requested_normalized = str(requested or "auto").strip().lower()
    if requested_normalized in {"maximize", "minimize"}:
        return requested_normalized
    if requested_normalized not in {"", "auto"}:
        raise ValueError("summary_objective must be 'auto', 'maximize', or 'minimize'")

    metric = summary_metric.lower()
    minimize_markers = ("rms", "error", "loss", "radius", "diameter", "spot", "residual")
    maximize_markers = ("efficiency", "throughput", "power", "strehl", "snr", "sbr")
    if any(marker in metric for marker in minimize_markers):
        return "minimize"
    if any(marker in metric for marker in maximize_markers):
        return "maximize"
    return "maximize"


def _array_item_count(value: Any, *, limit: int = SMALL_ARRAY_MAX_ITEM_COUNT + 1) -> int:
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return 1
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            value = tolist()
        except Exception:
            return limit
    if isinstance(value, dict):
        total = 0
        for item in value.values():
            total += _array_item_count(item, limit=limit)
            if total >= limit:
                return total
        return total
    if isinstance(value, (list, tuple)):
        total = 0
        for item in value:
            total += _array_item_count(item, limit=limit)
            if total >= limit:
                return total
        return total
    return limit


def _looks_like_large_array_key(key: str) -> bool:
    lowered = key.lower()
    return (
        key in LARGE_PATH_ARRAY_KEYS
        or "history" in lowered
        or "offset_map" in lowered
        or "field_intensity" in lowered
        or "field_phase" in lowered
        or "mode_intensity" in lowered
        or lowered.endswith("_intensity")
        or lowered.endswith("_phase_rad")
    )


class MultiPathPipeline:


    def __init__(self, single_path_evaluator: Callable[[Any], Any]) -> None:
        self._single_path_evaluator = single_path_evaluator

    def evaluate(self, request: Any) -> EnginePartialResult:
        paths = list(_read(request, "paths", default=()) or ())
        path_order = _validate_path_list(paths)
        global_options = dict(_read(request, "options", "global_options", default={}) or {})
        top_level_analyses = list(_read(request, "analyses", default=()) or [])
        combination = _object_to_dict(_read(request, "combination", default={}))
        combination_mode = str(combination.get("mode") or "independent").strip().lower()
        if combination_mode not in {"independent", "incoherent_power_sum", "coherent_field_sum", "ideal_2x2_scalar_combiner", "scalar_optical_network", "jones_polarization_combiner"}:
            raise ValueError(
                "multi-path combination.mode must be 'independent', 'incoherent_power_sum', 'coherent_field_sum', "
                "or 'ideal_2x2_scalar_combiner', 'scalar_optical_network', or 'jones_polarization_combiner'"
            )
        summary_metric = str(combination.get("summary_metric") or "coupling_efficiency")
        summary_objective = _resolve_summary_objective(
            summary_metric,
            str(combination.get("summary_objective") or "auto"),
        )

        path_results: dict[str, dict[str, Any]] = {}
        raw_arrays_by_path: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        errors: list[Any] = []

        for index, path in enumerate(paths):
            path_id = path_order[index]
            label = str(_read(path, "label", "name", default=path_id))
            weight = _path_weight(path, path_id=path_id)
            enabled = bool(_read(path, "enabled", default=True))

            if not enabled:
                item = MultiPathItemResult(
                    path_id=path_id,
                    label=label,
                    status="skipped",
                    weight=weight,
                    warnings=["path disabled"],
                    metadata={"enabled": False},
                )
                path_results[path_id] = item.as_dict()
                continue

            try:
                single_request = self._build_single_path_request(
                    parent_request=request,
                    path=path,
                    path_id=path_id,
                    global_options=global_options,
                    top_level_analyses=top_level_analyses,
                )
                result = self._single_path_evaluator(single_request)

                status = str(getattr(result, "status", "completed"))
                metrics = dict(getattr(result, "metrics", {}) or {})
                raw_arrays = dict(getattr(result, "arrays", {}) or {})
                raw_arrays_by_path[path_id] = raw_arrays
                arrays = self._compact_arrays(raw_arrays, path)
                path_warnings = list(getattr(result, "warnings", []) or [])
                path_errors = list(getattr(result, "errors", []) or [])
                metadata = dict(getattr(result, "metadata", {}) or {})
                requested_engine = _read(path, "engine", default=None)

                item = MultiPathItemResult(
                    path_id=path_id,
                    label=label,
                    status=status,
                    weight=weight,
                    metrics=metrics,
                    arrays=arrays,
                    warnings=path_warnings,
                    errors=path_errors,
                    metadata={
                        **metadata,
                        "path_request_id": getattr(single_request, "request_id", path_id),
                        "analyses": _analysis_names(getattr(single_request, "analyses", [])),
                        "path_engine_requested": requested_engine,
                        "multipath_stage1_engine_note": (
                            "stage1 multipath records path.engine but evaluates all paths with "
                            "the same configured optical engine instance"
                        ),
                        "include_large_arrays": bool(_read(path, "include_large_arrays", default=False)),
                    },
                    elapsed_ms=getattr(result, "elapsed_ms", None),
                    converged=bool(getattr(result, "converged", status == "completed")),
                )
                path_results[path_id] = item.as_dict()

                if status != "completed":
                    warnings.append(f"multi-path path {path_id} finished with status {status}")

            except Exception as exc:  
                message = f"multi-path path {path_id} failed: {exc}"
                warnings.append(message)
                errors.append(message)
                item = MultiPathItemResult(
                    path_id=path_id,
                    label=label,
                    status="failed",
                    weight=weight,
                    warnings=[message],
                    errors=[exc],
                    converged=False,
                )
                path_results[path_id] = item.as_dict()

        summary = self._summarize(
            path_results=path_results,
            path_order=path_order,
            summary_metric=summary_metric,
            summary_objective=summary_objective,
        )
        combination_summary_complete = True

        if combination_mode == "incoherent_power_sum":
            default_power = _default_input_power_w(combination)
            power_summary = summarize_incoherent_power_sum(
                path_results,
                paths=paths,
                default_input_power_w=default_power,
            )
            summary["combination_mode"] = "incoherent_power_sum"
            summary["incoherent_power_sum"] = power_summary
            combination_summary_complete = bool(power_summary.get("power_summary_complete", False))
            warnings.extend(power_summary.get("warnings", []))
        elif combination_mode == "coherent_field_sum":
            default_power = _default_input_power_w(combination)
            coherent_summary = summarize_coherent_field_sum(
                path_results,
                raw_arrays_by_path=raw_arrays_by_path,
                paths=paths,
                default_input_power_w=default_power,
                phase_offsets_rad_by_path=_require_mapping(
                    combination.get("phase_offsets_rad_by_path"),
                    "phase_offsets_rad_by_path",
                ),
                return_field_arrays=bool(combination.get("return_coherent_arrays", False)),
                combiner_normalization=str(combination.get("combiner_normalization") or "none"),
                amplitude_coefficients_by_path=_require_mapping(
                    combination.get("amplitude_coefficients_by_path"),
                    "amplitude_coefficients_by_path",
                ),
            )
            coherent_arrays = dict(coherent_summary.pop("arrays", {}) or {})
            summary["combination_mode"] = "coherent_field_sum"
            summary["coherent_field_sum"] = coherent_summary
            combination_summary_complete = bool(coherent_summary.get("coherent_summary_complete", False))
            warnings.extend(coherent_summary.get("warnings", []))
        elif combination_mode == "ideal_2x2_scalar_combiner":
            default_power = _default_input_power_w(combination)
            combiner_summary = summarize_ideal_2x2_scalar_combiner(
                path_results,
                raw_arrays_by_path=raw_arrays_by_path,
                paths=paths,
                default_input_power_w=default_power,
                phase_offsets_rad_by_path=_require_mapping(
                    combination.get("phase_offsets_rad_by_path"),
                    "phase_offsets_rad_by_path",
                ),
                return_port_arrays=bool(combination.get("return_combiner_arrays", False)),
                combination_options=combination,
            )
            coherent_arrays = dict(combiner_summary.pop("arrays", {}) or {})
            summary["combination_mode"] = "ideal_2x2_scalar_combiner"
            summary["ideal_2x2_scalar_combiner"] = combiner_summary
            combination_summary_complete = bool(combiner_summary.get("ideal_2x2_summary_complete", False))
            warnings.extend(combiner_summary.get("warnings", []))
        elif combination_mode == "jones_polarization_combiner":
            default_power = _default_input_power_w(combination)
            jones_summary = summarize_jones_polarization_combiner(
                path_results,
                raw_arrays_by_path=raw_arrays_by_path,
                paths=paths,
                default_input_power_w=default_power,
                phase_offsets_rad_by_path=_require_mapping(
                    combination.get("phase_offsets_rad_by_path"),
                    "phase_offsets_rad_by_path",
                ),
                jones_vectors_by_path=_require_mapping(
                    combination.get("jones_vectors_by_path"),
                    "jones_vectors_by_path",
                ),
                jones_elements_by_path=_require_mapping(
                    combination.get("jones_elements_by_path"),
                    "jones_elements_by_path",
                ),
                jones_matrices_by_path=_require_mapping(
                    combination.get("jones_matrices_by_path"),
                    "jones_matrices_by_path",
                ),
                mode_polarization=str(combination.get("mode_polarization") or combination.get("fiber_mode_polarization") or "polarization_insensitive"),
                mode_jones_vector=combination.get("mode_jones_vector", combination.get("fiber_mode_jones_vector")),
                return_jones_arrays=bool(combination.get("return_jones_arrays", False)),
                allow_jones_gain=bool(
                    combination.get("allow_jones_gain", combination.get("allow_nonpassive_jones", False))
                ),
                jones_passivity_tolerance=combination.get("jones_passivity_tolerance", 1.0e-9),
            )
            coherent_arrays = dict(jones_summary.pop("arrays", {}) or {})
            summary["combination_mode"] = "jones_polarization_combiner"
            summary["jones_polarization_combiner"] = jones_summary
            combination_summary_complete = bool(jones_summary.get("jones_physical_assumptions_complete", False))
            warnings.extend(jones_summary.get("warnings", []))
        elif combination_mode == "scalar_optical_network":
            default_power = _default_input_power_w(combination)
            network_summary = summarize_scalar_optical_network(
                path_results,
                raw_arrays_by_path=raw_arrays_by_path,
                paths=paths,
                default_input_power_w=default_power,
                phase_offsets_rad_by_path=_require_mapping(
                    combination.get("phase_offsets_rad_by_path"),
                    "phase_offsets_rad_by_path",
                ),
                return_network_arrays=bool(combination.get("return_network_arrays", False)),
                combination_options=combination,
            )
            coherent_arrays = dict(network_summary.pop("arrays", {}) or {})
            summary["combination_mode"] = "scalar_optical_network"
            summary["scalar_optical_network"] = network_summary
            combination_summary_complete = bool(network_summary.get("network_summary_complete", False))
            warnings.extend(network_summary.get("warnings", []))
        else:
            coherent_arrays = {}
            summary["combination_mode"] = "independent"

        final = EnginePartialResult.empty()
        result_arrays: dict[str, Any] = {"multipath_paths": path_results}
        if combination_mode in {"coherent_field_sum", "ideal_2x2_scalar_combiner", "scalar_optical_network", "jones_polarization_combiner"} and coherent_arrays:
            result_arrays.update(coherent_arrays)
        final.merge(
            EnginePartialResult(
                metrics=self._flatten_summary_metrics(summary),
                arrays=result_arrays,
                metadata={
                    "multipath_summary": summary,
                    "multipath_mode": summary.get("combination_mode", "independent"),
                    "multipath_evaluation_mode": "independent",
            "multipath_power_unit": "W",
                    "multipath_stage": (
                        "stage5_scalar_node_network"
                        if combination_mode == "scalar_optical_network"
                        else (
                            "stage6_jones_polarization_combiner"
                            if combination_mode == "jones_polarization_combiner"
                            else "stage1_independent_dispatch"
                        )
                    ),
                },
            ),
            namespace="multipath",
            on_conflict="raise",
        )
        final.metadata["multipath_supported_scope"] = (
            "Compatibility summaries support independent sequential paths, incoherent power sums, "
            "scalar coherent sums, one ideal 2x2 scalar node and the legacy Jones combiner. "
            "Use coherent_network for general delayed multi-node Jones propagation and "
            "ghost_stray_light for physical reflection, diffraction and coating branches."
        )
        final.metadata["multipath_array_policy"] = (
            "large per-path arrays are omitted unless include_large_arrays=true is set on that path"
        )
        final.warnings.extend(warnings)
        final.errors.extend(errors)
        final.converged = bool(summary.get("failed_path_count", 0) == 0 and combination_summary_complete)
        return final

    def _build_single_path_request(
        self,
        *,
        parent_request: Any,
        path: Any,
        path_id: str,
        global_options: dict[str, Any],
        top_level_analyses: list[Any],
    ) -> SimpleNamespace:
        project = _read(path, "project", default=None)
        system = _read(path, "system", default=None)

        if project is None:
            if system is None:
                raise ValueError(f"path {path_id} does not define project or system")
            project = self._system_to_project_like(system=system, path=path, path_id=path_id)

        analyses = list(_read(path, "analyses", default=None) or top_level_analyses or [])
        path_options = dict(_read(path, "options", default={}) or {})
        options = {**global_options, **path_options}

        return SimpleNamespace(
            schema_version=str(_read(parent_request, "schema_version", default="1.0")),
            request_id=f"{_read(parent_request, 'request_id', default='multipath')}.{path_id}",
            project=project,
            analyses=analyses,
            parameter_changes=list(_read(path, "parameter_changes", default=()) or ()),
            precision=str(_read(path, "precision", default=_read(parent_request, "precision", default="standard"))),
            random_seed=int(_read(path, "random_seed", default=_read(parent_request, "random_seed", default=42)) or 42),
            engine=_read(path, "engine", default=_read(parent_request, "engine", default=None)),
            options=options,
        )

    def _system_to_project_like(self, *, system: Any, path: Any, path_id: str) -> dict[str, Any]:
        project = _object_to_dict(system)
        source = _read(path, "source", default=None)
        receiver = _read(path, "receiver", default=None)

        if source is not None and "source" not in project:
            project["source"] = _object_to_dict(source)
        if receiver is not None and "receiver" not in project:
            project["receiver"] = _object_to_dict(receiver)

        project.setdefault("project_id", path_id)
        project.setdefault("object_distance_mm", 0.0)
        project.setdefault("image_distance_mm", 0.0)
        project.setdefault("pupil_radius_mm", 1.0)
        project.setdefault("surfaces", [])
        project.setdefault("fingerprint", f"multipath:{path_id}")
        project.setdefault("schema_version", "1.0")
        project.setdefault("analysis_settings", {})
        project.setdefault("aperture", {})

        if "source" not in project:
            wavelength_nm = _read(system, "wavelength_nm", default=None)
            project["source"] = {
                "wavelength_nm": float(wavelength_nm or 550.0),
                "source_type": "gaussian",
                "beam_quality_m2": 1.0,
            }
        return project

    def _compact_arrays(self, arrays: dict[str, Any], path: Any) -> dict[str, Any]:
        include_large_arrays = bool(_read(path, "include_large_arrays", default=False))
        if include_large_arrays:
            return arrays

        compact: dict[str, Any] = {}
        for key, value in arrays.items():
            if _looks_like_large_array_key(str(key)):
                continue
            if _array_item_count(value) > SMALL_ARRAY_MAX_ITEM_COUNT:
                continue
            compact[key] = value
        return compact

    def _summarize(
        self,
        *,
        path_results: dict[str, dict[str, Any]],
        path_order: list[str],
        summary_metric: str,
        summary_objective: str,
    ) -> dict[str, Any]:
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
            except (TypeError, ValueError):
                continue
            weight = float(result.get("weight", 1.0))
            if not math.isfinite(weight) or weight < 0.0:
                continue
            values[path_id] = value
            weighted_sum += weight * value
            weight_sum += weight

        if not values:
            best_path_id = None
        elif summary_objective == "minimize":
            best_path_id = min(values, key=values.get)
        else:
            best_path_id = max(values, key=values.get)

        completed = sum(1 for item in path_results.values() if item.get("status") == "completed")
        failed = sum(1 for item in path_results.values() if item.get("status") == "failed")
        skipped = sum(1 for item in path_results.values() if item.get("status") == "skipped")

        return {
            "mode": "independent",
            "combination_mode": "independent",
            "summary_metric": summary_metric,
            "summary_objective": summary_objective,
            "path_order": list(path_order),
            "path_count": len(path_results),
            "completed_path_count": completed,
            "failed_path_count": failed,
            "skipped_path_count": skipped,
            "summary_metric_by_path": values,
            "best_path_id": best_path_id,
            "best_summary_metric": values.get(best_path_id) if best_path_id is not None else None,
            "weighted_summary_metric": weighted_sum / weight_sum if weight_sum > 0.0 else None,
        }

    def _flatten_summary_metrics(self, summary: dict[str, Any]) -> dict[str, Any]:
        metric_name = str(summary.get("summary_metric") or "coupling_efficiency")
        combination_mode = str(summary.get("combination_mode") or "independent")
        metrics: dict[str, Any] = {
            "multipath_mode": combination_mode,
            "multipath_evaluation_mode": "independent",
            "multipath_summary_metric": metric_name,
            "multipath_summary_objective": summary.get("summary_objective"),
            "multipath_path_count": int(summary.get("path_count", 0) or 0),
            "multipath_completed_path_count": int(summary.get("completed_path_count", 0) or 0),
            "multipath_failed_path_count": int(summary.get("failed_path_count", 0) or 0),
            "multipath_skipped_path_count": int(summary.get("skipped_path_count", 0) or 0),
            "multipath_best_path_id": summary.get("best_path_id"),
            f"multipath_best_{metric_name}": summary.get("best_summary_metric"),
            f"multipath_weighted_{metric_name}": summary.get("weighted_summary_metric"),
            f"multipath_{metric_name}_by_path": dict(summary.get("summary_metric_by_path", {}) or {}),
        }

        power = dict(summary.get("incoherent_power_sum", {}) or {})
        if power:
            metrics.update(
                {
                    "multipath_power_combination_mode": "incoherent_power_sum",
                    "multipath_power_summary_complete": bool(power.get("power_summary_complete", False)),
                    "multipath_power_included_path_count": int(power.get("included_path_count", 0) or 0),
                    "multipath_power_skipped_path_count": int(power.get("skipped_power_path_count", 0) or 0),
                    "multipath_total_input_power_w": power.get("total_input_power_w"),
                    "multipath_total_transmitted_power_w": power.get("total_transmitted_power_w"),
                    "multipath_total_coupled_power_w": power.get("total_coupled_power_w"),
                    "multipath_overall_power_combining_efficiency": power.get("overall_power_combining_efficiency"),
                    "multipath_best_coupled_power_path_id": power.get("best_coupled_power_path_id"),
                    "multipath_best_coupled_power_w": power.get("best_coupled_power_w"),
                    "multipath_input_power_w_by_path": dict(power.get("input_power_w_by_path", {}) or {}),
                    "multipath_throughput_by_path": dict(power.get("throughput_by_path", {}) or {}),
                    "multipath_power_coupling_efficiency_by_path": dict(
                        power.get("coupling_efficiency_by_path", {}) or {}
                    ),
                    "multipath_transmitted_power_w_by_path": dict(
                        power.get("transmitted_power_w_by_path", {}) or {}
                    ),
                    "multipath_coupled_power_w_by_path": dict(power.get("coupled_power_w_by_path", {}) or {}),
                }
            )

        coherent = dict(summary.get("coherent_field_sum", {}) or {})
        if coherent:
            metrics.update(
                {
                    "multipath_coherent_combination_mode": "coherent_field_sum",
                    "multipath_coherent_summary_complete": bool(coherent.get("coherent_summary_complete", False)),
                    "multipath_coherent_included_path_count": int(coherent.get("included_path_count", 0) or 0),
                    "multipath_coherent_skipped_path_count": int(coherent.get("skipped_coherent_path_count", 0) or 0),
                    "multipath_coherent_total_input_power_w": coherent.get("total_input_power_w"),
                    "multipath_coherent_total_transmitted_power_w": coherent.get("total_transmitted_power_w"),
                    "multipath_coherent_field_power_w": coherent.get("total_coherent_field_power_w"),
                    "multipath_coherent_coupled_power_w": coherent.get("total_coupled_power_w"),
                    "multipath_coherent_mode_overlap_efficiency": coherent.get("coherent_mode_overlap_efficiency"),
                    "multipath_overall_coherent_combining_efficiency": coherent.get("overall_coherent_combining_efficiency"),
                    "multipath_coherent_overlap_abs": coherent.get("coherent_overlap_abs"),
                    "multipath_coherent_overlap_phase_rad": coherent.get("coherent_overlap_phase_rad"),
                    "multipath_coherent_input_power_w_by_path": dict(coherent.get("input_power_w_by_path", {}) or {}),
                    "multipath_coherent_throughput_by_path": dict(coherent.get("throughput_by_path", {}) or {}),
                    "multipath_coherent_transmitted_power_w_by_path": dict(
                        coherent.get("transmitted_power_w_by_path", {}) or {}
                    ),
                    "multipath_coherent_phase_offset_rad_by_path": dict(
                        coherent.get("phase_offset_rad_by_path", {}) or {}
                    ),
                    "multipath_coherent_amplitude_coefficient_by_path": dict(
                        coherent.get("amplitude_coefficient_by_path", {}) or {}
                    ),
                    "multipath_coherent_combiner_normalization": coherent.get("combiner_normalization"),
                    "multipath_coherent_reference_wavelength_nm": coherent.get("reference_wavelength_nm"),
                    "multipath_coherent_grid_checked": bool(coherent.get("coherent_assumption_grid_checked", False)),
                    "multipath_coherent_wavelength_checked": bool(
                        coherent.get("coherent_assumption_wavelength_checked", False)
                    ),
                    "multipath_coherent_mode_phase_checked": bool(
                        coherent.get("coherent_assumption_mode_phase_checked", False)
                    ),
                    "multipath_coherent_grid_uniform_checked": bool(
                        coherent.get("coherent_assumption_grid_uniform_checked", False)
                    ),
                    "multipath_coherent_physical_assumptions_complete": bool(
                        coherent.get("coherent_physical_assumptions_complete", False)
                    ),
                    "multipath_coherent_polarization_checked": bool(
                        coherent.get("coherent_assumption_polarization_checked", False)
                    ),
                    "multipath_coherent_phase_reference_checked": bool(
                        coherent.get("coherent_assumption_phase_reference_checked", False)
                    ),
                }
            )

        combiner = dict(summary.get("ideal_2x2_scalar_combiner", {}) or {})
        if combiner:
            metrics.update(
                {
                    "multipath_2x2_combination_mode": "ideal_2x2_scalar_combiner",
                    "multipath_2x2_summary_complete": bool(combiner.get("ideal_2x2_summary_complete", False)),
                    "multipath_2x2_included_path_count": int(combiner.get("included_path_count", 0) or 0),
                    "multipath_2x2_skipped_path_count": int(combiner.get("skipped_combiner_path_count", 0) or 0),
                    "multipath_2x2_input_path_order": list(combiner.get("input_path_order", []) or []),
                    "multipath_2x2_included_path_order": list(combiner.get("included_path_order", []) or []),
                    "multipath_2x2_total_input_power_w": combiner.get("total_input_power_w"),
                    "multipath_2x2_total_transmitted_power_w": combiner.get("total_transmitted_power_w"),
                    "multipath_2x2_total_output_field_power_w": combiner.get("total_output_field_power_w"),
                    "multipath_2x2_total_output_coupled_power_w": combiner.get("total_output_coupled_power_w"),
                    "multipath_2x2_overall_output_coupling_efficiency": combiner.get("overall_output_coupling_efficiency"),
                    "multipath_2x2_best_output_port_id": combiner.get("best_output_port_id"),
                    "multipath_2x2_best_output_coupled_power_w": combiner.get("best_output_coupled_power_w"),
                    "multipath_2x2_output_field_power_w_by_port": dict(combiner.get("output_field_power_w_by_port", {}) or {}),
                    "multipath_2x2_output_coupled_power_w_by_port": dict(combiner.get("output_coupled_power_w_by_port", {}) or {}),
                    "multipath_2x2_output_overlap_efficiency_by_port": dict(combiner.get("output_overlap_efficiency_by_port", {}) or {}),
                    "multipath_2x2_energy_conservation_checked": bool(combiner.get("energy_conservation_checked", False)),
                    "multipath_2x2_energy_conservation_passed": bool(combiner.get("energy_conservation_passed", False)),
                    "multipath_2x2_energy_conservation_error_w": combiner.get("energy_conservation_error_w"),
                    "multipath_2x2_relative_energy_conservation_error": combiner.get("relative_energy_conservation_error"),
                    "multipath_2x2_coefficient_unitary_like": bool(combiner.get("coefficient_unitary_like", False)),
                    "multipath_2x2_coefficient_info": dict(combiner.get("coefficient_info", {}) or {}),
                    "multipath_2x2_grid_checked": bool(combiner.get("combiner_assumption_grid_checked", False)),
                    "multipath_2x2_grid_uniform_checked": bool(combiner.get("combiner_assumption_grid_uniform_checked", False)),
                    "multipath_2x2_wavelength_checked": bool(combiner.get("combiner_assumption_wavelength_checked", False)),
                    "multipath_2x2_mode_phase_checked": bool(combiner.get("combiner_assumption_mode_phase_checked", False)),
                    "multipath_2x2_polarization_checked": bool(combiner.get("combiner_assumption_polarization_checked", False)),
                    "multipath_2x2_phase_reference_checked": bool(combiner.get("combiner_assumption_phase_reference_checked", False)),
                }
            )

        jones = dict(summary.get("jones_polarization_combiner", {}) or {})
        if jones:
            stokes = dict(jones.get("integrated_stokes", {}) or {})
            metrics.update(
                {
                    "multipath_jones_combination_mode": "jones_polarization_combiner",
                    "multipath_jones_summary_complete": bool(jones.get("jones_summary_complete", False)),
                    "multipath_jones_included_path_count": int(jones.get("included_path_count", 0) or 0),
                    "multipath_jones_skipped_path_count": int(jones.get("skipped_jones_path_count", 0) or 0),
                    "multipath_jones_total_input_power_w": jones.get("total_input_power_w"),
                    "multipath_jones_total_transmitted_power_w": jones.get("total_transmitted_power_w"),
                    "multipath_jones_field_power_w": jones.get("total_jones_field_power_w"),
                    "multipath_jones_coupled_power_w": jones.get("total_coupled_power_w"),
                    "multipath_jones_mode_overlap_efficiency": jones.get("jones_mode_overlap_efficiency"),
                    "multipath_overall_jones_combining_efficiency": jones.get("overall_jones_combining_efficiency"),
                    "multipath_jones_overlap_phase_rad": jones.get("jones_overlap_phase_rad"),
                    "multipath_jones_mode_polarization": jones.get("mode_polarization"),
                    "multipath_jones_input_power_w_by_path": dict(jones.get("input_power_w_by_path", {}) or {}),
                    "multipath_jones_throughput_by_path": dict(jones.get("throughput_by_path", {}) or {}),
                    "multipath_jones_transmitted_power_w_by_path": dict(jones.get("transmitted_power_w_by_path", {}) or {}),
                    "multipath_jones_phase_offset_rad_by_path": dict(jones.get("phase_offset_rad_by_path", {}) or {}),
                    "multipath_jones_vector_by_path": dict(jones.get("jones_vector_by_path", {}) or {}),
                    "multipath_jones_power_factor_by_path": dict(jones.get("jones_power_factor_by_path", {}) or {}),
                    "multipath_jones_reference_wavelength_nm": jones.get("reference_wavelength_nm"),
                    "multipath_jones_stokes_S0": stokes.get("S0"),
                    "multipath_jones_stokes_S1": stokes.get("S1"),
                    "multipath_jones_stokes_S2": stokes.get("S2"),
                    "multipath_jones_stokes_S3": stokes.get("S3"),
                    "multipath_jones_normalized_S1": stokes.get("normalized_S1"),
                    "multipath_jones_normalized_S2": stokes.get("normalized_S2"),
                    "multipath_jones_normalized_S3": stokes.get("normalized_S3"),
                    "multipath_jones_grid_checked": bool(jones.get("jones_assumption_grid_checked", False)),
                    "multipath_jones_grid_uniform_checked": bool(jones.get("jones_assumption_grid_uniform_checked", False)),
                    "multipath_jones_wavelength_checked": bool(jones.get("jones_assumption_wavelength_checked", False)),
                    "multipath_jones_mode_reference_checked": bool(jones.get("jones_assumption_mode_reference_checked", False)),
                    "multipath_jones_polarization_checked": bool(jones.get("jones_assumption_polarization_checked", False)),
                    "multipath_jones_phase_reference_checked": bool(jones.get("jones_assumption_phase_reference_checked", False)),
                    "multipath_jones_physical_assumptions_complete": bool(jones.get("jones_physical_assumptions_complete", False)),
                    "multipath_jones_explicit_polarization_checked": bool(
                        jones.get("jones_assumption_explicit_polarization_checked", False)
                    ),
                    "multipath_jones_default_polarization_path_ids": list(
                        jones.get("jones_default_polarization_path_ids", []) or []
                    ),
                    "multipath_jones_passive_checked": bool(jones.get("jones_passive_checked", False)),
                    "multipath_jones_passive_passed": bool(jones.get("jones_passive_passed", False)),
                    "multipath_jones_passive_warning_by_path": dict(
                        jones.get("jones_passive_warning_by_path", {}) or {}
                    ),
                    "multipath_jones_nonpassive_path_ids": list(jones.get("jones_nonpassive_path_ids", []) or []),
                    "multipath_jones_max_power_gain_by_path": dict(
                        jones.get("jones_max_power_gain_by_path", {}) or {}
                    ),
                    "multipath_jones_stokes_convention": jones.get("jones_stokes_convention"),
                    "multipath_jones_circular_convention": jones.get("jones_circular_convention"),
                    "multipath_jones_waveplate_matrix_convention": jones.get("jones_waveplate_matrix_convention"),
                    "multipath_jones_allow_nonpassive_gain": bool(jones.get("jones_allow_nonpassive_gain", False)),
                }
            )

        network = dict(summary.get("scalar_optical_network", {}) or {})
        if network:
            metrics.update(
                {
                    "multipath_network_combination_mode": "scalar_optical_network",
                    "multipath_network_summary_complete": bool(network.get("network_summary_complete", False)),
                    "multipath_network_stage": network.get("network_stage"),
                    "multipath_network_node_count": int(network.get("node_count", 0) or 0),
                    "multipath_network_edge_count": int(network.get("edge_count", 0) or 0),
                    "multipath_network_output_node_id": network.get("output_node_id"),
                    "multipath_network_node_order": list(network.get("node_order", []) or []),
                    "multipath_network_node_type_by_id": dict(network.get("node_type_by_id", {}) or {}),
                    "multipath_network_input_ports_by_node": dict(network.get("input_ports_by_node", {}) or {}),
                    "multipath_network_output_ports_by_node": dict(network.get("output_ports_by_node", {}) or {}),
                    "multipath_network_ordered_input_path_ids": list(network.get("ordered_input_path_ids", []) or []),
                    "multipath_network_total_input_power_w": network.get("total_input_power_w"),
                    "multipath_network_total_transmitted_power_w": network.get("total_transmitted_power_w"),
                    "multipath_network_total_output_field_power_w": network.get("total_output_field_power_w"),
                    "multipath_network_total_output_coupled_power_w": network.get("total_output_coupled_power_w"),
                    "multipath_network_best_output_port_id": network.get("best_output_port_id"),
                    "multipath_network_best_output_coupled_power_w": network.get("best_output_coupled_power_w"),
                    "multipath_network_output_field_power_w_by_port": dict(network.get("output_field_power_w_by_port", {}) or {}),
                    "multipath_network_output_coupled_power_w_by_port": dict(network.get("output_coupled_power_w_by_port", {}) or {}),
                    "multipath_network_output_overlap_efficiency_by_port": dict(network.get("output_overlap_efficiency_by_port", {}) or {}),
                    "multipath_network_energy_conservation_checked": bool(network.get("energy_conservation_checked", False)),
                    "multipath_network_energy_conservation_passed": bool(network.get("energy_conservation_passed", False)),
                    "multipath_network_energy_conservation_error_w": network.get("energy_conservation_error_w"),
                    "multipath_network_relative_energy_conservation_error": network.get("relative_energy_conservation_error"),
                    "multipath_network_coefficient_unitary_like": bool(network.get("coefficient_unitary_like", False)),
                    "multipath_network_coefficient_info_by_node": dict(network.get("coefficient_info_by_node", {}) or {}),
                    "multipath_network_grid_checked": bool(network.get("network_assumption_grid_checked", False)),
                    "multipath_network_grid_uniform_checked": bool(network.get("network_assumption_grid_uniform_checked", False)),
                    "multipath_network_wavelength_checked": bool(network.get("network_assumption_wavelength_checked", False)),
                    "multipath_network_mode_phase_checked": bool(network.get("network_assumption_mode_phase_checked", False)),
                    "multipath_network_polarization_checked": bool(network.get("network_assumption_polarization_checked", False)),
                    "multipath_network_phase_reference_checked": bool(network.get("network_assumption_phase_reference_checked", False)),
                }
            )
        return metrics
