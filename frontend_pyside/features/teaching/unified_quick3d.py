from __future__ import annotations

from pathlib import Path
import math
from typing import Any

from PySide6.QtCore import QObject, Property, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .asset_registry import asset_for_kind
from .experiment_scene import (
    formal_rays_world_3d,
    main_rail_y,
    scene_node_mount_world_3d,
)


class _Unified3DBridge(QObject):
    sceneChanged = Signal()
    displayChanged = Signal()
    analysisChanged = Signal()
    rotateRequested = Signal(float)
    zoomRequested = Signal(float)
    resetRequested = Signal()
    cameraPresetRequested = Signal(str)
    toolCategoryRequested = Signal(str)
    objectActivated = Signal(str)
    objectDoubleActivated = Signal(str)
    beamSegmentActivated = Signal(str, float)
    cameraStateChanged = Signal(float, float, float)
    nodeMoveRequested = Signal(str, float, float)
    componentDropRequested = Signal(str, float, float)
    nodeOrientationRequested = Signal(str, float, float, float)
    # QML toolbar controls must not mutate the model inside the bridge.  They
    # are routed through UnifiedTeachingQuick3DView so the workbench can
    # invalidate/recompute formal rays exactly like drag operations do.
    nudgeSelectedRequested = Signal(float, float)
    rotateSelectedRequested = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nodes: list[dict[str, Any]] = []
        self._model = None
        self._edges: list[dict[str, Any]] = []
        self._envelope: list[dict[str, Any]] = []
        self._selected = ""
        self._show_nodes = True
        self._show_rays = True
        self._show_envelope = True
        self._show_axis = True
        self._mode_label = "光路教学"
        self._placement_active = False
        self._detailed_assets_enabled = True
        self._section_fraction = 0.5
        self._section_edge: dict[str, float] | None = None
        self._section_segments: list[dict[str, Any]] = []
        self._section_x = 0.0
        self._section_y = 52.0
        self._section_z = 0.0
        self._section_yaw = 0.0
        self._section_radius = 6.0
        self._section_ideal_radius = 6.0
        self._fiber_available = False
        self._fiber_radius = 0.0
        self._fiber_ideal_radius = 0.0
        self._receiver_efficiency = 0.0
        self._image_receiver_available = False
        self._image_receiver_hit = False
        self._image_receiver_label = ""
        self._image_status = "当前实验未放置成像相机"
        self._image_radius_x_um = 0.0
        self._image_radius_y_um = 0.0
        self._image_center_x_um = 0.0
        self._image_center_y_um = 0.0
        self._result_metrics: dict[str, float] = {}
        self._rail_world_z = 0.0
        self._cached_topology: tuple[tuple[str, str], ...] | None = None
        self._cached_pose: tuple[tuple[str, float, float, float, float, float, float, bool], ...] | None = None
        self._cached_rays: tuple[str, tuple[Any, ...]] | None = None
        self._cached_metrics_key: tuple[Any, ...] | None = None
        self._cached_reached: tuple[str, ...] | None = None

    @Property("QVariantMap", notify=sceneChanged)
    def resultMetrics(self):
        return dict(self._result_metrics)

    @Property(str, notify=sceneChanged)
    def resultStatus(self):
        return str(self._result_metrics.get("status", "教学预览"))

    @Property(str, notify=sceneChanged)
    def resultSource(self):
        return str(self._result_metrics.get("source", "教学近似"))

    @Property(bool, notify=sceneChanged)
    def resultEfficiencyApplicable(self):
        return bool(self._result_metrics.get("applicable", True))

    @Property("QVariantList", notify=sceneChanged)
    def nodes(self):
        return self._nodes

    @Property("QVariantList", notify=sceneChanged)
    def edges(self):
        return self._edges

    @Property("QVariantList", notify=sceneChanged)
    def envelopeSegments(self):
        return self._envelope

    @Property(str, notify=sceneChanged)
    def selectedId(self):
        return self._selected

    @Property(bool, notify=displayChanged)
    def showNodes(self):
        return self._show_nodes

    @Property(bool, notify=displayChanged)
    def showRays(self):
        return self._show_rays

    @Property(bool, notify=displayChanged)
    def showEnvelope(self):
        return self._show_envelope

    @Property(bool, notify=displayChanged)
    def showAxis(self):
        return self._show_axis

    @Property(float, notify=sceneChanged)
    def railWorldZ(self):
        # World depth of the optical rail: nodes sit at world z = (scene_y-450)*0.62.
        return self._rail_world_z

    @Property(str, notify=displayChanged)
    def modeLabel(self):
        return self._mode_label

    @Property(bool, notify=displayChanged)
    def placementActive(self):
        return self._placement_active

    @Property(bool, notify=displayChanged)
    def detailedAssetsEnabled(self):
        return self._detailed_assets_enabled

    @Property(bool, notify=analysisChanged)
    def sectionAvailable(self): return self._section_edge is not None

    @Property(float, notify=analysisChanged)
    def sectionFraction(self): return self._section_fraction

    @Property(float, notify=analysisChanged)
    def sectionX(self): return self._section_x

    @Property(float, notify=analysisChanged)
    def sectionY(self): return self._section_y

    @Property(float, notify=analysisChanged)
    def sectionZ(self): return self._section_z

    @Property(float, notify=analysisChanged)
    def sectionYaw(self): return self._section_yaw

    @Property(float, notify=analysisChanged)
    def sectionRadius(self): return self._section_radius

    @Property(float, notify=analysisChanged)
    def sectionIdealRadius(self): return self._section_ideal_radius

    @Property(bool, notify=analysisChanged)
    def fiberAvailable(self): return self._fiber_available

    @Property(float, notify=analysisChanged)
    def fiberRadius(self): return self._fiber_radius

    @Property(float, notify=analysisChanged)
    def fiberIdealRadius(self): return self._fiber_ideal_radius

    @Property(float, notify=analysisChanged)
    def receiverEfficiency(self): return self._receiver_efficiency

    @Property(bool, notify=sceneChanged)
    def imageReceiverAvailable(self): return self._image_receiver_available

    @Property(bool, notify=sceneChanged)
    def imageReceiverHit(self): return self._image_receiver_hit

    @Property(str, notify=sceneChanged)
    def imageReceiverLabel(self): return self._image_receiver_label

    @Property(str, notify=sceneChanged)
    def imageStatus(self): return self._image_status

    @Property(float, notify=sceneChanged)
    def imageRadiusXUm(self): return self._image_radius_x_um

    @Property(float, notify=sceneChanged)
    def imageRadiusYUm(self): return self._image_radius_y_um

    @Property(float, notify=sceneChanged)
    def imageCenterXUm(self): return self._image_center_x_um

    @Property(float, notify=sceneChanged)
    def imageCenterYUm(self): return self._image_center_y_um

    def _update_section_values(self) -> None:
        segments = list(self._section_segments or ([] if self._section_edge is None else [self._section_edge]))
        if not segments:
            self._section_edge = None
            self.analysisChanged.emit()
            return
        total = sum(max(float(item.get("length", 0.0)), 1e-9) for item in segments)
        distance = max(0.0, min(1.0, float(self._section_fraction))) * total
        edge = segments[-1]
        local = 1.0
        walked = 0.0
        for candidate in segments:
            length = max(float(candidate.get("length", 0.0)), 1e-9)
            if distance <= walked + length or candidate is segments[-1]:
                edge = candidate
                local = max(0.0, min(1.0, (distance - walked) / length))
                break
            walked += length
        self._section_edge = edge
        self._section_x = edge["x1"] + (edge["x2"] - edge["x1"]) * local
        self._section_y = edge.get("y1", 52.0) + (edge.get("y2", 52.0) - edge.get("y1", 52.0)) * local
        self._section_z = edge["z1"] + (edge["z2"] - edge["z1"]) * local
        dx = edge["x2"] - edge["x1"]
        dz = edge["z2"] - edge["z1"]
        self._section_yaw = -math.degrees(math.atan2(dz, dx)) if abs(dx) + abs(dz) > 1e-9 else 0.0
        self._section_radius = edge["r0"] + (edge["r1"] - edge["r0"]) * local
        self._section_ideal_radius = edge["i0"] + (edge["i1"] - edge["i0"]) * local
        self.analysisChanged.emit()

    @Slot(float)
    def setCrossSectionFraction(self, value: float) -> None:
        next_value = max(0.0, min(1.0, float(value)))
        if abs(next_value - self._section_fraction) < 1e-6:
            return
        self._section_fraction = next_value
        self._update_section_values()

    def _topology_key(self, model: Any) -> tuple[tuple[str, str], ...]:
        nodes = dict(getattr(model, "nodes", {}) or {})
        return tuple(sorted((str(node_id), str(getattr(node, "kind", "generic") or "generic")) for node_id, node in nodes.items()))

    def _pose_key(self, model: Any) -> tuple[tuple[str, float, float, float, float, float, float, bool], ...]:
        selected = str(getattr(model, "selected_node_id", "") or "")
        parts: list[tuple[str, float, float, float, float, float, float, bool]] = []
        for node_id in sorted(dict(getattr(model, "nodes", {}) or {})):
            node = model.nodes[node_id]
            x, y, z = scene_node_mount_world_3d(node)
            params = dict(getattr(node, "params", {}) or {})
            parts.append(
                (
                    str(node_id),
                    round(x, 2),
                    round(y, 2),
                    round(z, 2),
                    round(float(getattr(node, "rotation_deg", 0.0) or 0.0), 2),
                    round(float(params.get("pitch_deg", 0.0) or 0.0), 2),
                    round(float(params.get("roll_deg", 0.0) or 0.0), 2),
                    str(node_id) == selected,
                )
            )
        return tuple(parts)

    def _formal_rays_key(self, snapshot: Any) -> tuple[str, tuple[Any, ...]]:
        world = tuple(getattr(snapshot, "formal_rays_world", ()) or ())
        if world:
            return ("world", world)
        return ("mm", tuple(getattr(snapshot, "formal_rays_mm", ()) or ()))

    def _metrics_key(self, snapshot: Any) -> tuple[Any, ...]:
        metrics = getattr(snapshot, "metrics", None)
        return (
            round(float(getattr(metrics, "total_efficiency", 0.0) or 0.0), 5),
            round(float(getattr(metrics, "system_efficiency", 0.0) or 0.0), 5),
            round(float(getattr(metrics, "receiver_efficiency", 0.0) or 0.0), 5),
            round(float(getattr(metrics, "output_power_mw", 0.0) or 0.0), 4),
            tuple(sorted(getattr(metrics, "reached_node_ids", ()) or ())),
            str(getattr(snapshot, "physics_status", "pending") or "pending"),
            tuple(getattr(snapshot, "validation_messages", ()) or ()),
            str(getattr(snapshot, "efficiency_source", "") or ""),
            str(getattr(snapshot, "efficiency_status", "") or ""),
            dict(getattr(snapshot, "current_radii", {}) or {}),
            dict(getattr(snapshot, "ideal_radii", {}) or {}),
        )

    def _build_node_payload(self, node_id: str, node: Any, *, reached: set[str], selected: str) -> dict[str, Any]:
        x, y, z = scene_node_mount_world_3d(node)
        kind = str(getattr(node, "kind", "generic") or "generic")
        asset = asset_for_kind(kind)
        fallback_source = "#Cylinder" if kind in {"lens", "fiber", "isolator", "half_wave_plate", "aperture"} else "#Cube"
        fallback_scale = {
            "lens": (0.52, 0.10, 0.52),
            "fiber": (0.22, 0.50, 0.22),
            "isolator": (0.32, 0.48, 0.32),
            "mirror": (0.08, 0.55, 0.46),
            "laser": (0.85, 0.42, 0.48),
            "power_meter": (0.50, 0.48, 0.55),
            "camera": (0.50, 0.48, 0.55),
            "wavefront_sensor": (0.50, 0.48, 0.55),
            "splitter": (0.45, 0.45, 0.18),
            "pbs": (0.45, 0.45, 0.18),
            "beam_sampler": (0.45, 0.45, 0.18),
        }.get(kind, (0.42, 0.42, 0.42))
        return {
            "id": str(node_id),
            "kind": kind,
            "label": str(getattr(node, "label", node_id) or node_id),
            "x": x,
            "y": y,
            "z": z,
            "rotation": float(getattr(node, "rotation_deg", 0.0) or 0.0),
            "pitch": float(getattr(node, "params", {}).get("pitch_deg", 0.0) or 0.0),
            "roll": float(getattr(node, "params", {}).get("roll_deg", 0.0) or 0.0),
            "active": str(node_id) in reached,
            "selected": str(node_id) == selected,
            "assetId": asset.asset_id,
            "assetQml": asset.qml,
            "assetTier": asset.tier,
            "pickX": asset.pick_scale[0],
            "pickY": asset.pick_scale[1],
            "pickZ": asset.pick_scale[2],
            "fallbackSource": fallback_source,
            "fallbackRotateZ": 90.0 if fallback_source == "#Cylinder" else 0.0,
            "fallbackX": fallback_scale[0],
            "fallbackY": fallback_scale[1],
            "fallbackZ": fallback_scale[2],
        }

    def _rebuild_nodes(self, model: Any, snapshot: Any) -> None:
        nodes_by_id = dict(getattr(model, "nodes", {}) or {})
        metrics = getattr(snapshot, "metrics", None)
        reached = set(getattr(metrics, "reached_node_ids", ()) or ())
        selected = str(getattr(model, "selected_node_id", "") or "")
        self._selected = selected
        self._nodes = [
            self._build_node_payload(str(node_id), node, reached=reached, selected=selected)
            for node_id, node in nodes_by_id.items()
        ]

    def _display_formal_rays_world(
        self,
        world_rays: tuple[tuple[tuple[float, float, float], ...], ...],
    ) -> tuple[tuple[tuple[float, float, float], ...], ...]:
        """Teaching Quick3D shows one chief formal ray, not the full pupil fan."""
        if not world_rays:
            return ()
        if len(world_rays) == 1:
            return world_rays
        chief_index = min(
            range(len(world_rays)),
            key=lambda index: (
                math.hypot(float(world_rays[index][0][0]), float(world_rays[index][0][1]))
                if world_rays[index]
                else float("inf")
            ),
        )
        return (world_rays[chief_index],)

    def _rebuild_rays(self, model: Any, snapshot: Any) -> list[dict[str, Any]]:
        nodes_by_id = dict(getattr(model, "nodes", {}) or {})
        self._edges = []
        self._envelope = []
        self._section_edge = None
        self._section_segments = []
        active_section_segments: list[dict[str, Any]] = []
        world_direct = tuple(getattr(snapshot, "formal_rays_world", ()) or ())
        if world_direct:
            formal_rays = self._display_formal_rays_world(world_direct)
        else:
            formal_rays = formal_rays_world_3d(
                model,
                getattr(snapshot, "formal_rays_mm", ()) or (),
                max_rays=1,
            )
        ray_sets = [
            ([f"formal:{ray_index}:{point_index}" for point_index in range(len(ray))], list(ray))
            for ray_index, ray in enumerate(formal_rays)
        ]
        for ray_index, (point_ids, ray) in enumerate(ray_sets):
            for segment_index, (start3, end3) in enumerate(zip(ray, ray[1:])):
                x1, y1, z1 = start3
                x2, y2, z2 = end3
                source_id = str(point_ids[segment_index])
                target_id = str(point_ids[segment_index + 1])
                edge_id = f"chief:{ray_index}:{segment_index}:{source_id}->{target_id}"
                length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)
                meta = {
                    "source_id": source_id,
                    "target_id": target_id,
                    "x1": x1,
                    "y1": y1,
                    "z1": z1,
                    "x2": x2,
                    "y2": y2,
                    "z2": z2,
                    "r0": 0.85,
                    "r1": 0.85,
                    "i0": 0.85,
                    "i1": 0.85,
                    "length": max(length, 1e-9),
                }
                active_section_segments.append(meta)
                self._edges.append(
                    {
                        "id": edge_id,
                        "x1": x1,
                        "y1": y1,
                        "z1": z1,
                        "x2": x2,
                        "y2": y2,
                        "z2": z2,
                        "active": True,
                    }
                )
        fiber_node = next((node for node in nodes_by_id.values() if str(getattr(node, "kind", "")) == "fiber"), None)
        if active_section_segments:
            selected_path: list[dict[str, Any]] = []
            fiber_id_for_path = str(getattr(fiber_node, "id", "") or "") if fiber_node is not None else ""
            by_target = {str(item.get("target_id", "")): item for item in active_section_segments}
            cursor = fiber_id_for_path
            visited: set[str] = set()
            while cursor and cursor not in visited and cursor in by_target:
                visited.add(cursor)
                segment = by_target[cursor]
                selected_path.append(segment)
                cursor = str(segment.get("source_id", ""))
            if selected_path:
                selected_path.reverse()
                self._section_segments = selected_path
            else:
                self._section_segments = active_section_segments
            self._section_edge = self._section_segments[0]
        return active_section_segments

    def _update_scene_overlays(self, model: Any, snapshot: Any) -> None:
        nodes_by_id = dict(getattr(model, "nodes", {}) or {})
        metrics = getattr(snapshot, "metrics", None)
        current_radii = dict(getattr(snapshot, "current_radii", {}) or {})
        ideal_radii = dict(getattr(snapshot, "ideal_radii", {}) or {})
        self._selected = str(getattr(model, "selected_node_id", "") or "")
        camera_priority = {"ccd": 0, "imaging_camera": 1, "camera": 2, "beam_analyzer": 3}
        camera_nodes = [
            node for node in nodes_by_id.values()
            if str(getattr(node, "kind", "")) in camera_priority
        ]
        camera_nodes.sort(
            key=lambda node: (
                0 if str(getattr(node, "id", "")) == self._selected else 1,
                camera_priority.get(str(getattr(node, "kind", "")), 99),
            )
        )
        camera_readings: list[tuple[Any, dict[str, Any]]] = []
        for candidate in camera_nodes:
            try:
                reading = dict(model.instrument_reading(str(getattr(candidate, "id", ""))) or {})
            except Exception:
                reading = {}
            camera_readings.append((candidate, reading))
        selected_camera = next(
            ((candidate, reading) for candidate, reading in camera_readings if bool(reading.get("valid", False))),
            camera_readings[0] if camera_readings else (None, {}),
        )
        camera_node, reading = selected_camera
        self._image_receiver_available = camera_node is not None
        formal_camera_hit = (
            str(getattr(snapshot, "physics_status", "pending")) == "verified"
            and bool(tuple(getattr(snapshot, "formal_rays_mm", ()) or ()))
        )
        self._image_receiver_hit = bool(reading.get("valid", False)) and formal_camera_hit if camera_node is not None else False
        self._image_receiver_label = str(getattr(camera_node, "label", "") or "相机") if camera_node is not None else ""
        self._image_status = "当前实验未放置成像相机"
        self._image_radius_x_um = 0.0
        self._image_radius_y_um = 0.0
        self._image_center_x_um = 0.0
        self._image_center_y_um = 0.0
        if camera_node is not None:
            if self._image_receiver_hit:
                self._image_radius_x_um = max(0.0, float(reading.get("radius_x_um", 0.0) or 0.0))
                self._image_radius_y_um = max(0.0, float(reading.get("radius_y_um", 0.0) or 0.0))
                self._image_center_x_um = float(reading.get("center_x_um", 0.0) or 0.0)
                self._image_center_y_um = float(reading.get("center_y_um", 0.0) or 0.0)
                self._image_status = "正式追迹已命中感光面；光斑尺寸为教学测量预览"
            else:
                self._image_status = (
                    "等待当前版本正式追迹命中相机感光面"
                    if bool(reading.get("valid", False)) else
                    str(reading.get("message", "光束未命中相机感光面；请调整相机位置或方向。"))
                )
        fiber_node = next((node for node in nodes_by_id.values() if str(getattr(node, "kind", "")) == "fiber"), None)
        if fiber_node is not None:
            fiber_id = str(getattr(fiber_node, "id", "") or "")
            self._fiber_available = bool(fiber_id)
            self._fiber_radius = float(current_radii.get(fiber_id, 0.0) or 0.0)
            self._fiber_ideal_radius = float(ideal_radii.get(fiber_id, 0.0) or 0.0)
        else:
            self._fiber_available = False
            self._fiber_radius = 0.0
            self._fiber_ideal_radius = 0.0
        try:
            self._receiver_efficiency = float(getattr(metrics, "receiver_efficiency", 0.0) or 0.0)
            self._result_metrics = {
                "total": float(getattr(metrics, "total_efficiency", 0.0) or 0.0),
                "system": float(getattr(metrics, "system_efficiency", 0.0) or 0.0),
                "receiver": self._receiver_efficiency,
                "power": float(getattr(metrics, "output_power_mw", 0.0) or 0.0),
                "status": (
                    str(getattr(snapshot, "validation_messages", ())[0])
                    if getattr(snapshot, "validation_messages", ())
                    else (
                        "光线已验证" if str(getattr(snapshot, "physics_status", "pending")) == "verified"
                        else "正式光线待计算"
                    )
                ),
                "source": str(getattr(snapshot, "efficiency_source", "教学快速估算") or "教学快速估算"),
                "applicable": str(getattr(snapshot, "efficiency_status", "preview")) != "not_applicable",
            }
        except (TypeError, ValueError):
            self._receiver_efficiency = 0.0
            self._result_metrics = {}
        self._rail_world_z = (main_rail_y(model) - 450.0) * 0.62

    def set_scene(self, model: Any, snapshot: Any) -> None:
        self._model = model
        topology = self._topology_key(model)
        pose = self._pose_key(model)
        rays = self._formal_rays_key(snapshot)
        metrics_key = self._metrics_key(snapshot)
        metrics = getattr(snapshot, "metrics", None)
        reached_key = tuple(sorted(str(item) for item in (getattr(metrics, "reached_node_ids", ()) or ())))
        need_nodes = topology != self._cached_topology
        need_pose = pose != self._cached_pose
        need_rays = rays != self._cached_rays or need_nodes
        need_active = reached_key != self._cached_reached
        if (
            not need_nodes
            and not need_pose
            and not need_rays
            and not need_active
            and metrics_key == self._cached_metrics_key
        ):
            return
        if not need_nodes and not need_pose and not need_rays:
            if need_active:
                reached = set(reached_key)
                for item in self._nodes:
                    item["active"] = str(item.get("id", "")) in reached
                self._cached_reached = reached_key
            self._update_scene_overlays(model, snapshot)
            self._cached_metrics_key = metrics_key
            self._update_section_values()
            self.sceneChanged.emit()
            return
        if need_nodes:
            self._rebuild_nodes(model, snapshot)
            self._cached_topology = topology
        elif need_pose:
            metrics = getattr(snapshot, "metrics", None)
            reached = set(getattr(metrics, "reached_node_ids", ()) or ())
            selected = str(getattr(model, "selected_node_id", "") or "")
            self._selected = selected
            self._nodes = [
                self._build_node_payload(str(node_id), model.nodes[node_id], reached=reached, selected=selected)
                for node_id in sorted(dict(getattr(model, "nodes", {}) or {}))
            ]
        if need_rays:
            self._rebuild_rays(model, snapshot)
            self._cached_rays = rays
        self._cached_pose = pose
        self._cached_reached = reached_key
        self._update_scene_overlays(model, snapshot)
        self._cached_metrics_key = metrics_key
        self._update_section_values()
        self.sceneChanged.emit()

    def set_display_layer(self, layer: str) -> None:
        value = str(layer or "overlay")
        if value == "experiment":
            self._mode_label = "实验外观"
            self._show_nodes, self._show_rays, self._show_envelope, self._show_axis = True, True, False, False
        elif value == "principle":
            self._mode_label = "光路教学"
            self._show_nodes, self._show_rays, self._show_envelope, self._show_axis = True, True, True, True
        else:
            self._mode_label = "光路教学"
            self._show_nodes, self._show_rays, self._show_envelope, self._show_axis = True, True, True, True
        self.displayChanged.emit()

    def set_rays_only(self, enabled: bool) -> None:
        self._show_nodes = not bool(enabled)
        self._show_rays = True
        self._show_envelope = True
        self.displayChanged.emit()

    def set_placement_active(self, enabled: bool) -> None:
        self._placement_active = bool(enabled)
        self.displayChanged.emit()

    @Slot(bool)
    def setDetailedAssetsEnabled(self, enabled: bool) -> None:
        value = bool(enabled)
        if value == self._detailed_assets_enabled:
            return
        self._detailed_assets_enabled = value
        self.displayChanged.emit()

    @Slot(str)
    def activate(self, object_id: str) -> None:
        value = str(object_id or "")
        if value.startswith("beam:"):
            self.beamSegmentActivated.emit(value.split(":", 1)[1], 0.5)
            return
        self.objectActivated.emit(value)

    @Slot(str)
    def activateDouble(self, object_id: str) -> None:
        self.objectDoubleActivated.emit(str(object_id or ""))

    @Slot(float, float)
    def nudgeSelected(self, dx: float, dy: float) -> None:
        # Do not edit the shared model here.  QML talks to this bridge directly,
        # while formal-physics refresh is owned by the QWidget/workbench layer.
        self.nudgeSelectedRequested.emit(float(dx), float(dy))

    @Slot(float)
    def rotateSelected(self, degrees: float) -> None:
        self.rotateSelectedRequested.emit(float(degrees))

    @Slot(str)
    def setCameraPreset(self, preset: str) -> None:
        self.cameraPresetRequested.emit(str(preset or "isometric"))

    @Slot(str)
    def requestPreset(self, label: str) -> None:
        self.displayChanged.emit()

    @Slot(str, float, float)
    def moveNodeWorld(self, node_id: str, world_x: float, world_z: float) -> None:
        # Inverse of set_scene()'s deterministic 2D -> 3D mapping.  The model
        # performs the final boundary clamp, so 2D and 3D remain one scene state.
        scene_x = float(world_x) / 0.76 + 800.0
        scene_y = float(world_z) / 0.62 + 450.0
        self.nodeMoveRequested.emit(str(node_id or ""), scene_x, scene_y)

    @Slot(str, float, float)
    def dropComponentWorld(self, kind: str, world_x: float, world_z: float) -> None:
        """Convert a Quick3D table-plane drop into the shared scene coordinates."""
        scene_x = float(world_x) / 0.76 + 800.0
        scene_y = float(world_z) / 0.62 + 450.0
        self.componentDropRequested.emit(str(kind or ""), scene_x, scene_y)

    @Slot(str, float, float, float)
    def setNodeOrientation(self, node_id: str, yaw: float, pitch: float, roll: float) -> None:
        self.nodeOrientationRequested.emit(str(node_id or ""), float(yaw), float(pitch), float(roll))

    @Slot(float, float, float)
    def reportCameraState(self, azimuth: float, elevation: float, zoom: float) -> None:
        self.cameraStateChanged.emit(float(azimuth), float(elevation), float(zoom))


