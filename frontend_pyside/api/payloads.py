
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import math
from typing import Any, Mapping

try:  
    from frontend_pyside.features.simulation.form_state import SimulationFormState
except Exception:  
    SimulationFormState = Any  


from shared_presentation.surface_payloads import serialize_surfaces, _number


def serialize_project(project: Any, form_state: SimulationFormState | None = None) -> dict[str, Any]:

    project_surfaces = list(getattr(project, "surfaces", []) or [])
    surfaces = serialize_surfaces(project_surfaces, float(form_state.source.wavelength_nm)
        if form_state is not None else float(getattr(project, "wavelength_nm", 1550.0)))

    source_payload, receiver_payload, system_payload, analysis_settings = _form_payloads(project, form_state)
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "project_id": _project_id(getattr(project, "name", "frontend-project")),
        "surfaces": surfaces,
        **system_payload,
        "source": source_payload,
        "receiver": receiver_payload,
        "aperture": {"radius_mm": system_payload["pupil_radius_mm"], "type": "circular"},
        "analysis_settings": {
            "frontend_version": str(getattr(project, "version", "v1")),
            **analysis_settings,
        },
    }
    payload["fingerprint"] = _fingerprint(payload)
    return payload


def serialize_value(value: Any) -> Any:

    if is_dataclass(value):
        return asdict(value)
    return value


