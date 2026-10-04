
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

import numpy as np

from shared_presentation.plotting.display_transform import AxialDisplayTransform

from .ray_data_model import FormalRayDataset, FormalRayPath, FormalSurfaceGeometry
from shared_presentation.plotting.optical_scene_adapter import (
    SceneBuildOptions,
    build_optical_scene,
    scene_to_plot_dict,
)


SectionPlane = Literal["yz", "xz", "custom"]


@dataclass(frozen=True, slots=True)
class RayViewOptions:


    plane: SectionPlane = "yz"
    position_mm: float = 0.0
    half_thickness_mm: float = 0.05
    custom_azimuth_deg: float = 45.0
    max_section_rays: int = 21
    max_3d_rays: int = 15
    scale_mode: str = "layout"
    selected_surface_index: int | None = None
    selected_group_id: str = ""
    show_section_plane: bool = False

    def validated(self) -> "RayViewOptions":
        if self.plane not in {"yz", "xz", "custom"}:
            raise ValueError(f"Unsupported section plane: {self.plane!r}")
        if not math.isfinite(self.position_mm):
            raise ValueError("Section position must be finite.")
        if not math.isfinite(self.half_thickness_mm) or self.half_thickness_mm <= 0.0:
            raise ValueError("Section half thickness must be positive and finite.")
        if not math.isfinite(self.custom_azimuth_deg):
            raise ValueError("Custom section azimuth must be finite.")
        if self.max_section_rays < 1 or self.max_3d_rays < 1:
            raise ValueError("Ray display limits must be positive integers.")
        if self.scale_mode not in {"layout", "physical", "group_detail"}:
            raise ValueError(f"Unsupported display scale mode: {self.scale_mode!r}")
        return self

    @classmethod
    def from_mapping(cls, value: dict | None) -> "RayViewOptions":
        value = dict(value or {})
        return cls(
            plane=str(value.get("plane", "yz")).lower(),
            position_mm=float(value.get("position_mm", 0.0) or 0.0),
            half_thickness_mm=float(value.get("half_thickness_mm", 0.05) or 0.05),
            custom_azimuth_deg=float(value.get("custom_azimuth_deg", 45.0) or 45.0),
            max_section_rays=int(value.get("max_section_rays", 21) or 21),
            max_3d_rays=int(value.get("max_3d_rays", 15) or 15),
            scale_mode=str(value.get("scale_mode", "layout") or "layout"),
            selected_surface_index=(
                int(value["selected_surface_index"])
                if value.get("selected_surface_index") is not None
                else None
            ),
            selected_group_id=str(value.get("selected_group_id", "") or ""),
            show_section_plane=bool(value.get("show_section_plane", False)),
        ).validated()


@dataclass(frozen=True, slots=True)
class _PlaneBasis:
    normal_xy: np.ndarray
    transverse_xy: np.ndarray
    plane_label: str
    transverse_label: str


