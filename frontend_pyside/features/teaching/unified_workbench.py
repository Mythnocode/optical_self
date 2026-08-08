
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
from datetime import datetime
import json
import logging
import math
import random
from typing import Any, Callable

from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.lifecycle import safe_single_shot
from frontend_pyside.shared.components.basic import Badge, PrimaryButton, SecondaryButton

from . import component_catalog as catalog
from .experiment_presets import EXPERIMENT_GROUPS, EXPERIMENT_PRESETS, presets_for_group


_logger = logging.getLogger(__name__)


SCENE_RECT = QRectF(0.0, 0.0, 1600.0, 900.0)
MAIN_RAIL_Y = 430.0
BRANCH_RAIL_Y = 690.0
FOCAL_LIBRARY = (6.0, 8.0, 10.0, 12.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0)

MODE_LABELS = {
    "standard": "标准实验",
    "layout": "布局调整",
    "free": "自由搭建",
    "diagnostic": "诊断分析",
}

DISPLAY_LAYER_LABELS = {
    "platform": "实验台视图",
    "principle": "光学原理视图",
    "overlay": "叠加视图",
}

NODE_LABELS = dict(catalog.NODE_LABELS)
OPTICAL_TYPES = set(catalog.OPTICAL_KINDS)
INSTRUMENT_TYPES = set(catalog.INSTRUMENT_KINDS)
TERMINAL_TYPES = set(catalog.TERMINAL_KINDS)


@dataclass(slots=True)
class ExperimentNode:
    id: str
    kind: str
    label: str
    x: float
    y: float
    rotation_deg: float = 0.0
    params: dict[str, float | str | bool] = field(default_factory=dict)

    def clone(self) -> "ExperimentNode":
        return ExperimentNode(
            id=self.id,
            kind=self.kind,
            label=self.label,
            x=float(self.x),
            y=float(self.y),
            rotation_deg=float(self.rotation_deg),
            params=copy.deepcopy(self.params),
        )


@dataclass(slots=True)
class ExperimentEdge:
    id: str
    source: str
    target: str

    def clone(self) -> "ExperimentEdge":
        return ExperimentEdge(self.id, self.source, self.target)


@dataclass(frozen=True, slots=True)
class WorkbenchMetrics:
    connected: bool
    path_node_ids: tuple[str, ...]
    reached_node_ids: tuple[str, ...]
    lens_count: int
    predicted_waist_um: float
    target_waist_um: float
    system_efficiency: float
    receiver_efficiency: float
    total_efficiency: float
    output_power_mw: float
    feasible: bool
    dominant_issue: str
    explanation: str
    latest_cause: str


@dataclass(frozen=True, slots=True)
class TeachingSceneSnapshot:
    revision: int
    metrics: WorkbenchMetrics
    current_radii: dict[str, float]
    ideal_radii: dict[str, float]


@dataclass(frozen=True, slots=True)
class SavedScheme:
    name: str
    snapshot: dict[str, Any]
    metrics: WorkbenchMetrics


