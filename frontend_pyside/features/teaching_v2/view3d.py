"""Teaching bench View3D: orbit camera, teaching-axis gizmo, ray overlay.

Display uses ``view3d_render``.  Gizmo hits are converted with
``render_to_teaching`` before writing ``Pose``.  Render coordinates are never
stored.  Optional ``.glb`` bodies load through Quick3D RuntimeLoader; Qt
primitives remain the fallback when a mesh is missing or fails to load.
"""

from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import tempfile
from typing import Any

from PySide6.QtCore import Property, QEvent, QObject, QPointF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .assets import (
    ASSET_DIR,
    BREADBOARD_HOLE_PITCH_MM,
    BREADBOARD_KEY,
    BREADBOARD_LENGTH_MM,
    BREADBOARD_WIDTH_MM,
    FIBER_MOUNT_PAD_HEIGHT_MM,
    FIBER_MOUNT_PAD_LENGTH_MM,
    FIBER_MOUNT_PAD_WIDTH_MM,
    FIBER_DISPLAY_DIA_MM,
    FIBER_DISPLAY_LENGTH_MM,
    LMR_THICKNESS_MM,
    LMR_WALL_MM,
    MOUNT_KEY_BY_STYLE,
    ORIGIN_INPUT_FACE,
    ORIGIN_OUTPUT_FACE,
    PH_PLATE_MM,
    PLACEHOLDER_CUBE,
    POST_BASE_KEY,
    POST_DISPLAY_DIA_MM,
    POST_STEM_KEY,
    MeshPlacement,
    fit_mesh_to_housing,
    mesh_extents,
    mesh_key_for_kind,
    mesh_url,
    stem_mesh_placement,
    visual_housing,
    stem_clearance_mm,
    stem_draw_height_mm,
)
from .coordinates import AXIS_HEIGHT_MM, FRAME_RENDER, beam_direction_teaching, teaching_orientation_to_render_quaternion, transform_from_reference
from .gizmo import GizmoSession, RotateSession, begin_gizmo_session, begin_rotate_session
from .model import MIRROR_RUNTIME_FOLD_DEG, Pose, SceneSnapshot, SceneStore, TEACHING_KIND_MIME


KIND_HEX = {
    "laser": "#dc2626",
    "lens": "#2563eb",
    "cylindrical_lens": "#1d4ed8",
    "fiber": "#0f766e",
    "ccd": "#7c3aed",
    "mirror": "#d97706",
    "isolator": "#047857",
    "waveplate": "#a855f7",
    "beam_expander": "#0284c7",
    "aperture": "#334155",
    "pbs": "#0ea5e9",
    "splitter": "#67e8f9",
    "beam_sampler": "#22d3ee",
    "grating": "#c026d3",
    "power_meter": "#e11d48",
    "wavefront_sensor": "#7c3aed",
    "oscilloscope": "#64748b",
}

ASSET_DIR = ASSET_DIR  # re-export for tests
QML_PATH = Path(__file__).resolve().parent / "qml" / "bench_view3d.qml"
CYLINDER_UNIT_MM = 100.0
# The 3D lesson view needs the envelope, not every sampled pupil ray.  Keeping
# a representative set prevents 3D cylinder draw calls dominating interaction.
MAX_DRAW_RAYS = 32
Quat = tuple[float, float, float, float]


def _quat_normalize(w: float, x: float, y: float, z: float) -> Quat:
    length = math.sqrt(w * w + x * x + y * y + z * z)
    if length < 1.0e-18:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / length, x / length, y / length, z / length)


def quaternion_align_plus_y(dx: float, dy: float, dz: float) -> Quat:
    """Unit quaternion rotating the Quick3D cylinder +Y axis onto ``(dx, dy, dz)``.

    Qt uses ``(scalar, x, y, z)``.  A zero-length direction returns identity.
    """
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1.0e-12:
        return (1.0, 0.0, 0.0, 0.0)
    dx, dy, dz = dx / length, dy / length, dz / length
    if dy > 0.999999:
        return (1.0, 0.0, 0.0, 0.0)
    if dy < -0.999999:
        return (0.0, 1.0, 0.0, 0.0)
    return _quat_normalize(1.0 + dy, dz, 0.0, -dx)


def rotate_vector_by_quaternion(quat: Quat, vector: tuple[float, float, float]) -> tuple[float, float, float]:
    w, x, y, z = quat
    vx, vy, vz = vector
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def cylinder_quaternion_from_segment(
    x1: float, y1: float, z1: float, x2: float, y2: float, z2: float
) -> Quat:
    return quaternion_align_plus_y(x2 - x1, y2 - y1, z2 - z1)


def mesh_source_for_asset(asset_key: str) -> str:
    return mesh_url(asset_key)