class UnifiedTeachingQuick3DView(QWidget):
    """Qt Quick 3D view for the main teaching workbench.

    The old Experiment3DView was a QPainter perspective illustration.  This widget
    uses View3D/PerspectiveCamera and true 3D primitives for devices, ray paths and
    the Gaussian envelope while keeping the existing ExperimentModel as the shared
    scene state used by the 2D view.
    """

    objectActivated = Signal(str)
    objectDoubleActivated = Signal(str)
    objectChanged = Signal(str, str)
    cameraChanged = Signal(float, float, float)
    beamSegmentActivated = Signal(str, float)
    nodeMoved = Signal(str, float, float)
    componentDropped = Signal(str, float, float)
    nodeControlChanged = Signal(str)
    toolCategoryRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teachingExperimentQuick3DView")
        self.setMinimumSize(600, 380)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._qml_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[2] / "resources" / "qml" / "unified_teaching_scene_3d.qml")
        )
        self._scene_suspended = False
        self._quick = QQuickWidget(self)
        # Keep the Quick/3D surface embedded. On some Windows + RHI stacks the scene
        # graph can briefly promote an untitled native window (icon + maximize + close).
        self._quick.setWindowFlags(Qt.WindowType.Widget)
        self._quick.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._quick.setClearColor(QColor("#F4F7FA"))
        self._bridge = _Unified3DBridge(self)
        self._bridge.objectActivated.connect(self.objectActivated)
        self._bridge.objectDoubleActivated.connect(self.objectDoubleActivated)
        self._bridge.beamSegmentActivated.connect(self.beamSegmentActivated)
        self._bridge.nodeMoveRequested.connect(self.nodeMoved)
        self._bridge.componentDropRequested.connect(self.componentDropped)
        self._bridge.nodeOrientationRequested.connect(self._on_node_orientation_requested)
        self._bridge.nudgeSelectedRequested.connect(self.nudgeSelected)
        self._bridge.rotateSelectedRequested.connect(self.rotateSelected)
        self._bridge.cameraPresetRequested.connect(self.set_view_preset)
        self._bridge.toolCategoryRequested.connect(self.toolCategoryRequested)
        self._bridge.cameraStateChanged.connect(self._on_camera_state_changed)
        self._quick.rootContext().setContextProperty("sceneBridge", self._bridge)
        self._quick.setSource(self._qml_url)
        self._quick.setAcceptDrops(True)
        layout.addWidget(self._quick)
        self._model = None
        self._snapshot = None
        self._instrument_placement_kind = None
        self._camera_state = (18.0, 22.0, 1.0)
        self._scene_flush_timer = QTimer(self)
        self._scene_flush_timer.setSingleShot(True)
        self._scene_flush_timer.setInterval(16)
        self._scene_flush_timer.timeout.connect(self._flush_scene)

    def suspend_scene_graph(self) -> None:
        """Unload Quick3D while the teaching page is hidden to avoid orphan native windows."""
        if self._scene_suspended:
            return
        self._scene_suspended = True
        self._scene_flush_timer.stop()
        self._quick.hide()
        self._quick.setSource(QUrl())

    def resume_scene_graph(self) -> None:
        if not self._scene_suspended:
            return
        self._scene_suspended = False
        self._quick.setSource(self._qml_url)
        self._quick.show()
        if self._model is not None:
            self._scene_flush_timer.start()

    def hideEvent(self, event) -> None:
        self.suspend_scene_graph()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.isVisible():
            self.resume_scene_graph()

    def _flush_scene(self) -> None:
        if self._model is None:
            return
        snapshot = self._snapshot or self._model.scene_snapshot()
        self._bridge.set_scene(self._model, snapshot)

    def set_model(self, model, snapshot=None) -> None:
        self._model = model
        self._snapshot = snapshot or model.scene_snapshot()
        self._scene_flush_timer.start()

    def _on_node_orientation_requested(self, node_id: str, yaw: float, pitch: float, roll: float) -> None:
        if self._model is None or str(node_id or "") not in getattr(self._model, "nodes", {}):
            return
        node = self._model.nodes[str(node_id)]
        self._model.set_orientation(str(node_id), yaw_deg=float(yaw), pitch_deg=float(pitch), roll_deg=float(roll), record=True)
        self._bridge.set_scene(self._model, self._snapshot or self._model.scene_snapshot())
        self.objectChanged.emit(str(node_id), "3D旋转")

    @Slot(float, float)
    def nudgeSelected(self, dx: float, dy: float) -> None:
        node_id = str(getattr(self._model, "selected_node_id", "") or "")
        node = getattr(self._model, "nodes", {}).get(node_id) if self._model is not None else None
        if node is None:
            return
        self._model.move_node_3d(node_id, node.x + float(dx), node.y + float(dy), float(node.params.get("z_mm", 82.0)), record=True)
        self._model.rebuild_auto_paths()
        self._refresh_after_control(node_id)

    @Slot(float)
    def rotateSelected(self, degrees: float) -> None:
        node_id = str(getattr(self._model, "selected_node_id", "") or "")
        node = getattr(self._model, "nodes", {}).get(node_id) if self._model is not None else None
        if node is None:
            return
        self._model.set_orientation(node_id, yaw_deg=float(node.rotation_deg) + float(degrees), record=True)
        self._model.rebuild_auto_paths()
        self._refresh_after_control(node_id)

    def _refresh_after_control(self, node_id: str) -> None:
        self._snapshot = self._model.scene_snapshot()
        self._bridge.set_scene(self._model, self._snapshot)
        self.nodeControlChanged.emit(node_id)
        if hasattr(self._model, "request_formal_recompute"):
            self._model.request_formal_recompute()

    def set_display_layer(self, layer: str) -> None:
        self._bridge.set_display_layer(layer)

    def set_rays_only(self, enabled: bool) -> None:
        self._bridge.set_rays_only(enabled)

    def rotate_camera(self, degrees: float) -> None:
        self._bridge.rotateRequested.emit(float(degrees))

    def reset_camera(self) -> None:
        self._bridge.resetRequested.emit()

    def zoom_in(self) -> None:
        self._bridge.zoomRequested.emit(0.88)

    def zoom_out(self) -> None:
        self._bridge.zoomRequested.emit(1.14)

    def focus_selected(self) -> None:
        # Current version keeps camera navigation deterministic; selected component remains highlighted.
        self._bridge.resetRequested.emit()

    def set_instrument_placement_kind(self, kind: str | None) -> None:
        self._instrument_placement_kind = str(kind) if kind else None
        self._bridge.set_placement_active(bool(self._instrument_placement_kind))

    def set_analysis_panels_visible(self, visible: bool) -> None:
        root = self._quick.rootObject()
        if root is not None:
            try:
                root.setProperty("analysisPanelsVisible", bool(visible))
            except Exception:
                pass

    def set_layer_visible(self, key: str, visible: bool) -> None:
        key = str(key or "")
        if key in {"beam", "chief_ray"}:
            self._bridge._show_rays = bool(visible)
        elif key == "beam_envelope":
            self._bridge._show_envelope = bool(visible)
        elif key == "axis":
            self._bridge._show_axis = bool(visible)
        elif key == "structure":
            self._bridge._show_nodes = bool(visible)
        # ideal/coordinates/measurement/sample_rays are optional diagnostic layers;
        # keeping them as no-op flags preserves compatibility without inventing data.
        self._bridge.displayChanged.emit()

    def camera_state(self) -> tuple[float, float, float]:
        return self._camera_state

    def _on_camera_state_changed(self, azimuth: float, elevation: float, zoom: float) -> None:
        self._camera_state = (float(azimuth), float(elevation), float(zoom))
        self.cameraChanged.emit(*self._camera_state)

    def set_view_preset(self, preset: str) -> None:
        root = self._quick.rootObject()
        if root is not None:
            try:
                root.setProperty("requestedPreset", str(preset or "isometric"))
                # Toggle the serial so QML applies even when the same preset is chosen twice.
                root.setProperty("presetSerial", int(root.property("presetSerial") or 0) + 1)
            except Exception:
                pass

    def focus_node(self, node_id: str) -> None:
        if self._model is not None and str(node_id or "") in getattr(self._model, "nodes", {}):
            self._model.selected_node_id = str(node_id)
            self._bridge.set_scene(self._model, self._snapshot or self._model.scene_snapshot())
        self.focus_selected()

    def align_to_selected_beam(self) -> None:
        self.focus_selected()

    def qml_errors(self) -> list[str]:
        return [error.toString() for error in self._quick.errors()]
