from __future__ import annotations



from math import isfinite, sqrt
from typing import Any, Mapping


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


def build_dataset_parameters(project_payload: Mapping[str, Any]) -> list[dict[str, Any]]:

    surfaces = [item for item in (project_payload.get("surfaces") or []) if isinstance(item, Mapping)]
    parameters: list[dict[str, Any]] = []

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

    return parameters


__all__ = ["build_dataset_parameters"]