@lru_cache(maxsize=1)
def matte_board_texture_url() -> str:
    """Dull anodized MB1218/M plate, M6 on 25 mm centres.  The artist glb is too metallic."""
    path = Path(tempfile.gettempdir()) / "optical_ml_matte_board_v2.png"
    width = int(BREADBOARD_LENGTH_MM) * 2
    height = int(BREADBOARD_WIDTH_MM) * 2
    sx = width / BREADBOARD_LENGTH_MM
    sy = height / BREADBOARD_WIDTH_MM
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#D5DAE0"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#9AA4AF"), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(1, 1, width - 3, height - 3)
    r_csink = 3.6 * sx
    r_hole = 2.6 * sx
    nx = int(BREADBOARD_LENGTH_MM / BREADBOARD_HOLE_PITCH_MM)
    ny = int(BREADBOARD_WIDTH_MM / BREADBOARD_HOLE_PITCH_MM)
    painter.setPen(Qt.PenStyle.NoPen)
    for ix in range(nx):
        cx = (0.5 * BREADBOARD_HOLE_PITCH_MM + ix * BREADBOARD_HOLE_PITCH_MM) * sx
        for iy in range(ny):
            cy = (0.5 * BREADBOARD_HOLE_PITCH_MM + iy * BREADBOARD_HOLE_PITCH_MM) * sy
            painter.setBrush(QColor("#8B96A2"))
            painter.drawEllipse(QPointF(cx, cy), r_csink, r_csink * (sy / sx))
            painter.setBrush(QColor("#59636E"))
            painter.drawEllipse(QPointF(cx, cy), r_hole, r_hole * (sy / sx))
    painter.end()
    image.save(str(path), "PNG")
    return QUrl.fromLocalFile(str(path.resolve())).toString(QUrl.ComponentFormattingOption.FullyEncoded)


def _identity_placement() -> MeshPlacement:
    return MeshPlacement((1.0, 1.0, 1.0), (0.0, 0.0, 0.0))


def fiber_stage_placement(item) -> tuple[str, MeshPlacement]:
    """The shipped fiber_stage.glb is a 40 mm tower.  Do not draw it on the bench."""
    return "", _identity_placement()


_RING_KINDS = frozenset({"lens", "cylindrical_lens", "waveplate", "aperture", "isolator", "beam_expander"})
_KM_KINDS = frozenset({"mirror", "splitter", "beam_sampler", "grating", "pbs"})
_PLATE_KINDS = frozenset({"ccd", "power_meter", "wavefront_sensor"})


