from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickWidgets import QQuickWidget


QUICK3D_ENABLED = os.environ.get("OPTICAL_TEACHING_3D_BACKEND", "painter").strip().lower() == "quick3d"
QML_PATH = Path(__file__).resolve().parents[2] / "resources" / "qml" / "TeachingQuick3D.qml"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def flatten_scene(model: Any, snapshot: Any | None = None) -> dict[str, Any]:
    """Convert the mutable teaching model into QML-safe plain data."""
    nodes: list[dict[str, Any]] = []
    for node in getattr(model, "nodes", {}).values():
        params = getattr(node, "params", {}) or {}
        nodes.append({
            "id": str(node.id),
            "kind": str(node.kind),
            "label": str(node.label),
            "x": _finite(node.x),
            "y": _finite(node.y),
            "z": _finite(params.get("z_mm", 82.0), 82.0),
            "yaw": _finite(node.rotation_deg),
            "pitch": _finite(params.get("pitch_deg", 0.0)),
            "roll": _finite(params.get("roll_deg", 0.0)),
            "enabled": bool(params.get("enabled", True)),
            "selected": str(getattr(model, "selected_node_id", "")) == str(node.id),
        })

    radii = getattr(snapshot, "current_radii", {}) if snapshot is not None else {}
    segments: list[dict[str, Any]] = []
    beam_segments = getattr(model, "beam_segments", lambda: ())()
    for index, info in enumerate(beam_segments):
        values = (
            info.start_x, info.start_y, info.start_z_mm,
            info.end_x, info.end_y, info.end_z_mm,
        )
        if not all(math.isfinite(_finite(value, math.nan)) for value in values):
            continue
        source_id = str(info.source_id or "")
        target_id = str(info.target_id or "")
        segments.append({
            "id": str(info.edge_id or f"segment-{index}"),
            "startX": _finite(info.start_x),
            "startY": _finite(info.start_y),
            "startZ": _finite(info.start_z_mm, 82.0),
            "endX": _finite(info.end_x),
            "endY": _finite(info.end_y),
            "endZ": _finite(info.end_z_mm, 82.0),
            "power": max(0.0, min(1.0, _finite(info.power_fraction, 1.0))),
            "chief": bool(info.is_chief_ray),
            "selectable": bool(info.edge_id in getattr(model, "edges", {}) and source_id != target_id),
            "sourceRadius": max(1.0, _finite(radii.get(source_id, 8.0), 8.0)),
            "targetRadius": max(1.0, _finite(radii.get(target_id, 8.0), 8.0)),
        })

    status = getattr(model, "engine_trace_status", lambda: {})()
    return {
        "revision": int(getattr(model, "revision", 0)),
        "generation": int(status.get("applied_generation", -1)),
        "nodes": nodes,
        "segments": segments,
    }


class TeachingQuick3DBridge(QObject):
    sceneChanged = Signal()
    nodeActivated = Signal(str)
    nodeChanged = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._scene: dict[str, Any] = {"revision": 0, "generation": -1, "nodes": [], "segments": []}
        self._model: Any | None = None
        self._snapshot: Any | None = None

    @Property("QVariant", notify=sceneChanged)
    def scene(self) -> dict[str, Any]:
        return self._scene

    @Slot(object)
    def set_scene(self, scene: dict[str, Any]) -> None:
        self._scene = scene if isinstance(scene, dict) else {"revision": 0, "generation": -1, "nodes": [], "segments": []}
        self.sceneChanged.emit()

    def _publish_model(self) -> None:
        if self._model is not None:
            self.set_scene(flatten_scene(self._model, self._snapshot))

    @Slot(str, float, float, float)
    def move_node_3d_live(self, node_id: str, x: float, y: float, z_mm: float) -> None:
        model = self._model
        if model is None or str(node_id) not in getattr(model, "nodes", {}):
            return
        model.move_node_3d(str(node_id), float(x), float(y), float(z_mm), record=False)

    @Slot(str, float, float, float)
    def set_orientation_live(self, node_id: str, yaw: float, pitch: float, roll: float) -> None:
        model = self._model
        if model is None or str(node_id) not in getattr(model, "nodes", {}):
            return
        model.set_orientation(
            str(node_id), yaw_deg=float(yaw), pitch_deg=float(pitch),
            roll_deg=float(roll), record=False,
        )

    @Slot(str, str)
    def commit_node_change(self, node_id: str, action: str) -> None:
        model = self._model
        if model is None or str(node_id) not in getattr(model, "nodes", {}):
            return
        self._publish_model()
        self.nodeChanged.emit(str(node_id), str(action))

    @Slot(str)
    def activate_node(self, node_id: str) -> None:
        self.nodeActivated.emit(str(node_id))

    @Slot(str, str)
    def change_node(self, node_id: str, change_kind: str) -> None:
        self.nodeChanged.emit(str(node_id), str(change_kind))


