
from __future__ import annotations
from .dependency_graph import build_project_dependency_keys

from copy import deepcopy
from typing import Any
import re

from .context import ExecutionProfile, SimulationContext, SimulationScene
from .project_mapper import build_optical_system
from optical_core.models.domain.aperture import CircularApertureDefinition
from optical_core.models.domain.receiver import FiberReceiver
from optical_core.models.domain.source import OpticalSource


_FORBIDDEN_REFERENCE_TOKENS = (
    "zemax",
    "opticstudio",
    "zosapi",
    "zos_api",
    "pop_reference",
    "reference_field",
    "reference_intensity",
    "reference_phase",
    "reference_complex",
)

_TRACE_KEYS = {
    "wavelength_nm", "pupil_sample_count", "pupil_radius_mm", "explicit_pupil_samples",
    "source_model", "object_distance_mm", "object_space_na", "field_x_deg", "field_y_deg",
    "apodization_type", "apodization_factor", "apodization_factor_x",
    "apodization_factor_y", "include_source_to_pupil_opl",
    "propagate_to_image", "evaluate_apertures", "max_intersection_iterations", "start_z_mm",
    "sampling_role", "trace_output_level",
}
_WAVE_KEYS = {
    "wavelength_nm", "grid_size", "extent_mm", "propagation_distance_mm", "distance_mm", "method",
    "aperture_type", "aperture_diameter_mm", "aperture_width_mm", "aperture_height_mm",
    "slit_width_mm", "gaussian_waist_mm", "normalize", "refractive_index",
}




def _canonical_source_model(value: Any) -> str:


    key = str(value or "parallel_pupil").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "parallel": "parallel_pupil",
        "collimated": "parallel_pupil",
        "collimated_beam": "parallel_pupil",
        "parallel_pupil": "parallel_pupil",
        "gaussian": "gaussian",
        "gaussian_pupil": "gaussian",
        "gaussian_beam": "gaussian",
        "gaussian_source": "gaussian",
        "realistic_gaussian": "gaussian",
        "measured_gaussian": "gaussian",
        "object_space_na": "object_space_na",
        "finite_object_na": "object_space_na",
        "point_source": "object_space_na",
        "finite_object": "object_space_na",
    }
    try:
        return aliases[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported source_type {value!r}; use parallel_pupil, gaussian, or object_space_na"
        ) from exc

