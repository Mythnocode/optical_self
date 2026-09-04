
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsPathItem,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon

from . import spatial_workbench as spatial
from . import unified_workbench as base
from . import component_catalog as catalog
from . import experiment_presets
from frontend_pyside.features.simulation.adapters.formal_results import formal_ray_dataset_from_result
from .experiment_scene import (
    main_rail_y,
    project_formal_rays_2d,
    formal_rays_scene_3d,
    project_scene_node_2d,
)
from .asset_registry import asset_for_kind
from . import scene_style as scene_style
from .formal_physics import TeachingFormalPhysicsController


ORIGINAL_EXPERIMENT_MODEL = base.ExperimentModel


MEASUREMENT_KINDS = tuple(catalog.MEASUREMENT_KINDS)
MEASUREMENT_LABELS = {kind: catalog.NODE_LABELS[kind] for kind in MEASUREMENT_KINDS}


@dataclass(frozen=True, slots=True)
class BeamSegmentInfo:
    edge_id: str
    source_id: str
    target_id: str
    angle_deg: float
    start_x: float = 0.0
    start_y: float = 0.0
    start_z_mm: float = 82.0
    end_x: float = 0.0
    end_y: float = 0.0
    end_z_mm: float = 82.0
    power_fraction: float = 1.0
    is_chief_ray: bool = False


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
        self._formal_physics_revision = -1
        self._formal_rays_mm: tuple[tuple[tuple[float, float, float], ...], ...] = ()
        self._formal_rays_scene: tuple[tuple[tuple[float, float, float], ...], ...] = ()
        self._formal_rays_world: tuple[tuple[tuple[float, float, float], ...], ...] = ()
        self._formal_metrics: dict[str, float] = {}
        self._formal_project: dict[str, Any] = {}
        self._formal_validation_messages: tuple[str, ...] = ()
        self._formal_ccd: dict[str, Any] = {}
        self._formal_ccd_scan: list[dict[str, Any]] = []
        super().__init__()

    def mark_changed(self) -> None:
        super().mark_changed()
        # Any physical edit invalidates the previous formal raytrace.  Rendering
        # must fall back to “pending” rather than reconnecting object centres.
        self._formal_physics_revision = -1
        self._formal_rays_mm = ()
        self._formal_rays_scene = ()
        self._formal_rays_world = ()
        self._formal_metrics = {}
        self._formal_project = {}
        self._formal_validation_messages = ()
        self._formal_ccd = {}
        self._formal_ccd_scan = []

    def set_formal_validation(self, revision: int, messages: list[str] | tuple[str, ...]) -> None:
        if int(revision) != int(self.revision):
            return
        self._formal_validation_messages = tuple(str(item) for item in messages if str(item).strip())
        self._scene_snapshot_cache = None

    def set_formal_physics_result(self, result: dict[str, Any], project: dict[str, Any], revision: int) -> bool:
        if int(revision) != int(self.revision):
            return False
        result = dict(result or {})
        scene_rays = tuple(
            tuple(tuple(float(v) for v in point) for point in ray)
            for ray in (result.get("scene_rays") or ())
            if len(ray) >= 2
        )
        world_rays = tuple(
            tuple(tuple(float(v) for v in point) for point in ray)
            for ray in (result.get("world_rays") or ())
            if len(ray) >= 2
        )
        engine_rays = tuple(
            tuple(tuple(float(v) for v in point) for point in ray)
            for ray in (result.get("engine_rays") or ())
            if len(ray) >= 2
        )
        if not scene_rays and not world_rays and not engine_rays:
            dataset = formal_ray_dataset_from_result(result, dict(project or {}))
            if dataset is None:
                return False
            rays: list[tuple[tuple[float, float, float], ...]] = []
            for ray in dataset.rays:
                if ray.failed:
                    continue
                points = tuple((float(p[0]), float(p[1]), float(p[2])) for p in ray.points_mm)
                if len(points) >= 2:
                    rays.append(points)
            self._formal_rays_mm = tuple(rays)
            self._formal_rays_scene = ()
            self._formal_rays_world = ()
        else:
            self._formal_rays_mm = engine_rays or scene_rays
            self._formal_rays_scene = scene_rays
            self._formal_rays_world = world_rays
        self._formal_metrics = {
            str(key): float(value)
            for key, value in dict(result.get("metrics", {}) or {}).items()
            if isinstance(value, (int, float))
        }
        self._formal_project = dict(project or {})
        self._formal_physics_revision = int(revision)
        self._formal_ccd = dict(result.get("ccd", {}) or {})
        scan = result.get("ccd_scan", [])
        self._formal_ccd_scan = list(scan) if isinstance(scan, list) else []
        self._scene_snapshot_cache = None
        return True

    def instrument_reading(self, node_id: str) -> dict[str, Any]:
        reading = super().instrument_reading(node_id)
        node = self.nodes.get(node_id)
        if node is None or str(getattr(node, "kind", "")) not in {"ccd", "imaging_camera", "camera"}:
            return reading
        if self._formal_physics_revision != self.revision or not self._formal_ccd:
            return reading
        formal = dict(self._formal_ccd)
        if not formal.get("valid"):
            return reading
        reading = dict(reading or {})
        reading.update({
            "valid": True,
            "kind": node.kind,
            "rms_x_um": formal.get("rms_x_um"),
            "rms_y_um": formal.get("rms_y_um"),
            "radial_rms_um": formal.get("radial_rms_um"),
            "centroid_x_um": formal.get("centroid_x_um"),
            "centroid_y_um": formal.get("centroid_y_um"),
            "radius_x_um": formal.get("radius_x_um"),
            "radius_y_um": formal.get("radius_y_um"),
            "center_x_um": formal.get("centroid_x_um"),
            "center_y_um": formal.get("centroid_y_um"),
            "intensity_matrix": formal.get("intensity_matrix"),
            "ccd_scan": list(self._formal_ccd_scan),
            "metric_source": formal.get("metric_source", "正式几何追迹"),
        })
        return reading

    def load_four_lens_json(self, path: str | None = None) -> None:
        """Load Laser→L1..L4→CCD from presets/four_lens.json into OpticalSystem."""
        from pathlib import Path
        import json

        preset_path = Path(path) if path else Path(__file__).resolve().parent / "presets" / "four_lens.json"
        payload = json.loads(preset_path.read_text(encoding="utf-8"))
        self.mode = "free"
        self.nodes.clear()
        self.edges.clear()
        self.active_experiment_key = "four_lens"
        self.wavelength_nm = float(payload.get("wavelength_nm", 780.0) or 780.0)
        self.max_system_length_mm = 120.0
        for item in list(payload.get("components", []) or []):
            kind = str(item.get("kind", ""))
            self.add_node(
                kind,
                float(item.get("x", 0.0)),
                float(item.get("y", 310.0)),
                label=str(item.get("label") or None) or None,
                params=dict(item.get("params") or {}),
                node_id=str(item.get("id") or None) or None,
                record=False,
                rotation_deg=float(item.get("rotation_deg", 0.0) or 0.0),
            )
        # Sequential train: connect laser → lenses → ccd in x order.
        ordered = sorted(self.nodes.values(), key=lambda node: float(node.x))
        for left, right in zip(ordered, ordered[1:]):
            self.add_edge(left.id, right.id, record=False)
        self.sync_optical_system()
        self.record("已载入 four_lens.json：Laser→L1→L2→L3→L4→CCD。")
        self.latest_cause = "四透镜＋CCD 配置已进入统一 OpticalSystem。"

    def _formalized_metrics(self, fallback: base.WorkbenchMetrics) -> base.WorkbenchMetrics:
        return fallback

    def evaluate(self) -> base.WorkbenchMetrics:
        return super().evaluate()

    def scene_snapshot(self) -> base.TeachingSceneSnapshot:
        snapshot = super().scene_snapshot()
        verified = self._formal_physics_revision == self.revision
        blocked = any(str(item).startswith("错误：") for item in self._formal_validation_messages)
        has_fiber = any(node.kind == "fiber" for node in self.nodes.values())
        preview_source = str(getattr(self, "_preview_metrics_source", "") or "")
        return base.TeachingSceneSnapshot(
            revision=snapshot.revision,
            metrics=snapshot.metrics,
            current_radii=snapshot.current_radii,
            ideal_radii=snapshot.ideal_radii,
            formal_rays_mm=self._formal_rays_mm if verified else (),
            formal_rays_scene=self._formal_rays_scene if verified else (),
            formal_rays_world=self._formal_rays_world if verified else (),
            physics_source=("场景光线追迹" if verified else "正式光线已阻止" if blocked else "正式光线待计算"),
            physics_status=("verified" if verified else "blocked" if blocked else "pending"),
            efficiency_source=(
                preview_source if preview_source else
                "教学快速估算" if has_fiber else
                "相机测量模式：耦合效率不适用"
            ),
            efficiency_status=("preview" if has_fiber else "not_applicable"),
            validation_messages=self._formal_validation_messages,
        )

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
        self.record(f"将{self.nodes[node_id].label}关联到所选测量截面。")
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
            self.record(f"取消{node.label}的测量截面关联，可自由移动和旋转。")

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
        laser = next((node for node in self.nodes.values() if node.kind == "laser"), None)
        if laser is not None and isinstance(laser.params.get("wavelength_nm"), (int, float)):
            self.wavelength_nm = float(laser.params["wavelength_nm"])
        self.selected_node_id = next((node.id for node in self.nodes.values() if node.kind == "lens"), None)
        self.selected_edge_id = None
        self._suspend_auto = False
        self.rebuild_auto_paths()
        self.latest_cause = description
        self.record(description)

    def load_layout_preset(self, preset: str) -> None:
        if str(preset) == "four_lens_json":
            self.load_four_lens_json()
            return
        if str(preset) == "minimal_laser_lens_ccd":
            self.active_experiment_key = "minimal_laser_lens_ccd"
            self.max_system_length_mm = 120.0
            self._replace_with_nodes(
                [
                    ("laser", 120, 310, 0, "Laser", {"wavelength_nm": 808.0, "object_distance_mm": 50.0, "beam_radius_mm": 0.72}),
                    ("lens", 420, 310, 0, "Lens001", {"focal_mm": 50.0, "air_gap_after_mm": 50.0, "thickness_mm": 3.0, "material": "N-BK7", "semi_aperture_mm": 12.5, "enabled": True}),
                    ("ccd", 720, 310, 180, "CCD", {"scan_positions_mm": "10,15,17.5,27.5,37.5", "plane_offset_mm": 0.0}),
                ],
                "最小闭环：Laser → Lens f=50 → CCD；光线来自正式几何追迹。",
            )
            return
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



