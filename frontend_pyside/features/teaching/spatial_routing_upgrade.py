
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
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
from frontend_pyside.api.job_client import JobClient
from frontend_pyside.api.simulation_client import SimulationClient

from . import spatial_workbench as spatial
from . import unified_workbench as base
from . import component_catalog as catalog
from . import experiment_presets
from teaching_runtime.physical_scene import (
    TeachingEngineTrace,
    TeachingOpticalEngineBridge,
    TeachingPhysicalNode,
    TeachingPhysicalScene,
    resolve_teaching_optical_params,
)
from teaching_runtime.trace_scheduler import TeachingTraceScheduler


ORIGINAL_EXPERIMENT_MODEL = base.ExperimentModel


MEASUREMENT_KINDS = tuple(catalog.MEASUREMENT_KINDS)
MEASUREMENT_LABELS = {kind: catalog.NODE_LABELS[kind] for kind in MEASUREMENT_KINDS}


@dataclass(frozen=True, slots=True)
class BeamSegmentInfo:
    edge_id: str
    source_id: str | None
    target_id: str | None
    angle_deg: float
    start_x: float
    start_y: float
    start_z_mm: float
    end_x: float
    end_y: float
    end_z_mm: float
    power_fraction: float = 1.0
    path_id: str = ""
    ray_id: str = ""
    is_chief_ray: bool = False
    signature: str = ""
    termination_reason: str = ""

    @property
    def start_point(self) -> QPointF:
        return QPointF(float(self.start_x), float(self.start_y))

    @property
    def end_point(self) -> QPointF:
        return QPointF(float(self.end_x), float(self.end_y))


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
        self._physical_segments: list[BeamSegmentInfo] = []
        self._engine_bridge = TeachingOpticalEngineBridge()
        self._trace_scheduler = TeachingTraceScheduler(self._engine_bridge)
        self._trace_generation = 0
        self._trace_applied_generation = -1
        self._trace_pending_quality = ""
        self._engine_trace_result: TeachingEngineTrace | None = None
        self._engine_trace_errors: tuple[str, ...] = ()
        self._engine_trace_warnings: tuple[str, ...] = ()
        self._engine_trace_elapsed_ms: float = 0.0
        self._engine_trace_metadata: dict[str, Any] = {}
        self._engine_trace_frame = None
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
        if kind in {"lens", "cylindrical_lens"}:
            values.setdefault("optical_model", "physical_surface")
            values.setdefault("material", "N-BK7")
            values.setdefault("diameter_mm", 12.7)
            values.setdefault("center_thickness_mm", 2.0)
            values.setdefault("design_refractive_index", 1.5168)
            values.setdefault("conic1", 0.0)
            values.setdefault("conic2", 0.0)
            values.setdefault("asphere_a2_1", 0.0)
            values.setdefault("asphere_a2_2", 0.0)
            values.setdefault("geometry_source", "focal_derived_physical")
        if kind == "cylindrical_lens":
            # axis_angle_deg 是界面输入，统一表示传统柱面轴（零光焦度方向）。
            values["axis_angle_deg"] = float(values.get("axis_angle_deg", 0.0) or 0.0) % 180.0
            values.setdefault("surface_geometry", "cylindrical")
        if kind == "mirror":
            values.setdefault("diameter_mm", 25.4)
        if kind in {"splitter", "pbs", "beam_sampler"}:
            values.setdefault("diameter_mm", 20.0)
            values.setdefault("split_ratio", float(values.get("monitor_fraction", 0.05)))
            values.setdefault("branch_offset_deg", 90.0)
        if kind == "fiber":
            values.setdefault("diameter_mm", 4.0)
            values.setdefault("mode_field_diameter_um", float(self.receiver_mode_radius_um) * 2.0 if hasattr(self, "receiver_mode_radius_um") else 5.6)
            values.setdefault("na", float(self.receiver_na) if hasattr(self, "receiver_na") else 0.12)
        if kind == "laser":
            values.setdefault("beam_radius_y_mm", float(values.get("beam_radius_mm", 0.72) or 0.72))
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
            segment = next((
                info for info in self._physical_segments
                if info.is_chief_ray and info.source_id == source.id and info.target_id == target.id
            ), None)
            if segment is None:
                # 真实追迹结果里没有该段的被跟踪主光线时保持原位，不再回退到节点间直线插值。
                continue
            node.x = segment.start_x + (segment.end_x - segment.start_x) * t
            node.y = segment.start_y + (segment.end_y - segment.start_y) * t
            node.params["z_mm"] = segment.start_z_mm + (segment.end_z_mm - segment.start_z_mm) * t
            if bool(node.params.get("follow_beam_orientation", True)):
                node.rotation_deg = (segment.angle_deg + 180.0) % 360.0

    def _physical_scene(self, *, generation: int | None = None, quality: str = "settled") -> TeachingPhysicalScene:
        physical_nodes: list[TeachingPhysicalNode] = []
        for node in self.nodes.values():
            physical = TeachingPhysicalNode(
                node_id=node.id,
                kind=node.kind,
                label=node.label,
                scene_x=float(node.x),
                scene_y=float(node.y),
                height_mm=float(node.params.get("z_mm", 82.0)),
                yaw_deg=float(node.rotation_deg),
                pitch_deg=float(node.params.get("pitch_deg", 0.0)),
                roll_deg=float(node.params.get("roll_deg", 0.0)),
                enabled=spatial._enabled(node),
                params=dict(node.params),
            )
            if node.kind in {"lens", "cylindrical_lens"}:
                resolved = resolve_teaching_optical_params(physical)
                physical = TeachingPhysicalNode(
                    node_id=physical.node_id, kind=physical.kind, label=physical.label,
                    scene_x=physical.scene_x, scene_y=physical.scene_y, height_mm=physical.height_mm,
                    yaw_deg=physical.yaw_deg, pitch_deg=physical.pitch_deg, roll_deg=physical.roll_deg,
                    enabled=physical.enabled, params=resolved,
                )
            physical_nodes.append(physical)
        nodes = tuple(physical_nodes)
        return TeachingPhysicalScene(
            nodes=nodes,
            wavelength_nm=float(self.wavelength_nm),
            input_power_mw=float(self.input_power_mw),
            max_system_length_mm=float(self.max_system_length_mm),
            scene_width_units=float(base.SCENE_RECT.width()),
            scene_height_units=float(base.SCENE_RECT.height()),
            generation=int(self._trace_generation if generation is None else generation),
            trace_quality=str(quality),
        )

    def beam_segments(self) -> tuple[BeamSegmentInfo, ...]:
        self.rebuild_auto_paths()
        return tuple(self._physical_segments)

    def engine_trace_status(self) -> dict[str, Any]:
        frame = self._engine_trace_frame
        result = self._engine_trace_result
        return {
            "errors": self._engine_trace_errors,
            "warnings": self._engine_trace_warnings,
            "elapsed_ms": self._engine_trace_elapsed_ms,
            "engine": "OpticalSimulationEngine",
            "analysis": "scene_raytrace",
            "generation": int(self._trace_generation),
            "applied_generation": int(self._trace_applied_generation),
            "pending_quality": str(self._trace_pending_quality),
            "quality": "" if result is None else str(result.quality),
            "sample_count": 0 if result is None else int(result.sample_count),
            "ray_count": 0 if result is None else len(result.rays),
            "metadata": dict(self._engine_trace_metadata),
            "coordinate_frame": None if frame is None else {
                "origin_scene": (frame.laser_scene_x, frame.laser_scene_y, frame.laser_height_mm),
                "laser_yaw_deg": frame.laser_yaw_deg,
                "mm_per_scene_unit": frame.mm_per_scene_unit,
                "axial_shift_mm": frame.axial_shift_mm,
            },
        }

    def node_physical_position_mm(self, node_id: str) -> tuple[float, float, float] | None:
        node = self.nodes.get(node_id)
        frame = self._engine_trace_frame
        if node is None or frame is None:
            return None
        return frame.scene_to_world(node.x, node.y, float(node.params.get("z_mm", 82.0)))

    def _next_trace_generation(self) -> int:
        self._trace_generation += 1
        return int(self._trace_generation)

    def teaching_trace_result(self) -> TeachingEngineTrace | None:
        return self._engine_trace_result

    def resolved_optical_parameters(self, node_id: str) -> dict[str, Any]:
        node = self.nodes.get(node_id)
        if node is None:
            return {}
        physical = TeachingPhysicalNode(
            node_id=node.id, kind=node.kind, label=node.label,
            scene_x=float(node.x), scene_y=float(node.y),
            height_mm=float(node.params.get("z_mm", 82.0)),
            yaw_deg=float(node.rotation_deg),
            pitch_deg=float(node.params.get("pitch_deg", 0.0)),
            roll_deg=float(node.params.get("roll_deg", 0.0)),
            enabled=spatial._enabled(node), params=dict(node.params),
        )
        return resolve_teaching_optical_params(physical)

    def _request_engine_trace(self, quality: str = "settled", *, synchronous: bool = False) -> int:
        if self._suspend_auto:
            return int(self._trace_generation)
        self._apply_beam_attachments()
        generation = self._next_trace_generation()
        scene = self._physical_scene(generation=generation, quality=quality)
        self._trace_pending_quality = str(quality)
        # 当前场景已经提交给完整引擎，避免视图刷新再次提交同一状态。
        self._routing_dirty = False
        if synchronous:
            traced = self._engine_bridge.trace(scene)
            self._apply_engine_trace(traced)
        else:
            self._trace_scheduler.submit(scene, generation=generation, quality=quality)
        return generation

    def request_live_trace(self) -> int:
        return self._request_engine_trace("live", synchronous=False)

    def request_settled_trace(self) -> int:
        return self._request_engine_trace("settled", synchronous=False)

    def poll_trace_update(self) -> bool:
        traced = self._trace_scheduler.poll_latest()
        if traced is None:
            return False
        if int(traced.generation) < int(self._trace_generation):
            return False
        return self._apply_engine_trace(traced)

    def close_trace_scheduler(self) -> None:
        self._trace_scheduler.close()

    def rebuild_auto_paths(self) -> None:
        if self._suspend_auto or not self._routing_dirty:
            return
        # 初次构造需要立刻拥有可用拓扑；之后的交互全部异步执行。
        if self._engine_trace_result is None:
            self._request_engine_trace("settled", synchronous=True)
        else:
            self._request_engine_trace("settled", synchronous=False)

    def _apply_engine_trace(self, traced: TeachingEngineTrace) -> bool:
        if int(traced.generation) < int(self._trace_applied_generation):
            return False
        self._engine_trace_result = traced
        self._trace_applied_generation = int(traced.generation)
        self._trace_pending_quality = "" if int(traced.generation) >= int(self._trace_generation) else self._trace_pending_quality
        self._engine_trace_errors = tuple(traced.errors)
        self._engine_trace_warnings = tuple(traced.warnings)
        self._engine_trace_elapsed_ms = float(traced.elapsed_ms)
        self._engine_trace_metadata = dict(traced.metadata)
        self._engine_trace_frame = traced.frame

        self.edges.clear()
        self._incident_angles.clear()
        self._auto_path_segments.clear()
        self._segment_info.clear()
        self._physical_segments.clear()
        if not traced.success:
            self._routing_dirty = False
            return True

        seen_physical: set[tuple[Any, ...]] = set()
        logical_pairs: dict[tuple[str, str, str], str] = {}
        physical_counter = 0
        edge_counter = 0

        for path in traced.paths:
            points = list(path.points)
            if len(points) < 2:
                continue
            is_chief = str(path.ray_id) == "R00"
            for index in range(len(points) - 1):
                start_point = points[index]
                end_point = points[index + 1]
                dx = float(end_point.scene_x - start_point.scene_x)
                dy = float(end_point.scene_y - start_point.scene_y)
                if math.hypot(dx, dy) <= 1.0e-7 and abs(float(end_point.height_mm - start_point.height_mm)) <= 1.0e-7:
                    continue
                source_id = start_point.node_id if start_point.node_id in self.nodes else None
                target_id = end_point.node_id if end_point.node_id in self.nodes else None
                angle = math.degrees(math.atan2(dy, dx)) % 360.0
                dedupe_key = (
                    str(path.ray_id),
                    round(float(start_point.scene_x), 4), round(float(start_point.scene_y), 4), round(float(start_point.height_mm), 4),
                    round(float(end_point.scene_x), 4), round(float(end_point.scene_y), 4), round(float(end_point.height_mm), 4),
                    source_id, target_id,
                )
                if dedupe_key in seen_physical:
                    continue
                seen_physical.add(dedupe_key)
                physical_counter += 1
                segment_id = f"engine_segment_{physical_counter}"

                logical_edge_id = ""
                # 代表光线用于显示光束，不参与教学拓扑；拓扑只由中心光线定义。
                if is_chief and source_id is not None and target_id is not None and source_id != target_id:
                    logical_key = (source_id, target_id, path.signature[: max(0, index + 1)])
                    logical_edge_id = logical_pairs.get(logical_key, "")
                    if not logical_edge_id:
                        edge_counter += 1
                        logical_edge_id = f"engine_edge_{edge_counter}"
                        logical_pairs[logical_key] = logical_edge_id
                        self.edges[logical_edge_id] = base.ExperimentEdge(logical_edge_id, source_id, target_id)
                        self._incident_angles[target_id] = angle
                        self._auto_path_segments.append((source_id, target_id, angle))

                info = BeamSegmentInfo(
                    edge_id=logical_edge_id or segment_id,
                    source_id=source_id,
                    target_id=target_id,
                    angle_deg=angle,
                    start_x=float(start_point.scene_x),
                    start_y=float(start_point.scene_y),
                    start_z_mm=float(start_point.height_mm),
                    end_x=float(end_point.scene_x),
                    end_y=float(end_point.scene_y),
                    end_z_mm=float(end_point.height_mm),
                    power_fraction=float(path.power_fraction),
                    path_id=str(path.path_id),
                    ray_id=str(path.ray_id),
                    is_chief_ray=bool(is_chief),
                    signature=str(path.signature),
                    termination_reason=str(path.termination_reason if index == len(points) - 2 else ""),
                )
                self._physical_segments.append(info)
                self._segment_info[info.edge_id] = info
                if logical_edge_id:
                    self._segment_info[logical_edge_id] = info

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
        self._routing_dirty = False
        return True

    def segment_info(self, edge_id: str) -> BeamSegmentInfo | None:
        self.rebuild_auto_paths()
        return self._segment_info.get(edge_id)

    def edge_fraction(self, edge_id: str, point: QPointF) -> float:
        info = self.segment_info(edge_id)
        if info is None:
            return 0.5
        return _segment_fraction(point, info.start_point, info.end_point)

    def nearest_beam_segment(
        self,
        point: QPointF,
        *,
        max_distance: float = 72.0,
    ) -> tuple[str, float, float] | None:


        self.rebuild_auto_paths()
        best: tuple[str, float, float] | None = None
        for info in self._physical_segments:
            if info.edge_id not in self.edges:
                continue
            if info.source_id is None or info.target_id is None or info.source_id == info.target_id:
                continue
            distance, fraction = _distance_to_segment(point, info.start_point, info.end_point)
            if distance > float(max_distance):
                continue
            if best is None or distance < best[2]:
                best = (info.edge_id, fraction, distance)
        return best

    def attach_instrument_to_edge(self, kind: str, edge_id: str, t: float = 0.50) -> str | None:
        if kind not in MEASUREMENT_KINDS:
            return None
        edge = self.edges.get(edge_id)
        info = self.segment_info(edge_id)
        if edge is None or info is None:
            return None
        source = self.nodes.get(edge.source)
        target = self.nodes.get(edge.target)
        if source is None or target is None:
            return None
        t = max(0.08, min(0.92, float(t)))
        x = info.start_x + (info.end_x - info.start_x) * t
        y = info.start_y + (info.end_y - info.start_y) * t
        z_mm = info.start_z_mm + (info.end_z_mm - info.start_z_mm) * t
        incoming = info.angle_deg
        node_id = self.add_node(
            kind,
            x,
            y,
            params={
                "beam_attached": True,
                "beam_source_id": source.id,
                "beam_target_id": target.id,
                "beam_t": t,
                "z_mm": z_mm,
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
        self.mark_changed()
        if record:
            self.record(f"沿光束移动{node.label}。")
        else:
            self.request_live_trace()

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
        if node is None:
            return
        if node.kind in base.INSTRUMENT_TYPES and bool(node.params.get("beam_attached", False)):
            source = self.nodes.get(str(node.params.get("beam_source_id", "")))
            target = self.nodes.get(str(node.params.get("beam_target_id", "")))
            if source is not None and target is not None:
                info = next((
                    item for item in self._physical_segments
                    if item.is_chief_ray and item.source_id == source.id and item.target_id == target.id
                ), None)
                if info is None:
                    # 没有真实追迹段时无法计算沿光束位置，保持吸附位置不动。
                    return
                fraction = _segment_fraction(QPointF(float(x), float(y)), info.start_point, info.end_point)
                self.set_attachment_fraction(node_id, fraction, record=record)
                return
        old = (float(node.x), float(node.y))
        node.x = max(45.0, min(base.SCENE_RECT.width() - 45.0, float(x)))
        node.y = max(70.0, min(base.SCENE_RECT.height() - 70.0, float(y)))
        if self.mode == "layout":
            if node.kind in base.OPTICAL_TYPES:
                node.y = base.MAIN_RAIL_Y
            elif node.kind != "oscilloscope":
                node.y = base.BRANCH_RAIL_Y
        changed = abs(old[0] - node.x) > 0.1 or abs(old[1] - node.y) > 0.1
        if not changed:
            return
        self.mark_changed()
        if record:
            self.record(f"移动{node.label}；系统已重新追迹光路。")
        else:
            self.request_live_trace()

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
            self.request_live_trace()

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
            self.request_live_trace()

    def update_node_params(self, node_id: str, changes: dict[str, Any], *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        spatial_changes = dict(changes)
        if "rotation_deg" in spatial_changes:
            node.rotation_deg = float(spatial_changes.pop("rotation_deg")) % 360.0
        node.params.update(spatial_changes)
        if node.kind == "cylindrical_lens":
            if "cylinder_axis_deg" in spatial_changes:
                axis_deg = float(spatial_changes["cylinder_axis_deg"]) % 180.0
            elif "axis_angle_deg" in spatial_changes:
                axis_deg = float(spatial_changes["axis_angle_deg"]) % 180.0
            elif "cylinder_power_axis_deg" in spatial_changes:
                axis_deg = (float(spatial_changes["cylinder_power_axis_deg"]) - 90.0) % 180.0
            else:
                axis_deg = float(node.params.get("cylinder_axis_deg", node.params.get("axis_angle_deg", 0.0)) or 0.0) % 180.0
            node.params["axis_angle_deg"] = axis_deg
            node.params["cylinder_axis_deg"] = axis_deg
            node.params["cylinder_power_axis_deg"] = (axis_deg + 90.0) % 180.0
            node.params["cylinder_axis_definition"] = "zero_power_axis"
        self.mark_changed()
        if record:
            description = "、".join(f"{key}={value}" for key, value in changes.items())
            self.record(f"更新{node.label}：{description}。")
        else:
            self.request_live_trace()

    
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


class PhysicalBeamSegmentItem(QGraphicsObject):
    segmentActivated = Signal(str, QPointF)

    def __init__(
        self,
        info: BeamSegmentInfo,
        *,
        source_radius: float = 6.0,
        target_radius: float = 6.0,
        ideal_source_radius: float | None = None,
        ideal_target_radius: float | None = None,
        display_layer: str = "overlay",
        placement_active: bool = False,
        selectable: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.info = info
        self.edge_id = info.edge_id
        self.source_radius = max(2.0, float(source_radius))
        self.target_radius = max(2.0, float(target_radius))
        self.ideal_source_radius = max(2.0, float(ideal_source_radius if ideal_source_radius is not None else source_radius))
        self.ideal_target_radius = max(2.0, float(ideal_target_radius if ideal_target_radius is not None else target_radius))
        self.display_layer = display_layer if display_layer in base.DISPLAY_LAYER_LABELS else "overlay"
        self.placement_active = bool(placement_active)
        self.selectable = bool(selectable)
        self._hovered = False
        self.setZValue(2.0)
        buttons = Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton if self.selectable else Qt.MouseButton.NoButton
        self.setAcceptedMouseButtons(buttons)
        self.setAcceptHoverEvents(self.selectable)

    def _path(self) -> QPainterPath:
        path = QPainterPath(self.info.start_point)
        path.lineTo(self.info.end_point)
        return path

    def _envelope(self, source_radius: float, target_radius: float) -> QPolygonF | None:
        start = self.info.start_point
        end = self.info.end_point
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1.0e-8:
            return None
        nx, ny = -dy / length, dx / length
        r0 = max(2.0, min(18.0, float(source_radius)))
        r1 = max(2.0, min(18.0, float(target_radius)))
        return QPolygonF([
            QPointF(start.x() + nx * r0, start.y() + ny * r0),
            QPointF(end.x() + nx * r1, end.y() + ny * r1),
            QPointF(end.x() - nx * r1, end.y() - ny * r1),
            QPointF(start.x() - nx * r0, start.y() - ny * r0),
        ])

    def boundingRect(self) -> QRectF:
        margin = max(self.source_radius, self.target_radius, self.ideal_source_radius, self.ideal_target_radius) + 24.0
        return self._path().boundingRect().adjusted(-margin, -margin, margin, margin)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(max(20.0, 2.0 * max(self.source_radius, self.target_radius)))
        return stroker.createStroke(self._path())

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.selectable:
            self.segmentActivated.emit(self.edge_id, event.scenePos())
            event.accept()
            return
        super().mousePressEvent(event)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        start = self.info.start_point
        end = self.info.end_point
        power = max(0.04, min(1.0, float(self.info.power_fraction)))
        alpha = int(34 + 58 * math.sqrt(power))
        polygon = self._envelope(self.source_radius, self.target_radius)
        if polygon is not None:
            gradient = QLinearGradient(start, end)
            gradient.setColorAt(0.0, QColor(255, 74, 74, max(24, alpha - 14)))
            gradient.setColorAt(0.55, QColor(255, 52, 52, alpha))
            gradient.setColorAt(1.0, QColor(255, 104, 104, max(22, alpha - 18)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawPolygon(polygon)
        if self.display_layer in {"principle", "overlay"}:
            ideal = self._envelope(self.ideal_source_radius, self.ideal_target_radius)
            if ideal is not None:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(33, 118, 180, 145), 1.2, Qt.PenStyle.DashLine))
                painter.drawPolygon(ideal)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme.ERROR), 2.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(start, end)
        if self.placement_active or self._hovered:
            painter.setPen(QPen(QColor(theme.PRIMARY), 5.0 if self.placement_active else 3.0, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)


class FlexibleSpatialGraphicsView(spatial.SpatialExperimentGraphicsView):
    beamSegmentActivated = Signal(str, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._instrument_placement_kind: str | None = None
        self._live_trace_timer = QTimer(self)
        self._live_trace_timer.setSingleShot(True)
        self._live_trace_timer.setInterval(35)
        self._live_trace_timer.timeout.connect(self._submit_live_trace)

    def _submit_live_trace(self) -> None:
        model = self._model
        if isinstance(model, FlexibleSpatialExperimentModel):
            model.mark_changed()
            model.request_live_trace()

    def _stop_live_trace_timer(self, *_args) -> None:
        self._live_trace_timer.stop()

    def set_instrument_placement_kind(self, kind: str | None) -> None:
        self._instrument_placement_kind = kind if kind in MEASUREMENT_KINDS else None
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if self._instrument_placement_kind else Qt.CursorShape.ArrowCursor)
        if self._model is not None:
            self.set_model(self._model, preserve_view=True)

    def _on_item_position_changed(self, node_id: str) -> None:
        model = self._model
        item = self._node_items.get(node_id)
        if isinstance(model, FlexibleSpatialExperimentModel) and item is not None and node_id in model.nodes:
            node = model.nodes[node_id]
            node.x = max(45.0, min(base.SCENE_RECT.width() - 45.0, float(item.pos().x())))
            node.y = max(70.0, min(base.SCENE_RECT.height() - 70.0, float(item.pos().y())))
            if model.mode == "layout":
                if node.kind in base.OPTICAL_TYPES:
                    node.y = base.MAIN_RAIL_Y
                elif node.kind != "oscilloscope":
                    node.y = base.BRANCH_RAIL_Y
        if not self._live_trace_timer.isActive():
            self._live_trace_timer.start()
        # 只刷新与移动节点相邻的光路图元；其余静态图元由 DeviceCoordinateCache 提供缓存。
        for edge_id, edge_item in self._edge_items.items():
            info = getattr(edge_item, "info", None)
            if info is not None and (info.source_id == node_id or info.target_id == node_id):
                edge_item.update()

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
            if not node_movable:
                item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
            item.activated.connect(self.nodeActivated)
            item.positionChanged.connect(self._on_item_position_changed)
            item.movementFinished.connect(self._stop_live_trace_timer)
            item.movementFinished.connect(self.nodeMoved)
            self.scene_obj.addItem(item)
            self._node_items[node.id] = item
        for info in model.beam_segments():
            source_id = info.source_id or ""
            target_id = info.target_id or ""
            source_radius = current_radii.get(source_id, current_radii.get(target_id, 6.0))
            target_radius = current_radii.get(target_id, source_radius)
            ideal_source_radius = ideal_radii.get(source_id, ideal_radii.get(target_id, source_radius))
            ideal_target_radius = ideal_radii.get(target_id, ideal_source_radius)
            selectable = info.edge_id in model.edges and source_id != target_id
            item = PhysicalBeamSegmentItem(
                info,
                source_radius=source_radius,
                target_radius=target_radius,
                ideal_source_radius=ideal_source_radius,
                ideal_target_radius=ideal_target_radius,
                display_layer=self._display_layer,
                placement_active=bool(self._instrument_placement_kind and selectable),
                selectable=selectable,
            )
            # 光束图元在拖拽期间几何不变，设备坐标缓存避免逐帧重绘。
            item.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
            if selectable:
                item.segmentActivated.connect(lambda edge_id, point: self.beamSegmentActivated.emit(edge_id, point.x(), point.y()))
            self.scene_obj.addItem(item)
            self._edge_items[info.edge_id] = item
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
        self._live_trace_timer = QTimer(self)
        self._live_trace_timer.setSingleShot(True)
        self._live_trace_timer.setInterval(35)
        self._live_trace_timer.timeout.connect(self._submit_live_trace)

    def _submit_live_trace(self) -> None:
        model = self._model
        if isinstance(model, FlexibleSpatialExperimentModel) and self._interaction in {"move_node", "rotate_node"}:
            model.mark_changed()
            model.request_live_trace()

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
        for info in self._model.beam_segments():
            a = self._project(info.start_x, info.start_y, info.start_z_mm)[0]
            b = self._project(info.end_x, info.end_y, info.end_z_mm)[0]
            selectable = info.edge_id in self._model.edges and info.source_id != info.target_id
            if selectable:
                self._beam_screen_segments[info.edge_id] = (a, b)
            if self._instrument_placement_kind and selectable:
                painter.setPen(QPen(QColor(76, 187, 236, 105), 18.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(a, b)
            source_radius = current_radii.get(info.source_id or "", current_radii.get(info.target_id or "", 8.0))
            target_radius = current_radii.get(info.target_id or "", source_radius)
            self._draw_beam_segment(painter, a, b, source_radius, target_radius)

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

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        interaction_before = self._interaction
        super().mouseMoveEvent(event)
        if interaction_before in {"move_node", "rotate_node"} and not self._live_trace_timer.isActive():
            self._live_trace_timer.start()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._live_trace_timer.stop()
        super().mouseReleaseEvent(event)

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
        self._trace_poll_timer = QTimer(self)
        self._trace_poll_timer.setInterval(33)
        self._trace_poll_timer.timeout.connect(self._poll_engine_trace)
        self._trace_poll_timer.start()
        # 正式仿真：提交后台任务，轮询状态并在完成后展示带来源标注的结果。
        self._formal_job_id = ""
        self._formal_status_text = "未提交正式仿真。"
        self._formal_poll_timer = QTimer(self)
        self._formal_poll_timer.setInterval(700)
        self._formal_poll_timer.timeout.connect(self._poll_formal_job)
        self.context.api_client.completed.connect(self._on_api_completed)
        self.context.api_client.failed.connect(self._on_api_failed)
        # 复场验证：解析复场模式重叠，settle 完成后自动刷新结果。
        self._field_verification_result: dict[str, Any] | None = None
        self._refresh_all(preserve_view=True)

    def _poll_engine_trace(self) -> None:
        if isinstance(self.model, FlexibleSpatialExperimentModel) and self.model.poll_trace_update():
            self._refresh_all(preserve_view=True)
            if self.model.engine_trace_status().get("quality") in {"settled", "formal"}:
                self._auto_field_verification()

    def _run_field_verification(self) -> None:
        model = self.model
        if not isinstance(model, FlexibleSpatialExperimentModel):
            return
        result = model.field_verification()
        self._field_verification_result = result
        efficiency = float(result.get("coupling_efficiency", 0.0))
        model.record(f"完成复场验证：模式重叠耦合效率 {efficiency * 100.0:.1f}%。")
        self._update_field_label()

    def _auto_field_verification(self) -> None:
        self._field_verification_result = self.model.field_verification()
        self._update_field_label()

    def _update_field_label(self) -> None:
        label = getattr(self, "field_result_label", None)
        result = self._field_verification_result
        if label is None:
            return
        if not result or not result.get("ok"):
            label.setText("复场验证：光路未连通，无法计算。")
            return
        efficiency = float(result.get("coupling_efficiency", 0.0))
        side = int(result.get("sample_side", 0))
        lines = [
            f"复场验证 · 解析高斯复场与光纤模场模式重叠（{side}×{side} 采样）",
            f"耦合效率 η = {efficiency * 100.0:.1f}%",
            f"接收面束腰 {float(result['waist_x_um']):.2f}×{float(result['waist_y_um']):.2f} μm"
            f" · 模场半径 {float(result['fiber_mode_radius_um']):.2f} μm",
        ]
        label.setText("\n".join(lines))

    def _submit_formal_simulation(self) -> None:
        model = self.model
        if not isinstance(model, FlexibleSpatialExperimentModel):
            return
        if self._formal_job_id:
            self._formal_status_text = f"已有后台任务 #{self._formal_job_id} 运行中，请等待完成。"
            self._update_formal_label()
            return
        try:
            scene = model._physical_scene(quality="formal")
            project, engine_options = model._engine_bridge.compile_project(scene)
        except Exception as exc:
            self._formal_status_text = f"场景编译失败：{exc}"
            self._update_formal_label()
            return
        request_id = f"teaching-formal-{uuid4().hex[:8]}"
        payload = {
            "request_id": request_id,
            "project": project.model_dump(mode="json"),
            "analyses": ["scene_raytrace"],
            "precision": "high",
            "random_seed": 0,
            "options": dict(engine_options),
        }
        self._formal_status_text = "已提交正式仿真，等待后台任务响应……"
        self._update_formal_label()
        SimulationClient(self.context.api_client).submit(
            f"teaching.formal.submit:{request_id}", payload
        )

    def _poll_formal_job(self) -> None:
        job_id = self._formal_job_id
        if not job_id:
            self._formal_poll_timer.stop()
            return
        JobClient(self.context.api_client).get_status(f"teaching.formal.status:{job_id}", job_id)

    def _on_api_completed(self, key: str, data: object) -> None:
        if not key.startswith("teaching.formal."):
            return
        payload = data.get("data") if isinstance(data, dict) else None
        if key.startswith("teaching.formal.submit:"):
            job_id = str((payload or {}).get("job_id", ""))
            if job_id:
                self._formal_job_id = job_id
                self._formal_status_text = f"正式仿真任务 #{job_id} 已排队，等待完成……"
                self._formal_poll_timer.start()
            else:
                self._formal_status_text = "后台未返回任务编号。"
            self._update_formal_label()
            return
        if key.startswith("teaching.formal.status:"):
            status = str((payload or {}).get("status", ""))
            if status == "completed":
                job_id = self._formal_job_id
                self._formal_poll_timer.stop()
                JobClient(self.context.api_client).get_result(
                    f"teaching.formal.result:{job_id}", job_id
                )
            elif status in {"failed", "cancelled"}:
                self._formal_poll_timer.stop()
                error = (payload or {}).get("error") or {}
                detail = str(error.get("message", "") or "") if isinstance(error, dict) else ""
                self._formal_status_text = f"正式仿真任务已{status}。{detail}"
                self._formal_job_id = ""
                self._update_formal_label()
            return
        if key.startswith("teaching.formal.result:"):
            self._formal_poll_timer.stop()
            self._show_formal_result(payload if isinstance(payload, dict) else {})

    def _on_api_failed(self, key: str, error: str) -> None:
        if not key.startswith("teaching.formal."):
            return
        self._formal_poll_timer.stop()
        self._formal_job_id = ""
        self._formal_status_text = f"后台正式仿真不可用：{str(error)[:120]}"
        self._update_formal_label()

    def _show_formal_result(self, result: dict) -> None:
        metrics = dict(result.get("metrics") or {})
        lines = [f"正式结果 · 后台任务 #{self._formal_job_id} · 完整 optical_core 链路"]
        engine = str(result.get("engine_name", "") or "")
        version = str(result.get("engine_version", "") or "")
        if engine:
            lines.append(f"引擎：{engine}" + (f" v{version}" if version else ""))
        elapsed = result.get("elapsed_ms")
        if elapsed is not None:
            lines.append(f"耗时：{float(elapsed):.0f} ms")
        shown = 0
        for name, value in metrics.items():
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                lines.append(f"{name} = {value}")
                shown += 1
                if shown >= 6:
                    break
        self._formal_job_id = ""
        self._formal_status_text = "\n".join(lines)
        self._update_formal_label()

    def _update_formal_label(self) -> None:
        label = getattr(self, "formal_result_label", None)
        if label is not None:
            label.setText(self._formal_status_text)

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
        field = QPushButton("复场验证（模式重叠）")
        field.setEnabled(self.model.mode == "free")
        field.clicked.connect(self._run_field_verification)
        action_layout.addWidget(field)
        self.field_result_label = QLabel("复场验证：尚未计算。")
        self.field_result_label.setObjectName("helperText")
        self.field_result_label.setWordWrap(True)
        action_layout.addWidget(self.field_result_label)
        self._update_field_label()
        formal = QPushButton("提交正式仿真（后台任务）")
        formal.setEnabled(self.model.mode == "free")
        formal.clicked.connect(self._submit_formal_simulation)
        action_layout.addWidget(formal)
        self.formal_result_label = QLabel(self._formal_status_text)
        self.formal_result_label.setObjectName("helperText")
        self.formal_result_label.setWordWrap(True)
        action_layout.addWidget(self.formal_result_label)
        self.left_drawer.body_layout.addWidget(action_group)
        self.left_drawer.body_layout.addStretch(1)

    def _on_node_moved(self, node_id: str, x: float, y: float) -> None:
        if self.model.mode == "standard" or node_id not in self.model.nodes:
            self._refresh_views(preserve_view=True)
            return
        node = self.model.nodes[node_id]
        if node.kind in base.INSTRUMENT_TYPES and bool(node.params.get("beam_attached", False)):
            self.model.move_node(node_id, x, y, record=True)
        else:
            node.x = max(45.0, min(base.SCENE_RECT.width() - 45.0, float(x)))
            node.y = max(70.0, min(base.SCENE_RECT.height() - 70.0, float(y)))
            if self.model.mode == "layout":
                if node.kind in base.OPTICAL_TYPES:
                    node.y = base.MAIN_RAIL_Y
                elif node.kind != "oscilloscope":
                    node.y = base.BRANCH_RAIL_Y
            self.model.mark_changed()
            self.model.record(f"移动{node.label}；系统已重新追迹光路。")
        self._refresh_all(preserve_view=True)

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
        if node is None:
            return
        layout = self.right_drawer.body_layout
        if node.kind == "cylindrical_lens":
            if layout.count() and layout.itemAt(layout.count() - 1).spacerItem() is not None:
                layout.takeAt(layout.count() - 1)
            group, group_layout = self._group_box("柱面轴")
            row = QHBoxLayout()
            row.addWidget(QLabel("轴角"))
            axis = QDoubleSpinBox()
            axis.setRange(0.0, 179.9)
            axis.setDecimals(1)
            axis.setSingleStep(1.0)
            axis.setSuffix(" °")
            axis.setValue(float(node.params.get("axis_angle_deg", node.params.get("cylinder_axis_deg", 0.0)) or 0.0) % 180.0)
            axis.setToolTip("柱面轴为零光焦度方向；实际光焦度方向与柱面轴正交。")
            axis.valueChanged.connect(lambda value, nid=node.id: self.model.update_node_params(nid, {"axis_angle_deg": float(value)}, record=False))
            axis.editingFinished.connect(lambda nid=node.id, box=axis: self.model.update_node_params(nid, {"axis_angle_deg": float(box.value())}, record=True))
            row.addWidget(axis)
            group_layout.addLayout(row)
            hint = QLabel("轴角按传统柱面镜定义：沿柱面轴方向无光焦度，光焦度方向 = 轴角 + 90°。")
            hint.setWordWrap(True)
            hint.setObjectName("helperText")
            group_layout.addWidget(hint)
            self.right_drawer.body_layout.addWidget(group)
            self.right_drawer.body_layout.addStretch(1)
            return
        if node.kind not in base.INSTRUMENT_TYPES or node.kind == "oscilloscope":
            return
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

    def closeEvent(self, event) -> None:
        timer = getattr(self, "_trace_poll_timer", None)
        if timer is not None:
            timer.stop()
        formal_timer = getattr(self, "_formal_poll_timer", None)
        if formal_timer is not None:
            formal_timer.stop()
        if isinstance(getattr(self, "model", None), FlexibleSpatialExperimentModel):
            self.model.close_trace_scheduler()
        super().closeEvent(event)

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