def _hardware_mount(kind: str, housing) -> dict[str, Any]:
    """Thorlabs-class post base + optic mount.  Catalog glbs stay housings only."""

    cube = CYLINDER_UNIT_MM
    empty = {
        "mountStyle": "none",
        "hasPostBase": False,
        "baseSx": 0.01,
        "baseSy": 0.01,
        "baseSz": 0.01,
        "baseH": 0.0,
        "holderS": 0.01,
        "holderH": 0.0,
        "cheekSx": 0.01,
        "cheekSy": 0.01,
        "cheekSz": 0.01,
        "cheekY": 0.0,
        "saddleSx": 0.01,
        "saddleSy": 0.01,
        "saddleSz": 0.01,
        "saddleZ": 0.0,
        "kmSx": 0.01,
        "kmSy": 0.01,
        "kmSz": 0.01,
        "kmX": 0.0,
        "knobS": 0.01,
        "knobLen": 0.01,
        "knobY": 0.0,
        "knobZ": 0.0,
        "clampSx": 0.01,
        "clampSy": 0.01,
        "clampSz": 0.01,
        "clampX": 0.0,
        "clampZ": 0.0,
        "plateSx": 0.01,
        "plateSy": 0.01,
        "plateSz": 0.01,
        "plateZ": 0.0,
        "knobX": 0.0,
        "ringBackSx": 0.01,
        "ringBackSy": 0.01,
        "ringBackSz": 0.01,
        "ringBackX": 0.0,
        "jawSy": 0.01,
        "jawSz": 0.01,
        "jawY": 0.0,
        "screwS": 0.01,
        "screwLen": 0.01,
        "hasMountMesh": False,
        "mountMeshSource": "",
        "mountSx": 1.0,
        "mountSy": 1.0,
        "mountSz": 1.0,
        "mountOx": 0.0,
        "mountOy": 0.0,
        "mountOz": 0.0,
        "hasBaseMesh": False,
        "baseMeshSource": "",
        "baseMeshSx": 1.0,
        "baseMeshSy": 1.0,
        "baseMeshSz": 1.0,
        "baseMeshOx": 0.0,
        "baseMeshOy": 0.0,
        "baseMeshOz": 0.0,
    }
    if kind == "oscilloscope":
        return empty
    aperture = max(float(housing.aperture_mm), 6.0)
    length = max(float(housing.length_mm), 1.0)
    if kind in _RING_KINDS:
        style = "ring"
    elif kind in _KM_KINDS:
        style = "km"
    elif kind == "laser":
        style = "clamp"
    elif kind in _PLATE_KINDS:
        style = "plate"
    else:
        style = "none"
    od = aperture + (2.4 if style == "ring" else 6.0)
    barrel = max(length + 0.8, 3.2) if style == "ring" else max(length + 2.5, 8.0)
    cheek_t = 1.6
    back_t = 8.0
    if housing.origin == ORIGIN_OUTPUT_FACE:
        km_x = -(length + 0.5 * back_t + 0.4)
        clamp_x = -0.55 * length
    elif housing.origin == ORIGIN_INPUT_FACE:
        km_x = length + 0.5 * back_t + 0.4
        clamp_x = 0.45 * length
    else:
        km_x = -(0.5 * length + 0.5 * back_t + 0.4)
        clamp_x = 0.0
    payload = {
        **empty,
        "mountStyle": style,
        "hasPostBase": True,
        "baseSx": 20.0 / cube,
        "baseSy": 5.0 / cube,
        "baseSz": 20.0 / cube,
        "baseH": 5.0,
        "holderS": 16.0 / cube,
        "holderH": 10.0,
        "cheekSx": barrel / cube,
        "cheekSy": cheek_t / cube,
        "cheekSz": (0.42 * aperture) / cube,
        "cheekY": 0.5 * aperture + 0.5 * cheek_t + 0.2,
        "saddleSx": barrel / cube,
        "saddleSy": (0.45 * aperture) / cube,
        "saddleSz": 2.4 / cube,
        "saddleZ": -(0.5 * aperture + 1.3),
        "kmSx": back_t / cube,
        "kmSy": od / cube,
        "kmSz": od / cube,
        "kmX": km_x,
        "knobS": 4.2 / cube,
        "knobLen": 11.0 / cube,
        "knobY": od * 0.28,
        "knobZ": od * 0.28,
        "clampSx": min(length * 0.45, 16.0) / cube,
        "clampSy": (aperture + 2.0) / cube,
        "clampSz": 4.0 / cube,
        "clampX": clamp_x,
        "clampZ": -(0.5 * aperture + 2.2),
        "plateSx": max(length, 12.0) / cube,
        "plateSy": (aperture + 4.0) / cube,
        "plateSz": 5.0 / cube,
        "plateZ": -(0.5 * aperture + 2.6),
        "knobX": km_x - (6.2 if km_x <= 0.0 else -6.2),
        "ringBackSx": 0.01,
        "ringBackSy": 0.01,
        "ringBackSz": 0.01,
        "ringBackX": 0.0,
        "jawSy": 3.0 / cube,
        "jawSz": (0.72 * aperture) / cube,
        "jawY": 0.5 * aperture + 1.6,
        "screwS": 2.8 / cube,
        "screwLen": 8.0 / cube,
        "origin": housing.origin,
    }
    if kind != "oscilloscope":
        base_url = mesh_url(POST_BASE_KEY)
        base_ext = mesh_extents(POST_BASE_KEY) if base_url else None
        if base_ext is not None:
            payload["hasBaseMesh"] = True
            payload["baseMeshSource"] = base_url
            plate = max(base_ext.size_mm[0], base_ext.size_mm[1], 0.2)
            sxy = PH_PLATE_MM / plate
            payload["baseMeshSx"] = sxy
            payload["baseMeshSy"] = sxy
            payload["baseMeshSz"] = 0.8
            payload["baseMeshOx"] = -0.5 * (base_ext.min_xyz[0] + base_ext.max_xyz[0]) * sxy
            payload["baseMeshOy"] = -0.5 * (base_ext.min_xyz[1] + base_ext.max_xyz[1]) * sxy
            payload["baseMeshOz"] = -base_ext.min_xyz[2] * 0.8
    mount_key = MOUNT_KEY_BY_STYLE.get(style)
    if mount_key:
        mount_url = mesh_url(mount_key)
        mount_ext = mesh_extents(mount_key) if mount_url else None
        if mount_ext is not None:
            payload["hasMountMesh"] = True
            payload["mountMeshSource"] = mount_url
            size = mount_ext.size_mm
            if style == "ring":
                target_od = max(aperture, 6.0) + 2.0 * LMR_WALL_MM
                payload["mountSx"] = LMR_THICKNESS_MM / max(size[0], 0.2)
                payload["mountSy"] = target_od / max(size[1], size[2], 0.2)
                payload["mountSz"] = payload["mountSy"]
            elif style == "km":
                scale = (aperture + 8.3) / max(size[1], size[2], 0.2)
                payload["mountSy"] = scale
                payload["mountSz"] = scale
                payload["mountOx"] = -length - mount_ext.max_xyz[0]
            elif style == "clamp":
                payload["mountSx"] = 0.88
                payload["mountSy"] = 0.72
                payload["mountSz"] = 0.72
            elif style == "plate":
                payload["mountSx"] = max(length, 12.0) / max(size[0], 0.2)
                payload["mountSy"] = (aperture + 4.0) / max(size[1], 0.2)
                payload["mountSz"] = 6.0 / max(size[2], 0.2)
                payload["mountOz"] = -(0.5 * aperture + 2.6) - mount_ext.max_xyz[2] * float(payload["mountSz"])
    return payload


def stem_mesh_source() -> str:
    return mesh_url(POST_STEM_KEY)


def _placeholder_geometry(item) -> dict[str, Any]:
    target = visual_housing(item.kind, item.params)
    if target.placeholder == PLACEHOLDER_CUBE:
        return {
            "shape": "cube",
            "sx": target.height_mm / CYLINDER_UNIT_MM,
            "sy": target.length_mm / CYLINDER_UNIT_MM,
            "sz": target.width_mm / CYLINDER_UNIT_MM,
        }
    aperture = target.aperture_mm
    return {
        "shape": "cylinder",
        "sx": aperture / CYLINDER_UNIT_MM,
        "sy": target.length_mm / CYLINDER_UNIT_MM,
        "sz": aperture / CYLINDER_UNIT_MM,
    }


def _placeholder_offset(item) -> tuple[float, float, float]:
    """Placeholder cylinders use +Y as the beam; offset keeps the optical port on Pose."""
    target = visual_housing(item.kind, item.params)
    half = 0.5 * target.length_mm
    if target.origin == ORIGIN_OUTPUT_FACE:
        return (0.0, -half, 0.0)
    if target.origin == ORIGIN_INPUT_FACE:
        return (0.0, half, 0.0)
    return (0.0, 0.0, 0.0)


