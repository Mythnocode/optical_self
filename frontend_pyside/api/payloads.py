
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


_APERTURE_TYPE_MAP = {
    "圆形通光孔径": "circular",
    "圆形": "circular",
    "矩形孔径": "rectangular",
    "矩形": "rectangular",
    "椭圆孔径": "elliptical",
    "椭圆": "elliptical",
    "用户孔径": "user",
}


def serialize_project(project: Any, form_state: SimulationFormState | None = None) -> dict[str, Any]:

    project_surfaces = list(getattr(project, "surfaces", []) or [])
    surfaces: list[dict[str, Any]] = []
    material_before = "AIR"
    cumulative_transform = {
        "decenter_x_mm": 0.0,
        "decenter_y_mm": 0.0,
        "tilt_x_deg": 0.0,
        "tilt_y_deg": 0.0,
        "tilt_z_deg": 0.0,
    }

    for index, surface in enumerate(project_surfaces):
        type_parameters = dict(getattr(surface, "type_parameters", {}) or {})
        surface_type = _surface_type(getattr(surface, "surface_type", "spherical"))

        
        
        
        local_transform = {
            name: float(type_parameters.get(name, 0.0) or 0.0)
            for name in cumulative_transform
        }
        if surface_type == "coordinate_break":
            for name, value in local_transform.items():
                cumulative_transform[name] += value
            effective_transform = dict(cumulative_transform)
            enabled = bool(getattr(surface, "enabled", True))
        else:
            effective_transform = {
                name: cumulative_transform[name] + local_transform[name]
                for name in cumulative_transform
            }
            enabled = bool(getattr(surface, "enabled", True))

        material_after = str(getattr(surface, "material", "AIR") or "AIR")
        if surface_type in {"mirror", "stop", "coordinate_break", "detector"}:
            material_after = material_before

        coefficients = _asphere_coefficients(type_parameters)
        groove_density = _number(type_parameters.get("groove_density_lpm"))
        grating_period_um = None
        if groove_density and groove_density > 0.0:
            
            grating_period_um = 1000.0 / groove_density
        order = int(type_parameters.get("diffraction_order", 1) or 1)
        efficiency = _grating_efficiency(type_parameters)

        clear_diameter = _number(type_parameters.get("_clear_aperture_mm"))
        semi_aperture = _number(getattr(surface, "semi_aperture_mm", None))
        clear_aperture_radius = (
            clear_diameter / 2.0 if clear_diameter is not None and clear_diameter > 0 else semi_aperture
        )
        mechanical = _number(getattr(surface, "mechanical_diameter_mm", None))
        if mechanical is None or mechanical <= 0:
            mechanical = 2.0 * clear_aperture_radius if clear_aperture_radius else None

        metadata = {
            "name": str(getattr(surface, "name", f"S{index + 1}")),
            "group_id": str(getattr(surface, "group_id", "")),
            "element_id": str(getattr(surface, "element_id", "")),
            "surface_id": str(getattr(surface, "surface_id", "")),
            "frontend_surface_type": str(getattr(surface, "surface_type", surface_type)),
            "coating_preset": str(getattr(surface, "coating", "无") or "无"),
            "note": str(getattr(surface, "note", "") or ""),
            "type_parameters": type_parameters,
        }
        cylinder_axis_deg = float(
            type_parameters.get(
                "cylinder_axis_deg", type_parameters.get("axis_angle_deg", 0.0)
            )
            or 0.0
        ) % 180.0
        if surface_type == "cylindrical":
            metadata.update(
                {
                    "surface_geometry": "cylindrical",
                    "cylinder_axis_deg": cylinder_axis_deg,
                    "cylinder_power_axis_deg": (cylinder_axis_deg + 90.0) % 180.0,
                    "cylinder_axis_definition": "zero_power_axis",
                }
            )
        if surface_type == "mirror":
            metadata["reflectivity"] = float(type_parameters.get("reflectivity", 1.0) or 1.0)
            metadata["mirror_mode"] = str(type_parameters.get("mirror_mode", "理想反射"))
        if surface_type == "grating":
            metadata.update(
                {
                    "grating_mode": str(type_parameters.get("grating_mode", "反射式")),
                    "groove_angle_deg": float(type_parameters.get("groove_angle_deg", 0.0) or 0.0),
                    "blaze_angle_deg": float(type_parameters.get("blaze_angle_deg", 0.0) or 0.0),
                    "efficiency_model": str(type_parameters.get("efficiency_model", "标量近似")),
                }
            )

        surfaces.append(
            {
                "index": index,
                "surface_type": surface_type,
                "radius_mm": _surface_radius(surface_type, getattr(surface, "radius_mm", None)),
                "distance_to_next_mm": float(getattr(surface, "thickness_mm", 0.0) or 0.0),
                "material_before": material_before,
                "material_after": material_after,
                "clear_aperture_mm": clear_aperture_radius,
                "conic": float(getattr(surface, "conic", 0.0) or 0.0),
                "asphere_a2": float(type_parameters.get("asphere_a2", 0.0) or 0.0),
                "asphere_coefficients": coefficients,
                "coating_layers": _coating_layers(
                    getattr(surface, "coating", "无"),
                    type_parameters,
                    wavelength_nm=(
                        float(form_state.source.wavelength_nm)
                        if form_state is not None
                        else float(getattr(project, "wavelength_nm", 1550.0))
                    ),
                ),
                "surface_absorption_fraction": _absorption_fraction(surface_type, type_parameters),
                "roughness_rms_nm": max(0.0, float(getattr(surface, "roughness_nm", 0.0) or 0.0)),
                "grating_period_um": grating_period_um,
                "grating_orders": [order] if surface_type in {"grating", "binary_diffractive"} else [],
                "grating_efficiencies": [efficiency] if surface_type in {"grating", "binary_diffractive"} else [],
                "aperture_type": _APERTURE_TYPE_MAP.get(
                    str(type_parameters.get("_aperture_type", "圆形通光孔径")), "circular"
                ),
                "mechanical_diameter_mm": mechanical,
                "enabled": enabled,
                "cylinder_axis_deg": cylinder_axis_deg,
                **effective_transform,
                "metadata": metadata,
            }
        )
        material_before = material_after
        if surface_type == "coordinate_break" and bool(type_parameters.get("return_to_previous", False)):
            cumulative_transform = {name: 0.0 for name in cumulative_transform}

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
        "waist_position_x_mm": float(source.waist_position_mm),
        "waist_position_y_mm": float(source.waist_position_mm),
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


