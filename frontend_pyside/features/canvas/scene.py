"""画布场景：节点 / 连线的增删改管、脏传播、快照导出与恢复。

- add_node(key)：经 registry 解析 NodeSpec → 工厂创建节点；singleton 去重（已存在则闪烁聚焦）；
- view/tool 节点加入时自动连到激活 source（最近聚焦的镜头组，无则退回首个 source）；
- 新节点落点：按工作流分列（镜头组 | 分析/任务 | 数据 | 模型），列宽按实际展开尺寸累加；
- auto_layout（整理布局）：列距用节点实际宽度（含子节点伸出），行距用展开高度，信息卡跟父节点；
- source 节点变更 → mark_downstream_stale 沿边传播「!」；
- snapshot()/restore()：布局持久化的数据源（QSettings 存储由 layout_store 完成）。
"""

from __future__ import annotations

import itertools
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtWidgets import QGraphicsScene

from frontend_pyside.features.canvas.edges import EdgeItem
from frontend_pyside.features.canvas.invalidation_map import node_affected
from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.registry import (
    CHART_KIND_BY_KEY,
    NodeSpec,
    spec as resolve_spec,
)

SNAPSHOT_VERSION = 2

# 落点参数（世界坐标）：按工作流分列，列内 y 网格避让
_SLOT_GAP_X = 72.0        # 镜头组右边缘到分析列的间距
_SLOT_STEP_Y = 24.0       # y 方向网格步进
_SLOT_MAX_ROWS = 96       # 单列最大步进次数
_SLOT_MARGIN = 24.0       # 候选矩形外扩边距
_LANE_GAP = 64.0          # 工作流列间距
_LANE_MIN_WIDTH = 420.0   # 空列占位（新节点落点预留分析列，避免直接压到数据列）
_FALLBACK_ORIGIN = QPointF(280.0, 80.0)  # 给左侧参数胶囊留空，避免顶到左栏
_LANE_ROW_GAP = 28.0
_LANE_ROW_GAP_EXPANDED = 48.0  # 展开节点下方多留空，避免贴着下一张卡
_SATELLITE_GAP = 48.0     # 信息/预测子节点贴在父节点右侧
_SATELLITE_KEYS = frozenset({"forward_result"})

_LEGACY_PANEL_KEYS = frozenset({
    "overview", "system", "physical_inverse", "model_build", "forward",
    "ml_inverse", "model_explain", "model_manage", "data", "tasks",
})


_TASK_NODE_KEYS = frozenset({
    "scan", "tolerance", "optimize", "physical_inverse", "ml_inverse",
    "random_forest", "xgboost_physics_residual", "bilstm_structure_sequence",
})

_MODEL_NODE_KEYS = frozenset({
    "random_forest", "xgboost_physics_residual", "bilstm_structure_sequence",
})
_SKIP_AUTO_EDGE_KEYS = frozenset({"compute_settings"})
_MODEL_LANE_KEYS = _MODEL_NODE_KEYS | frozenset({
    "forward", "forward_result", "model_build", "model_explain", "model_manage",
})
_DATA_LANE_KEYS = frozenset({"data", "tasks"})


def default_node_factory(spec: NodeSpec, node_id: str) -> CanvasNode:
    """NodeSpec → 节点实例。壳层可注入自定义工厂替换（panel / 3D 等需 context）。"""
    if spec.node_kind == "source" and spec.key == "lens_editor":
        from frontend_pyside.features.canvas.lens_node import LensNode

        return LensNode(node_id, spec)
    if spec.node_kind == "data" or spec.key == "data":
        from frontend_pyside.features.canvas.dataset_node import DatasetNode

        return DatasetNode(node_id, spec)
    if spec.node_kind == "tool" and spec.key in _TASK_NODE_KEYS:
        if spec.key in {"random_forest", "xgboost_physics_residual", "bilstm_structure_sequence"}:
            from frontend_pyside.features.canvas.model_node import ModelNode

            return ModelNode(node_id, spec, spec.key)
        from frontend_pyside.features.canvas.task_node import TaskNode

        return TaskNode(node_id, spec, spec.key)
    if spec.node_kind == "tool" and spec.key == "compute_settings":
        from frontend_pyside.features.canvas.config_node import ConfigNode

        return ConfigNode(node_id, spec)
    if spec.node_kind == "summary" and spec.key == "forward":
        from frontend_pyside.features.canvas.forward_node import ForwardNode

        return ForwardNode(node_id, spec)
    if spec.node_kind == "summary" and spec.key == "model_explain":
        from frontend_pyside.features.canvas.explain_node import ExplainNode

        return ExplainNode(node_id, spec)
    if spec.node_kind == "summary":
        from frontend_pyside.features.canvas.native_summary_node import NativeSummaryNode

        return NativeSummaryNode(node_id, spec)
    chart_kind = CHART_KIND_BY_KEY.get(spec.key)
    if chart_kind is not None:
        from frontend_pyside.features.canvas.chart_node import ChartNode

        return ChartNode(node_id, spec, chart_kind)
    # 未注册专用实现的节点由壳层工厂接管：通用骨架
    return CanvasNode(node_id, spec)


