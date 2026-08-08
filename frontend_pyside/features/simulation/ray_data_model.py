
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class FormalRayPath:


    ray_index: int
    points_mm: np.ndarray
    status_code: int = 0
    power_weight: float = 1.0
    wavelength_nm: float | None = None

    def __post_init__(self) -> None:
        points = np.asarray(self.points_mm, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("FormalRayPath.points_mm must have shape (N, 3).")
        points = points[np.all(np.isfinite(points), axis=1)]
        if len(points) < 2:
            raise ValueError("A formal ray path must contain at least two finite points.")
        points = np.ascontiguousarray(points, dtype=float)
        points.setflags(write=False)
        object.__setattr__(self, "points_mm", points)

    @property
    def entrance_xy_mm(self) -> np.ndarray:
        return self.points_mm[0, :2]

    @property
    def exit_xy_mm(self) -> np.ndarray:
        return self.points_mm[-1, :2]

    @property
    def z_span_mm(self) -> float:
        return float(np.ptp(self.points_mm[:, 2]))

    @property
    def failed(self) -> bool:
        return int(self.status_code) != 0


@dataclass(frozen=True, slots=True)
class FormalSurfaceGeometry:


    surface_index: int
    name: str
    surface_type: str
    z_mm: float
    aperture_radius_mm: float
    radius_mm: float = float("inf")
    conic: float = 0.0
    group_id: str = ""
    material: str = "AIR"
    distance_to_next_mm: float = 0.0
    decenter_x_mm: float = 0.0
    decenter_y_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    tilt_z_deg: float = 0.0
    mechanical_diameter_mm: float = 0.0
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class FormalRayDataset:


    rays: tuple[FormalRayPath, ...]
    surfaces: tuple[FormalSurfaceGeometry, ...]
    source: str = "正式仿真"

    @property
    def ray_count(self) -> int:
        return len(self.rays)

    @property
    def surface_count(self) -> int:
        return len(self.surfaces)

    @property
    def z_limits_mm(self) -> tuple[float, float]:
        values: list[float] = []
        for ray in self.rays:
            values.extend((float(np.min(ray.points_mm[:, 2])), float(np.max(ray.points_mm[:, 2]))))
        values.extend(surface.z_mm for surface in self.surfaces)
        if not values:
            return (0.0, 1.0)
        low, high = min(values), max(values)
        if high <= low:
            high = low + 1.0
        return (low, high)

    @property
    def transverse_limit_mm(self) -> float:
        maximum = 0.0
        for ray in self.rays:
            maximum = max(maximum, float(np.max(np.abs(ray.points_mm[:, :2]))))
        for surface in self.surfaces:
            maximum = max(
                maximum,
                abs(surface.decenter_x_mm) + surface.aperture_radius_mm,
                abs(surface.decenter_y_mm) + surface.aperture_radius_mm,
            )
        return max(maximum, 1.0e-6)

    @property
    def wavelengths_nm(self) -> tuple[float, ...]:
        values = sorted({float(ray.wavelength_nm) for ray in self.rays if ray.wavelength_nm})
        return tuple(values)

    @classmethod
    def from_backend(
        cls,
        arrays: Mapping[str, Any],
        project: Mapping[str, Any] | None = None,
    ) -> "FormalRayDataset | None":
        project = dict(project or {})
        paths = _as_2d(arrays.get("raytrace_path_points_mm"), columns=3)
        offsets = _as_1d(arrays.get("raytrace_path_offsets"), dtype=int)
        statuses = _as_1d(
            _first(arrays, "raytrace_status_codes", "raytrace_status_code"), dtype=int
        )
        weights = _as_1d(
            _first(arrays, "raytrace_power_weights", "raytrace_weights", "raytrace_power"),
            dtype=float,
        )
        wavelengths = _as_1d(
            _first(arrays, "raytrace_wavelength_nm", "raytrace_wavelengths_nm"),
            dtype=float,
        )
        rays: list[FormalRayPath] = []

        if paths.size and offsets.size >= 2:
            for ray_index, (start, end) in enumerate(zip(offsets[:-1], offsets[1:])):
                start_i, end_i = int(start), int(end)
                if not (0 <= start_i < end_i <= len(paths)):
                    continue
                segment = paths[start_i:end_i]
                try:
                    rays.append(
                        FormalRayPath(
                            ray_index=ray_index,
                            points_mm=segment,
                            status_code=int(statuses[ray_index]) if ray_index < len(statuses) else 0,
                            power_weight=float(weights[ray_index]) if ray_index < len(weights) else 1.0,
                            wavelength_nm=(
                                float(wavelengths[ray_index])
                                if ray_index < len(wavelengths) and np.isfinite(wavelengths[ray_index])
                                else None
                            ),
                        )
                    )
                except ValueError:
                    continue

        if not rays:
            final_positions = _as_2d(arrays.get("raytrace_final_positions_mm"), columns=3)
            if final_positions.size:
                object_z = -abs(float(project.get("object_distance_mm", 1.0) or 1.0))
                for ray_index, point in enumerate(final_positions):
                    if not np.all(np.isfinite(point)):
                        continue
                    points = np.asarray(
                        [[0.0, 0.0, object_z], [float(point[0]), float(point[1]), float(point[2])]],
                        dtype=float,
                    )
                    rays.append(FormalRayPath(ray_index=ray_index, points_mm=points))

        if not rays:
            return None

        return cls(rays=tuple(rays), surfaces=tuple(_surface_geometry(project)))


def _surface_geometry(project: Mapping[str, Any]) -> list[FormalSurfaceGeometry]:
    z_mm = 0.0
    surfaces: list[FormalSurfaceGeometry] = []
    for index, raw in enumerate(project.get("surfaces", []) or []):
        item = dict(raw or {})
        enabled = bool(item.get("enabled", True))
        distance = float(
            item.get("distance_to_next_mm", item.get("thickness_mm", 0.0)) or 0.0
        )
        if enabled:
            clear_aperture = float(
                item.get("clear_aperture_mm", item.get("semi_aperture_mm", 1.0)) or 1.0
            )
            radius_raw = item.get("radius_mm", item.get("radius", float("inf")))
            try:
                radius = float(radius_raw)
            except (TypeError, ValueError):
                radius = float("inf")
            type_parameters = dict(item.get("type_parameters", {}) or {})
            surfaces.append(
                FormalSurfaceGeometry(
                    surface_index=index,
                    name=str(item.get("name", f"Surface {index}")),
                    surface_type=str(item.get("surface_type", "standard")),
                    z_mm=float(z_mm),
                    aperture_radius_mm=max(0.0, clear_aperture),
                    radius_mm=radius,
                    conic=float(item.get("conic", item.get("conic_constant", 0.0)) or 0.0),
                    group_id=str(item.get("group_id", "") or ""),
                    material=str(item.get("material", item.get("material_after", "AIR")) or "AIR"),
                    distance_to_next_mm=distance,
                    decenter_x_mm=float(item.get("decenter_x_mm", type_parameters.get("decenter_x_mm", 0.0)) or 0.0),
                    decenter_y_mm=float(item.get("decenter_y_mm", type_parameters.get("decenter_y_mm", 0.0)) or 0.0),
                    tilt_x_deg=float(item.get("tilt_x_deg", type_parameters.get("tilt_x_deg", 0.0)) or 0.0),
                    tilt_y_deg=float(item.get("tilt_y_deg", type_parameters.get("tilt_y_deg", 0.0)) or 0.0),
                    tilt_z_deg=float(item.get("tilt_z_deg", type_parameters.get("tilt_z_deg", 0.0)) or 0.0),
                    mechanical_diameter_mm=float(item.get("mechanical_diameter_mm", 0.0) or 0.0),
                    enabled=True,
                )
            )
        z_mm += distance

    image_distance = float(project.get("image_distance_mm", 0.0) or 0.0)
    if image_distance:
        surfaces.append(
            FormalSurfaceGeometry(
                surface_index=len(surfaces),
                name="Image",
                surface_type="image",
                z_mm=z_mm + image_distance,
                aperture_radius_mm=max(
                    0.0,
                    float(project.get("receiver", {}).get("core_radius_um", 0.0) or 0.0) / 1000.0,
                ),
                group_id="IMAGE",
            )
        )
    return surfaces


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _as_1d(value: Any, dtype=float) -> np.ndarray:
    if value is None:
        return np.asarray([], dtype=dtype)
    try:
        array = np.asarray(value, dtype=dtype)
    except (TypeError, ValueError):
        return np.asarray([], dtype=dtype)
    return array.reshape(-1) if array.size else np.asarray([], dtype=dtype)


def _as_2d(value: Any, columns: int | None = None) -> np.ndarray:
    if value is None:
        return np.empty((0, columns or 0), dtype=float)
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return np.empty((0, columns or 0), dtype=float)
    if array.ndim != 2 or not array.size:
        return np.empty((0, columns or 0), dtype=float)
    if columns is not None and array.shape[1] != columns:
        return np.empty((0, columns), dtype=float)
    return array


__all__ = [
    "FormalRayDataset",
    "FormalRayPath",
    "FormalSurfaceGeometry",
]