def body_axis_teaching(item) -> tuple[float, float, float]:
    yaw = item.pose.yaw_rad
    if item.kind == "mirror":
        yaw = yaw + math.radians(MIRROR_RUNTIME_FOLD_DEG)
    return beam_direction_teaching(yaw, item.pose.pitch_rad, item.pose.roll_rad)


def body_mesh_placement(item, *, body_mesh: str) -> MeshPlacement:
    """Fit a glb AABB to the catalog housing.  Identity if the file is missing."""
    identity = MeshPlacement((1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    if not body_mesh:
        return identity
    extents = mesh_extents(mesh_key_for_kind(item.kind, item.asset_key))
    if extents is None:
        return identity
    return fit_mesh_to_housing(extents, visual_housing(item.kind, item.params))


def body_mesh_scale(item, *, body_mesh: str) -> tuple[float, float, float]:
    return body_mesh_placement(item, body_mesh=body_mesh).scale


def body_render_quaternion(item, transform, *, body_mesh: str) -> Quat:
    """Placeholder cylinders keep +Y along the beam; glb meshes keep +X optical."""
    yaw = item.pose.yaw_rad
    if item.kind == "mirror":
        yaw = yaw + math.radians(MIRROR_RUNTIME_FOLD_DEG)
    if body_mesh:
        return teaching_orientation_to_render_quaternion(yaw, item.pose.pitch_rad, item.pose.roll_rad)
    axis_r = transform.teaching_direction_to_render(
        beam_direction_teaching(yaw, item.pose.pitch_rad, item.pose.roll_rad)
    )
    return quaternion_align_plus_y(*axis_r)


def snapshot_to_render_nodes(snapshot: SceneSnapshot) -> list[dict[str, Any]]:
    """Project teaching poses into the frozen view3d frame.

    Placeholders are Qt cylinders along local +Y, then aligned to the beam.
    glb bodies use teaching +X as the optical axis and +Z as up, fitted to
    catalog housings.  Stems are Ø12.7 mm from the housing underside to the
    breadboard; they do not pierce the optic or the table.
    """
    transform = transform_from_reference(snapshot.reference)
    selected = snapshot.selected_component_id
    nodes: list[dict[str, Any]] = []
    for item in snapshot.components:
        x_r, y_r, z_r = transform.teaching_to_render((item.pose.x_mm, item.pose.y_mm, item.pose.z_mm))
        geometry = _placeholder_geometry(item)
        housing = visual_housing(item.kind, item.params)
        if item.kind == "oscilloscope":
            stem_drop = 0.0
            stem = 0.0
        else:
            stem_drop = stem_clearance_mm(item.kind, item.params) * float(transform.render_units_per_mm)
            stem = stem_draw_height_mm(float(item.pose.z_mm), item.kind, item.params) * float(transform.render_units_per_mm)
        selected_scale = 1.0
        body_mesh = mesh_source_for_asset(mesh_key_for_kind(item.kind, item.asset_key))
        stem_mesh = "" if item.kind == "oscilloscope" else stem_mesh_source()
        qw, qx, qy, qz = body_render_quaternion(item, transform, body_mesh=body_mesh)
        fallback_sx = geometry["sx"] * selected_scale
        fallback_sy = geometry["sy"] * selected_scale
        fallback_sz = geometry["sz"] * selected_scale
        placement = body_mesh_placement(item, body_mesh=body_mesh)
        mesh_sx, mesh_sy, mesh_sz = placement.scale
        mesh_ox, mesh_oy, mesh_oz = placement.offset_mm
        fallback_ox, fallback_oy, fallback_oz = _placeholder_offset(item)
        if item.kind == "fiber":
            along = FIBER_DISPLAY_LENGTH_MM / max(housing.length_mm, 0.2)
            across = FIBER_DISPLAY_DIA_MM / max(housing.aperture_mm, 0.2)
            mesh_sx *= along
            mesh_sy *= across
            mesh_sz *= across
            mesh_ox *= along
            mesh_oy *= across
            mesh_oz *= across
            fallback_sx *= across
            fallback_sy *= along
            fallback_sz *= across
            fallback_ox *= across
            fallback_oy *= along
            fallback_oz *= across
        stem_placement = stem_mesh_placement(
            stem, mesh_extents(POST_STEM_KEY) if stem_mesh else None, POST_DISPLAY_DIA_MM
        )
        stage_mesh, stage_placement = fiber_stage_placement(item)
        nodes.append(
            {
                "id": item.component_id,
                "kind": item.kind,
                "label": item.label,
                "x": float(x_r),
                "y": float(y_r),
                "z": float(z_r),
                "stemHeight": stem,
                "stemDrop": stem_drop,
                "qw": qw,
                "qx": qx,
                "qy": qy,
                "qz": qz,
                "sx": mesh_sx if body_mesh else fallback_sx,
                "sy": mesh_sy if body_mesh else fallback_sy,
                "sz": mesh_sz if body_mesh else fallback_sz,
                "meshOx": mesh_ox,
                "meshOy": mesh_oy,
                "meshOz": mesh_oz,
                "fallbackSx": fallback_sx,
                "fallbackSy": fallback_sy,
                "fallbackSz": fallback_sz,
                "fallbackOx": fallback_ox,
                "fallbackOy": fallback_oy,
                "fallbackOz": fallback_oz,
                "shape": geometry["shape"],
                "diameterMm": FIBER_DISPLAY_DIA_MM if item.kind == "fiber" else housing.aperture_mm,
                "meshSource": body_mesh,
                "stemMeshSource": stem_mesh,
                "stemSx": stem_placement.scale[0],
                "stemSy": stem_placement.scale[1],
                "stemSz": stem_placement.scale[2],
                "stemOx": stem_placement.offset_mm[0],
                "stemOy": stem_placement.offset_mm[1],
                "stemOz": stem_placement.offset_mm[2],
                "stemPlaceholderS": POST_DISPLAY_DIA_MM / CYLINDER_UNIT_MM,
                "pickS": (max(housing.aperture_mm if item.kind != "fiber" else FIBER_DISPLAY_DIA_MM, 8.0) + 5.0)
                / CYLINDER_UNIT_MM,
                "hasBodyMesh": bool(body_mesh),
                "hasStemMesh": bool(stem_mesh),
                "stageMeshSource": stage_mesh,
                "hasStageMesh": bool(stage_mesh),
                "stageSx": stage_placement.scale[0],
                "stageSy": stage_placement.scale[1],
                "stageSz": stage_placement.scale[2],
                "stageOx": stage_placement.offset_mm[0],
                "stageOy": stage_placement.offset_mm[1],
                "stageOz": stage_placement.offset_mm[2],
                "hasMountPad": item.kind == "fiber",
                "padHeight": FIBER_MOUNT_PAD_HEIGHT_MM if item.kind == "fiber" else 0.0,
                "padSx": FIBER_MOUNT_PAD_LENGTH_MM / CYLINDER_UNIT_MM,
                "padSy": FIBER_MOUNT_PAD_HEIGHT_MM / CYLINDER_UNIT_MM,
                "padSz": FIBER_MOUNT_PAD_WIDTH_MM / CYLINDER_UNIT_MM,
                "selected": item.component_id == selected,
                "color": KIND_HEX.get(item.kind, "#64748b"),
                "frame": FRAME_RENDER,
                **_hardware_mount(item.kind, housing),
            }
        )
    return nodes


def snapshot_view3d_guides(snapshot: SceneSnapshot) -> dict[str, float]:
    transform = transform_from_reference(snapshot.reference)
    units = float(transform.render_units_per_mm)
    axis = float(snapshot.reference.axis_height_mm) * units
    xs = [float(item.pose.x_mm) for item in snapshot.components] or [0.0, 80.0]
    board = visual_housing(BREADBOARD_KEY)
    board_mesh = mesh_url(BREADBOARD_KEY)
    board_extents = mesh_extents(BREADBOARD_KEY) if board_mesh else None
    board_place = (
        fit_mesh_to_housing(board_extents, board) if board_extents is not None else _identity_placement()
    )
    board_x, board_y, board_z = transform.teaching_to_render((0.5 * board.length_mm, 0.0, 0.0))
    qw, qx, qy, qz = teaching_orientation_to_render_quaternion(0.0, 0.0, 0.0)
    return {
        "axisHeight": axis,
        "tableLength": board.length_mm * units,
        "tableWidth": board.width_mm * units,
        "tableThickness": board.height_mm * units,
        "beamStartX": min(xs) * units,
        "beamEndX": max(xs) * units,
        "boardMeshSource": board_mesh,
        "hasBoardMesh": bool(board_mesh),
        "boardX": float(board_x),
        "boardY": float(board_y),
        "boardZ": float(board_z),
        "boardQw": float(qw),
        "boardQx": float(qx),
        "boardQy": float(qy),
        "boardQz": float(qz),
        "boardSx": float(board_place.scale[0]),
        "boardSy": float(board_place.scale[1]),
        "boardSz": float(board_place.scale[2]),
        "boardOx": float(board_place.offset_mm[0]),
        "boardOy": float(board_place.offset_mm[1]),
        "boardOz": float(board_place.offset_mm[2]),
        "boardAlbedo": matte_board_texture_url(),
    }


def teaching_rays_to_render(rays: list[dict[str, Any]] | tuple, snapshot: SceneSnapshot) -> list[dict[str, Any]]:
    transform = transform_from_reference(snapshot.reference)
    laser = next((item for item in snapshot.components if item.kind == "laser"), None)
    radius = 0.72
    if laser is not None:
        try:
            radius = max(0.35, float((laser.params or {}).get("beam_radius_mm") or 0.72))
        except (TypeError, ValueError):
            radius = 0.72
    rendered: list[dict[str, Any]] = []
    for index, ray in enumerate(list(rays or [])[:MAX_DRAW_RAYS]):
        start = list(ray.get("start") or ())
        end = list(ray.get("end") or ())
        if len(start) < 3 or len(end) < 3:
            continue
        x1, y1, z1 = transform.teaching_to_render((float(start[0]), float(start[1]), float(start[2])))
        x2, y2, z2 = transform.teaching_to_render((float(end[0]), float(end[1]), float(end[2])))
        qw, qx, qy, qz = cylinder_quaternion_from_segment(x1, y1, z1, x2, y2, z2)
        rendered.append(
            {
                "id": f"ray-{index}",
                "x1": x1,
                "y1": y1,
                "z1": z1,
                "x2": x2,
                "y2": y2,
                "z2": z2,
                "qw": qw,
                "qx": qx,
                "qy": qy,
                "qz": qz,
                "radius": radius,
                "power": float(ray.get("power_fraction", 1.0)),
                "frame": FRAME_RENDER,
            }
        )
    return rendered


class View3DBridge(QObject):
    sceneChanged = Signal()
    selectRequested = Signal(str)
    poseDragged = Signal(str, float, float, float)
    orientationDragged = Signal(str, float, float, float)
    kindDropped = Signal(str, float, float, float)
    resetCameraRequested = Signal()
    topViewRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nodes: list[dict[str, Any]] = []
        self._rays: list[dict[str, Any]] = []
        self._axis_height = AXIS_HEIGHT_MM
        self._table_length = 450.0
        self._table_width = 300.0
        self._table_thickness = 12.7
        self._beam_start_x = 0.0
        self._beam_end_x = 72.0
        self._gizmo = (0.0, AXIS_HEIGHT_MM, 0.0)
        self._gizmo_visible = False
        self._selected_id = ""
        self._selected_label = ""
        self._render_revision: int | None = None
        self._session: GizmoSession | None = None
        self._rotate: RotateSession | None = None
        self._transform = transform_from_reference({"axis_height_mm": AXIS_HEIGHT_MM})
        self._origin_teaching = (0.0, 0.0, AXIS_HEIGHT_MM)
        self._origin_angles = (0.0, 0.0, 0.0)
        self._board: dict[str, Any] = {
            "boardMeshSource": "",
            "hasBoardMesh": False,
            "boardX": 225.0,
            "boardY": 0.0,
            "boardZ": 0.0,
            "boardQw": 1.0,
            "boardQx": 0.0,
            "boardQy": 0.0,
            "boardQz": 0.0,
            "boardSx": 1.0,
            "boardSy": 1.0,
            "boardSz": 1.0,
            "boardOx": 0.0,
            "boardOy": 0.0,
            "boardOz": 0.0,
            "boardAlbedo": matte_board_texture_url(),
        }

    def set_snapshot(self, snapshot: SceneSnapshot) -> None:
        # Selection changes do not alter geometry.  Avoid rebuilding the full
        # QML node payload (and its mesh-placement work) for that common path.
        if self._render_revision != int(snapshot.revision):
            self._transform = transform_from_reference(snapshot.reference)
            self._nodes = snapshot_to_render_nodes(snapshot)
            guides = snapshot_view3d_guides(snapshot)
            self._axis_height = float(guides["axisHeight"])
            self._table_length = float(guides["tableLength"])
            self._table_width = float(guides["tableWidth"])
            self._table_thickness = float(guides["tableThickness"])
            self._beam_start_x = float(guides["beamStartX"])
            self._beam_end_x = float(guides["beamEndX"])
            for key in self._board:
                if key in guides:
                    self._board[key] = guides[key]
            self._render_revision = int(snapshot.revision)
        selected = snapshot.selected_component_id or ""
        self._selected_id = selected
        component = next((item for item in snapshot.components if item.component_id == selected), None)
        if component is None:
            self._gizmo_visible = False
            self._gizmo = (0.0, self._axis_height, 0.0)
            self._origin_teaching = (0.0, 0.0, AXIS_HEIGHT_MM)
            self._origin_angles = (0.0, 0.0, 0.0)
            self._selected_label = ""
        else:
            self._gizmo_visible = True
            self._origin_teaching = (component.pose.x_mm, component.pose.y_mm, component.pose.z_mm)
            self._origin_angles = (component.pose.yaw_rad, component.pose.pitch_rad, component.pose.roll_rad)
            self._gizmo = self._transform.teaching_to_render(self._origin_teaching)
            self._selected_label = str(component.label or "")
        self.sceneChanged.emit()

    def set_rays(self, rays: list[dict[str, Any]], snapshot: SceneSnapshot) -> None:
        self._rays = teaching_rays_to_render(rays, snapshot)
        self.sceneChanged.emit()

    @Property("QVariantList", notify=sceneChanged)
    def nodes(self) -> list[dict[str, Any]]:
        return list(self._nodes)

    @Property(str, notify=sceneChanged)
    def selectedId(self) -> str:  # noqa: N802 - exposed to QML
        return self._selected_id

    @Property("QVariantList", notify=sceneChanged)
    def rays(self) -> list[dict[str, Any]]:
        return list(self._rays)

    @Property(float, notify=sceneChanged)
    def axisHeight(self) -> float:
        return float(self._axis_height)

    @Property(float, notify=sceneChanged)
    def tableLength(self) -> float:
        return float(self._table_length)

    @Property(float, notify=sceneChanged)
    def tableWidth(self) -> float:
        return float(self._table_width)

    @Property(float, notify=sceneChanged)
    def tableThickness(self) -> float:
        return float(self._table_thickness)

    @Property(str, notify=sceneChanged)
    def boardMeshSource(self) -> str:
        return str(self._board.get("boardMeshSource") or "")

    @Property(bool, notify=sceneChanged)
    def hasBoardMesh(self) -> bool:
        return bool(self._board.get("hasBoardMesh"))

    @Property(float, notify=sceneChanged)
    def boardX(self) -> float:
        return float(self._board.get("boardX") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardY(self) -> float:
        return float(self._board.get("boardY") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardZ(self) -> float:
        return float(self._board.get("boardZ") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardQw(self) -> float:
        return float(self._board.get("boardQw") or 1.0)

    @Property(float, notify=sceneChanged)
    def boardQx(self) -> float:
        return float(self._board.get("boardQx") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardQy(self) -> float:
        return float(self._board.get("boardQy") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardQz(self) -> float:
        return float(self._board.get("boardQz") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardSx(self) -> float:
        return float(self._board.get("boardSx") or 1.0)

    @Property(float, notify=sceneChanged)
    def boardSy(self) -> float:
        return float(self._board.get("boardSy") or 1.0)

    @Property(float, notify=sceneChanged)
    def boardSz(self) -> float:
        return float(self._board.get("boardSz") or 1.0)

    @Property(float, notify=sceneChanged)
    def boardOx(self) -> float:
        return float(self._board.get("boardOx") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardOy(self) -> float:
        return float(self._board.get("boardOy") or 0.0)

    @Property(float, notify=sceneChanged)
    def boardOz(self) -> float:
        return float(self._board.get("boardOz") or 0.0)

    @Property(str, notify=sceneChanged)
    def boardAlbedo(self) -> str:
        return str(self._board.get("boardAlbedo") or matte_board_texture_url())

    @Property(float, notify=sceneChanged)
    def beamStartX(self) -> float:
        return float(self._beam_start_x)

    @Property(float, notify=sceneChanged)
    def beamEndX(self) -> float:
        return float(self._beam_end_x)

    @Property(bool, notify=sceneChanged)
    def gizmoVisible(self) -> bool:
        return bool(self._gizmo_visible)

    @Property(float, notify=sceneChanged)
    def gizmoX(self) -> float:
        return float(self._gizmo[0])

    @Property(float, notify=sceneChanged)
    def gizmoY(self) -> float:
        return float(self._gizmo[1])

    @Property(float, notify=sceneChanged)
    def gizmoZ(self) -> float:
        return float(self._gizmo[2])

    @Property(str, notify=sceneChanged)
    def selectedId(self) -> str:
        return str(self._selected_id)

    @Property(str, notify=sceneChanged)
    def selectedLabel(self) -> str:
        return str(self._selected_label)

    @Property(str, notify=sceneChanged)
    def selectedPosition(self) -> str:
        """Selected component's bench coordinates (mm), shown in the name tag."""
        if not self._selected_id:
            return ""
        x_mm, y_mm, z_mm = self._origin_teaching
        return f"X {x_mm:.1f} · Y {y_mm:.1f} · Z {z_mm:.1f} mm"

    @Property(bool, constant=True)
    def readOnly(self) -> bool:
        return False

    @Slot(str)
    def selectComponent(self, component_id: str) -> None:
        cid = str(component_id or "")
        if cid.startswith("node:"):
            cid = cid[5:]
        if not cid or cid.startswith(("gizmo:", "ray:", "stem:")) or cid == "table":
            return
        self._selected_id = cid
        self.selectRequested.emit(cid)

    @Slot(str, str, float, float, float, float, float, float)
    def beginGizmoDrag(self, mode: str, name: str, ox: float, oy: float, oz: float, dx: float, dy: float, dz: float) -> None:
        if not self._selected_id:
            return
        ray_o = (ox, oy, oz)
        ray_d = (dx, dy, dz)
        if str(mode) == "rotate":
            self._session = None
            self._rotate = begin_rotate_session(
                self._selected_id,
                name,
                self._origin_teaching,
                self._origin_angles,
                ray_o,
                ray_d,
                self._transform,
            )
            return
        self._rotate = None
        self._session = begin_gizmo_session(
            self._selected_id,
            mode,
            name,
            self._origin_teaching,
            ray_o,
            ray_d,
            self._transform,
        )

    @Slot(float, float, float, float, float, float)
    def updateGizmoDrag(self, ox: float, oy: float, oz: float, dx: float, dy: float, dz: float) -> None:
        if self._rotate is not None:
            angles = self._rotate.apply((ox, oy, oz), (dx, dy, dz))
            if angles is None:
                return
            self.orientationDragged.emit(self._rotate.component_id, angles[0], angles[1], angles[2])
            return
        if self._session is None:
            return
        pose = self._session.apply((ox, oy, oz), (dx, dy, dz))
        if pose is None:
            return
        self.poseDragged.emit(self._session.component_id, pose[0], pose[1], pose[2])

    @Slot()
    def endGizmoDrag(self) -> None:
        self._session = None
        self._rotate = None

    @Slot(str, float, float, float)
    def dropKindAt(self, kind: str, x_r: float, y_r: float, z_r: float) -> None:
        x_mm, y_mm, _z_mm = self._transform.render_to_teaching((x_r, y_r, z_r))
        x_mm = min(max(float(x_mm), 0.0), float(self._table_length))
        y_mm = min(max(float(y_mm), -0.5 * float(self._table_width)), 0.5 * float(self._table_width))
        self.kindDropped.emit(str(kind), x_mm, y_mm, float(self._axis_height))


class BenchView3D(QWidget):
    """Orbit camera plus teaching-axis translate gizmo."""

    selected = Signal(str)

    def __init__(self, store: SceneStore, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingV2View3D")
        self.setAcceptDrops(True)
        self.store = store
        self.bridge = View3DBridge(self)
        self._quick = None
        self._ready = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._fallback = QLabel("正在启动 3D 视口…")
        self._fallback.setObjectName("teachingV2View3DFallback")
        self._fallback.setStyleSheet(
            "QLabel { background: #f4f7fa; color: #475569; border: 1px solid #d8e1eb; border-radius: 8px; padding: 12px; }"
        )
        layout.addWidget(self._fallback)
        self.bridge.selectRequested.connect(self._on_select)
        self.bridge.poseDragged.connect(self._on_pose_dragged)
        self.bridge.orientationDragged.connect(self._on_orientation_dragged)
        self.store.sceneChanged.connect(self._on_scene)
        self.store.selectionChanged.connect(self._on_selection)
        self._pending_snapshot: SceneSnapshot | None = None
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setSingleShot(True)
        self._snapshot_timer.setInterval(33)
        self._snapshot_timer.timeout.connect(self._flush_snapshot)
        self.bridge.set_snapshot(store.snapshot())
        self._try_start_quick3d(layout)
        self.setMinimumHeight(220)

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasFormat(TEACHING_KIND_MIME) or bool(mime.text()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasFormat(TEACHING_KIND_MIME):
            kind = bytes(mime.data(TEACHING_KIND_MIME)).decode("utf-8")
        else:
            kind = str(mime.text() or "")
        if not kind:
            event.ignore()
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        root = getattr(self._quick, "rootObject", lambda: None)()
        if root is not None and hasattr(root, "placeDroppedKind"):
            root.placeDroppedKind(kind, float(pos.x()), float(pos.y()))
        else:
            self.bridge.kindDropped.emit(kind, self.bridge.beamEndX + 12.0, 0.0, float(self.bridge.axisHeight))
        event.acceptProposedAction()

    def render_nodes(self) -> list[dict[str, Any]]:
        return list(self.bridge.nodes)

    def render_rays(self) -> list[dict[str, Any]]:
        return list(self.bridge.rays)

    def is_quick3d_ready(self) -> bool:
        return bool(self._ready)

    def reset_camera(self) -> None:
        self.bridge.resetCameraRequested.emit()

    def look_top(self) -> None:
        self.bridge.topViewRequested.emit()

    def set_rays(self, rays: list[dict[str, Any]] | tuple, snapshot: SceneSnapshot | None = None) -> None:
        self.bridge.set_rays(list(rays or []), snapshot or self.store.snapshot())

    def _on_scene(self, snapshot: SceneSnapshot, _reason: str = "") -> None:
        self._queue_snapshot(snapshot)

    def _on_selection(self, _component_id: str | None) -> None:
        self._queue_snapshot(self.store.snapshot())

    def _queue_snapshot(self, snapshot: SceneSnapshot) -> None:
        self._pending_snapshot = snapshot
        if not self._snapshot_timer.isActive():
            self._snapshot_timer.start()

    def _flush_snapshot(self) -> None:
        snapshot = self._pending_snapshot
        self._pending_snapshot = None
        if snapshot is not None:
            self.bridge.set_snapshot(snapshot)

    def _on_select(self, component_id: str) -> None:
        self.store.select(component_id)
        self.selected.emit(component_id)

    def _on_pose_dragged(self, component_id: str, x_mm: float, y_mm: float, z_mm: float) -> None:
        component = self.store.components.get(component_id)
        if component is None:
            return
        pose = component.pose
        self.store.update_pose(
            component_id,
            Pose(x_mm, y_mm, z_mm, pose.yaw_rad, pose.pitch_rad, pose.roll_rad),
            reason=f"三维移动{component.label}",
        )

    def _on_orientation_dragged(self, component_id: str, yaw_rad: float, pitch_rad: float, roll_rad: float) -> None:
        component = self.store.components.get(component_id)
        if component is None:
            return
        pose = component.pose
        self.store.update_pose(
            component_id,
            Pose(pose.x_mm, pose.y_mm, pose.z_mm, yaw_rad, pitch_rad, roll_rad),
            reason=f"三维旋转{component.label}",
        )

    def _try_start_quick3d(self, layout: QVBoxLayout) -> None:
        try:
            from PySide6.QtQuickWidgets import QQuickWidget
        except Exception:
            self._fallback.setText("3D 视口需要 Qt Quick 3D。坐标桥已接通，当前环境无法显示。")
            return
        quick = QQuickWidget(self)
        quick.setObjectName("teachingV2View3DQuick")
        quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        quick.setClearColor(QColor("#F4F7FA"))
        quick.rootContext().setContextProperty("sceneBridge", self.bridge)
        quick.setSource(QUrl.fromLocalFile(str(QML_PATH)))
        errors = [error.toString() for error in quick.errors()]
        if quick.status() != QQuickWidget.Status.Ready or errors:
            detail = "；".join(errors[:3]) if errors else "Quick3D 未就绪"
            self._fallback.setText(f"3D 视口当前无法显示（{detail}）。坐标桥已接通。")
            quick.setParent(None)
            quick.deleteLater()
            return
        self._quick = quick
        self._ready = True
        self._fallback.hide()
        quick.setAcceptDrops(True)
        quick.installEventFilter(self)
        layout.addWidget(quick, 1)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._quick:
            etype = event.type()
            if etype == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
                return True
            if etype == QEvent.Type.DragMove:
                mime = event.mimeData()
                if mime.hasFormat(TEACHING_KIND_MIME) or bool(mime.text()):
                    event.acceptProposedAction()
                    return True
            if etype == QEvent.Type.Drop:
                self.dropEvent(event)
                return True
        return super().eventFilter(watched, event)


__all__ = [
    "BenchView3D",
    "View3DBridge",
    "body_axis_teaching",
    "body_mesh_placement",
    "body_mesh_scale",
    "body_render_quaternion",
    "cylinder_quaternion_from_segment",
    "mesh_source_for_asset",
    "stem_mesh_source",
    "quaternion_align_plus_y",
    "rotate_vector_by_quaternion",
    "snapshot_to_render_nodes",
    "snapshot_view3d_guides",
    "teaching_rays_to_render",
]