NodeFactory = Callable[[NodeSpec, str], CanvasNode]


class CanvasScene(QGraphicsScene):
    """无限画布场景：节点注册表驱动的节点/边生命周期管理。"""

    nodeAdded = Signal(str)  # node_id
    nodeRemoved = Signal(str)  # node_id
    sourceChanged = Signal(str, str)  # (source_node_id, reason)
    refreshRequested = Signal(str)  # node_id（请求引擎刷新）
    topologyChanged = Signal()  # 节点/边增删
    layoutDirty = Signal()  # 位置/尺寸/折叠变化（防抖持久化）

    def __init__(self, node_factory: NodeFactory | None = None, parent=None):
        super().__init__(parent)
        self.setSceneRect(QRectF(-4000.0, -3000.0, 8000.0, 6000.0))
        self._factory: NodeFactory = node_factory or default_node_factory
        self._nodes: dict[str, CanvasNode] = {}
        self._edges: list[EdgeItem] = []
        self._id_counter = itertools.count(1)
        self._restoring = False
        self._active_source_id: str | None = None
        self._refreshing_edges = False
        self._hovered_node: CanvasNode | None = None
        self.selectionChanged.connect(self._track_active_source)
        self.selectionChanged.connect(self._refresh_edge_highlights)

    # ---- 节点管理 -----------------------------------------------------------

    def node(self, node_id: str) -> CanvasNode | None:
        return self._nodes.get(str(node_id))

    def nodes(self) -> tuple[CanvasNode, ...]:
        return tuple(self._nodes.values())

    def nodes_by_key(self, key: str) -> tuple[CanvasNode, ...]:
        return tuple(n for n in self._nodes.values() if n.spec.key == str(key))

    def add_node(
        self,
        key: str | NodeSpec,
        pos: QPointF | None = None,
        *,
        expanded: bool = False,
        size: tuple[float, float] | None = None,
        node_id: str | None = None,
    ) -> CanvasNode | None:
        node_spec = key if isinstance(key, NodeSpec) else resolve_spec(str(key))
        if node_spec is None:
            return None
        # singleton 去重：已存在 → 闪烁 + 返回现有节点
        if node_spec.singleton:
            for existing in self.nodes_by_key(node_spec.key):
                existing.flash()
                self._emit_layout()
                return existing
        final_id = str(node_id) if node_id else f"{node_spec.key}#{next(self._id_counter)}"
        node = self._factory(node_spec, final_id)
        if not isinstance(node, CanvasNode):
            raise TypeError(f"工厂返回的不是 CanvasNode：{type(node)!r}")
        if size is not None:
            node.resize(float(size[0]), float(size[1]))
        # 落点按节点落位后的实际尺寸避让（右栏点击即展开 → 按展开尺寸算）
        node.setPos(pos if pos is not None else self._free_slot(node, expanded=expanded))
        self._wire_node(node)
        self.addItem(node)
        self._nodes[node.node_id] = node
        if node.is_source:
            self._active_source_id = node.node_id  # 新 source 即激活
        if expanded:
            node.expand()
        # 视图/任务/数据/模型都接入正式工作流；参数胶囊不经过此处。
        if node.node_kind in ("source", "view", "tool", "data") and not self._restoring:
            self._repair_workflow_edges(node)
        self.nodeAdded.emit(node.node_id)
        self.topologyChanged.emit()
        self._emit_layout()
        return node

    def remove_node(self, node_id: str) -> bool:
        node = self._nodes.pop(str(node_id), None)
        if node is None:
            return False
        if node.node_id == self._active_source_id:
            self._active_source_id = None
        keep: list[EdgeItem] = []
        for edge in self._edges:
            if edge.target is node or edge.source is node:
                edge.dispose()
                self.removeItem(edge)
            else:
                keep.append(edge)
        self._edges = keep
        self.removeItem(node)
        for edge in self._edges:
            edge.refresh()
        # 删除中间节点可能切断合法的下游链路（例如 scan→data→model）。
        # 重新修复一次，让剩余节点回到可运行拓扑，而不是留下“未连接但无报错”的状态。
        if not self._restoring:
            self._repair_workflow_edges()
        self.nodeRemoved.emit(node.node_id)
        self.topologyChanged.emit()
        self._emit_layout()
        return True

    def remove_selected(self) -> int:
        """删除选中的非 source 节点（数据源节点是依赖图根，不允许删除）。"""
        removed = [n for n in self._nodes.values() if n.isSelected() and not n.is_source]
        for node in removed:
            self.remove_node(node.node_id)
        return len(removed)

    # ---- 连线 -----------------------------------------------------------

    def connect_edge(self, source_id: str, target_id: str, kind: str = "data") -> EdgeItem | None:
        source, target = self.node(source_id), self.node(target_id)
        if source is None or target is None or source is target:
            return None
        for edge in self._edges:  # 去重
            if edge.source is source and edge.target is target:
                if edge.edge_kind != str(kind):
                    edge.edge_kind = str(kind)
                    edge.refresh()
                self.refresh_attached_edges(source, target)
                return edge
        edge = EdgeItem(source, target, kind)
        self.addItem(edge)
        self._edges.append(edge)
        self.refresh_attached_edges(source, target)
        self.topologyChanged.emit()
        return edge

    def refresh_attached_edges(self, *nodes) -> None:
        """同一节点上的多条连线按目标上下顺序重新摊开端口。"""
        if self._refreshing_edges:
            return
        self._refreshing_edges = True
        try:
            touched = {node for node in nodes if node is not None}
            if not touched:
                return
            for edge in self._edges:
                if edge.source in touched or edge.target in touched:
                    edge.refresh()
        finally:
            self._refreshing_edges = False

    def edges(self) -> tuple[EdgeItem, ...]:
        return tuple(self._edges)

    def downstream_of(self, source_id: str) -> tuple[CanvasNode, ...]:
        source = self.node(source_id)
        if source is None:
            return ()
        return tuple(edge.target for edge in self._edges if edge.source is source)

    # ---- 脏传播 -----------------------------------------------------------

    def mark_downstream_stale(self, source_id: str, reason: str, scope: int | None = None) -> int:
        """source 变更 → 按 invalidation_map 过滤后给下游节点标「!」。

        scope=None 表示未分级（全量标脏）；受影响节点进入 stale 态，
        实时模式节点自动触发防抖刷新。返回标脏的节点数。
        """
        count = 0
        for target in self.downstream_of(source_id):
            if scope is not None and not node_affected(target.spec.analyses, scope):
                continue  # 该 scope 不影响此节点声明的分析（§6.3）
            if hasattr(target, "apply_source_change"):
                target.apply_source_change(reason)
                count += 1
        return count

    # ---- 快照 -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        nodes = []
        for node in self._nodes.values():
            entry = {
                "id": node.node_id,
                "key": node.spec.key,
                "x": round(node.pos().x(), 1),
                "y": round(node.pos().y(), 1),
                "w": round(node._full_w, 1),
                "h": round(node._full_h, 1),
                "expanded": not node.is_collapsed(),
            }
            config = getattr(node, "config", None)
            if isinstance(config, dict):
                entry["config"] = dict(config)
            nodes.append(entry)
        return {
            "version": SNAPSHOT_VERSION,
            "nodes": nodes,
            "edges": [
                [edge.source.node_id, edge.target.node_id, edge.edge_kind]
                for edge in self._edges
            ],
        }

    def restore(self, snap: dict[str, Any] | None) -> bool:
        if not isinstance(snap, dict):
            return False
        entries = snap.get("nodes")
        if not isinstance(entries, list):
            return False
        # 全量重建：先清空再按快照落节点；恢复期间不自动建边（按快照边重建）
        for node_id in list(self._nodes):
            self.remove_node(node_id)
        self._restoring = True
        try:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("key", ""))
                size = entry.get("size") or (entry.get("w"), entry.get("h"))
                if not (isinstance(size, (list, tuple)) and len(size) == 2):
                    size = None
                # v1 的这些 key 曾保存整页 PanelNode 的超大尺寸。恢复为原生节点时
                # 必须使用新 spec 默认尺寸，否则虽然页面已移除，仍会留下巨型空卡片。
                if key in _LEGACY_PANEL_KEYS:
                    size = None
                restored = self.add_node(
                    key,
                    QPointF(float(entry.get("x", 0.0)), float(entry.get("y", 0.0))),
                    expanded=bool(entry.get("expanded", False)),
                    size=(float(size[0]), float(size[1])) if size else None,
                    node_id=str(entry.get("id", "")),
                )
                config = entry.get("config")
                if restored is not None and isinstance(config, dict):
                    restore_config = getattr(restored, "restore_config", None)
                    if callable(restore_config):
                        restore_config(config)
        finally:
            self._restoring = False
        for edge_entry in snap.get("edges", []) or []:
            if isinstance(edge_entry, (list, tuple)) and len(edge_entry) in (2, 3):
                kind = str(edge_entry[2]) if len(edge_entry) == 3 else "data"
                self.connect_edge(str(edge_entry[0]), str(edge_entry[1]), kind)
        self._repair_workflow_edges()
        self.topologyChanged.emit()
        return True

    # ---- 内部 -----------------------------------------------------------

    def _wire_node(self, node: CanvasNode) -> None:
        node.refreshRequested.connect(self.refreshRequested)
        node.moved.connect(self._emit_layout)
        node.expandChanged.connect(lambda *_: self._emit_layout())
        # × 关闭：非 source 节点直接移除（source 是依赖图根，无 × 按钮）
        node.closeRequested.connect(
            lambda *_args, nid=node.node_id: self.remove_node(nid)
        )
        if node.is_source and hasattr(node, "sourceChanged"):
            node.sourceChanged.connect(
                lambda reason, scope, nid=node.node_id: self._on_source_changed(nid, reason, scope)
            )

    def _on_source_changed(self, node_id: str, reason: str, scope: int | None = None) -> None:
        self.mark_downstream_stale(node_id, reason, scope)
        self.sourceChanged.emit(node_id, reason)

    def _preferred_source(self) -> CanvasNode | None:
        sources = [n for n in self._nodes.values() if n.is_source]
        for source in sources:
            if source.spec.key == "lens_editor":
                return source
        return sources[0] if sources else None

    def _remove_data_edge(self, source: CanvasNode, target: CanvasNode) -> None:
        """移除一条正式数据边；参数胶囊线不在 CanvasScene._edges 中。"""
        keep: list[EdgeItem] = []
        for edge in self._edges:
            if edge.source is source and edge.target is target:
                edge.dispose()
                self.removeItem(edge)
            else:
                keep.append(edge)
        self._edges = keep
        self.refresh_attached_edges(source, target)

    def _repair_workflow_edges(self, changed: CanvasNode | None = None) -> None:
        """确保镜头组→研究→数据集→模型的正式依赖线始终存在。"""
        source = self._active_source() or self._preferred_source()
        data = next(iter(self.nodes_by_key("data")), None)
        scan = next(iter(self.nodes_by_key("scan")), None)

        # 新旧快照都必须得到完整的镜头组→分析/任务拓扑；不能因为旧快照
        # 没保存边，或用户先添加了模型，再补数据集，导致流程线消失。
        for node in self.nodes():
            if node.node_kind not in ("view", "tool") or node.spec.key in _MODEL_NODE_KEYS:
                continue
            if node.spec.key in _SKIP_AUTO_EDGE_KEYS:
                continue
            if changed is not None and node is not changed and changed.node_kind in ("view", "tool"):
                continue
            if source is not None:
                self.connect_edge(source.node_id, node.node_id, "data")

        if data is not None:
            data_source = scan or source
            if data_source is not None:
                self.connect_edge(data_source.node_id, data.node_id, "workflow")
            if scan is not None and source is not None:
                self._remove_data_edge(source, data)

        for node in self.nodes():
            if node.spec.key not in _MODEL_NODE_KEYS:
                continue
            model_source = data or source
            if model_source is None:
                continue
            self.connect_edge(model_source.node_id, node.node_id, "workflow")
            if data is not None and source is not None:
                self._remove_data_edge(source, node)

        if changed is not None and changed.spec.key == "scan" and data is not None and source is not None:
            self._remove_data_edge(source, data)

    def set_hovered_node(self, node: CanvasNode | None) -> None:
        if self._hovered_node is node:
            return
        self._hovered_node = node
        self._refresh_edge_highlights()

    def _refresh_edge_highlights(self) -> None:
        for edge in self._edges:
            edge.refresh()

    def edge_highlight_for(self, edge: EdgeItem) -> str:
        selected = [item for item in self.selectedItems() if isinstance(item, CanvasNode)]
        if any(edge.source is node or edge.target is node for node in selected):
            return "selected"
        hovered = self._hovered_node
        if hovered is not None and (edge.source is hovered or edge.target is hovered):
            return "hover"
        return ""

    def _active_source(self) -> CanvasNode | None:
        """最近聚焦/选中的 source（§7.2：自动建边与落点的参照）。"""
        node = self.node(self._active_source_id) if self._active_source_id else None
        if node is not None and node.is_source:
            return node
        return None

    def _track_active_source(self) -> None:
        for item in self.selectedItems():
            if isinstance(item, CanvasNode) and item.is_source:
                self._active_source_id = item.node_id
                return

    def _lane_index(self, node: CanvasNode) -> int:
        """工作流列：0 镜头组 · 1 分析/任务 · 2 数据 · 3 模型。"""
        key = node.spec.key
        if node.node_kind == "source" or key == "lens_editor":
            return 0
        if key in _MODEL_LANE_KEYS:
            return 3
        if key in _DATA_LANE_KEYS or node.node_kind == "data":
            return 2
        return 1

    def _is_satellite(self, node: CanvasNode) -> bool:
        return node.spec.key in _SATELLITE_KEYS

    def _satellites_of(self, parent: CanvasNode) -> list[CanvasNode]:
        """贴在父节点右侧的信息卡 / 预测结果卡（边 + info_child_id / result_child_id）。"""
        found: list[CanvasNode] = []
        seen: set[str] = set()

        def _add(candidate: CanvasNode | None) -> None:
            if candidate is None or candidate.node_id in seen or not self._is_satellite(candidate):
                return
            seen.add(candidate.node_id)
            found.append(candidate)

        _add(self.node(str(getattr(parent, "info_child_id", "") or "")))
        _add(self.node(str(getattr(parent, "result_child_id", "") or "")))
        for edge in self._edges:
            if edge.source is parent:
                _add(edge.target)
        found.sort(key=lambda item: (item.pos().y(), item.node_id))
        return found

    def _members_in_lane(self, lane: int, source: CanvasNode | None = None) -> list[CanvasNode]:
        members = [
            node for node in self._nodes.values()
            if not self._is_satellite(node) and self._lane_index(node) == lane
        ]
        if lane == 0 and source is not None and source not in members:
            members.insert(0, source)
        return members

    def _lane_occupied_width(self, nodes: list[CanvasNode]) -> float:
        """列占用宽度 = 节点实际宽度，含子节点挂在右侧的伸出量。"""
        width = 0.0
        for node in nodes:
            span = float(node._w)
            satellites = self._satellites_of(node)
            if satellites:
                span += _SATELLITE_GAP + max(float(item._w) for item in satellites)
            width = max(width, span)
        return width

    def _attached_height(self, node: CanvasNode) -> float:
        """行高：父节点高度与右侧子节点叠放高度取大，避免子卡压到下一行。"""
        height = max(float(node.height), 1.0)
        satellites = self._satellites_of(node)
        if not satellites:
            return height
        stacked = 0.0
        for index, satellite in enumerate(satellites):
            stacked += max(float(satellite.height), 1.0)
            if index < len(satellites) - 1:
                stacked += _LANE_ROW_GAP
        return max(height, stacked)

    def _row_gap_after(self, node: CanvasNode) -> float:
        if node.is_collapsed():
            return _LANE_ROW_GAP
        return _LANE_ROW_GAP_EXPANDED

    def _node_stride(self, node: CanvasNode) -> float:
        return self._attached_height(node) + self._row_gap_after(node)

    def _lane_x(self, source: CanvasNode, lane: int) -> float:
        """新节点落点 X：按左侧各列实际占用宽度累加（展开的 3D/透镜组不再按 420 估宽）。"""
        x = float(source.pos().x())
        if lane <= 0:
            return x
        for index in range(lane):
            members = self._members_in_lane(index, source)
            width = self._lane_occupied_width(members)
            if width <= 0.0:
                width = _LANE_MIN_WIDTH if index > 0 else max(float(source._w), CanvasNode.COLLAPSED_W)
            x += width + (_SLOT_GAP_X if index == 0 else _LANE_GAP)
        return x

    def _free_slot(self, node: CanvasNode | None = None, *, expanded: bool = False) -> QPointF:
        """新节点落点：按工作流分列，列内 y 向步进避让。"""
        source = self._active_source() or self._preferred_source()
        if source is None:
            return QPointF(_FALLBACK_ORIGIN)
        if node is not None and expanded:
            node_w, node_h = node._full_w, node._full_h
        else:
            node_w, node_h = CanvasNode.COLLAPSED_W, CanvasNode.COLLAPSED_H
        occupied = [
            QRectF(n.pos().x(), n.pos().y(), n._w, n.height)
            for n in self._nodes.values()
        ]
        lane = self._lane_index(node) if node is not None else 1
        x0 = self._lane_x(source, lane)
        y0 = source.pos().y()
        for row in range(_SLOT_MAX_ROWS):
            y = y0 + row * _SLOT_STEP_Y
            candidate = QRectF(
                x0 - _SLOT_MARGIN,
                y - _SLOT_MARGIN,
                node_w + 2.0 * _SLOT_MARGIN,
                node_h + 2.0 * _SLOT_MARGIN,
            )
            if not any(candidate.intersects(rect) for rect in occupied):
                return QPointF(x0, y)
        return QPointF(x0, y0)

    def auto_layout(self) -> None:
        """按工作流列重排：列距用实际宽度，行距用展开高度，信息子节点跟父节点。"""
        nodes = [node for node in self._nodes.values() if not self._is_satellite(node)]
        if not nodes:
            return
        anchor = self._preferred_source() or min(
            nodes, key=lambda item: (item.pos().x(), item.pos().y())
        )
        lanes: dict[int, list[CanvasNode]] = {0: [], 1: [], 2: [], 3: []}
        for node in nodes:
            if node is anchor:
                continue
            lanes[self._lane_index(node)].append(node)
        for lane_nodes in lanes.values():
            lane_nodes.sort(key=lambda item: (item.pos().y(), item.pos().x(), item.node_id))

        origin_x = float(_FALLBACK_ORIGIN.x())
        origin_y = float(_FALLBACK_ORIGIN.y())
        x_cursor = origin_x

        lane0 = [anchor, *lanes[0]]
        y_cursor = origin_y
        for node in lane0:
            node.setPos(QPointF(x_cursor, y_cursor))
            y_cursor += self._node_stride(node)
        x_cursor += self._lane_occupied_width(lane0) + _LANE_GAP

        for lane in (1, 2, 3):
            if not lanes[lane]:
                continue
            y_cursor = origin_y
            for node in lanes[lane]:
                node.setPos(QPointF(x_cursor, y_cursor))
                y_cursor += self._node_stride(node)
            x_cursor += self._lane_occupied_width(lanes[lane]) + _LANE_GAP

        self._place_satellites()
        self.refresh_attached_edges(*self._nodes.values())
        self._emit_layout()

    def _place_satellites(self) -> None:
        placed: set[str] = set()
        for parent in list(self._nodes.values()):
            if self._is_satellite(parent):
                continue
            y_cursor = float(parent.pos().y())
            x = float(parent.pos().x()) + float(parent._w) + _SATELLITE_GAP
            for satellite in self._satellites_of(parent):
                satellite.setPos(QPointF(x, y_cursor))
                y_cursor += max(float(satellite.height), 1.0) + _LANE_ROW_GAP
                placed.add(satellite.node_id)
        for node in self._nodes.values():
            if not self._is_satellite(node) or node.node_id in placed:
                continue
            parent = self._satellite_parent(node)
            if parent is None:
                continue
            node.setPos(QPointF(
                float(parent.pos().x()) + float(parent._w) + _SATELLITE_GAP,
                float(parent.pos().y()),
            ))

    def _satellite_parent(self, satellite: CanvasNode) -> CanvasNode | None:
        for edge in self._edges:
            if edge.target is satellite:
                return edge.source
        for node in self._nodes.values():
            if getattr(node, "info_child_id", None) == satellite.node_id:
                return node
            if getattr(node, "result_child_id", None) == satellite.node_id:
                return node
        return None

    def _emit_layout(self, *_args) -> None:
        self.layoutDirty.emit()


__all__ = ["CanvasScene", "SNAPSHOT_VERSION", "default_node_factory"]
