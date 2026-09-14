from __future__ import annotations



from math import isfinite, sqrt
from typing import Any, Iterable, Mapping


_NON_CURVED_TYPES = {
    "plane",
    "detector",
    "stop",
    "coordinate_break",
}


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _radius_bounds(surface: Mapping[str, Any], value: float) -> tuple[float, float] | None:

    magnitude = abs(value)
    if magnitude <= 1.0e-9:
        return None

    aperture = abs(_finite_number(surface.get("clear_aperture_mm")) or 0.0)
    conic = _finite_number(surface.get("conic")) or 0.0
    radicand_factor = max(0.0, 1.0 + conic)
    minimum_magnitude = max(1.0e-3, aperture * sqrt(radicand_factor) * 1.03)

    spread = max(magnitude * 0.10, min(0.25, magnitude * 0.04))
    low_mag = max(minimum_magnitude, magnitude - spread)
    high_mag = max(low_mag + 1.0e-6, magnitude + spread)
    if value > 0.0:
        return low_mag, high_mag
    return -high_mag, -low_mag


def _positive_bounds(value: float) -> tuple[float, float] | None:
    if not isfinite(value) or value <= 1.0e-6:
        return None
    spread = max(value * 0.10, min(0.25, value * 0.03))
    lower = max(1.0e-4, value - spread)
    upper = max(lower + 1.0e-6, value + spread)
    return lower, upper


def _spread_bounds(value: float, *, floor: float) -> tuple[float, float]:
    spread = max(abs(value) * 0.10, floor)
    return value - spread, value + spread


def build_dataset_parameters(
    project_payload: Mapping[str, Any],
    groups: Iterable[str] | None = None,
    *,
    explicit_paths: Iterable[str] | None = None,
) -> list[dict[str, Any]]:

    selected = {str(item) for item in groups} if groups is not None else {"曲率半径", "厚度"}
    surfaces = [item for item in (project_payload.get("surfaces") or []) if isinstance(item, Mapping)]
    parameters: list[dict[str, Any]] = []

    if explicit_paths is not None:
        ordered_paths = [str(path) for path in explicit_paths]
        for path in ordered_paths:
            if not path.startswith("surfaces[") or "]." not in path:
                continue
            index_text, field = path[len("surfaces["):].split("].", 1)
            try:
                index = int(index_text)
                surface = surfaces[index]
            except (ValueError, IndexError):
                continue
            value = _finite_number(surface.get(field))
            bounds = None
            unit = "1"
            if field == "radius_mm" and value is not None:
                bounds, unit = _radius_bounds(surface, value), "mm"
            elif field == "distance_to_next_mm" and value is not None:
                bounds, unit = _positive_bounds(value), "mm"
            elif field == "conic":
                bounds = _spread_bounds(value or 0.0, floor=0.25)
            if bounds is not None:
                parameters.append({
                    "name": f"surface_{index}_{field}", "path": path, "unit": unit,
                    "lower_bound": bounds[0], "upper_bound": bounds[1],
                })
        return parameters

    if "曲率半径" in selected:
        for index, surface in enumerate(surfaces):
            surface_type = str(surface.get("surface_type", "")).strip().lower()
            radius = _finite_number(surface.get("radius_mm"))
            if surface_type not in _NON_CURVED_TYPES and radius is not None:
                bounds = _radius_bounds(surface, radius)
                if bounds is not None:
                    parameters.append(
                        {
                            "name": f"surface_{index}_radius",
                            "path": f"surfaces[{index}].radius_mm",
                            "unit": "mm",
                            "lower_bound": bounds[0],
                            "upper_bound": bounds[1],
                        }
                    )

    if "厚度" in selected:
        for index, surface in enumerate(surfaces):
            material_after = str(surface.get("material_after", "")).strip().upper()
            if material_after == "AIR" and index < len(surfaces) - 1:
                distance = _finite_number(surface.get("distance_to_next_mm"))
                bounds = _positive_bounds(distance) if distance is not None else None
                if bounds is not None:
                    parameters.append(
                        {
                            "name": f"surface_{index}_air_gap",
                            "path": f"surfaces[{index}].distance_to_next_mm",
                            "unit": "mm",
                            "lower_bound": bounds[0],
                            "upper_bound": bounds[1],
                        }
                    )

        image_distance = _finite_number(project_payload.get("image_distance_mm"))
        image_bounds = _positive_bounds(image_distance) if image_distance is not None else None
        if image_bounds is not None:
            parameters.append(
                {
                    "name": "image_distance",
                    "path": "image_distance_mm",
                    "unit": "mm",
                    "lower_bound": image_bounds[0],
                    "upper_bound": image_bounds[1],
                }
            )

    if "光纤位置" in selected:
        receiver = project_payload.get("receiver") or {}
        if not isinstance(receiver, Mapping):
            receiver = {}
        for field, name, unit, floor in (
            ("offset_x_um", "fiber_offset_x", "um", 5.0),
            ("offset_y_um", "fiber_offset_y", "um", 5.0),
            ("axial_offset_z_um", "fiber_axial_offset", "um", 5.0),
        ):
            value = _finite_number(receiver.get(field))
            if value is None:
                value = 0.0
            lower, upper = _spread_bounds(value, floor=floor)
            parameters.append(
                {
                    "name": name,
                    "path": f"receiver.{field}",
                    "unit": unit,
                    "lower_bound": lower,
                    "upper_bound": upper,
                }
            )

    if "波长属性" in selected:
        source = project_payload.get("source") or {}
        if not isinstance(source, Mapping):
            source = {}
        wavelength = _finite_number(source.get("wavelength_nm")) or _finite_number(project_payload.get("wavelength_nm"))
        if wavelength is not None and wavelength > 0:
            lower, upper = _spread_bounds(wavelength, floor=1.0)
            parameters.append(
                {
                    "name": "wavelength",
                    "path": "source.wavelength_nm",
                    "unit": "nm",
                    "lower_bound": max(1.0, lower),
                    "upper_bound": max(lower + 1.0, upper),
                }
            )

    return parameters


__all__ = ["build_dataset_parameters"]