class EngineeringProjectionScene(base.ExperimentScene):
    """Light engineering work surface matching the Quick3D teaching scene.

    Side/top views are orthographic projections of the same ExperimentScene, but
    they do not need identical backgrounds: side view shows the table edge/horizon
    while top view shows the breadboard surface and hole pattern.  Both use the
    exact neutral palette of the Quick3D workbench.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.projection_plane = "side"
        self.reference_rail_y = float(base.MAIN_RAIL_Y)

    def set_reference_rail_y(self, rail_y: float) -> None:
        rail_y = float(rail_y)
        if abs(rail_y - self.reference_rail_y) < 1e-6:
            return
        self.reference_rail_y = rail_y
        self.update()

    def set_projection_plane(self, plane: str) -> None:
        plane = "top" if str(plane).lower() == "top" else "side"
        if plane == self.projection_plane:
            return
        self.projection_plane = plane
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(rect, QColor(scene_style.SCENE_BACKGROUND))
        board = base.SCENE_RECT.adjusted(24, 24, -24, -24)

        if self.projection_plane == "top":
            # Top view is a real orthographic view of the optical breadboard.
            painter.setPen(QPen(QColor(scene_style.TABLE_EDGE), 1.4))
            painter.setBrush(QColor(scene_style.TABLE_SURFACE))
            painter.drawRoundedRect(board, 12, 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(174, 187, 196, 92))
            for x in range(72, 1545, 56):
                for y in range(76, 836, 56):
                    painter.drawEllipse(QPointF(float(x), float(y)), 1.45, 1.45)
        else:
            # Side projection shares the pale Quick3D world background and shows
            # only the optical-table slab below the apparatus.  It must not look
            # like the old dark top-down CAD grid.
            table_top = self.reference_rail_y + 58.0
            table_rect = QRectF(board.left(), table_top, board.width(), max(80.0, board.bottom() - table_top))
            painter.setPen(QPen(QColor(scene_style.TABLE_EDGE), 1.2))
            painter.setBrush(QColor(scene_style.TABLE_SURFACE))
            painter.drawRoundedRect(table_rect, 8, 8)
            painter.setPen(QPen(QColor(scene_style.TABLE_EDGE), 1.0))
            painter.drawLine(QPointF(board.left(), table_top), QPointF(board.right(), table_top))

        # The Quick3D scene has no heavy metal rail running through the optical
        # centres.  Keep only a restrained optical-axis guide; the experiment
        # hardware is visibly supported by the table below.
        axis_color = QColor(scene_style.AXIS)
        axis_color.setAlpha(92)
        painter.setPen(QPen(axis_color, 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(60, self.reference_rail_y), QPointF(1540, self.reference_rail_y))


class ProjectedOpticalNodeItem(spatial.SpatialOpticalNodeItem):
    """2-D orthographic silhouette of the same registered 3-D teaching asset.

    The old 2-D workbench used an independent set of hand-drawn icons.  That made
    a lens/mount, laser or detector look like a different apparatus after switching
    to 3-D.  This item derives its envelope from the *same* asset registry used by
    Quick3D and only simplifies the projection for engineering readability.
    """

    def __init__(self, node: base.ExperimentNode, movable: bool, *, plane: str, display_layer: str = "overlay", parent=None) -> None:
        self.projection_plane = "top" if str(plane).lower() == "top" else "side"
        super().__init__(node, movable, display_layer=display_layer, parent=parent)

    def boundingRect(self) -> QRectF:
        return QRectF(-82.0, -82.0, 164.0, 168.0)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        asset = asset_for_kind(self.kind)
        width = max(22.0, min(106.0, 104.0 * float(asset.pick_scale[0])))
        depth_or_height = float(asset.pick_scale[2] if self.projection_plane == "top" else asset.pick_scale[1])
        height = max(24.0, min(104.0, 104.0 * depth_or_height))

        painter.save()
        if self.projection_plane == "top":
            painter.rotate(float(self.rotation_deg))

        if self.isSelected():
            painter.setPen(QPen(QColor(scene_style.SELECTION), 2.2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(21, 94, 239, 22))
            painter.drawRoundedRect(QRectF(-width/2-8, -height/2-8, width+16, height+16), 8, 8)

        # Use the same mechanical palette and support semantics as Quick3D.
        # Side view preserves the body -> holder -> post -> base chain; top view
        # preserves the body/base footprints and the post centre.
        painter.setPen(QPen(QColor("#111820"), 1.0))
        if self.projection_plane == "side":
            base_y = max(height/2 + 18.0, 47.0)
            painter.setBrush(QColor(scene_style.BASE))
            painter.drawRoundedRect(QRectF(-max(30.0, width*0.48), base_y, max(60.0, width*0.96), 10.0), 2, 2)
            painter.setBrush(QColor(scene_style.POST))
            painter.drawRoundedRect(QRectF(-3.5, height/2-1.0, 7.0, max(8.0, base_y-height/2+2.0)), 2, 2)
            painter.setBrush(QColor(scene_style.FRAME))
            painter.drawRoundedRect(QRectF(-max(12.0, width*0.20), height/2-4.0, max(24.0, width*0.40), 8.0), 2, 2)
        else:
            painter.setBrush(QColor(scene_style.BASE))
            painter.drawRoundedRect(QRectF(-max(28.0, width*0.46), -max(20.0, height*0.42), max(56.0, width*0.92), max(40.0, height*0.84)), 4, 4)
            painter.setBrush(QColor(scene_style.POST))
            painter.drawEllipse(QRectF(-4.0, -4.0, 8.0, 8.0))

        kind = self.kind
        outline = QPen(QColor("#111820"), 1.45)
        optic_pen = QPen(QColor(scene_style.GLASS_EDGE), 1.25)
        optic_brush = QColor(109, 213, 231, 105)

        thin_optics = {"lens", "aperture", "half_wave_plate", "mirror"}
        box_instruments = {"power_meter", "photodetector", "camera", "beam_analyzer", "imaging_camera", "ccd", "focus_scan_module", "wavefront_sensor", "oscilloscope"}

        painter.setPen(outline)
        if kind == "laser":
            body = QRectF(-width, -height/2, max(18.0, width-7.0), height)
            painter.setBrush(QColor(scene_style.LASER_BODY)); painter.drawRoundedRect(body, 5, 5)
            painter.setBrush(QColor(scene_style.FRAME)); painter.drawEllipse(QRectF(-8, -9, 16, 18))
            painter.setBrush(QColor(scene_style.BEAM)); painter.setPen(Qt.PenStyle.NoPen); painter.drawEllipse(QRectF(-2.5, -2.5, 5, 5))
        elif kind == "fiber":
            body = QRectF(-width*0.82, -height*0.42, width*0.72, height*0.84)
            painter.setPen(outline); painter.setBrush(QColor("#252F37")); painter.drawRoundedRect(body, 5, 5)
            painter.setBrush(QColor("#202B33")); painter.drawEllipse(QRectF(-15, -15, 30, 30))
            painter.setPen(optic_pen); painter.setBrush(QColor("#7ED7E7")); painter.drawEllipse(QRectF(-6.5, -6.5, 13, 13))
        elif kind in thin_optics:
            thin = max(10.0, min(18.0, width * 0.30))
            body = QRectF(-thin/2, -height/2, thin, height)
            painter.setBrush(QColor(scene_style.FRAME)); painter.drawRoundedRect(body, 3, 3)
            inner = body.adjusted(3.0, 5.0, -3.0, -5.0)
            if kind == "mirror":
                painter.setPen(QPen(QColor("#98A6B1"), 1.2)); painter.setBrush(QColor(scene_style.MIRROR_FACE))
            elif kind == "aperture":
                painter.setPen(QPen(QColor("#A8E1EA"), 1.1)); painter.setBrush(QColor("#11181D"))
            else:
                painter.setPen(optic_pen); painter.setBrush(optic_brush)
            painter.drawRoundedRect(inner, 2, 2)
        elif kind in {"splitter", "pbs", "beam_sampler"}:
            plate_w = max(18.0, width * 0.58)
            plate_h = max(26.0, height * 0.78)
            body = QRectF(-plate_w/2, -plate_h/2, plate_w, plate_h)
            painter.setBrush(QColor("#28343D")); painter.drawRoundedRect(body, 3, 3)
            painter.setPen(QPen(QColor(scene_style.SPLITTER_GLASS), 1.2)); painter.setBrush(QColor(168, 224, 234, 105))
            inner = body.adjusted(4.0, 4.0, -4.0, -4.0)
            painter.drawRoundedRect(inner, 2, 2); painter.drawLine(inner.bottomLeft(), inner.topRight())
        elif kind == "isolator":
            body = QRectF(-width/2, -height*0.34, width, height*0.68)
            painter.setBrush(QColor("#303943")); painter.drawRoundedRect(body, height*0.28, height*0.28)
            painter.setPen(QPen(QColor("#6B7782"), 1.2)); painter.setBrush(QColor("#121A20")); painter.drawEllipse(QRectF(width*0.25, -height*0.18, height*0.36, height*0.36))
        elif kind == "beam_expander":
            body = QRectF(-width/2, -height*0.33, width, height*0.66)
            painter.setBrush(QColor("#33404A")); painter.drawRoundedRect(body, height*0.26, height*0.26)
            painter.setPen(QPen(QColor("#75CFDC"), 1.2)); painter.setBrush(QColor(117, 207, 220, 88))
            painter.drawEllipse(QRectF(width*0.24, -height*0.20, height*0.40, height*0.40))
        elif kind in box_instruments:
            body = QRectF(-width/2, -height/2, width, height)
            body_color = "#33404A" if kind in {"camera", "beam_analyzer", "imaging_camera", "ccd", "focus_scan_module"} else "#303B44"
            painter.setBrush(QColor(body_color)); painter.drawRoundedRect(body, 5, 5)
            painter.setPen(QPen(QColor("#6FCAD6"), 1.2)); painter.setBrush(QColor("#151D23")); painter.drawEllipse(QRectF(-width/2-5, -9, 18, 18))
        else:
            body = QRectF(-width/2, -height/2, width, height)
            painter.setBrush(QColor(scene_style.BODY)); painter.drawRoundedRect(body, 5, 5)

        painter.restore()

        # 2-D keeps concise engineering annotations, but not the old large card
        # labels.  This preserves identity while the apparatus itself remains the
        # dominant visual, like in 3-D.
        label_y = 62.0 if self.projection_plane == "top" else max(64.0, height/2 + 58.0)
        label_rect = QRectF(-78, label_y, 156, 24)
        painter.setPen(QColor(scene_style.TEXT_SECONDARY if not self.isSelected() else scene_style.TEXT))
        font = painter.font(); font.setBold(self.isSelected())
        painter.setFont(font)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.label)

class FlexibleSpatialGraphicsView(spatial.SpatialExperimentGraphicsView):
    """Engineering projection of the shared ExperimentScene.

    Apparatus comes from the experiment model; *physical light* comes only from
    ``TeachingSceneSnapshot.formal_rays_mm``.  The former automatically snapped
    topology edges are intentionally not rendered as beams.
    """

    beamSegmentActivated = Signal(str, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        old_scene = self.scene_obj
        self.scene_obj = EngineeringProjectionScene(self)
        self.scene_obj.set_display_layer(self._display_layer)
        self.scene_obj.set_projection_plane("side")
        self.setScene(self.scene_obj)
        old_scene.deleteLater()
        self._instrument_placement_kind: str | None = None
        self._projection_plane = "side"
        self._formal_ray_items: list[QGraphicsPathItem] = []
        # Compatibility guard for the former live-trace implementation. Drag
        # motion only updates geometry; a formal trace is requested after the
        # move is committed by the workbench.
        self._live_trace_timer = QTimer(self)
        self._live_trace_timer.setSingleShot(True)

    @property
    def projection_plane(self) -> str:
        return self._projection_plane

    def set_projection_plane(self, plane: str) -> None:
        plane = "top" if str(plane).lower() == "top" else "side"
        if plane == self._projection_plane:
            return
        self._projection_plane = plane
        if hasattr(self.scene_obj, "set_projection_plane"):
            self.scene_obj.set_projection_plane(plane)
        if self._model is not None:
            self.set_model(self._model, preserve_view=True)

    def set_instrument_placement_kind(self, kind: str | None) -> None:
        self._instrument_placement_kind = kind if kind in MEASUREMENT_KINDS else None
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if self._instrument_placement_kind else Qt.CursorShape.ArrowCursor)
        if self._model is not None:
            self.set_model(self._model, preserve_view=True)

    def set_rays_only(self, enabled: bool) -> None:
        self._rays_only = bool(enabled)
        for item in self._node_items.values():
            item.setVisible(not self._rays_only)
        for item in self._formal_ray_items:
            item.setVisible(True)
        self.viewport().update()

    def _add_formal_rays(self, model: FlexibleSpatialExperimentModel, scene_snapshot: base.TeachingSceneSnapshot) -> None:
        scene_rays = tuple(getattr(scene_snapshot, "formal_rays_scene", ()) or ())
        if scene_rays:
            # Free-placement solver already returns scene coordinates.
            projected = []
            for ray in scene_rays:
                if self._projection_plane == "top":
                    projected.append(tuple((float(p[0]), float(p[1])) for p in ray))
                else:
                    rail = main_rail_y(model)
                    projected.append(tuple((float(p[0]), rail - (float(p[2]) - 82.0)) for p in ray))
        else:
            projected = project_formal_rays_2d(
                model,
                scene_snapshot.formal_rays_mm,
                plane=self._projection_plane,
                rail_y=main_rail_y(model),
            )
        for index, ray in enumerate(projected):
            if len(ray) < 2:
                continue
            path = QPainterPath(QPointF(*ray[0]))
            for x, y in ray[1:]:
                path.lineTo(QPointF(x, y))
            glow = QGraphicsPathItem(path)
            glow.setPen(QPen(QColor(217, 72, 1, 46), 6.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            glow.setZValue(2.4)
            glow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.scene_obj.addItem(glow)
            self._formal_ray_items.append(glow)
            item = QGraphicsPathItem(path)
            item.setPen(QPen(QColor(scene_style.BEAM), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            item.setZValue(2.6 + index * 0.001)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.scene_obj.addItem(item)
            self._formal_ray_items.append(item)

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
        self.scene_obj.set_display_layer(self._display_layer)
        # Topology edges remain in the model for experiment structure, history and
        # measurement attachment, but they are not a source of physical light.
        self._edge_items = {}
        # Formal rays are rebuilt on every refresh; remove the previous set
        # explicitly because the scene is no longer cleared wholesale.
        for item in self._formal_ray_items:
            self.scene_obj.removeItem(item)
        self._formal_ray_items = []
        scene_snapshot = snapshot or model.scene_snapshot()
        movable = model.mode in {"layout", "free", "diagnostic"}
        rail_y = main_rail_y(model)
        if hasattr(self.scene_obj, "set_reference_rail_y"):
            self.scene_obj.set_reference_rail_y(rail_y)

        # Side view is a projection of the same canonical world transform.  Hide
        # only off-axis diagnostic instruments that collapse exactly on top of the
        # main train; the physical node still remains in the scene model and
        # reappears in top/3-D views.
        hidden_kinds = set(base.INSTRUMENT_TYPES) | {"photodetector", "camera", "wavefront_sensor", "beam_analyzer"}
        visible_ids = {
            node.id
            for node in model.nodes.values()
            if not (
                self._projection_plane == "side"
                and abs(float(getattr(node, "y", rail_y)) - rail_y) > 70.0
                and str(getattr(node, "kind", "")) in hidden_kinds
            )
        }

        # Reconcile projected node items in place instead of clearing the scene,
        # so a refresh triggered from inside an item's own mouse handler never
        # destroys the item being pressed or dragged.
        for node_id in tuple(self._node_items):
            if node_id not in model.nodes or node_id not in visible_ids:
                item = self._node_items.pop(node_id)
                self.scene_obj.removeItem(item)
                item.deleteLater()

        for node in model.nodes.values():
            if node.id not in visible_ids:
                continue
            projected_x, projected_y = project_scene_node_2d(
                node, plane=self._projection_plane, rail_y=rail_y
            )
            try:
                display_node = replace(node, x=projected_x, y=projected_y)
            except TypeError:
                # Lightweight integration tests and plugin adapters may expose
                # dataclass-compatible node objects without actually using a
                # dataclass.  Project a shallow view copy; never mutate the
                # canonical experiment node merely to draw another plane.
                display_node = copy.copy(node)
                display_node.x = projected_x
                display_node.y = projected_y
            node_movable = movable and self._projection_plane == "top" and not (model.mode == "layout" and node.kind in {"laser", "isolator", "half_wave_plate", "pbs", "splitter"})
            item = self._node_items.get(node.id)
            if item is None or item.kind != node.kind:
                if item is not None:
                    self.scene_obj.removeItem(item)
                    item.deleteLater()
                item = ProjectedOpticalNodeItem(
                    display_node,
                    node_movable,
                    plane=self._projection_plane,
                    display_layer=self._display_layer,
                )
                item.activated.connect(self.nodeActivated)
                item.positionChanged.connect(self._on_item_position_changed)
                item.movementFinished.connect(self.nodeMoved)
                self.scene_obj.addItem(item)
                self._node_items[node.id] = item
            else:
                item.projection_plane = self._projection_plane
                item.update_from_node(
                    display_node,
                    movable=node_movable,
                    display_layer=self._display_layer,
                    show_ports=False,
                )
            item.setSelected(node.id == model.selected_node_id)
            item.setVisible(not self._rays_only)
        self._add_formal_rays(model, scene_snapshot)
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
        rail_y = main_rail_y(self._model)
        if self._layer_flags["axis"]:
            p1 = self._project(60, rail_y, 82)[0]
            p2 = self._project(1540, rail_y, 82)[0]
            painter.setPen(QPen(QColor(185, 199, 211, 72), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(p1, p2)
        if not self._layer_flags.get("beam", True):
            return
        if not self._layer_flags.get("chief_ray", True):
            return
        snapshot = self._snapshot or self._model.scene_snapshot()
        # Same formal raytrace used by the 2-D engineering projection.  If the
        # formal solver has not returned yet, show no physical light instead of
        # reconnecting apparatus centres.
        rays = formal_rays_scene_3d(self._model, snapshot.formal_rays_mm)
        for ray_index, ray in enumerate(rays):
            for segment_index, (start3, end3) in enumerate(zip(ray, ray[1:])):
                a = self._project(*start3)[0]
                b = self._project(*end3)[0]
                key = f"formal:{ray_index}:{segment_index}"
                self._beam_screen_segments[key] = (a, b)
                painter.setPen(QPen(QColor(255, 115, 45, 70), 8.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(a, b)
                painter.setPen(QPen(QColor(theme.CHART_ORANGE), 2.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(a, b)

    def _beam_at(self, pos: QPointF) -> tuple[str, float] | None:
        best: tuple[str, float, float] | None = None
        for edge_id, (start, end) in self._beam_screen_segments.items():
            distance, fraction = _distance_to_segment(pos, start, end)
            if distance <= 18.0 and (best is None or distance < best[2]):
                best = (edge_id, fraction, distance)
        return (best[0], best[1]) if best is not None else None

    def mousePressEvent(self, event: QMouseEvent) -> None:  
        # Physical rays are formal solver output and are not interchangeable with
        # topology edge IDs.  Measurement attachment therefore stays an explicit
        # free-experiment action rather than snapping an instrument to a rendered ray.
        if event.button() == Qt.MouseButton.LeftButton and self._instrument_placement_kind:
            hit = self._beam_at(event.position())
            if hit is not None:
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

    phenomenonRequested = Signal(str)
    sceneStateChanged = Signal(object, object)
    model_class = FlexibleSpatialExperimentModel
    graphics_view_class = FlexibleSpatialGraphicsView

    def __init__(self, context, parent=None) -> None:
        self._pending_instrument_kind: str | None = None
        self._formal_physics: TeachingFormalPhysicsController | None = None
        super().__init__(context, parent)
        self._live_commit_timer = QTimer(self)
        self._live_commit_timer.setSingleShot(True)
        self._live_commit_timer.setInterval(420)
        self._live_commit_timer.timeout.connect(self._commit_pending_live_edit)
        self._pending_live_commit = False
        self.graphics_view.beamSegmentActivated.connect(self._on_2d_beam_segment)
        self.view_3d.beamSegmentActivated.connect(self._on_3d_beam_segment)
        self._create_teaching_navigation()
        self._create_measurement_placement_hint()
        self._formal_physics = TeachingFormalPhysicsController(context, self)
        self._formal_physics.resultReady.connect(self._on_formal_physics_result)
        self._formal_physics.stateChanged.connect(self._on_formal_physics_state)
        self.set_view_kind("3d")
        self._hide_legacy_overlay_controls()
        self._refresh_all(preserve_view=True)

    def _hide_legacy_overlay_controls(self) -> None:
        """Keep the QML teaching controls as the only visible control layer."""
        for name in ("camera_bar", "lens_strip", "measurement_hint"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.hide()
        for name in ("view_control_buttons", "left_buttons", "right_buttons", "rotate_buttons", "nudge_buttons"):
            for button in getattr(self, name, ()):
                button.hide()
        for name in ("experiment_scene_stage", "experiment_analysis_stage", "experiment_record_stage"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.hide()
        if hasattr(self, "view_3d_button"):
            self.view_3d_button.hide()
        # Primary workflow entry points stay visible; only duplicate QML chrome is hidden.
        if hasattr(self, "scheme_menu_button"):
            self.scheme_menu_button.show()
        navigation = self.findChild(QWidget, "teachingExperimentNavigation")
        if navigation is not None:
            navigation.show()
        if hasattr(self, "teaching_physics_status"):
            self.teaching_physics_status.show()

    def _create_overlay_buttons(self) -> None:
        # Keep the canvas rails limited to universal tools. Teaching topics live in
        # the compact semantic navigation above the canvas instead of occupying a
        # fourth text-heavy button on the right edge.
        super()._create_overlay_buttons()

    def _create_teaching_navigation(self) -> None:
        """Expose the five physical mismatch experiments directly.

        The former semantic navigation (phenomenon/diagnosis/model/free) made the
        teaching center behave like a textbook website.  These buttons now load
        a concrete experiment so the learner changes one dominant physical
        quantity first and only opens explanation when needed.
        """
        wrapper = QWidget(self)
        wrapper.setObjectName("teachingExperimentNavigation")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(6)
        specs = [
            ("横向失配", "lateral_scan", "改变光纤横向位置，观察模场中心与耦合效率"),
            ("角度失配", "fiber_angle", "改变光纤端面倾角，观察线性相位与耦合效率"),
            ("尺寸失配", "spherical_expansion", "改变完整 q 参数，观察模场尺寸匹配"),
            ("轴向失配", "axial_defocus", "改变 Z，观察束腰、曲率与耦合效率联动"),
            ("曲率失配", "curvature_matching", "观察尺寸近似一致但波前曲率不同的状态"),
        ]
        nav.addWidget(QLabel("研究变量"))
        self.teaching_mismatch_combo = QComboBox(self)
        self.teaching_mismatch_combo.setObjectName("teachingMismatchCombo")
        for label, preset, tooltip in specs:
            self.teaching_mismatch_combo.addItem(label, preset)
            self.teaching_mismatch_combo.setItemData(self.teaching_mismatch_combo.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)
        self.teaching_mismatch_combo.currentIndexChanged.connect(
            lambda _index: self._select_mismatch_experiment(str(self.teaching_mismatch_combo.currentData() or "lateral_scan"))
        )
        nav.addWidget(self.teaching_mismatch_combo)
        nav.addStretch(1)
        # 原理、曲线和测量不再永久占顶部；统一从“测量与分析”或右侧按需打开。
        self.teaching_principle_button = QToolButton(self)
        self.teaching_principle_button.setText("原理")
        self.teaching_principle_button.clicked.connect(self._open_principle_panel)
        self.teaching_principle_button.hide()
        self.teaching_process_hint = QLabel("")
        self.teaching_process_hint.hide()
        self.teaching_physics_status = QLabel("正式光学：等待计算")
        self.teaching_physics_status.setObjectName("helperText")
        self.teaching_physics_status.setToolTip("只有正式光学引擎返回的代表性光线才会显示为红色光束；场景连接不会冒充物理结果。")
        nav.addWidget(self.teaching_physics_status)
        # 侧视/俯视是同一 ExperimentScene 的语义化工程投影；3D 仍然
        # 使用同一实验状态和同一正式 raytrace，不维护第二套光路。
        if hasattr(self, "view_3d_button"):
            self.view_3d_button.setText("3D")
            nav.addWidget(self.view_3d_button)
        outer.addLayout(nav)
        root = self.layout()
        if isinstance(root, QVBoxLayout):
            root.insertWidget(1, wrapper)
        self._apply_teaching_compact_header()

    def _set_projection_view(self, plane: str) -> None:
        plane = "top" if str(plane).lower() == "top" else "side"
        if hasattr(self, "graphics_view") and hasattr(self.graphics_view, "set_projection_plane"):
            self.graphics_view.set_projection_plane(plane)
        # set_projection_plane() already refreshes the 2-D scene.  Avoid calling
        # set_view_kind() again when 2-D is already active: the duplicate
        # synchronous refresh re-enters the lens strip QListWidget while its
        # previous item delegates are being destroyed on Windows.
        if self._view_kind != "2d":
            super().set_view_kind("2d")
        else:
            self.view_stack.setCurrentIndex(0)
        self.view_2d_button.setChecked(plane == "side")
        if hasattr(self, "view_top_button"):
            self.view_top_button.setChecked(plane == "top")
        if hasattr(self, "view_3d_button"):
            self.view_3d_button.setChecked(False)

    def set_view_kind(self, kind: str) -> None:
        super().set_view_kind(kind)
        if str(kind).lower() == "3d":
            if hasattr(self, "view_top_button"):
                self.view_top_button.setChecked(False)
        else:
            plane = getattr(self.graphics_view, "projection_plane", "side")
            if hasattr(self, "view_2d_button"):
                self.view_2d_button.setChecked(plane == "side")
            if hasattr(self, "view_top_button"):
                self.view_top_button.setChecked(plane == "top")

    def _on_formal_physics_state(self, state: str, message: str) -> None:
        label = getattr(self, "teaching_physics_status", None)
        if label is None:
            return
        prefix = {
            "verified": "正式光学：已验证",
            "running": "正式光学：计算中",
            "pending": "正式光学：等待计算",
            "blocked": "正式光学：已阻止",
            "error": "正式光学：失败",
        }.get(str(state), "正式光学")
        label.setText(prefix)
        label.setToolTip(str(message or prefix) + "。红色光束只来自正式 raytrace；诊断支路若未被正式求解则不会伪造光路。")
        if str(state) == "blocked":
            # Validation is part of the current scene snapshot. Refresh once so
            # the visible result card and principle inspector show the blocker;
            # the controller already marked this revision handled, so this does
            # not resubmit the same invalid scene.
            self._refresh_all(preserve_view=True)

    def _on_formal_physics_result(self, result: object, project: object, revision: int) -> None:
        if self.model.set_formal_physics_result(dict(result or {}), dict(project or {}), int(revision)):
            # Do not mark the model changed here: a solver result belongs to the
            # revision that triggered it and should update both projections/3-D in place.
            self._refresh_all(preserve_view=True, skip_physics_request=True)

    def _refresh_live_preview(self) -> None:
        """Update visible metrics and 3-D scene without formal raytrace or drawer churn."""
        snapshot = self.model.scene_snapshot()
        self._refresh_views(preserve_view=True, snapshot=snapshot)
        metrics = snapshot.metrics
        self.total_metric.setText(f"总效率  {metrics.total_efficiency * 100:.1f}%")
        self.system_metric.setText(f"系统效率 {metrics.system_efficiency * 100:.1f}%")
        self.receiver_metric.setText(f"接收效率 {metrics.receiver_efficiency * 100:.1f}%")
        self.feasible_metric.setText("工程可实现：通过" if metrics.feasible else "工程可实现：需检查")
        self.sceneStateChanged.emit(self.model, snapshot)

    def _commit_pending_live_edit(self) -> None:
        if not self._pending_live_commit:
            return
        self._pending_live_commit = False
        self.model.mark_changed()
        self._refresh_all(preserve_view=True)

    def _schedule_live_commit(self) -> None:
        self._pending_live_commit = True
        self._live_commit_timer.start()

    def _on_node_moved(self, node_id: str, x: float, y: float) -> None:
        if self.model.mode == "standard":
            self._refresh_views(preserve_view=True)
            return
        self.model.selected_node_id = node_id
        self.model.selected_edge_id = None
        self.model.move_node(node_id, x, y, record=True)
        self.model.mark_changed()
        snapshot = self.model.scene_snapshot()
        self._refresh_views(preserve_view=True, snapshot=snapshot)
        metrics = snapshot.metrics
        self.total_metric.setText(f"总效率  {metrics.total_efficiency * 100:.1f}%")
        self.system_metric.setText(f"系统效率 {metrics.system_efficiency * 100:.1f}%")
        self.receiver_metric.setText(f"接收效率 {metrics.receiver_efficiency * 100:.1f}%")
        self.feasible_metric.setText("工程可实现：通过" if metrics.feasible else "工程可实现：需检查")
        for button in self.nudge_buttons:
            button.setEnabled(bool(self.model.selected_node_id))
        for button in self.rotate_buttons:
            button.setEnabled(bool(self.model.selected_node_id))
        self.sceneStateChanged.emit(self.model, snapshot)
        revision = int(self.model.revision)
        if revision != int(getattr(self.model, "_formal_physics_revision", -1)):
            controller = getattr(self, "_formal_physics", None)
            if controller is not None:
                controller.request(self.model)

    def _refresh_all(self, *, preserve_view: bool = True, skip_physics_request: bool = False) -> None:
        super()._refresh_all(preserve_view=preserve_view)
        snapshot = self.model.scene_snapshot()
        self.sceneStateChanged.emit(self.model, snapshot)
        if skip_physics_request:
            return
        revision = int(self.model.revision)
        if revision == int(getattr(self.model, "_formal_physics_revision", -1)):
            return
        controller = getattr(self, "_formal_physics", None)
        if controller is not None:
            controller.request(self.model)

    def closeEvent(self, event) -> None:
        controller = getattr(self, "_formal_physics", None)
        if controller is not None:
            controller.dispose()
            self._formal_physics = None
        super().closeEvent(event)

    def _apply_teaching_compact_header(self) -> None:
        """Remove redundant header prose before narrow screens start clipping controls."""
        compact = self.width() < 900
        hint = getattr(self, "teaching_process_hint", None)
        if hint is not None:
            hint.setVisible(not compact)
        badge = getattr(self, "teaching_badge", None)
        if badge is not None:
            badge.setVisible(not compact)
        # Keep the actual experiment menu and the 2D/3D state controls visible;
        # only redundant explanatory chrome is removed in portrait layouts.
        if hasattr(self, "scheme_menu_button"):
            self.scheme_menu_button.setText("实验库")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_teaching_compact_header()

    def _select_mismatch_experiment(self, preset: str) -> None:
        combo = getattr(self, "teaching_mismatch_combo", None)
        if combo is not None:
            index = combo.findData(str(preset))
            if index >= 0 and combo.currentIndex() != index:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        if self.model.mode != "free":
            self.set_mode("free", force=True)
        self._load_layout_preset(preset)
        if hasattr(self, "experiment_info_label"):
            self.experiment_info_label.setVisible(False)
        if hasattr(self, "right_drawer") and self.right_drawer.isVisible():
            self.right_drawer.hide()
        if self._view_kind == "3d" and hasattr(self, "view_3d"):
            self.view_3d.set_view_preset("paper")

    def _open_principle_panel(self) -> None:
        """Route principle analysis into the unified exploration inspector.

        The old workbench opened a second floating panel with essentially the
        same mismatch visualisation as the exploration lab.  Keeping one
        analysis surface avoids stacked, immovable windows and keeps the bench
        visible beside the explanation.
        """
        selected = "curvature"
        fiber = next((node for node in self.model.nodes.values() if node.kind == "fiber"), None)
        if fiber is not None:
            fp = fiber.params
            candidates = {
                "lateral": math.hypot(float(fp.get("offset_x_um", 0.0)), float(fp.get("offset_y_um", 0.0))) / 3.0,
                "defocus": abs(float(fp.get("offset_z_um", 0.0))) / 50.0,
                "angle": math.hypot(float(fp.get("pitch_mrad", 0.0)), float(fp.get("yaw_mrad", 0.0))) / 20.0,
                "curvature": abs(float(fp.get("curvature_waves", 0.0))) / 0.2,
            }
            if max(candidates.values(), default=0.0) > 0.0:
                selected = max(candidates, key=candidates.get)
        self.phenomenonRequested.emit(f"mismatch:{selected}")

    def _create_measurement_placement_hint(self) -> None:
        self.measurement_hint = QFrame(self.overlay_host)
        self.measurement_hint.setObjectName("teachingMeasurementPlacementHint")
        self.measurement_hint.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self.measurement_hint)
        layout.setContentsMargins(10, 5, 8, 5)
        self.measurement_hint_label = QLabel("请选择一段有效光束")
        layout.addWidget(self.measurement_hint_label)
        cancel = QToolButton()
        cancel.setIcon(icon("close", "#667085", 16))
        cancel.setToolTip("取消放置测量仪器")
        cancel.clicked.connect(self._cancel_instrument_placement)
        layout.addWidget(cancel)
        self.measurement_hint.hide()

    def _create_3d_camera_bar(self) -> None:
        super()._create_3d_camera_bar()

    def _position_overlays(self) -> None:
        super()._position_overlays()
        if hasattr(self, "measurement_hint"):
            width = min(430, max(300, self.overlay_host.width() // 3))
            self.measurement_hint.setGeometry((self.overlay_host.width() - width) // 2, 62, width, 38)
            self.measurement_hint.raise_()

    
    def _populate_library_drawer(self) -> None:
        """Show a compact experiment library; free-build components live one level deeper."""
        self.left_drawer.clear_body()
        title = QLabel("选择实验")
        title.setObjectName("drawerObjectTitle")
        self.left_drawer.body_layout.addWidget(title)
        hint = QLabel("载入一套真实实验状态。失配类型、测量方式和系统配置在实验内部切换，不再拆成十几个入口。")
        hint.setWordWrap(True)
        hint.setObjectName("helperText")
        self.left_drawer.body_layout.addWidget(hint)

        core = [
            ("最小闭环 Laser-Lens-CCD", "minimal_laser_lens_ccd", "拖拽闭环验收：Laser + f50 透镜 + CCD"),
            ("四透镜 four_lens.json", "four_lens_json", "Laser→L1(50)→L2(100)→L3(200)→L4(200)→CCD，含 10–37.5 mm RMS"),
            ("780 nm 四透镜 · LM135C", "lm135c_four_lens_benchmark", "相机接收、五个轴向位置与完整光斑指标基准"),
            ("基础耦合与失配", "common_platform", "横向、角度、尺寸、轴向和曲率失配共享同一实验台"),
            ("五轴耦合装调", "lateral_scan", "XYZ + Tilt/Pitch 装调与耦合最大化"),
            ("光束指向与测量", "dual_mirror_position", "双镜调节，并结合功率/光束/波前测量"),
            ("模场匹配与整形", "spherical_expansion", "q 参数、束腰尺寸与波前曲率匹配"),
            ("耦合系统设计", "coupling_4_lens", "双/三/四透镜配置在实验内部比较"),
        ]
        for label, key, tip in core:
            button = QPushButton(label)
            button.setToolTip(tip)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda checked=False, value=key: self._load_layout_preset(value))
            self.left_drawer.body_layout.addWidget(button)

        free_button = QPushButton("自由实验…")
        free_button.setToolTip("进入元件库，自由添加、移动、旋转器件和测量仪器")
        free_button.clicked.connect(self._populate_free_experiment_tools)
        self.left_drawer.body_layout.addWidget(free_button)

        self.experiment_info_label = QLabel("")
        self.experiment_info_label.setObjectName("helperText")
        self.experiment_info_label.setWordWrap(True)
        self.left_drawer.body_layout.addWidget(self.experiment_info_label)
        self._update_experiment_info(getattr(self.model, "active_experiment_key", ""))
        self.left_drawer.body_layout.addStretch(1)

    def _populate_free_experiment_tools(self) -> None:
        self.left_drawer.clear_body()
        back = QPushButton("← 返回实验库")
        back.clicked.connect(self._populate_library_drawer)
        self.left_drawer.body_layout.addWidget(back)
        hint = QLabel("自由实验：这里才显示完整元件和测量工具。所有操作仍修改同一个实验状态。")
        hint.setWordWrap(True)
        hint.setObjectName("helperText")
        self.left_drawer.body_layout.addWidget(hint)
        for title, kinds in [
            ("光源与偏振", catalog.SOURCE_POLARIZATION_KINDS),
            ("光路与取样", catalog.ROUTING_SAMPLING_KINDS),
            ("整形与耦合", catalog.SHAPING_COUPLING_KINDS),
        ]:
            group, group_layout = self._group_box(title)
            tray = spatial.ComponentTrayList(list(kinds))
            tray.componentRequested.connect(self._add_component)
            group_layout.addWidget(tray)
            self.left_drawer.body_layout.addWidget(group)
        instrument_group, instrument_layout = self._group_box("测量仪器")
        instruments = spatial.ComponentTrayList(list(MEASUREMENT_KINDS) + ["oscilloscope"])
        instruments.componentRequested.connect(self._request_instrument_or_scope)
        instrument_layout.addWidget(instruments)
        self.left_drawer.body_layout.addWidget(instrument_group)
        action_group, action_layout = self._group_box("平台操作")
        standard = QPushButton("恢复标准起始布局")
        standard.clicked.connect(self._reset_free_to_standard)
        action_layout.addWidget(standard)
        clear = QPushButton("清空实验平台")
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
            label.setText("当前为基础自由布局；器件移动、旋转和测量位置在工程视图/3D中同步。")
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
            node_id = self.model.add_node(
                kind,
                float(x),
                float(y),
                params={"beam_attached": False},
                rotation_deg=180.0,
            )
            self.model.selected_node_id = node_id
            self.model.latest_cause = (
                f"已将{MEASUREMENT_LABELS[kind]}放置到当前实验位置；"
                "位置不会自动贴到光束，需要取样时请明确选择测量截面。"
            )
            self._refresh_all(preserve_view=True)
            return
        super()._add_component_at(kind, x, y)

    
    def _request_instrument_or_scope(self, kind: str) -> None:
        self._add_component(kind)

    def _begin_instrument_placement(self, kind: str) -> None:
        if self.model.mode != "free" or kind not in MEASUREMENT_KINDS:
            return
        self._pending_instrument_kind = kind
        self.graphics_view.set_instrument_placement_kind(kind)
        self.view_3d.set_instrument_placement_kind(kind)
        self.measurement_hint_label.setText(f"选择{MEASUREMENT_LABELS[kind]}的测量截面：点击需要取样的高亮光束")
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
        title = menu.addAction("在此测量截面放置检测仪器")
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
        status = QLabel("已关联测量截面；调整截面位置会同步更新取样位置。" if attached else "自由放置：当前未关联测量截面，可能没有有效读数。")
        status.setWordWrap(True)
        status.setObjectName("helperText")
        group_layout.addWidget(status)
        if attached:
            row = QHBoxLayout()
            row.addWidget(QLabel("截面位置"))
            fraction = QDoubleSpinBox()
            fraction.setRange(8.0, 92.0)
            fraction.setSuffix(" %")
            fraction.setValue(float(node.params.get("beam_t", 0.5)) * 100.0)
            fraction.valueChanged.connect(lambda value, nid=node.id: self._set_attachment_fraction(nid, value / 100.0, live=True))
            fraction.editingFinished.connect(lambda nid=node.id, box=fraction: self._set_attachment_fraction(nid, box.value() / 100.0, live=False))
            row.addWidget(fraction)
            group_layout.addLayout(row)
            detach = QPushButton("取消测量截面关联")
            detach.clicked.connect(lambda checked=False, nid=node.id: self._detach_instrument(nid))
            group_layout.addWidget(detach)
        else:
            start = QPushButton("选择测量截面")
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