class ExperimentModel:


    def __init__(self) -> None:
        self.mode = "standard"
        self.nodes: dict[str, ExperimentNode] = {}
        self.edges: dict[str, ExperimentEdge] = {}
        self.selected_node_id: str | None = None
        self.selected_edge_id: str | None = None
        self.connect_source_id: str | None = None
        self.input_power_mw = 100.0
        self.wavelength_nm = 808.0
        self.receiver_na = 0.12
        self.receiver_mode_radius_um = 2.80
        self.target_total_efficiency = 0.85
        self.max_system_length_mm = 80.0
        self.min_air_gap_mm = 0.50
        self.latest_cause = "已载入标准实验平台。"
        self.log: list[str] = []
        self.saved_schemes: list[SavedScheme] = []
        self.baseline_snapshot: dict[str, Any] | None = None
        self._history: list[dict[str, Any]] = []
        self._history_index = -1
        self._counter = 0
        self._revision = 0
        self._metrics_cache_revision = -1
        self._metrics_cache: WorkbenchMetrics | None = None
        self._scene_snapshot_cache: TeachingSceneSnapshot | None = None
        self.load_standard(record=False)
        self._reset_history()

    
    @property
    def revision(self) -> int:
        return self._revision

    def mark_changed(self) -> None:
        self._revision += 1
        self._metrics_cache_revision = -1
        self._metrics_cache = None
        self._scene_snapshot_cache = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "nodes": [asdict(node) for node in self.nodes.values()],
            "edges": [asdict(edge) for edge in self.edges.values()],
            "selected_node_id": self.selected_node_id,
            "selected_edge_id": self.selected_edge_id,
            "input_power_mw": self.input_power_mw,
            "wavelength_nm": self.wavelength_nm,
            "receiver_na": self.receiver_na,
            "receiver_mode_radius_um": self.receiver_mode_radius_um,
            "target_total_efficiency": self.target_total_efficiency,
            "max_system_length_mm": self.max_system_length_mm,
            "min_air_gap_mm": self.min_air_gap_mm,
            "latest_cause": self.latest_cause,
            "counter": self._counter,
        }

    def restore(self, snapshot: dict[str, Any], *, reset_history: bool = False) -> None:
        data = copy.deepcopy(snapshot)
        self.mode = str(data.get("mode", self.mode))
        self.nodes = {
            str(item["id"]): ExperimentNode(
                id=str(item["id"]),
                kind=str(item["kind"]),
                label=str(item["label"]),
                x=float(item["x"]),
                y=float(item["y"]),
                rotation_deg=float(item.get("rotation_deg", 0.0)),
                params=copy.deepcopy(item.get("params", {})),
            )
            for item in data.get("nodes", [])
        }
        self.edges = {
            str(item["id"]): ExperimentEdge(str(item["id"]), str(item["source"]), str(item["target"]))
            for item in data.get("edges", [])
            if str(item.get("source")) in self.nodes and str(item.get("target")) in self.nodes
        }
        self.selected_node_id = data.get("selected_node_id") if data.get("selected_node_id") in self.nodes else None
        self.selected_edge_id = data.get("selected_edge_id") if data.get("selected_edge_id") in self.edges else None
        self.connect_source_id = None
        self.input_power_mw = float(data.get("input_power_mw", 100.0))
        self.wavelength_nm = float(data.get("wavelength_nm", 808.0))
        self.receiver_na = float(data.get("receiver_na", 0.12))
        self.receiver_mode_radius_um = float(data.get("receiver_mode_radius_um", 2.80))
        self.target_total_efficiency = float(data.get("target_total_efficiency", 0.85))
        self.max_system_length_mm = float(data.get("max_system_length_mm", 80.0))
        self.min_air_gap_mm = float(data.get("min_air_gap_mm", 0.50))
        self.latest_cause = str(data.get("latest_cause", "已恢复实验状态。"))
        self._counter = int(data.get("counter", self._counter))
        self.mark_changed()
        if reset_history:
            self._reset_history()

    def _reset_history(self) -> None:
        self._history = [copy.deepcopy(self.snapshot())]
        self._history_index = 0

    def record(self, label: str) -> None:
        self.latest_cause = str(label)
        self.mark_changed()
        self.log.append(str(label))
        self._history = self._history[: self._history_index + 1]
        self._history.append(copy.deepcopy(self.snapshot()))
        self._history_index += 1
        if len(self._history) > 80:
            overflow = len(self._history) - 80
            self._history = self._history[overflow:]
            self._history_index -= overflow

    def can_undo(self) -> bool:
        return self._history_index > 0

    def can_redo(self) -> bool:
        return self._history_index + 1 < len(self._history)

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self._history_index -= 1
        self.restore(self._history[self._history_index])
        self.latest_cause = "已撤销上一步操作。"
        self.log.append(self.latest_cause)
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        self._history_index += 1
        self.restore(self._history[self._history_index])
        self.latest_cause = "已重做下一步操作。"
        self.log.append(self.latest_cause)
        return True

    
    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def _default_params(self, kind: str) -> dict[str, float | str | bool]:
        if kind == "lens":
            return {"focal_mm": 50.0, "reversed": False, "enabled": True}
        if kind == "fiber":
            return {
                "offset_x_um": 0.0,
                "offset_y_um": 0.0,
                "offset_z_um": 0.0,
                "pitch_mrad": 0.0,
                "yaw_mrad": 0.0,
                "curvature_waves": 0.0,
            }
        if kind in {"splitter", "beam_sampler"}:
            return {"monitor_fraction": 0.05}
        if kind == "pbs":
            return {"monitor_fraction": 0.50, "polarization_angle_deg": 0.0}
        if kind == "half_wave_plate":
            return {"axis_angle_deg": 0.0}
        if kind == "mirror":
            return {"angle_deg": 45.0}
        if kind == "aperture":
            return {"diameter_mm": 5.0}
        if kind == "beam_expander":
            return {
                "magnification": 2.0,
                "spacing_mm": 150.0,
                "design_spacing_mm": 150.0,
                "module_offset_mm": 0.0,
            }
        if kind == "cylindrical_lens":
            return {
                "focal_mm": 50.0,
                "axis_angle_deg": 0.0,
                "pair_spacing_mm": 60.0,
                "module_offset_mm": 0.0,
            }
        if kind in {"beam_analyzer", "imaging_camera", "focus_scan_module", "wavefront_sensor"}:
            return {"plane_offset_mm": 0.0}
        if kind == "focus_scan_module":
            return {"plane_offset_mm": 0.0, "scan_span_mm": 20.0}
        if kind == "power_meter":
            return {"range_mw": 500.0}
        return {}

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
    ) -> str:
        kind = str(kind)
        node_id = node_id or self._next_id(kind)
        merged = self._default_params(kind)
        merged.update(params or {})
        if label is None:
            base = NODE_LABELS.get(kind, kind)
            same_kind = sum(1 for node in self.nodes.values() if node.kind == kind)
            label = base if same_kind == 0 else f"{base}{same_kind + 1}"
        self.nodes[node_id] = ExperimentNode(node_id, kind, label, float(x), float(y), params=merged)
        self.mark_changed()
        self.selected_node_id = node_id
        self.selected_edge_id = None
        if record:
            self.record(f"添加{label}。")
        return node_id

    def add_edge(self, source: str, target: str, *, record: bool = True) -> str | None:
        if source == target or source not in self.nodes or target not in self.nodes:
            return None
        if any(edge.source == source and edge.target == target for edge in self.edges.values()):
            return None
        source_kind = self.nodes[source].kind
        target_kind = self.nodes[target].kind
        if source_kind in TERMINAL_TYPES and not (source_kind == "photodetector" and target_kind == "oscilloscope"):
            return None
        if target_kind == "laser":
            return None
        if target_kind == "oscilloscope" and source_kind != "photodetector":
            return None
        edge_id = self._next_id("edge")
        self.edges[edge_id] = ExperimentEdge(edge_id, source, target)
        self.mark_changed()
        self.selected_edge_id = edge_id
        self.selected_node_id = None
        if record:
            self.record(f"连接{self.nodes[source].label} → {self.nodes[target].label}。")
        return edge_id

    def remove_selected(self) -> bool:
        if self.selected_edge_id in self.edges:
            edge = self.edges.pop(self.selected_edge_id)
            self.mark_changed()
            self.selected_edge_id = None
            self.record(f"删除{self.nodes[edge.source].label}到{self.nodes[edge.target].label}的连接。")
            return True
        node_id = self.selected_node_id
        if node_id not in self.nodes:
            return False
        node = self.nodes.pop(node_id)
        self.mark_changed()
        self.edges = {
            edge_id: edge
            for edge_id, edge in self.edges.items()
            if edge.source != node_id and edge.target != node_id
        }
        self.selected_node_id = None
        self.record(f"删除{node.label}。")
        return True

    def move_node(self, node_id: str, x: float, y: float, *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        old = (node.x, node.y)
        node.x = max(45.0, min(SCENE_RECT.width() - 45.0, float(x)))
        node.y = max(70.0, min(SCENE_RECT.height() - 70.0, float(y)))
        if self.mode == "layout":
            if node.kind in OPTICAL_TYPES:
                node.y = MAIN_RAIL_Y
            elif node.kind != "oscilloscope":
                node.y = BRANCH_RAIL_Y
        changed = abs(old[0] - node.x) > 0.1 or abs(old[1] - node.y) > 0.1
        if changed:
            self.mark_changed()
        if record and changed:
            self.record(f"移动{node.label}到({node.x:.0f}, {node.y:.0f})。")

    def update_node_params(self, node_id: str, changes: dict[str, Any], *, record: bool = True) -> None:
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.params.update(changes)
        self.mark_changed()
        if "rotation_deg" in changes:
            node.rotation_deg = float(changes["rotation_deg"])
        if record:
            description = "、".join(f"{key}={value}" for key, value in changes.items())
            self.record(f"更新{node.label}：{description}。")

    def load_standard(self, *, record: bool = True) -> None:
        self.nodes.clear()
        self.edges.clear()
        self._counter = 0
        laser = self.add_node("laser", 120, MAIN_RAIL_Y, node_id="laser", label="激光器", record=False)
        isolator = self.add_node("isolator", 300, MAIN_RAIL_Y, node_id="isolator", label="光隔离器", record=False)
        splitter = self.add_node("splitter", 495, MAIN_RAIL_Y, node_id="splitter", label="分束器", record=False)
        l1 = self.add_node("lens", 710, MAIN_RAIL_Y, node_id="lens_1", label="L1", params={"focal_mm": 12.0}, record=False)
        l2 = self.add_node("lens", 910, MAIN_RAIL_Y, node_id="lens_2", label="L2", params={"focal_mm": 12.0}, record=False)
        fiber = self.add_node("fiber", 1160, MAIN_RAIL_Y, node_id="fiber", label="五轴光纤架", record=False)
        input_meter = self.add_node("power_meter", 500, BRANCH_RAIL_Y, node_id="input_meter", label="输入功率计", params={"range_mw": 500.0}, record=False)
        output_meter = self.add_node("power_meter", 1380, MAIN_RAIL_Y, node_id="output_meter", label="输出功率计", params={"range_mw": 20.0}, record=False)
        analyzer = self.add_node("beam_analyzer", 910, BRANCH_RAIL_Y, node_id="beam_analyzer", label="光束分析仪", record=False)
        wavefront = self.add_node("wavefront_sensor", 1140, BRANCH_RAIL_Y, node_id="wavefront", label="波前传感器", record=False)
        for source, target in (
            (laser, isolator),
            (isolator, splitter),
            (splitter, l1),
            (l1, l2),
            (l2, fiber),
            (fiber, output_meter),
            (splitter, input_meter),
        ):
            self.add_edge(source, target, record=False)
        self.selected_node_id = l2
        self.selected_edge_id = None
        self.connect_source_id = None
        self.latest_cause = "恢复标准实验平台。"
        self.mark_changed()
        if record:
            self.record(self.latest_cause)

    def clear_platform(self) -> None:
        self.nodes.clear()
        self.edges.clear()
        self.selected_node_id = None
        self.selected_edge_id = None
        self.connect_source_id = None
        self.record("清空自由搭建平台。")

    def apply_diagnostic_example(self) -> None:
        self.load_standard(record=False)
        fiber = self.nodes.get("fiber")
        if fiber is not None:
            fiber.params.update(
                {
                    "offset_x_um": 2.2,
                    "offset_y_um": -0.8,
                    "offset_z_um": 34.0,
                    "pitch_mrad": 13.0,
                    "yaw_mrad": -7.0,
                    "curvature_waves": 0.12,
                }
            )
        self.latest_cause = "载入复合失配诊断示例。"
        self.mark_changed()
        self._reset_history()
        self.log.append(self.latest_cause)

    
    def outgoing(self, node_id: str) -> list[str]:
        return [edge.target for edge in self.edges.values() if edge.source == node_id]

    def incoming(self, node_id: str) -> list[str]:
        return [edge.source for edge in self.edges.values() if edge.target == node_id]

    def reached_nodes(self) -> set[str]:
        lasers = [node.id for node in self.nodes.values() if node.kind == "laser"]
        reached: set[str] = set(lasers)
        queue = list(lasers)
        while queue:
            source = queue.pop(0)
            for target in self.outgoing(source):
                if target not in reached:
                    reached.add(target)
                    queue.append(target)
        return reached

    def shortest_path(self, target_kind: str = "fiber") -> list[str]:
        lasers = [node.id for node in self.nodes.values() if node.kind == "laser"]
        targets = {node.id for node in self.nodes.values() if node.kind == target_kind}
        queue: list[tuple[str, list[str]]] = [(node_id, [node_id]) for node_id in lasers]
        visited = set(lasers)
        while queue:
            node_id, path = queue.pop(0)
            if node_id in targets:
                return path
            for target in self.outgoing(node_id):
                if target not in visited:
                    visited.add(target)
                    queue.append((target, path + [target]))
        return []

    def beam_state(self) -> dict[str, float]:

        path = self.shortest_path("fiber")
        nodes = [self.nodes[node_id] for node_id in path if node_id in self.nodes]
        wavelength_um = max(self.wavelength_nm / 1000.0, 1e-9)
        radius_x_mm = 0.72
        radius_y_mm = 0.72
        curvature_waves = 0.0
        waist_shift_x_um = 0.0
        waist_shift_y_um = 0.0

        for node in nodes:
            if node.kind == "beam_expander":
                magnification = max(0.25, min(8.0, float(node.params.get("magnification", 2.0))))
                spacing = float(node.params.get("spacing_mm", 150.0))
                design = max(1.0, float(node.params.get("design_spacing_mm", spacing)))
                detune = (spacing - design) / design
                module_offset = float(node.params.get("module_offset_mm", 0.0))
                radius_x_mm *= magnification * max(0.55, 1.0 + 0.32 * detune)
                radius_y_mm *= magnification * max(0.55, 1.0 + 0.32 * detune)
                curvature_waves += 1.65 * detune + 0.006 * module_offset
                waist_shift_x_um += (0.08 * module_offset + 3.0 * detune) * 1000.0
                waist_shift_y_um += (0.08 * module_offset + 3.0 * detune) * 1000.0
            elif node.kind == "cylindrical_lens":
                focal = float(node.params.get("focal_mm", 50.0))
                axis = math.radians(float(node.params.get("axis_angle_deg", 0.0)))
                power = 50.0 / max(abs(focal), 1.0)
                signed = 1.0 if focal >= 0.0 else -1.0
                effect_x = math.cos(axis) ** 2
                effect_y = math.sin(axis) ** 2
                radius_x_mm *= max(0.45, 1.0 - 0.16 * signed * power * effect_x)
                radius_y_mm *= max(0.45, 1.0 - 0.16 * signed * power * effect_y)
                separation = float(node.params.get("pair_spacing_mm", 60.0))
                module_offset = float(node.params.get("module_offset_mm", 0.0))
                shift = signed * power * (0.0012 * separation + 0.002 * module_offset) * 1000.0
                waist_shift_x_um += shift * effect_x
                waist_shift_y_um += shift * effect_y
                curvature_waves += signed * 0.08 * power * (effect_x - effect_y)

        lenses = [node for node in nodes if node.kind == "lens" and bool(node.params.get("enabled", True))]
        for index, lens in enumerate(lenses[:-1]):
            focal = float(lens.params.get("focal_mm", 50.0))
            role = 0.14 + 0.05 * index
            factor = max(0.58, min(1.62, 1.0 + role * (50.0 / max(abs(focal), 1.0) - 1.0)))
            radius_x_mm *= factor
            radius_y_mm *= factor
        if lenses:
            final_focal = abs(float(lenses[-1].params.get("focal_mm", 25.0)))
            waist_x = self.wavelength_nm * 1e-6 * final_focal / max(math.pi * radius_x_mm, 1e-9) * 1000.0
            waist_y = self.wavelength_nm * 1e-6 * final_focal / max(math.pi * radius_y_mm, 1e-9) * 1000.0
        else:
            waist_x = waist_y = 18.0
        waist_x = max(0.15, min(80.0, waist_x))
        waist_y = max(0.15, min(80.0, waist_y))

        fiber = next((node for node in nodes if node.kind == "fiber"), None)
        fp = fiber.params if fiber is not None else {}
        z_um = float(fp.get("offset_z_um", 0.0))
        zx_um = z_um - waist_shift_x_um
        zy_um = z_um - waist_shift_y_um
        zrx = math.pi * waist_x**2 / wavelength_um
        zry = math.pi * waist_y**2 / wavelength_um
        radius_plane_x = waist_x * math.sqrt(1.0 + (zx_um / max(zrx, 1e-9)) ** 2)
        radius_plane_y = waist_y * math.sqrt(1.0 + (zy_um / max(zry, 1e-9)) ** 2)
        natural_curvature = 0.5 * (zx_um / max(zrx, 1e-9) + zy_um / max(zry, 1e-9))
        return {
            "waist_x_um": waist_x, "waist_y_um": waist_y,
            "waist_x_z_um": waist_shift_x_um, "waist_y_z_um": waist_shift_y_um,
            "plane_radius_x_um": radius_plane_x, "plane_radius_y_um": radius_plane_y,
            "rayleigh_x_um": zrx, "rayleigh_y_um": zry,
            "curvature_waves": curvature_waves + natural_curvature,
            "ellipticity": max(radius_plane_x, radius_plane_y) / max(min(radius_plane_x, radius_plane_y), 1e-9),
        }

    def _evaluate_uncached(self) -> WorkbenchMetrics:
        reached = self.reached_nodes()
        path = self.shortest_path("fiber")
        if not path:
            return WorkbenchMetrics(
                connected=False,
                path_node_ids=tuple(),
                reached_node_ids=tuple(sorted(reached)),
                lens_count=0,
                predicted_waist_um=0.0,
                target_waist_um=self.receiver_mode_radius_um,
                system_efficiency=0.0,
                receiver_efficiency=0.0,
                total_efficiency=0.0,
                output_power_mw=0.0,
                feasible=False,
                dominant_issue="光路未连通",
                explanation="激光器到光纤接收端之间没有完整的有向连接。",
                latest_cause=self.latest_cause,
            )

        nodes = [self.nodes[node_id] for node_id in path]
        lenses = [node for node in nodes if node.kind == "lens" and bool(node.params.get("enabled", True))]
        wavelength_um = self.wavelength_nm / 1000.0
        target_waist = max(0.2, self.receiver_mode_radius_um)

        state = self.beam_state()
        predicted_waist_x = float(state["waist_x_um"])
        predicted_waist_y = float(state["waist_y_um"])
        plane_radius_x = float(state["plane_radius_x_um"])
        plane_radius_y = float(state["plane_radius_y_um"])
        predicted_waist = math.sqrt(predicted_waist_x * predicted_waist_y)
        beam_radius_mm = math.sqrt(max(1e-9, 0.72 * 0.72 * target_waist / max(predicted_waist, 0.15)))
        size_match_x = 2.0 * plane_radius_x * target_waist / max(plane_radius_x**2 + target_waist**2, 1e-9)
        size_match_y = 2.0 * plane_radius_y * target_waist / max(plane_radius_y**2 + target_waist**2, 1e-9)
        size_match = max(0.0, min(1.0, size_match_x * size_match_y))
        capacity = {0: 0.08, 1: 0.78, 2: 0.91, 3: 0.965, 4: 0.985}.get(min(len(lenses), 4), 0.985)

        fiber = next((node for node in nodes if node.kind == "fiber"), None)
        fp = fiber.params if fiber is not None else {}
        dx = float(fp.get("offset_x_um", 0.0))
        dy = float(fp.get("offset_y_um", 0.0))
        dz = float(fp.get("offset_z_um", 0.0))
        pitch = float(fp.get("pitch_mrad", 0.0))
        yaw = float(fp.get("yaw_mrad", 0.0))
        curvature = float(fp.get("curvature_waves", 0.0))
        effective_w2 = max(predicted_waist**2 + target_waist**2, 1e-9)
        position_match = math.exp(-2.0 * (dx**2 + dy**2) / effective_w2)
        angle_rad = math.hypot(pitch, yaw) * 1e-3
        angle_match = math.exp(-((math.pi * target_waist * angle_rad / max(wavelength_um, 1e-9)) ** 2))
        rayleigh_um = math.sqrt(float(state["rayleigh_x_um"]) * float(state["rayleigh_y_um"]))
        
        
        
        defocus_match = 1.0 / (1.0 + (dz / max(2.4 * rayleigh_um, 1e-9)) ** 2)
        total_curvature = curvature + float(state["curvature_waves"])
        curvature_match = 1.0 / (1.0 + (math.pi * total_curvature) ** 2)

        progression = 1.0
        if len(lenses) > 1:
            focal_values = [float(node.params.get("focal_mm", 50.0)) for node in lenses]
            jumps = [abs(math.log(max(b, 1e-6) / max(a, 1e-6))) for a, b in zip(focal_values, focal_values[1:])]
            progression = math.exp(-0.12 * sum(jumps))
        reversal_penalty = math.prod(0.975 if bool(lens.params.get("reversed", False)) else 1.0 for lens in lenses)

        receiver = max(0.0, min(1.0, size_match * capacity * position_match * angle_match * defocus_match * curvature_match * progression * reversal_penalty))

        transmissions = {
            "laser": 1.0,
            "isolator": 0.965,
            "half_wave_plate": 0.995,
            "pbs": 0.97,
            "beam_sampler": 0.985,
            "splitter": 0.95,
            "mirror": 0.985,
            "aperture": 0.995,
            "lens": 0.992,
            "beam_expander": 0.985,
            "cylindrical_lens": 0.992,
            "fiber": 1.0,
        }
        system = 1.0
        for node in nodes:
            system *= transmissions.get(node.kind, 1.0)
            if node.kind == "aperture":
                diameter = float(node.params.get("diameter_mm", 5.0))
                if diameter < 2.0 * beam_radius_mm:
                    system *= math.exp(-((2.0 * beam_radius_mm - diameter) / max(diameter, 0.2)) ** 2)

        splitter = next((node for node in nodes if node.kind in {"splitter", "beam_sampler", "pbs"}), None)
        monitor_fraction = float(splitter.params.get("monitor_fraction", 0.05)) if splitter else 0.0
        system *= max(0.0, 1.0 - monitor_fraction)

        
        optical = [node for node in nodes if node.kind in OPTICAL_TYPES]
        overlap = False
        for left, right in zip(optical, optical[1:]):
            if math.hypot(right.x - left.x, right.y - left.y) < 72.0:
                overlap = True
                break
        span_mm = 0.0
        if optical:
            span_mm = math.hypot(optical[-1].x - optical[0].x, optical[-1].y - optical[0].y) / 14.0
        feasible = not overlap and span_mm <= self.max_system_length_mm
        if overlap:
            system *= 0.35
        if span_mm > self.max_system_length_mm:
            system *= math.exp(-(span_mm - self.max_system_length_mm) / max(self.max_system_length_mm * 0.25, 1.0))
        system = max(0.0, min(1.0, system))
        total = system * receiver

        factors = {
            "束腰尺寸不匹配": size_match,
            "横向位置不匹配": position_match,
            "传播方向不匹配": angle_match,
            "轴向离焦": defocus_match,
            "波前曲率不匹配": curvature_match,
            "结构通过能力": system,
        }
        dominant, weakest = min(factors.items(), key=lambda item: item[1])
        explanations = {
            "束腰尺寸不匹配": "最终聚焦光斑与光纤模场尺寸不同，振幅重叠不足。",
            "横向位置不匹配": "入射光斑中心偏离纤芯中心，横向空间重叠下降。",
            "传播方向不匹配": "光束方向与光纤轴线存在夹角，端面出现线性相位坡度。",
            "轴向离焦": "光纤端面没有位于合适的束腰位置，尺寸和相位共同偏离目标。",
            "波前曲率不匹配": "端面强度可能接近，但二次相位不同，复场积分发生抵消。",
            "结构通过能力": "光路传输、分光、元件重叠或系统长度限制了可用功率。",
        }
        if not feasible:
            dominant = "结构不可实现"
            explanation = "当前光路存在元件过近或总长度超出教学约束，应先修改布局再继续优化。"
        else:
            explanation = explanations[dominant]

        return WorkbenchMetrics(
            connected=True,
            path_node_ids=tuple(path),
            reached_node_ids=tuple(sorted(reached)),
            lens_count=len(lenses),
            predicted_waist_um=predicted_waist,
            target_waist_um=target_waist,
            system_efficiency=system,
            receiver_efficiency=receiver,
            total_efficiency=total,
            output_power_mw=self.input_power_mw * total,
            feasible=feasible,
            dominant_issue=dominant,
            explanation=explanation,
            latest_cause=self.latest_cause,
        )

    def evaluate(self) -> WorkbenchMetrics:
        if self._metrics_cache_revision == self._revision and self._metrics_cache is not None:
            return self._metrics_cache
        metrics = self._evaluate_uncached()
        self._metrics_cache = metrics
        self._metrics_cache_revision = self._revision
        return metrics

    def _compute_beam_radii(self, metrics: WorkbenchMetrics) -> tuple[dict[str, float], dict[str, float]]:
        path = list(metrics.path_node_ids)
        current = {node_id: 6.0 for node_id in self.nodes}
        ideal = {node_id: 6.0 for node_id in self.nodes}
        if not path:
            return current, ideal
        current[path[0]] = 15.0
        ideal[path[0]] = 15.0
        for index, node_id in enumerate(path[:-1]):
            node = self.nodes[node_id]
            target_id = path[index + 1]
            target = self.nodes[target_id]
            radius, ideal_radius = current[node_id], ideal[node_id]
            next_radius, next_ideal = radius, ideal_radius
            if node.kind == "lens":
                focal = float(node.params.get("focal_mm", 50.0))
                if target.kind == "fiber":
                    ratio = metrics.predicted_waist_um / max(metrics.target_waist_um, 0.2)
                    next_radius, next_ideal = max(3.2, min(13.0, 4.8 * ratio)), 4.8
                else:
                    next_radius = max(9.0, min(30.0, 8.0 + focal * 0.14))
                    next_ideal = max(10.0, min(26.0, 9.0 + focal * 0.11))
            elif target.kind == "fiber":
                next_radius = max(3.5, min(12.0, 4.8 * metrics.predicted_waist_um / max(metrics.target_waist_um, 0.2)))
                next_ideal = 4.8
            elif target.kind == "power_meter" and node.kind == "fiber":
                next_radius = next_ideal = 3.2
            elif target.kind == "lens":
                next_radius, next_ideal = max(12.0, radius), max(12.0, ideal_radius)
            current[target_id], ideal[target_id] = next_radius, next_ideal
        for edge in self.edges.values():
            if edge.source in path and edge.target not in path:
                current[edge.target] = ideal[edge.target] = 6.0
        return current, ideal

    def scene_snapshot(self) -> TeachingSceneSnapshot:
        cached = self._scene_snapshot_cache
        if cached is not None and cached.revision == self._revision:
            return cached
        metrics = self.evaluate()
        current, ideal = self._compute_beam_radii(metrics)
        snapshot = TeachingSceneSnapshot(self._revision, metrics, current, ideal)
        self._scene_snapshot_cache = snapshot
        return snapshot

    def instrument_reading(self, node_id: str) -> dict[str, Any]:
        node = self.nodes.get(node_id)
        metrics = self.evaluate()
        reached = set(metrics.reached_node_ids)
        if node is None or node.kind not in INSTRUMENT_TYPES:
            return {"valid": False, "message": "请选择测量仪器。"}
        if node.kind == "oscilloscope":
            incoming = self.incoming(node_id)
            valid = any(self.nodes.get(source) and self.nodes[source].kind == "photodetector" and source in reached for source in incoming)
        else:
            valid = node_id in reached
        if not valid:
            return {"valid": False, "message": "仪器未接收到有效光束；请检查位置、方向和光路连接。"}

        if node.kind == "power_meter":
            path_to_fiber = set(metrics.path_node_ids)
            if node_id == "output_meter" or any(source in path_to_fiber and self.nodes[source].kind == "fiber" for source in self.incoming(node_id)):
                power = metrics.output_power_mw
                role = "输出功率"
            else:
                splitters = [self.nodes[source] for source in self.incoming(node_id) if self.nodes[source].kind in {"splitter", "beam_sampler", "pbs"}]
                fraction = float(splitters[0].params.get("monitor_fraction", 0.05)) if splitters else 1.0
                power = self.input_power_mw * fraction
                role = "监测功率"
            return {"valid": True, "kind": node.kind, "role": role, "power_mw": power, "efficiency": metrics.total_efficiency}
        if node.kind in {"beam_analyzer", "imaging_camera", "focus_scan_module"}:
            state = self.beam_state()
            offset_mm = float(node.params.get("plane_offset_mm", 0.0))
            offset_um = offset_mm * 1000.0
            zx = offset_um - float(state["waist_x_z_um"])
            zy = offset_um - float(state["waist_y_z_um"])
            wx = float(state["waist_x_um"]) * math.sqrt(1.0 + (zx / max(float(state["rayleigh_x_um"]), 1e-9)) ** 2)
            wy = float(state["waist_y_um"]) * math.sqrt(1.0 + (zy / max(float(state["rayleigh_y_um"]), 1e-9)) ** 2)
            fiber = next((item for item in self.nodes.values() if item.kind == "fiber"), None)
            dx = float(fiber.params.get("offset_x_um", 0.0)) if fiber else 0.0
            dy = float(fiber.params.get("offset_y_um", 0.0)) if fiber else 0.0
            result = {
                "valid": True, "kind": node.kind, "radius_x_um": wx, "radius_y_um": wy,
                "center_x_um": dx, "center_y_um": dy, "offset_mm": offset_mm,
                "waist_x_z_mm": float(state["waist_x_z_um"]) / 1000.0,
                "waist_y_z_mm": float(state["waist_y_z_um"]) / 1000.0,
                "ellipticity": max(wx, wy) / max(min(wx, wy), 1e-9),
            }
            if node.kind == "focus_scan_module":
                span = max(0.5, float(node.params.get("scan_span_mm", 20.0)))
                positions = [(-0.5 + index / 20.0) * span for index in range(21)]
                result["scan_z_mm"] = positions
                result["scan_wx_um"] = [
                    float(state["waist_x_um"]) * math.sqrt(1.0 + (((z * 1000.0) - float(state["waist_x_z_um"])) / max(float(state["rayleigh_x_um"]), 1e-9)) ** 2)
                    for z in positions
                ]
                result["scan_wy_um"] = [
                    float(state["waist_y_um"]) * math.sqrt(1.0 + (((z * 1000.0) - float(state["waist_y_z_um"])) / max(float(state["rayleigh_y_um"]), 1e-9)) ** 2)
                    for z in positions
                ]
            return result
        if node.kind == "wavefront_sensor":
            fiber = next((item for item in self.nodes.values() if item.kind == "fiber"), None)
            fp = fiber.params if fiber else {}
            return {
                "valid": True,
                "kind": node.kind,
                "tilt_x_mrad": float(fp.get("pitch_mrad", 0.0)),
                "tilt_y_mrad": float(fp.get("yaw_mrad", 0.0)),
                "curvature_waves": float(fp.get("curvature_waves", 0.0)) + float(self.beam_state()["curvature_waves"]),
                "astigmatism_um": abs(float(self.beam_state()["waist_x_z_um"]) - float(self.beam_state()["waist_y_z_um"])),
            }
        if node.kind == "photodetector":
            return {"valid": True, "kind": node.kind, "signal_v": 0.018 * self.input_power_mw * max(metrics.system_efficiency, 0.05), "noise_v": 0.012}
        if node.kind == "oscilloscope":
            return {"valid": True, "kind": node.kind, "amplitude_v": 0.018 * self.input_power_mw * max(metrics.system_efficiency, 0.05), "frequency_hz": 37.0}
        return {"valid": True, "kind": node.kind}


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------


class OpticalNodeItem(QGraphicsObject):


    activated = Signal(str)
    positionChanged = Signal(str)
    movementFinished = Signal(str, float, float)

    def __init__(
        self,
        node: ExperimentNode,
        movable: bool,
        *,
        display_layer: str = "overlay",
        show_ports: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.node_id = node.id
        self.kind = node.kind
        self.label = node.label
        self.params = copy.deepcopy(node.params)
        self.rotation_deg = float(node.rotation_deg)
        self.display_layer = display_layer if display_layer in DISPLAY_LAYER_LABELS else "overlay"
        self.show_ports = bool(show_ports)
        self._old_pos = QPointF(node.x, node.y)
        self._syncing = True
        self.setPos(node.x, node.y)
        self._syncing = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(10.0)

    def boundingRect(self) -> QRectF:  
        return QRectF(-78.0, -76.0, 156.0, 156.0)

    def itemChange(self, change, value):  
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._syncing:
            self.positionChanged.emit(self.node_id)
        return result

    def update_from_node(
        self,
        node: ExperimentNode,
        *,
        movable: bool,
        display_layer: str,
        show_ports: bool,
    ) -> None:
        self.prepareGeometryChange()
        self.kind = node.kind
        self.label = node.label
        self.params = copy.deepcopy(node.params)
        self.rotation_deg = float(node.rotation_deg)
        self.display_layer = display_layer if display_layer in DISPLAY_LAYER_LABELS else "overlay"
        self.show_ports = bool(show_ports)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, movable)
        target = QPointF(float(node.x), float(node.y))
        if (self.pos() - target).manhattanLength() > 0.01:
            self._syncing = True
            self.setPos(target)
            self._syncing = False
        self.update()

    def mousePressEvent(self, event) -> None:  
        self._old_pos = self.pos()
        self.activated.emit(self.node_id)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  
        super().mouseReleaseEvent(event)
        if (self.pos() - self._old_pos).manhattanLength() > 0.5:
            self.movementFinished.emit(self.node_id, self.pos().x(), self.pos().y())

    @staticmethod
    def _hardware_gradient(top: str = "#F7F8FA", bottom: str = "#cbd8e1") -> QLinearGradient:
        gradient = QLinearGradient(0, -42, 0, 42)
        gradient.setColorAt(0.0, QColor(top))
        gradient.setColorAt(1.0, QColor(bottom))
        return gradient

    def _draw_base_and_post(self, painter: QPainter, *, post_y: float = 31.0, width: float = 54.0) -> None:

        painter.save()
        painter.setPen(QPen(QColor("#617b8b"), 1.2))
        painter.setBrush(self._hardware_gradient("#eef3f6", "#aebdc7"))
        painter.drawRoundedRect(QRectF(-width / 2, 54, width, 11), 3, 3)
        painter.setBrush(QColor("#b8c6cf"))
        painter.drawRoundedRect(QRectF(-5, post_y, 10, 25), 3, 3)
        painter.setBrush(QColor("#eaf0f4"))
        painter.drawEllipse(QRectF(-8, 50, 16, 8))
        painter.restore()

    def _draw_selection_halo(self, painter: QPainter) -> None:
        if not self.isSelected():
            return
        painter.save()
        painter.setPen(QPen(QColor(11, 121, 183, 190), 2.2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(11, 121, 183, 22))
        painter.drawRoundedRect(QRectF(-69, -59, 138, 126), 12, 12)
        painter.restore()

    def _draw_laser(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#47697e"), 1.5))
        painter.setBrush(self._hardware_gradient("#f9fbfc", "#bccbd5"))
        painter.drawRoundedRect(QRectF(-52, -27, 82, 54), 7, 7)
        painter.setBrush(QColor("#9eafb9"))
        painter.drawRoundedRect(QRectF(-61, -19, 12, 38), 3, 3)
        painter.setBrush(QColor("#304e60"))
        painter.drawEllipse(QRectF(23, -12, 20, 24))
        painter.setBrush(QColor("#f04747"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(35, -5, 10, 10))
        painter.setPen(QPen(QColor("#607b8c"), 1.2))
        painter.setBrush(QColor("#c7d4dc"))
        painter.drawRoundedRect(QRectF(-46, 29, 68, 11), 3, 3)

    def _draw_isolator(self, painter: QPainter) -> None:
        self._draw_base_and_post(painter, post_y=25, width=66)
        painter.setPen(QPen(QColor("#456a80"), 1.4))
        painter.setBrush(self._hardware_gradient("#edf7fb", "#a9c4d4"))
        painter.drawRoundedRect(QRectF(-49, -22, 98, 44), 18, 18)
        painter.setBrush(QColor("#7b98aa"))
        painter.drawEllipse(QRectF(-52, -22, 12, 44))
        painter.drawEllipse(QRectF(40, -22, 12, 44))
        painter.setPen(QPen(QColor(theme.PRIMARY), 2.5))
        painter.drawLine(QPointF(-18, 0), QPointF(20, 0))
        painter.drawLine(QPointF(11, -8), QPointF(20, 0))
        painter.drawLine(QPointF(11, 8), QPointF(20, 0))

    def _draw_splitter(self, painter: QPainter) -> None:
        self._draw_base_and_post(painter, post_y=32, width=60)
        painter.setPen(QPen(QColor("#5888a2"), 1.5))
        glass = QLinearGradient(-32, -34, 32, 34)
        glass.setColorAt(0.0, QColor(223, 245, 255, 220))
        glass.setColorAt(0.5, QColor(143, 210, 239, 155))
        glass.setColorAt(1.0, QColor(91, 158, 194, 130))
        painter.setBrush(glass)
        painter.drawPolygon(QPolygonF([
            QPointF(-31, -31), QPointF(17, -31), QPointF(35, -12),
            QPointF(35, 31), QPointF(-15, 31), QPointF(-35, 12),
        ]))
        painter.setPen(QPen(QColor("#4f839e"), 2.0))
        painter.drawLine(QPointF(-23, 27), QPointF(25, -27))
        painter.setBrush(QColor("#9db4c2"))
        painter.setPen(QPen(QColor("#647f90"), 1.2))
        painter.drawEllipse(QRectF(-42, 26, 13, 13))
        painter.drawEllipse(QRectF(29, 26, 13, 13))

    def _draw_mirror(self, painter: QPainter) -> None:
        self._draw_base_and_post(painter, post_y=29, width=64)
        painter.save()
        painter.rotate(-42)
        painter.setPen(QPen(QColor("#496b80"), 2.0))
        mirror = QLinearGradient(-34, 0, 34, 0)
        mirror.setColorAt(0.0, QColor("#a6bac6"))
        mirror.setColorAt(0.45, QColor("#f9fcfd"))
        mirror.setColorAt(1.0, QColor("#8fa8b7"))
        painter.setBrush(mirror)
        painter.drawRoundedRect(QRectF(-35, -9, 70, 18), 7, 7)
        painter.restore()
        painter.setBrush(QColor("#8da2af"))
        painter.setPen(QPen(QColor("#5b7382"), 1))
        painter.drawEllipse(QRectF(-31, 29, 10, 10))
        painter.drawEllipse(QRectF(21, 29, 10, 10))

    def _draw_aperture(self, painter: QPainter) -> None:
        self._draw_base_and_post(painter, post_y=28, width=52)
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY), 1.6))
        painter.setBrush(QColor("#566b78"))
        painter.drawEllipse(QRectF(-28, -35, 56, 70))
        painter.setBrush(QColor("#f4f8fa"))
        painter.drawEllipse(QRectF(-10, -14, 20, 28))
        painter.setBrush(QColor(theme.TEXT_MUTED))
        painter.drawRoundedRect(QRectF(25, -5, 15, 10), 3, 3)

    def _draw_lens(self, painter: QPainter) -> None:
        self._draw_base_and_post(painter, post_y=33, width=58)
        painter.setPen(QPen(QColor("#567b90"), 2.2))
        painter.setBrush(QColor("#d5e1e7"))
        painter.drawEllipse(QRectF(-24, -48, 48, 96))
        lens_path = QPainterPath(QPointF(0, -43))
        lens_path.cubicTo(QPointF(-15, -26), QPointF(-15, 26), QPointF(0, 43))
        lens_path.cubicTo(QPointF(15, 26), QPointF(15, -26), QPointF(0, -43))
        glass = QLinearGradient(-16, 0, 16, 0)
        glass.setColorAt(0.0, QColor(108, 190, 226, 90))
        glass.setColorAt(0.5, QColor(230, 249, 255, 180))
        glass.setColorAt(1.0, QColor(74, 161, 207, 110))
        painter.setBrush(glass)
        painter.setPen(QPen(QColor(theme.PRIMARY), 1.6))
        painter.drawPath(lens_path)

    def _draw_fiber_stage(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#4f6d7e"), 1.4))
        painter.setBrush(self._hardware_gradient("#f8fafb", "#bcc9d1"))
        painter.drawRoundedRect(QRectF(-56, 24, 88, 34), 5, 5)
        painter.setBrush(QColor("#d8e1e6"))
        painter.drawRoundedRect(QRectF(-46, -25, 66, 50), 5, 5)
        painter.setBrush(QColor("#afbec7"))
        painter.drawRoundedRect(QRectF(-37, -35, 50, 16), 4, 4)
        
        painter.setBrush(QColor("#6f8999"))
        painter.drawEllipse(QRectF(-59, -18, 17, 17))
        painter.drawEllipse(QRectF(-18, -48, 17, 17))
        painter.drawEllipse(QRectF(-20, 39, 17, 17))
        painter.setPen(QPen(QColor(theme.PRIMARY), 3.0))
        painter.drawLine(QPointF(16, 0), QPointF(58, 0))
        painter.setBrush(QColor(theme.PRIMARY_TINT))
        painter.drawEllipse(QRectF(10, -13, 26, 26))
        painter.setBrush(QColor(theme.PRIMARY))
        painter.drawEllipse(QRectF(19, -4, 8, 8))
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.0))
        painter.drawLine(QPointF(43, -8), QPointF(43, 8))

    def _draw_instrument(self, painter: QPainter) -> None:
        symbols = {
            "power_meter": "P",
            "beam_analyzer": "CAM",
            "wavefront_sensor": "WF",
            "photodetector": "PD",
            "oscilloscope": "∿",
        }
        body = self._hardware_gradient("#fbfcfd", "#c4d1d9")
        painter.setPen(QPen(QColor("#587386"), 1.5))
        painter.setBrush(body)
        painter.drawRoundedRect(QRectF(-53, -32, 93, 64), 8, 8)
        
        painter.setBrush(QColor("#274d63"))
        painter.drawEllipse(QRectF(33, -15, 23, 30))
        painter.setBrush(QColor(theme.COMPONENT_LENS))
        painter.drawEllipse(QRectF(39, -8, 11, 16))
        painter.setBrush(QColor("#9cabb4"))
        painter.drawRoundedRect(QRectF(-40, 33, 68, 9), 3, 3)
        painter.setPen(QColor(theme.PRIMARY))
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)
        painter.drawText(QRectF(-45, -20, 70, 35), Qt.AlignmentFlag.AlignCenter, symbols.get(self.kind, "M"))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_selection_halo(painter)

        
        
        hardware_opacity = 0.50 if self.display_layer == "principle" else 1.0
        painter.save()
        painter.setOpacity(hardware_opacity)
        painter.rotate(self.rotation_deg)
        if self.kind == "laser":
            self._draw_laser(painter)
        elif self.kind == "isolator":
            self._draw_isolator(painter)
        elif self.kind in {"splitter", "pbs", "beam_sampler"}:
            self._draw_splitter(painter)
        elif self.kind == "mirror":
            self._draw_mirror(painter)
        elif self.kind == "aperture":
            self._draw_aperture(painter)
        elif self.kind in {"lens", "half_wave_plate", "beam_expander", "cylindrical_lens"}:
            self._draw_lens(painter)
        elif self.kind == "fiber":
            self._draw_fiber_stage(painter)
        else:
            self._draw_instrument(painter)
        painter.restore()

        painter.setPen(QColor(theme.TEXT_PRIMARY))
        font = QFont(painter.font())
        font.setBold(self.isSelected())
        font.setPointSize(max(9, font.pointSize()))
        painter.setFont(font)
        painter.drawText(
            QRectF(-76, 65, 152, 28),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self.label,
        )

        if self.show_ports:
            painter.setPen(QPen(QColor(theme.PRIMARY), 1.3))
            painter.setBrush(QColor(theme.SURFACE))
            painter.drawEllipse(QPointF(-65, 0), 4.8, 4.8)
            painter.drawEllipse(QPointF(65, 0), 4.8, 4.8)