class TeachingQuick3DWidget(QQuickWidget):
    """Optional GPU view. It remains inert unless explicitly selected."""

    nodeActivated = Signal(str)
    nodeChanged = Signal(str, str)
    objectActivated = Signal(str)
    objectChanged = Signal(str, str)
    beamSegmentActivated = Signal(str, float, float)
    cameraChanged = Signal(float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.bridge = TeachingQuick3DBridge(self)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor("#101820")
        self.rootContext().setContextProperty("sceneBridge", self.bridge)
        self.bridge.nodeActivated.connect(self.nodeActivated)
        self.bridge.nodeActivated.connect(self.objectActivated)
        self.bridge.nodeChanged.connect(self.nodeChanged)
        self.bridge.nodeChanged.connect(self.objectChanged)
        self.setSource(QUrl.fromLocalFile(str(QML_PATH)))

    @property
    def load_ok(self) -> bool:
        return self.status() == QQuickWidget.Status.Ready

    def set_model(self, model: Any, snapshot: Any | None = None) -> None:
        self.bridge._model = model
        self.bridge._snapshot = snapshot
        self.bridge.set_scene(flatten_scene(model, snapshot))

    def set_display_layer(self, _layer: str) -> None:
        pass

    def set_rays_only(self, _enabled: bool) -> None:
        pass

    def set_layer_visible(self, _key: str, _visible: bool) -> None:
        pass

    def reset_camera(self) -> None:
        root = self.rootObject()
        if root is not None:
            root.setProperty("yaw", 4.0)
            root.setProperty("pitch", 12.0)
            root.setProperty("distance", 1750.0)
            root.setProperty("panX", 0.0)
            root.setProperty("panY", 0.0)

    def set_view_preset(self, preset: str) -> None:
        presets = {
            "isometric": (35.0, 28.0),
            "top": (0.0, 89.0),
            "front": (0.0, 0.0),
            "side": (90.0, 0.0),
            "main_axis": (0.0, 0.0),
            "branch": (90.0, 0.0),
            "paper": (4.0, 12.0),
        }
        yaw, pitch = presets.get(str(preset), presets["isometric"])
        root = self.rootObject()
        if root is not None:
            root.setProperty("yaw", yaw)
            root.setProperty("pitch", pitch)
            root.setProperty("panX", 0.0)
            root.setProperty("panY", 0.0)

    def rotate_camera(self, degrees: float) -> None:
        root = self.rootObject()
        if root is not None:
            root.setProperty("yaw", float(root.property("yaw") or 0.0) + float(degrees))

    def align_to_selected_beam(self) -> None:
        """Compatibility action; Quick 3D keeps the current camera orientation."""
        self.set_view_preset("main_axis")

    def focus_node(self, _node_id: str) -> None:
        pass

    def set_instrument_placement_kind(self, _kind: str | None) -> None:
        pass


__all__ = [
    "QUICK3D_ENABLED",
    "QML_PATH",
    "TeachingQuick3DBridge",
    "TeachingQuick3DWidget",
    "flatten_scene",
]