def _surface_type(value: Any) -> str:
    mapping = {
        "球面": "spherical",
        "非球面": "aspheric",
        "柱面": "cylindrical",
        "柱面镜": "cylindrical",
        "平面": "plane",
        "光阑": "stop",
        "反射镜": "mirror",
        "光栅": "grating",
        "衍射光栅": "grating",
        "坐标断点": "coordinate_break",
        "二元衍射面": "binary_diffractive",
        "探测器/像面": "detector",
        "用户自定义面": "user_defined",
    }
    text = str(value or "spherical").strip()
    return mapping.get(text, text.lower().replace(" ", "_"))


def _surface_radius(surface_type: str, value: Any) -> float | None:
    if surface_type in {"plane", "stop", "coordinate_break", "detector"}:
        return None
    number = _number(value)
    return None if number is None or abs(number) < 1e-15 else number


def _asphere_coefficients(parameters: Mapping[str, Any]) -> list[float]:
    raw = parameters.get("asphere_coefficients")
    if isinstance(raw, (list, tuple)):
        return [float(value) for value in raw]
    
    values = [float(parameters.get(key, 0.0) or 0.0) for key in ("a4", "a6", "a8")]
    while values and abs(values[-1]) < 1e-30:
        values.pop()
    return values


def _coating_layers(preset: Any, parameters: Mapping[str, Any], wavelength_nm: float) -> list[dict[str, Any]]:
    custom = parameters.get("coating_layers")
    if isinstance(custom, list):
        return [dict(layer) for layer in custom if isinstance(layer, Mapping)]
    name = str(preset or "无").strip()
    quarter_wave = max(float(wavelength_nm), 1e-9) / 4.0
    if name == "增透膜":
        return [{"name": "AR-MgF2", "refractive_index": 1.38, "thickness_nm": quarter_wave / 1.38}]
    if name == "高反膜":
        return [
            {"name": "HR-H", "refractive_index": 2.10, "thickness_nm": quarter_wave / 2.10},
            {"name": "HR-L", "refractive_index": 1.45, "thickness_nm": quarter_wave / 1.45},
            {"name": "HR-H2", "refractive_index": 2.10, "thickness_nm": quarter_wave / 2.10},
            {"name": "HR-L2", "refractive_index": 1.45, "thickness_nm": quarter_wave / 1.45},
        ]
    if name == "金属膜":
        return [
            {
                "name": "metal",
                "refractive_index": float(parameters.get("metal_n", 0.2) or 0.2),
                "extinction_coefficient": float(parameters.get("metal_k", 6.0) or 6.0),
                "thickness_nm": float(parameters.get("metal_thickness_nm", 100.0) or 100.0),
            }
        ]
    return []


def _absorption_fraction(surface_type: str, parameters: Mapping[str, Any]) -> float:
    explicit = _number(parameters.get("surface_absorption_fraction"))
    if explicit is not None:
        return min(max(explicit, 0.0), 1.0 - 1e-12)
    if surface_type == "mirror":
        reflectivity = min(max(float(parameters.get("reflectivity", 1.0) or 1.0), 0.0), 1.0)
        return min(max(1.0 - reflectivity, 0.0), 1.0 - 1e-12)
    return 0.0


def _grating_efficiency(parameters: Mapping[str, Any]) -> float:
    explicit = _number(parameters.get("grating_efficiency"))
    if explicit is not None:
        return min(max(explicit, 0.0), 1.0)
    model = str(parameters.get("efficiency_model", "标量近似"))
    return 1.0 if model == "理想" else 0.8


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _project_id(name: Any) -> str:
    compact = "".join(character.lower() if character.isalnum() else "-" for character in str(name))
    compact = "-".join(filter(None, compact.split("-")))
    return f"frontend-{compact or 'project'}"


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"frontend-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


__all__ = ["serialize_project", "serialize_value"]
