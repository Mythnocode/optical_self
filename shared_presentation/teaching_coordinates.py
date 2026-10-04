"""Frozen teaching / simulation / view3d frames.

Teaching millimetres are the only scene truth.  Simulation and the future
Qt Quick 3D view are derived.  Render coordinates must never be written into
``Pose`` or sent to the engine.

Teaching ``teaching_bench_mm`` (right-handed, origin = bench datum):
  +X  along the rail (nominal propagation)
  +Y  lateral on the table
  +Z  up from the table surface (z=0 is the table)

Simulation ``simulation_engine_mm`` (right-handed, sequential-style):
  (X_e, Y_e, Z_e) = (Y_t, Z_t − axis_height_mm, X_t)
  A point at teaching (0, 0, axis_height_mm) maps to engine (0, 0, 0).

View ``view3d_render`` (Qt Quick 3D Y-up, table on XZ):
  (X_r, Y_r, Z_r) = (X_t, Z_t, −Y_t) × render_units_per_mm
  Table at Y_r = 0.  Nominal beam height is Y_r = axis_height_mm × scale, not a second origin.

``axis_height_mm`` (default 25, compact 1/2\" post class) is a bench property: the nominal
beam height above the table.  It is not the location of any source, and it is
not Newport 561's 79.4 mm.  It is used only by the engine map, never by the
view3d map.

Teaching orientation is ``R = Rz(yaw) Ry(−pitch) Rx(roll)``.  Simulation
rotations are conjugated by the axis permutation ``P``, not by swapping Euler
scalars.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


AXIS_HEIGHT_MM = 25.0
TABLE_HEIGHT_MM = AXIS_HEIGHT_MM  # back-compat alias; means optical-axis height
RENDER_UNITS_PER_MM = 1.0

FRAME_TEACHING = "teaching_bench_mm"
FRAME_ENGINE = "simulation_engine_mm"
FRAME_RENDER = "view3d_render"

FRAMES = {
    "teaching": FRAME_TEACHING,
    "simulation": FRAME_ENGINE,
    "view3d": FRAME_RENDER,
}


@dataclass(frozen=True, slots=True)
class FrameTransform:
    """Affine maps among teaching millimetres, simulation millimetres, and view3d.

    The bench origin is frozen at the rail start on the table ``(0, 0, 0)``.
    ``origin_teaching_mm`` / ``origin_engine_mm`` are kept for payload
    compatibility and are always coerced to zero.  ``axis_height_mm`` remains a
    bench property used only by the engine map.
    """

    origin_teaching_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    origin_engine_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis_height_mm: float = AXIS_HEIGHT_MM
    render_units_per_mm: float = RENDER_UNITS_PER_MM

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin_teaching_mm", (0.0, 0.0, 0.0))
        object.__setattr__(self, "origin_engine_mm", (0.0, 0.0, 0.0))
        object.__setattr__(self, "axis_height_mm", float(self.axis_height_mm))
        object.__setattr__(self, "render_units_per_mm", float(self.render_units_per_mm))

    @property
    def table_height_mm(self) -> float:
        return float(self.axis_height_mm)

    def teaching_to_engine(self, point: Iterable[float]) -> tuple[float, float, float]:
        x_t, y_t, z_t = (float(value) for value in point)
        return (
            y_t,
            z_t - float(self.axis_height_mm),
            x_t,
        )

    def engine_to_teaching(self, point: Iterable[float]) -> tuple[float, float, float]:
        x_e, y_e, z_e = (float(value) for value in point)
        return (
            z_e,
            x_e,
            y_e + float(self.axis_height_mm),
        )

    def teaching_direction_to_engine(self, direction: Iterable[float]) -> tuple[float, float, float]:
        dx, dy, dz = (float(value) for value in direction)
        return dy, dz, dx

    def engine_direction_to_teaching(self, direction: Iterable[float]) -> tuple[float, float, float]:
        dx, dy, dz = (float(value) for value in direction)
        return dz, dx, dy

    def teaching_to_render(self, point: Iterable[float]) -> tuple[float, float, float]:
        """Qt Y-up table frame.  Independent of the engine permutation."""
        x_t, y_t, z_t = (float(value) for value in point)
        scale = float(self.render_units_per_mm)
        return x_t * scale, z_t * scale, -y_t * scale

    def render_to_teaching(self, point: Iterable[float]) -> tuple[float, float, float]:
        x_r, y_r, z_r = (float(value) for value in point)
        scale = max(float(self.render_units_per_mm), 1.0e-12)
        return x_r / scale, -z_r / scale, y_r / scale

    def teaching_direction_to_render(self, direction: Iterable[float]) -> tuple[float, float, float]:
        dx, dy, dz = (float(value) for value in direction)
        scale = float(self.render_units_per_mm)
        return dx * scale, dz * scale, -dy * scale

    def render_direction_to_teaching(self, direction: Iterable[float]) -> tuple[float, float, float]:
        dx, dy, dz = (float(value) for value in direction)
        scale = max(float(self.render_units_per_mm), 1.0e-12)
        return dx / scale, -dz / scale, dy / scale

    def engine_direction_to_render(self, direction: Iterable[float]) -> tuple[float, float, float]:
        return self.teaching_direction_to_render(self.engine_direction_to_teaching(direction))


DEFAULT_TRANSFORM = FrameTransform()

# Teaching (x, y, z) → engine (y, z, x).  det = 1.
_P = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
_PT = ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
# Teaching (x, y, z) → view3d (x, z, −y).  det = 1.
_P_RENDER = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
Mat3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
Quat = tuple[float, float, float, float]


def _rot_x(angle: float) -> Mat3:
    c, s = math.cos(angle), math.sin(angle)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _rot_y(angle: float) -> Mat3:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rot_z(angle: float) -> Mat3:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _matmul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]


def _matvec(a: Mat3, v: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(a[i][j] * v[j] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def teaching_rotation_matrix(yaw_rad: float, pitch_rad: float, roll_rad: float) -> Mat3:
    """R_t maps teaching body axes into the bench frame.  +X_body is the beam."""
    return _matmul(_rot_z(float(yaw_rad)), _matmul(_rot_y(-float(pitch_rad)), _rot_x(float(roll_rad))))


def engine_rotation_matrix(tilt_x_rad: float, tilt_y_rad: float, tilt_z_rad: float) -> Mat3:
    """R_e = Rx(tx) Ry(ty) Rz(tz).  Identity keeps the beam along +Z_e."""
    return _matmul(_rot_x(float(tilt_x_rad)), _matmul(_rot_y(float(tilt_y_rad)), _rot_z(float(tilt_z_rad))))


def _euler_zyx_neg_pitch(matrix: Mat3) -> tuple[float, float, float]:
    """Extract yaw, pitch, roll from R = Rz(yaw) Ry(−pitch) Rx(roll)."""
    sin_beta = max(-1.0, min(1.0, -matrix[2][0]))
    beta = math.asin(sin_beta)
    cos_beta = math.cos(beta)
    if abs(cos_beta) < 1.0e-8:
        yaw = math.atan2(-matrix[0][1], matrix[1][1])
        roll = 0.0
    else:
        yaw = math.atan2(matrix[1][0], matrix[0][0])
        roll = math.atan2(matrix[2][1], matrix[2][2])
    return yaw, -beta, roll


def _euler_xyz(matrix: Mat3) -> tuple[float, float, float]:
    """Extract tx, ty, tz from R = Rx(tx) Ry(ty) Rz(tz)."""
    sin_ty = max(-1.0, min(1.0, matrix[0][2]))
    ty = math.asin(sin_ty)
    cos_ty = math.cos(ty)
    if abs(cos_ty) < 1.0e-8:
        tx = math.atan2(matrix[1][0], matrix[1][1])
        tz = 0.0
    else:
        tx = math.atan2(-matrix[1][2], matrix[2][2])
        tz = math.atan2(-matrix[0][1], matrix[0][0])
    return tx, ty, tz


def conjugate_teaching_rotation_to_engine(matrix: Mat3) -> Mat3:
    return _matmul(_P, _matmul(matrix, _PT))


def conjugate_engine_rotation_to_teaching(matrix: Mat3) -> Mat3:
    return _matmul(_PT, _matmul(matrix, _P))


def teaching_rotation_to_render_matrix(matrix: Mat3) -> Mat3:
    """Map a teaching-body rotation into the view3d frame.

    Mesh local axes match teaching axes (``+X`` optical, ``+Z`` up).  The
    parent node already lives in ``view3d_render``, so the loaded mesh needs
    ``R_r = P_render R_t``, not a cylinder ``+Y`` alignment.
    """
    return _matmul(_P_RENDER, matrix)


def _quat_normalize(w: float, x: float, y: float, z: float) -> Quat:
    length = math.sqrt(w * w + x * x + y * y + z * z)
    if length < 1.0e-18:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / length, x / length, y / length, z / length)


def quaternion_from_rotation_matrix(matrix: Mat3) -> Quat:
    """Convert a right-handed rotation matrix to a Qt ``(w, x, y, z)`` quaternion."""
    m00, m01, m02 = matrix[0]
    m10, m11, m12 = matrix[1]
    m20, m21, m22 = matrix[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (m21 - m12) / scale
        y = (m02 - m20) / scale
        z = (m10 - m01) / scale
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w = (m21 - m12) / scale
        x = 0.25 * scale
        y = (m01 + m10) / scale
        z = (m02 + m20) / scale
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w = (m02 - m20) / scale
        x = (m01 + m10) / scale
        y = 0.25 * scale
        z = (m12 + m21) / scale
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w = (m10 - m01) / scale
        x = (m02 + m20) / scale
        y = (m12 + m21) / scale
        z = 0.25 * scale
    return _quat_normalize(w, x, y, z)


def teaching_orientation_to_render_quaternion(
    yaw_rad: float,
    pitch_rad: float,
    roll_rad: float = 0.0,
) -> Quat:
    """Quaternion placing a ``+X`` optical / ``+Z``-up mesh into ``view3d_render``."""
    rotation = teaching_rotation_to_render_matrix(teaching_rotation_matrix(yaw_rad, pitch_rad, roll_rad))
    return quaternion_from_rotation_matrix(rotation)


def beam_direction_teaching(yaw_rad: float, pitch_rad: float, roll_rad: float = 0.0) -> tuple[float, float, float]:
    """Unit direction of a beam that follows a component's yaw/pitch in teaching axes."""
    return _matvec(teaching_rotation_matrix(yaw_rad, pitch_rad, roll_rad), (1.0, 0.0, 0.0))


