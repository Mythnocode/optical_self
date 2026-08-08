from __future__ import annotations

from typing import Any
import warnings

from optical_core.materials import default_material_database
from optical_core.materials.thermal import (
    ThermalOpticModel,
    linear_thermal_scale,
    refractive_index_at_temperature,
)
from optical_core.models.domain.material import OpticalMaterial
from optical_core.models.domain.coating import CoatingLayerSpec
from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.domain.system import SequentialOpticalSystem


def _read(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _build_material_table(
    material_names: set[str],
    *,
    wavelength_nm: float,
    temperature_c: float = 20.0,
    thermal_models: dict[str, Any] | None = None,
    warning_sink: list[str] | None = None,
) -> dict[str, OpticalMaterial]:

    db = default_material_database()
    materials: dict[str, OpticalMaterial] = {}
    for name in sorted(material_names):
        clean = str(name or "AIR")
        if clean.lower() in {"air", "vacuum", "none", ""}:
            materials[clean] = OpticalMaterial(name=clean, refractive_index=1.0)
            continue
        try:
            n_value = float(clean)
            if n_value <= 0.0:
                raise ValueError
        except ValueError:
            try:
                n_value = float(db.get_n(clean, wavelength_nm=wavelength_nm))
            except Exception as exc:
                message = (
                    f"材料 {clean!r} 在 {wavelength_nm:g} nm 无可用色散数据（{exc}）；"
                    "已显式回退为空气 n=1.0。"
                )
                warnings.warn(message, UserWarning, stacklevel=2)
                if warning_sink is not None:
                    warning_sink.append(message)
                n_value = 1.0
        model_raw = dict(thermal_models or {}).get(clean)
        if model_raw is None:
            model_raw = dict(thermal_models or {}).get(clean.lower())
        if model_raw is not None:
            n_value = refractive_index_at_temperature(
                n_value, temperature_c, ThermalOpticModel.from_mapping(model_raw)
            )
        materials[clean] = OpticalMaterial(name=clean, refractive_index=n_value)
        materials.setdefault(clean.lower(), materials[clean])
    materials.setdefault("AIR", OpticalMaterial(name="AIR", refractive_index=1.0))
    materials.setdefault("air", materials["AIR"])
    return materials


def build_optical_system(
    project: Any,
    *,
    simulation_options: dict[str, Any] | None = None,
    warning_sink: list[str] | None = None,
) -> SequentialOpticalSystem:

    sim_opts = dict(simulation_options or {})
    temperature_c = float(sim_opts.get("environment_temperature_c", 20.0))
    thermal_models = dict(sim_opts.get("material_thermal_models", {}) or {})
    surface_cte = dict(sim_opts.get("surface_thermal_expansion_ppm_per_c", {}) or {})
    raw_surfaces = list(_read(project, "surfaces", default=()) or ())
    compiled_inputs: list[tuple[int, Any, float, float]] = []
    axial_z = 0.0
    for index, raw in enumerate(raw_surfaces):
        raw_distance = float(_read(raw, "distance_to_next_mm", "thickness_mm", "thickness", default=0.0) or 0.0)
        enabled = bool(_read(raw, "enabled", default=True))
        surface_type = str(_read(raw, "surface_type", default="refractive")).strip().lower()
        
        
        
        if enabled and surface_type not in {"coordinate_break", "coordinate-break"}:
            compiled_inputs.append((index, raw, axial_z, raw_distance))
        axial_z += raw_distance

    surfaces: list[OpticalSurface] = []
    previous_material = "AIR"
    for compiled_index, (source_index, raw, vertex_z, raw_distance) in enumerate(compiled_inputs):
        material_before = _read(raw, "material_before", "before_material", "material_before_name", default=previous_material)
        material_after = _read(raw, "material_after", "after_material", "material_after_name", "material", default="AIR")
        model_raw = thermal_models.get(str(material_after)) or thermal_models.get(str(material_after).lower())
        expansion_model = ThermalOpticModel.from_mapping(model_raw) if model_raw is not None else ThermalOpticModel()
        if str(source_index) in surface_cte or source_index in surface_cte:
            override = surface_cte.get(str(source_index), surface_cte.get(source_index))
            expansion_model = ThermalOpticModel(
                reference_temperature_c=float(sim_opts.get("reference_temperature_c", expansion_model.reference_temperature_c)),
                dn_dt_per_c=expansion_model.dn_dt_per_c,
                d2n_dt2_per_c2=expansion_model.d2n_dt2_per_c2,
                cte_per_c=float(override) * 1.0e-6,
            )
        thermal_scale = linear_thermal_scale(temperature_c, expansion_model)
        raw_radius = _read(raw, "radius_mm", "radius", default=None)
        if compiled_index + 1 < len(compiled_inputs):
            next_vertex_z = compiled_inputs[compiled_index + 1][2]
            effective_distance = float(next_vertex_z - vertex_z)
        else:
            effective_distance = raw_distance
        surfaces.append(
            OpticalSurface(
                index=int(_read(raw, "index", default=source_index)),
                surface_type=str(_read(raw, "surface_type", default="refractive")),
                radius_mm=(None if raw_radius is None else float(raw_radius) * thermal_scale),
                distance_to_next_mm=effective_distance * thermal_scale,
                material_before=str(material_before or "AIR"),
                material_after=str(material_after or "AIR"),
                clear_aperture_mm=_read(raw, "clear_aperture_mm", "semi_diameter_mm", "aperture_mm", default=None),
                conic=float(_read(raw, "conic", default=0.0) or 0.0),
                asphere_a2=float(_read(raw, "asphere_a2", "a2_coefficient", "a2", "A2", default=0.0) or 0.0),
                asphere_coefficients=tuple(_read(raw, "asphere_coefficients", "asphere_coeffs", default=()) or ()),
                coating_layers=tuple(
                    CoatingLayerSpec(
                        name=str(_read(layer, "name", default="layer")),
                        refractive_index=float(_read(layer, "refractive_index", "n", default=1.0)),
                        extinction_coefficient=float(_read(layer, "extinction_coefficient", "k", default=0.0)),
                        thickness_nm=float(_read(layer, "thickness_nm", default=0.0)),
                        dn_dt_per_c=float(_read(layer, "dn_dt_per_c", default=0.0)),
                        dk_dt_per_c=float(_read(layer, "dk_dt_per_c", default=0.0)),
                        cte_per_c=float(_read(layer, "cte_per_c", default=0.0)),
                        reference_temperature_c=float(_read(layer, "reference_temperature_c", default=20.0)),
                    )
                    for layer in (_read(raw, "coating_layers", default=()) or ())
                ),
                surface_absorption_fraction=float(_read(raw, "surface_absorption_fraction", default=0.0) or 0.0),
                roughness_rms_nm=float(_read(raw, "roughness_rms_nm", default=0.0) or 0.0),
                grating_period_um=_read(raw, "grating_period_um", default=None),
                grating_orders=tuple(int(v) for v in (_read(raw, "grating_orders", default=()) or ())),
                grating_efficiencies=tuple(float(v) for v in (_read(raw, "grating_efficiencies", default=()) or ())),
                aperture_type=str(_read(raw, "aperture_type", default="circular") or "circular"),
                mechanical_diameter_mm=_read(raw, "mechanical_diameter_mm", default=None),
                enabled=True,
                decenter_x_mm=float(_read(raw, "decenter_x_mm", default=0.0) or 0.0) * thermal_scale,
                decenter_y_mm=float(_read(raw, "decenter_y_mm", default=0.0) or 0.0) * thermal_scale,
                tilt_x_deg=float(_read(raw, "tilt_x_deg", default=0.0) or 0.0),
                tilt_y_deg=float(_read(raw, "tilt_y_deg", default=0.0) or 0.0),
                tilt_z_deg=float(_read(raw, "tilt_z_deg", default=0.0) or 0.0),
                metadata=dict(_read(raw, "metadata", default={}) or {}),
            )
        )
        previous_material = str(material_after or "AIR")

    source = _read(project, "source", default=None)
    wavelength_nm = float(_read(source, "wavelength_nm", default=_read(project, "wavelength_nm", default=550.0)) or 550.0)
    material_names = {"AIR", "air"}
    for surface in surfaces:
        material_names.add(str(surface.material_before or "AIR"))
        material_names.add(str(surface.material_after or "AIR"))
    materials = _build_material_table(
        material_names,
        wavelength_nm=wavelength_nm,
        temperature_c=temperature_c,
        thermal_models=thermal_models,
        warning_sink=warning_sink,
    )
    return SequentialOpticalSystem(
        surfaces=tuple(surfaces),
        materials=materials,
        wavelength_nm=wavelength_nm,
        pupil_radius_mm=float(_read(project, "pupil_radius_mm", default=1.0) or 1.0),
        object_distance_mm=float(_read(project, "object_distance_mm", default=0.0) or 0.0),
        image_distance_mm=float(_read(project, "image_distance_mm", default=0.0) or 0.0),
    )
