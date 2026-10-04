
"""光学场景数据适配器。

它把后端的镜片、光阑、探测面和光线记录转换为 3D 场景模型，隔离后端字段
命名与渲染器所需的几何结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from shared_presentation.simulation.ray_data_model import (
    FormalRayDataset,
    FormalRayPath,
    FormalSurfaceGeometry,
)
from shared_presentation.plotting.display_transform import AxialDisplayTransform
from shared_presentation.plotting.optical_scene_geometry import (
    build_beam_envelope,
    focus_from_envelope,
    infer_lens_groups,
)
from shared_presentation.plotting.optical_scene_models import (
    OpticalScene,
    SceneObject,
    SceneRay,
    SceneSurface,
)


@dataclass(frozen=True, slots=True)
class SceneBuildOptions:
    scale_mode: str = "layout"
    selected_surface_index: int | None = None
    max_rays: int = 15
    selected_group_id: str = ""
    section_plane_vertices: tuple[tuple[float, float, float], ...] = ()
    show_section_plane: bool = False


def build_optical_scene(
    dataset: FormalRayDataset,
    options: SceneBuildOptions | None = None,
) -> OpticalScene:
    options = options or SceneBuildOptions()
    selected_range = _selected_group_range(dataset.surfaces, options.selected_group_id)
    z_values = _transform_knots(dataset)
    transform = AxialDisplayTransform.build(
        z_values,
        mode=options.scale_mode if options.scale_mode in {"layout", "physical", "group_detail"} else "layout",
        selected_range_mm=selected_range,
    )

    surfaces = tuple(
        _scene_surface(surface, transform, options.selected_surface_index)
        for surface in dataset.surfaces
    )
    selected_rays = _representative_rays(dataset.rays, max(1, int(options.max_rays)))
    roles = _ray_roles(selected_rays)
    rays = tuple(
        _scene_ray(ray, transform, roles[index])
        for index, ray in enumerate(selected_rays)
    )
    objects = tuple(_scene_objects(dataset, surfaces))
    section = _map_section_vertices(options.section_plane_vertices, transform)
    return OpticalScene(
        surfaces=surfaces,
        rays=rays,
        objects=objects,
        optical_axis=(float(transform.map(dataset.z_limits_mm[0])), float(transform.map(dataset.z_limits_mm[1]))),
        scale_mode=transform.mode,
        scale_label=transform.label,
        full_ray_count=dataset.ray_count,
        selected_surface_index=options.selected_surface_index,
        section_plane_vertices=section,
        show_section_plane=bool(options.show_section_plane),
    )


def scene_to_plot_dict(scene: OpticalScene, *, source: str = "正式仿真") -> dict:
    surfaces = [
        {
            "surface_index": item.index,
            "name": item.name,
            "type": item.surface_type,
            "group_id": item.group_id,
            "material": item.material,
            "z_physical": item.z_physical_mm,
            "z": item.z_display_mm,
            "radius": item.radius_mm,
            "conic": item.conic,
            "aperture": item.aperture_radius_mm,
            "decenter_x": item.decenter_x_mm,
            "decenter_y": item.decenter_y_mm,
            "tilt_x_deg": item.tilt_x_deg,
            "tilt_y_deg": item.tilt_y_deg,
            "tilt_z_deg": item.tilt_z_deg,
            "selected": item.selected,
            "enabled": item.enabled,
        }
        for item in scene.surfaces
    ]
    rays = [
        {
            "ray_index": item.index,
            "points": item.points_display_mm.tolist(),
            "physical_points": item.points_physical_mm.tolist(),
            "role": item.role,
            "status_code": item.status_code,
            "wavelength_nm": item.wavelength_nm,
            "power_weight": item.power_weight,
        }
        for item in scene.rays
    ]
    envelope = build_beam_envelope(rays)
    focus = focus_from_envelope(envelope)
    objects = [
        {
            "kind": item.kind,
            "name": item.name,
            "z": item.z_display_mm,
            "center_x": item.center_x_mm,
            "center_y": item.center_y_mm,
            "radius": item.radius_mm,
            "width": item.width_mm,
            "height": item.height_mm,
            "selected": item.selected,
            "metadata": dict(item.metadata),
        }
        for item in scene.objects
    ]
    if isinstance(focus, dict):
        receiver_z = [
            float(item.get("z", 0.0))
            for item in objects
            if str(item.get("kind", "")) in {"image", "detector", "fiber"}
        ]
        if receiver_z:
            axial_span = max(abs(scene.optical_axis[1] - scene.optical_axis[0]), 1.0)
            if min(abs(float(focus.get("z", 0.0)) - value) for value in receiver_z) <= 0.002 * axial_span:
                focus["label"] = ""
    return {
        "kind": "raytrace3d",
        "renderer": "professional_optical_scene",
        "scene_version": 3,
        "title": "三维光学布局",
        "source": source,
        "scale_mode": scene.scale_mode,
        "scale_label": scene.scale_label,
        "selected_surface_index": scene.selected_surface_index,
        "full_ray_count": scene.full_ray_count,
        "display_ray_count": len(scene.rays),
        "surfaces": surfaces,
        "lens_groups": infer_lens_groups(surfaces),
        "rays": rays,
        "beam_envelope": envelope,
        "focus": focus,
        "objects": objects,
        "section_plane": {"vertices": [list(v) for v in scene.section_plane_vertices]},
        "show_section_plane": bool(scene.show_section_plane),
        "optical_axis": list(scene.optical_axis),
        "description": "",
    }

def _transform_knots(dataset: FormalRayDataset) -> np.ndarray:
    values = [*dataset.z_limits_mm]
    values.extend(surface.z_mm for surface in dataset.surfaces)
    for ray in dataset.rays:
        values.extend((float(ray.points_mm[0, 2]), float(ray.points_mm[-1, 2])))
    return np.asarray(values, dtype=float)


def _scene_surface(
    surface: FormalSurfaceGeometry,
    transform: AxialDisplayTransform,
    selected_index: int | None,
) -> SceneSurface:
    return SceneSurface(
        index=surface.surface_index,
        name=surface.name,
        surface_type=surface.surface_type,
        group_id=surface.group_id,
        material=surface.material,
        z_physical_mm=surface.z_mm,
        z_display_mm=float(transform.map(surface.z_mm)),
        radius_mm=surface.radius_mm,
        conic=surface.conic,
        aperture_radius_mm=surface.aperture_radius_mm,
        decenter_x_mm=surface.decenter_x_mm,
        decenter_y_mm=surface.decenter_y_mm,
        tilt_x_deg=surface.tilt_x_deg,
        tilt_y_deg=surface.tilt_y_deg,
        tilt_z_deg=surface.tilt_z_deg,
        selected=surface.surface_index == selected_index,
        enabled=surface.enabled,
    )


def _scene_ray(ray: FormalRayPath, transform: AxialDisplayTransform, role: str) -> SceneRay:
    physical = np.asarray(ray.points_mm, dtype=float)
    display = physical.copy()
    display[:, 2] = transform.map(physical[:, 2])
    return SceneRay(
        index=ray.ray_index,
        points_physical_mm=physical,
        points_display_mm=display,
        role="failed" if ray.failed else role,
        status_code=ray.status_code,
        wavelength_nm=ray.wavelength_nm,
        power_weight=ray.power_weight,
    )


def _scene_objects(
    dataset: FormalRayDataset,
    surfaces: tuple[SceneSurface, ...],
) -> Iterable[SceneObject]:
    receiver_surfaces: list[SceneSurface] = []
    for surface in surfaces:
        lower = f"{surface.surface_type} {surface.name}".lower()
        if "光阑" in surface.surface_type or "aperture" in lower or "stop" in lower:
            yield SceneObject(
                kind="aperture",
                name=surface.name,
                z_display_mm=surface.z_display_mm,
                center_x_mm=surface.decenter_x_mm,
                center_y_mm=surface.decenter_y_mm,
                radius_mm=surface.aperture_radius_mm,
                selected=surface.selected,
                metadata={"surface_index": surface.index},
            )
        elif "detector" in lower or "探测器" in surface.surface_type:
            size = max(surface.aperture_radius_mm * 2.0, 1.0)
            receiver_surfaces.append(surface)
            yield SceneObject(
                kind="detector",
                name=surface.name,
                z_display_mm=surface.z_display_mm,
                center_x_mm=surface.decenter_x_mm,
                center_y_mm=surface.decenter_y_mm,
                width_mm=size,
                height_mm=size,
                selected=surface.selected,
                metadata={"surface_index": surface.index},
            )
        elif lower.strip() == "image" or "像面" in surface.surface_type or "image" in lower:
            size = max(surface.aperture_radius_mm * 2.0, dataset.transverse_limit_mm * 0.55)
            receiver_surfaces.append(surface)
            yield SceneObject(
                kind="image",
                name=surface.name or "像面",
                z_display_mm=surface.z_display_mm,
                center_x_mm=surface.decenter_x_mm,
                center_y_mm=surface.decenter_y_mm,
                width_mm=size,
                height_mm=size,
                selected=surface.selected,
                metadata={"surface_index": surface.index},
            )

    
    
    
    if receiver_surfaces:
        receiver = receiver_surfaces[-1]
        radius = max(
            receiver.aperture_radius_mm * 0.25,
            min(dataset.transverse_limit_mm * 0.08, 0.35),
            0.03,
        )
        yield SceneObject(
            kind="fiber",
            name="光纤端面",
            z_display_mm=receiver.z_display_mm,
            center_x_mm=receiver.decenter_x_mm,
            center_y_mm=receiver.decenter_y_mm,
            radius_mm=radius,
            metadata={"length_display": max(radius * 2.8, 0.4)},
        )

def _selected_group_range(
    surfaces: tuple[FormalSurfaceGeometry, ...],
    group_id: str,
) -> tuple[float, float] | None:
    if not group_id:
        return None
    values = [surface.z_mm for surface in surfaces if surface.group_id == group_id]
    if not values:
        return None
    return (min(values), max(values))


def _representative_rays(rays: tuple[FormalRayPath, ...], limit: int) -> list[FormalRayPath]:
    if len(rays) <= limit:
        return list(rays)
    features = np.asarray(
        [[*ray.entrance_xy_mm, *ray.exit_xy_mm] for ray in rays], dtype=float
    )
    scale = np.ptp(features, axis=0)
    scale[scale <= 1.0e-12] = 1.0
    normalized = (features - np.mean(features, axis=0)) / scale
    start = int(np.argmin(np.linalg.norm(normalized[:, :2], axis=1)))
    selected = [start]
    minimum = np.linalg.norm(normalized - normalized[start], axis=1)
    minimum[start] = -1.0
    while len(selected) < limit:
        nxt = int(np.argmax(minimum))
        if nxt in selected:
            break
        selected.append(nxt)
        minimum = np.minimum(minimum, np.linalg.norm(normalized - normalized[nxt], axis=1))
        minimum[selected] = -1.0
    
    failed = [index for index, ray in enumerate(rays) if ray.failed]
    for index in failed[: max(0, min(6, limit // 8))]:
        if index not in selected:
            selected[-1] = index
    return [rays[index] for index in selected]


def _ray_roles(rays: list[FormalRayPath]) -> list[str]:
    if not rays:
        return []
    radii = np.asarray([np.linalg.norm(ray.entrance_xy_mm) for ray in rays])
    centre = int(np.argmin(radii))
    sorted_indices = list(np.argsort(radii))
    marginal = set(sorted_indices[-min(4, len(sorted_indices)):])
    roles = []
    for index, ray in enumerate(rays):
        if ray.failed:
            roles.append("failed")
        elif index == centre:
            roles.append("chief")
        elif index in marginal:
            roles.append("marginal")
        else:
            roles.append("regular")
    return roles


def _map_section_vertices(
    vertices: tuple[tuple[float, float, float], ...],
    transform: AxialDisplayTransform,
) -> tuple[tuple[float, float, float], ...]:
    mapped = []
    for z, x, y in vertices:
        mapped.append((float(transform.map(z)), float(x), float(y)))
    return tuple(mapped)


__all__ = ["SceneBuildOptions", "build_optical_scene", "scene_to_plot_dict"]
