
from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
import hashlib
import json
from typing import Any, Mapping

_RECEIVER_ALIGNMENT_KEYS = {
    "offset_x_mm", "offset_y_mm", "tilt_x_rad", "tilt_y_rad", "tilt_x_deg",
    "tilt_y_deg", "receiver_axial_offset_z_mm", "axial_offset_z_mm",
}
_RECEIVER_MODE_SIZE_KEYS = {"mode_field_diameter_x_um", "mode_field_diameter_y_um"}
_RESULT_ONLY_KEYS = {
    "include_diagnostic_arrays", "result_array_policy", "include_breakdown",
    "include_convergence", "convergence_grid_sizes",
}


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if isinstance(value, complex):
        return {"real": float(value.real), "imag": float(value.imag)}
    return value


def stable_digest(value: Any) -> str:
    encoded = json.dumps(
        _plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_project_dependency_keys(
    project_data: Mapping[str, Any], options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:

    project = dict(project_data or {})
    request_options = dict(options or {})
    source_payload = {
        "source": project.get("source", {}),
        "aperture": project.get("aperture", {}),
        "object_distance_mm": project.get("object_distance_mm"),
        "pupil_radius_mm": project.get("pupil_radius_mm"),
        "wavelength_nm": (project.get("source") or {}).get("wavelength_nm"),
        
        
        
        
        
        "environment_temperature_c": request_options.get("environment_temperature_c", 20.0),
        "reference_temperature_c": request_options.get("reference_temperature_c", 20.0),
        "material_thermal_models": request_options.get("material_thermal_models", {}),
        "environment_pressure_kpa": request_options.get("environment_pressure_kpa", 101.325),
        "geometric": request_options.get("geometric", {}),
    }
    source_key = stable_digest(source_payload)
    cumulative: dict[str, Any] = {"source": source_payload}
    surface_keys: list[str] = []
    for index, surface in enumerate(list(project.get("surfaces", []) or [])):
        cumulative[f"surface_{index}"] = surface
        surface_keys.append(stable_digest(cumulative))

    final_optical_key = surface_keys[-1] if surface_keys else source_key
    hybrid = dict(request_options.get("hybrid", {}) or {})
    receiver = dict(project.get("receiver", {}) or {})
    propagation_options = {
        key: value for key, value in hybrid.items()
        if key not in _RECEIVER_ALIGNMENT_KEYS
        and key not in _RECEIVER_MODE_SIZE_KEYS
        and key not in _RESULT_ONLY_KEYS
        and not key.startswith("fiber_")
        and not key.startswith("receiver_na")
        and key not in {"mode_model", "receiver_medium_refractive_index"}
    }
    receiver_field_key = stable_digest(
        {
            "final_optical": final_optical_key,
            
            
            
            "image_distance_mm": project.get("image_distance_mm"),
            "propagation": propagation_options,
        }
    )
    fiber_mode_payload = {
        "mode_model": hybrid.get("mode_model", receiver.get("mode_model", "gaussian")),
        "mfd_x_um": hybrid.get("mode_field_diameter_x_um", receiver.get("mode_field_diameter_x_um")),
        "mfd_y_um": hybrid.get("mode_field_diameter_y_um", receiver.get("mode_field_diameter_y_um")),
        "receiver_na_x": hybrid.get("receiver_na_x", receiver.get("na_x")),
        "receiver_na_y": hybrid.get("receiver_na_y", receiver.get("na_y")),
        "receiver_medium_refractive_index": hybrid.get(
            "receiver_medium_refractive_index", receiver.get("outside_refractive_index", 1.0)
        ),
        "fiber_core_radius_um": hybrid.get(
            "fiber_core_radius_um",
            None if receiver.get("core_diameter_um") is None else float(receiver.get("core_diameter_um")) / 2.0,
        ),
        "fiber_n_core": hybrid.get("fiber_n_core", receiver.get("core_refractive_index")),
        "fiber_n_clad": hybrid.get("fiber_n_clad", receiver.get("cladding_refractive_index")),
        "imported_mode_values": hybrid.get("imported_mode_values", receiver.get("imported_mode_values")),
    }
    fiber_mode_key = stable_digest(fiber_mode_payload)
    alignment_payload = {
        "offset_x_mm": hybrid.get("offset_x_mm", receiver.get("offset_x_mm", 0.0)),
        "offset_y_mm": hybrid.get("offset_y_mm", receiver.get("offset_y_mm", 0.0)),
        "axial_offset_z_mm": hybrid.get(
            "receiver_axial_offset_z_mm", hybrid.get("axial_offset_z_mm", receiver.get("axial_offset_z_mm", 0.0))
        ),
        "tilt_x_rad": hybrid.get("tilt_x_rad"),
        "tilt_y_rad": hybrid.get("tilt_y_rad"),
        "tilt_x_deg": hybrid.get("tilt_x_deg", receiver.get("tilt_x_deg", 0.0)),
        "tilt_y_deg": hybrid.get("tilt_y_deg", receiver.get("tilt_y_deg", 0.0)),
    }
    receiver_passive_payload = {
        "endface_transmission": hybrid.get(
            "fiber_facet_transmission_override", receiver.get("endface_transmission", 1.0)
        ),
        "fiber_length_m": hybrid.get("fiber_length_m", receiver.get("fiber_length_m", 0.0)),
        "attenuation_db_per_km": hybrid.get(
            "fiber_attenuation_db_per_km", receiver.get("attenuation_db_per_km", 0.0)
        ),
        "connector_loss_db": hybrid.get("fiber_connector_loss_db", receiver.get("connector_loss_db", 0.0)),
    }
    receiver_passive_key = stable_digest(receiver_passive_payload)
    overlap_key = stable_digest({
        "receiver_field": receiver_field_key,
        "fiber_mode": fiber_mode_key,
        "receiver_passive": receiver_passive_key,
        "alignment": alignment_payload,
    })
    return {
        "source": source_key,
        "surface_outputs": surface_keys,
        "final_optical": final_optical_key,
        "receiver_field": receiver_field_key,
        "fiber_mode": fiber_mode_key,
        "receiver_passive": receiver_passive_key,
        "overlap": overlap_key,
    }


def prepared_coupling_key(trace: Any, options: Any) -> str:

    if is_dataclass(options):
        payload = asdict(options)
    elif hasattr(options, "model_dump"):
        payload = options.model_dump(mode="json")
    else:
        payload = dict(vars(options)) if hasattr(options, "__dict__") else _plain(options)
    payload = dict(payload or {})
    for key in _RECEIVER_ALIGNMENT_KEYS | _RESULT_ONLY_KEYS:
        payload.pop(key, None)
    if not bool(payload.get("vector_coupling_enabled")) and not bool(payload.get("polarization_sensitive")):
        for key in _RECEIVER_MODE_SIZE_KEYS:
            payload.pop(key, None)
    trace_identity = {
        "object_id": id(trace),
        "wavelength_nm": getattr(trace, "wavelength_nm", None),
        "ray_count": int(getattr(getattr(trace, "valid_mask", ()), "size", 0) or 0),
    }
    return stable_digest({"trace": trace_identity, "prepared_options": payload})


__all__ = ["build_project_dependency_keys", "prepared_coupling_key", "stable_digest"]