def build_ray_view_plots(
    dataset: FormalRayDataset,
    options: RayViewOptions | None = None,
) -> dict[str, dict]:

    options = (options or RayViewOptions()).validated()
    basis = _plane_basis(options)
    section_rays, section_scores = _section_rays(dataset, options, basis)
    section_surfaces = _section_surfaces(dataset.surfaces, options, basis)
    plane_vertices = _section_plane_vertices(dataset, options, basis)
    scene = build_optical_scene(
        dataset,
        SceneBuildOptions(
            scale_mode=options.scale_mode,
            selected_surface_index=options.selected_surface_index,
            max_rays=options.max_3d_rays,
            selected_group_id=options.selected_group_id,
            section_plane_vertices=tuple(tuple(value) for value in plane_vertices),
            show_section_plane=bool(options.show_section_plane),
        ),
    )
    display_transform = _display_transform(dataset, options)
    section_roles = _section_roles(section_rays)

    section_name = _section_name(options)
    section_description = (
        f"来自同一正式三维追迹数据：完整 {dataset.ray_count} 条，"
        f"截面显示 {len(section_rays)} 条；{section_name}，"
        f"路径到截面的 RMS 距离按 ±{options.half_thickness_mm:g} mm 筛选。"
    )
    three_d_description = (
        f"正式三维追迹共 {dataset.ray_count} 条光线；"
        f"当前分层选取 {len(scene.rays)} 条代表光线显示。"
    )

    three_d_plot = scene_to_plot_dict(scene, source=dataset.source)
    three_d_plot.setdefault("render_quality", "high")
    three_d_plot["section_options"] = _options_dict(options)
    three_d_plot["description"] = three_d_description + " " + scene.scale_label

    return {
        "光路": {
            "kind": "raytrace_section",
            "title": f"二维光路 · {section_name}",
            "x_label": "z / mm",
            "y_label": basis.transverse_label,
            "surfaces": [
                _section_surface_display_model(surface, display_transform, options)
                for surface in section_surfaces
            ],
            "rays": [
                _section_ray_model(ray, basis, display_transform, section_roles[index])
                for index, ray in enumerate(section_rays)
            ],
            "ray_scores_mm": [float(value) for value in section_scores],
            "source": dataset.source,
            "description": section_description,
            "full_ray_count": dataset.ray_count,
            "display_ray_count": len(section_rays),
            "section_options": _options_dict(options),
            "scale_mode": options.scale_mode,
            "scale_label": display_transform.label,
            "selected_surface_index": options.selected_surface_index,
        },
        "3D光路": three_d_plot,
    }


def _plane_basis(options: RayViewOptions) -> _PlaneBasis:
    if options.plane == "yz":
        return _PlaneBasis(
            normal_xy=np.asarray([1.0, 0.0]),
            transverse_xy=np.asarray([0.0, 1.0]),
            plane_label="YZ 截面",
            transverse_label="y / mm",
        )
    if options.plane == "xz":
        return _PlaneBasis(
            normal_xy=np.asarray([0.0, 1.0]),
            transverse_xy=np.asarray([1.0, 0.0]),
            plane_label="XZ 截面",
            transverse_label="x / mm",
        )

    angle = math.radians(options.custom_azimuth_deg)
    transverse = np.asarray([math.cos(angle), math.sin(angle)], dtype=float)
    normal = np.asarray([-math.sin(angle), math.cos(angle)], dtype=float)
    return _PlaneBasis(
        normal_xy=normal,
        transverse_xy=transverse,
        plane_label=f"自定义截面 {options.custom_azimuth_deg:g}°",
        transverse_label="截面横向坐标 / mm",
    )


def _section_name(options: RayViewOptions) -> str:
    basis = _plane_basis(options)
    return f"{basis.plane_label}（位置 {options.position_mm:g} mm）"


def _section_rays(
    dataset: FormalRayDataset,
    options: RayViewOptions,
    basis: _PlaneBasis,
) -> tuple[list[FormalRayPath], list[float]]:
    scores = np.asarray(
        [_plane_distance_score(ray, options, basis) for ray in dataset.rays],
        dtype=float,
    )
    eligible = np.flatnonzero(scores <= options.half_thickness_mm)

    
    
    desired_minimum = min(9, dataset.ray_count, options.max_section_rays)
    if len(eligible) < desired_minimum:
        eligible = np.argsort(scores)[:desired_minimum]

    candidate_rays = [dataset.rays[int(index)] for index in eligible]
    candidate_scores = scores[eligible]
    selected_local = _section_stratified_indices(
        candidate_rays, basis, options.max_section_rays
    )
    selected_rays = [candidate_rays[index] for index in selected_local]
    selected_scores = [float(candidate_scores[index]) for index in selected_local]
    return selected_rays, selected_scores


def _plane_distance_score(
    ray: FormalRayPath,
    options: RayViewOptions,
    basis: _PlaneBasis,
) -> float:
    distances = ray.points_mm[:, :2] @ basis.normal_xy - options.position_mm
    return float(np.sqrt(np.mean(np.square(distances))))


def _representative_rays(
    rays: tuple[FormalRayPath, ...],
    limit: int,
) -> list[FormalRayPath]:
    if len(rays) <= limit:
        return list(rays)
    indices = _farthest_point_indices(rays, limit)
    return [rays[index] for index in indices]



