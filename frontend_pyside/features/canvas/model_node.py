"""轻量代理模型节点及其邻接式参数胶囊。

参数胶囊是主节点的附属配置 UI，不是工作流节点：它没有数据端口、不会进入
CanvasScene 的普通拓扑，也不会把完整机器学习页面嵌入画布。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QGraphicsObject,
    QGraphicsPathItem,
    QSpinBox,
    QVBoxLayout,
)

from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.parameter_catalog import MAX_FEATURE_CHOICES
from frontend_pyside.features.canvas.theme import C
from frontend_pyside.shared.qt_zh import localize_dialog_buttons


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


@dataclass(frozen=True, slots=True)
class ModelField:
    key: str
    label: str
    kind: str = "text"
    default: Any = ""
    minimum: float = 0.0
    maximum: float = 100000.0
    decimals: int = 4
    suffix: str = ""
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    key: str
    title: str
    groups: tuple[tuple[str, str, tuple[ModelField, ...]], ...]
    backend_kind: str


MODEL_DEFINITIONS: dict[str, ModelDefinition] = {
    "random_forest": ModelDefinition(
        "random_forest",
        "随机森林",
        (
            ("data", "数据与目标", (ModelField("dataset_id", "数据集 ID"), ModelField("target_name", "目标列", default="coupling_efficiency"))),
            ("forest", "森林规模", (ModelField("n_estimators", "树数量", "int", 300, 1, 10000), ModelField("max_depth", "最大深度", "int", 0, 0, 256))),
            ("sampling", "采样与特征", (ModelField("max_features", "最大特征比例", "choice", "sqrt", choices=MAX_FEATURE_CHOICES), ModelField("min_samples_leaf", "叶节点最小样本", "int", 1, 1, 100))),
            ("validation", "验证与随机种子", (ModelField("seed", "随机种子", "int", 42, 0, 2147483647),)),
            ("advanced", "高级设置", (ModelField("n_jobs", "并行任务数", "int", 1, 1, 64),)),
        ),
        "random_forest",
    ),
    "xgboost_physics_residual": ModelDefinition(
        "xgboost_physics_residual",
        "XGBoost物理残差",
        (
            ("data", "数据与目标", (ModelField("dataset_id", "数据集 ID"), ModelField("target_name", "目标列", default="coupling_loss_db"))),
            ("booster", "提升器参数", (ModelField("n_estimators", "迭代轮数", "int", 300, 10, 10000), ModelField("learning_rate", "学习率", "float", 0.05, 0.000001, 1.0, 6))),
            ("tree", "树结构", (ModelField("max_depth", "最大深度", "int", 4, 1, 32), ModelField("min_child_weight", "子节点权重", "float", 2.0, 0.0, 10000.0))),
            ("regularization", "正则化", (ModelField("subsample", "样本采样率", "float", 0.9, 0.01, 1.0, 3), ModelField("colsample_bytree", "特征采样率", "float", 0.95, 0.01, 1.0, 3))),
            ("training", "训练与早停", (ModelField("early_stopping", "启用早停", "bool", True), ModelField("patience", "耐心轮数", "int", 20, 2, 500), ModelField("seed", "随机种子", "int", 42, 0, 2147483647))),
        ),
        "xgboost_physics_residual",
    ),
    "bilstm_structure_sequence": ModelDefinition(
        "bilstm_structure_sequence",
        "BiLSTM",
        (
            ("sequence", "序列与字段", (ModelField("dataset_path", "数据集路径"), ModelField("numeric_feature_columns", "数值特征列", default="radius_mm,thickness_mm"), ModelField("target_columns", "目标列", default="coupling_efficiency"))),
            ("network", "网络结构", (ModelField("embedding_dim", "嵌入维度", "int", 16, 2, 256), ModelField("hidden_dim", "隐藏维度", "int", 64, 8, 512), ModelField("num_layers", "层数", "int", 2, 1, 6), ModelField("dropout", "Dropout", "float", 0.15, 0.0, 0.99, 3))),
            ("optimizer", "优化器", (ModelField("learning_rate", "学习率", "float", 0.001, 0.000001, 1.0, 6), ModelField("weight_decay", "权重衰减", "float", 0.0001, 0.0, 1.0, 6))),
            ("training", "训练控制", (ModelField("batch_size", "批大小", "int", 32, 1, 1024), ModelField("max_epochs", "最大轮数", "int", 200, 1, 5000), ModelField("patience", "早停耐心", "int", 20, 1, 500))),
            ("output", "验证与输出", (ModelField("system_id_column", "系统 ID 列", default="system_id"), ModelField("order_column", "顺序列", default="element_index"), ModelField("element_type_column", "元件类型列", default="element_type"), ModelField("random_seed", "随机种子", "int", 42, 0, 2147483647))),
        ),
        "bilstm_structure_sequence",
    ),
}


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Parse checkbox values; a non-empty string like ``"False"`` is not True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and value != 0
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "是", "开启"}:
        return True
    if text in {"", "0", "false", "no", "off", "否", "关闭"}:
        return False
    return bool(default)


class ParameterCapsule(QGraphicsObject):
    """主节点左侧的一类参数入口。"""

    clicked = Signal(str)
    WIDTH = 168.0
    HEIGHT = 36.0

    def __init__(self, group_key: str, title: str, summary: str, parent=None):
        super().__init__(parent)
        self.group_key = str(group_key)
        self.title = str(title)
        self.summary = str(summary)
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self.setZValue(3.0)

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self.WIDTH, self.HEIGHT)

    def set_summary(self, summary: str) -> None:
        self.summary = str(summary)
        self.update()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(C["node_border_focus"] if self._hovered else C["node_border"]), 1.2))
        painter.setBrush(QColor(C["node_fill"] if self._hovered else C["rail_bg"]))
        painter.drawRoundedRect(self.boundingRect(), 8.0, 8.0)
        painter.setPen(QColor(C["text"]))
        painter.setFont(_font(12, True))
        painter.drawText(QRectF(10.0, 3.0, self.WIDTH - 20.0, 16.0), Qt.AlignmentFlag.AlignLeft, self.title)
        painter.setPen(QColor(C["text_muted"]))
        painter.setFont(_font(10))
        painter.drawText(QRectF(10.0, 18.0, self.WIDTH - 20.0, 14.0), Qt.AlignmentFlag.AlignLeft, self.summary[:28])

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.group_key)
            event.accept()
            return
        super().mousePressEvent(event)


class ParameterEdge(QGraphicsPathItem):
    """参数胶囊到主节点的从属关系线，不参与 CanvasScene 数据拓扑。"""

    def __init__(self, owner, capsule: ParameterCapsule, direction: int = -1, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.capsule = capsule
        self.direction = -1 if direction < 0 else 1
        self.setZValue(2.0)
        owner.moved.connect(self.refresh)
        capsule.clicked.connect(lambda _key: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        if self.direction < 0:
            start = QPointF(self.capsule.pos().x() + self.capsule.WIDTH, self.capsule.pos().y() + self.capsule.HEIGHT / 2.0)
            end = QPointF(2.0, self.owner.HEADER_H / 2.0)
        else:
            start = QPointF(self.capsule.pos().x(), self.capsule.pos().y() + self.capsule.HEIGHT / 2.0)
            end = QPointF(self.owner._w - 2.0, self.owner.HEADER_H / 2.0)
        path = QPainterPath(start)
        dx = max(18.0, abs(end.x() - start.x()) * 0.25)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        self.setPath(path)
        pen = QPen(QColor(C["edge_stale"]), 1.25, Qt.PenStyle.DashLine)
        pen.setDashPattern([4.0, 3.0])
        self.setPen(pen)


class ModelNode(CanvasNode):
    """代理模型配置节点：主体摘要 + 真实任务状态 + 分类参数胶囊。"""

    taskRunRequested = Signal(str)
    configurationChanged = Signal(str)

    def __init__(self, node_id: str, spec, model_type: str, context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self.context = context
        self.model_type = str(model_type)
        self.definition = MODEL_DEFINITIONS[self.model_type]
        self.task_kind = self.definition.backend_kind
        self._config = self._default_config()
        self._phase = "idle"
        self._progress = 0.0
        self._stage = ""
        self._job_id = ""
        self._note = ""
        self._result_rows: list[tuple[str, str]] = []
        self._capsules: list[ParameterCapsule] = []
        self._parameter_edges: list[ParameterEdge] = []
        self._parameters_open = False
        self._chrome_settings = True
        self._chrome_run = True
        self.settingsRequested.connect(self.toggle_parameter_capsules)
        self.runRequested.connect(self.run_task)
        self._bind_registry()

    def _bind_registry(self) -> None:
        registry = getattr(self.context, "registry", None)
        if registry is None:
            return
        registry.datasets_changed.connect(self._on_datasets_changed)
        registry.current_dataset_changed.connect(self._on_current_dataset_changed)
        current = str(getattr(registry, "current_dataset_id", "") or "")
        if current:
            if self.model_type in {"random_forest", "xgboost_physics_residual"} and not str(self._config.get("dataset_id", "") or ""):
                self._config["dataset_id"] = current
            elif self.model_type == "bilstm_structure_sequence" and not str(self._config.get("dataset_path", "") or ""):
                self._config["dataset_path"] = self._dataset_path(registry.dataset(current))
        self._request_dataset_list()

    def _request_dataset_list(self) -> None:
        services = getattr(self.context, "services", None)
        api = getattr(self.context, "api_client", None)
        client = getattr(services, "dataset", None)
        registry = getattr(self.context, "registry", None)
        if api is None or client is None or registry is None or getattr(registry, "datasets", None):
            return
        self._dataset_list_key = f"canvas.model.datasets.list.{id(self)}"
        api.completed.connect(self._on_api_completed)
        client.list_datasets(self._dataset_list_key)

    def _on_api_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_dataset_list_key", ""):
            return
        records = data.get("items", data.get("datasets", data)) if isinstance(data, dict) else data
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.set_datasets([item for item in (records or []) if isinstance(item, dict)])

    def _on_datasets_changed(self, _records: list) -> None:
        if self._parameters_open:
            self._layout_parameter_capsules()
        self.update()

    def _on_current_dataset_changed(self, dataset_id: str) -> None:
        if self.model_type in {"random_forest", "xgboost_physics_residual"} and str(dataset_id or ""):
            self._config["dataset_id"] = str(dataset_id)
            self.set_stale(True, "当前数据集已切换，请确认模型参数")
            if self._parameters_open:
                self._layout_parameter_capsules()
            self.update()
        elif self.model_type == "bilstm_structure_sequence" and str(dataset_id or ""):
            registry = getattr(self.context, "registry", None)
            path = self._dataset_path(registry.dataset(str(dataset_id))) if registry is not None else ""
            if path:
                self._config["dataset_path"] = path
                self.set_stale(True, "当前数据集已切换，请确认序列字段")
                if self._parameters_open:
                    self._layout_parameter_capsules()
                self.update()

    @staticmethod
    def _dataset_path(record: dict | None) -> str:
        if not isinstance(record, dict):
            return ""
        # 结构模型优先使用训练切分后的扁平 CSV；旧版数据集服务和导入
        # 数据集可能只提供 samples_flat_csv_path，因此按顺序兼容两种清单。
        for key in (
            "training_samples_flat_csv_path",
            "samples_flat_csv_path",
            "dataset_path",
            "training_manifest_path",
            "manifest_path",
        ):
            value = str(record.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _default_config(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for _key, _title, fields in self.definition.groups:
            for field in fields:
                values[field.key] = field.default
        return values

    def restore_config(self, config: dict[str, Any]) -> None:
        """从画布快照恢复参数，不触发任务、不伪造结果。"""
        allowed = {field.key for _key, _title, fields in self.definition.groups for field in fields}
        self._config.update({key: value for key, value in config.items() if key in allowed})

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def job_id(self) -> str:
        return self._job_id

    def expanded_size(self) -> tuple[float, float]:
        return self._full_w, self._full_h

    def _on_resize(self) -> None:
        self._layout_parameter_capsules()

    def _on_expand_state(self) -> None:
        # 模型节点不再通过 NodeHost 嵌入完整页面。
        self._layout_parameter_capsules()

    def toggle_parameter_capsules(self) -> None:
        if self._parameters_open:
            self._clear_parameter_capsules()
            return
        self._parameters_open = True
        self._layout_parameter_capsules()

    def _clear_parameter_capsules(self) -> None:
        for edge in self._parameter_edges:
            scene = edge.scene()
            if scene is not None:
                scene.removeItem(edge)
            edge.setParentItem(None)
        for capsule in self._capsules:
            scene = capsule.scene()
            if scene is not None:
                scene.removeItem(capsule)
            capsule.setParentItem(None)
        self._parameter_edges.clear()
        self._capsules.clear()
        self._parameters_open = False
        self.update()

    def _layout_parameter_capsules(self) -> None:
        if not self._parameters_open:
            return
        self._clear_parameter_capsules()
        self._parameters_open = True
        direction = self._parameter_direction()
        for index, (group_key, title, fields) in enumerate(self.definition.groups):
            values = []
            for field in fields[:2]:
                raw = self._config.get(field.key, field.default)
                if field.kind == "bool":
                    values.append("开" if coerce_bool(raw, bool(field.default)) else "关")
                else:
                    values.append(str(raw))
            summary = " · ".join(values) if values else "可配置"
            capsule = ParameterCapsule(group_key, title, summary, self)
            x = -ParameterCapsule.WIDTH - 24.0 if direction < 0 else self._w + 24.0
            capsule.setPos(x, 34.0 + index * (ParameterCapsule.HEIGHT + 7.0))
            capsule.clicked.connect(self._edit_group)
            edge = ParameterEdge(self, capsule, direction, self)
            self._capsules.append(capsule)
            self._parameter_edges.append(edge)
        self.update()

    def _parameter_direction(self) -> int:
        """靠左的节点向右展开，避免胶囊画进左栏；否则默认向左，冲突时改向右。"""
        if float(self.pos().x()) < ParameterCapsule.WIDTH + 48.0:
            return 1
        scene = self.scene()
        if scene is None:
            return -1
        top = self.pos().y() + 28.0
        left = QRectF(
            self.pos().x() - ParameterCapsule.WIDTH - 24.0,
            top,
            ParameterCapsule.WIDTH,
            len(self.definition.groups) * (ParameterCapsule.HEIGHT + 7.0),
        )
        for item in scene.items(left):
            if item is self or item in self._capsules or item in self._parameter_edges:
                continue
            if hasattr(item, "spec"):
                return 1
        return -1

    def _edit_group(self, group_key: str) -> None:
        group = next((item for item in self.definition.groups if item[0] == group_key), None)
        if group is None:
            return
        _key, title, fields = group
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        dialog = QDialog(view.window() if view is not None else None)
        dialog.setSizeGripEnabled(True)
        dialog.setWindowTitle(f"{self.definition.title} · {title}")
        dialog.setMinimumWidth(360)
        dialog.setStyleSheet(
            "QDialog { background:#F7F8FA; } "
            "QLabel, QCheckBox { color:#0F172A; } "
            "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:#FFFFFF; padding:3px 6px; }"
        )
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        editors: dict[str, Any] = {}
        for field in fields:
            current = self._config.get(field.key, field.default)
            if field.key in {"dataset_id", "dataset_path"} and self.model_type == "bilstm_structure_sequence":
                editor = QComboBox(dialog)
                editor.addItem("未选择数据集（请先生成或刷新）", "")
                registry = getattr(self.context, "registry", None)
                records = list(getattr(registry, "datasets", []) or []) if registry is not None else []
                for record in records:
                    dataset_id = str(record.get("dataset_id", record.get("id", "")) or "")
                    path = self._dataset_path(record)
                    if not path:
                        continue
                    name = str(record.get("dataset_name", record.get("name", dataset_id)) or dataset_id)
                    editor.addItem(name or dataset_id or path, path)
                current_index = editor.findData(str(current or ""))
                editor.setCurrentIndex(current_index if current_index >= 0 else 0)
            elif field.key == "dataset_id":
                editor = QComboBox(dialog)
                editor.addItem("暂无数据集（请先生成或刷新）", "")
                registry = getattr(self.context, "registry", None)
                records = list(getattr(registry, "datasets", []) or []) if registry is not None else []
                for record in records:
                    dataset_id = str(record.get("dataset_id", record.get("id", "")) or "")
                    if not dataset_id:
                        continue
                    name = str(record.get("dataset_name", record.get("name", dataset_id)) or dataset_id)
                    sample_count = record.get("sample_count")
                    suffix = f" · {int(sample_count)} 条" if isinstance(sample_count, (int, float)) else ""
                    editor.addItem(f"{name}{suffix}", dataset_id)
                current_index = editor.findData(str(current or ""))
                editor.setCurrentIndex(current_index if current_index >= 0 else 0)
            elif field.key == "target_name" and self.model_type in {"random_forest", "xgboost_physics_residual"}:
                editor = QComboBox(dialog)
                target_choices = [
                    "coupling_efficiency", "coupling_loss_db", "rms_spot_radius_um", "strehl_estimate_marechal",
                ]
                registry = getattr(self.context, "registry", None)
                selected_id = str(self._config.get("dataset_id", "") or "")
                record = registry.dataset(selected_id) if registry is not None and selected_id else None
                if isinstance(record, dict):
                    target_choices = [
                        str(item) for item in (record.get("target_names") or []) if str(item)
                    ] or ([str(record.get("target_column"))] if record.get("target_column") else target_choices)
                if str(current or "") not in target_choices:
                    target_choices.insert(0, str(current or ""))
                editor.addItems(list(dict.fromkeys(target_choices)))
                editor.setCurrentText(str(current or ""))
            elif field.kind == "choice":
                editor = QComboBox(dialog)
                editor.addItems(list(field.choices))
                editor.setCurrentText(str(current))
            elif field.kind == "int":
                editor = QSpinBox(dialog)
                editor.setRange(int(field.minimum), int(field.maximum))
                editor.setValue(int(current or 0))
            elif field.kind == "float":
                editor = QDoubleSpinBox(dialog)
                editor.setRange(float(field.minimum), float(field.maximum))
                editor.setDecimals(field.decimals)
                editor.setValue(float(current or 0.0))
                if field.suffix:
                    editor.setSuffix(field.suffix)
            elif field.kind == "bool":
                editor = QCheckBox("启用", dialog)
                editor.setChecked(coerce_bool(current, bool(field.default)))
            else:
                editor = QLineEdit(str(current or ""), dialog)
            editors[field.key] = editor
            form.addRow(QLabel(field.label, dialog), editor)
        layout.addLayout(form)
        buttons = localize_dialog_buttons(
            QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                parent=dialog,
            )
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for field in fields:
            editor = editors[field.key]
            if field.key in {"dataset_id", "dataset_path"} and isinstance(editor, QComboBox):
                value = str(editor.currentData() or "")
            elif field.kind == "choice" or field.key == "target_name":
                value = editor.currentText()
            elif field.kind == "int":
                value = int(editor.value())
            elif field.kind == "float":
                value = float(editor.value())
            elif field.kind == "bool":
                value = bool(editor.isChecked())
            else:
                value = editor.text().strip()
            self._config[field.key] = value
        self.set_stale(True, f"{title}参数已修改")
        self.configurationChanged.emit(group_key)
        self._layout_parameter_capsules()
        self.update()

    def run_task(self) -> None:
        if self._phase in {"submitting", "running"}:
            return
        if self.model_type in {"random_forest", "xgboost_physics_residual"} and not str(self._config.get("dataset_id", "") or ""):
            self.set_task_failed("尚未选择数据集。请先在数据管理节点点 ▶ 生成。")
            return
        if self.model_type == "bilstm_structure_sequence" and not str(self._config.get("dataset_path", "") or ""):
            self.set_task_failed("尚未选择数据集路径。请先在数据管理节点点 ▶ 生成。")
            return
        self.taskRunRequested.emit(self.node_id)

    def set_submitting(self) -> None:
        self._phase, self._progress, self._stage, self._note = "submitting", 0.0, "提交任务…", ""
        self.update()

    def set_job(self, job_id: str) -> None:
        self._job_id, self._phase, self._stage = str(job_id or ""), "running", "排队中"
        self.update()

    def set_progress(self, progress: float, stage: str) -> None:
        if self._phase != "running":
            return
        self._progress = max(0.0, min(1.0, float(progress or 0.0)))
        self._stage = str(stage or self._stage)
        self.update()

    def set_task_result(self, result: dict) -> None:
        status = str((result or {}).get("status", "completed") or "completed")
        if status != "completed":
            self.set_task_failed(f"任务{status}")
            return
        self._phase, self._progress, self._job_id = "done", 1.0, ""
        val = (result or {}).get("validation_metrics") or {}
        test = (result or {}).get("test_metrics") or {}
        self._result_rows = [("验证 R²", f"{float(val['r2']):.4f}") for _ in [0] if isinstance(val, dict) and isinstance(val.get("r2"), (int, float))]
        if isinstance(test, dict) and isinstance(test.get("r2"), (int, float)):
            self._result_rows.append(("测试 R²", f"{float(test['r2']):.4f}"))
        if not self._result_rows:
            self._result_rows = [("状态", "训练完成")]
        model_id = str((result or {}).get("model_id", "") or "")
        registry = getattr(self.context, "registry", None)
        if model_id and registry is not None:
            registry.merge_model({
                **dict(result or {}),
                "model_id": model_id,
                "model_type": self.model_type,
                "name": str((result or {}).get("name", "") or self.definition.title),
                "dataset_id": str(self._config.get("dataset_id", "") or ""),
            })
            registry.set_current_model(model_id)
        self.set_stale(False)
        self.update()

    def set_task_failed(self, message: str) -> None:
        self._phase, self._job_id, self._note = "failed", "", str(message or "任务失败")
        self.update()

    def apply_source_change(self, reason: str) -> None:
        if self._phase not in {"submitting", "running"}:
            self.set_stale(True, reason)

    def summary_text(self) -> str:
        if self._phase == "running":
            return f"{self._stage or '训练中'} {self._progress:.0%}"
        if self._phase == "failed":
            return self._note[:22] or "失败"
        if self._phase == "done":
            return "训练完成"
        dataset = self._config.get("dataset_id") or self._config.get("dataset_path")
        if not dataset:
            return "请先生成数据集"
        return "参数待配置"

    def _paint_content(self, painter: QPainter, rect: QRectF) -> None:
        painter.setClipRect(rect)
        painter.setPen(QColor(C["text"]))
        painter.setFont(_font(11, True))
        painter.drawText(QRectF(rect.left(), rect.top(), rect.width(), 18.0), Qt.AlignmentFlag.AlignLeft, self.definition.title)
        painter.setFont(_font(10))
        painter.setPen(QColor(C["text_muted"]))
        dataset = self._config.get("dataset_id") or self._config.get("dataset_path") or "未选择"
        target = self._config.get("target_name") or self._config.get("target_columns") or "未设置"
        painter.drawText(QRectF(rect.left(), rect.top() + 22.0, rect.width(), 17.0), Qt.AlignmentFlag.AlignLeft, f"数据：{str(dataset)[:28]}")
        painter.drawText(QRectF(rect.left(), rect.top() + 40.0, rect.width(), 17.0), Qt.AlignmentFlag.AlignLeft, f"目标：{str(target)[:28]}")
        if (not dataset or dataset == "未选择") and self._phase == "idle":
            painter.setPen(QColor(C["text"]))
            painter.setFont(_font(10, True))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 62.0, rect.width(), 36.0),
                Qt.TextFlag.TextWordWrap,
                "数据集生成后会自动填入。点右上角 ▶ 训练，完成后去正向预测。",
            )
        elif self._phase in {"submitting", "running"}:
            bar = QRectF(rect.left(), rect.top() + 66.0, rect.width(), 8.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C["grid_dot"]))
            painter.drawRoundedRect(bar, 4.0, 4.0)
            painter.setBrush(QColor(C["badge"]))
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * self._progress, bar.height()), 4.0, 4.0)
            painter.setPen(QColor(C["text"]))
            painter.setFont(_font(10, True))
            painter.drawText(QRectF(rect.left(), bar.bottom() + 5.0, rect.width(), 16.0), Qt.AlignmentFlag.AlignLeft, f"{self._stage or '训练中'} {self._progress:.0%}")
        elif self._result_rows:
            painter.setFont(_font(10))
            y = rect.top() + 68.0
            for label, value in self._result_rows[:3]:
                painter.setPen(QColor(C["text_muted"]))
                painter.drawText(QRectF(rect.left(), y, rect.width() * 0.5, 16.0), Qt.AlignmentFlag.AlignLeft, label)
                painter.setPen(QColor(C["text"]))
                painter.drawText(QRectF(rect.left() + rect.width() * 0.5, y, rect.width() * 0.5, 16.0), Qt.AlignmentFlag.AlignRight, value)
                y += 17.0
        elif self._note:
            painter.setPen(QColor("#B00020"))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 62.0, rect.width(), max(36.0, rect.height() - 70.0)),
                Qt.TextFlag.TextWordWrap,
                self._note,
            )
        else:
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(QRectF(rect.left(), rect.top() + 68.0, rect.width(), 32.0), Qt.AlignmentFlag.AlignLeft, "点击齿轮按分类设置参数")
        painter.setClipping(False)


__all__ = ["MODEL_DEFINITIONS", "ModelDefinition", "ModelField", "ModelNode", "ParameterCapsule", "ParameterEdge", "coerce_bool"]