def teaching_angles_to_engine(
    yaw_rad: float,
    pitch_rad: float,
    roll_rad: float,
) -> tuple[float, float, float]:
    """Map teaching Euler angles onto simulation tilts through SO(3).

    ``R_e = P R_t Pᵀ``.  Extracted as ``Rx(tilt_x) Ry(tilt_y) Rz(tilt_z)``.
    Small yaw about +Z_t becomes tilt about +Y_e; small pitch maps to −tilt_x.
    """
    rotation = conjugate_teaching_rotation_to_engine(teaching_rotation_matrix(yaw_rad, pitch_rad, roll_rad))
    return _euler_xyz(rotation)


def engine_angles_to_teaching(
    tilt_x_rad: float,
    tilt_y_rad: float,
    tilt_z_rad: float,
) -> tuple[float, float, float]:
    rotation = conjugate_engine_rotation_to_teaching(engine_rotation_matrix(tilt_x_rad, tilt_y_rad, tilt_z_rad))
    return _euler_zyx_neg_pitch(rotation)


def rotate_teaching_about_axis(
    yaw_rad: float,
    pitch_rad: float,
    roll_rad: float,
    axis: str,
    delta_rad: float,
) -> tuple[float, float, float]:
    """Apply a world-axis increment in the teaching frame, then re-extract Euler."""
    key = str(axis).lower()
    if key == "x":
        increment = _rot_x(float(delta_rad))
    elif key == "y":
        increment = _rot_y(float(delta_rad))
    elif key == "z":
        increment = _rot_z(float(delta_rad))
    else:
        return float(yaw_rad), float(pitch_rad), float(roll_rad)
    rotated = _matmul(increment, teaching_rotation_matrix(yaw_rad, pitch_rad, roll_rad))
    return _euler_zyx_neg_pitch(rotated)


