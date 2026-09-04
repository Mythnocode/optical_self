from __future__ import annotations

"""Convert teaching ExperimentModel nodes into TeachingPhysicalScene."""

from typing import Any

from teaching_runtime.physical_scene import TeachingPhysicalNode, TeachingPhysicalScene


def experiment_model_to_physical_scene(
    model: Any,
    *,
    generation: int | None = None,
    trace_quality: str = "live",
) -> TeachingPhysicalScene:
    nodes_raw = dict(getattr(model, "nodes", {}) or {})
    physical: list[TeachingPhysicalNode] = []
    for node in nodes_raw.values():
        params = dict(getattr(node, "params", {}) or {})
        enabled = bool(params.get("enabled", True))
        kind = str(getattr(node, "kind", "") or "")
        # Normalize CCD aliases for the scene compiler / terminal surfaces.
        if kind in {"camera"}:
            kind = "ccd"
        height = float(params.get("z_mm", params.get("height_mm", 82.0)) or 82.0)
        physical.append(TeachingPhysicalNode(
            node_id=str(getattr(node, "id", "")),
            kind=kind,
            label=str(getattr(node, "label", "") or kind),
            scene_x=float(getattr(node, "x", 0.0)),
            scene_y=float(getattr(node, "y", 0.0)),
            height_mm=height,
            yaw_deg=float(getattr(node, "rotation_deg", 0.0) or 0.0),
            pitch_deg=float(params.get("pitch_deg", 0.0) or 0.0),
            roll_deg=float(params.get("roll_deg", 0.0) or 0.0),
            enabled=enabled,
            params=params,
        ))
    return TeachingPhysicalScene(
        nodes=tuple(physical),
        wavelength_nm=float(getattr(model, "wavelength_nm", 808.0) or 808.0),
        input_power_mw=float(getattr(model, "input_power_mw", 1.0) or 1.0),
        max_system_length_mm=max(40.0, float(getattr(model, "max_system_length_mm", 140.0) or 140.0)),
        generation=int(generation if generation is not None else getattr(model, "revision", 0)),
        trace_quality=str(trace_quality or "live"),
    )


def trace_paths_to_scene_rays(
    paths: Any,
    *,
    max_rays: int = 5,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Pack TeachingTracePath points as (scene_x, scene_y, height_mm) polylines."""
    selected: list[tuple[tuple[float, float, float], ...]] = []
    for path in paths or ():
        points = tuple(
            (float(pt.scene_x), float(pt.scene_y), float(pt.height_mm))
            for pt in getattr(path, "points", ()) or ()
        )
        if len(points) >= 2:
            selected.append(points)
        if len(selected) >= max_rays:
            break
    return tuple(selected)


def trace_paths_to_engine_rays(
    paths: Any,
    *,
    max_rays: int = 5,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    selected: list[tuple[tuple[float, float, float], ...]] = []
    for path in paths or ():
        points = tuple(
            tuple(float(v) for v in pt.engine_point_mm)
            for pt in getattr(path, "points", ()) or ()
        )
        if len(points) >= 2:
            selected.append(points)
        if len(selected) >= max_rays:
            break
    return tuple(selected)


def scene_rays_to_world_3d(
    rays_scene: Any,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Map (scene_x, scene_y, height_mm) into Quick3D world coordinates."""
    output: list[tuple[tuple[float, float, float], ...]] = []
    for ray in rays_scene or ():
        world: list[tuple[float, float, float]] = []
        for scene_x, scene_y, height_mm in ray:
            wx = (float(scene_x) - 800.0) * 0.76
            wy = 52.0 + (float(height_mm) - 82.0)
            wz = (float(scene_y) - 450.0) * 0.62
            world.append((wx, wy, wz))
        if len(world) >= 2:
            output.append(tuple(world))
    return tuple(output)


__all__ = [
    "experiment_model_to_physical_scene",
    "scene_rays_to_world_3d",
    "trace_paths_to_engine_rays",
    "trace_paths_to_scene_rays",
]
