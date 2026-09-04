from __future__ import annotations

"""Shared scene/projection helpers for the teaching virtual laboratory.

There is one physical experiment state.  Formal optical-engine rays are stored in
millimetres using the simulation convention ``(x, y, z)`` where ``z`` is the
longitudinal coordinate.  This module maps those same formal rays into:

* the side engineering projection (z vs y),
* the top engineering projection (z vs x), and
* the 3-D teaching world.

No function in this module reconnects apparatus centres or invents a path when a
formal raytrace is unavailable.  An empty formal-ray set therefore renders no
physical beam.
"""

from dataclasses import dataclass
from typing import Any, Iterable
import statistics
import math


# The scene compiles its own sequential project, so the longitudinal mm frame is
# the same 0.76 mm per scene pixel used by the shared scene/world transform.
# z = 0 sits at the first lens surface; a component at scene x owns z = (x - anchor) * SCENE_MM_PER_PX.
SCENE_MM_PER_PX = 0.76


def scene_node_world_3d(node: Any) -> tuple[float, float, float]:
    """Map one experiment node to the canonical optical-centre coordinates.

    ``world_y`` follows the physical ``z_mm`` optical height.  Engineering
    projections use this transform because vertical misalignment is meaningful
    there.  Quick3D *mechanical assets* use :func:`scene_node_mount_world_3d`
    instead so their bases remain on the optical table even when a saved state
    contains a non-standard optical height.
    """
    scene_x = float(getattr(node, "x", 800.0))
    scene_y = float(getattr(node, "y", 450.0))
    params = dict(getattr(node, "params", {}) or {})
    optical_height_mm = float(params.get("z_mm", 82.0) or 82.0)
    world_x = (scene_x - 800.0) * 0.76
    world_y = 52.0 + (optical_height_mm - 82.0)
    world_z = (scene_y - 450.0) * 0.62
    return world_x, world_y, world_z


def scene_node_mount_world_3d(node: Any) -> tuple[float, float, float]:
    """Return the grounded root position for a tabletop Quick3D asset.

    All built-in procedural teaching assets share the same local convention:
    optical centre at local ``y=0`` and mechanical foot at local ``y=-61``.
    With root ``y=52`` that foot lands on the table top at world ``y=-9``.
    The old code moved the *whole mount* when ``z_mm`` changed, producing
    visibly floating bases.  Until a component has an explicit telescopic
    vertical-stage model, grounding the mechanics is both clearer and more
    truthful than levitating the complete assembly.
    """
    world_x, _optical_world_y, world_z = scene_node_world_3d(node)
    return world_x, 52.0, world_z


def project_scene_node_2d(
    node: Any,
    *,
    plane: str,
    rail_y: float,
) -> tuple[float, float]:
    """Orthographic semantic projection of the same apparatus world transform."""
    world_x, world_y, world_z = scene_node_world_3d(node)
    scene_x = world_x / 0.76 + 800.0
    if str(plane).lower() == "top":
        scene_depth = world_z / 0.62 + 450.0
        return float(scene_x), float(scene_depth)
    # Side view projects world X/Y.  Use the workbench rail as the optical-axis
    # datum and exaggerate only vertical displacement for legibility.
    return float(scene_x), float(rail_y - (world_y - 52.0) * 4.0)


