"""Teaching-axis gizmo math in the frozen view3d render frame.

Render mapping: (X_r, Y_r, Z_r) = (X_t, Z_t, −Y_t).
  teaching +X → render +X
  teaching +Y → render −Z
  teaching +Z → render +Y

Axis drag uses the closest point between the mouse ray and the teaching axis.
Plane drag intersects the mouse ray with the render plane of the two free axes.
Locked teaching coordinates are taken from the press pose, never from the ray.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from .coordinates import DEFAULT_TRANSFORM, FrameTransform, rotate_teaching_about_axis


Vec3 = tuple[float, float, float]

AXIS_PARALLEL_DOT = 0.999

AXIS_RENDER = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 0.0, -1.0),
    "z": (0.0, 1.0, 0.0),
}

PLANE_RENDER_NORMAL = {
    "xy": (0.0, 1.0, 0.0),  # constant teaching z / render Y
    "xz": (0.0, 0.0, 1.0),  # constant teaching y / render Z
    "yz": (1.0, 0.0, 0.0),  # constant teaching x / render X
}

PLANE_FREE = {
    "xy": ("x", "y"),
    "xz": ("x", "z"),
    "yz": ("y", "z"),
}


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a: Vec3, scale: float) -> Vec3:
    return (a[0] * scale, a[1] * scale, a[2] * scale)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vec3) -> Vec3:
    length = math.sqrt(max(_dot(a, a), 1.0e-18))
    return _mul(a, 1.0 / length)


def closest_point_on_axis(origin: Vec3, direction: Vec3, ray_origin: Vec3, ray_direction: Vec3) -> Vec3 | None:
    """Closest point on the infinite axis line to the mouse ray."""
    axis = _norm(direction)
    ray = _norm(ray_direction)
    w0 = _sub(origin, ray_origin)
    b = _dot(axis, ray)
    d = _dot(axis, w0)
    e = _dot(ray, w0)
    denom = 1.0 - b * b
    if abs(b) >= AXIS_PARALLEL_DOT or abs(denom) < 1.0e-3:
        s = _dot(axis, _sub(ray_origin, origin))
    else:
        s = (b * e - d) / denom
    if not math.isfinite(s) or abs(s) > 1.0e6:
        return None
    return _add(origin, _mul(axis, s))


def intersect_ray_plane(ray_origin: Vec3, ray_direction: Vec3, plane_point: Vec3, plane_normal: Vec3) -> Vec3 | None:
    normal = _norm(plane_normal)
    denom = _dot(ray_direction, normal)
    if abs(denom) < 1.0e-10:
        return None
    t = _dot(_sub(plane_point, ray_origin), normal) / denom
    if t < 0.0:
        return None
    return _add(ray_origin, _mul(ray_direction, t))


def _lock_to_axes(origin: Vec3, proposed: Vec3, free: Iterable[str]) -> Vec3:
    allowed = set(free)
    x = proposed[0] if "x" in allowed else origin[0]
    y = proposed[1] if "y" in allowed else origin[1]
    z = max(0.0, proposed[2] if "z" in allowed else origin[2])
    return (float(x), float(y), float(z))


@dataclass(slots=True)
class GizmoSession:
    component_id: str
    mode: str
    name: str
    origin_teaching: Vec3
    grab_offset: Vec3
    transform: FrameTransform = DEFAULT_TRANSFORM

    def hit_teaching(self, ray_origin: Vec3, ray_direction: Vec3) -> Vec3 | None:
        origin_render = self.transform.teaching_to_render(self.origin_teaching)
        if self.mode == "axis":
            direction = AXIS_RENDER[self.name]
            hit_render = closest_point_on_axis(origin_render, direction, ray_origin, ray_direction)
        else:
            normal = PLANE_RENDER_NORMAL[self.name]
            hit_render = intersect_ray_plane(ray_origin, ray_direction, origin_render, normal)
        if hit_render is None:
            return None
        return self.transform.render_to_teaching(hit_render)

    def apply(self, ray_origin: Vec3, ray_direction: Vec3) -> Vec3 | None:
        hit = self.hit_teaching(ray_origin, ray_direction)
        if hit is None:
            return None
        proposed = (
            hit[0] + self.grab_offset[0],
            hit[1] + self.grab_offset[1],
            hit[2] + self.grab_offset[2],
        )
        free = (self.name,) if self.mode == "axis" else PLANE_FREE[self.name]
        return _lock_to_axes(self.origin_teaching, proposed, free)


@dataclass(slots=True)
class RotateSession:
    component_id: str
    axis: str
    origin_teaching: Vec3
    origin_angles: Vec3
    grab_angle: float
    transform: FrameTransform = DEFAULT_TRANSFORM

    def plane_angle(self, ray_origin: Vec3, ray_direction: Vec3) -> float | None:
        origin_render = self.transform.teaching_to_render(self.origin_teaching)
        normal = AXIS_RENDER[self.axis]
        hit = intersect_ray_plane(ray_origin, ray_direction, origin_render, normal)
        if hit is None:
            return None
        rel = _sub(hit, origin_render)
        reference = (1.0, 0.0, 0.0) if abs(_dot(normal, (1.0, 0.0, 0.0))) < 0.9 else (0.0, 0.0, 1.0)
        tangent = _norm(_sub(reference, _mul(normal, _dot(reference, normal))))
        bitangent = _norm((
            normal[1] * tangent[2] - normal[2] * tangent[1],
            normal[2] * tangent[0] - normal[0] * tangent[2],
            normal[0] * tangent[1] - normal[1] * tangent[0],
        ))
        return math.atan2(_dot(rel, bitangent), _dot(rel, tangent))

    def apply(self, ray_origin: Vec3, ray_direction: Vec3) -> Vec3 | None:
        angle = self.plane_angle(ray_origin, ray_direction)
        if angle is None:
            return None
        return rotate_teaching_about_axis(
            self.origin_angles[0],
            self.origin_angles[1],
            self.origin_angles[2],
            self.axis,
            angle - self.grab_angle,
        )


def begin_gizmo_session(
    component_id: str,
    mode: str,
    name: str,
    origin_teaching: Iterable[float],
    ray_origin: Iterable[float],
    ray_direction: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> GizmoSession | None:
    mode = str(mode)
    name = str(name).lower()
    if mode not in {"axis", "plane"}:
        return None
    if mode == "axis" and name not in AXIS_RENDER:
        return None
    if mode == "plane" and name not in PLANE_RENDER_NORMAL:
        return None
    origin = tuple(float(value) for value in origin_teaching)
    session = GizmoSession(component_id, mode, name, origin, (0.0, 0.0, 0.0), transform)
    hit = session.hit_teaching(tuple(float(v) for v in ray_origin), tuple(float(v) for v in ray_direction))
    if hit is None:
        return None
    session.grab_offset = (origin[0] - hit[0], origin[1] - hit[1], origin[2] - hit[2])
    return session


def begin_rotate_session(
    component_id: str,
    axis: str,
    origin_teaching: Iterable[float],
    origin_angles: Iterable[float],
    ray_origin: Iterable[float],
    ray_direction: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> RotateSession | None:
    axis = str(axis).lower()
    if axis not in AXIS_RENDER:
        return None
    origin = tuple(float(value) for value in origin_teaching)
    angles = tuple(float(value) for value in origin_angles)
    session = RotateSession(component_id, axis, origin, angles, 0.0, transform)
    grab = session.plane_angle(tuple(float(v) for v in ray_origin), tuple(float(v) for v in ray_direction))
    if grab is None:
        return None
    session.grab_angle = grab
    return session


__all__ = [
    "AXIS_PARALLEL_DOT",
    "AXIS_RENDER",
    "GizmoSession",
    "PLANE_FREE",
    "PLANE_RENDER_NORMAL",
    "RotateSession",
    "begin_gizmo_session",
    "begin_rotate_session",
    "closest_point_on_axis",
    "intersect_ray_plane",
]
