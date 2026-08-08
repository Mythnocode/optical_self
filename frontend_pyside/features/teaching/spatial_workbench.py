
from __future__ import annotations

from dataclasses import asdict
import copy
import math
from time import monotonic
from typing import Any

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme

from . import unified_workbench as base
from . import component_catalog as catalog


_COMPONENT_MIME = "application/x-optical-teaching-component"


def _enabled(node: base.ExperimentNode) -> bool:
    return bool(node.params.get("enabled", True))


def _angle_delta(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


class SpatialExperimentModel(base.ExperimentModel):


    def __init__(self) -> None:
        self._incident_angles: dict[str, float] = {}
        self._auto_path_segments: list[tuple[str, str, float]] = []
        self._suspend_auto = False
        self._routing_dirty = True
        super().__init__()

    def mark_changed(self) -> None:
        self._routing_dirty = True
        super().mark_changed()

    def _default_params(self, kind: str) -> dict[str, float | str | bool]:
        values = super()._default_params(kind)
        values.setdefault("enabled", True)
        values.setdefault("z_mm", 82.0 if kind not in {"oscilloscope"} else 35.0)
        values.setdefault("pitch_deg", 0.0)
        values.setdefault("roll_deg", 0.0)
        values.setdefault("acceptance_deg", 32.0)
        if kind == "laser":
            values.setdefault("beam_radius_mm", 0.72)
        if kind in {"splitter", "pbs", "beam_sampler"}:
            values.setdefault("branch_offset_deg", 90.0)
        return values

    def add_node(
        self,
        kind: str,
        x: float,
        y: float,
        *,
        label: str | None = None,
        params: dict[str, float | str | bool] | None = None,
        node_id: str | None = None,
        record: bool = True,
        rotation_deg: float | None = None,
    ) -> str:
        previous = self._suspend_auto
        self._suspend_auto = True
        node_id = super().add_node(
            kind,
            x,
            y,
            label=label,
            params=params,
            node_id=node_id,
            record=False,
        )
        node = self.nodes[node_id]
        if rotation_deg is not None:
            node.rotation_deg = float(rotation_deg)
        node.params.update(self._default_params(kind))
        node.params.update(params or {})
        self._suspend_auto = previous
        if record:
            self.record(f"将{node.label}放到实验平台。")
        elif not self._suspend_auto:
            self.rebuild_auto_paths()
        return node_id

    def restore(self, snapshot: dict[str, Any], *, reset_history: bool = False) -> None:
        self._suspend_auto = True
        super().restore(snapshot, reset_history=False)
        for node in self.nodes.values():
            defaults = self._default_params(node.kind)
            defaults.update(node.params)
            node.params = defaults
        self._suspend_auto = False
        self.rebuild_auto_paths()
        if reset_history:
            self._reset_history()

    def record(self, label: str) -> None:
        super().record(label)
        if not self._suspend_auto:
            self.rebuild_auto_paths()

    def load_standard(self, *, record: bool = True) -> None:
        self._suspend_auto = True
        self.nodes.clear()
        self.edges.clear()
        self._counter = 0
        self.add_node("laser", 120, base.MAIN_RAIL_Y, node_id="laser", label="激光器", record=False, rotation_deg=0.0)
        self.add_node("isolator", 300, base.MAIN_RAIL_Y, node_id="isolator", label="光隔离器", record=False, rotation_deg=0.0)
        self.add_node("splitter", 495, base.MAIN_RAIL_Y, node_id="splitter", label="分束器", record=False, rotation_deg=0.0)
        self.add_node("lens", 710, base.MAIN_RAIL_Y, node_id="lens_1", label="L1", params={"focal_mm": 12.0}, record=False, rotation_deg=0.0)
        self.add_node("lens", 910, base.MAIN_RAIL_Y, node_id="lens_2", label="L2", params={"focal_mm": 12.0}, record=False, rotation_deg=0.0)
        self.add_node("fiber", 1160, base.MAIN_RAIL_Y, node_id="fiber", label="五轴光纤架", record=False, rotation_deg=180.0)
        self.add_node(
            "power_meter",
            500,
            base.BRANCH_RAIL_Y,
            node_id="input_meter",
            label="输入功率计",
            params={"range_mw": 500.0},
            record=False,
            rotation_deg=-90.0,
        )
        self.add_node(
            "power_meter",
            1380,
            base.MAIN_RAIL_Y,
            node_id="output_meter",
            label="输出功率计",
            params={"range_mw": 20.0},
            record=False,
            rotation_deg=180.0,
        )
        self.add_node("beam_analyzer", 930, base.BRANCH_RAIL_Y, node_id="beam_analyzer", label="光束分析仪", record=False, rotation_deg=-90.0)
        self.add_node("wavefront_sensor", 1160, base.BRANCH_RAIL_Y, node_id="wavefront", label="波前传感器", record=False, rotation_deg=-90.0)
        self.selected_node_id = "lens_2"
        self.selected_edge_id = None
        self.connect_source_id = None
        self._suspend_auto = False
        self.rebuild_auto_paths()
        self.latest_cause = "恢复标准空间实验平台；光路由器材位置和姿态自动生成。"
        if record:
            self.record(self.latest_cause)

    def clear_platform(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self._incident_angles.clear()
        self.selected_node_id = None
        self.selected_edge_id = None
        self.latest_cause = "已清空自由搭建平台。"
        self.record(self.latest_cause)

    def remove_node_to_tray(self, node_id: str, *, record: bool = True) -> bool:
        node = self.nodes.get(node_id)
        if node is None:
            return False
        label = node.label
        self.nodes.pop(node_id, None)
        self.mark_changed()
        self.selected_node_id = None
        self.selected_edge_id = None
        if record:
            self.record(f"将{label}移出实验平台。")
        else:
            self.rebuild_auto_paths()
        return True

    def set_node_enabled(self, node_id: str, enabled: bool, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.params["enabled"] = bool(enabled)
        self.mark_changed()
        if record:
            self.record(f"{'启用' if enabled else '暂时停用'}{node.label}。")
        else:
            self.rebuild_auto_paths()

    def move_node(self, node_id: str, x: float, y: float, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        old = (node.x, node.y)
        node.x = max(45.0, min(base.SCENE_RECT.width() - 45.0, float(x)))
        node.y = max(70.0, min(base.SCENE_RECT.height() - 70.0, float(y)))
        if self.mode == "layout":
            if node.kind in base.OPTICAL_TYPES:
                node.y = base.MAIN_RAIL_Y
            elif node.kind != "oscilloscope":
                node.y = base.BRANCH_RAIL_Y
        changed = abs(old[0] - node.x) > 0.1 or abs(old[1] - node.y) > 0.1
        if changed:
            self.mark_changed()
            if record:
                self.record(f"移动{node.label}；系统已重新追迹光路。")
            else:
                self.rebuild_auto_paths()

    def move_node_3d(self, node_id: str, x: float, y: float, z_mm: float, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.x = max(45.0, min(base.SCENE_RECT.width() - 45.0, float(x)))
        node.y = max(70.0, min(base.SCENE_RECT.height() - 70.0, float(y)))
        node.params["z_mm"] = max(12.0, min(180.0, float(z_mm)))
        self.mark_changed()
        if record:
            self.record(f"在3D平台中移动{node.label}。")
        else:
            self.rebuild_auto_paths()

    def set_orientation(
        self,
        node_id: str,
        *,
        yaw_deg: float | None = None,
        pitch_deg: float | None = None,
        roll_deg: float | None = None,
        record: bool = True,
    ) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        if yaw_deg is not None:
            node.rotation_deg = float(yaw_deg) % 360.0
        if pitch_deg is not None:
            node.params["pitch_deg"] = max(-89.0, min(89.0, float(pitch_deg)))
        if roll_deg is not None:
            node.params["roll_deg"] = float(roll_deg) % 360.0
        self.mark_changed()
        if record:
            self.record(f"调整{node.label}的空间姿态。")
        else:
            self.rebuild_auto_paths()

    def update_node_params(self, node_id: str, changes: dict[str, Any], *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        spatial = dict(changes)
        if "rotation_deg" in spatial:
            node.rotation_deg = float(spatial.pop("rotation_deg")) % 360.0
        node.params.update(spatial)
        self.mark_changed()
        if record:
            description = "、".join(f"{key}={value}" for key, value in changes.items())
            self.record(f"更新{node.label}：{description}。")
        else:
            self.rebuild_auto_paths()

    def reorder_lenses(self, ordered_ids: list[str], *, record: bool = True) -> None:
        lenses = [self.nodes[node_id] for node_id in ordered_ids if node_id in self.nodes and self.nodes[node_id].kind == "lens"]
        if not lenses:
            return
        x_positions = sorted(node.x for node in lenses)
        for node, x in zip(lenses, x_positions):
            node.x = x
            node.y = base.MAIN_RAIL_Y
        self.mark_changed()
        if record:
            self.record("按镜组编辑带重新排列透镜顺序。")
        else:
            self.rebuild_auto_paths()

    def _ray_hit(
        self,
        origin: QPointF,
        angle_deg: float,
        *,
        excluded: set[str],
    ) -> tuple[base.ExperimentNode, float] | None:
        rad = math.radians(angle_deg)
        dx, dy = math.cos(rad), math.sin(rad)
        best: tuple[base.ExperimentNode, float] | None = None
        for node in self.nodes.values():
            if node.id in excluded or node.kind in {"laser", "oscilloscope"} or not _enabled(node):
                continue
            vx = node.x - origin.x()
            vy = node.y - origin.y()
            forward = vx * dx + vy * dy
            if forward <= 35.0:
                continue
            perpendicular = abs(vx * dy - vy * dx)
            tolerance = 58.0 if node.kind in base.OPTICAL_TYPES else 72.0
            if node.kind == "fiber":
                tolerance = 64.0
            if perpendicular > tolerance:
                continue
            if best is None or forward < best[1]:
                best = (node, forward)
        return best

    def rebuild_auto_paths(self, *, force: bool = False) -> None:

        if self._suspend_auto or (not force and not self._routing_dirty):
            return
        self.edges.clear()
        self._incident_angles.clear()
        self._auto_path_segments.clear()
        edge_counter = 0
        rays: list[tuple[str, QPointF, float, frozenset[str]]] = []
        for laser in self.nodes.values():
            if laser.kind == "laser" and _enabled(laser):
                rays.append((laser.id, QPointF(laser.x, laser.y), laser.rotation_deg, frozenset({laser.id})))
        visited_states: set[tuple[str, int]] = set()
        while rays and edge_counter < 80:
            source_id, origin, angle, visited = rays.pop(0)
            state_key = (source_id, int(round(angle)) % 360)
            if state_key in visited_states:
                continue
            visited_states.add(state_key)
            hit = self._ray_hit(origin, angle, excluded=set(visited))
            if hit is None:
                continue
            target, _distance = hit
            edge_counter += 1
            edge_id = f"auto_edge_{edge_counter}"
            self.edges[edge_id] = base.ExperimentEdge(edge_id, source_id, target.id)
            self._incident_angles[target.id] = angle % 360.0
            self._auto_path_segments.append((source_id, target.id, angle % 360.0))
            next_visited = frozenset(set(visited) | {target.id})
            if target.kind in base.TERMINAL_TYPES or target.kind == "oscilloscope":
                continue
            if target.kind == "mirror":
                outgoing = target.rotation_deg % 360.0
                rays.append((target.id, QPointF(target.x, target.y), outgoing, next_visited))
            elif target.kind in {"splitter", "pbs", "beam_sampler"}:
                rays.append((target.id, QPointF(target.x, target.y), angle % 360.0, next_visited))
                branch = (target.rotation_deg + float(target.params.get("branch_offset_deg", 90.0))) % 360.0
                rays.append((target.id, QPointF(target.x, target.y), branch, next_visited))
            else:
                rays.append((target.id, QPointF(target.x, target.y), angle % 360.0, next_visited))

        
        
        reached = super().reached_nodes() if self.edges else set()
        scopes = [n for n in self.nodes.values() if n.kind == "oscilloscope" and _enabled(n)]
        detectors = [n for n in self.nodes.values() if n.kind == "photodetector" and n.id in reached]
        for scope in scopes:
            if not detectors:
                continue
            detector = min(detectors, key=lambda n: math.hypot(n.x - scope.x, n.y - scope.y))
            if math.hypot(detector.x - scope.x, detector.y - scope.y) <= 310.0:
                edge_counter += 1
                edge_id = f"auto_signal_{edge_counter}"
                self.edges[edge_id] = base.ExperimentEdge(edge_id, detector.id, scope.id)
        self._routing_dirty = False

    def reached_nodes(self) -> set[str]:
        self.rebuild_auto_paths()
        return super().reached_nodes()

    def shortest_path(self, target_kind: str = "fiber") -> list[str]:
        self.rebuild_auto_paths()
        return super().shortest_path(target_kind)

    def evaluate(self) -> base.WorkbenchMetrics:
        self.rebuild_auto_paths()
        return super().evaluate()

    def instrument_reading(self, node_id: str) -> dict[str, Any]:
        self.rebuild_auto_paths()
        reading = super().instrument_reading(node_id)
        node = self.nodes.get(node_id)
        if node is None or not reading.get("valid") or node.kind == "oscilloscope":
            return reading
        incoming = self._incident_angles.get(node_id)
        if incoming is None:
            return {"valid": False, "message": "仪器未处于有效光束路径上。"}
        desired_face = (incoming + 180.0) % 360.0
        error = _angle_delta(node.rotation_deg, desired_face)
        acceptance = float(node.params.get("acceptance_deg", 32.0))
        if error > acceptance:
            return {
                "valid": False,
                "message": f"仪器接收面偏离光束 {error:.1f}°；请旋转接收面后再测量。",
                "orientation_error_deg": error,
            }
        reading["orientation_error_deg"] = error
        return reading


class ComponentTrayList(QListWidget):


    componentRequested = Signal(str)

    def __init__(self, kinds: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setDragEnabled(True)
        self.setSpacing(5)
        self.setMinimumHeight(112)
        self.setMaximumHeight(178)
        for kind in kinds:
            item = QListWidgetItem(base.NODE_LABELS[kind])
            item.setData(Qt.ItemDataRole.UserRole, kind)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            scheme = catalog.DRAWING_SCHEMES.get(kind)
            if scheme is not None:
                item.setToolTip(f"{scheme.role}\n简化外形：{scheme.silhouette}")
            self.addItem(item)
        self.itemDoubleClicked.connect(lambda item: self.componentRequested.emit(str(item.data(Qt.ItemDataRole.UserRole))))

    def startDrag(self, supportedActions) -> None:  
        item = self.currentItem()
        if item is None:
            return
        mime = QMimeData()
        mime.setData(_COMPONENT_MIME, str(item.data(Qt.ItemDataRole.UserRole)).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class SpatialOpticalNodeItem(base.OpticalNodeItem):


    def __init__(self, node: base.ExperimentNode, movable: bool, *, display_layer: str = "overlay", parent=None) -> None:
        super().__init__(node, movable, display_layer=display_layer, show_ports=False, parent=parent)
        self.rotation_deg = float(node.rotation_deg)
        self.enabled = _enabled(node)

    def update_from_node(
        self,
        node: base.ExperimentNode,
        *,
        movable: bool,
        display_layer: str,
        show_ports: bool = False,
    ) -> None:
        super().update_from_node(
            node, movable=movable, display_layer=display_layer, show_ports=show_ports
        )
        self.rotation_deg = float(node.rotation_deg)
        self.enabled = _enabled(node)
        self.update()

    @staticmethod
    def _dark_gradient(top: str = "#30373e", bottom: str = "#11161b") -> QColor:

        return QColor(top)

    def _draw_realistic_base_and_post(self, painter: QPainter, *, width: float = 58.0, post_y: float = 31.0) -> None:

        painter.save()
        painter.setPen(QPen(QColor("#11161b"), 1.0))
        painter.setBrush(QColor("#272e34"))
        painter.drawRoundedRect(QRectF(-width / 2.0, 53, width, 11), 3, 3)
        painter.setPen(QPen(QColor("#66717a"), 1.0))
        painter.setBrush(QColor("#7d878f"))
        painter.drawRoundedRect(QRectF(-4, post_y, 8, 24), 2, 2)
        painter.setBrush(QColor("#434c53"))
        painter.drawEllipse(QRectF(-7, 49, 14, 7))
        painter.restore()

    @staticmethod
    def _draw_metal_knob(painter: QPainter, rect: QRectF) -> None:

        painter.setPen(QPen(QColor("#3b4349"), 0.9))
        painter.setBrush(QColor("#8d979e"))
        painter.drawEllipse(rect)

    def _draw_laser(self, painter: QPainter) -> None:
        
        painter.setPen(QPen(QColor("#0a0d10"), 1.2))
        painter.setBrush(QColor("#242a30"))
        painter.drawRoundedRect(QRectF(-54, -26, 84, 52), 5, 5)
        painter.setBrush(QColor("#1a2025"))
        painter.drawRoundedRect(QRectF(-43, 28, 21, 9), 2, 2)
        painter.drawRoundedRect(QRectF(3, 28, 21, 9), 2, 2)
        painter.setBrush(QColor("#8a949b"))
        painter.setPen(QPen(QColor("#3f484e"), 1.0))
        painter.drawEllipse(QRectF(20, -15, 26, 30))
        painter.setBrush(QColor("#050607"))
        painter.drawEllipse(QRectF(30, -10, 17, 20))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 52, 52, 220))
        painter.drawEllipse(QRectF(39, -4, 8, 8))

    def _draw_isolator(self, painter: QPainter) -> None:
        
        painter.setPen(QPen(QColor("#4f151b"), 1.0))
        painter.setBrush(QColor("#84232b"))
        painter.drawRoundedRect(QRectF(-43, 31, 86, 12), 3, 3)
        painter.setBrush(QColor("#a52b35"))
        painter.drawRoundedRect(QRectF(-29, -26, 58, 56), 4, 4)
        painter.setBrush(QColor("#858f96"))
        painter.setPen(QPen(QColor("#4f595f"), 1.0))
        painter.drawRoundedRect(QRectF(-49, -15, 98, 30), 13, 13)
        painter.setBrush(QColor("#050607"))
        painter.drawEllipse(QRectF(-54, -10, 14, 20))
        painter.drawEllipse(QRectF(40, -10, 14, 20))
        painter.setPen(QPen(QColor("#f3f5f6"), 1.8))
        painter.drawLine(QPointF(-10, 0), QPointF(12, 0))
        painter.drawLine(QPointF(6, -6), QPointF(12, 0))
        painter.drawLine(QPointF(6, 6), QPointF(12, 0))

    def _draw_half_wave_plate(self, painter: QPainter) -> None:

        self._draw_realistic_base_and_post(painter, width=54, post_y=31)
        painter.setPen(QPen(QColor("#0b0f12"), 2.0))
        painter.setBrush(QColor("#181d21"))
        painter.drawEllipse(QRectF(-32, -40, 64, 80))
        painter.setPen(QPen(QColor("#78b9d8"), 1.2))
        painter.setBrush(QColor(76, 158, 196, 80))
        painter.drawEllipse(QRectF(-22, -30, 44, 60))
        painter.setPen(QPen(QColor("#d7e3e9"), 1.5))
        painter.drawLine(QPointF(-16, 16), QPointF(16, -16))
        self._draw_metal_knob(painter, QRectF(25, -6, 13, 13))

    def _draw_pbs(self, painter: QPainter) -> None:

        self._draw_realistic_base_and_post(painter, width=62, post_y=30)
        painter.setPen(QPen(QColor("#0b0f12"), 2.0))
        painter.setBrush(QColor("#171c21"))
        painter.drawRoundedRect(QRectF(-38, -38, 76, 76), 5, 5)
        painter.setPen(QPen(QColor("#71b9d9"), 1.2))
        painter.setBrush(QColor(54, 143, 184, 92))
        painter.drawRect(QRectF(-27, -27, 54, 54))
        painter.setPen(QPen(QColor("#c1e5f3"), 1.7))
        painter.drawLine(QPointF(-22, 22), QPointF(22, -22))
        painter.setPen(QPen(QColor("#8a969e"), 3.0))
        painter.drawLine(QPointF(38, 0), QPointF(48, 0))
        painter.drawLine(QPointF(0, -38), QPointF(0, -48))

    def _draw_beam_sampler(self, painter: QPainter) -> None:

        self._draw_realistic_base_and_post(painter, width=52, post_y=31)
        painter.save()
        painter.rotate(-35.0)
        painter.setPen(QPen(QColor("#64afd2"), 1.4))
        painter.setBrush(QColor(61, 150, 194, 82))
        painter.drawRoundedRect(QRectF(-7, -43, 14, 86), 2, 2)
        painter.restore()
        painter.setPen(QPen(QColor("#9aa4aa"), 1.0))
        painter.drawLine(QPointF(16, -20), QPointF(29, -32))

    def _draw_splitter(self, painter: QPainter) -> None:
        self._draw_realistic_base_and_post(painter, width=62, post_y=30)
        
        painter.setPen(QPen(QColor("#0b0f12"), 2.0))
        painter.setBrush(QColor("#171c21"))
        painter.drawRoundedRect(QRectF(-37, -37, 74, 74), 5, 5)
        painter.setPen(QPen(QColor("#72bddf"), 1.2))
        painter.setBrush(QColor(63, 151, 194, 105))
        painter.drawRoundedRect(QRectF(-27, -27, 54, 54), 3, 3)
        painter.setPen(QPen(QColor(190, 229, 245, 185), 1.7))
        painter.drawLine(QPointF(-22, 22), QPointF(22, -22))
        self._draw_metal_knob(painter, QRectF(23, -34, 12, 12))

    def _draw_mirror(self, painter: QPainter) -> None:
        self._draw_realistic_base_and_post(painter, width=64, post_y=30)
        painter.setPen(QPen(QColor("#0a0d10"), 2.0))
        painter.setBrush(QColor("#181d21"))
        painter.drawRoundedRect(QRectF(-38, -39, 66, 74), 7, 7)
        painter.setPen(QPen(QColor("#9ca6ac"), 1.2))
        painter.setBrush(QColor("#737e85"))
        painter.drawEllipse(QRectF(-27, -28, 54, 56))
        
        self._draw_metal_knob(painter, QRectF(28, -25, 15, 15))
        self._draw_metal_knob(painter, QRectF(28, 10, 15, 15))

    def _draw_aperture(self, painter: QPainter) -> None:
        self._draw_realistic_base_and_post(painter, width=54, post_y=29)
        painter.setPen(QPen(QColor("#0b0e10"), 1.7))
        painter.setBrush(QColor("#171c20"))
        painter.drawEllipse(QRectF(-30, -37, 60, 74))
        painter.setBrush(QColor("#030405"))
        painter.drawEllipse(QRectF(-9, -12, 18, 24))
        self._draw_metal_knob(painter, QRectF(27, -7, 15, 15))

    def _draw_lens(self, painter: QPainter) -> None:
        self._draw_realistic_base_and_post(painter, width=58, post_y=34)
        painter.setPen(QPen(QColor("#0a0d0f"), 2.0))
        painter.setBrush(QColor("#171c20"))
        painter.drawEllipse(QRectF(-31, -47, 62, 94))
        painter.setPen(QPen(QColor(theme.COMPONENT_LENS), 1.3))
        painter.setBrush(QColor(51, 151, 198, 110))
        painter.drawEllipse(QRectF(-21, -38, 42, 76))
        self._draw_metal_knob(painter, QRectF(25, -7, 14, 14))

    def _draw_beam_expander(self, painter: QPainter) -> None:

        painter.setPen(QPen(QColor("#0a0d10"), 1.2))
        painter.setBrush(QColor("#252c32"))
        painter.drawRoundedRect(QRectF(-60, 35, 120, 13), 3, 3)
        for x, w, h in [(-28, 34, 60), (27, 48, 82)]:
            painter.setBrush(QColor("#171c20"))
            painter.drawEllipse(QRectF(x - w / 2, -h / 2, w, h))
            painter.setPen(QPen(QColor(theme.COMPONENT_LENS), 1.2))
            painter.setBrush(QColor(51, 151, 198, 90))
            painter.drawEllipse(QRectF(x - w * 0.32, -h * 0.38, w * 0.64, h * 0.76))
            painter.setPen(QPen(QColor("#0a0d10"), 1.2))
        painter.setPen(QPen(QColor("#7d878f"), 1.0))
        painter.drawLine(QPointF(-28, 30), QPointF(-28, 36))
        painter.drawLine(QPointF(27, 40), QPointF(27, 36))

    def _draw_cylindrical_lens(self, painter: QPainter) -> None:

        self._draw_realistic_base_and_post(painter, width=56, post_y=33)
        painter.setPen(QPen(QColor("#0a0d0f"), 2.0))
        painter.setBrush(QColor("#171c20"))
        painter.drawRoundedRect(QRectF(-31, -43, 62, 86), 5, 5)
        painter.setPen(QPen(QColor(theme.COMPONENT_LENS), 1.3))
        painter.setBrush(QColor(51, 151, 198, 100))
        painter.drawRoundedRect(QRectF(-18, -34, 36, 68), 6, 6)
        painter.setPen(QPen(QColor("#c5e7f5"), 1.4))
        painter.drawArc(QRectF(-11, -29, 22, 58), 90 * 16, 180 * 16)
        self._draw_metal_knob(painter, QRectF(25, -7, 14, 14))

    def _draw_fiber_stage(self, painter: QPainter) -> None:
        
        painter.setPen(QPen(QColor("#0a0d10"), 1.2))
        painter.setBrush(QColor("#252c32"))
        painter.drawRoundedRect(QRectF(-55, 24, 92, 36), 4, 4)
        painter.drawRoundedRect(QRectF(-42, -39, 68, 67), 5, 5)
        painter.setBrush(QColor("#11161a"))
        painter.setPen(QPen(QColor("#424b52"), 1.0))
        painter.drawEllipse(QRectF(-24, -28, 48, 48))
        painter.setBrush(QColor("#050607"))
        painter.drawEllipse(QRectF(-13, -17, 26, 26))
        painter.setBrush(QColor("#8b959c"))
        painter.drawRoundedRect(QRectF(17, -7, 43, 14), 6, 6)
        painter.setBrush(QColor("#050607"))
        painter.drawEllipse(QRectF(50, -5, 12, 10))
        for rect in [QRectF(-60, -23, 17, 17), QRectF(-29, -53, 17, 17), QRectF(15, 34, 17, 17)]:
            self._draw_metal_knob(painter, rect)

    def _draw_instrument(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#0a0d10"), 1.2))
        painter.setBrush(QColor("#242b31"))
        if self.kind == "focus_scan_module":
            
            painter.drawRoundedRect(QRectF(-62, 38, 124, 12), 3, 3)
            painter.setBrush(QColor("#545e65"))
            painter.drawRoundedRect(QRectF(-13, 28, 34, 13), 3, 3)
            painter.setBrush(QColor("#242b31"))
            painter.drawRoundedRect(QRectF(-28, -25, 62, 54), 5, 5)
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(25, -15, 27, 30))
            painter.setBrush(QColor(theme.TEXT_SECONDARY))
            painter.drawEllipse(QRectF(34, -9, 14, 18))
            return

        self._draw_realistic_base_and_post(painter, width=56, post_y=30)
        painter.setBrush(QColor("#242b31"))
        if self.kind in {"power_meter", "photodetector"}:
            painter.drawRoundedRect(QRectF(-42, -25, 70, 50), 12, 12)
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(18, -17, 30, 34))
            painter.setBrush(QColor(theme.TEXT_SECONDARY))
            painter.drawEllipse(QRectF(28, -10, 16, 20))
        elif self.kind == "wavefront_sensor":
            painter.drawRoundedRect(QRectF(-52, -31, 90, 62), 5, 5)
            painter.setBrush(QColor("#11161a"))
            painter.drawRoundedRect(QRectF(25, -17, 28, 34), 3, 3)
            painter.setBrush(QColor(theme.TEXT_SECONDARY))
            painter.drawRect(QRectF(32, -10, 14, 20))
        else:
            painter.drawRoundedRect(QRectF(-50, -31, 88, 62), 6, 6)
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(29, -15, 25, 30))
            painter.setBrush(QColor("#24333c"))
            painter.drawRoundedRect(QRectF(-38, -18, 47, 36), 3, 3)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_selection_halo(painter)
        opacity = (0.46 if self.display_layer == "principle" else 1.0) * (1.0 if self.enabled else 0.30)
        painter.save()
        painter.setOpacity(opacity)
        painter.rotate(self.rotation_deg)
        if self.kind == "laser":
            self._draw_laser(painter)
        elif self.kind == "isolator":
            self._draw_isolator(painter)
        elif self.kind == "half_wave_plate":
            self._draw_half_wave_plate(painter)
        elif self.kind == "pbs":
            self._draw_pbs(painter)
        elif self.kind == "beam_sampler":
            self._draw_beam_sampler(painter)
        elif self.kind == "splitter":
            self._draw_splitter(painter)
        elif self.kind == "mirror":
            self._draw_mirror(painter)
        elif self.kind == "aperture":
            self._draw_aperture(painter)
        elif self.kind == "lens":
            self._draw_lens(painter)
        elif self.kind == "beam_expander":
            self._draw_beam_expander(painter)
        elif self.kind == "cylindrical_lens":
            self._draw_cylindrical_lens(painter)
        elif self.kind == "fiber":
            self._draw_fiber_stage(painter)
        else:
            self._draw_instrument(painter)
        painter.restore()

        
        if self.isSelected() and self.kind in {"laser", "mirror", "splitter", "pbs", "beam_sampler", "fiber"} | base.INSTRUMENT_TYPES:
            rad = math.radians(self.rotation_deg)
            start = QPointF(0, -58)
            end = QPointF(start.x() + 24 * math.cos(rad), start.y() + 24 * math.sin(rad))
            painter.setPen(QPen(QColor(theme.PRIMARY), 1.6))
            painter.drawLine(start, end)
            painter.drawEllipse(end, 2.4, 2.4)

        painter.setPen(QColor("#f2f5f7" if self.enabled else "#8798a3"))
        font = painter.font()
        font.setBold(self.isSelected())
        painter.setFont(font)
        suffix = "（停用）" if not self.enabled else ""
        painter.drawText(
            QRectF(-78, 65, 156, 34),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            f"{self.label}{suffix}",
        )


class SpatialExperimentGraphicsView(base.ExperimentGraphicsView):
    componentDropped = Signal(str, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def set_model(
        self,
        model: SpatialExperimentModel,
        *,
        preserve_view: bool = True,
        snapshot: base.TeachingSceneSnapshot | None = None,
    ) -> None:
        transform = self.transform()
        center_scene = self.mapToScene(self.viewport().rect().center())
        self._model = model
        self.scene_obj.set_display_layer(self._display_layer)
        snapshot = snapshot or model.scene_snapshot()
        reached = set(snapshot.metrics.reached_node_ids)
        current_radii, ideal_radii = snapshot.current_radii, snapshot.ideal_radii
        movable = model.mode in {"layout", "free", "diagnostic"}

        for edge_id in tuple(self._edge_items):
            if edge_id not in model.edges:
                item = self._edge_items.pop(edge_id)
                self.scene_obj.removeItem(item)
                item.deleteLater()
        for node_id in tuple(self._node_items):
            if node_id not in model.nodes:
                item = self._node_items.pop(node_id)
                self.scene_obj.removeItem(item)
                item.deleteLater()

        for node in model.nodes.values():
            node_movable = movable and not (model.mode == "layout" and node.kind in {"laser", "isolator", "half_wave_plate", "pbs", "splitter"})
            item = self._node_items.get(node.id)
            if item is None or item.kind != node.kind:
                if item is not None:
                    self.scene_obj.removeItem(item)
                    item.deleteLater()
                item = SpatialOpticalNodeItem(node, node_movable, display_layer=self._display_layer)
                item.activated.connect(self.nodeActivated)
                item.positionChanged.connect(self._on_item_position_changed)
                item.movementFinished.connect(self.nodeMoved)
                self.scene_obj.addItem(item)
                self._node_items[node.id] = item
            else:
                item.update_from_node(node, movable=node_movable, display_layer=self._display_layer)
            item.setSelected(node.id == model.selected_node_id)

        for edge in model.edges.values():
            source = self._node_items.get(edge.source)
            target = self._node_items.get(edge.target)
            if source is None or target is None:
                continue
            item = self._edge_items.get(edge.id)
            if item is None or item.source_item is not source or item.target_item is not target:
                if item is not None:
                    self.scene_obj.removeItem(item)
                    item.deleteLater()
                item = base.OpticalConnectionItem(edge, source, target, False, False)
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.scene_obj.addItem(item)
                self._edge_items[edge.id] = item
            item.update_state(
                reached=edge.source in reached and edge.target in reached,
                selected=False,
                source_radius=current_radii.get(edge.source, 6.0),
                target_radius=current_radii.get(edge.target, 6.0),
                ideal_source_radius=ideal_radii.get(edge.source, 6.0),
                ideal_target_radius=ideal_radii.get(edge.target, 6.0),
                display_layer=self._display_layer,
            )
        if preserve_view and self._initial_fit_done:
            self.setTransform(transform)
            self.centerOn(center_scene)
        else:
            self.fit_full()

    def dragEnterEvent(self, event) -> None:  
        if event.mimeData().hasFormat(_COMPONENT_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  
        if event.mimeData().hasFormat(_COMPONENT_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  
        if not event.mimeData().hasFormat(_COMPONENT_MIME):
            super().dropEvent(event)
            return
        kind = bytes(event.mimeData().data(_COMPONENT_MIME)).decode("utf-8")
        scene_pos = self.mapToScene(event.position().toPoint())
        self.componentDropped.emit(kind, scene_pos.x(), scene_pos.y())
        event.acceptProposedAction()


class LensSequenceStrip(QFrame):
    orderChanged = Signal(list)
    addRequested = Signal()
    selectRequested = Signal(str)
    enabledRequested = Signal(str, bool)
    removeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingLensSequenceStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        title = QLabel("镜组")
        title.setObjectName("drawerTitle")
        layout.addWidget(title)
        self.list = QListWidget()
        self.list.setFlow(QListView.Flow.LeftToRight)
        self.list.setWrapping(False)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMaximumHeight(58)
        self.list.setMinimumWidth(420)
        self.list.itemClicked.connect(lambda item: self.selectRequested.emit(str(item.data(Qt.ItemDataRole.UserRole))))
        self.list.model().rowsMoved.connect(lambda *_args: self._emit_order())
        layout.addWidget(self.list, 1)
        add = QPushButton("＋添加透镜")
        add.clicked.connect(self.addRequested)
        layout.addWidget(add)
        self.toggle = QPushButton("停用/启用")
        self.toggle.clicked.connect(self._toggle_current)
        layout.addWidget(self.toggle)
        remove = QPushButton("移出平台")
        remove.clicked.connect(self._remove_current)
        layout.addWidget(remove)
        close = QToolButton()
        close.setText("×")
        close.clicked.connect(self.hide)
        layout.addWidget(close)

    def _emit_order(self) -> None:
        self.orderChanged.emit([
            str(self.list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.list.count())
        ])

    def _current_id(self) -> str | None:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _toggle_current(self) -> None:
        node_id = self._current_id()
        if node_id is None:
            return
        item = self.list.currentItem()
        enabled = not bool(item.data(Qt.ItemDataRole.UserRole + 1))
        self.enabledRequested.emit(node_id, enabled)

    def _remove_current(self) -> None:
        node_id = self._current_id()
        if node_id:
            self.removeRequested.emit(node_id)

    def set_model(self, model: SpatialExperimentModel) -> None:
        selected = model.selected_node_id
        self.list.blockSignals(True)
        self.list.clear()
        lenses = sorted((n for n in model.nodes.values() if n.kind == "lens"), key=lambda n: n.x)
        for node in lenses:
            focal = float(node.params.get("focal_mm", 50.0))
            enabled = _enabled(node)
            item = QListWidgetItem(f"{node.label}  {focal:g} mm{'  · 停用' if not enabled else ''}")
            item.setData(Qt.ItemDataRole.UserRole, node.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, enabled)
            self.list.addItem(item)
            if node.id == selected:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)


class SpatialExperiment3DView(QWidget):


    objectActivated = Signal(str)
    objectChanged = Signal(str, str)
    cameraChanged = Signal(float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingExperiment3DView")
        self.setMinimumSize(600, 380)
        self.setMouseTracking(True)
        self._model: SpatialExperimentModel | None = None
        self._metrics: base.WorkbenchMetrics | None = None
        self._snapshot: base.TeachingSceneSnapshot | None = None
        self._fast_interaction = False
        self._last_drag_repaint = 0.0
        self._display_layer = "overlay"
        self._rays_only = False
        self._azimuth = 4.0
        self._elevation = 12.0
        self._zoom = 0.94
        self._pan = QPointF(0.0, 0.0)
        self._focus = (800.0, 390.0, 0.0)
        self._hit_boxes: dict[str, QRectF] = {}
        self._last_mouse = QPointF()
        self._interaction: str | None = None
        self._active_node_id: str | None = None
        self._node_origin: tuple[float, float, float, float, float] | None = None
        self._layer_flags = {
            "structure": True,
            "beam": True,
            "ideal": False,
            "axis": True,
            "coordinates": False,
            "measurement": False,
        }

    def set_model(
        self, model: SpatialExperimentModel, snapshot: base.TeachingSceneSnapshot | None = None
    ) -> None:
        self._model = model
        self._snapshot = snapshot or model.scene_snapshot()
        self._metrics = self._snapshot.metrics
        self.update()

    def _throttled_drag_repaint(self) -> None:
        now = monotonic()
        if now - self._last_drag_repaint < 0.032:
            return
        self._last_drag_repaint = now
        self.update()

    def set_display_layer(self, layer: str) -> None:
        self._display_layer = layer if layer in base.DISPLAY_LAYER_LABELS else "overlay"
        self._layer_flags["ideal"] = self._display_layer in {"principle", "overlay"}
        self.update()

    def set_rays_only(self, enabled: bool) -> None:
        self._rays_only = bool(enabled)
        self.update()

    def set_layer_visible(self, key: str, visible: bool) -> None:
        if key in self._layer_flags:
            self._layer_flags[key] = bool(visible)
            self.update()

    def camera_state(self) -> tuple[float, float, float]:
        return self._azimuth, self._elevation, self._zoom

    def reset_camera(self) -> None:
        self._azimuth, self._elevation, self._zoom = 4.0, 12.0, 0.94
        self._pan = QPointF(0.0, 0.0)
        self._focus = (800.0, 390.0, 0.0)
        self.cameraChanged.emit(*self.camera_state())
        self.update()

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
        self._azimuth, self._elevation = presets.get(preset, presets["isometric"])
        self._pan = QPointF()
        self.cameraChanged.emit(*self.camera_state())
        self.update()

    def rotate_camera(self, degrees: float) -> None:
        self._azimuth = (self._azimuth + float(degrees)) % 360.0
        self.cameraChanged.emit(*self.camera_state())
        self.update()

    def focus_node(self, node_id: str) -> None:
        if self._model is None or node_id not in self._model.nodes:
            return
        node = self._model.nodes[node_id]
        self._focus = (node.x, node.y, float(node.params.get("z_mm", 82.0)))
        self._pan = QPointF()
        self._zoom = max(self._zoom, 1.35)
        self.cameraChanged.emit(*self.camera_state())
        self.update()

    def _base_scale(self) -> float:
        return min(self.width() / 1850.0, self.height() / 1080.0) * self._zoom

    def _project(self, x: float, y: float, z: float) -> tuple[QPointF, float, float]:
        fx, fy, fz = self._focus
        dx, dy, dz = x - fx, y - fy, z - fz
        az = math.radians(self._azimuth)
        el = math.radians(self._elevation)
        x1 = math.cos(az) * dx - math.sin(az) * dy
        y1 = math.sin(az) * dx + math.cos(az) * dy
        depth = math.cos(el) * y1 + math.sin(el) * dz
        vertical = -math.sin(el) * y1 + math.cos(el) * dz
        perspective = 1.0 / max(0.52, 1.0 + depth / 4200.0)
        scale = self._base_scale() * perspective
        point = QPointF(
            self.width() * 0.5 + self._pan.x() + x1 * scale,
            self.height() * 0.52 + self._pan.y() - vertical * scale,
        )
        return point, depth, scale

    def _draw_board(self, painter: QPainter) -> None:

        corners = [(25, 25), (1575, 25), (1575, 875), (25, 875)]
        top = QPolygonF([self._project(x, y, 0.0)[0] for x, y in corners])
        bottom = QPolygonF([self._project(x, y, -34.0)[0] for x, y in corners])
        painter.setPen(QPen(QColor("#10151b"), 1.2))
        painter.setBrush(QColor("#171d24"))
        painter.drawPolygon(QPolygonF([top[3], top[2], bottom[2], bottom[3]]))
        painter.setBrush(QColor("#11171d"))
        painter.drawPolygon(QPolygonF([top[1], top[2], bottom[2], bottom[1]]))
        painter.setBrush(QColor("#272e35"))
        painter.setPen(QPen(QColor("#4e5962"), 1.0))
        painter.drawPolygon(top)
        painter.setPen(QPen(QColor(112, 124, 135, 90), 0.7))
        painter.setBrush(QColor(8, 12, 16, 150))
        for x in range(75, 1550, 100):
            for y in range(75, 850, 100):
                point, _depth, scale = self._project(float(x), float(y), 2.0)
                radius = max(1.0, 2.4 * scale)
                painter.drawEllipse(point, radius, radius)

    def _draw_beam_segment(
        self,
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        start_radius: float,
        end_radius: float,
    ) -> None:

        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return
        nx, ny = -dy / length, dx / length
        r0 = max(3.0, min(18.0, float(start_radius) * 0.62))
        r1 = max(2.2, min(18.0, float(end_radius) * 0.62))
        envelope = QPolygonF([
            QPointF(start.x() + nx * r0, start.y() + ny * r0),
            QPointF(end.x() + nx * r1, end.y() + ny * r1),
            QPointF(end.x() - nx * r1, end.y() - ny * r1),
            QPointF(start.x() - nx * r0, start.y() - ny * r0),
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 48, 48, 82))
        painter.drawPolygon(envelope)
        painter.setPen(QPen(QColor("#ff5b5b"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, end)

    def _draw_axis_and_beams(self, painter: QPainter) -> None:
        if self._model is None:
            return
        reached = set(self._metrics.reached_node_ids if self._metrics else ())
        if self._layer_flags["axis"]:
            p1 = self._project(60, base.MAIN_RAIL_Y, 82)[0]
            p2 = self._project(1540, base.MAIN_RAIL_Y, 82)[0]
            painter.setPen(QPen(QColor(185, 199, 211, 72), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(p1, p2)
        if not self._layer_flags["beam"]:
            return
        current_radii = self._snapshot.current_radii if self._snapshot is not None else self._model.scene_snapshot().current_radii
        for edge in self._model.edges.values():
            source = self._model.nodes.get(edge.source)
            target = self._model.nodes.get(edge.target)
            if source is None or target is None or (source.kind == "photodetector" and target.kind == "oscilloscope"):
                continue
            if source.id not in reached or target.id not in reached:
                continue
            sz = float(source.params.get("z_mm", 82.0))
            tz = float(target.params.get("z_mm", 82.0))
            a = self._project(source.x, source.y, sz)[0]
            b = self._project(target.x, target.y, tz)[0]
            if self._fast_interaction:
                painter.setPen(QPen(QColor(theme.ERROR), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(a, b)
            else:
                self._draw_beam_segment(
                    painter, a, b,
                    current_radii.get(source.id, 8.0),
                    current_radii.get(target.id, 8.0),
                )

    def _component_scale(self, node: base.ExperimentNode) -> tuple[QPointF, float]:
        z = float(node.params.get("z_mm", 82.0))
        point, _depth, scale = self._project(node.x, node.y, z)
        return point, max(0.55, min(1.65, scale * 2.0))

    def _draw_post(self, painter: QPainter, node: base.ExperimentNode, point: QPointF, scale: float) -> None:
        base_point = self._project(node.x, node.y, 2.0)[0]
        painter.setPen(QPen(QColor("#11161b"), 1.0))
        painter.setBrush(QColor("#292f35"))
        painter.drawRoundedRect(QRectF(base_point.x() - 22 * scale, base_point.y() - 5 * scale, 44 * scale, 10 * scale), 3, 3)
        painter.setPen(QPen(QColor("#707b84"), max(1.0, 4.5 * scale)))
        painter.drawLine(base_point, point + QPointF(0, 13 * scale))

    @staticmethod
    def _draw_screen_knob(painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#3b4349"), 0.9))
        painter.setBrush(QColor("#8d979e"))
        painter.drawEllipse(rect)

    @staticmethod
    def _body_gradient(point: QPointF, scale: float, top: str = "#30373e", bottom: str = "#11161b") -> QColor:

        return QColor(top)

    def _draw_component(self, painter: QPainter, node: base.ExperimentNode) -> None:
        point, scale = self._component_scale(node)
        enabled = _enabled(node)
        selected = self._model is not None and node.id == self._model.selected_node_id
        painter.save()
        painter.setOpacity(1.0 if enabled else 0.28)
        outline = QColor("#5bb8e5") if selected else QColor("#0b0e11")
        painter.setPen(QPen(outline, 2.0 if selected else 1.0))
        body = QColor("#252c32")

        if node.kind == "laser":
            base_point = self._project(node.x, node.y, 3.0)[0]
            painter.setBrush(QColor("#171c21"))
            painter.drawRoundedRect(QRectF(base_point.x() - 48 * scale, base_point.y() - 6 * scale, 86 * scale, 12 * scale), 3, 3)
            painter.setBrush(body)
            painter.drawRoundedRect(QRectF(point.x() - 52 * scale, point.y() - 25 * scale, 84 * scale, 50 * scale), 5, 5)
            painter.setBrush(QColor("#8a949b"))
            painter.setPen(QPen(QColor("#3f484e"), 1.0))
            painter.drawEllipse(QRectF(point.x() + 20 * scale, point.y() - 15 * scale, 28 * scale, 30 * scale))
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(point.x() + 31 * scale, point.y() - 10 * scale, 18 * scale, 20 * scale))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 52, 52, 220))
            painter.drawEllipse(QRectF(point.x() + 40 * scale, point.y() - 4 * scale, 8 * scale, 8 * scale))

        elif node.kind == "isolator":
            base_point = self._project(node.x, node.y, 3.0)[0]
            painter.setPen(QPen(QColor("#4f151b"), 1.0))
            painter.setBrush(QColor("#84232b"))
            painter.drawRoundedRect(QRectF(base_point.x() - 43 * scale, base_point.y() - 5 * scale, 86 * scale, 12 * scale), 3, 3)
            painter.setBrush(QColor("#858f96"))
            painter.setPen(QPen(QColor("#4f595f"), 1.0))
            painter.drawRoundedRect(QRectF(point.x() - 49 * scale, point.y() - 15 * scale, 98 * scale, 30 * scale), 13, 13)
            painter.setBrush(QColor("#a52b35"))
            painter.setPen(QPen(QColor("#63171e"), 1.0))
            painter.drawRoundedRect(QRectF(point.x() - 28 * scale, point.y() - 27 * scale, 56 * scale, 55 * scale), 4, 4)
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(point.x() - 54 * scale, point.y() - 10 * scale, 14 * scale, 20 * scale))
            painter.drawEllipse(QRectF(point.x() + 40 * scale, point.y() - 10 * scale, 14 * scale, 20 * scale))
            painter.setPen(QPen(QColor("#f3f5f6"), max(1.0, 1.7 * scale)))
            painter.drawLine(point + QPointF(-10 * scale, 0), point + QPointF(12 * scale, 0))
            painter.drawLine(point + QPointF(6 * scale, -6 * scale), point + QPointF(12 * scale, 0))
            painter.drawLine(point + QPointF(6 * scale, 6 * scale), point + QPointF(12 * scale, 0))

        elif node.kind == "half_wave_plate":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0b0f12"), 2.0))
            painter.setBrush(QColor("#181d21"))
            painter.drawEllipse(QRectF(point.x() - 32 * scale, point.y() - 40 * scale, 64 * scale, 80 * scale))
            painter.setPen(QPen(QColor("#78b9d8"), 1.2))
            painter.setBrush(QColor(76, 158, 196, 80))
            painter.drawEllipse(QRectF(point.x() - 22 * scale, point.y() - 30 * scale, 44 * scale, 60 * scale))
            painter.setPen(QPen(QColor("#d7e3e9"), 1.4))
            painter.drawLine(point + QPointF(-16 * scale, 16 * scale), point + QPointF(16 * scale, -16 * scale))

        elif node.kind == "pbs":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0b0f12"), 2.0))
            painter.setBrush(QColor("#171c21"))
            painter.drawRoundedRect(QRectF(point.x() - 38 * scale, point.y() - 38 * scale, 76 * scale, 76 * scale), 5, 5)
            painter.setPen(QPen(QColor("#71b9d9"), 1.2))
            painter.setBrush(QColor(54, 143, 184, 92))
            painter.drawRect(QRectF(point.x() - 27 * scale, point.y() - 27 * scale, 54 * scale, 54 * scale))
            painter.setPen(QPen(QColor("#c1e5f3"), max(1.0, 1.6 * scale)))
            painter.drawLine(point + QPointF(-22 * scale, 22 * scale), point + QPointF(22 * scale, -22 * scale))

        elif node.kind == "beam_sampler":
            self._draw_post(painter, node, point, scale)
            plate = QPolygonF([
                point + QPointF(-10 * scale, -42 * scale),
                point + QPointF(2 * scale, -42 * scale),
                point + QPointF(18 * scale, 42 * scale),
                point + QPointF(6 * scale, 42 * scale),
            ])
            painter.setPen(QPen(QColor("#64afd2"), 1.3))
            painter.setBrush(QColor(61, 150, 194, 82))
            painter.drawPolygon(plate)

        elif node.kind == "splitter":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0b0f12"), 2.0))
            painter.setBrush(QColor("#171c21"))
            painter.drawRoundedRect(QRectF(point.x() - 37 * scale, point.y() - 37 * scale, 74 * scale, 74 * scale), 5, 5)
            painter.setPen(QPen(QColor("#72bddf"), 1.2))
            painter.setBrush(QColor(63, 151, 194, 105))
            painter.drawRoundedRect(QRectF(point.x() - 27 * scale, point.y() - 27 * scale, 54 * scale, 54 * scale), 3, 3)
            painter.setPen(QPen(QColor(190, 229, 245, 185), max(1.0, 1.6 * scale)))
            painter.drawLine(point + QPointF(-22 * scale, 22 * scale), point + QPointF(22 * scale, -22 * scale))
            self._draw_screen_knob(painter, QRectF(point.x() + 23 * scale, point.y() - 34 * scale, 12 * scale, 12 * scale))

        elif node.kind == "mirror":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0a0d10"), 2.0))
            painter.setBrush(QColor("#181d21"))
            painter.drawRoundedRect(QRectF(point.x() - 38 * scale, point.y() - 39 * scale, 66 * scale, 74 * scale), 7, 7)
            painter.setPen(QPen(QColor("#9ca6ac"), 1.2))
            painter.setBrush(QColor("#737e85"))
            painter.drawEllipse(QRectF(point.x() - 27 * scale, point.y() - 28 * scale, 54 * scale, 56 * scale))
            self._draw_screen_knob(painter, QRectF(point.x() + 28 * scale, point.y() - 25 * scale, 15 * scale, 15 * scale))
            self._draw_screen_knob(painter, QRectF(point.x() + 28 * scale, point.y() + 10 * scale, 15 * scale, 15 * scale))

        elif node.kind == "aperture":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0a0d10"), 1.7))
            painter.setBrush(QColor("#181d21"))
            painter.drawEllipse(QRectF(point.x() - 30 * scale, point.y() - 37 * scale, 60 * scale, 74 * scale))
            painter.setBrush(QColor("#030405"))
            painter.drawEllipse(QRectF(point.x() - 9 * scale, point.y() - 12 * scale, 18 * scale, 24 * scale))

        elif node.kind == "lens":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0a0d0f"), 2.0))
            painter.setBrush(QColor("#171c20"))
            painter.drawEllipse(QRectF(point.x() - 31 * scale, point.y() - 47 * scale, 62 * scale, 94 * scale))
            painter.setPen(QPen(QColor(theme.COMPONENT_LENS), 1.3))
            painter.setBrush(QColor(51, 151, 198, 110))
            painter.drawEllipse(QRectF(point.x() - 21 * scale, point.y() - 38 * scale, 42 * scale, 76 * scale))
            self._draw_screen_knob(painter, QRectF(point.x() + 25 * scale, point.y() - 7 * scale, 14 * scale, 14 * scale))

        elif node.kind == "beam_expander":
            base_point = self._project(node.x, node.y, 3.0)[0]
            painter.setPen(QPen(QColor("#0a0d10"), 1.2))
            painter.setBrush(QColor("#252c32"))
            painter.drawRoundedRect(QRectF(base_point.x() - 60 * scale, base_point.y() - 6 * scale, 120 * scale, 13 * scale), 3, 3)
            for ox, w, h in [(-28, 34, 60), (27, 48, 82)]:
                center = point + QPointF(ox * scale, 0)
                painter.setBrush(QColor("#171c20"))
                painter.drawEllipse(QRectF(center.x() - w * scale / 2, center.y() - h * scale / 2, w * scale, h * scale))
                painter.setPen(QPen(QColor(theme.COMPONENT_LENS), 1.2))
                painter.setBrush(QColor(51, 151, 198, 90))
                painter.drawEllipse(QRectF(center.x() - w * scale * 0.32, center.y() - h * scale * 0.38, w * scale * 0.64, h * scale * 0.76))
                painter.setPen(QPen(QColor("#0a0d10"), 1.2))

        elif node.kind == "cylindrical_lens":
            self._draw_post(painter, node, point, scale)
            painter.setPen(QPen(QColor("#0a0d0f"), 2.0))
            painter.setBrush(QColor("#171c20"))
            painter.drawRoundedRect(QRectF(point.x() - 31 * scale, point.y() - 43 * scale, 62 * scale, 86 * scale), 5, 5)
            painter.setPen(QPen(QColor(theme.COMPONENT_LENS), 1.3))
            painter.setBrush(QColor(51, 151, 198, 100))
            painter.drawRoundedRect(QRectF(point.x() - 18 * scale, point.y() - 34 * scale, 36 * scale, 68 * scale), 6, 6)
            painter.setPen(QPen(QColor("#c5e7f5"), 1.3))
            painter.drawLine(point + QPointF(0, -27 * scale), point + QPointF(0, 27 * scale))

        elif node.kind == "fiber":
            base_point = self._project(node.x, node.y, 3.0)[0]
            painter.setPen(QPen(QColor("#0a0d10"), 1.2))
            painter.setBrush(QColor("#252c32"))
            painter.drawRoundedRect(QRectF(base_point.x() - 55 * scale, base_point.y() - 8 * scale, 92 * scale, 18 * scale), 4, 4)
            painter.drawRoundedRect(QRectF(point.x() - 42 * scale, point.y() - 39 * scale, 68 * scale, 67 * scale), 5, 5)
            painter.setBrush(QColor("#11161a"))
            painter.setPen(QPen(QColor("#424b52"), 1.0))
            painter.drawEllipse(QRectF(point.x() - 24 * scale, point.y() - 28 * scale, 48 * scale, 48 * scale))
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(point.x() - 13 * scale, point.y() - 17 * scale, 26 * scale, 26 * scale))
            painter.setBrush(QColor("#8b959c"))
            painter.drawRoundedRect(QRectF(point.x() + 17 * scale, point.y() - 7 * scale, 43 * scale, 14 * scale), 6, 6)
            painter.setBrush(QColor("#050607"))
            painter.drawEllipse(QRectF(point.x() + 50 * scale, point.y() - 5 * scale, 12 * scale, 10 * scale))
            for ox, oy in [(-60, -23), (-29, -53), (15, 34)]:
                self._draw_screen_knob(painter, QRectF(point.x() + ox * scale, point.y() + oy * scale, 17 * scale, 17 * scale))

        else:
            painter.setPen(QPen(QColor("#0a0d10"), 1.2))
            painter.setBrush(body)
            if node.kind == "focus_scan_module":
                base_point = self._project(node.x, node.y, 3.0)[0]
                painter.drawRoundedRect(QRectF(base_point.x() - 62 * scale, base_point.y() - 6 * scale, 124 * scale, 12 * scale), 3, 3)
                painter.setBrush(QColor("#545e65"))
                painter.drawRoundedRect(QRectF(point.x() - 13 * scale, point.y() + 27 * scale, 34 * scale, 13 * scale), 3, 3)
                painter.setBrush(body)
                painter.drawRoundedRect(QRectF(point.x() - 28 * scale, point.y() - 25 * scale, 62 * scale, 54 * scale), 5, 5)
                painter.setBrush(QColor("#050607"))
                painter.drawEllipse(QRectF(point.x() + 25 * scale, point.y() - 15 * scale, 27 * scale, 30 * scale))
            else:
                self._draw_post(painter, node, point, scale)
                if node.kind in {"power_meter", "photodetector"}:
                    painter.drawRoundedRect(QRectF(point.x() - 42 * scale, point.y() - 25 * scale, 70 * scale, 50 * scale), 12, 12)
                    painter.setBrush(QColor("#050607"))
                    painter.drawEllipse(QRectF(point.x() + 18 * scale, point.y() - 17 * scale, 30 * scale, 34 * scale))
                    painter.setBrush(QColor(theme.TEXT_SECONDARY))
                    painter.drawEllipse(QRectF(point.x() + 28 * scale, point.y() - 10 * scale, 16 * scale, 20 * scale))
                elif node.kind == "wavefront_sensor":
                    painter.drawRoundedRect(QRectF(point.x() - 52 * scale, point.y() - 31 * scale, 90 * scale, 62 * scale), 5, 5)
                    painter.setBrush(QColor("#11161a"))
                    painter.drawRoundedRect(QRectF(point.x() + 25 * scale, point.y() - 17 * scale, 28 * scale, 34 * scale), 3, 3)
                    painter.setBrush(QColor(theme.TEXT_SECONDARY))
                    painter.drawRect(QRectF(point.x() + 32 * scale, point.y() - 10 * scale, 14 * scale, 20 * scale))
                else:
                    painter.drawRoundedRect(QRectF(point.x() - 50 * scale, point.y() - 31 * scale, 88 * scale, 62 * scale), 6, 6)
                    painter.setBrush(QColor("#050607"))
                    painter.drawEllipse(QRectF(point.x() + 29 * scale, point.y() - 15 * scale, 25 * scale, 30 * scale))
                    painter.setBrush(QColor("#24333c"))
                    painter.drawRoundedRect(QRectF(point.x() - 38 * scale, point.y() - 18 * scale, 47 * scale, 36 * scale), 3, 3)
        painter.restore()

        label_offset = 55 if node.kind in {"lens", "beam_expander", "cylindrical_lens", "fiber", "mirror", "splitter", "pbs", "half_wave_plate", "beam_sampler"} else 39
        label_rect = QRectF(point.x() - 72, point.y() + label_offset * scale, 144, 25)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(4, 7, 10, 185))
        painter.drawRoundedRect(label_rect, 5, 5)
        painter.setPen(QColor("#f2f5f7" if enabled else "#89939b"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, node.label)
        self._hit_boxes[node.id] = QRectF(point.x() - 65 * scale, point.y() - 62 * scale, 130 * scale, 124 * scale)

        if selected and self._layer_flags["coordinates"]:
            painter.setPen(QPen(QColor("#5bb8e5"), 1.8, Qt.PenStyle.DashLine))
            painter.drawEllipse(QRectF(point.x() - 34, point.y() - 34, 68, 68))

    @staticmethod
    def _title_rect_for_width(width: int) -> QRectF:

        left = 116.0  
        right = max(left, float(width) - 128.0)  
        return QRectF(left, 62.0, right - left, 28.0)

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#182027"))
        self._draw_board(painter)
        if self._model is None:
            return
        self._draw_axis_and_beams(painter)
        self._hit_boxes = {}
        ordered = sorted(
            self._model.nodes.values(),
            key=lambda n: self._project(n.x, n.y, float(n.params.get("z_mm", 82.0)))[1],
            reverse=True,
        )
        for node in ordered:
            if self._layer_flags["structure"] and not self._rays_only:
                self._draw_component(painter, node)
        painter.setPen(QColor("#c6d0d8"))
        painter.drawText(
            self._title_rect_for_width(self.width()),
            Qt.AlignmentFlag.AlignLeft,
            "教学实验平台 · 半实物示意模式",
        )

    def _node_at(self, pos: QPointF) -> str | None:
        for node_id, rect in reversed(list(self._hit_boxes.items())):
            if rect.contains(pos):
                return node_id
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  
        self._last_mouse = event.position()
        node_id = self._node_at(event.position())
        shift_pan = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and shift_pan):
            self._interaction = "pan_camera"
            return
        if event.button() == Qt.MouseButton.LeftButton and node_id is not None and self._model is not None:
            self.objectActivated.emit(node_id)
            self._active_node_id = node_id
            node = self._model.nodes[node_id]
            self._node_origin = (
                node.x,
                node.y,
                float(node.params.get("z_mm", 82.0)),
                node.rotation_deg,
                float(node.params.get("pitch_deg", 0.0)),
            )
            self._interaction = "rotate_node" if event.modifiers() & Qt.KeyboardModifier.ControlModifier else "move_node"
            self._fast_interaction = True
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._interaction = "orbit_camera"
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  
        delta = event.position() - self._last_mouse
        self._last_mouse = event.position()
        if self._interaction == "orbit_camera":
            self._azimuth = (self._azimuth + delta.x() * 0.45) % 360.0
            self._elevation = max(-5.0, min(89.0, self._elevation - delta.y() * 0.35))
            self.cameraChanged.emit(*self.camera_state())
            self.update()
            return
        if self._interaction == "pan_camera":
            self._pan += delta
            self.update()
            return
        if self._model is not None and self._active_node_id in self._model.nodes and self._node_origin is not None:
            node = self._model.nodes[self._active_node_id]
            if self._interaction == "move_node":
                scale = max(0.08, self._base_scale())
                az = math.radians(self._azimuth)
                world_x = (math.cos(az) * delta.x() + math.sin(az) * delta.y()) / scale
                world_y = (-math.sin(az) * delta.x() + math.cos(az) * delta.y()) / scale
                node.x = max(45.0, min(base.SCENE_RECT.width() - 45.0, node.x + world_x))
                node.y = max(70.0, min(base.SCENE_RECT.height() - 70.0, node.y + world_y))
                self._throttled_drag_repaint()
                return
            if self._interaction == "rotate_node":
                node.rotation_deg = (node.rotation_deg + delta.x() * 0.6) % 360.0
                node.params["pitch_deg"] = max(-89.0, min(89.0, float(node.params.get("pitch_deg", 0.0)) - delta.y() * 0.35))
                self._throttled_drag_repaint()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  
        if self._model is not None and self._active_node_id in self._model.nodes and self._interaction in {"move_node", "rotate_node"}:
            self._model.mark_changed()
            label = "3D移动" if self._interaction == "move_node" else "3D旋转"
            self.objectChanged.emit(self._active_node_id, label)
        self._fast_interaction = False
        self.update()
        self._interaction = None
        self._active_node_id = None
        self._node_origin = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  
        factor = 1.12 if event.angleDelta().y() > 0 else 1.0 / 1.12
        self._zoom = max(0.35, min(4.0, self._zoom * factor))
        self.cameraChanged.emit(*self.camera_state())
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  
        node_id = self._node_at(event.position())
        if node_id:
            self.focus_node(node_id)
        else:
            self.reset_camera()
        event.accept()


class SpatialTeachingWorkbench(base.UnifiedTeachingWorkbench):


    def __init__(self, context, parent=None) -> None:
        
        
        
        base.ExperimentModel = SpatialExperimentModel
        base.ExperimentGraphicsView = SpatialExperimentGraphicsView
        base.Experiment3DView = SpatialExperiment3DView
        super().__init__(context, parent)
        self._connect_mode = False
        self.graphics_view.componentDropped.connect(self._add_component_at)
        self.view_3d.objectChanged.connect(self._on_3d_object_changed)
        self.view_3d.cameraChanged.connect(self._update_camera_status)
        self._create_lens_strip()
        self._create_3d_camera_bar()
        self._refresh_all(preserve_view=True)

    def _create_overlay_buttons(self) -> None:
        super()._create_overlay_buttons()
        self.lens_strip_button = QToolButton(self.overlay_host)
        self.lens_strip_button.setObjectName("teachingOverlayButton")
        self.lens_strip_button.setText("镜组")
        self.lens_strip_button.clicked.connect(self._toggle_lens_strip)
        self.left_buttons.append(self.lens_strip_button)

    def _create_lens_strip(self) -> None:
        self.lens_strip = LensSequenceStrip(self.overlay_host)
        self.lens_strip.hide()
        self.lens_strip.orderChanged.connect(self._reorder_lenses)
        self.lens_strip.addRequested.connect(lambda: self._add_component("lens"))
        self.lens_strip.selectRequested.connect(self._on_node_activated)
        self.lens_strip.enabledRequested.connect(self._set_node_enabled)
        self.lens_strip.removeRequested.connect(self._remove_node_to_tray)

    def _create_3d_camera_bar(self) -> None:
        self.camera_bar = QFrame(self.overlay_host)
        self.camera_bar.setObjectName("teachingCameraBar")
        self.camera_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self.camera_bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        
        
        reset = QToolButton()
        reset.setText("恢复相机")
        reset.clicked.connect(self.view_3d.reset_camera)
        layout.addWidget(reset)
        layout.addSpacing(8)
        for text, key, checked in [
            ("光束包络", "beam", True),
            ("理想参考", "ideal", True),
            ("光轴", "axis", True),
            ("元件坐标", "coordinates", False),
            ("测量区域", "measurement", False),
        ]:
            box = QCheckBox(text)
            box.setChecked(checked)
            box.toggled.connect(lambda value, layer=key: self.view_3d.set_layer_visible(layer, value))
            layout.addWidget(box)
        self.camera_status = QLabel("方位角 35°｜俯仰角 28°｜缩放 1.00×")
        layout.addWidget(self.camera_status)
        self.camera_bar.hide()

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        super()._position_overlays()
        if hasattr(self, "lens_strip"):
            width = max(620, min(self.overlay_host.width() - 240, 1050))
            self.lens_strip.setGeometry((self.overlay_host.width() - width) // 2, max(10, self.overlay_host.height() - 128), width, 70)
            self.lens_strip.raise_()
        if hasattr(self, "camera_bar"):
            width = max(620, min(self.overlay_host.width() - 180, 980))
            self.camera_bar.setGeometry((self.overlay_host.width() - width) // 2, 10, width, 44)
            self.camera_bar.raise_()

    def set_mode(self, mode: str, *, force: bool = False) -> None:
        super().set_mode(mode, force=force)
        descriptions = {
            "standard": "标准实验：固定器材观察光束、测量与原理。",
            "layout": "布局调整：拓扑由空间位置自动计算，可移动现有器材。",
            "free": "自由搭建：从器材托盘摆放、旋转和停用器材，系统自动生成主路与测量支路。",
            "diagnostic": "诊断分析：在同一空间平台中利用仪器证据分析复合失配。",
        }
        self.mode_description.setText(descriptions.get(mode, ""))
        self.model.rebuild_auto_paths()
        if hasattr(self, "lens_strip"):
            self.lens_strip.set_model(self.model)

    def set_view_kind(self, kind: str) -> None:
        super().set_view_kind(kind)
        if hasattr(self, "camera_bar"):
            self.camera_bar.setVisible(self._view_kind == "3d")
            self.camera_bar.raise_()

    def _refresh_views(
        self,
        *,
        preserve_view: bool = True,
        snapshot: base.TeachingSceneSnapshot | None = None,
    ) -> None:
        self.model.rebuild_auto_paths()
        snapshot = snapshot or self.model.scene_snapshot()
        super()._refresh_views(preserve_view=preserve_view, snapshot=snapshot)
        if hasattr(self, "lens_strip"):
            self.lens_strip.set_model(self.model)

    def _focus_selected_node(self) -> None:
        node_id = self.model.selected_node_id
        if not node_id:
            return
        if self._view_kind == "3d":
            self.view_3d.focus_node(node_id)
        else:
            self.graphics_view.focus_node(node_id)

    def _on_node_activated(self, node_id: str) -> None:
        if node_id not in self.model.nodes:
            return
        self.model.selected_node_id = node_id
        self.model.selected_edge_id = None
        self._refresh_views(preserve_view=True)
        self._open_right_drawer("object")

    def _on_edge_activated(self, edge_id: str) -> None:
        
        return

    def _on_node_moved(self, node_id: str, x: float, y: float) -> None:
        if self.model.mode == "standard":
            self._refresh_views(preserve_view=True)
            return
        self.model.move_node(node_id, x, y, record=True)
        self._refresh_all(preserve_view=True)

    def _on_3d_object_changed(self, node_id: str, action: str) -> None:
        if node_id not in self.model.nodes:
            return
        self.model.record(f"{action}{self.model.nodes[node_id].label}；2D、3D和测量结果已同步。")
        self._refresh_all(preserve_view=True)

    def _update_camera_status(self, azimuth: float, elevation: float, zoom: float) -> None:
        if hasattr(self, "camera_status"):
            self.camera_status.setText(f"方位角 {azimuth:.0f}°｜俯仰角 {elevation:.0f}°｜缩放 {zoom:.2f}×")

    def _populate_library_drawer(self) -> None:
        self.left_drawer.clear_body()
        intro = QLabel("从器材托盘拖入平台或双击添加。光路由器材空间位置和方向自动生成，不需要手动连线。")
        intro.setWordWrap(True)
        intro.setObjectName("helperText")
        self.left_drawer.body_layout.addWidget(intro)

        for title, kinds in [
            ("光源与偏振", catalog.SOURCE_POLARIZATION_KINDS),
            ("光路与取样", catalog.ROUTING_SAMPLING_KINDS),
            ("整形与耦合", catalog.SHAPING_COUPLING_KINDS),
        ]:
            group, group_layout = self._group_box(title)
            tray = ComponentTrayList(list(kinds))
            tray.setEnabled(self.model.mode == "free")
            tray.componentRequested.connect(self._add_component)
            group_layout.addWidget(tray)
            self.left_drawer.body_layout.addWidget(group)

        instrument_group, instrument_layout = self._group_box("测量仪器")
        instruments = ComponentTrayList(list(catalog.INSTRUMENT_KINDS))
        instruments.setEnabled(self.model.mode == "free")
        instruments.componentRequested.connect(self._add_component)
        instrument_layout.addWidget(instruments)
        self.left_drawer.body_layout.addWidget(instrument_group)

        actions, action_layout = self._group_box("平台操作")
        standard = QPushButton("恢复标准起始布局")
        standard.setEnabled(self.model.mode == "free")
        standard.clicked.connect(self._reset_free_to_standard)
        action_layout.addWidget(standard)
        clear = QPushButton("清空实验平台")
        clear.setEnabled(self.model.mode == "free")
        clear.clicked.connect(self._clear_free_platform)
        action_layout.addWidget(clear)
        note = QLabel("比较镜组时优先使用“暂时停用”，不必反复删除和重新添加。")
        note.setWordWrap(True)
        note.setObjectName("helperText")
        action_layout.addWidget(note)
        self.left_drawer.body_layout.addWidget(actions)
        self.left_drawer.body_layout.addStretch(1)

    def _populate_settings_drawer(self) -> None:
        super()._populate_settings_drawer()
        
        for button in self.left_drawer.findChildren(QPushButton):
            if button.text() in {"3D视图左转", "3D视图右转"}:
                button.hide()
        camera_group, camera_layout = self._group_box("3D相机与图层")
        grid = QGridLayout()
        presets = [("等轴", "isometric"), ("俯视", "top"), ("正视", "front"), ("侧视", "side"), ("沿主光轴", "main_axis"), ("沿测量支路", "branch")]
        for index, (text, preset) in enumerate(presets):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=preset: self.view_3d.set_view_preset(value))
            grid.addWidget(button, index // 2, index % 2)
        camera_layout.addLayout(grid)
        reset = QPushButton("恢复默认相机")
        reset.clicked.connect(self.view_3d.reset_camera)
        camera_layout.addWidget(reset)
        self.left_drawer.body_layout.addWidget(camera_group)

    def _populate_object_drawer(self) -> None:
        self.model.selected_edge_id = None
        super()._populate_object_drawer()
        node = self.model.nodes.get(self.model.selected_node_id or "")
        if node is None:
            return
        
        layout = self.right_drawer.body_layout
        if layout.count() and layout.itemAt(layout.count() - 1).spacerItem() is not None:
            layout.takeAt(layout.count() - 1)

        state_group, state_layout = self._group_box("空间姿态与状态")
        enabled = QCheckBox("参与当前光路计算")
        enabled.setChecked(_enabled(node))
        enabled.setEnabled(self.model.mode == "free")
        enabled.toggled.connect(lambda value, nid=node.id: self._set_node_enabled(nid, value))
        state_layout.addWidget(enabled)
        form = QFormLayout()
        z_spin = QDoubleSpinBox()
        z_spin.setRange(12.0, 180.0)
        z_spin.setSuffix(" mm")
        z_spin.setValue(float(node.params.get("z_mm", 82.0)))
        z_spin.setEnabled(self.model.mode in {"free", "diagnostic"})
        z_spin.editingFinished.connect(lambda nid=node.id, box=z_spin: self._set_node_height(nid, box.value()))
        form.addRow("光轴高度", z_spin)
        yaw = QDoubleSpinBox()
        yaw.setRange(-360, 360)
        yaw.setSuffix(" °")
        yaw.setValue(node.rotation_deg)
        yaw.setEnabled(self.model.mode in {"free", "diagnostic"})
        yaw.editingFinished.connect(lambda nid=node.id, box=yaw: self._set_node_orientation(nid, yaw=box.value()))
        form.addRow("平台内方向", yaw)
        pitch = QDoubleSpinBox()
        pitch.setRange(-89, 89)
        pitch.setSuffix(" °")
        pitch.setValue(float(node.params.get("pitch_deg", 0.0)))
        pitch.setEnabled(self.model.mode in {"free", "diagnostic"})
        pitch.editingFinished.connect(lambda nid=node.id, box=pitch: self._set_node_orientation(nid, pitch=box.value()))
        form.addRow("俯仰", pitch)
        roll = QDoubleSpinBox()
        roll.setRange(-360, 360)
        roll.setSuffix(" °")
        roll.setValue(float(node.params.get("roll_deg", 0.0)))
        roll.setEnabled(self.model.mode == "free")
        roll.editingFinished.connect(lambda nid=node.id, box=roll: self._set_node_orientation(nid, roll=box.value()))
        form.addRow("滚转", roll)
        state_layout.addLayout(form)
        self.right_drawer.body_layout.addWidget(state_group)

        
        for button in self.right_drawer.findChildren(QPushButton):
            if button.text() == "删除该元件":
                try:
                    button.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                button.setText("移出实验平台")
                button.clicked.connect(lambda checked=False, nid=node.id: self._remove_node_to_tray(nid))
        if node.kind == "lens":
            strip = QPushButton("打开镜组编辑带")
            strip.clicked.connect(self._show_lens_strip)
            self.right_drawer.body_layout.addWidget(strip)
        self.right_drawer.body_layout.addStretch(1)

    def _add_component(self, kind: str) -> None:
        if self.model.mode != "free":
            return
        center = self.graphics_view.mapToScene(self.graphics_view.viewport().rect().center())
        y = base.MAIN_RAIL_Y if kind in base.OPTICAL_TYPES else base.BRANCH_RAIL_Y
        self._add_component_at(kind, center.x(), y)

    def _add_component_at(self, kind: str, x: float, y: float) -> None:
        if self.model.mode != "free":
            return
        rotation = 0.0
        if kind in base.INSTRUMENT_TYPES:
            rotation = 180.0
        self.model.add_node(kind, x, y, rotation_deg=rotation)
        self._refresh_all(preserve_view=True)
        if self.left_drawer.isVisible() and self._left_drawer_key == "library":
            self._populate_library_drawer()

    def _remove_node_to_tray(self, node_id: str) -> None:
        if self.model.mode != "free":
            return
        if self.model.remove_node_to_tray(node_id):
            self.right_drawer.hide()
            self._refresh_all(preserve_view=True)

    def _delete_selected(self) -> None:
        node_id = self.model.selected_node_id
        if node_id:
            self._remove_node_to_tray(node_id)

    def _toggle_connect_mode(self, checked: bool) -> None:
        
        self._connect_mode = False
        self.model.latest_cause = "空间自由搭建不需要手动连接；系统根据位置与姿态自动追迹光路。"
        self._refresh_all(preserve_view=True)

    def _set_node_enabled(self, node_id: str, enabled: bool) -> None:
        self.model.set_node_enabled(node_id, enabled, record=True)
        self._refresh_all(preserve_view=True)

    def _set_node_height(self, node_id: str, z_mm: float) -> None:
        node = self.model.nodes.get(node_id)
        if node is None:
            return
        node.params["z_mm"] = float(z_mm)
        self.model.rebuild_auto_paths()
        self.model.record(f"调整{node.label}的光轴高度。")
        self._refresh_all(preserve_view=True)

    def _set_node_orientation(self, node_id: str, *, yaw: float | None = None, pitch: float | None = None, roll: float | None = None) -> None:
        self.model.set_orientation(node_id, yaw_deg=yaw, pitch_deg=pitch, roll_deg=roll, record=True)
        self._refresh_all(preserve_view=True)

    def _update_node_parameter(self, node_id: str, key: str, value: Any, *, live: bool = False) -> None:
        self.model.update_node_params(node_id, {key: value}, record=not live)
        if live:
            node = self.model.nodes.get(node_id)
            if node:
                self.model.latest_cause = f"调整{node.label}的{key}。"
        self._refresh_all(preserve_view=True)

    def _toggle_lens_strip(self) -> None:
        if self.lens_strip.isVisible():
            self.lens_strip.hide()
        else:
            self._show_lens_strip()

    def _show_lens_strip(self) -> None:
        self.lens_strip.set_model(self.model)
        self.lens_strip.show()
        self.lens_strip.raise_()
        self._position_overlays()

    def _reorder_lenses(self, order: list[str]) -> None:
        self.model.reorder_lenses(order, record=True)
        self._refresh_all(preserve_view=True)

    def _reset_free_to_standard(self) -> None:
        super()._reset_free_to_standard()
        self.model.rebuild_auto_paths()

    def _clear_free_platform(self) -> None:
        
        
        if self.model.mode != "free":
            return
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(self, "清空平台", "确定移出自由搭建平台中的全部器材吗？")
        if answer == QMessageBox.StandardButton.Yes:
            self.model.clear_platform()
            self._refresh_all(preserve_view=True)

    def keyPressEvent(self, event) -> None:  
        if event.key() == Qt.Key.Key_Delete and self.model.mode == "free" and self.model.selected_node_id:
            self._remove_node_to_tray(self.model.selected_node_id)
            event.accept()
            return
        control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if control and event.key() == Qt.Key.Key_Z and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._undo()
            event.accept()
            return
        if (control and event.key() == Qt.Key.Key_Y) or (control and event.modifiers() & Qt.KeyboardModifier.ShiftModifier and event.key() == Qt.Key.Key_Z):
            self._redo()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._on_blank_activated()
            event.accept()
            return
        super().keyPressEvent(event)

    def _apply_local_style(self) -> None:
        super()._apply_local_style()
        self.setStyleSheet(
            self.styleSheet()
            + """
            QFrame#teachingLensSequenceStrip, QFrame#teachingCameraBar {
                background: rgba(248, 252, 254, 238);
                border: 1px solid #a9c2d1;
                border-radius: 8px;
            }
            QFrame#teachingLensSequenceStrip QListWidget {
                background: rgba(255, 255, 255, 205);
                border: 1px solid #c3d5df;
                border-radius: 6px;
            }
            QFrame#teachingCameraBar QToolButton {
                padding: 4px 8px;
            }
            """
        )


__all__ = ["SpatialTeachingWorkbench", "SpatialExperimentModel", "SpatialExperiment3DView"]
