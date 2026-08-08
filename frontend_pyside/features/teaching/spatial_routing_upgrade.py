
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from frontend_pyside.resources import theme_tokens as theme

from . import spatial_workbench as spatial
from . import unified_workbench as base
from . import component_catalog as catalog
from . import experiment_presets


ORIGINAL_EXPERIMENT_MODEL = base.ExperimentModel


MEASUREMENT_KINDS = tuple(catalog.MEASUREMENT_KINDS)
MEASUREMENT_LABELS = {kind: catalog.NODE_LABELS[kind] for kind in MEASUREMENT_KINDS}


@dataclass(frozen=True, slots=True)
class BeamSegmentInfo:
    edge_id: str
    source_id: str
    target_id: str
    angle_deg: float


def _segment_fraction(point: QPointF, start: QPointF, end: QPointF) -> float:
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    length2 = dx * dx + dy * dy
    if length2 <= 1e-9:
        return 0.5
    value = ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length2
    return max(0.08, min(0.92, float(value)))


def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> tuple[float, float]:
    t = _segment_fraction(point, start, end)
    projection = QPointF(start.x() + (end.x() - start.x()) * t, start.y() + (end.y() - start.y()) * t)
    return math.hypot(point.x() - projection.x(), point.y() - projection.y()), t


def _mount_angle_for_reflection(incoming_deg: float, outgoing_deg: float) -> float:


    return (45.0 + 0.5 * (float(incoming_deg) + float(outgoing_deg))) % 180.0