class OpticalConnectionItem(QGraphicsObject):


    activated = Signal(str)

    def __init__(
        self,
        edge: ExperimentEdge,
        source_item: OpticalNodeItem,
        target_item: OpticalNodeItem,
        reached: bool,
        selected: bool,
        *,
        source_radius: float = 12.0,
        target_radius: float = 12.0,
        ideal_source_radius: float | None = None,
        ideal_target_radius: float | None = None,
        display_layer: str = "overlay",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.edge_id = edge.id
        self.source_item = source_item
        self.target_item = target_item
        self.reached = bool(reached)
        self.selected = bool(selected)
        self.source_radius = max(2.0, float(source_radius))
        self.target_radius = max(2.0, float(target_radius))
        self.ideal_source_radius = max(2.0, float(ideal_source_radius if ideal_source_radius is not None else source_radius))
        self.ideal_target_radius = max(2.0, float(ideal_target_radius if ideal_target_radius is not None else target_radius))
        self.display_layer = display_layer if display_layer in DISPLAY_LAYER_LABELS else "overlay"
        self.setZValue(2.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def update_state(
        self,
        *,
        reached: bool,
        selected: bool,
        source_radius: float,
        target_radius: float,
        ideal_source_radius: float,
        ideal_target_radius: float,
        display_layer: str,
    ) -> None:
        self.prepareGeometryChange()
        self.reached = bool(reached)
        self.selected = bool(selected)
        self.source_radius = max(2.0, float(source_radius))
        self.target_radius = max(2.0, float(target_radius))
        self.ideal_source_radius = max(2.0, float(ideal_source_radius))
        self.ideal_target_radius = max(2.0, float(ideal_target_radius))
        self.display_layer = display_layer if display_layer in DISPLAY_LAYER_LABELS else "overlay"
        self.update()

    def _path(self) -> QPainterPath:
        source = self.source_item.pos()
        target = self.target_item.pos()
        path = QPainterPath(source)
        dx = target.x() - source.x()
        if abs(target.y() - source.y()) < 30:
            path.lineTo(target)
        else:
            bend_x = source.x() + dx * 0.48
            path.cubicTo(QPointF(bend_x, source.y()), QPointF(bend_x, target.y()), target)
        return path

    def _straight_envelope(self, source_radius: float, target_radius: float) -> QPolygonF | None:
        source = self.source_item.pos()
        target = self.target_item.pos()
        dx = target.x() - source.x()
        dy = target.y() - source.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return None
        nx, ny = -dy / length, dx / length
        return QPolygonF([
            QPointF(source.x() + nx * source_radius, source.y() + ny * source_radius),
            QPointF(target.x() + nx * target_radius, target.y() + ny * target_radius),
            QPointF(target.x() - nx * target_radius, target.y() - ny * target_radius),
            QPointF(source.x() - nx * source_radius, source.y() - ny * source_radius),
        ])

    def boundingRect(self) -> QRectF:  
        margin = max(self.source_radius, self.target_radius, self.ideal_source_radius, self.ideal_target_radius) + 22
        return self._path().boundingRect().adjusted(-margin, -margin, margin, margin)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(max(20.0, 2.0 * max(self.source_radius, self.target_radius)))
        return stroker.createStroke(self._path())

    def mousePressEvent(self, event) -> None:  
        self.activated.emit(self.edge_id)
        event.accept()

    def _draw_reference_envelope(self, painter: QPainter) -> None:
        if self.display_layer not in {"principle", "overlay"}:
            return
        source = self.source_item.pos()
        target = self.target_item.pos()
        dx, dy = target.x() - source.x(), target.y() - source.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return
        nx, ny = -dy / length, dx / length
        painter.save()
        painter.setPen(QPen(QColor(33, 118, 180, 175), 1.7, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(source.x() + nx * self.ideal_source_radius, source.y() + ny * self.ideal_source_radius),
            QPointF(target.x() + nx * self.ideal_target_radius, target.y() + ny * self.ideal_target_radius),
        )
        painter.drawLine(
            QPointF(source.x() - nx * self.ideal_source_radius, source.y() - ny * self.ideal_source_radius),
            QPointF(target.x() - nx * self.ideal_target_radius, target.y() - ny * self.ideal_target_radius),
        )
        painter.restore()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = self._path()
        if self.reached:
            
            
            alpha = 42 if self.display_layer == "platform" else 78
            polygon = self._straight_envelope(self.source_radius, self.target_radius)
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            gradient = QLinearGradient(self.source_item.pos(), self.target_item.pos())
            gradient.setColorAt(0.0, QColor(255, 92, 92, max(24, alpha - 18)))
            gradient.setColorAt(0.55, QColor(255, 74, 74, alpha))
            gradient.setColorAt(1.0, QColor(255, 112, 112, max(22, alpha - 22)))
            painter.setBrush(gradient)
            if polygon is not None and abs(self.target_item.pos().y() - self.source_item.pos().y()) < 30:
                painter.drawPolygon(polygon)
            else:
                painter.setPen(QPen(QColor(239, 68, 68, alpha), max(8.0, 1.6 * max(self.source_radius, self.target_radius)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawPath(path)
            painter.restore()

            self._draw_reference_envelope(painter)
            painter.setPen(QPen(QColor(theme.ERROR), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(path)
        else:
            painter.setPen(QPen(QColor(theme.BORDER), 1.5, Qt.PenStyle.DashLine))
            painter.drawPath(path)
        if self.selected:
            painter.setPen(QPen(QColor(theme.CHART_ORANGE), 4.0, Qt.PenStyle.DashLine))
            painter.drawPath(path)


class ExperimentScene(QGraphicsScene):


    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.display_layer = "overlay"

    def set_display_layer(self, layer: str) -> None:
        self.display_layer = layer if layer in DISPLAY_LAYER_LABELS else "overlay"
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(rect, QColor("#10151a"))

        board = SCENE_RECT.adjusted(24, 24, -24, -24)
        board_gradient = QLinearGradient(board.topLeft(), board.bottomRight())
        board_gradient.setColorAt(0.0, QColor("#343c44"))
        board_gradient.setColorAt(1.0, QColor("#1a2026"))
        painter.setPen(QPen(QColor("#58636d"), 2.0))
        painter.setBrush(board_gradient)
        painter.drawRoundedRect(board, 14, 14)

        painter.setPen(QPen(QColor(122, 135, 146, 90), 0.7))
        painter.setBrush(QColor(8, 11, 14, 155))
        for x in range(60, 1561, 40):
            for y in range(70, 841, 40):
                painter.drawEllipse(QPointF(float(x), float(y)), 2.2, 2.2)

        
        painter.setPen(QPen(QColor("#606b74"), 1.0))
        rail_gradient = QLinearGradient(0, MAIN_RAIL_Y - 10, 0, MAIN_RAIL_Y + 10)
        rail_gradient.setColorAt(0.0, QColor("#626b73"))
        rail_gradient.setColorAt(0.5, QColor("#242a2f"))
        rail_gradient.setColorAt(1.0, QColor("#4b545c"))
        painter.setBrush(rail_gradient)
        painter.drawRoundedRect(QRectF(54, MAIN_RAIL_Y - 8, 1492, 16), 7, 7)
        painter.drawRoundedRect(QRectF(54, BRANCH_RAIL_Y - 7, 1492, 14), 6, 6)



class ExperimentGraphicsView(QGraphicsView):
    nodeActivated = Signal(str)
    edgeActivated = Signal(str)
    nodeMoved = Signal(str, float, float)
    blankActivated = Signal()

    def __init__(self, parent=None) -> None:
        self.scene_obj = ExperimentScene()
        super().__init__(self.scene_obj, parent)
        self.setObjectName("teachingMainExperimentView")
        self.setSceneRect(SCENE_RECT)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._node_items: dict[str, OpticalNodeItem] = {}
        self._edge_items: dict[str, OpticalConnectionItem] = {}
        self._model: ExperimentModel | None = None
        self._initial_fit_done = False
        self._auto_fit = True
        self._display_layer = "overlay"
        self._rays_only = False

    @property
    def display_layer(self) -> str:
        return self._display_layer

    def set_display_layer(self, layer: str) -> None:
        layer = layer if layer in DISPLAY_LAYER_LABELS else "overlay"
        if layer == self._display_layer:
            return
        self._display_layer = layer
        self.scene_obj.set_display_layer(layer)
        if self._model is not None:
            self.set_model(self._model, preserve_view=True)

    def set_rays_only(self, enabled: bool) -> None:
        self._rays_only = bool(enabled)
        for item in self._node_items.values():
            item.setVisible(not self._rays_only)
        for item in self._edge_items.values():
            item.setVisible(True)
        self.viewport().update()

    @staticmethod
    def _beam_radii(model: ExperimentModel) -> tuple[dict[str, float], dict[str, float]]:
        metrics = model.evaluate()
        path = list(metrics.path_node_ids)
        current: dict[str, float] = {node_id: 6.0 for node_id in model.nodes}
        ideal: dict[str, float] = {node_id: 6.0 for node_id in model.nodes}
        if not path:
            return current, ideal

        current[path[0]] = 15.0
        ideal[path[0]] = 15.0
        for index, node_id in enumerate(path[:-1]):
            node = model.nodes[node_id]
            target_id = path[index + 1]
            target = model.nodes[target_id]
            radius = current[node_id]
            ideal_radius = ideal[node_id]
            next_radius = radius
            next_ideal = ideal_radius
            if node.kind == "lens":
                focal = float(node.params.get("focal_mm", 50.0))
                if target.kind == "fiber":
                    mismatch_ratio = metrics.predicted_waist_um / max(metrics.target_waist_um, 0.2)
                    next_radius = max(3.2, min(13.0, 4.8 * mismatch_ratio))
                    next_ideal = 4.8
                else:
                    next_radius = max(9.0, min(30.0, 8.0 + focal * 0.14))
                    next_ideal = max(10.0, min(26.0, 9.0 + focal * 0.11))
            elif target.kind == "fiber":
                next_radius = max(3.5, min(12.0, 4.8 * metrics.predicted_waist_um / max(metrics.target_waist_um, 0.2)))
                next_ideal = 4.8
            elif target.kind == "power_meter" and node.kind == "fiber":
                next_radius = 3.2
                next_ideal = 3.2
            elif target.kind == "lens":
                next_radius = max(12.0, radius)
                next_ideal = max(12.0, ideal_radius)
            current[target_id] = next_radius
            ideal[target_id] = next_ideal

        
        for edge in model.edges.values():
            if edge.source in path and edge.target not in path:
                current[edge.target] = 6.0
                ideal[edge.target] = 6.0
        return current, ideal

    def set_model(
        self,
        model: ExperimentModel,
        *,
        preserve_view: bool = True,
        snapshot: TeachingSceneSnapshot | None = None,
    ) -> None:
        transform = self.transform()
        center_scene = self.mapToScene(self.viewport().rect().center())
        self._model = model
        self.scene_obj.set_display_layer(self._display_layer)
        snapshot = snapshot or model.scene_snapshot()
        metrics = snapshot.metrics
        reached = set(metrics.reached_node_ids)
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
            node_movable = movable and not (model.mode == "layout" and node.kind in {"laser", "isolator", "splitter"})
            item = self._node_items.get(node.id)
            if item is None or item.kind != node.kind:
                if item is not None:
                    self.scene_obj.removeItem(item)
                    item.deleteLater()
                item = OpticalNodeItem(node, node_movable, display_layer=self._display_layer, show_ports=model.mode == "free")
                item.activated.connect(self.nodeActivated)
                item.positionChanged.connect(self._on_item_position_changed)
                item.movementFinished.connect(self.nodeMoved)
                self.scene_obj.addItem(item)
                self._node_items[node.id] = item
            else:
                item.update_from_node(node, movable=node_movable, display_layer=self._display_layer, show_ports=model.mode == "free")
            item.setSelected(node.id == model.selected_node_id)
            item.setVisible(not self._rays_only)

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
                item = OpticalConnectionItem(edge, source, target, False, False)
                item.activated.connect(self.edgeActivated)
                self.scene_obj.addItem(item)
                self._edge_items[edge.id] = item
            item.update_state(
                reached=edge.source in reached and edge.target in reached,
                selected=edge.id == model.selected_edge_id,
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

    def _on_item_position_changed(self, node_id: str) -> None:
        for edge in self._edge_items.values():
            if edge.source_item.node_id == node_id or edge.target_item.node_id == node_id:
                edge.prepareGeometryChange()
                edge.update()

    def _fit_content(self) -> None:
        content = self.scene_obj.itemsBoundingRect()
        if content.isNull() or content.width() < 10 or content.height() < 10:
            content = SCENE_RECT
        margin_x = max(110.0, content.width() * 0.08)
        margin_y = max(100.0, content.height() * 0.18)
        self.fitInView(content.adjusted(-margin_x, -margin_y, margin_x, margin_y), Qt.AspectRatioMode.KeepAspectRatio)
        self._initial_fit_done = True

    def fit_full(self) -> None:
        self._auto_fit = True
        self._fit_content()

    def zoom_in(self) -> None:
        self._auto_fit = False
        if self.transform().m11() < 2.5:
            self.scale(1.15, 1.15)

    def zoom_out(self) -> None:
        self._auto_fit = False
        if self.transform().m11() > 0.34:
            self.scale(1.0 / 1.15, 1.0 / 1.15)

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        
        
        if self._auto_fit:
            safe_single_shot(self, 0, self._fit_content)

    def focus_node(self, node_id: str) -> None:
        item = self._node_items.get(node_id)
        if item is None:
            return
        self._auto_fit = False
        self.centerOn(item)
        if self.transform().m11() < 0.65:
            self.scale(1.25, 1.25)

    def wheelEvent(self, event) -> None:  
        self._auto_fit = False
        factor = 1.14 if event.angleDelta().y() > 0 else 1.0 / 1.14
        new_scale = self.transform().m11() * factor
        if 0.32 <= new_scale <= 2.6:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  
        if self.itemAt(event.position().toPoint()) is None:
            self.blankActivated.emit()
        super().mousePressEvent(event)


class Experiment3DView(QWidget):
    objectActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingExperiment3DView")
        self.setMinimumSize(600, 380)
        self._model: ExperimentModel | None = None
        self._metrics: WorkbenchMetrics | None = None
        self._hit_boxes: dict[str, QRectF] = {}
        self._azimuth = 0.0
        self._display_layer = "overlay"
        self._rays_only = False

    def set_model(self, model: ExperimentModel, snapshot: TeachingSceneSnapshot | None = None) -> None:
        self._model = model
        self._metrics = (snapshot or model.scene_snapshot()).metrics
        self.update()

    def set_display_layer(self, layer: str) -> None:
        self._display_layer = layer if layer in DISPLAY_LAYER_LABELS else "overlay"
        self.update()

    def set_rays_only(self, enabled: bool) -> None:
        self._rays_only = bool(enabled)
        self.update()

    def rotate_camera(self, degrees: float) -> None:
        self._azimuth = (self._azimuth + degrees) % 360.0
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  
        for node_id, rect in self._hit_boxes.items():
            if rect.contains(event.position()):
                self.objectActivated.emit(node_id)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(241, 244, 248))
        width = float(self.width())
        height = float(self.height())
        margin = max(34.0, min(width, height) * 0.045)
        table = QPolygonF(
            [
                QPointF(margin, height * 0.22),
                QPointF(width * 0.86, height * 0.11),
                QPointF(width - margin, height * 0.78),
                QPointF(width * 0.12, height * 0.90),
            ]
        )
        painter.setPen(QPen(QColor(22, 31, 42), 2.2))
        painter.setBrush(QColor(37, 47, 59))
        painter.drawPolygon(table)

        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(92, 108, 124))
        for iu in range(1, 18):
            u = iu / 18.0
            for iv in range(1, 11):
                v = iv / 11.0
                top = table[0] * (1 - u) + table[1] * u
                bottom = table[3] * (1 - u) + table[2] * u
                point = top * (1 - v) + bottom * v
                painter.drawEllipse(point, 1.7, 1.7)

        if self._model is None:
            return
        reached = set(self._metrics.reached_node_ids if self._metrics else ())
        projected: dict[str, QPointF] = {}
        for node in self._model.nodes.values():
            u = max(0.0, min(1.0, node.x / SCENE_RECT.width()))
            v = max(0.0, min(1.0, node.y / SCENE_RECT.height()))
            top = table[0] * (1 - u) + table[1] * u
            bottom = table[3] * (1 - u) + table[2] * u
            projected[node.id] = top * (1 - v) + bottom * v

        
        def project_xy(x: float, y: float) -> QPointF:
            u = max(0.0, min(1.0, x / SCENE_RECT.width()))
            v = max(0.0, min(1.0, y / SCENE_RECT.height()))
            top = table[0] * (1 - u) + table[1] * u
            bottom = table[3] * (1 - u) + table[2] * u
            return top * (1 - v) + bottom * v
        painter.setPen(QPen(QColor(168, 184, 199), 1.2, Qt.PenStyle.DashLine))
        painter.drawLine(project_xy(0, MAIN_RAIL_Y), project_xy(SCENE_RECT.width(), MAIN_RAIL_Y))

        
        for edge in self._model.edges.values():
            if edge.source not in projected or edge.target not in projected:
                continue
            active = edge.source in reached and edge.target in reached
            start_point, end_point = projected[edge.source], projected[edge.target]
            if active:
                if self._display_layer in {"principle", "overlay"}:
                    painter.setPen(QPen(QColor(251, 113, 133, 58), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.drawLine(start_point, end_point)
                painter.setPen(QPen(QColor(239, 68, 68), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            else:
                painter.setPen(QPen(QColor(122, 139, 156), 1.2, Qt.PenStyle.DashLine))
            painter.drawLine(start_point, end_point)

        self._hit_boxes = {}
        nodes_to_draw = [] if self._rays_only else sorted(self._model.nodes.values(), key=lambda item: item.y)
        for node in nodes_to_draw:
            point = projected[node.id]
            selected = node.id == self._model.selected_node_id
            outline = QColor(16, 185, 255) if selected else QColor(10, 16, 24)
            fill = QColor(31, 46, 59) if not selected else QColor(27, 76, 105)
            painter.setPen(QPen(outline, 2.5 if selected else 1.5))
            painter.setBrush(fill)
            kind = node.kind
            if kind == "lens":
                painter.setBrush(QColor(23, 109, 145, 205))
                painter.drawEllipse(QRectF(point.x() - 12, point.y() - 39, 24, 64))
                painter.setPen(QPen(QColor(31, 191, 255), 1.4))
                painter.drawEllipse(QRectF(point.x() - 9, point.y() - 36, 18, 58))
                painter.setPen(QPen(outline, 1.5))
                painter.drawLine(QPointF(point.x(), point.y() + 25), QPointF(point.x(), point.y() + 39))
                painter.drawRoundedRect(QRectF(point.x() - 22, point.y() + 38, 44, 7), 2, 2)
            elif kind in {"splitter", "pbs", "beam_sampler"}:
                rect = QRectF(point.x() - 24, point.y() - 24, 48, 48)
                painter.drawRoundedRect(rect, 4, 4)
                painter.setPen(QPen(QColor(111, 211, 255), 1.8))
                painter.drawLine(rect.topLeft() + QPointF(5, 5), rect.bottomRight() - QPointF(5, 5))
                painter.setPen(QPen(outline, 1.4))
                painter.drawRoundedRect(QRectF(point.x() - 31, point.y() - 31, 62, 62), 5, 5)
            elif kind == "mirror":
                painter.save()
                painter.translate(point)
                painter.rotate(float(node.rotation_deg))
                painter.setBrush(QColor(154, 171, 188))
                painter.drawRoundedRect(QRectF(-4, -34, 8, 68), 2, 2)
                painter.restore()
                painter.drawLine(QPointF(point.x(), point.y() + 20), QPointF(point.x(), point.y() + 38))
                painter.drawRoundedRect(QRectF(point.x() - 20, point.y() + 37, 40, 7), 2, 2)
            elif kind == "fiber":
                painter.drawRoundedRect(QRectF(point.x() - 30, point.y() - 25, 50, 50), 7, 7)
                painter.setBrush(QColor(112, 136, 154))
                painter.drawEllipse(QRectF(point.x() + 12, point.y() - 8, 22, 16))
                painter.setBrush(QColor(20, 29, 39))
                painter.drawRoundedRect(QRectF(point.x() - 13, point.y() - 38, 22, 14), 5, 5)
            elif kind in INSTRUMENT_TYPES:
                painter.drawRoundedRect(QRectF(point.x() - 30, point.y() - 23, 48, 46), 7, 7)
                painter.setBrush(QColor(118, 147, 166))
                painter.drawRoundedRect(QRectF(point.x() + 12, point.y() - 7, 25, 14), 3, 3)
                if node.id in reached:
                    painter.setBrush(QColor(34, 197, 94))
                    painter.drawEllipse(QPointF(point.x() - 21, point.y() - 13), 3.5, 3.5)
            elif kind == "laser":
                painter.drawRoundedRect(QRectF(point.x() - 31, point.y() - 19, 53, 38), 6, 6)
                painter.setBrush(QColor(224, 57, 57))
                painter.drawEllipse(QRectF(point.x() + 17, point.y() - 6, 15, 12))
            else:
                painter.drawRoundedRect(QRectF(point.x() - 25, point.y() - 18, 50, 36), 5, 5)
            painter.setPen(QColor(238, 243, 248))
            label_rect = QRectF(point.x() - 64, point.y() + 45, 128, 25)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, node.label)
            self._hit_boxes[node.id] = QRectF(point.x() - 44, point.y() - 48, 88, 112)

        
        origin = QPointF(48, height - 44)
        painter.setPen(QPen(QColor(220, 38, 38), 2.2))
        painter.drawLine(origin, origin + QPointF(28, 0))
        painter.drawText(origin + QPointF(32, 5), "X")
        painter.setPen(QPen(QColor(22, 163, 74), 2.2))
        painter.drawLine(origin, origin + QPointF(0, -28))
        painter.drawText(origin + QPointF(-4, -33), "Y")
        painter.setPen(QPen(QColor(37, 99, 235), 2.2))
        painter.drawLine(origin, origin + QPointF(20, -18))
        painter.drawText(origin + QPointF(23, -20), "Z")
        painter.setPen(QColor(22, 31, 42))
        font = painter.font()
        font.setPointSize(max(11, font.pointSize()))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(24, 16, width - 48, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "三维光学布局")


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------


class OverlayDrawer(QFrame):
    closed = Signal()

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingOverlayDrawer")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(7)
        head = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("drawerTitle")
        head.addWidget(self.title_label, 1)
        close = QToolButton()
        close.setText("×")
        close.setToolTip("收起")
        close.clicked.connect(self.hide)
        close.clicked.connect(self.closed)
        head.addWidget(close)
        layout.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        self.hide()

    def clear_body(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class FloatingPanel(QFrame):
    closed = Signal(str)

    def __init__(self, key: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self._drag_origin: QPoint | None = None
        self._drag_global: QPoint | None = None
        self._collapsed = False
        self.setObjectName("teachingFloatingPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(360, 230)
        self.resize(520, 390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(6)
        self.title_bar = QFrame()
        self.title_bar.setObjectName("floatingTitleBar")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(4, 0, 2, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("floatingTitle")
        title_layout.addWidget(self.title_label, 1)
        self.collapse_button = QToolButton()
        self.collapse_button.setText("—")
        self.collapse_button.setToolTip("最小化/恢复")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        title_layout.addWidget(self.collapse_button)
        close = QToolButton()
        close.setText("×")
        close.setToolTip("关闭")
        close.clicked.connect(self._close)
        title_layout.addWidget(close)
        layout.addWidget(self.title_bar)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(2, 2, 2, 2)
        self.content_layout.setSpacing(7)
        layout.addWidget(self.content, 1)
        self.title_bar.installEventFilter(self)
        self.hide()

    def _close(self) -> None:
        self.hide()
        self.closed.emit(self.key)

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.content.setVisible(not self._collapsed)
        if self._collapsed:
            self.setMinimumHeight(42)
            self.resize(self.width(), 46)
        else:
            self.setMinimumHeight(230)
            self.resize(self.width(), max(300, self.height()))

    def eventFilter(self, watched, event) -> bool:  
        if watched is self.title_bar:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = self.pos()
                self._drag_global = event.globalPosition().toPoint()
                self.raise_()
                return True
            if event.type() == event.Type.MouseMove and self._drag_origin is not None and self._drag_global is not None:
                delta = event.globalPosition().toPoint() - self._drag_global
                target = self._drag_origin + delta
                parent_rect = self.parentWidget().rect() if self.parentWidget() else QRectF(0, 0, 9999, 9999).toRect()
                target.setX(max(0, min(target.x(), parent_rect.width() - self.width())))
                target.setY(max(0, min(target.y(), parent_rect.height() - self.height())))
                self.move(target)
                return True
            if event.type() == event.Type.MouseButtonRelease:
                self._drag_origin = None
                self._drag_global = None
                return True
        return super().eventFilter(watched, event)

    def clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------


class SpotDistributionWidget(QWidget):
    def __init__(self, reading: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.reading = reading
        self.setMinimumHeight(170)

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))
        area = QRectF(self.rect()).adjusted(18, 12, -18, -18)
        center = area.center()
        radius = min(area.width(), area.height()) * 0.37
        painter.setPen(QPen(QColor(theme.BORDER), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawEllipse(center, radius, radius)
        dx = float(self.reading.get("center_x_um", 0.0)) * 5.0
        dy = float(self.reading.get("center_y_um", 0.0)) * 5.0
        rx = max(8.0, min(radius * 0.9, float(self.reading.get("radius_x_um", 3.0)) * 7.0))
        ry = max(8.0, min(radius * 0.9, float(self.reading.get("radius_y_um", 3.0)) * 7.0))
        gradient = QLinearGradient(QPointF(center.x() - rx, center.y()), QPointF(center.x() + rx, center.y()))
        gradient.setColorAt(0.0, QColor(35, 94, 196, 80))
        gradient.setColorAt(0.5, QColor(242, 67, 54, 220))
        gradient.setColorAt(1.0, QColor(35, 94, 196, 80))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(center.x() + dx, center.y() + dy), rx, ry)
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY), 1))
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))


class WavefrontMapWidget(QWidget):
    def __init__(self, reading: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.reading = reading
        self.setMinimumHeight(180)

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))
        area = QRectF(self.rect()).adjusted(20, 15, -20, -20)
        center = area.center()
        radius = min(area.width(), area.height()) * 0.39
        curvature = float(self.reading.get("curvature_waves", 0.0))
        tilt_x = float(self.reading.get("tilt_x_mrad", 0.0))
        tilt_y = float(self.reading.get("tilt_y_mrad", 0.0))
        for index in range(10, 0, -1):
            t = index / 10.0
            color = QColor.fromHsvF((0.65 - 0.55 * t + curvature * 0.08) % 1.0, 0.75, 0.95, 0.88)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            shift_x = tilt_x * 0.9 * (1 - t)
            shift_y = tilt_y * 0.9 * (1 - t)
            rr = radius * t
            painter.drawEllipse(QPointF(center.x() + shift_x, center.y() + shift_y), rr, rr)
        painter.setPen(QPen(QColor(theme.SURFACE), 1.2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))


class ScopeTraceWidget(QWidget):
    def __init__(self, reading: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.reading = reading
        self.setMinimumHeight(160)

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0d2230"))
        area = QRectF(self.rect()).adjusted(12, 10, -12, -10)
        painter.setPen(QPen(QColor(92, 132, 154, 90), 1))
        for i in range(1, 10):
            x = area.left() + area.width() * i / 10
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        for i in range(1, 6):
            y = area.top() + area.height() * i / 6
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        amplitude = min(0.42, 0.08 + float(self.reading.get("amplitude_v", self.reading.get("signal_v", 0.4))) * 0.02)
        path = QPainterPath()
        for i in range(240):
            t = i / 239.0
            x = area.left() + area.width() * t
            y = area.center().y() - area.height() * amplitude * math.sin(2 * math.pi * (3.2 * t)) - area.height() * 0.03 * math.sin(2 * math.pi * 31 * t)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor(theme.SUCCESS), 2.0))
        painter.drawPath(path)


class MismatchTripleView(QWidget):


    def __init__(self, model: ExperimentModel, mismatch: str = "curvature", parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.mismatch = mismatch
        self.setMinimumHeight(280)

    def set_mismatch(self, mismatch: str) -> None:
        self.mismatch = str(mismatch)
        self.update()

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        width = float(self.width())
        height = float(self.height())
        gap = 14.0
        col = (width - gap * 4) / 3.0
        panels = [QRectF(gap + i * (col + gap), 16, col, height - 32) for i in range(3)]
        titles = ["传播位置", "光纤端面", "效率趋势"]
        for rect, title in zip(panels, titles):
            painter.setPen(QPen(QColor(theme.DIVIDER), 1.2))
            painter.setBrush(QColor(theme.SURFACE_MUTED))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor(theme.PRIMARY_DARK))
            font = QFont(painter.font())
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(rect.left() + 8, rect.top() + 7, rect.width() - 16, 24), Qt.AlignmentFlag.AlignCenter, title)

        fiber = next((node for node in self.model.nodes.values() if node.kind == "fiber"), None)
        fp = fiber.params if fiber else {}
        value = {
            "lateral": math.hypot(float(fp.get("offset_x_um", 0.0)), float(fp.get("offset_y_um", 0.0))),
            "defocus": abs(float(fp.get("offset_z_um", 0.0))),
            "angle": math.hypot(float(fp.get("pitch_mrad", 0.0)), float(fp.get("yaw_mrad", 0.0))),
            "size": abs(self.model.evaluate().predicted_waist_um - self.model.evaluate().target_waist_um),
            "curvature": abs(float(fp.get("curvature_waves", 0.0))),
        }.get(self.mismatch, 0.0)

        
        r = panels[0].adjusted(16, 42, -16, -16)
        axis_y = r.center().y()
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY), 1.2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(r.left(), axis_y), QPointF(r.right(), axis_y))
        lens_x = r.left() + r.width() * 0.35
        fiber_x = r.right() - 24
        painter.setPen(QPen(QColor(theme.PRIMARY), 2))
        painter.setBrush(QColor(135, 209, 240, 100))
        painter.drawEllipse(QRectF(lens_x - 8, axis_y - 42, 16, 84))
        if self.mismatch == "angle":
            y_end = axis_y - min(48.0, value * 1.7)
            painter.setPen(QPen(QColor(theme.ERROR), 3))
            painter.drawLine(QPointF(r.left(), axis_y + 18), QPointF(fiber_x, y_end))
            painter.setPen(QPen(QColor(theme.PRIMARY), 2, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(r.left(), axis_y), QPointF(fiber_x, axis_y))
        else:
            path = QPainterPath(QPointF(r.left(), axis_y - 22))
            path.lineTo(QPointF(lens_x, axis_y - 22))
            path.lineTo(QPointF(fiber_x, axis_y - 5))
            path.lineTo(QPointF(fiber_x, axis_y + 5))
            path.lineTo(QPointF(lens_x, axis_y + 22))
            path.lineTo(QPointF(r.left(), axis_y + 22))
            path.closeSubpath()
            painter.setPen(QPen(QColor(239, 68, 68, 100), 1))
            painter.setBrush(QColor(239, 68, 68, 55))
            painter.drawPath(path)
            if self.mismatch == "curvature":
                painter.setPen(QPen(QColor(theme.ERROR), 2))
                bend = min(24.0, value * 45.0)
                painter.drawArc(QRectF(fiber_x - 18 - bend, axis_y - 34, 36 + 2 * bend, 68), -70 * 16, 140 * 16)
                painter.setPen(QPen(QColor(theme.PRIMARY), 2, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(fiber_x - 4, axis_y - 34), QPointF(fiber_x - 4, axis_y + 34))
        painter.setPen(QPen(QColor(theme.TEXT_SECONDARY), 2))
        painter.drawLine(QPointF(fiber_x, axis_y - 48), QPointF(fiber_x, axis_y + 48))

        
        r = panels[1].adjusted(18, 42, -18, -18)
        center = r.center()
        rad = min(r.width(), r.height()) * 0.35
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawEllipse(center, rad, rad)
        if self.mismatch == "curvature":
            for idx in range(9, 0, -1):
                t = idx / 9.0
                painter.setBrush(QColor.fromHsvF((0.68 - 0.58 * t + value * 0.07) % 1.0, 0.8, 0.95, 0.85))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, rad * t, rad * t)
        else:
            dx = float(fp.get("offset_x_um", 0.0)) * 7.0
            dy = float(fp.get("offset_y_um", 0.0)) * 7.0
            if self.mismatch == "angle":
                dx += float(fp.get("pitch_mrad", 0.0)) * 1.6
                dy += float(fp.get("yaw_mrad", 0.0)) * 1.6
            painter.setPen(Qt.PenStyle.NoPen)
            gradient = QLinearGradient(QPointF(center.x() - rad, center.y()), QPointF(center.x() + rad, center.y()))
            gradient.setColorAt(0.0, QColor(41, 99, 193, 70))
            gradient.setColorAt(0.5, QColor(239, 68, 68, 220))
            gradient.setColorAt(1.0, QColor(41, 99, 193, 70))
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(center.x() + dx, center.y() + dy), rad * 0.55, rad * 0.55)

        
        r = panels[2].adjusted(34, 48, -18, -32)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1))
        painter.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))
        painter.drawLine(QPointF(r.left(), r.top()), QPointF(r.left(), r.bottom()))
        painter.setPen(QPen(QColor("#1f77b4"), 2.6))
        path = QPainterPath()
        for i in range(100):
            x_norm = -3.0 + 6.0 * i / 99.0
            if self.mismatch == "curvature":
                eta = 1.0 / (1.0 + (math.pi * x_norm / 2.4) ** 2)
            else:
                eta = math.exp(-0.5 * x_norm**2)
            x = r.left() + r.width() * i / 99.0
            y = r.bottom() - r.height() * eta
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)
        marker_norm = min(1.0, value / ({"angle": 35.0, "curvature": 0.5, "defocus": 80.0, "lateral": 5.0, "size": 5.0}.get(self.mismatch, 1.0)))
        marker_x = r.center().x() + marker_norm * r.width() * 0.43
        painter.setPen(QPen(QColor(theme.ERROR), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(marker_x, r.top()), QPointF(marker_x, r.bottom()))
        metrics = self.model.evaluate()
        painter.setPen(QColor(theme.ERROR))
        painter.drawText(QRectF(r.left(), r.bottom() + 5, r.width(), 22), Qt.AlignmentFlag.AlignCenter, f"当前接收效率 {metrics.receiver_efficiency * 100:.1f}%")


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------


class UnifiedTeachingWorkbench(QWidget):
    navigateRequested = Signal(str)
    profileReady = Signal(dict)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.settings = QSettings("Optical ML Platform", "OpticalFrontend")
        self.model = ExperimentModel()
        self._mode_snapshots: dict[str, dict[str, Any]] = {}
        self._view_kind = "2d"
        self._display_layer = "overlay"
        self._floating_panels: dict[str, FloatingPanel] = {}
        self._left_drawer_key: str | None = None
        self._right_drawer_key: str | None = None
        self._connect_mode = False
        self._building_form = False

        self.setObjectName("unifiedTeachingWorkbench")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title = QLabel("光纤耦合教学中心")
        title.setObjectName("pageTitle")
        title_block.addWidget(title)
        header.addLayout(title_block, 1)
        header.addWidget(Badge("教学近似模式", "warning"))
        self.save_parameters_button = SecondaryButton("保存参数")
        self.save_parameters_button.setToolTip("保存当前教学方案，供教学中心和正式工作台继续使用")
        self.save_parameters_button.clicked.connect(self._save_shared_parameters)
        header.addWidget(self.save_parameters_button)
        self.import_workbench_button = SecondaryButton("读取工作台")
        self.import_workbench_button.setToolTip("读取正式工作台最近保存的结构和参数")
        self.import_workbench_button.clicked.connect(self._import_workbench_parameters)
        header.addWidget(self.import_workbench_button)
        self.enter_workbench_button = PrimaryButton("进入工作台")
        self.enter_workbench_button.clicked.connect(self._enter_formal_workbench)
        header.addWidget(self.enter_workbench_button)
        root.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        self.model.mode = "free"
        self.view_2d_button = SecondaryButton("2D平台")
        self.view_2d_button.setCheckable(True)
        self.view_2d_button.clicked.connect(lambda: self.set_view_kind("2d"))
        toolbar.addWidget(self.view_2d_button)
        self.view_3d_button = SecondaryButton("3D空间")
        self.view_3d_button.setCheckable(True)
        self.view_3d_button.clicked.connect(lambda: self.set_view_kind("3d"))
        toolbar.addWidget(self.view_3d_button)
        toolbar.addSpacing(10)
        
        
        self.display_layer_group = QButtonGroup(self)
        self.display_layer_group.setExclusive(True)
        self.display_layer_buttons: dict[str, QPushButton] = {}
        toolbar.addStretch(1)
        self.mode_description = QLabel("")
        self.mode_description.hide()
        root.addLayout(toolbar)

        self.overlay_host = QWidget()
        self.overlay_host.setObjectName("teachingOverlayHost")
        self.overlay_host.setMinimumHeight(520)
        host_layout = QVBoxLayout(self.overlay_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        self.view_stack = QStackedWidget()
        self.graphics_view = ExperimentGraphicsView()
        self.view_3d = Experiment3DView()
        self.view_stack.addWidget(self.graphics_view)
        self.view_stack.addWidget(self.view_3d)
        host_layout.addWidget(self.view_stack)
        root.addWidget(self.overlay_host, 1)

        self.graphics_view.nodeActivated.connect(self._on_node_activated)
        self.graphics_view.edgeActivated.connect(self._on_edge_activated)
        self.graphics_view.nodeMoved.connect(self._on_node_moved)
        self.graphics_view.blankActivated.connect(self._on_blank_activated)
        self.view_3d.objectActivated.connect(self._on_node_activated)

        self.left_drawer = OverlayDrawer("工具与设置", self.overlay_host)
        self.right_drawer = OverlayDrawer("当前对象", self.overlay_host)

        self._create_overlay_buttons()

        
        status = QHBoxLayout()
        status.setSpacing(12)
        self.total_metric = QLabel()
        self.total_metric.setObjectName("teachingPrimaryMetric")
        status.addWidget(self.total_metric)
        self.system_metric = QLabel()
        status.addWidget(self.system_metric)
        self.receiver_metric = QLabel()
        status.addWidget(self.receiver_metric)
        self.feasible_metric = QLabel()
        status.addWidget(self.feasible_metric)
        status.addStretch(1)
        self.undo_button = SecondaryButton("撤销")
        self.undo_button.clicked.connect(self._undo)
        status.addWidget(self.undo_button)
        self.redo_button = SecondaryButton("重做")
        self.redo_button.clicked.connect(self._redo)
        status.addWidget(self.redo_button)
        self.baseline_button = SecondaryButton("设为基线")
        self.baseline_button.clicked.connect(self._set_baseline)
        status.addWidget(self.baseline_button)
        self.restore_baseline_button = SecondaryButton("恢复基线")
        self.restore_baseline_button.clicked.connect(self._restore_baseline)
        status.addWidget(self.restore_baseline_button)
        self.save_scheme_button = PrimaryButton("保存方案")
        self.save_scheme_button.clicked.connect(self._save_scheme)
        status.addWidget(self.save_scheme_button)
        root.addLayout(status)

        
        
        self.cause_bar = QLabel()
        self.cause_bar.hide()

        self._apply_local_style()
        self.set_mode("standard", force=True)
        self.set_view_kind("2d")
        self.set_display_layer("overlay", force=True)
        safe_single_shot(self, 0, self._restore_persisted_snapshot)

    
    def _create_overlay_buttons(self) -> None:
        self.left_buttons: list[QToolButton] = []
        self.right_buttons: list[QToolButton] = []
        left_specs = [
            ("器材", lambda: self._open_left_drawer("library")),
            ("设置", lambda: self._open_left_drawer("settings")),
            ("方案", lambda: self._open_left_drawer("schemes")),
        ]
        right_specs = [
            ("当前对象", lambda: self._open_right_drawer("object")),
            ("测量结果", self._open_measurement_panel),
            ("原理分析", self._open_principle_panel),
            ("智能建议", self._open_smart_panel),
        ]
        for text, callback in left_specs:
            button = QToolButton(self.overlay_host)
            button.setObjectName("teachingOverlayButton")
            button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(callback)
            button.raise_()
            self.left_buttons.append(button)
        for text, callback in right_specs:
            button = QToolButton(self.overlay_host)
            button.setObjectName("teachingOverlayButton")
            button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(callback)
            button.raise_()
            self.right_buttons.append(button)

        self.bottom_buttons: list[QToolButton] = []
        for text, callback in [
            ("参数优化", self._open_optimization_panel),
            ("智能分析", self._open_smart_panel),
            ("方案比较", self._open_compare_panel),
            ("设计记录", self._open_log_panel),
        ]:
            button = QToolButton(self.overlay_host)
            button.setObjectName("teachingBottomOverlayButton")
            button.setText(text)
            button.clicked.connect(callback)
            button.raise_()
            self.bottom_buttons.append(button)

        self.view_control_buttons: list[QToolButton] = []
        for text, tooltip, callback in [
            ("全图", "适合全图", self.graphics_view.fit_full),
            ("聚焦", "聚焦当前选中元件", self._focus_selected_node),
            ("＋", "放大主实验平台", self.graphics_view.zoom_in),
            ("－", "缩小主实验平台", self.graphics_view.zoom_out),
        ]:
            button = QToolButton(self.overlay_host)
            button.setObjectName("teachingViewControlButton")
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            button.raise_()
            self.view_control_buttons.append(button)
        self.rays_only_button = QToolButton(self.overlay_host)
        self.rays_only_button.setObjectName("teachingViewControlButton")
        self.rays_only_button.setText("光线")
        self.rays_only_button.setToolTip("隐藏器件只查看光线；再次点击恢复叠加显示")
        self.rays_only_button.setCheckable(True)
        self.rays_only_button.toggled.connect(self._toggle_rays_only)
        self.rays_only_button.raise_()
        self.view_control_buttons.append(self.rays_only_button)

    def _toggle_rays_only(self, checked: bool) -> None:

        self.graphics_view.set_rays_only(bool(checked))
        if hasattr(self.view_3d, "set_rays_only"):
            self.view_3d.set_rays_only(bool(checked))
        self.rays_only_button.setToolTip(
            "恢复器件与光线叠加显示" if checked else "隐藏器件只查看光线"
        )

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        w = self.overlay_host.width()
        h = self.overlay_host.height()
        y0 = 18
        for index, button in enumerate(self.left_buttons):
            button.setGeometry(12, y0 + index * 46, 92, 38)
            button.raise_()
        for index, button in enumerate(self.right_buttons):
            button.setGeometry(max(0, w - 116), y0 + index * 46, 104, 38)
            button.raise_()
        total_width = len(self.bottom_buttons) * 104 + (len(self.bottom_buttons) - 1) * 6
        start_x = max(110, (w - total_width) // 2)
        for index, button in enumerate(self.bottom_buttons):
            button.setGeometry(start_x + index * 110, max(0, h - 52), 104, 38)
            button.raise_()
        widths = [58 if button.text() in {"全图", "聚焦", "光线"} else 46 for button in self.view_control_buttons]
        view_total_width = sum(widths) + max(0, len(widths) - 1) * 4
        view_start_x = max(120, w - view_total_width - 136)
        cursor_x = view_start_x
        for button, button_width in zip(self.view_control_buttons, widths):
            button.setGeometry(cursor_x, max(8, h - 98), button_width, 34)
            button.raise_()
            cursor_x += button_width + 4
        drawer_h = max(280, h - 36)
        
        
        
        left_width = min(620, max(500, int(w * 0.44)))
        left_width = min(left_width, max(360, w - 150))
        right_width = min(430, max(350, w // 3))
        self.left_drawer.setGeometry(112, 18, left_width, drawer_h)
        self.right_drawer.setGeometry(max(0, w - right_width - 122), 18, right_width, drawer_h)
        if self.left_drawer.isVisible():
            self.left_drawer.raise_()
        if self.right_drawer.isVisible():
            self.right_drawer.raise_()
        for panel in self._floating_panels.values():
            panel.raise_()

    
    def set_mode(self, mode: str, *, force: bool = False) -> None:
        del mode, force
        self.model.mode = "free"
        self._connect_mode = False
        self.model.connect_source_id = None
        self._refresh_all(preserve_view=True)

    def set_view_kind(self, kind: str) -> None:
        self._view_kind = "3d" if str(kind).lower() == "3d" else "2d"
        self.view_stack.setCurrentIndex(1 if self._view_kind == "3d" else 0)
        self.view_2d_button.setChecked(self._view_kind == "2d")
        self.view_3d_button.setChecked(self._view_kind == "3d")
        self._refresh_views(preserve_view=True)

    def set_display_layer(self, layer: str, *, force: bool = False) -> None:
        layer = layer if layer in DISPLAY_LAYER_LABELS else "overlay"
        if not force and layer == self._display_layer:
            return
        self._display_layer = layer
        button = self.display_layer_buttons.get(layer)
        if button is not None:
            button.setChecked(True)
        self.graphics_view.set_display_layer(layer)
        if hasattr(self.view_3d, "set_display_layer"):
            self.view_3d.set_display_layer(layer)
        self.model.latest_cause = f"切换到{DISPLAY_LAYER_LABELS[layer]}，实验结构和方案参数保持不变。"
        self._refresh_all(preserve_view=True)

    def _focus_selected_node(self) -> None:
        node_id = self.model.selected_node_id
        if node_id:
            self.graphics_view.focus_node(node_id)

    
    def _refresh_views(
        self,
        *,
        preserve_view: bool = True,
        snapshot: TeachingSceneSnapshot | None = None,
    ) -> None:
        snapshot = snapshot or self.model.scene_snapshot()
        self.graphics_view.set_model(self.model, preserve_view=preserve_view, snapshot=snapshot)
        self.view_3d.set_model(self.model, snapshot=snapshot)

    def _refresh_all(self, *, preserve_view: bool = True) -> None:
        snapshot = self.model.scene_snapshot()
        metrics = snapshot.metrics
        self._refresh_views(preserve_view=preserve_view, snapshot=snapshot)
        self.total_metric.setText(f"总效率  {metrics.total_efficiency * 100:.1f}%")
        self.system_metric.setText(f"系统效率 {metrics.system_efficiency * 100:.1f}%")
        self.receiver_metric.setText(f"接收效率 {metrics.receiver_efficiency * 100:.1f}%")
        self.feasible_metric.setText("工程可实现：通过" if metrics.feasible else "工程可实现：需检查")
        self.undo_button.setEnabled(self.model.can_undo())
        self.redo_button.setEnabled(self.model.can_redo())
        if self.right_drawer.isVisible():
            if self._right_drawer_key == "object":
                self._populate_object_drawer()
            elif self._right_drawer_key == "measurement":
                self._populate_measurement_drawer()
        self._refresh_open_panels()
        self._position_overlays()

    def _refresh_open_panels(self) -> None:
        for key, panel in list(self._floating_panels.items()):
            if not panel.isVisible():
                continue
            if key == "measurement":
                self._build_measurement_panel(panel)
            elif key == "principle":
                self._build_principle_panel(panel)
            elif key == "smart":
                self._build_smart_panel(panel)
            elif key == "compare":
                self._build_compare_panel(panel)
            elif key == "log":
                self._build_log_panel(panel)

    
    def _on_node_activated(self, node_id: str) -> None:
        if node_id not in self.model.nodes:
            return
        if self._connect_mode and self.model.mode == "free":
            if self.model.connect_source_id is None:
                self.model.connect_source_id = node_id
                self.model.selected_node_id = node_id
                self.model.selected_edge_id = None
                self.model.latest_cause = f"已选择连接起点：{self.model.nodes[node_id].label}。请再选择目标元件。"
            else:
                source = self.model.connect_source_id
                self.model.connect_source_id = None
                edge_id = self.model.add_edge(source, node_id)
                if edge_id is None:
                    self.model.latest_cause = "该连接不符合教学平台的端口规则，未建立连接。"
                else:
                    self._connect_mode = False
            self._refresh_all(preserve_view=True)
            return
        self.model.selected_node_id = node_id
        self.model.selected_edge_id = None
        self._refresh_views(preserve_view=True)
        self._open_right_drawer("object")

    def _on_edge_activated(self, edge_id: str) -> None:
        if edge_id not in self.model.edges:
            return
        self.model.selected_edge_id = edge_id
        self.model.selected_node_id = None
        self._refresh_views(preserve_view=True)
        self._open_right_drawer("object")

    def _on_node_moved(self, node_id: str, x: float, y: float) -> None:
        if self.model.mode == "standard":
            self._refresh_views(preserve_view=True)
            return
        self.model.move_node(node_id, x, y, record=True)
        self._refresh_all(preserve_view=True)

    def _on_blank_activated(self) -> None:
        self.model.selected_node_id = None
        self.model.selected_edge_id = None
        if self.right_drawer.isVisible() and self._right_drawer_key == "object":
            self.right_drawer.hide()
        self._refresh_views(preserve_view=True)

    
    def _open_left_drawer(self, key: str) -> None:
        if self.left_drawer.isVisible() and self._left_drawer_key == key:
            self.left_drawer.hide()
            return
        self._left_drawer_key = key
        if key == "library":
            self._populate_library_drawer()
        elif key == "settings":
            self._populate_settings_drawer()
        else:
            self._populate_schemes_drawer()
        self.left_drawer.show()
        self.left_drawer.raise_()
        self._position_overlays()

    def _open_right_drawer(self, key: str) -> None:
        self._right_drawer_key = key
        self._populate_object_drawer()
        self.right_drawer.show()
        self.right_drawer.raise_()
        self._position_overlays()

    def _group_box(self, title: str) -> tuple[QGroupBox, QVBoxLayout]:
        group = QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(True)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)
        return group, layout

    def _populate_library_drawer(self) -> None:
        self.left_drawer.clear_body()
        for title, kinds in [
            ("光源与偏振", catalog.SOURCE_POLARIZATION_KINDS),
            ("光路与取样", catalog.ROUTING_SAMPLING_KINDS),
            ("整形与耦合", catalog.SHAPING_COUPLING_KINDS),
            ("测量仪器", catalog.INSTRUMENT_KINDS),
        ]:
            group, layout = self._group_box(title)
            grid = QGridLayout()
            for index, kind in enumerate(kinds):
                button = QPushButton(NODE_LABELS[kind])
                button.setEnabled(True)
                button.clicked.connect(lambda checked=False, value=kind: self._add_component(value))
                grid.addWidget(button, index // 2, index % 2)
            layout.addLayout(grid)
            self.left_drawer.body_layout.addWidget(group)

        mirror_group, mirror_layout = self._group_box("反射镜快捷布局")
        mirror_row = QHBoxLayout()
        add_single = QPushButton("添加反射镜")
        add_single.setEnabled(True)
        add_single.clicked.connect(lambda checked=False: self._add_mirror_bundle(1))
        mirror_row.addWidget(add_single)
        add_pair = QPushButton("添加双镜组")
        add_pair.setEnabled(True)
        add_pair.clicked.connect(lambda checked=False: self._add_mirror_bundle(2))
        mirror_row.addWidget(add_pair)
        mirror_layout.addLayout(mirror_row)
        self.left_drawer.body_layout.addWidget(mirror_group)

        group, layout = self._group_box("结构编辑")
        connect = QPushButton("连接两个元件")
        connect.setCheckable(True)
        connect.setChecked(self._connect_mode)
        connect.setEnabled(self.model.mode == "free")
        connect.clicked.connect(self._toggle_connect_mode)
        layout.addWidget(connect)
        delete = QPushButton("删除当前元件或连接")
        delete.setEnabled(self.model.mode == "free")
        delete.clicked.connect(self._delete_selected)
        layout.addWidget(delete)
        standard = QPushButton("从标准布局开始")
        standard.setEnabled(self.model.mode == "free")
        standard.clicked.connect(self._reset_free_to_standard)
        layout.addWidget(standard)
        clear = QPushButton("清空平台")
        clear.setEnabled(self.model.mode == "free")
        clear.clicked.connect(self._clear_free_platform)
        layout.addWidget(clear)
        self.left_drawer.body_layout.addWidget(group)
        self.left_drawer.body_layout.addStretch(1)

    def _populate_settings_drawer(self) -> None:
        self.left_drawer.clear_body()
        group, layout = self._group_box("显示设置")
        fit = QPushButton("适合全图")
        fit.clicked.connect(self.graphics_view.fit_full)
        layout.addWidget(fit)
        focus = QPushButton("聚焦当前对象")
        focus.clicked.connect(lambda: self.graphics_view.focus_node(self.model.selected_node_id or ""))
        layout.addWidget(focus)
        reset_view = QPushButton("恢复默认视图")
        reset_view.clicked.connect(self.graphics_view.fit_full)
        layout.addWidget(reset_view)
        rotate_left = QPushButton("3D视图左转")
        rotate_left.clicked.connect(lambda: self.view_3d.rotate_camera(-15))
        layout.addWidget(rotate_left)
        rotate_right = QPushButton("3D视图右转")
        rotate_right.clicked.connect(lambda: self.view_3d.rotate_camera(15))
        layout.addWidget(rotate_right)
        self.left_drawer.body_layout.addWidget(group)

        group, layout = self._group_box("教学光源与接收端")
        form = QFormLayout()
        wavelength = QDoubleSpinBox()
        wavelength.setRange(200, 2000)
        wavelength.setSuffix(" nm")
        wavelength.setValue(self.model.wavelength_nm)
        wavelength.valueChanged.connect(self._update_global_settings)
        wavelength.setObjectName("wavelengthSpin")
        form.addRow("波长", wavelength)
        input_power = QDoubleSpinBox()
        input_power.setRange(0, 5000)
        input_power.setSuffix(" mW")
        input_power.setValue(self.model.input_power_mw)
        input_power.valueChanged.connect(self._update_global_settings)
        input_power.setObjectName("inputPowerSpin")
        form.addRow("输入功率", input_power)
        na = QDoubleSpinBox()
        na.setRange(0.001, 0.95)
        na.setDecimals(3)
        na.setSingleStep(0.01)
        na.setValue(self.model.receiver_na)
        na.valueChanged.connect(self._update_global_settings)
        na.setObjectName("receiverNaSpin")
        form.addRow("接收NA", na)
        mode_radius = QDoubleSpinBox()
        mode_radius.setRange(0.2, 50)
        mode_radius.setSuffix(" μm")
        mode_radius.setValue(self.model.receiver_mode_radius_um)
        mode_radius.valueChanged.connect(self._update_global_settings)
        mode_radius.setObjectName("modeRadiusSpin")
        form.addRow("模场半径", mode_radius)
        layout.addLayout(form)
        self.left_drawer.body_layout.addWidget(group)

        group, layout = self._group_box("结构约束")
        form = QFormLayout()
        max_length = QDoubleSpinBox()
        max_length.setRange(10, 500)
        max_length.setSuffix(" mm")
        max_length.setValue(self.model.max_system_length_mm)
        max_length.valueChanged.connect(self._update_global_settings)
        max_length.setObjectName("maxLengthSpin")
        form.addRow("最大系统长度", max_length)
        min_gap = QDoubleSpinBox()
        min_gap.setRange(0, 20)
        min_gap.setSuffix(" mm")
        min_gap.setValue(self.model.min_air_gap_mm)
        min_gap.valueChanged.connect(self._update_global_settings)
        min_gap.setObjectName("minGapSpin")
        form.addRow("最小空气间距", min_gap)
        target = QDoubleSpinBox()
        target.setRange(1, 99.9)
        target.setSuffix(" %")
        target.setValue(self.model.target_total_efficiency * 100)
        target.valueChanged.connect(self._update_global_settings)
        target.setObjectName("targetEfficiencySpin")
        form.addRow("目标总效率", target)
        layout.addLayout(form)
        self.left_drawer.body_layout.addWidget(group)
        self.left_drawer.body_layout.addStretch(1)

    def _populate_schemes_drawer(self) -> None:
        self.left_drawer.clear_body()
        for group_name in EXPERIMENT_GROUPS:
            group, layout = self._group_box(group_name)
            for preset in presets_for_group(group_name):
                button = QPushButton(preset.label)
                button.clicked.connect(lambda checked=False, key=preset.key: self._load_experiment_preset(key))
                layout.addWidget(button)
            self.left_drawer.body_layout.addWidget(group)
        if self.model.saved_schemes:
            saved_group, saved_layout = self._group_box("已保存方案")
            for index, scheme in enumerate(self.model.saved_schemes):
                row = QHBoxLayout()
                row.addWidget(QLabel(scheme.name), 1)
                restore = QPushButton("载入")
                restore.clicked.connect(lambda checked=False, idx=index: self._restore_scheme(idx))
                row.addWidget(restore)
                saved_layout.addLayout(row)
            self.left_drawer.body_layout.addWidget(saved_group)
        self.left_drawer.body_layout.addStretch(1)

    def _load_experiment_preset(self, key: str) -> None:
        preset = EXPERIMENT_PRESETS.get(str(key))
        if preset is None:
            return
        self.model.nodes.clear()
        self.model.edges.clear()
        self.model._counter = 0
        created: list[str] = []
        for index, (kind, x, y, rotation, label, params) in enumerate(preset.specs):
            node_id = self.model.add_node(
                kind,
                x,
                y,
                label=label,
                params=dict(params),
                node_id=f"{kind}_{index + 1}",
                record=False,
            )
            self.model.nodes[node_id].rotation_deg = float(rotation)
            created.append(node_id)
        main_nodes = [node_id for node_id in created if abs(self.model.nodes[node_id].y - 310.0) <= 85.0]
        main_nodes.sort(key=lambda node_id: self.model.nodes[node_id].x)
        for source, target in zip(main_nodes, main_nodes[1:]):
            self.model.add_edge(source, target, record=False)
        branch_nodes = [node_id for node_id in created if node_id not in main_nodes]
        for target in branch_nodes:
            target_node = self.model.nodes[target]
            eligible = [
                source for source in main_nodes
                if self.model.nodes[source].kind in {"splitter", "beam_sampler", "pbs", "photodetector"}
            ]
            if target_node.kind == "oscilloscope":
                eligible = [source for source in branch_nodes if self.model.nodes[source].kind == "photodetector"]
            if eligible:
                source = min(eligible, key=lambda node_id: abs(self.model.nodes[node_id].x - target_node.x))
                self.model.add_edge(source, target, record=False)
        self.model.mode = "free"
        self.model.selected_node_id = main_nodes[-1] if main_nodes else (created[0] if created else None)
        self.model.selected_edge_id = None
        self.model.latest_cause = preset.label
        self.model.mark_changed()
        self.model._reset_history()
        self.model.log.append(f"载入{preset.label}。")
        self._refresh_all(preserve_view=False)
        self.left_drawer.hide()

    def _populate_object_drawer(self) -> None:
        self.right_drawer.clear_body()
        edge_id = self.model.selected_edge_id
        node_id = self.model.selected_node_id
        if edge_id in self.model.edges:
            edge = self.model.edges[edge_id]
            title = QLabel(f"连接：{self.model.nodes[edge.source].label} → {self.model.nodes[edge.target].label}")
            title.setWordWrap(True)
            title.setObjectName("drawerObjectTitle")
            self.right_drawer.body_layout.addWidget(title)
            note = QLabel("自由搭建模式下可删除该连接；断开后，下游光束和仪器读数将同步消失。")
            note.setWordWrap(True)
            note.setObjectName("helperText")
            self.right_drawer.body_layout.addWidget(note)
            delete = QPushButton("删除连接")
            delete.setEnabled(self.model.mode == "free")
            delete.clicked.connect(self._delete_selected)
            self.right_drawer.body_layout.addWidget(delete)
            self.right_drawer.body_layout.addStretch(1)
            return
        node = self.model.nodes.get(node_id or "")
        if node is None:
            label = QLabel("在主实验平台中选择一个元件、仪器或连接。")
            label.setWordWrap(True)
            self.right_drawer.body_layout.addWidget(label)
            self.right_drawer.body_layout.addStretch(1)
            return
        title = QLabel(node.label)
        title.setObjectName("drawerObjectTitle")
        self.right_drawer.body_layout.addWidget(title)
        kind = QLabel(NODE_LABELS.get(node.kind, node.kind))
        kind.setObjectName("helperText")
        self.right_drawer.body_layout.addWidget(kind)

        group, layout = self._group_box("位置与姿态")
        form = QFormLayout()
        x_spin = QDoubleSpinBox()
        x_spin.setRange(45, SCENE_RECT.width() - 45)
        x_spin.setValue(node.x)
        x_spin.setSuffix(" px")
        y_spin = QDoubleSpinBox()
        y_spin.setRange(70, SCENE_RECT.height() - 70)
        y_spin.setValue(node.y)
        y_spin.setSuffix(" px")
        editable = self.model.mode in {"layout", "free", "diagnostic"}
        x_spin.setEnabled(editable)
        y_spin.setEnabled(editable and self.model.mode == "free")
        x_spin.editingFinished.connect(lambda nid=node.id, widget=x_spin: self._set_node_position_component(nid, x=widget.value()))
        y_spin.editingFinished.connect(lambda nid=node.id, widget=y_spin: self._set_node_position_component(nid, y=widget.value()))
        form.addRow("平台X", x_spin)
        form.addRow("平台Y", y_spin)
        layout.addLayout(form)
        self.right_drawer.body_layout.addWidget(group)

        if node.kind == "lens":
            group, layout = self._group_box("透镜参数")
            form = QFormLayout()
            focal = QComboBox()
            for value in FOCAL_LIBRARY:
                focal.addItem(f"{value:g} mm", value)
            current = float(node.params.get("focal_mm", 50.0))
            index = min(range(focal.count()), key=lambda i: abs(float(focal.itemData(i)) - current))
            focal.setCurrentIndex(index)
            focal.currentIndexChanged.connect(lambda _i, nid=node.id, box=focal: self._update_node_parameter(nid, "focal_mm", float(box.currentData())))
            form.addRow("焦距", focal)
            reversed_box = QCheckBox("翻转透镜方向")
            reversed_box.setChecked(bool(node.params.get("reversed", False)))
            reversed_box.toggled.connect(lambda value, nid=node.id: self._update_node_parameter(nid, "reversed", bool(value)))
            form.addRow("方向", reversed_box)
            layout.addLayout(form)
            hint = QLabel("改变焦距或方向后，束腰与接收效率立即按教学近似更新。")
            hint.setWordWrap(True)
            hint.setObjectName("helperText")
            layout.addWidget(hint)
            self.right_drawer.body_layout.addWidget(group)
        elif node.kind == "fiber":
            group, layout = self._group_box("五轴与波前")
            form = QFormLayout()
            specs = [
                ("offset_x_um", "X偏移", -20, 20, " μm", 0.1),
                ("offset_y_um", "Y偏移", -20, 20, " μm", 0.1),
                ("offset_z_um", "Z离焦", -300, 300, " μm", 1.0),
                ("pitch_mrad", "Pitch", -100, 100, " mrad", 0.5),
                ("yaw_mrad", "Yaw", -100, 100, " mrad", 0.5),
                ("curvature_waves", "曲率相位差", -2, 2, " waves", 0.01),
            ]
            for key, label, minimum, maximum, suffix, step in specs:
                spin = QDoubleSpinBox()
                spin.setRange(minimum, maximum)
                spin.setDecimals(3)
                spin.setSingleStep(step)
                spin.setSuffix(suffix)
                spin.setValue(float(node.params.get(key, 0.0)))
                spin.valueChanged.connect(lambda value, nid=node.id, name=key: self._update_node_parameter(nid, name, float(value), live=True))
                form.addRow(label, spin)
            layout.addLayout(form)
            self.right_drawer.body_layout.addWidget(group)
        elif node.kind == "splitter":
            group, layout = self._group_box("分光设置")
            form = QFormLayout()
            fraction = QDoubleSpinBox()
            fraction.setRange(0, 50)
            fraction.setSuffix(" %")
            fraction.setValue(float(node.params.get("monitor_fraction", 0.05)) * 100)
            fraction.valueChanged.connect(lambda value, nid=node.id: self._update_node_parameter(nid, "monitor_fraction", float(value) / 100.0, live=True))
            form.addRow("监测支路", fraction)
            branch_angle = QDoubleSpinBox()
            branch_angle.setRange(-170.0, 170.0)
            branch_angle.setDecimals(1)
            branch_angle.setSingleStep(5.0)
            branch_angle.setSuffix(" °")
            branch_angle.setValue(float(node.params.get("branch_offset_deg", 90.0)))
            branch_angle.valueChanged.connect(lambda value, nid=node.id: self._update_node_parameter(nid, "branch_offset_deg", float(value), live=True))
            form.addRow("支路偏转角", branch_angle)
            layout.addLayout(form)
            hint = QLabel("学生可以设置采样支路的偏转角；分束器损耗与通光损耗由教学模型固定处理，不开放手动输入。")
            hint.setWordWrap(True)
            hint.setObjectName("helperText")
            layout.addWidget(hint)
            self.right_drawer.body_layout.addWidget(group)
        elif node.kind == "mirror":
            group, layout = self._group_box("反射设置")
            form = QFormLayout()
            beam_offset = QDoubleSpinBox()
            beam_offset.setRange(-170.0, 170.0)
            beam_offset.setDecimals(1)
            beam_offset.setSingleStep(5.0)
            beam_offset.setSuffix(" °")
            beam_offset.setValue(float(node.params.get("beam_offset_deg", 90.0)))
            beam_offset.valueChanged.connect(lambda value, nid=node.id: self._update_node_parameter(nid, "beam_offset_deg", float(value), live=True))
            form.addRow("光偏移角", beam_offset)
            mount_angle = QLabel(f"当前镜架角：{float(node.rotation_deg):.1f} °")
            form.addRow("镜架姿态", mount_angle)
            layout.addLayout(form)
            hint = QLabel("学生只需设置光束偏转角；镜面损耗由教学模型自动采用固定值，不开放手动输入。")
            hint.setWordWrap(True)
            hint.setObjectName("helperText")
            layout.addWidget(hint)
            self.right_drawer.body_layout.addWidget(group)
        elif node.kind == "aperture":
            group, layout = self._group_box("光阑设置")
            form = QFormLayout()
            diameter = QDoubleSpinBox()
            diameter.setRange(0.1, 50)
            diameter.setSuffix(" mm")
            diameter.setValue(float(node.params.get("diameter_mm", 5.0)))
            diameter.valueChanged.connect(lambda value, nid=node.id: self._update_node_parameter(nid, "diameter_mm", float(value), live=True))
            form.addRow("孔径", diameter)
            layout.addLayout(form)
            self.right_drawer.body_layout.addWidget(group)
        elif node.kind in {"beam_analyzer", "wavefront_sensor"}:
            group, layout = self._group_box("测量面设置")
            form = QFormLayout()
            offset = QDoubleSpinBox()
            offset.setRange(-20, 20)
            offset.setSuffix(" mm")
            offset.setValue(float(node.params.get("plane_offset_mm", 0.0)))
            offset.valueChanged.connect(lambda value, nid=node.id: self._update_node_parameter(nid, "plane_offset_mm", float(value), live=True))
            form.addRow("相对焦面", offset)
            layout.addLayout(form)
            self.right_drawer.body_layout.addWidget(group)

        if node.kind in INSTRUMENT_TYPES:
            measure = PrimaryButton("查看测量结果")
            measure.clicked.connect(self._open_measurement_panel)
            self.right_drawer.body_layout.addWidget(measure)
        if node.kind in {"fiber", "lens"}:
            principle = SecondaryButton("查看原理分析")
            principle.clicked.connect(self._open_principle_panel)
            self.right_drawer.body_layout.addWidget(principle)
        if self.model.mode == "free":
            delete = QPushButton("删除该元件")
            delete.clicked.connect(self._delete_selected)
            self.right_drawer.body_layout.addWidget(delete)
        self.right_drawer.body_layout.addStretch(1)

    
    def _add_component(self, kind: str) -> None:
        if self.model.mode != "free":
            return
        center = self.graphics_view.mapToScene(self.graphics_view.viewport().rect().center())
        x = max(100.0, min(1500.0, center.x() + random.uniform(-60, 60)))
        y = MAIN_RAIL_Y if kind in OPTICAL_TYPES else BRANCH_RAIL_Y
        params = {"beam_offset_deg": 90.0} if kind == "mirror" else None
        self.model.add_node(kind, x, y, params=params)
        self._refresh_all(preserve_view=True)
        self._populate_library_drawer()

    def _add_mirror_bundle(self, count: int) -> None:
        if self.model.mode != "free":
            return
        center = self.graphics_view.mapToScene(self.graphics_view.viewport().rect().center())
        base_x = max(120.0, min(1450.0, center.x()))
        base_y = max(160.0, min(760.0, center.y()))
        if count <= 1:
            self.model.add_node("mirror", base_x, base_y, params={"beam_offset_deg": 90.0})
            self.model.latest_cause = "已添加一面反射镜，可在右侧设置光偏移角。"
        else:
            self.model.add_node("mirror", base_x - 90.0, max(120.0, base_y - 110.0), params={"beam_offset_deg": 90.0})
            self.model.add_node("mirror", min(1480.0, base_x + 110.0), min(780.0, base_y + 110.0), params={"beam_offset_deg": -90.0})
            self.model.latest_cause = "已添加双反射镜组合，可用于L形或Z形折叠光路设计。"
        self._refresh_all(preserve_view=True)
        self._populate_library_drawer()

    def _toggle_connect_mode(self, checked: bool) -> None:
        self._connect_mode = bool(checked)
        self.model.connect_source_id = None
        self.model.latest_cause = "连接模式：依次选择起点和目标元件。" if checked else "已退出连接模式。"
        self._refresh_all(preserve_view=True)

    def _delete_selected(self) -> None:
        if self.model.mode != "free":
            return
        if self.model.remove_selected():
            self.right_drawer.hide()
            self._refresh_all(preserve_view=True)

    def _reset_free_to_standard(self) -> None:
        if self.model.mode != "free":
            return
        self.model.load_standard(record=False)
        self.model.mode = "free"
        self.model._reset_history()
        self.model.log.append("自由搭建恢复为标准起始布局。")
        self._refresh_all(preserve_view=False)

    def _clear_free_platform(self) -> None:
        if self.model.mode != "free":
            return
        answer = QMessageBox.question(self, "清空平台", "确定清空自由搭建平台中的所有元件和连接吗？")
        if answer == QMessageBox.StandardButton.Yes:
            self.model.clear_platform()
            self._refresh_all(preserve_view=True)

    def _update_global_settings(self) -> None:
        sender = self.sender()
        if sender is None:
            return
        name = sender.objectName()
        value = float(sender.value())
        if name == "wavelengthSpin":
            self.model.wavelength_nm = value
        elif name == "inputPowerSpin":
            self.model.input_power_mw = value
        elif name == "receiverNaSpin":
            self.model.receiver_na = value
        elif name == "modeRadiusSpin":
            self.model.receiver_mode_radius_um = value
        elif name == "maxLengthSpin":
            self.model.max_system_length_mm = value
        elif name == "minGapSpin":
            self.model.min_air_gap_mm = value
        elif name == "targetEfficiencySpin":
            self.model.target_total_efficiency = value / 100.0
        self.model.latest_cause = "更新教学系统设置。"
        self._refresh_all(preserve_view=True)

    def _set_node_position_component(self, node_id: str, *, x: float | None = None, y: float | None = None) -> None:
        node = self.model.nodes.get(node_id)
        if node is None:
            return
        self.model.move_node(node_id, node.x if x is None else x, node.y if y is None else y, record=True)
        self._refresh_all(preserve_view=True)

    def _update_node_parameter(self, node_id: str, key: str, value: Any, *, live: bool = False) -> None:
        node = self.model.nodes.get(node_id)
        if node is None:
            return
        old = node.params.get(key)
        changed = old != value
        node.params[key] = value
        if key == "rotation_deg":
            node.rotation_deg = float(value)
        if live:
            if changed:
                self.model.mark_changed()
                rebuild = getattr(self.model, "rebuild_auto_paths", None)
                if callable(rebuild):
                    rebuild()
            self.model.latest_cause = f"调整{node.label}的{key}：{old} → {value}。"
        else:
            self.model.record(f"调整{node.label}的{key}：{old} → {value}。")
        self._refresh_all(preserve_view=True)

    
    def _get_panel(self, key: str, title: str, size: tuple[int, int] = (540, 400)) -> FloatingPanel:
        panel = self._floating_panels.get(key)
        if panel is None:
            panel = FloatingPanel(key, title, self.overlay_host)
            panel.resize(*size)
            offset = len(self._floating_panels) * 28
            panel.move(max(120, (self.overlay_host.width() - size[0]) // 2 + offset), max(55, (self.overlay_host.height() - size[1]) // 2 + offset))
            self._floating_panels[key] = panel
        panel.title_label.setText(title)
        panel.setMinimumSize(min(size[0], 760), min(size[1], 480))
        if panel.width() < size[0] or panel.height() < size[1]:
            panel.resize(max(panel.width(), size[0]), max(panel.height(), size[1]))
        panel.show()
        panel.raise_()
        return panel

    def _measurement_records(self) -> list[tuple[ExperimentNode, dict[str, Any]]]:
        measurements: list[tuple[ExperimentNode, dict[str, Any]]] = []
        for node in self.model.nodes.values():
            if node.kind not in INSTRUMENT_TYPES:
                continue
            reading = self.model.instrument_reading(node.id)
            if bool(reading.get("valid")):
                measurements.append((node, reading))
        return measurements

    def _open_measurement_panel(self) -> None:
        
        
        if self.right_drawer.isVisible() and self._right_drawer_key == "measurement":
            self.right_drawer.hide()
            return
        self._right_drawer_key = "measurement"
        self._populate_measurement_drawer()
        self.right_drawer.show()
        self.right_drawer.raise_()
        self._position_overlays()

    def _populate_measurement_drawer(self) -> None:
        self.right_drawer.clear_body()
        measurements = self._measurement_records()
        self.right_drawer.title_label.setText(f"测量结果 · {len(measurements)}台")
        self._append_measurement_cards(self.right_drawer.body_layout, measurements)

    def _build_measurement_panel(self, panel: FloatingPanel) -> None:
        
        panel.clear_content()
        measurements = self._measurement_records()
        panel.title_label.setText(f"测量结果 · {len(measurements)}台仪器")
        self._append_measurement_cards(panel.content_layout, measurements)

    def _append_measurement_cards(
        self,
        target_layout: QVBoxLayout,
        measurements: list[tuple[ExperimentNode, dict[str, Any]]],
    ) -> None:
        if not measurements:
            label = QLabel("没有仪器接收到光束")
            label.setObjectName("warningText")
            target_layout.addWidget(label)
            target_layout.addStretch(1)
            return

        for node, reading in measurements:
            group = QGroupBox(node.label)
            group.setObjectName("measurementResultCard")
            layout = QVBoxLayout(group)
            layout.setContentsMargins(10, 12, 10, 10)
            layout.setSpacing(6)
            if node.kind == "power_meter":
                value = QLabel(f"{reading['role']}　{reading['power_mw']:.4f} mW")
                value.setObjectName("panelBigMetric")
                layout.addWidget(value)
                incoming = [self.model.nodes[source] for source in self.model.incoming(node.id) if source in self.model.nodes]
                splitter = next((item for item in incoming if item.kind in {"splitter", "beam_sampler", "pbs"}), None)
                if splitter is not None:
                    fraction = float(splitter.params.get("monitor_fraction", splitter.params.get("split_ratio", 0.0)))
                    layout.addWidget(QLabel(f"支路比例　{fraction * 100:.2f}%"))
                layout.addWidget(QLabel("状态　正常接收"))
            elif node.kind in {"beam_analyzer", "imaging_camera", "focus_scan_module"}:
                grid = QGridLayout()
                values = (
                    ("X半径", f"{reading['radius_x_um']:.2f} μm"),
                    ("Y半径", f"{reading['radius_y_um']:.2f} μm"),
                    ("中心X", f"{reading['center_x_um']:.2f} μm"),
                    ("中心Y", f"{reading['center_y_um']:.2f} μm"),
                    ("椭圆率", f"{reading.get('ellipticity', 1.0):.3f}"),
                    ("状态", "正常接收"),
                )
                for index, (label, value) in enumerate(values):
                    grid.addWidget(QLabel(label), index // 2, (index % 2) * 2)
                    metric = QLabel(value)
                    metric.setObjectName("measurementMetric")
                    grid.addWidget(metric, index // 2, (index % 2) * 2 + 1)
                layout.addLayout(grid)
            elif node.kind == "wavefront_sensor":
                grid = QGridLayout()
                values = (
                    ("倾斜X", f"{reading['tilt_x_mrad']:.2f} mrad"),
                    ("倾斜Y", f"{reading['tilt_y_mrad']:.2f} mrad"),
                    ("曲率相位差", f"{reading['curvature_waves']:.3f} λ"),
                    ("像散量", f"{reading.get('astigmatism_um', 0.0):.2f} μm"),
                )
                for index, (label, value) in enumerate(values):
                    grid.addWidget(QLabel(label), index, 0)
                    grid.addWidget(QLabel(value), index, 1)
                layout.addLayout(grid)
            elif node.kind == "oscilloscope":
                layout.addWidget(QLabel(f"幅值　{reading['amplitude_v']:.3f} V"))
                layout.addWidget(QLabel(f"频率　{reading['frequency_hz']:.1f} Hz"))
            else:
                layout.addWidget(QLabel(f"光电信号　{reading.get('signal_v', 0.0):.3f} V"))
                layout.addWidget(QLabel(f"噪声　{reading.get('noise_v', 0.0):.3f} V"))
            row = QHBoxLayout()
            row.addStretch(1)
            locate = SecondaryButton("定位")
            locate.clicked.connect(lambda checked=False, node_id=node.id: self._on_node_activated(node_id))
            row.addWidget(locate)
            layout.addLayout(row)
            target_layout.addWidget(group)
        target_layout.addStretch(1)

    def _open_principle_panel(self) -> None:
        panel = self._get_panel("principle", "原理分析", (850, 500))
        self._build_principle_panel(panel)

    def _build_principle_panel(self, panel: FloatingPanel) -> None:
        panel.clear_content()
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("分析类型"))
        selector = QComboBox()
        items = [
            ("横向偏移", "lateral"),
            ("轴向离焦", "defocus"),
            ("角度失配", "angle"),
            ("尺寸失配", "size"),
            ("曲率失配", "curvature"),
        ]
        for label, data in items:
            selector.addItem(label, data)
        selected = "curvature"
        fiber = next((node for node in self.model.nodes.values() if node.kind == "fiber"), None)
        if fiber:
            fp = fiber.params
            candidates = {
                "lateral": math.hypot(float(fp.get("offset_x_um", 0.0)), float(fp.get("offset_y_um", 0.0))) / 3.0,
                "defocus": abs(float(fp.get("offset_z_um", 0.0))) / 50.0,
                "angle": math.hypot(float(fp.get("pitch_mrad", 0.0)), float(fp.get("yaw_mrad", 0.0))) / 20.0,
                "curvature": abs(float(fp.get("curvature_waves", 0.0))) / 0.2,
            }
            selected = max(candidates, key=candidates.get) if max(candidates.values(), default=0) > 0 else "curvature"
        selector.setCurrentIndex(next((i for i in range(selector.count()) if selector.itemData(i) == selected), 0))
        selector_row.addWidget(selector)
        selector_row.addStretch(1)
        panel.content_layout.addLayout(selector_row)
        triple = MismatchTripleView(self.model, selected)
        selector.currentIndexChanged.connect(lambda _i, widget=triple, box=selector: widget.set_mismatch(str(box.currentData())))
        panel.content_layout.addWidget(triple, 1)
        metrics = self.model.evaluate()
        conclusion = QLabel(f"当前主要限制：{metrics.dominant_issue}。{metrics.explanation}")
        conclusion.setWordWrap(True)
        conclusion.setObjectName("teachingConclusion")
        panel.content_layout.addWidget(conclusion)

    def _open_optimization_panel(self) -> None:
        panel = self._get_panel("optimization", "参数优化", (650, 470))
        self._build_optimization_panel(panel)

    def _build_optimization_panel(self, panel: FloatingPanel) -> None:
        panel.clear_content()
        metrics = self.model.evaluate()
        intro = QLabel("只优化学生选择的连续变量。优化器不会替代镜片数量、连接关系或器材选择。")
        intro.setWordWrap(True)
        intro.setObjectName("helperText")
        panel.content_layout.addWidget(intro)
        variable_group = QGroupBox("开放变量")
        variable_layout = QVBoxLayout(variable_group)
        checks: list[tuple[QCheckBox, str, str]] = []
        for node in self.model.nodes.values():
            if node.kind == "lens":
                check = QCheckBox(f"{node.label} 轴向位置")
                variable_layout.addWidget(check)
                checks.append((check, node.id, "x"))
            elif node.kind == "fiber":
                for key, label in [("offset_x_um", "光纤X"), ("offset_y_um", "光纤Y"), ("offset_z_um", "光纤Z"), ("pitch_mrad", "Pitch"), ("yaw_mrad", "Yaw")]:
                    check = QCheckBox(label)
                    variable_layout.addWidget(check)
                    checks.append((check, node.id, key))
        panel.content_layout.addWidget(variable_group)
        before = QLabel(f"当前：系统 {metrics.system_efficiency * 100:.1f}%｜接收 {metrics.receiver_efficiency * 100:.1f}%｜总效率 {metrics.total_efficiency * 100:.1f}%")
        panel.content_layout.addWidget(before)
        result_label = QLabel("尚未运行参数优化。")
        result_label.setWordWrap(True)
        panel.content_layout.addWidget(result_label)
        run = PrimaryButton("运行参数优化")
        run.clicked.connect(lambda: self._run_teaching_optimization(checks, result_label))
        panel.content_layout.addWidget(run)
        panel.content_layout.addStretch(1)

    def _run_teaching_optimization(self, checks: list[tuple[QCheckBox, str, str]], result_label: QLabel) -> None:
        variables = [(node_id, key) for check, node_id, key in checks if check.isChecked()]
        if not variables:
            result_label.setText("请至少选择一个开放变量。")
            return
        before_snapshot = self.model.snapshot()
        before = self.model.evaluate()
        best_snapshot = copy.deepcopy(before_snapshot)
        best = before.total_efficiency
        rng = random.Random(20260729 + len(self.model.log))
        for _ in range(240):
            self.model.restore(before_snapshot)
            for node_id, key in variables:
                node = self.model.nodes.get(node_id)
                if node is None:
                    continue
                if key == "x":
                    node.x = max(70.0, min(1530.0, node.x + rng.uniform(-90.0, 90.0)))
                elif key in {"offset_x_um", "offset_y_um"}:
                    node.params[key] = rng.uniform(-1.2, 1.2)
                elif key == "offset_z_um":
                    node.params[key] = rng.uniform(-35.0, 35.0)
                else:
                    node.params[key] = rng.uniform(-8.0, 8.0)
            candidate = self.model.evaluate()
            if candidate.feasible and candidate.total_efficiency > best:
                best = candidate.total_efficiency
                best_snapshot = self.model.snapshot()
        self.model.restore(best_snapshot)
        after = self.model.evaluate()
        self.model.record(f"参数优化完成：总效率 {before.total_efficiency * 100:.1f}% → {after.total_efficiency * 100:.1f}%。")
        result_label.setText(
            f"优化前 {before.total_efficiency * 100:.1f}% → 优化后 {after.total_efficiency * 100:.1f}%\n"
            f"当前主要限制：{after.dominant_issue}。"
        )
        self._refresh_all(preserve_view=True)

    def _open_smart_panel(self) -> None:
        panel = self._get_panel("smart", "智能分析", (980, 640))
        self._build_smart_panel(panel)

    def _candidate_rows(self) -> list[tuple[list[float], float, float, str]]:
        lenses = [node for node in self.model.nodes.values() if node.kind == "lens"]
        count = max(1, min(4, len(lenses) or 2))
        pools = list(FOCAL_LIBRARY)
        rng = random.Random(808 + count * 17)
        original = self.model.snapshot()
        rows: list[tuple[list[float], float, float, str]] = []
        for _ in range(36):
            values = [rng.choice(pools) for _ in range(count)]
            self.model.restore(original)
            active = [node for node in self.model.nodes.values() if node.kind == "lens"]
            while len(active) < count and self.model.mode == "free":
                node_id = self.model.add_node("lens", 650 + len(active) * 150, MAIN_RAIL_Y, record=False)
                active.append(self.model.nodes[node_id])
            for node, value in zip(active, values):
                node.params["focal_mm"] = value
            metrics = self.model.evaluate()
            spread = 0.025 + 0.012 * max(0, count - 2)
            confidence = max(0.35, min(0.96, 0.93 - 0.07 * max(0, count - 2) - (0.12 if not metrics.feasible else 0.0)))
            reason = metrics.dominant_issue
            rows.append((values, metrics.total_efficiency, confidence, reason))
        self.model.restore(original)
        rows.sort(key=lambda item: item[1] * (0.75 + 0.25 * item[2]), reverse=True)
        return rows[:6]

    def _build_smart_panel(self, panel: FloatingPanel) -> None:
        panel.clear_content()
        metrics = self.model.evaluate()
        summary = QLabel(
            f"教学代理判断：当前方案主要受“{metrics.dominant_issue}”限制。\n"
            "智能分析只给出候选排序和影响依据，最终方案仍需学生选择并进入正式工作台验证。"
        )
        summary.setWordWrap(True)
        summary.setObjectName("teachingConclusion")
        panel.content_layout.addWidget(summary)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["候选", "焦距组合/mm", "预测总效率", "可信程度", "主要风险"])
        table.setMinimumHeight(300)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(0, 72)
        table.setColumnWidth(1, 150)
        table.setColumnWidth(2, 170)
        table.setColumnWidth(3, 100)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(64)
        table.verticalHeader().setDefaultSectionSize(34)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        rows = self._candidate_rows()
        for index, (values, efficiency, confidence, risk) in enumerate(rows):
            table.insertRow(index)
            table.setItem(index, 0, QTableWidgetItem(chr(ord("A") + index)))
            table.setItem(index, 1, QTableWidgetItem(" / ".join(f"{v:g}" for v in values)))
            table.setItem(index, 2, QTableWidgetItem(f"{max(0, efficiency - 0.025) * 100:.1f}%～{min(1, efficiency + 0.025) * 100:.1f}%"))
            table.setItem(index, 3, QTableWidgetItem("高" if confidence >= 0.8 else "中" if confidence >= 0.55 else "低"))
            table.setItem(index, 4, QTableWidgetItem(risk))
            for column in range(table.columnCount()):
                cell = table.item(index, column)
                if cell is not None:
                    cell.setToolTip(cell.text())
            table.item(index, 0).setData(Qt.ItemDataRole.UserRole, values)
        panel.content_layout.addWidget(table, 1)
        factors = QLabel(
            "当前前三个影响因素：\n"
            f"1. 最终束腰偏差（{metrics.predicted_waist_um:.2f} μm vs {metrics.target_waist_um:.2f} μm）\n"
            "2. 末级透镜焦距与位置\n"
            "3. 光纤端面位置、角度或曲率"
        )
        factors.setWordWrap(True)
        panel.content_layout.addWidget(factors)
        apply_button = PrimaryButton("应用选中候选")
        apply_button.clicked.connect(lambda: self._apply_smart_candidate(table))
        panel.content_layout.addWidget(apply_button)

    def _apply_smart_candidate(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row < 0:
            return
        item = table.item(row, 0)
        values = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not values:
            return
        lenses = [node for node in self.model.nodes.values() if node.kind == "lens"]
        for node, value in zip(lenses, values):
            node.params["focal_mm"] = float(value)
        self.model.record(f"采用智能候选{item.text()}：焦距组合 {' / '.join(str(v) for v in values)} mm。")
        self._refresh_all(preserve_view=True)

    def _open_compare_panel(self) -> None:
        panel = self._get_panel("compare", "方案比较", (760, 430))
        self._build_compare_panel(panel)

    def _build_compare_panel(self, panel: FloatingPanel) -> None:
        panel.clear_content()
        if not self.model.saved_schemes:
            label = QLabel("尚未保存方案。使用底部“保存方案”后，可比较效率、束腰、结构长度和镜片数量。")
            label.setWordWrap(True)
            panel.content_layout.addWidget(label)
            return
        table = QTableWidget(len(self.model.saved_schemes), 7)
        table.setHorizontalHeaderLabels(["方案", "系统效率", "接收效率", "总效率", "束腰/目标", "镜片数", "可实现"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, scheme in enumerate(self.model.saved_schemes):
            metrics = scheme.metrics
            values = [
                scheme.name,
                f"{metrics.system_efficiency * 100:.1f}%",
                f"{metrics.receiver_efficiency * 100:.1f}%",
                f"{metrics.total_efficiency * 100:.1f}%",
                f"{metrics.predicted_waist_um:.2f}/{metrics.target_waist_um:.2f}",
                str(metrics.lens_count),
                "是" if metrics.feasible else "否",
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        panel.content_layout.addWidget(table, 1)
        note = QLabel("方案比较聚焦效率、束腰、结构可实现性和复杂度。")
        note.setObjectName("helperText")
        note.setWordWrap(True)
        panel.content_layout.addWidget(note)

    def _open_log_panel(self) -> None:
        panel = self._get_panel("log", "设计记录", (620, 430))
        self._build_log_panel(panel)

    def _build_log_panel(self, panel: FloatingPanel) -> None:
        panel.clear_content()
        log_list = QListWidget()
        entries = self.model.log[-100:] or ["尚无操作记录。"]
        for index, text in enumerate(reversed(entries), start=1):
            item = QListWidgetItem(text)
            log_list.addItem(item)
        panel.content_layout.addWidget(log_list, 1)
        note = QLabel("记录由系统自动生成，用于复盘“改了什么—光束如何变化—结果为何变化”。")
        note.setWordWrap(True)
        note.setObjectName("helperText")
        panel.content_layout.addWidget(note)

    
    def _undo(self) -> None:
        if self.model.undo():
            self._refresh_all(preserve_view=True)

    def _redo(self) -> None:
        if self.model.redo():
            self._refresh_all(preserve_view=True)

    def _set_baseline(self) -> None:
        self.model.baseline_snapshot = copy.deepcopy(self.model.snapshot())
        self.model.latest_cause = "已将当前实验状态设为基线。"
        self.model.log.append(self.model.latest_cause)
        self._refresh_all(preserve_view=True)

    def _restore_baseline(self) -> None:
        if self.model.baseline_snapshot is None:
            QMessageBox.information(self, "恢复基线", "尚未设置基线。")
            return
        self.model.restore(self.model.baseline_snapshot)
        self.model.record("恢复到已保存的实验基线。")
        self._refresh_all(preserve_view=True)

    def _save_scheme(self) -> None:
        metrics = self.model.evaluate()
        name = f"方案{chr(ord('A') + len(self.model.saved_schemes))}"
        scheme = SavedScheme(name, copy.deepcopy(self.model.snapshot()), metrics)
        self.model.saved_schemes.append(scheme)
        self.model.latest_cause = f"保存{name}，总效率 {metrics.total_efficiency * 100:.1f}%。"
        self.model.log.append(self.model.latest_cause)
        self._refresh_all(preserve_view=True)
        if self.left_drawer.isVisible() and self._left_drawer_key == "schemes":
            self._populate_schemes_drawer()

    def _restore_scheme(self, index: int) -> None:
        if not (0 <= index < len(self.model.saved_schemes)):
            return
        scheme = self.model.saved_schemes[index]
        self.model.restore(scheme.snapshot)
        self.model.record(f"恢复{scheme.name}。")
        self._refresh_all(preserve_view=True)

    
    @staticmethod
    def _estimate_focal_from_surfaces(front: dict[str, Any], back: dict[str, Any]) -> float:

        try:
            r1 = float(front.get("radius_mm", 0.0))
            r2 = float(back.get("radius_mm", 0.0))
            n = 1.52
            power = (n - 1.0) * ((0.0 if abs(r1) < 1e-9 else 1.0 / r1) - (0.0 if abs(r2) < 1e-9 else 1.0 / r2))
            if abs(power) > 1e-6:
                return max(6.0, min(200.0, abs(1.0 / power)))
        except Exception:
            pass
        return 25.0

    def _load_workbench_structure(self, profile: dict[str, Any]) -> bool:
        surfaces = list(profile.get("surfaces", []) or profile.get("project_surfaces", []) or [])
        if not surfaces:
            return False
        groups: list[tuple[str, list[dict[str, Any]]]] = []
        by_group: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for index, surface in enumerate(surfaces):
            item = dict(surface or {})
            group_id = str(item.get("group_id") or item.get("element_id") or f"L{index // 2 + 1}")
            if group_id not in by_group:
                by_group[group_id] = []
                order.append(group_id)
            by_group[group_id].append(item)
        groups = [(group_id, by_group[group_id]) for group_id in order][:6]
        if not groups:
            return False

        self.model.nodes.clear()
        self.model.edges.clear()
        self.model._counter = 0
        laser = self.model.add_node("laser", 110, MAIN_RAIL_Y, node_id="laser", label="激光器", record=False)
        isolator = self.model.add_node("isolator", 270, MAIN_RAIL_Y, node_id="isolator", label="光隔离器", record=False)
        splitter = self.model.add_node("splitter", 440, MAIN_RAIL_Y, node_id="splitter", label="分束器", record=False)
        lens_ids: list[str] = []
        start_x, end_x = 620.0, 1120.0
        spacing = (end_x - start_x) / max(1, len(groups) - 1) if len(groups) > 1 else 0.0
        for index, (_group_id, group_surfaces) in enumerate(groups):
            front = group_surfaces[0]
            back = group_surfaces[-1]
            focal = self._estimate_focal_from_surfaces(front, back)
            lens_ids.append(
                self.model.add_node(
                    "lens",
                    start_x + index * spacing,
                    MAIN_RAIL_Y,
                    node_id=f"lens_{index + 1}",
                    label=f"L{index + 1}",
                    params={"focal_mm": focal, "formal_group_id": _group_id},
                    record=False,
                )
            )
        fiber = self.model.add_node("fiber", 1270, MAIN_RAIL_Y, node_id="fiber", label="五轴光纤架", record=False)
        output_meter = self.model.add_node("power_meter", 1460, MAIN_RAIL_Y, node_id="output_meter", label="输出功率计", params={"range_mw": 20.0}, record=False)
        input_meter = self.model.add_node("power_meter", 450, BRANCH_RAIL_Y, node_id="input_meter", label="输入功率计", params={"range_mw": 500.0}, record=False)
        self.model.add_node("beam_analyzer", 930, BRANCH_RAIL_Y, node_id="beam_analyzer", label="光束分析仪", record=False)
        self.model.add_node("wavefront_sensor", 1180, BRANCH_RAIL_Y, node_id="wavefront", label="波前传感器", record=False)
        chain = [laser, isolator, splitter, *lens_ids, fiber, output_meter]
        for source, target in zip(chain, chain[1:]):
            self.model.add_edge(source, target, record=False)
        self.model.add_edge(splitter, input_meter, record=False)
        self.model.wavelength_nm = float(profile.get("wavelength_nm", getattr(self.context.project.project, "wavelength_nm", 808.0)))
        receiver_mfd = float(profile.get("receiver_mfd_um", getattr(self.context.project.project, "receiver_mfd_um", 5.6)))
        self.model.receiver_mode_radius_um = max(0.2, receiver_mfd / 2.0)
        self.model.selected_node_id = lens_ids[-1] if lens_ids else fiber
        self.model.mode = "free"
        self.model._reset_history()
        return True

    def _apply_shared_profile(self, profile: dict[str, Any], *, announce: bool = True) -> bool:
        if not isinstance(profile, dict):
            return False
        nodes = list(profile.get("nodes", []) or [])
        edges = list(profile.get("edges", []) or [])
        if nodes:
            snapshot = self.model.snapshot()
            snapshot.update(
                {
                    "mode": str(profile.get("teaching_mode", profile.get("mode", snapshot.get("mode", "free")))),
                    "nodes": nodes,
                    "edges": edges,
                    "wavelength_nm": float(profile.get("wavelength_nm", snapshot["wavelength_nm"])),
                    "input_power_mw": float(profile.get("input_power_mw", snapshot["input_power_mw"])),
                    "receiver_na": float(profile.get("receiver_na", snapshot["receiver_na"])),
                    "receiver_mode_radius_um": float(profile.get("receiver_mode_radius_um", snapshot["receiver_mode_radius_um"])),
                    "target_total_efficiency": float(profile.get("target_total_efficiency", snapshot["target_total_efficiency"])),
                    "latest_cause": "已读取共享方案参数。",
                }
            )
            self.model.restore(snapshot, reset_history=True)
            loaded = True
        else:
            loaded = self._load_workbench_structure(profile)
        if not loaded:
            return False
        layer = str(profile.get("display_layer", "overlay"))
        self.set_display_layer(layer if layer in DISPLAY_LAYER_LABELS else "overlay", force=True)
        if announce:
            self.model.record("已从正式工作台读取并恢复光源、光纤和镜片结构参数。")
        self._refresh_all(preserve_view=False)
        return True

    def _save_shared_parameters(self) -> bool:
        profile = self.current_profile()
        encoded = json.dumps(profile, ensure_ascii=False)
        try:
            self.settings.setValue("teaching/shared_snapshot_json", encoded)
            self.settings.sync()
            if self.settings.status() != QSettings.Status.NoError:
                raise OSError(f"QSettings 写入失败：{self.settings.status().name}")
            self.context.project.update_research_profile(
                {
                    "active_snapshot_source": "teaching",
                    "teaching_snapshot": profile,
                    "shared_snapshot": profile,
                }
            )
        except Exception as exc:
            _logger.exception("保存教学平台共享参数失败")
            self.model.latest_cause = f"教学参数保存失败：{exc}"
            self.model.log.append(self.model.latest_cause)
            self._refresh_all(preserve_view=True)
            QMessageBox.warning(self, "保存教学参数", self.model.latest_cause)
            return False
        self.model.latest_cause = "已保存教学平台参数，可在正式工作台继续仿真和寻优。"
        self.model.log.append(self.model.latest_cause)
        self._refresh_all(preserve_view=True)
        return True

    def _restore_persisted_snapshot(self) -> None:
        raw = self.settings.value("teaching/shared_snapshot_json", "", type=str)
        if raw:
            try:
                profile = json.loads(raw)
                if self._apply_shared_profile(profile, announce=False):
                    self.model.latest_cause = "已恢复上次保存的教学方案。"
                    self._refresh_all(preserve_view=False)
                    return
            except Exception:
                _logger.warning("恢复教学平台持久化参数失败，已使用当前方案。", exc_info=True)
        self._refresh_all(preserve_view=False)

    def _import_workbench_parameters(self) -> None:
        try:
            research_profile = self.context.project.research_profile
        except Exception:
            _logger.warning("读取正式工作台研究参数失败。", exc_info=True)
            research_profile = {}
        candidate = {}
        if isinstance(research_profile, dict):
            candidate = dict(
                research_profile.get("workbench_snapshot")
                or research_profile.get("shared_snapshot")
                or (research_profile if research_profile.get("source") in {"formal_workbench", "simulation_workbench"} else {})
            )
        if not candidate:
            raw = self.settings.value("teaching/workbench_snapshot_json", "", type=str)
            if raw:
                try:
                    candidate = dict(json.loads(raw))
                except Exception:
                    _logger.warning("正式工作台共享参数不是有效 JSON，已忽略。", exc_info=True)
                    candidate = {}
        if not candidate:
            QMessageBox.information(self, "读取工作台参数", "正式工作台尚未保存可读取的方案参数。")
            return
        if not self._apply_shared_profile(candidate):
            QMessageBox.warning(self, "读取工作台参数", "已找到工作台记录，但其中没有可映射的光学结构参数。")

    def current_profile(self) -> dict[str, Any]:
        metrics = self.model.evaluate()
        return {
            "source": "unified_teaching_workbench",
            "snapshot_version": 2,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "teaching_mode": self.model.mode,
            "view_kind": self._view_kind,
            "display_layer": self._display_layer,
            "wavelength_nm": self.model.wavelength_nm,
            "input_power_mw": self.model.input_power_mw,
            "receiver_na": self.model.receiver_na,
            "receiver_mode_radius_um": self.model.receiver_mode_radius_um,
            "target_total_efficiency": self.model.target_total_efficiency,
            "nodes": [asdict(node) for node in self.model.nodes.values()],
            "edges": [asdict(edge) for edge in self.model.edges.values()],
            "teaching_metrics": asdict(metrics),
        }

    def _enter_formal_workbench(self) -> None:
        self._save_shared_parameters()
        profile = self.current_profile()
        self.profileReady.emit(profile)
        self.navigateRequested.emit("simulation")

    
    def _apply_local_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#unifiedTeachingWorkbench { background: #EEF1F5; }
            QWidget#teachingOverlayHost { background: #FFFFFF; border: 1px solid #98A2B3; border-radius: 8px; }
            QGraphicsView#teachingMainExperimentView, QWidget#teachingExperiment3DView { background: #F7F8FA; }
            QToolButton#teachingOverlayButton, QToolButton#teachingBottomOverlayButton {
                background: rgba(255,255,255,235); color: #0A327A; border: 1px solid #667085;
                border-radius: 6px; padding: 6px 8px; font-weight: 600;
            }
            QToolButton#teachingOverlayButton:hover, QToolButton#teachingBottomOverlayButton:hover {
                background: #D6E4FF; border-color: #155EEF;
            }
            QToolButton#teachingViewControlButton {
                background: rgba(248,252,254,238); color: #344054; border: 1px solid #98A2B3;
                border-radius: 6px; padding: 4px 6px; font-weight: 600;
            }
            QToolButton#teachingViewControlButton:hover { background: #D6E4FF; border-color: #155EEF; }
            QToolButton#teachingViewControlButton:checked {
                background: #155EEF; color: #FFFFFF; border-color: #155EEF;
            }
            QFrame#teachingOverlayDrawer {
                background: rgba(250,253,255,248); border: 1px solid #667085; border-radius: 9px;
            }
            QLabel#drawerTitle, QLabel#drawerObjectTitle { font-weight: 700; color: #101828; font-size: 15px; }
            QFrame#teachingFloatingPanel {
                background: #FFFFFF; border: 1px solid #667085; border-radius: 9px;
            }
            QFrame#floatingTitleBar { background: #E6EAF0; border-radius: 6px; }
            QLabel#floatingTitle { font-weight: 700; color: #101828; }
            QLabel#teachingPrimaryMetric { color: #0b6fae; font-weight: 700; font-size: 15px; }
            QLabel#teachingCauseBar { background: #F7F8FA; color: #101828; border: 1px solid #98A2B3; border-radius: 5px; padding: 5px 8px; }
            QLabel#panelBigMetric { color: #0b6fae; font-size: 22px; font-weight: 700; }
            QLabel#warningText { background: #fff3e6; color: #8a4e00; border: 1px solid #f0c892; border-radius: 5px; padding: 8px; }
            QLabel#teachingConclusion { background: #FFFFFF; color: #101828; border-left: 4px solid #155EEF; padding: 8px; }
            QGroupBox { font-weight: 600; color: #204d69; border: 1px solid #d5e3ec; border-radius: 6px; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            """
        )


__all__ = [
    "ExperimentEdge",
    "ExperimentModel",
    "ExperimentNode",
    "UnifiedTeachingWorkbench",
    "WorkbenchMetrics",
]