@dataclass(frozen=True, slots=True)
class SceneRayMapping:
    anchor_scene_x: float
    mm_per_px: float
    transverse_px_per_mm: float = 120.0
    # Optional semantic layout mapping.  Formal distances remain in millimetres,
    # while the teaching apparatus may use wider screen spacing for draggable
    # hardware.  Piecewise interpolation keeps every traced surface on its own
    # icon without changing any physical distance in the solver.
    longitudinal_breakpoints: tuple[tuple[float, float], ...] = ()

    def scene_x(self, z_mm: float) -> float:
        points = self.longitudinal_breakpoints
        if len(points) >= 2:
            z = float(z_mm)
            if z <= points[0][0]:
                z0, x0 = points[0]
                z1, x1 = points[1]
            elif z >= points[-1][0]:
                z0, x0 = points[-2]
                z1, x1 = points[-1]
            else:
                for (z0, x0), (z1, x1) in zip(points, points[1:]):
                    if z0 <= z <= z1:
                        break
            if abs(z1 - z0) > 1e-12:
                return x0 + (z - z0) * (x1 - x0) / (z1 - z0)
        return self.anchor_scene_x + float(z_mm) / self.mm_per_px

    def formal_z(self, scene_x: float) -> float:
        points = self.longitudinal_breakpoints
        if len(points) >= 2:
            x = float(scene_x)
            if x <= points[0][1]:
                z0, x0 = points[0]
                z1, x1 = points[1]
            elif x >= points[-1][1]:
                z0, x0 = points[-2]
                z1, x1 = points[-1]
            else:
                for (z0, x0), (z1, x1) in zip(points, points[1:]):
                    if x0 <= x <= x1:
                        break
            if abs(x1 - x0) > 1e-12:
                return z0 + (x - x0) * (z1 - z0) / (x1 - x0)
        return (float(scene_x) - self.anchor_scene_x) * self.mm_per_px


def _formal_points(formal_rays_mm: Iterable[Iterable[Iterable[float]]]) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for ray in formal_rays_mm or ():
        for point in ray or ():
            try:
                x, y, z = point
                points.append((float(x), float(y), float(z)))
            except Exception:
                continue
    return points