def _form_payloads(project: Any, form_state: SimulationFormState | None):
    project_surfaces = list(getattr(project, "surfaces", []) or [])
    if form_state is None:
        wavelength_nm = float(getattr(project, "wavelength_nm", 1550.0))
        receiver_mfd_um = float(getattr(project, "receiver_mfd_um", 10.4))
        image_distance_mm = max(
            float(getattr(project_surfaces[-1], "thickness_mm", 0.0)) if project_surfaces else 0.0,
            1e-6,
        )
        project_pupil = _number(getattr(project, "pupil_radius_mm", None))
        fallback_pupil = max(
            (_number(getattr(surface, "semi_aperture_mm", None)) or 1.0 for surface in project_surfaces),
            default=1.0,
        )
        pupil_radius_mm = project_pupil if project_pupil and project_pupil > 0.0 else fallback_pupil
        return (
            {"wavelength_nm": wavelength_nm},
            {
                "mode_field_diameter_x_um": receiver_mfd_um,
                "mode_field_diameter_y_um": receiver_mfd_um,
            },
            {
                "object_distance_mm": 1_000_000.0,
                "image_distance_mm": image_distance_mm,
                "pupil_radius_mm": pupil_radius_mm,
            },
            {},
        )

    source = form_state.source
    receiver = form_state.receiver
    system = form_state.system
    calculation = form_state.calculation
    wavelengths = [float(source.wavelength_nm), *map(float, source.auxiliary_wavelengths_nm)]
    
    wavelengths = list(dict.fromkeys(value for value in wavelengths if value > 0.0))
    weights = [1.0 / len(wavelengths)] * len(wavelengths) if wavelengths else []
    source_payload = {
        "wavelength_nm": float(source.wavelength_nm),
        "source_type": source.source_type,
        "object_na_x": float(source.object_na_x),
        "object_na_y": float(source.object_na_y),
        "field_x_deg": float(source.field_x_deg),
        "field_y_deg": float(source.field_y_deg),
        "waist_x_mm": float(source.waist_x_um) * 1e-3,
        "waist_y_mm": float(source.waist_y_um) * 1e-3,
        "beam_quality_m2": 0.5 * (float(source.beam_quality_m2_x) + float(source.beam_quality_m2_y)),
        "beam_quality_m2_x": float(source.beam_quality_m2_x),
        "beam_quality_m2_y": float(source.beam_quality_m2_y),
        "waist_position_x_mm": float(source.waist_position_x_mm if source.waist_position_x_mm is not None else source.waist_position_mm),
        "waist_position_y_mm": float(source.waist_position_y_mm if source.waist_position_y_mm is not None else source.waist_position_mm),
        "center_x_mm": 0.0,
        "center_y_mm": 0.0,
        "axis_tilt_x_rad": math.radians(float(source.field_x_deg)),
        "axis_tilt_y_rad": math.radians(float(source.field_y_deg)),
        "spectral_wavelengths_nm": wavelengths,
        "spectral_power_weights": weights,
        "power_value": float(source.power_value),
        "power_unit": source.power_unit,
    }
    receiver_payload = {
        "receiver_type": receiver.receiver_type,
        "mode_model": receiver.mode_model,
        "na_x": float(receiver.na_x),
        "na_y": float(receiver.na_y),
        "mode_field_diameter_x_um": float(receiver.mode_field_diameter_x_um),
        "mode_field_diameter_y_um": float(receiver.mode_field_diameter_y_um),
        "offset_x_mm": float(receiver.offset_x_um) * 1e-3,
        "offset_y_mm": float(receiver.offset_y_um) * 1e-3,
        "axial_offset_z_mm": float(receiver.axial_offset_z_um) * 1e-3,
        "tilt_x_deg": math.degrees(float(receiver.tilt_x_urad) * 1e-6),
        "tilt_y_deg": math.degrees(float(receiver.tilt_y_urad) * 1e-6),
        "core_diameter_um": float(receiver.core_diameter_um),
        "core_refractive_index": float(receiver.core_refractive_index),
        "cladding_refractive_index": float(receiver.cladding_refractive_index),
        "outside_refractive_index": float(receiver.outside_refractive_index),
        "endface_transmission": float(receiver.endface_transmission),
        "fiber_length_m": float(receiver.fiber_length_m),
        "attenuation_db_per_km": float(receiver.attenuation_db_per_km),
        "connector_loss_db": float(receiver.connector_loss_db),
    }
    system_payload = {
        "object_distance_mm": float(system.object_distance_mm),
        "image_distance_mm": max(float(system.image_distance_mm), 1e-9),
        "pupil_radius_mm": max(float(system.pupil_radius_mm), 1e-9),
    }
    analysis_settings = {
        "system_field_x_deg": float(system.field_x_deg),
        "system_field_y_deg": float(system.field_y_deg),
        "auto_best_focus": bool(system.auto_best_focus),
        "thermal_compensation": bool(system.thermal_compensation),
        "requested_analyses": list(calculation.analyses),
        "calc_precision": calculation.precision,
        "calc_grid_size": int(calculation.output_grid_size),
        "calc_layout_pupil": int(calculation.layout_pupil_sample_count),
        "calc_pupil": int(calculation.pupil_sample_count),
        "calc_propagation": calculation.propagation_model,
        "calc_zero_padding": float(calculation.zero_padding_factor),
        "calc_output_extent_mm": float(calculation.output_extent_mm),
        "calc_auto_expand_output": bool(calculation.auto_expand_output),
        "calc_only_visible_results": bool(calculation.only_visible_results),
        "calc_sampling_convergence": bool(calculation.sampling_convergence_enabled),
        "calc_save_large_arrays": bool(calculation.save_large_arrays),
        "calc_high_precision_coupling": bool(calculation.high_precision_coupling_enabled),
        "incident_intensity_only": bool(calculation.incident_intensity_only),
        "alignment_enabled": bool(form_state.alignment.enabled),
        "alignment_include_dz": bool(form_state.alignment.include_dz),
        "alignment_max_offset_um": float(form_state.alignment.max_offset_um),
        "alignment_max_axial_offset_um": float(form_state.alignment.max_axial_offset_um),
        "alignment_max_tilt_urad": float(form_state.alignment.max_tilt_urad),
        "alignment_max_iterations": int(form_state.alignment.max_iterations),
        "alignment_max_function_evaluations": int(form_state.alignment.max_function_evaluations),
        "alignment_timeout_seconds": float(form_state.alignment.timeout_seconds),
    }
    return source_payload, receiver_payload, system_payload, analysis_settings


def _project_id(name: Any) -> str:
    compact = "".join(character.lower() if character.isalnum() else "-" for character in str(name))
    compact = "-".join(filter(None, compact.split("-")))
    return f"frontend-{compact or 'project'}"


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"frontend-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


__all__ = ["serialize_project", "serialize_value"]