def _section_stratified_indices(
    rays: list[FormalRayPath],
    basis: _PlaneBasis,
    limit: int,
) -> list[int]:

    if len(rays) <= limit:
        return list(range(len(rays)))
    entrance = np.asarray(
        [float(ray.entrance_xy_mm @ basis.transverse_xy) for ray in rays],
        dtype=float,
    )
    order = np.argsort(entrance, kind="stable")
    quantiles = np.linspace(0, len(order) - 1, int(limit))
    selected = [int(order[int(round(value))]) for value in quantiles]
    chief = int(np.argmin(np.abs(entrance)))
    if chief not in selected:
        selected[len(selected) // 2] = chief
    return list(dict.fromkeys(selected))

def _stratified_indices(rays: list[FormalRayPath], limit: int) -> list[int]:
    if len(rays) <= limit:
        return list(range(len(rays)))
    return _farthest_point_indices(tuple(rays), limit)


def _farthest_point_indices(rays: tuple[FormalRayPath, ...], limit: int) -> list[int]:

    features = np.asarray(
        [
            [
                ray.entrance_xy_mm[0],
                ray.entrance_xy_mm[1],
                ray.exit_xy_mm[0],
                ray.exit_xy_mm[1],
            ]
            for ray in rays
        ],
        dtype=float,
    )
    scale = np.ptp(features, axis=0)
    scale[scale <= 1.0e-12] = 1.0
    normalized = (features - np.mean(features, axis=0)) / scale

    start = int(np.argmin(np.linalg.norm(normalized[:, :2], axis=1)))
    selected = [start]
    minimum_distance = np.linalg.norm(normalized - normalized[start], axis=1)
    minimum_distance[start] = -1.0

    while len(selected) < min(limit, len(rays)):
        next_index = int(np.argmax(minimum_distance))
        if next_index in selected:
            break
        selected.append(next_index)
        distance = np.linalg.norm(normalized - normalized[next_index], axis=1)
        minimum_distance = np.minimum(minimum_distance, distance)
        minimum_distance[selected] = -1.0

    return selected


def _section_ray_model(
    ray: FormalRayPath,
    basis: _PlaneBasis,
    transform: AxialDisplayTransform,
    role: str,
) -> dict[str, list[float] | int | str | float | None]:
    transverse = ray.points_mm[:, :2] @ basis.transverse_xy
    return {
        "ray_index": ray.ray_index,
        "z": np.asarray(transform.map(ray.points_mm[:, 2]), dtype=float).tolist(),
        "physical_z": ray.points_mm[:, 2].astype(float).tolist(),
        "t": transverse.astype(float).tolist(),
        "role": "failed" if ray.failed else role,
        "status_code": int(ray.status_code),
        "wavelength_nm": ray.wavelength_nm,
        "power_weight": float(ray.power_weight),
    }


def _ray_3d_model(ray: FormalRayPath) -> dict[str, list[float] | int]:
    return {
        "ray_index": ray.ray_index,
        "x": ray.points_mm[:, 0].astype(float).tolist(),
        "y": ray.points_mm[:, 1].astype(float).tolist(),
        "z": ray.points_mm[:, 2].astype(float).tolist(),
    }


def _surface_3d_model(surface: FormalSurfaceGeometry) -> dict[str, float | str | int]:
    return {
        "surface_index": surface.surface_index,
        "name": surface.name,
        "type": surface.surface_type,
        "z": surface.z_mm,
        "aperture": surface.aperture_radius_mm,
        "decenter_x": surface.decenter_x_mm,
        "decenter_y": surface.decenter_y_mm,
    }


def _section_surfaces(
    surfaces: tuple[FormalSurfaceGeometry, ...],
    options: RayViewOptions,
    basis: _PlaneBasis,
) -> list[dict[str, float | str | int]]:
    result: list[dict[str, float | str | int]] = []
    for surface in surfaces:
        center_xy = np.asarray([surface.decenter_x_mm, surface.decenter_y_mm])
        normal_distance = float(center_xy @ basis.normal_xy - options.position_mm)
        radius = float(surface.aperture_radius_mm)
        if radius <= 0.0:
            half_height = 0.0
        elif abs(normal_distance) > radius:
            continue
        else:
            half_height = math.sqrt(max(radius * radius - normal_distance * normal_distance, 0.0))
        center_t = float(center_xy @ basis.transverse_xy)
        result.append(
            {
                "surface_index": surface.surface_index,
                "name": surface.name,
                "type": surface.surface_type,
                "group_id": surface.group_id,
                "material": surface.material,
                "z": surface.z_mm,
                "radius": surface.radius_mm,
                "conic": surface.conic,
                "aperture": surface.aperture_radius_mm,
                "decenter_x": surface.decenter_x_mm,
                "decenter_y": surface.decenter_y_mm,
                "t_min": center_t - half_height,
                "t_max": center_t + half_height,
            }
        )
    return result


def _section_plane_vertices(
    dataset: FormalRayDataset,
    options: RayViewOptions,
    basis: _PlaneBasis,
) -> list[list[float]]:
    z_min, z_max = dataset.z_limits_mm
    margin = 0.03 * max(z_max - z_min, 1.0)
    z_min -= margin
    z_max += margin
    transverse_limit = dataset.transverse_limit_mm * 1.05
    normal_origin = basis.normal_xy * options.position_mm

    vertices: list[list[float]] = []
    for z, transverse in (
        (z_min, -transverse_limit),
        (z_max, -transverse_limit),
        (z_max, transverse_limit),
        (z_min, transverse_limit),
    ):
        xy = normal_origin + basis.transverse_xy * transverse
        vertices.append([float(z), float(xy[0]), float(xy[1])])
    return vertices


def _options_dict(options: RayViewOptions) -> dict[str, float | int | str | bool]:
    return {
        "plane": options.plane,
        "position_mm": options.position_mm,
        "half_thickness_mm": options.half_thickness_mm,
        "custom_azimuth_deg": options.custom_azimuth_deg,
        "max_section_rays": options.max_section_rays,
        "max_3d_rays": options.max_3d_rays,
        "scale_mode": options.scale_mode,
        "selected_surface_index": options.selected_surface_index,
        "selected_group_id": options.selected_group_id,
        "show_section_plane": options.show_section_plane,
    }


def _display_transform(dataset: FormalRayDataset, options: RayViewOptions) -> AxialDisplayTransform:
    values = [*dataset.z_limits_mm]
    values.extend(surface.z_mm for surface in dataset.surfaces)
    selected_range = None
    if options.selected_group_id:
        selected_values = [
            surface.z_mm for surface in dataset.surfaces
            if surface.group_id == options.selected_group_id
        ]
        if selected_values:
            selected_range = (min(selected_values), max(selected_values))
    return AxialDisplayTransform.build(
        values,
        mode=options.scale_mode,
        selected_range_mm=selected_range,
    )


def _section_roles(rays: list[FormalRayPath]) -> list[str]:
    if not rays:
        return []
    radii = np.asarray([np.linalg.norm(ray.entrance_xy_mm) for ray in rays], dtype=float)
    chief = int(np.argmin(radii))
    marginal = set(np.argsort(radii)[-min(4, len(rays)):].tolist())
    result = []
    for index, ray in enumerate(rays):
        if ray.failed:
            result.append("failed")
        elif index == chief:
            result.append("chief")
        elif index in marginal:
            result.append("marginal")
        else:
            result.append("regular")
    return result


def _section_surface_display_model(
    surface: dict,
    transform: AxialDisplayTransform,
    options: RayViewOptions,
) -> dict:
    model = dict(surface)
    model["physical_z"] = float(model.get("z", 0.0) or 0.0)
    model["z"] = float(transform.map(model["physical_z"]))
    model["selected"] = int(model.get("surface_index", -1)) == options.selected_surface_index
    return model


__all__ = [
    "RayViewOptions",
    "SectionPlane",
    "build_ray_view_plots",
]