def representative_formal_rays(
    formal_rays_mm: Iterable[Iterable[Iterable[float]]],
    *,
    max_rays: int = 5,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Reduce dense pupil ray sets to a readable, deterministic teaching subset.

    Formal raytrace jobs may return thousands of pupil samples.  Drawing all of
    them turns a teaching view into a solid orange polygon.  The default is only
    five actual rays (chief + sparse boundary representatives); callers that need
    denser engineering inspection can explicitly request a larger ``max_rays``.
    This selector keeps the chief ray plus radial representatives in angular sectors;
    every retained path is still an actual formal ray, never an interpolated one.
    """
    rays = tuple(
        tuple(tuple(float(v) for v in point) for point in ray)
        for ray in (formal_rays_mm or ())
        if len(ray) >= 2
    )
    max_rays = max(0, int(max_rays))
    if max_rays == 0 or not rays:
        return ()
    if len(rays) <= max_rays:
        return rays
    if max_rays == 1:
        # One physical ray is enough for the teaching 3-D view.  Prefer the
        # chief/near-axis formal ray instead of the first arbitrary pupil sample.
        chief_index = min(
            range(len(rays)),
            key=lambda index: math.hypot(float(rays[index][0][0]), float(rays[index][0][1])),
        )
        return (rays[chief_index],)
    descriptors = []
    for index, ray in enumerate(rays):
        x, y, _z = ray[0]
        radius = math.hypot(x, y)
        angle = math.atan2(y, x)
        descriptors.append((index, radius, angle))
    selected: set[int] = {min(descriptors, key=lambda item: item[1])[0]}
    sectors = max(4, min(8, (max_rays - 1) // 2))
    for sector in range(sectors):
        lo = -math.pi + sector * (2.0 * math.pi / sectors)
        hi = -math.pi + (sector + 1) * (2.0 * math.pi / sectors)
        bucket = [item for item in descriptors if lo <= item[2] < hi or (sector == sectors - 1 and item[2] == math.pi)]
        if not bucket:
            continue
        bucket.sort(key=lambda item: item[1])
        selected.add(bucket[-1][0])
        selected.add(bucket[len(bucket) // 2][0])
    # If sectors were sparse, fill with evenly spaced real rays.
    if len(selected) < max_rays:
        step = max(1, len(rays) // max_rays)
        for index in range(0, len(rays), step):
            selected.add(index)
            if len(selected) >= max_rays:
                break
    return tuple(rays[index] for index in sorted(selected)[:max_rays])


def build_ray_mapping(model: Any, formal_rays_mm: Iterable[Iterable[Iterable[float]]]) -> SceneRayMapping | None:
    """Map formal ray z (mm) back onto the scene's own longitudinal axis.

    The teaching scene compiles its lens/fiber train into the sequential project,
    so z = 0 sits at the first lens surface and z grows by ``SCENE_MM_PER_PX``
    per scene pixel.  Inverting that same transform places every ray point at the
    scene x of the component that owns that z, so a ray hitting a lens lands
    exactly on that lens' icon instead of being stretched to arbitrary endpoints.
    """
    points = _formal_points(formal_rays_mm)
    if len(points) < 2:
        return None
    lenses = sorted([
        node for node in dict(getattr(model, "nodes", {}) or {}).values()
        if str(getattr(node, "kind", "")) == "lens"
    ], key=lambda node: float(getattr(node, "x", 0.0)))
    if not lenses:
        return None
    anchor_scene_x = min(float(getattr(node, "x", 0.0)) for node in lenses)
    receiver = next(
        (
            node for node in sorted(
                dict(getattr(model, "nodes", {}) or {}).values(),
                key=lambda item: float(getattr(item, "x", 0.0)),
            )
            if str(getattr(node, "kind", "")) in {"fiber", "imaging_camera", "focus_scan_module", "beam_analyzer", "ccd", "camera"}
            and float(getattr(node, "x", 0.0)) > float(getattr(lenses[-1], "x", 0.0))
        ),
        None,
    )
    ordered = lenses + ([receiver] if receiver is not None else [])
    cumulative_z = 0.0
    breakpoints: list[tuple[float, float]] = [(0.0, float(getattr(lenses[0], "x", 0.0)))]
    for current, nxt in zip(ordered, ordered[1:]):
        params = dict(getattr(current, "params", {}) or {})
        thickness = float(params.get("thickness_mm", 3.0) or 3.0) if str(getattr(current, "kind", "")) == "lens" else 0.0
        if "air_gap_after_mm" in params:
            distance = thickness + float(params.get("air_gap_after_mm", 0.0) or 0.0)
        elif "distance_to_next_mm" in params:
            distance = float(params.get("distance_to_next_mm", 0.0) or 0.0)
        else:
            distance = (float(getattr(nxt, "x", 0.0)) - float(getattr(current, "x", 0.0))) * SCENE_MM_PER_PX
        if distance > 1e-9:
            cumulative_z += distance
            breakpoints.append((cumulative_z, float(getattr(nxt, "x", 0.0))))

    # Teaching apparatus icons are small.  Always stretching the formal pupil to
    # ±38 px made every focusing train look like a dramatic V that dwarfs the
    # lenses — optically correct, but visually “wrong”.  Prefer a stable
    # ~12 px/mm scale and keep the tallest formal ray within ~16 px of the rail.
    transverse_extent_mm = max(
        [abs(point[0]) for point in points] + [abs(point[1]) for point in points] + [1e-6]
    )
    natural_scale = 12.0
    capped_scale = 16.0 / max(transverse_extent_mm, 1e-6)
    transverse_scale = max(4.0, min(natural_scale, capped_scale, 40.0))
    if transverse_extent_mm * transverse_scale < 4.0:
        transverse_scale = 4.0 / max(transverse_extent_mm, 1e-6)
    return SceneRayMapping(
        anchor_scene_x, SCENE_MM_PER_PX,
        transverse_px_per_mm=transverse_scale,
        longitudinal_breakpoints=tuple(breakpoints),
    )



def main_rail_y(model: Any, fallback: float = 310.0) -> float:
    nodes = list(dict(getattr(model, "nodes", {}) or {}).values())
    optical_kinds = {
        "laser", "isolator", "half_wave_plate", "pbs", "splitter", "beam_sampler",
        "mirror", "lens", "aperture", "fiber", "source", "receiver",
    }
    values = [float(getattr(node, "y", fallback)) for node in nodes if str(getattr(node, "kind", "")) in optical_kinds]
    if not values:
        return float(fallback)
    # Most presets share one main rail plus a few off-axis diagnostic branches;
    # the median is robust to those branches.
    return float(statistics.median(values))

def _laser_start_z_mm(model: Any, mapping: SceneRayMapping) -> float | None:
    """Longitudinal z of the scene's laser in the compiled mm frame (negative)."""
    laser = next(
        (node for node in dict(getattr(model, "nodes", {}) or {}).values()
         if str(getattr(node, "kind", "")) == "laser"),
        None,
    )
    if laser is None:
        return None
    z_laser = mapping.formal_z(float(getattr(laser, "x", 0.0)))
    return z_laser if z_laser < 0.0 else None


def _extend_rays_to_laser(
    rays: Iterable[Iterable[Iterable[float]]],
    model: Any,
    mapping: SceneRayMapping,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Prepend each ray's free-space continuation back to the laser.

    The sequential trace starts at the first lens surface.  Extending each ray
    backward along its own initial direction to the laser's z keeps the visible
    beam following the whole scene train instead of appearing at the first lens.
    """
    z_laser = _laser_start_z_mm(model, mapping)
    if z_laser is None:
        return tuple(tuple(tuple(float(v) for v in point) for point in ray) for ray in rays)
    extended: list[tuple[tuple[float, float, float], ...]] = []
    for ray in rays:
        points = [tuple(float(v) for v in point) for point in ray]
        if len(points) < 2:
            extended.append(tuple(points))
            continue
        p0, p1 = points[0], points[1]
        dz = p1[2] - p0[2]
        if dz > 1e-12 and z_laser < p0[2]:
            t = (z_laser - p0[2]) / dz
            start = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]), z_laser)
            extended.append((start, *points))
        else:
            extended.append(tuple(points))
    return tuple(extended)


def project_formal_rays_2d(
    model: Any,
    formal_rays_mm: Iterable[Iterable[Iterable[float]]],
    *,
    plane: str = "side",
    rail_y: float | None = None,
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Project the same formal rays into a semantic engineering view.

    ``side`` shows the longitudinal axis versus formal ``y``; ``top`` shows it
    versus formal ``x``.  Apparatus layout and optical state stay unchanged.
    """
    rays = representative_formal_rays(formal_rays_mm)
    mapping = build_ray_mapping(model, formal_rays_mm)
    if mapping is None:
        return ()
    rays = _extend_rays_to_laser(rays, model, mapping)
    use_top = str(plane).lower() == "top"
    rail_y = main_rail_y(model) if rail_y is None else float(rail_y)
    output: list[tuple[tuple[float, float], ...]] = []
    for ray in rays:
        projected: list[tuple[float, float]] = []
        for x_mm, y_mm, z_mm in ray:
            transverse = x_mm if use_top else y_mm
            projected.append((mapping.scene_x(z_mm), float(rail_y) - transverse * mapping.transverse_px_per_mm))
        if len(projected) >= 2:
            output.append(tuple(projected))
    return tuple(output)



def formal_rays_scene_3d(
    model: Any,
    formal_rays_mm: Iterable[Iterable[Iterable[float]]],
    *,
    optical_height: float = 82.0,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Map formal rays into the painter-based 3-D scene coordinate convention."""
    rays = representative_formal_rays(formal_rays_mm)
    mapping = build_ray_mapping(model, formal_rays_mm)
    if mapping is None:
        return ()
    rays = _extend_rays_to_laser(rays, model, mapping)
    rail = main_rail_y(model)
    output: list[tuple[tuple[float, float, float], ...]] = []
    for ray in rays:
        scene_ray: list[tuple[float, float, float]] = []
        for x_mm, y_mm, z_mm in ray:
            scene_ray.append((
                mapping.scene_x(z_mm),
                rail + x_mm * mapping.transverse_px_per_mm,
                float(optical_height) + y_mm * mapping.transverse_px_per_mm,
            ))
        if len(scene_ray) >= 2:
            output.append(tuple(scene_ray))
    return tuple(output)

def _densify_ray_points(
    points: tuple[tuple[float, float, float], ...],
    *,
    max_segment_mm: float = 8.0,
) -> tuple[tuple[float, float, float], ...]:
    """Insert free-space samples so Quick3D does not draw one giant cylinder per surface hop."""
    if len(points) < 2:
        return points
    out: list[tuple[float, float, float]] = [points[0]]
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        length = math.hypot(dx, math.hypot(dy, dz))
        steps = max(1, int(math.ceil(length / max(max_segment_mm, 1e-6))))
        for step in range(1, steps + 1):
            t = step / steps
            out.append((start[0] + dx * t, start[1] + dy * t, start[2] + dz * t))
    return tuple(out)


def formal_rays_world_3d(
    model: Any,
    formal_rays_mm: Iterable[Iterable[Iterable[float]]],
    *,
    world_height: float = 52.0,
    max_rays: int = 1,
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Map formal rays into the same world convention used by Quick3D assets.

    Nodes sit at world z = (scene_y - 450) * 0.62, so the rail (``main_rail_y``)
    is a constant depth offset below the table centre.  The beam must share that
    datum or it floats off the apparatus along the depth axis.
    """
    rays = representative_formal_rays(formal_rays_mm, max_rays=max(1, int(max_rays)))
    mapping = build_ray_mapping(model, formal_rays_mm)
    if mapping is None:
        return ()
    rays = _extend_rays_to_laser(rays, model, mapping)
    # Formal y is vertical in 3-D; formal x is table-depth.  Use the same
    # semantic scale as the 2-D projection converted through the existing
    # scene/world factors, anchored at the rail depth where the nodes sit.
    depth_scale = mapping.transverse_px_per_mm * 0.62
    height_scale = mapping.transverse_px_per_mm * 0.62
    rail_depth = (main_rail_y(model) - 450.0) * 0.62
    output: list[tuple[tuple[float, float, float], ...]] = []
    for ray in rays:
        world_ray: list[tuple[float, float, float]] = []
        for x_mm, y_mm, z_mm in _densify_ray_points(tuple(ray)):
            sx = mapping.scene_x(z_mm)
            wx = (sx - 800.0) * 0.76
            wy = float(world_height) + y_mm * height_scale
            wz = rail_depth + x_mm * depth_scale
            world_ray.append((wx, wy, wz))
        if len(world_ray) >= 2:
            output.append(tuple(world_ray))
    return tuple(output)


CAMERA_RECEIVER_KINDS = ("imaging_camera", "camera", "beam_analyzer", "ccd")


def _directed_node_path(model: Any, target_id: str) -> tuple[str, ...]:
    nodes = dict(getattr(model, "nodes", {}) or {})
    adjacency: dict[str, list[str]] = {}
    for edge in dict(getattr(model, "edges", {}) or {}).values():
        source = str(getattr(edge, "source", "") or "")
        dest = str(getattr(edge, "target", "") or "")
        if source and dest and source in nodes and dest in nodes:
            adjacency.setdefault(source, []).append(dest)
    lasers = [
        str(getattr(node, "id", "")) for node in nodes.values()
        if str(getattr(node, "kind", "")) == "laser"
    ]
    for laser_id in lasers:
        queue: list[tuple[str, tuple[str, ...]]] = [(laser_id, (laser_id,))]
        visited = {laser_id}
        while queue:
            current, path = queue.pop(0)
            if current == target_id:
                return path
            for dest in adjacency.get(current, ()):
                if dest in visited:
                    continue
                visited.add(dest)
                queue.append((dest, (*path, dest)))
    return ()


def _scene_point_world_3d(scene_x: float, scene_y: float, height_mm: float = 82.0) -> tuple[float, float, float]:
    return (
        (float(scene_x) - 800.0) * 0.76,
        52.0 + (float(height_mm) - 82.0),
        (float(scene_y) - 450.0) * 0.62,
    )


def routed_receiver_world_ray(
    model: Any,
    *,
    receiver_kinds: tuple[str, ...] = CAMERA_RECEIVER_KINDS,
) -> tuple[tuple[str, tuple[float, float, float]], ...]:
    """Return one receiver-oriented chief-ray chain for Quick3D.

    A valid imaging receiver gets an exact routed laser→receiver chain.  If an
    imaging receiver exists but has been moved off its diagnostic branch, the
    red chief ray follows that branch only to the closest physical pass-by point
    and stops there.  The renderer therefore shows a *miss* instead of silently
    reverting to an unrelated fibre endpoint or drawing a fake line to the
    camera.  Receiver orientation is still validated by ``instrument_reading``;
    a badly rotated camera may be geometrically hit while the image panel stays
    dark, which is the physically useful teaching behaviour.
    """
    nodes = dict(getattr(model, "nodes", {}) or {})
    if not nodes:
        return ()
    rebuild = getattr(model, "rebuild_auto_paths", None)
    if callable(rebuild):
        try:
            rebuild()
        except Exception:
            pass

    priority = {kind: index for index, kind in enumerate(receiver_kinds)}
    selected_id = str(getattr(model, "selected_node_id", "") or "")
    candidates = [node for node in nodes.values() if str(getattr(node, "kind", "")) in priority]
    candidates.sort(key=lambda node: (
        0 if str(getattr(node, "id", "")) == selected_id else 1,
        priority.get(str(getattr(node, "kind", "")), 999),
    ))
    if not candidates:
        return ()

    readings: list[tuple[Any, dict[str, Any]]] = []
    for node in candidates:
        try:
            reading = dict(model.instrument_reading(str(getattr(node, "id", ""))) or {})
        except Exception:
            reading = {}
        readings.append((node, reading))
    target, reading = next(
        ((node, reading) for node, reading in readings if bool(reading.get("valid", False))),
        readings[0],
    )
    target_id = str(getattr(target, "id", "") or "")

    # Geometric routing can still reach a detector whose *orientation* is bad.
    # Keep that path visible; imageReceiverHit will remain false.
    direct_path = _directed_node_path(model, target_id)
    if direct_path:
        return tuple((node_id, scene_node_world_3d(nodes[node_id])) for node_id in direct_path if node_id in nodes)

    # Position miss: locate the diagnostic splitter/sampler whose reflected
    # branch passes closest to the receiver.  This is a real routed direction,
    # not a centre-to-centre connection to the missed detector.
    target_x = float(getattr(target, "x", 0.0))
    target_y = float(getattr(target, "y", 0.0))
    incident_map = dict(getattr(model, "_incident_angles", {}) or {})
    best: tuple[float, Any, float, float, tuple[str, ...]] | None = None
    for optic in nodes.values():
        if str(getattr(optic, "kind", "")) not in {"splitter", "pbs", "beam_sampler"}:
            continue
        optic_id = str(getattr(optic, "id", "") or "")
        path_to_optic = _directed_node_path(model, optic_id)
        if not path_to_optic:
            continue
        incoming = incident_map.get(optic_id)
        if incoming is None and len(path_to_optic) >= 2:
            prev = nodes[path_to_optic[-2]]
            incoming = math.degrees(math.atan2(float(optic.y) - float(prev.y), float(optic.x) - float(prev.x))) % 360.0
        if incoming is None:
            continue
        turn = float(getattr(optic, "params", {}).get("branch_offset_deg", 90.0) or 90.0)
        outgoing = math.radians((float(incoming) + turn) % 360.0)
        ux, uy = math.cos(outgoing), math.sin(outgoing)
        dx = target_x - float(getattr(optic, "x", 0.0))
        dy = target_y - float(getattr(optic, "y", 0.0))
        t = dx * ux + dy * uy
        if t <= 1.0:
            continue
        miss_x = float(getattr(optic, "x", 0.0)) + t * ux
        miss_y = float(getattr(optic, "y", 0.0)) + t * uy
        miss_distance = math.hypot(target_x - miss_x, target_y - miss_y)
        # More than ~180 scene units away is not plausibly this detector's branch.
        if miss_distance > 180.0:
            continue
        score = miss_distance + 0.001 * t
        if best is None or score < best[0]:
            best = (score, optic, miss_x, miss_y, path_to_optic)
    if best is None:
        return ()

    _score, optic, miss_x, miss_y, path_to_optic = best
    routed = [(node_id, scene_node_world_3d(nodes[node_id])) for node_id in path_to_optic if node_id in nodes]
    height = float(getattr(optic, "params", {}).get("z_mm", 82.0) or 82.0)
    routed.append((f"miss:{target_id}", _scene_point_world_3d(miss_x, miss_y, height)))
    return tuple(routed)


def formal_ray_segments_world_3d(
    model: Any,
    formal_rays_mm: Iterable[Iterable[Iterable[float]]],
) -> tuple[tuple[tuple[float, float, float], tuple[float, float, float]], ...]:
    segments = []
    for ray in formal_rays_world_3d(model, formal_rays_mm):
        for start, end in zip(ray, ray[1:]):
            segments.append((start, end))
    return tuple(segments)