class FlexibleSpatialExperimentModel(spatial.SpatialExperimentModel):


    def __init__(self) -> None:
        self._segment_info: dict[str, BeamSegmentInfo] = {}
        self.active_experiment_key = ""
        super().__init__()

    def _default_params(self, kind: str) -> dict[str, float | str | bool]:
        values = super()._default_params(kind)
        if kind in base.INSTRUMENT_TYPES:
            values.setdefault("beam_attached", False)
            values.setdefault("beam_source_id", "")
            values.setdefault("beam_target_id", "")
            values.setdefault("beam_t", 0.50)
            values.setdefault("follow_beam_orientation", True)
        if kind in {"splitter", "pbs", "beam_sampler"}:
            values.setdefault("split_ratio", float(values.get("monitor_fraction", 0.05)))
            values.setdefault("branch_offset_deg", 90.0)
        return values

    def snapshot(self) -> dict[str, Any]:
        data = super().snapshot()
        data["active_experiment_key"] = self.active_experiment_key
        return data

    def restore(self, snapshot: dict[str, Any], *, reset_history: bool = False) -> None:
        self.active_experiment_key = str(snapshot.get("active_experiment_key", ""))
        super().restore(snapshot, reset_history=reset_history)
        self.rebuild_auto_paths()

    
    @staticmethod
    def _surface_angle(node: base.ExperimentNode) -> float:
        return (float(node.rotation_deg) - 45.0) % 180.0

    @staticmethod
    def _normalize_turn_deg(value: float, default: float = 90.0) -> float:
        turn = float(value)
        if not math.isfinite(turn):
            turn = default
        while turn <= -180.0:
            turn += 360.0
        while turn > 180.0:
            turn -= 360.0
        if abs(turn) < 1.0:
            turn = default if default >= 0.0 else -default
        return turn

    def _mirror_outgoing_angle(self, node: base.ExperimentNode, incoming_deg: float) -> float:
        if "beam_offset_deg" not in node.params:
            surface = self._surface_angle(node)
            return (2.0 * surface - float(incoming_deg)) % 360.0
        turn = self._normalize_turn_deg(float(node.params.get("beam_offset_deg", 90.0)), 90.0)
        outgoing = (float(incoming_deg) + turn) % 360.0
        node.rotation_deg = _mount_angle_for_reflection(incoming_deg, outgoing)
        return outgoing

    def _splitter_branch_angle(self, node: base.ExperimentNode, incoming_deg: float) -> float:
        turn = self._normalize_turn_deg(float(node.params.get("branch_offset_deg", 90.0)), 90.0)
        outgoing = (float(incoming_deg) + turn) % 360.0
        node.rotation_deg = _mount_angle_for_reflection(incoming_deg, outgoing)
        return outgoing

    def _apply_beam_attachments(self) -> None:


        for node in self.nodes.values():
            if node.kind not in base.INSTRUMENT_TYPES or not bool(node.params.get("beam_attached", False)):
                continue
            source = self.nodes.get(str(node.params.get("beam_source_id", "")))
            target = self.nodes.get(str(node.params.get("beam_target_id", "")))
            if source is None or target is None or source.id == node.id or target.id == node.id:
                node.params["beam_attached"] = False
                continue
            t = max(0.08, min(0.92, float(node.params.get("beam_t", 0.5))))
            node.x = source.x + (target.x - source.x) * t
            node.y = source.y + (target.y - source.y) * t
            source_z = float(source.params.get("z_mm", 82.0))
            target_z = float(target.params.get("z_mm", 82.0))
            node.params["z_mm"] = source_z + (target_z - source_z) * t
            if bool(node.params.get("follow_beam_orientation", True)):
                incoming = math.degrees(math.atan2(target.y - source.y, target.x - source.x)) % 360.0
                node.rotation_deg = (incoming + 180.0) % 360.0

    def rebuild_auto_paths(self) -> None:


        if self._suspend_auto:
            return
        self._apply_beam_attachments()
        self.edges.clear()
        self._incident_angles.clear()
        self._auto_path_segments.clear()
        self._segment_info.clear()

        edge_counter = 0
        rays: list[tuple[str, QPointF, float, frozenset[str], int]] = []
        for laser in self.nodes.values():
            if laser.kind == "laser" and spatial._enabled(laser):
                rays.append((laser.id, QPointF(laser.x, laser.y), laser.rotation_deg % 360.0, frozenset({laser.id}), 0))

        
        
        
        visited_states: set[tuple[str, int, int]] = set()
        while rays and edge_counter < 120:
            source_id, origin, angle, visited, depth = rays.pop(0)
            if depth > 18:
                continue
            state_key = (source_id, int(round(angle * 2.0)) % 720, depth)
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
            self._segment_info[edge_id] = BeamSegmentInfo(edge_id, source_id, target.id, angle % 360.0)

            next_visited = frozenset(set(visited) | {target.id})
            if target.kind in base.TERMINAL_TYPES or target.kind == "oscilloscope":
                continue
            target_point = QPointF(target.x, target.y)
            if target.kind == "mirror":
                outgoing = self._mirror_outgoing_angle(target, angle)
                rays.append((target.id, target_point, outgoing, next_visited, depth + 1))
            elif target.kind in {"splitter", "pbs", "beam_sampler"}:
                transmitted = angle % 360.0
                reflected = self._splitter_branch_angle(target, angle)
                rays.append((target.id, target_point, transmitted, next_visited, depth + 1))
                if abs(((reflected - transmitted + 180.0) % 360.0) - 180.0) > 1.0:
                    rays.append((target.id, target_point, reflected, next_visited, depth + 1))
            else:
                rays.append((target.id, target_point, angle % 360.0, next_visited, depth + 1))

        
        reached = ORIGINAL_EXPERIMENT_MODEL.reached_nodes(self) if self.edges else set()
        scopes = [node for node in self.nodes.values() if node.kind == "oscilloscope" and spatial._enabled(node)]
        detectors = [node for node in self.nodes.values() if node.kind == "photodetector" and node.id in reached]
        for scope in scopes:
            if not detectors:
                continue
            detector = min(detectors, key=lambda item: math.hypot(item.x - scope.x, item.y - scope.y))
            if math.hypot(detector.x - scope.x, detector.y - scope.y) <= 310.0:
                edge_counter += 1
                edge_id = f"auto_signal_{edge_counter}"
                self.edges[edge_id] = base.ExperimentEdge(edge_id, detector.id, scope.id)

    def segment_info(self, edge_id: str) -> BeamSegmentInfo | None:
        self.rebuild_auto_paths()
        return self._segment_info.get(edge_id)

    def edge_fraction(self, edge_id: str, point: QPointF) -> float:
        edge = self.edges.get(edge_id)
        if edge is None:
            return 0.5
        source = self.nodes.get(edge.source)
        target = self.nodes.get(edge.target)
        if source is None or target is None:
            return 0.5
        return _segment_fraction(point, QPointF(source.x, source.y), QPointF(target.x, target.y))

    def nearest_beam_segment(
        self,
        point: QPointF,
        *,
        max_distance: float = 72.0,
    ) -> tuple[str, float, float] | None:


        self.rebuild_auto_paths()
        best: tuple[str, float, float] | None = None
        for edge_id in self._segment_info:
            edge = self.edges.get(edge_id)
            if edge is None:
                continue
            source = self.nodes.get(edge.source)
            target = self.nodes.get(edge.target)
            if source is None or target is None:
                continue
            distance, fraction = _distance_to_segment(
                point,
                QPointF(source.x, source.y),
                QPointF(target.x, target.y),
            )
            if distance > float(max_distance):
                continue
            if best is None or distance < best[2]:
                best = (edge_id, fraction, distance)
        return best

    def attach_instrument_to_edge(self, kind: str, edge_id: str, t: float = 0.50) -> str | None:
        if kind not in MEASUREMENT_KINDS:
            return None
        edge = self.edges.get(edge_id)
        if edge is None:
            return None
        source = self.nodes.get(edge.source)
        target = self.nodes.get(edge.target)
        if source is None or target is None:
            return None
        t = max(0.08, min(0.92, float(t)))
        x = source.x + (target.x - source.x) * t
        y = source.y + (target.y - source.y) * t
        incoming = math.degrees(math.atan2(target.y - source.y, target.x - source.x)) % 360.0
        node_id = self.add_node(
            kind,
            x,
            y,
            params={
                "beam_attached": True,
                "beam_source_id": source.id,
                "beam_target_id": target.id,
                "beam_t": t,
                "follow_beam_orientation": True,
            },
            rotation_deg=(incoming + 180.0) % 360.0,
            record=False,
        )
        self.selected_node_id = node_id
        self.selected_edge_id = None
        self.record(f"将{self.nodes[node_id].label}吸附到光束段；接收面已自动对准。")
        return node_id

    def set_attachment_fraction(self, node_id: str, fraction: float, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None or not bool(node.params.get("beam_attached", False)):
            return
        node.params["beam_t"] = max(0.08, min(0.92, float(fraction)))
        self.rebuild_auto_paths()
        if record:
            self.record(f"沿光束移动{node.label}。")

    def detach_instrument(self, node_id: str, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None or node.kind not in base.INSTRUMENT_TYPES:
            return
        node.params["beam_attached"] = False
        node.params["beam_source_id"] = ""
        node.params["beam_target_id"] = ""
        if record:
            self.record(f"解除{node.label}的沿光束吸附，可自由移动和旋转。")

    def move_node(self, node_id: str, x: float, y: float, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is not None and node.kind in base.INSTRUMENT_TYPES and bool(node.params.get("beam_attached", False)):
            source = self.nodes.get(str(node.params.get("beam_source_id", "")))
            target = self.nodes.get(str(node.params.get("beam_target_id", "")))
            if source is not None and target is not None:
                fraction = _segment_fraction(QPointF(float(x), float(y)), QPointF(source.x, source.y), QPointF(target.x, target.y))
                self.set_attachment_fraction(node_id, fraction, record=record)
                return
        super().move_node(node_id, x, y, record=record)

    
    def _replace_with_nodes(self, specs: list[tuple[str, float, float, float, str, dict[str, Any]]], description: str) -> None:
        self._suspend_auto = True
        self.nodes.clear()
        self.edges.clear()
        self._counter = 0
        for kind, x, y, rotation, label, params in specs:
            self.add_node(kind, x, y, label=label, params=params, rotation_deg=rotation, record=False)
        self.selected_node_id = next((node.id for node in self.nodes.values() if node.kind == "lens"), None)
        self.selected_edge_id = None
        self._suspend_auto = False
        self.rebuild_auto_paths()
        self.latest_cause = description
        self.record(description)

    def load_layout_preset(self, preset: str) -> None:
        teaching_preset = experiment_presets.EXPERIMENT_PRESETS.get(str(preset))
        if teaching_preset is not None:
            
            
            self.active_experiment_key = teaching_preset.key
            
            
            
            self.max_system_length_mm = 140.0
            self._replace_with_nodes(list(teaching_preset.specs), teaching_preset.description)
            return
        self.active_experiment_key = ""
        self.max_system_length_mm = 80.0
        main_y = 310.0
        specs: list[tuple[str, float, float, float, str, dict[str, Any]]]
        if preset == "straight":
            specs = [
                ("laser", 110, main_y, 0, "激光器", {}),
                ("isolator", 300, main_y, 0, "光隔离器", {}),
                ("lens", 610, main_y, 0, "L1", {"focal_mm": 50.0}),
                ("lens", 850, main_y, 0, "L2", {"focal_mm": 12.0}),
                ("fiber", 1120, main_y, 180, "五轴光纤架", {}),
                ("power_meter", 1360, main_y, 180, "输出功率计", {"range_mw": 20.0}),
            ]
            text = "载入直线型起始布局；可继续加入反射镜、分束器或测量仪器。"
        elif preset == "l_shape":
            specs = [
                ("laser", 110, 250, 0, "激光器", {}),
                ("isolator", 290, 250, 0, "光隔离器", {}),
                ("mirror", 570, 250, _mount_angle_for_reflection(0, 90), "M1", {}),
                ("lens", 570, 470, 90, "L1", {"focal_mm": 50.0}),
                ("lens", 570, 650, 90, "L2", {"focal_mm": 12.0}),
                ("fiber", 570, 790, 270, "五轴光纤架", {}),
            ]
            text = "载入L形折叠布局；M1的角度决定竖直光路方向。"
        elif preset == "z_shape":
            angle = 34.0
            specs = [
                ("laser", 100, 220, 0, "激光器", {}),
                ("isolator", 280, 220, 0, "光隔离器", {}),
                ("mirror", 500, 220, _mount_angle_for_reflection(0, angle), "M1", {}),
                ("mirror", 860, 463, _mount_angle_for_reflection(angle, 0), "M2", {}),
                ("lens", 1050, 463, 0, "L1", {"focal_mm": 50.0}),
                ("lens", 1240, 463, 0, "L2", {"focal_mm": 12.0}),
                ("fiber", 1440, 463, 180, "五轴光纤架", {}),
            ]
            text = "载入Z形折叠布局；两面反射镜共同完成光束平移。"
        elif preset == "dual_branch":
            specs = [
                ("laser", 100, main_y, 0, "激光器", {}),
                ("isolator", 280, main_y, 0, "光隔离器", {}),
                ("splitter", 470, main_y, 90, "分束器1", {"split_ratio": 0.05}),
                ("splitter", 760, main_y, 0, "分束器2", {"split_ratio": 0.05}),
                ("lens", 960, main_y, 0, "L1", {"focal_mm": 50.0}),
                ("lens", 1160, main_y, 0, "L2", {"focal_mm": 12.0}),
                ("fiber", 1390, main_y, 180, "五轴光纤架", {}),
                ("power_meter", 470, 650, 270, "输入功率计", {"range_mw": 500.0}),
                ("beam_analyzer", 760, 90, 90, "光束分析仪", {}),
            ]
            text = "载入双支路布局；两只分束器分别建立功率和光斑测量支路。"
        else:  
            specs = [
                ("laser", 100, main_y, 0, "激光器", {}),
                ("isolator", 285, main_y, 0, "光隔离器", {}),
                ("splitter", 475, main_y, 90, "分束器", {"split_ratio": 0.05}),
                ("lens", 730, main_y, 0, "L1", {"focal_mm": 50.0}),
                ("lens", 960, main_y, 0, "L2", {"focal_mm": 12.0}),
                ("fiber", 1220, main_y, 180, "五轴光纤架", {}),
                ("power_meter", 475, 650, 270, "输入功率计", {"range_mw": 500.0}),
                ("power_meter", 1450, main_y, 180, "输出功率计", {"range_mw": 20.0}),
            ]
            text = "载入T形监测布局；旋转分束器可以改变采样支路方向。"
        self._replace_with_nodes(specs, text)


class SelectableBeamSegmentItem(base.OpticalConnectionItem):


    segmentActivated = Signal(str, QPointF)

    def __init__(self, *args, placement_active: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.placement_active = bool(placement_active)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setAcceptHoverEvents(True)
        self._hovered = False

    def hoverEnterEvent(self, event) -> None:  
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:  
        self.segmentActivated.emit(self.edge_id, event.scenePos())
        event.accept()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        if self.placement_active or self._hovered:
            painter.setPen(QPen(QColor(theme.PRIMARY), 5.0 if self.placement_active else 3.0, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(self._path())


class FlexibleSpatialGraphicsView(spatial.SpatialExperimentGraphicsView):
    beamSegmentActivated = Signal(str, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._instrument_placement_kind: str | None = None

    def set_instrument_placement_kind(self, kind: str | None) -> None:
        self._instrument_placement_kind = kind if kind in MEASUREMENT_KINDS else None
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if self._instrument_placement_kind else Qt.CursorShape.ArrowCursor)
        if self._model is not None:
            self.set_model(self._model, preserve_view=True)

    def set_model(
        self,
        model: FlexibleSpatialExperimentModel,
        *,
        preserve_view: bool = True,
        snapshot: base.TeachingSceneSnapshot | None = None,
    ) -> None:
        transform = self.transform()
        center_scene = self.mapToScene(self.viewport().rect().center())
        self._model = model
        self.scene_obj.clear()
        self.scene_obj.set_display_layer(self._display_layer)
        self._node_items = {}
        self._edge_items = {}
        scene_snapshot = snapshot or model.scene_snapshot()
        metrics = scene_snapshot.metrics
        reached = set(metrics.reached_node_ids)
        current_radii = scene_snapshot.current_radii
        ideal_radii = scene_snapshot.ideal_radii
        movable = model.mode in {"layout", "free", "diagnostic"}
        for node in model.nodes.values():
            node_movable = movable and not (model.mode == "layout" and node.kind in {"laser", "isolator", "half_wave_plate", "pbs", "splitter"})
            item = spatial.SpatialOpticalNodeItem(node, node_movable, display_layer=self._display_layer)
            item.activated.connect(self.nodeActivated)
            item.positionChanged.connect(self._on_item_position_changed)
            item.movementFinished.connect(self.nodeMoved)
            self.scene_obj.addItem(item)
            self._node_items[node.id] = item
        for edge in model.edges.values():
            source = self._node_items.get(edge.source)
            target = self._node_items.get(edge.target)
            source_node = model.nodes.get(edge.source)
            target_node = model.nodes.get(edge.target)
            if source is None or target is None or source_node is None or target_node is None:
                continue
            if source_node.kind == "photodetector" and target_node.kind == "oscilloscope":
                continue
            active = edge.source in reached and edge.target in reached
            item = SelectableBeamSegmentItem(
                edge,
                source,
                target,
                active,
                False,
                source_radius=current_radii.get(edge.source, 6.0),
                target_radius=current_radii.get(edge.target, 6.0),
                ideal_source_radius=ideal_radii.get(edge.source, 6.0),
                ideal_target_radius=ideal_radii.get(edge.target, 6.0),
                display_layer=self._display_layer,
                placement_active=bool(self._instrument_placement_kind),
            )
            item.segmentActivated.connect(lambda edge_id, point: self.beamSegmentActivated.emit(edge_id, point.x(), point.y()))
            self.scene_obj.addItem(item)
            self._edge_items[edge.id] = item
        if model.selected_node_id in self._node_items:
            self._node_items[model.selected_node_id].setSelected(True)
        if preserve_view and self._initial_fit_done:
            self.setTransform(transform)
            self.centerOn(center_scene)
        else:
            self.fit_full()


class FlexibleSpatial3DView(spatial.SpatialExperiment3DView):
    beamSegmentActivated = Signal(str, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._instrument_placement_kind: str | None = None
        self._beam_screen_segments: dict[str, tuple[QPointF, QPointF]] = {}

    def set_instrument_placement_kind(self, kind: str | None) -> None:
        self._instrument_placement_kind = kind if kind in MEASUREMENT_KINDS else None
        self.setCursor(Qt.CursorShape.CrossCursor if self._instrument_placement_kind else Qt.CursorShape.ArrowCursor)
        self.update()

    def _draw_axis_and_beams(self, painter: QPainter) -> None:
        self._beam_screen_segments = {}
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
        current_radii, _ideal = base.ExperimentGraphicsView._beam_radii(self._model)
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
            self._beam_screen_segments[edge.id] = (a, b)
            if self._instrument_placement_kind:
                painter.setPen(QPen(QColor(76, 187, 236, 105), 18.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(a, b)
            self._draw_beam_segment(
                painter, a, b,
                current_radii.get(source.id, 8.0),
                current_radii.get(target.id, 8.0),
            )

    def _beam_at(self, pos: QPointF) -> tuple[str, float] | None:
        best: tuple[str, float, float] | None = None
        for edge_id, (start, end) in self._beam_screen_segments.items():
            distance, fraction = _distance_to_segment(pos, start, end)
            if distance <= 18.0 and (best is None or distance < best[2]):
                best = (edge_id, fraction, distance)
        return (best[0], best[1]) if best is not None else None

    def mousePressEvent(self, event: QMouseEvent) -> None:  
        if event.button() == Qt.MouseButton.LeftButton and self._instrument_placement_kind:
            hit = self._beam_at(event.position())
            if hit is not None:
                self.beamSegmentActivated.emit(hit[0], hit[1])
                event.accept()
                return
        super().mousePressEvent(event)

    def align_to_selected_beam(self) -> None:
        if self._model is None:
            return
        node = self._model.nodes.get(self._model.selected_node_id or "")
        if node is None:
            return
        source = self._model.nodes.get(str(node.params.get("beam_source_id", "")))
        target = self._model.nodes.get(str(node.params.get("beam_target_id", "")))
        if source is None or target is None:
            return
        angle = math.degrees(math.atan2(target.y - source.y, target.x - source.x))
        self._azimuth = (90.0 - angle) % 360.0
        self._elevation = 0.0
        self._focus = (node.x, node.y, float(node.params.get("z_mm", 82.0)))
        self._pan = QPointF()
        self.cameraChanged.emit(*self.camera_state())
        self.update()


class FlexibleSpatialTeachingWorkbench(spatial.SpatialTeachingWorkbench):


    def __init__(self, context, parent=None) -> None:
        
        
        
        spatial.SpatialExperimentModel = FlexibleSpatialExperimentModel
        spatial.SpatialExperimentGraphicsView = FlexibleSpatialGraphicsView
        spatial.SpatialExperiment3DView = FlexibleSpatial3DView
        self._pending_instrument_kind: str | None = None
        super().__init__(context, parent)
        self.graphics_view.beamSegmentActivated.connect(self._on_2d_beam_segment)
        self.view_3d.beamSegmentActivated.connect(self._on_3d_beam_segment)
        self._create_measurement_placement_hint()
        self._refresh_all(preserve_view=True)

    def _create_measurement_placement_hint(self) -> None:
        self.measurement_hint = QFrame(self.overlay_host)
        self.measurement_hint.setObjectName("teachingMeasurementPlacementHint")
        self.measurement_hint.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self.measurement_hint)
        layout.setContentsMargins(10, 5, 8, 5)
        self.measurement_hint_label = QLabel("请选择一段有效光束")
        layout.addWidget(self.measurement_hint_label)
        cancel = QToolButton()
        cancel.setText("取消")
        cancel.clicked.connect(self._cancel_instrument_placement)
        layout.addWidget(cancel)
        self.measurement_hint.hide()

    def _create_3d_camera_bar(self) -> None:
        super()._create_3d_camera_bar()
        button = QToolButton()
        button.setText("沿当前光束")
        button.clicked.connect(self.view_3d.align_to_selected_beam)
        self.camera_bar.layout().insertWidget(6, button)

    def _position_overlays(self) -> None:
        super()._position_overlays()
        if hasattr(self, "measurement_hint"):
            width = min(430, max(300, self.overlay_host.width() // 3))
            self.measurement_hint.setGeometry((self.overlay_host.width() - width) // 2, 62, width, 38)
            self.measurement_hint.raise_()

    
    def _populate_library_drawer(self) -> None:
        self.left_drawer.clear_body()

        for group_name in experiment_presets.EXPERIMENT_GROUPS:
            presets = experiment_presets.presets_for_group(group_name)
            if not presets:
                continue
            group, group_layout = self._group_box(group_name)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(7)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            for index, preset in enumerate(presets):
                button = QPushButton(preset.label)
                button.setToolTip(preset.description)
                button.setMinimumWidth(0)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.setEnabled(self.model.mode == "free")
                button.clicked.connect(
                    lambda checked=False, value=preset.key: self._load_layout_preset(value)
                )
                grid.addWidget(button, index // 2, index % 2)
            group_layout.addLayout(grid)
            self.left_drawer.body_layout.addWidget(group)

        legacy_group, legacy_layout = self._group_box("基础空间布局")
        legacy_grid = QGridLayout()
        for index, (text, key) in enumerate([
            ("直线型", "straight"), ("L形折叠", "l_shape"),
            ("Z形折叠", "z_shape"), ("T形监测", "t_shape"), ("双支路", "dual_branch"),
        ]):
            button = QPushButton(text)
            button.setEnabled(self.model.mode == "free")
            button.clicked.connect(lambda checked=False, value=key: self._load_layout_preset(value))
            legacy_grid.addWidget(button, index // 2, index % 2)
        legacy_layout.addLayout(legacy_grid)
        self.left_drawer.body_layout.addWidget(legacy_group)

        info_group, info_layout = self._group_box("当前实验逻辑")
        self.experiment_info_label = QLabel("请选择实验预设。")
        self.experiment_info_label.setObjectName("helperText")
        self.experiment_info_label.setWordWrap(True)
        info_layout.addWidget(self.experiment_info_label)
        self.left_drawer.body_layout.addWidget(info_group)
        self._update_experiment_info(getattr(self.model, "active_experiment_key", ""))

        for title, kinds in [
            ("光源与偏振", catalog.SOURCE_POLARIZATION_KINDS),
            ("光路与取样", catalog.ROUTING_SAMPLING_KINDS),
            ("整形与耦合", catalog.SHAPING_COUPLING_KINDS),
        ]:
            group, group_layout = self._group_box(title)
            tray = spatial.ComponentTrayList(list(kinds))
            tray.setEnabled(self.model.mode == "free")
            tray.componentRequested.connect(self._add_component)
            group_layout.addWidget(tray)
            self.left_drawer.body_layout.addWidget(group)

        instrument_group, instrument_layout = self._group_box("测量仪器")
        instruction = QLabel(
            "可将仪器直接拖入2D平台：靠近有效光束时自动吸附并对准，拖到空白处则自由放置；"
            "已放置仪器也可在2D中继续拖动。双击仪器仍可选择2D或3D光束位置。"
        )
        instruction.setWordWrap(True)
        instruction.setObjectName("helperText")
        instrument_layout.addWidget(instruction)
        instruments = spatial.ComponentTrayList(list(MEASUREMENT_KINDS) + ["oscilloscope"])
        instruments.setEnabled(self.model.mode == "free")
        instruments.componentRequested.connect(self._request_instrument_or_scope)
        instrument_layout.addWidget(instruments)
        self.left_drawer.body_layout.addWidget(instrument_group)

        action_group, action_layout = self._group_box("平台操作")
        standard = QPushButton("恢复标准起始布局")
        standard.setEnabled(self.model.mode == "free")
        standard.clicked.connect(self._reset_free_to_standard)
        action_layout.addWidget(standard)
        clear = QPushButton("清空实验平台")
        clear.setEnabled(self.model.mode == "free")
        clear.clicked.connect(self._clear_free_platform)
        action_layout.addWidget(clear)
        self.left_drawer.body_layout.addWidget(action_group)
        self.left_drawer.body_layout.addStretch(1)

    def _update_experiment_info(self, preset_key: str) -> None:
        label = getattr(self, "experiment_info_label", None)
        if label is None:
            return
        preset = experiment_presets.EXPERIMENT_PRESETS.get(str(preset_key))
        if preset is None:
            label.setText("当前为基础自由布局；器件移动、旋转和测量位置在2D/3D中同步。")
            return
        label.setText("\n".join((preset.description, *experiment_presets.metadata_lines(preset))))

    def _load_layout_preset(self, preset: str) -> None:
        if self.model.mode != "free":
            return
        self._cancel_instrument_placement()
        self.model.load_layout_preset(preset)
        self._refresh_all(preserve_view=False)
        self._update_experiment_info(preset)
        if self.left_drawer.isVisible():
            self._populate_library_drawer()

    def _add_component_at(self, kind: str, x: float, y: float) -> None:


        if self.model.mode != "free":
            return
        if kind in MEASUREMENT_KINDS:
            nearest = self.model.nearest_beam_segment(QPointF(float(x), float(y)))
            if nearest is not None:
                edge_id, fraction, _distance = nearest
                node_id = self.model.attach_instrument_to_edge(kind, edge_id, fraction)
                if node_id is not None:
                    self.model.latest_cause = (
                        f"已将{MEASUREMENT_LABELS[kind]}拖入2D平台并吸附到最近光束；"
                        "可继续沿光束拖动。"
                    )
                    self._refresh_all(preserve_view=True)
                    if self.left_drawer.isVisible() and self._left_drawer_key == "library":
                        self._populate_library_drawer()
                    return
            node_id = self.model.add_node(
                kind,
                float(x),
                float(y),
                params={"beam_attached": False},
                rotation_deg=180.0,
            )
            self.model.selected_node_id = node_id
            self.model.latest_cause = (
                f"已将{MEASUREMENT_LABELS[kind]}拖入2D平台空白位置；"
                "可自由拖动，靠近光束后也可重新选择吸附位置。"
            )
            self._refresh_all(preserve_view=True)
            if self.left_drawer.isVisible() and self._left_drawer_key == "library":
                self._populate_library_drawer()
            return
        super()._add_component_at(kind, x, y)

    
    def _request_instrument_or_scope(self, kind: str) -> None:
        if kind == "oscilloscope":
            self._add_component(kind)
            return
        self._begin_instrument_placement(kind)

    def _begin_instrument_placement(self, kind: str) -> None:
        if self.model.mode != "free" or kind not in MEASUREMENT_KINDS:
            return
        self._pending_instrument_kind = kind
        self.graphics_view.set_instrument_placement_kind(kind)
        self.view_3d.set_instrument_placement_kind(kind)
        self.measurement_hint_label.setText(f"放置{MEASUREMENT_LABELS[kind]}：点击一段高亮光束，接收面将自动对准")
        self.measurement_hint.show()
        self.measurement_hint.raise_()
        self.left_drawer.hide()
        self._position_overlays()

    def _cancel_instrument_placement(self) -> None:
        self._pending_instrument_kind = None
        if hasattr(self, "graphics_view"):
            self.graphics_view.set_instrument_placement_kind(None)
        if hasattr(self, "view_3d"):
            self.view_3d.set_instrument_placement_kind(None)
        if hasattr(self, "measurement_hint"):
            self.measurement_hint.hide()

    def _place_pending_instrument(self, edge_id: str, fraction: float) -> None:
        kind = self._pending_instrument_kind
        if kind is None:
            return
        node_id = self.model.attach_instrument_to_edge(kind, edge_id, fraction)
        self._cancel_instrument_placement()
        if node_id:
            self._refresh_all(preserve_view=True)
            self._open_right_drawer("object")

    def _on_2d_beam_segment(self, edge_id: str, x: float, y: float) -> None:
        if self._pending_instrument_kind:
            self._place_pending_instrument(edge_id, self.model.edge_fraction(edge_id, QPointF(x, y)))
            return
        self._show_beam_measurement_menu(edge_id, self.model.edge_fraction(edge_id, QPointF(x, y)))

    def _on_3d_beam_segment(self, edge_id: str, fraction: float) -> None:
        if self._pending_instrument_kind:
            self._place_pending_instrument(edge_id, fraction)
            return
        self._show_beam_measurement_menu(edge_id, fraction)

    def _show_beam_measurement_menu(self, edge_id: str, fraction: float) -> None:
        if self.model.mode != "free":
            return
        menu = QMenu(self)
        title = menu.addAction("在此光束段放置检测仪器")
        title.setEnabled(False)
        menu.addSeparator()
        for kind in MEASUREMENT_KINDS:
            action = menu.addAction(f"＋ {MEASUREMENT_LABELS[kind]}")
            action.triggered.connect(lambda checked=False, value=kind: self._attach_direct(value, edge_id, fraction))
        menu.exec(QCursor.pos())

    def _attach_direct(self, kind: str, edge_id: str, fraction: float) -> None:
        node_id = self.model.attach_instrument_to_edge(kind, edge_id, fraction)
        if node_id:
            self._refresh_all(preserve_view=True)
            self._open_right_drawer("object")

    
    def _populate_object_drawer(self) -> None:
        super()._populate_object_drawer()
        node = self.model.nodes.get(self.model.selected_node_id or "")
        if node is None or node.kind not in base.INSTRUMENT_TYPES or node.kind == "oscilloscope":
            return
        layout = self.right_drawer.body_layout
        if layout.count() and layout.itemAt(layout.count() - 1).spacerItem() is not None:
            layout.takeAt(layout.count() - 1)
        group, group_layout = self._group_box("测量位置")
        attached = bool(node.params.get("beam_attached", False))
        status = QLabel("已吸附到光束，拖动仪器时将沿光束前后移动。" if attached else "自由移动：位置或接收面偏离光束时可能无有效读数。")
        status.setWordWrap(True)
        status.setObjectName("helperText")
        group_layout.addWidget(status)
        if attached:
            row = QHBoxLayout()
            row.addWidget(QLabel("沿光束位置"))
            fraction = QDoubleSpinBox()
            fraction.setRange(8.0, 92.0)
            fraction.setSuffix(" %")
            fraction.setValue(float(node.params.get("beam_t", 0.5)) * 100.0)
            fraction.valueChanged.connect(lambda value, nid=node.id: self._set_attachment_fraction(nid, value / 100.0, live=True))
            fraction.editingFinished.connect(lambda nid=node.id, box=fraction: self._set_attachment_fraction(nid, box.value() / 100.0, live=False))
            row.addWidget(fraction)
            group_layout.addLayout(row)
            detach = QPushButton("解除吸附，改为自由移动")
            detach.clicked.connect(lambda checked=False, nid=node.id: self._detach_instrument(nid))
            group_layout.addWidget(detach)
        else:
            start = QPushButton("重新选择光束位置")
            start.clicked.connect(lambda checked=False, kind=node.kind: self._begin_instrument_placement(kind))
            group_layout.addWidget(start)
        self.right_drawer.body_layout.addWidget(group)
        self.right_drawer.body_layout.addStretch(1)

    def _set_attachment_fraction(self, node_id: str, value: float, *, live: bool) -> None:
        self.model.set_attachment_fraction(node_id, value, record=not live)
        self._refresh_all(preserve_view=True)

    def _detach_instrument(self, node_id: str) -> None:
        self.model.detach_instrument(node_id, record=True)
        self._refresh_all(preserve_view=True)
        self._open_right_drawer("object")

    def set_mode(self, mode: str, *, force: bool = False) -> None:
        super().set_mode(mode, force=force)
        if mode != "free":
            self._cancel_instrument_placement()

    def set_view_kind(self, kind: str) -> None:
        super().set_view_kind(kind)
        self.graphics_view.set_instrument_placement_kind(self._pending_instrument_kind)
        self.view_3d.set_instrument_placement_kind(self._pending_instrument_kind)

    def keyPressEvent(self, event) -> None:  
        if event.key() == Qt.Key.Key_Escape and self._pending_instrument_kind:
            self._cancel_instrument_placement()
            event.accept()
            return
        super().keyPressEvent(event)

    def _apply_local_style(self) -> None:
        super()._apply_local_style()
        self.setStyleSheet(
            self.styleSheet()
            + """
            QFrame#teachingMeasurementPlacementHint {
                background: rgba(233, 247, 253, 245);
                border: 1px solid #1687c5;
                border-radius: 8px;
            }
            QFrame#teachingMeasurementPlacementHint QLabel {
                color: #124d6d;
                font-weight: 600;
            }
            """
        )


__all__ = [
    "FlexibleSpatialTeachingWorkbench",
    "FlexibleSpatialExperimentModel",
    "FlexibleSpatialGraphicsView",
    "FlexibleSpatial3DView",
]