def _read(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _dump(obj: Any) -> Any:

    if hasattr(obj, "model_dump"):
        return _dump(obj.model_dump())
    if isinstance(obj, dict):
        return {str(key): _dump(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dump(value) for value in obj]
    if hasattr(obj, "__dict__"):
        return {str(key): _dump(value) for key, value in vars(obj).items()}
    return deepcopy(obj)


def _parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for name, index in re.findall(r"([^\.\[\]]+)|\[(\d+)\]", str(path)):
        parts.append(int(index) if index else name)
    return parts


def _set_path(data: Any, path: str, value: Any) -> None:
    parts = _parse_path(path)
    if not parts:
        raise ValueError(f"invalid parameter path: {path!r}")
    current = data
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def _assert_no_reference_data(value: Any, path: str = "request") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in _FORBIDDEN_REFERENCE_TOKENS):
                raise ValueError(f"参考/Zemax 数据禁止进入生产仿真输入: {path}.{key}")
            _assert_no_reference_data(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_reference_data(item, f"{path}[{index}]")


def _precision_profile(precision: str, random_seed: int) -> ExecutionProfile:
    profiles = {
        "test": (9, 33, 10, False),
        "preview": (9, 65, 10, False),
        "standard": (25, 129, 14, True),
        "high": (65, 257, 24, True),
    }
    key = str(precision).strip().lower()
    if key not in profiles:
        raise ValueError(f"unsupported precision profile: {precision!r}")
    sample_count, grid_size, iterations, record = profiles[key]
    return ExecutionProfile(str(precision), sample_count, grid_size, iterations, record, int(random_seed))




def _normalise_options(project_data: dict[str, Any], request_options: dict[str, Any], profile: ExecutionProfile) -> dict[str, Any]:
    options: dict[str, Any] = {"geometric": {}, "wave": {}, "hybrid": {}}
    analysis_settings = dict(project_data.get("analysis_settings", {}) or {})
    for source in (analysis_settings, request_options):
        for group in ("geometric", "wave", "hybrid"):
            options[group].update(dict(source.get(group, {}) or {}))
        for key, value in source.items():
            if key in {"geometric", "wave", "hybrid"}:
                continue
            if key in _TRACE_KEYS:
                options["geometric"][key] = value
                options["hybrid"][key] = value
            if key in _WAVE_KEYS:
                options["wave"][key] = value
            options[key] = value
    options["geometric"].setdefault("pupil_sample_count", profile.pupil_sample_count)
    options["hybrid"].setdefault("pupil_sample_count", profile.pupil_sample_count)
    options["wave"].setdefault("grid_size", profile.wave_grid_size)
    options["geometric"].setdefault("max_intersection_iterations", profile.max_intersection_iterations)
    options["hybrid"].setdefault("max_intersection_iterations", profile.max_intersection_iterations)
    
    
    
    _PRECISION_TO_COUPLING = {
        "test": "fast",
        "preview": "preview",
        "standard": "balanced",
        "high": "quantitative",
    }
    coupling_mode = _PRECISION_TO_COUPLING.get(profile.precision, "balanced")
    options["hybrid"].setdefault("precision_mode", coupling_mode)
    return options


def compile_simulation_context(request: Any) -> SimulationContext:
    project_data = _dump(_read(request, "project"))
    changes = list(_read(request, "parameter_changes", []) or [])
    for change in changes:
        path = str(_read(change, "path", ""))
        if any(token in path.lower() for token in _FORBIDDEN_REFERENCE_TOKENS):
            raise ValueError(f"参考/Zemax 参数路径禁止进入生产仿真: {path}")
        _set_path(project_data, path, _read(change, "value"))

    request_options = dict(_read(request, "options", {}) or {})
    _assert_no_reference_data(request_options, "request.options")
    _assert_no_reference_data(project_data.get("analysis_settings", {}), "project.analysis_settings")

    precision = str(_read(request, "precision", "standard"))
    raw_seed = _read(request, "random_seed", 42)
    profile = _precision_profile(precision, 42 if raw_seed is None else int(raw_seed))
    options = _normalise_options(project_data, request_options, profile)
    compile_warnings: list[str] = []
    system = build_optical_system(
        project_data, simulation_options=request_options, warning_sink=compile_warnings
    )

    source_data = dict(project_data.get("source", {}) or {})
    source = OpticalSource(
        wavelength_nm=float(source_data.get("wavelength_nm", system.wavelength_nm)),
        source_type=_canonical_source_model(source_data.get("source_type", "parallel_pupil")),
        object_na_x=float(source_data.get("object_na_x", 0.0) or 0.0),
        object_na_y=float(source_data.get("object_na_y", 0.0) or 0.0),
        field_x_deg=float(source_data.get("field_x_deg", 0.0) or 0.0),
        field_y_deg=float(source_data.get("field_y_deg", 0.0) or 0.0),
        waist_x_mm=float(source_data.get("waist_x_mm", 0.0) or 0.0),
        waist_y_mm=float(source_data.get("waist_y_mm", 0.0) or 0.0),
        beam_quality_m2=float(source_data.get("beam_quality_m2", source_data.get("m2", 1.0)) or 1.0),
        beam_quality_m2_x=(None if source_data.get("beam_quality_m2_x") is None else float(source_data["beam_quality_m2_x"])),
        beam_quality_m2_y=(None if source_data.get("beam_quality_m2_y") is None else float(source_data["beam_quality_m2_y"])),
        waist_position_x_mm=float(source_data.get("waist_position_x_mm", 0.0) or 0.0),
        waist_position_y_mm=float(source_data.get("waist_position_y_mm", 0.0) or 0.0),
        center_x_mm=float(source_data.get("center_x_mm", 0.0) or 0.0),
        center_y_mm=float(source_data.get("center_y_mm", 0.0) or 0.0),
        axis_tilt_x_rad=float(source_data.get("axis_tilt_x_rad", 0.0) or 0.0),
        axis_tilt_y_rad=float(source_data.get("axis_tilt_y_rad", 0.0) or 0.0),
        power_drift_fraction=float(source_data.get("power_drift_fraction", 0.0) or 0.0),
        spectral_fwhm_nm=float(source_data.get("spectral_fwhm_nm", 0.0) or 0.0),
        spectral_sample_count=int(source_data.get("spectral_sample_count", 1) or 1),
        spectral_wavelengths_nm=tuple(float(v) for v in source_data.get("spectral_wavelengths_nm", ()) or ()),
        spectral_power_weights=tuple(float(v) for v in source_data.get("spectral_power_weights", ()) or ()),
        coherence_groups=tuple(source_data.get("coherence_groups", ()) or ()),
        amplitude_map=source_data.get("amplitude_map"),
        phase_map_rad=source_data.get("phase_map_rad"),
        power_value=source_data.get("power_value"),
        power_unit=source_data.get("power_unit"),
    )

    receiver_data = project_data.get("receiver")
    receiver = None
    if receiver_data:
        receiver_data = dict(receiver_data)
        receiver = FiberReceiver(
            na_x=float(receiver_data.get("na_x", 0.0) or 0.0),
            na_y=float(receiver_data.get("na_y", 0.0) or 0.0),
            mode_field_diameter_x_um=float(receiver_data.get("mode_field_diameter_x_um", 5.0) or 5.0),
            mode_field_diameter_y_um=float(receiver_data.get("mode_field_diameter_y_um", 5.0) or 5.0),
            offset_x_mm=float(receiver_data.get("offset_x_mm", 0.0) or 0.0),
            offset_y_mm=float(receiver_data.get("offset_y_mm", 0.0) or 0.0),
            axial_offset_z_mm=float(receiver_data.get("axial_offset_z_mm", 0.0) or 0.0),
            tilt_x_deg=float(receiver_data.get("tilt_x_deg", 0.0) or 0.0),
            tilt_y_deg=float(receiver_data.get("tilt_y_deg", 0.0) or 0.0),
            receiver_type=str(receiver_data.get("receiver_type", "single_mode_fiber")),
            mode_model=str(receiver_data.get("mode_model", "gaussian")).lower(),
            core_diameter_um=(None if receiver_data.get("core_diameter_um") is None else float(receiver_data["core_diameter_um"])),
            core_refractive_index=(None if receiver_data.get("core_refractive_index") is None else float(receiver_data["core_refractive_index"])),
            cladding_refractive_index=(None if receiver_data.get("cladding_refractive_index") is None else float(receiver_data["cladding_refractive_index"])),
            outside_refractive_index=float(receiver_data.get("outside_refractive_index", 1.0) or 1.0),
            endface_transmission=float(receiver_data.get("endface_transmission", 1.0) or 0.0),
            fiber_length_m=float(receiver_data.get("fiber_length_m", 0.0) or 0.0),
            attenuation_db_per_km=float(receiver_data.get("attenuation_db_per_km", 0.0) or 0.0),
            connector_loss_db=float(receiver_data.get("connector_loss_db", 0.0) or 0.0),
        )

    aperture_data = dict(project_data.get("aperture", {}) or {})
    aperture_radius = float(aperture_data.get("radius_mm", aperture_data.get("pupil_radius_mm", project_data.get("pupil_radius_mm", 1.0))) or 1.0)
    aperture = CircularApertureDefinition(radius_mm=aperture_radius)

    
    for group in ("geometric", "hybrid"):
        options[group].setdefault("wavelength_nm", source.wavelength_nm)
        options[group].setdefault("pupil_radius_mm", aperture.radius_mm)
        options[group].setdefault("source_model", source.source_type)
        options[group].setdefault("object_distance_mm", system.object_distance_mm)
        options[group].setdefault("object_space_na", max(source.object_na_x, source.object_na_y))
        options[group].setdefault("field_x_deg", source.field_x_deg)
        options[group].setdefault("field_y_deg", source.field_y_deg)
        options[group].setdefault("beam_quality_m2", source.beam_quality_m2)
    options["wave"].setdefault("wavelength_nm", source.wavelength_nm)
    for group in ("geometric", "wave", "hybrid"):
        options[group].setdefault("random_seed", profile.random_seed)
    if receiver is not None:
        hybrid = options["hybrid"]
        hybrid.setdefault("receiver_na_x", receiver.na_x)
        hybrid.setdefault("receiver_na_y", receiver.na_y)
        hybrid.setdefault("mode_field_diameter_x_um", receiver.mode_field_diameter_x_um)
        hybrid.setdefault("mode_field_diameter_y_um", receiver.mode_field_diameter_y_um)
        hybrid.setdefault("offset_x_mm", receiver.offset_x_mm)
        hybrid.setdefault("offset_y_mm", receiver.offset_y_mm)
        hybrid.setdefault("axial_offset_z_mm", receiver.axial_offset_z_mm)
        hybrid.setdefault("tilt_x_deg", receiver.tilt_x_deg)
        hybrid.setdefault("tilt_y_deg", receiver.tilt_y_deg)
        hybrid.setdefault("mode_model", receiver.mode_model)
        hybrid.setdefault("fiber_core_radius_um", None if receiver.core_diameter_um is None else receiver.core_diameter_um / 2.0)
        hybrid.setdefault("fiber_n_core", receiver.core_refractive_index)
        hybrid.setdefault("fiber_n_clad", receiver.cladding_refractive_index)
        hybrid.setdefault("receiver_medium_refractive_index", receiver.outside_refractive_index)
        hybrid.setdefault("fiber_facet_transmission_override", receiver.endface_transmission)
        hybrid.setdefault("fiber_length_m", receiver.fiber_length_m)
        hybrid.setdefault("fiber_attenuation_db_per_km", receiver.attenuation_db_per_km)
        hybrid.setdefault("fiber_connector_loss_db", receiver.connector_loss_db)

    scene = SimulationScene(system, source, receiver, aperture, profile, options, project_data)
    context = SimulationContext(scene=scene, warnings=compile_warnings)
    context.metadata["dependency_keys"] = build_project_dependency_keys(project_data, options)
    context.metadata["request_fields_applied"] = {
        "parameter_changes": len(changes),
        "precision": precision,
        "random_seed": profile.random_seed,
        "source": True,
        "source_model": source.source_type,
        "source_waist_x_mm": source.waist_x_mm,
        "source_waist_y_mm": source.waist_y_mm,
        "source_beam_quality_m2": source.beam_quality_m2,
        "receiver": receiver is not None,
        "aperture": True,
        "analysis_settings": bool(project_data.get("analysis_settings")),
    }
    context.metadata["thermal_environment"] = {
        "temperature_c": float(request_options.get("environment_temperature_c", 20.0)),
        "reference_temperature_c": float(request_options.get("reference_temperature_c", 20.0)),
        "material_model_count": len(dict(request_options.get("material_thermal_models", {}) or {})),
        "temperature_model_source": "explicit_native_options",
    }
    context.metadata["source_power"] = {
        "value": source.power_value,
        "unit": source.power_unit,
        "applied_to_absolute_field": False,
        "reason": "absolute complex-field calibration requires a detector/source radiometric model",
    }
    return context
