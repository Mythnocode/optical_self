"""Convert editor values using the original Python surface serializer."""
from math import isfinite
from types import SimpleNamespace
from typing import Any

from shared_presentation.surface_payloads import serialize_surfaces, _surface_type
from shared_presentation.surface_registry import SURFACE_TYPES, ensure_surface_defaults


def _finite_values(value: Any) -> None:
    if isinstance(value, (int, float)) and not isfinite(value):
        raise ValueError("表面参数必须为有限数值")
    if isinstance(value, dict):
        for item in value.values():
            _finite_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite_values(item)


def editor_surfaces(project: dict[str, Any]) -> list[Any]:
    types = {_surface_type(spec.name): spec.name for spec in SURFACE_TYPES}
    authored = []
    for row in project["surfaces"]:
        metadata = row["metadata"]
        editor = metadata.get("_editor", {})
        if not isinstance(editor, dict):
            raise ValueError("编辑表面数据格式无效")
        params = dict(metadata.get("type_parameters", {}) or {})
        _finite_values(row)
        type_name = types.get(row["surface_type"])
        if type_name is None:
            raise ValueError("未知表面类型")
        surface = SimpleNamespace(
            surface_type=type_name, radius_mm=row.get("radius_mm"),
            thickness_mm=row["distance_to_next_mm"],
            semi_aperture_mm=editor.get("semi_aperture_mm", row["clear_aperture_mm"]),
            material=editor.get("material", row["material_after"]),
            conic=row["conic"], type_parameters=params,
            coating=metadata.get("coating_preset", "无"),
            roughness_nm=row.get("roughness_rms_nm", 0),
            mechanical_diameter_mm=row.get("mechanical_diameter_mm"),
            enabled=row["enabled"], name=metadata.get("name", ""),
            group_id=metadata.get("group_id", ""),
            element_id=metadata.get("element_id", ""),
            surface_id=metadata.get("surface_id", ""), note=metadata.get("note", ""),
        )
        if surface.semi_aperture_mm is None:
            raise ValueError("编辑表面缺少半口径")
        for value in (surface.radius_mm, surface.thickness_mm, surface.semi_aperture_mm,
                      surface.conic, surface.roughness_nm, surface.mechanical_diameter_mm):
            if value is not None and not isfinite(float(value)):
                raise ValueError("表面参数必须为有限数值")
        # Old shared snapshots can contain a coefficient list without authored A4/A6/A8.
        if row.get("asphere_coefficients") and not any(key in params for key in ("a4", "a6", "a8", "asphere_coefficients")):
            params["asphere_coefficients"] = list(row.get("asphere_coefficients", []))
        ensure_surface_defaults(surface)
        authored.append(surface)
    return authored


def canonical_surfaces(project: dict[str, Any]) -> list[dict[str, Any]]:
    return serialize_surfaces(editor_surfaces(project), project["source"]["wavelength_nm"])
