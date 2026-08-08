from __future__ import annotations

from typing import Any, Mapping

from .schemas import HelpContext


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="python"))
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _first(mapping: Mapping[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _normalise_errors(errors: Any) -> list[dict[str, Any] | str]:
    result: list[dict[str, Any] | str] = []
    for item in errors or []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(dict(item))
        elif hasattr(item, "model_dump"):
            result.append(dict(item.model_dump(mode="python")))
        else:
            result.append(str(item))
    return result


def _derive_rms_ratio(metrics: Mapping[str, Any], axis: str) -> float | None:
    field = metrics.get(f"coupling_field_rms_{axis}_um")
    mode = metrics.get(f"coupling_mode_rms_{axis}_um")
    try:
        if field is None or mode is None or float(mode) == 0.0:
            return None
        return float(field) / float(mode)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def build_help_context(
    *,
    page_id: str | None = None,
    selected_control_id: str | None = None,
    project: Any = None,
    request: Any = None,
    result: Any = None,
    model_report: Any = None,
    shap_report: Any = None,
) -> HelpContext:


    project_data = _as_mapping(project)
    request_data = _as_mapping(request)
    result_data = _as_mapping(result)
    model_data = _as_mapping(model_report)
    shap_data = _as_mapping(shap_report)

    metrics = _as_mapping(result_data.get("metrics"))
    metadata = _as_mapping(result_data.get("metadata"))
    options = _as_mapping(request_data.get("options"))

    result_summary = {
        key: value
        for key, value in {
            "coupling_efficiency": _first(
                metrics,
                ("coupling_efficiency", "mode_overlap_efficiency", "complex_field_overlap_efficiency"),
            ),
            "total_coupling_efficiency": _first(
                metrics,
                ("total_coupling_efficiency", "overall_output_coupling_efficiency"),
            ),
            "best_focus_z_mm": _first(metrics, ("best_focus_z_mm",)),
            "best_focus_offset_z_mm_diagnostic": _first(
                metrics,
                ("best_focus_offset_z_mm_diagnostic", "receiver_best_focus_offset_z_mm"),
            ),
            "best_focus_minimum_at_scan_boundary": _first(
                metrics,
                ("best_focus_minimum_at_scan_boundary",),
            ),
            "phase_only_penalty": _first(
                metrics,
                ("phase_only_penalty", "centered_phase_matching_efficiency"),
            ),
            "intensity_only_overlap": _first(
                metrics,
                ("intensity_only_overlap", "centered_intensity_overlap"),
            ),
            "alignment_efficiency": _first(metrics, ("alignment_efficiency",)),
            "transmission_efficiency": _first(metrics, ("transmission_efficiency",)),
            "polarization_overlap_efficiency": _first(
                metrics,
                ("polarization_overlap_efficiency",),
            ),
            "coupling_valid_ray_fraction": _first(
                metrics,
                ("coupling_valid_ray_fraction",),
            ),
            "mode_size_ratio_x": _derive_rms_ratio(metrics, "x"),
            "mode_size_ratio_y": _derive_rms_ratio(metrics, "y"),
            "in_training_domain": _first(model_data, ("in_training_domain",)),
            "shap_additivity_error": _first(
                shap_data,
                ("additivity_error", "total_additivity_error_db", "residual_additivity_error_db"),
            ),
        }.items()
        if value is not None
    }

    diagnostics = {
        key: value
        for key, value in {
            "converged": result_data.get("converged") if result_data else None,
            "has_errors": bool(result_data.get("errors")) if result_data else None,
            "warning_text": "\n".join(str(item) for item in result_data.get("warnings", []) or []) if result_data else None,
            "edge_power_fraction": _first(
                metrics,
                (
                    "propagation_edge_power_fraction",
                    "edge_power_fraction",
                    "receiver_window_edge_power",
                    "aliasing_edge_power_fraction",
                    "fiber_tolerance_propagation_edge_power_fraction",
                ),
            ),
            "edge_power_threshold": _first(
                metrics,
                ("edge_power_threshold",),
                options.get("edge_power_threshold"),
            ),
            "edge_power_pass": _first(
                metrics,
                ("coupling_propagation_edge_pass", "edge_power_pass"),
            ),
            "energy_closure_error": _first(
                metrics,
                (
                    "propagation_energy_closure_error",
                    "energy_closure_error",
                    "fiber_tolerance_propagation_energy_closure_error",
                ),
            ),
            "energy_closure_threshold": _first(
                metrics,
                ("energy_closure_threshold",),
                options.get("energy_closure_threshold"),
            ),
            "energy_closure_pass": _first(
                metrics,
                ("coupling_propagation_energy_pass", "energy_closure_pass"),
            ),
            "nyquist_margin_min": _first(
                metrics,
                (
                    "propagation_nyquist_margin_min",
                    "nyquist_margin_min",
                    "fiber_tolerance_propagation_nyquist_margin_min",
                ),
            ),
            "nyquist_required_min": options.get("nyquist_margin_min"),
            "nyquist_pass": _first(
                metrics,
                ("coupling_propagation_nyquist_pass", "nyquist_pass"),
            ),
            "sampling_convergence_pass": _first(
                metrics,
                ("sampling_convergence_pass", "coupling_propagation_sampling_pass"),
            ),
            "best_focus_at_boundary": _first(
                metrics,
                ("best_focus_minimum_at_scan_boundary",),
            ),
            "feature_contract_match": _first(
                model_data,
                ("feature_contract_match", "schema_match"),
            ),
            "in_training_domain": _first(model_data, ("in_training_domain",)),
            "shap_additivity_error": _first(
                shap_data,
                ("additivity_error", "total_additivity_error_db", "residual_additivity_error_db"),
            ),
            "shap_additivity_tolerance": _first(
                shap_data,
                ("additivity_tolerance", "max_additivity_error"),
            ),
            "mode_size_ratio_x": result_summary.get("mode_size_ratio_x"),
            "mode_size_ratio_y": result_summary.get("mode_size_ratio_y"),
            "mode_size_ratio_tolerance": options.get("mode_size_ratio_tolerance"),
            "phase_matching_efficiency": result_summary.get("phase_only_penalty"),
            "phase_matching_efficiency_min": options.get("phase_matching_efficiency_min"),
            "valid_ray_fraction": result_summary.get("coupling_valid_ray_fraction"),
            "valid_ray_fraction_min": options.get("valid_ray_fraction_min"),
        }.items()
        if value is not None
    }

    dynamic_sources: dict[str, dict[str, Any]] = {}
    request_id = str(result_data.get("request_id") or request_data.get("request_id") or "") or None
    if result_data:
        dynamic_sources["context.current_report"] = {
            "title": f"当前正式结果{f'（{request_id}）' if request_id else ''}",
            "source_type": "current_report",
            "request_id": request_id,
            "engine_name": result_data.get("engine_name"),
            "engine_version": result_data.get("engine_version"),
            "status": result_data.get("status"),
            "converged": result_data.get("converged"),
        }

    analysis_type = None
    analyses = request_data.get("analyses")
    if isinstance(analyses, list) and analyses:
        analysis_type = str(analyses[0])
    analysis_type = str(metadata.get("analysis_type") or analysis_type or "") or None

    project_id = project_data.get("project_id") or project_data.get("id") or project_data.get("name")
    project_version = project_data.get("version") or project_data.get("project_version")

    return HelpContext(
        page_id=page_id,
        selected_control_id=selected_control_id,
        project_id=None if project_id is None else str(project_id),
        project_version=None if project_version is None else str(project_version),
        analysis_type=analysis_type,
        request_id=request_id,
        result_status=result_data.get("status"),
        result_summary=result_summary,
        diagnostics=diagnostics,
        request_options=options,
        warnings=[str(item) for item in result_data.get("warnings", []) or []]
        + [str(item) for item in model_data.get("warnings", []) or []],
        errors=_normalise_errors(result_data.get("errors"))
        + _normalise_errors(model_data.get("errors")),
        dynamic_sources=dynamic_sources,
    )