def teaching_point_to_simulation(
    point: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> tuple[float, float, float]:
    return transform.teaching_to_engine(point)


def simulation_point_to_teaching(
    point: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> tuple[float, float, float]:
    return transform.engine_to_teaching(point)


def teaching_point_to_render(
    point: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> tuple[float, float, float]:
    return transform.teaching_to_render(point)


def render_point_to_teaching(
    point: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> tuple[float, float, float]:
    return transform.render_to_teaching(point)


def teaching_pose_to_simulation(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    yaw_rad: float = 0.0,
    pitch_rad: float = 0.0,
    roll_rad: float = 0.0,
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> dict[str, Any]:
    """Convert one teaching pose into simulation millimetres and tilts."""
    position = transform.teaching_to_engine((x_mm, y_mm, z_mm))
    tilt_x, tilt_y, tilt_z = teaching_angles_to_engine(yaw_rad, pitch_rad, roll_rad)
    direction = transform.teaching_direction_to_engine(beam_direction_teaching(yaw_rad, pitch_rad, roll_rad))
    rotation = conjugate_teaching_rotation_to_engine(teaching_rotation_matrix(yaw_rad, pitch_rad, roll_rad))
    return {
        "x_mm": position[0],
        "y_mm": position[1],
        "z_mm": position[2],
        "tilt_x_rad": tilt_x,
        "tilt_y_rad": tilt_y,
        "tilt_z_rad": tilt_z,
        "tilt_x_deg": math.degrees(tilt_x),
        "tilt_y_deg": math.degrees(tilt_y),
        "tilt_z_deg": math.degrees(tilt_z),
        "direction": list(direction),
        "rotation_3x3": [list(row) for row in rotation],
        "frame": FRAME_ENGINE,
    }


ORIENTATION_SOURCE_TEACHING_SO3 = "teaching_engine_so3"


def engine_orientation_fields(
    yaw_rad: float,
    pitch_rad: float,
    roll_rad: float,
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> dict[str, Any]:
    """SO(3) tilts and +X axis in the engine frame.  Does not move the laser origin."""
    payload = teaching_pose_to_simulation(0.0, 0.0, AXIS_HEIGHT_MM, yaw_rad, pitch_rad, roll_rad, transform)
    return {
        "orientation_source": ORIENTATION_SOURCE_TEACHING_SO3,
        "tilt_x_deg": float(payload["tilt_x_deg"]),
        "tilt_y_deg": float(payload["tilt_y_deg"]),
        "tilt_z_deg": float(payload["tilt_z_deg"]),
        "axis_engine": list(payload["direction"]),
    }


def simulation_pose_to_teaching(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    tilt_x_rad: float = 0.0,
    tilt_y_rad: float = 0.0,
    tilt_z_rad: float = 0.0,
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> dict[str, Any]:
    position = transform.engine_to_teaching((x_mm, y_mm, z_mm))
    yaw, pitch, roll = engine_angles_to_teaching(tilt_x_rad, tilt_y_rad, tilt_z_rad)
    return {
        "x_mm": position[0],
        "y_mm": position[1],
        "z_mm": position[2],
        "yaw_rad": yaw,
        "pitch_rad": pitch,
        "roll_rad": roll,
        "yaw_deg": math.degrees(yaw),
        "pitch_deg": math.degrees(pitch),
        "roll_deg": math.degrees(roll),
        "frame": FRAME_TEACHING,
    }


def teaching_pose_to_render(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> dict[str, Any]:
    position = transform.teaching_to_render((x_mm, y_mm, z_mm))
    return {
        "x": position[0],
        "y": position[1],
        "z": position[2],
        "frame": FRAME_RENDER,
    }


def transform_from_reference(reference: Mapping[str, Any] | Any) -> FrameTransform:
    getter = reference.get if isinstance(reference, Mapping) else lambda key, default=None: getattr(reference, key, default)
    axis_height = getter("axis_height_mm", AXIS_HEIGHT_MM)
    if axis_height is None:
        axis_height = AXIS_HEIGHT_MM
    render_scale = getter("render_units_per_mm", RENDER_UNITS_PER_MM)
    if render_scale is None:
        render_scale = RENDER_UNITS_PER_MM
    return FrameTransform(
        axis_height_mm=float(axis_height),
        render_units_per_mm=float(render_scale),
    )


def physical_scene_scale_mm(axial_span_mm: float) -> tuple[float, float]:
    """Shim for the current teaching_runtime canvas-unit compiler.

    Runtime still does ``mm_per_scene = max_system_length / max(400, width-200)``.
    These two values force that scale to 1 so teaching millimetres can be passed
    as scene_x/scene_y.  This does not make the laser the world origin.
    """
    max_system_length_mm = max(400.0, float(axial_span_mm))
    scene_width_units = max_system_length_mm + 200.0
    return max_system_length_mm, scene_width_units


def mm_per_scene_unit(max_system_length_mm: float, scene_width_units: float) -> float:
    usable_span = max(400.0, float(scene_width_units) - 200.0)
    return max(1.0e-4, float(max_system_length_mm) / usable_span)


def teaching_pose_to_engine(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> tuple[float, float, float]:
    return transform.teaching_to_engine((x_mm, y_mm, z_mm))


def engine_point_to_teaching(
    point_mm: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
) -> tuple[float, float, float]:
    return transform.engine_to_teaching(point_mm)


def _close(a: Iterable[float], b: Iterable[float], tolerance: float) -> bool:
    return all(abs(float(left) - float(right)) <= tolerance for left, right in zip(tuple(a), tuple(b)))


def assert_round_trip(
    point: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
    *,
    tolerance: float = 1.0e-9,
) -> None:
    original = tuple(float(value) for value in point)
    recovered = transform.engine_to_teaching(transform.teaching_to_engine(original))
    if not _close(original, recovered, tolerance):
        raise AssertionError(f"engine round trip failed: {original!r} != {recovered!r}")


def assert_render_round_trip(
    point: Iterable[float],
    transform: FrameTransform = DEFAULT_TRANSFORM,
    *,
    tolerance: float = 1.0e-9,
) -> None:
    original = tuple(float(value) for value in point)
    recovered = transform.render_to_teaching(transform.teaching_to_render(original))
    if not _close(original, recovered, tolerance):
        raise AssertionError(f"render round trip failed: {original!r} != {recovered!r}")


__all__ = [
    "AXIS_HEIGHT_MM",
    "DEFAULT_TRANSFORM",
    "FRAME_ENGINE",
    "FRAME_RENDER",
    "FRAME_TEACHING",
    "FRAMES",
    "FrameTransform",
    "RENDER_UNITS_PER_MM",
    "TABLE_HEIGHT_MM",
    "assert_render_round_trip",
    "assert_round_trip",
    "beam_direction_teaching",
    "conjugate_engine_rotation_to_teaching",
    "conjugate_teaching_rotation_to_engine",
    "quaternion_from_rotation_matrix",
    "teaching_orientation_to_render_quaternion",
    "teaching_rotation_to_render_matrix",
    "engine_angles_to_teaching",
    "engine_orientation_fields",
    "engine_point_to_teaching",
    "engine_rotation_matrix",
    "mm_per_scene_unit",
    "physical_scene_scale_mm",
    "render_point_to_teaching",
    "rotate_teaching_about_axis",
    "simulation_point_to_teaching",
    "simulation_pose_to_teaching",
    "teaching_angles_to_engine",
    "teaching_point_to_render",
    "teaching_point_to_simulation",
    "teaching_pose_to_engine",
    "teaching_pose_to_render",
    "teaching_pose_to_simulation",
    "teaching_rotation_matrix",
    "transform_from_reference",
]
