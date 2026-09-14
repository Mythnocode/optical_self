"""正向预测节点：把“模型选择”做成画布内可见的真实交互，而不是藏在右键菜单里。

- 展开后嵌入 ForwardPredictionPanel（QComboBox 选模型 + 预测输入上下文 + 开始预测）；
- 模型下拉实时读取 context.registry.models（模型管理节点登记的训练结果）；
 - 「开始预测」直接在节点内调用代理模型，完成后由画布创建结果子节点；
- 折叠态不显示嵌入面板，只保留节点标题/摘要。
"""

from __future__ import annotations

from typing import Any

from uuid import uuid4

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.machine_learning.feature_adapter import (
    FeaturePathError,
    features_from_project,
)
from frontend_pyside.infrastructure.api.clients import TrainingClient
from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.node_host import NodeHost
from frontend_pyside.features.canvas.prediction_compare import build_forward_compare


def _model_records(context) -> list[dict[str, Any]]:
    registry = getattr(context, "registry", None) if context is not None else None
    records = list(getattr(registry, "models", []) or []) if registry is not None else []
    return [r for r in records if isinstance(r, dict)]


def _model_id(record: dict[str, Any]) -> str:
    return str(record.get("model_id", record.get("id", "")) or "")


def _model_name(record: dict[str, Any]) -> str:
    model_id = _model_id(record)
    return str(
        record.get("name") or record.get("model_name") or model_id or "未命名模型"
    )


class ForwardPredictionPanel(QWidget):
    """正向预测表单：模型下拉 + 预测上下文 + 开始预测。"""

    predictionCompleted = Signal(dict)
    setupRequested = Signal()

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self._prediction_token = ""
        self._prediction_result: dict[str, Any] = {}
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.model_combo = QComboBox(self)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.model_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.model_combo.setMinimumContentsLength(8)
        self.model_combo.view().setTextElideMode(Qt.TextElideMode.ElideRight)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        form.addRow("预测模型", self.model_combo)
        root.addLayout(form)

        self.context_label = QLabel(self)
        self.context_label.setWordWrap(True)
        self.context_label.setStyleSheet("color: #57606A; font-size: 12px;")
        root.addWidget(self.context_label)

        button_row = QHBoxLayout()
        self.predict_btn = QPushButton("开始预测", self)
        self.predict_btn.clicked.connect(self._predict)
        self.refresh_btn = QPushButton("刷新模型", self)
        self.refresh_btn.clicked.connect(self.reload_models)
        self.setup_btn = QPushButton("准备数据闭环", self)
        self.setup_btn.setToolTip("在画布上排出 数据管理 → 模型 → 正向预测，并提示每一步要点哪里")
        self.setup_btn.clicked.connect(self.setupRequested.emit)
        for button in (self.predict_btn, self.refresh_btn, self.setup_btn):
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        button_row.addWidget(self.predict_btn, 1)
        button_row.addWidget(self.refresh_btn, 0)
        root.addLayout(button_row)
        root.addWidget(self.setup_btn)

        self.status = QLabel("请选择已训练模型后开始预测", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #71767E; font-size: 12px;")
        root.addWidget(self.status)
        root.addStretch(1)

        api = getattr(self.context, "api_client", None)
        if api is not None:
            api.completed.connect(self._on_prediction_completed)
            api.failed.connect(self._on_prediction_failed)

        self.reload_models()
        self._refresh_context()

    # ---- 数据 -----------------------------------------------------------

    def reload_models(self) -> None:
        """从注册表重建模型下拉，保留当前选择。"""
        previous = str(self.model_combo.currentData() or "")
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        records = _model_records(self.context)
        for record in records:
            model_id = _model_id(record)
            if not model_id:
                continue
            model_type = str(record.get("model_type") or "")
            label = _model_name(record)
            if model_type:
                label = f"{label} · {model_type}"
            self.model_combo.addItem(label, model_id)
        self.model_combo.blockSignals(False)
        if not records:
            self.model_combo.addItem("（暂无已训练模型）", "")
            self.model_combo.setEnabled(False)
            self.predict_btn.setEnabled(False)
            self.setup_btn.setVisible(True)
            self.status.setText("尚未训练任何模型。点「准备数据闭环」排出采样 → 训练 → 预测。")
        else:
            self.model_combo.setEnabled(True)
            self.predict_btn.setEnabled(True)
            self.setup_btn.setVisible(False)
            idx = self.model_combo.findData(previous)
            self.model_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.status.setText(f"已加载 {len(records)} 个模型。")

    def _refresh_context(self) -> None:
        """展示预测所消费的镜头/系统上下文（只读信息，预测使用实时镜头组参数）。"""
        project = getattr(getattr(self.context, "project", None), "project", None)
        if project is None:
            self.context_label.setText("预测使用当前镜头组参数：未检测到镜头组。")
            return
        surfaces = getattr(project, "surfaces", []) or []
        lines = [
            f"镜头组参数 · 表面 {len(surfaces)} 面",
            f"入瞳半径 {getattr(project, 'pupil_radius_mm', 0.0):g} mm · "
            f"波长 {getattr(project, 'wavelength_nm', 0.0):g} nm",
        ]
        self.context_label.setText("\n".join(lines))

    def _on_model_changed(self) -> None:
        self.status.setText(f"当前采用：{self.model_combo.currentText()}")

    # ---- 预测 -----------------------------------------------------------

    def _predict(self) -> None:
        model_id = str(self.model_combo.currentData() or "")
        if not model_id:
            self.status.setText("请先选择一个已训练模型。")
            return
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            setter = getattr(registry, "set_current_model", None)
            if callable(setter):
                setter(model_id)
        if self._prediction_token:
            self.status.setText("已有预测正在执行，请等待当前结果。")
            return
        project_context = getattr(self.context, "project", None)
        registry = getattr(self.context, "registry", None)
        api = getattr(self.context, "api_client", None)
        record = registry.model(model_id) if registry is not None else None
        if not isinstance(record, dict):
            self.status.setText("当前模型不在已训练模型列表中，请刷新模型。")
            return
        if api is None or project_context is None:
            self.status.setText("预测服务或当前镜头组尚未准备好。")
            return
        try:
            shared = getattr(project_context, "simulation_project_payload", {})
            project_payload = (
                dict(shared)
                if isinstance(shared, dict) and shared.get("surfaces")
                else serialize_project(project_context.project)
            )
            features = features_from_project(
                project_payload,
                list(record.get("feature_paths", []) or []),
            )
        except FeaturePathError as exc:
            self.status.setText(f"当前项目无法构造模型特征：{exc}")
            return
        except Exception as exc:
            self.status.setText(f"读取镜头组参数失败：{exc}")
            return

        self._prediction_token = uuid4().hex[:12]
        self._prediction_result = {
            "model_id": model_id,
            "model_name": record.get("name") or record.get("model_name") or model_id,
            "feature_count": len(features),
            "features": dict(features),
        }
        self.predict_btn.setEnabled(False)
        self.status.setText(f"正在预测 · {len(features)} 项输入…")
        key = f"canvas.forward.predict.{self._prediction_token}.{model_id}"
        TrainingClient(api).predict(key, model_id, features)

    def _on_prediction_completed(self, key: str, data: object) -> None:
        prefix = f"canvas.forward.predict.{self._prediction_token}."
        if not self._prediction_token or not str(key).startswith(prefix):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        predictions = dict(body.get("predictions", {}) or {})
        self.predict_btn.setEnabled(True)
        self._prediction_token = ""
        if not predictions:
            self.status.setText("预测完成，但后端未返回预测值。")
            return
        self._prediction_result.update({"predictions": predictions, "response": body})
        compared = build_forward_compare(
            dict(self._prediction_result),
            features=dict(self._prediction_result.get("features") or {}),
            context=self.context,
        )
        self._prediction_result = compared
        self.status.setText("预测完成，结果卡已对比当前透镜与正式基线。")
        self.predictionCompleted.emit(dict(compared))

    def _on_prediction_failed(self, key: str, message: str) -> None:
        prefix = f"canvas.forward.predict.{self._prediction_token}."
        if not self._prediction_token or not str(key).startswith(prefix):
            return
        self.predict_btn.setEnabled(True)
        self._prediction_token = ""
        self.status.setText(f"预测失败：{message}")


class ForwardNode(CanvasNode):
    """正向预测 source 节点：展开态宿主嵌入真实模型选择表单。"""

    predictionCompleted = Signal(dict)
    setupRequested = Signal()

    def __init__(self, node_id: str, spec, context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self.context = context
        self.result_child_id: str | None = None
        self._host = NodeHost(  # factory 路径实际不会触发：直接 set_panel 挂载表单
            self, "frontend_pyside.features.canvas.forward_node:_unused"
        )
        self.panel = ForwardPredictionPanel(self.context, None)
        self.panel.predictionCompleted.connect(self.predictionCompleted.emit)
        self.panel.setupRequested.connect(self.setupRequested.emit)
        self._host.set_panel(self.panel)
        self._host.sync_geometry(*self._content_geometry())
        self._host.setVisible(False)  # 默认折叠

    # ---- 几何 -----------------------------------------------------------

    def _content_geometry(self) -> tuple[float, float, float, float]:
        return (12.0, self.HEADER_H + 8.0, self._full_w - 24.0, self._full_h - self.HEADER_H - 16.0)

    def _on_resize(self) -> None:
        self._host.sync_geometry(*self._content_geometry())

    def _on_expand_state(self) -> None:
        self._host.setVisible(not self._collapsed)
        if not self._collapsed:
            self._host.sync_geometry(*self._content_geometry())

    # ---- 摘要 -----------------------------------------------------------

    def summary_text(self) -> str:
        records = _model_records(self.context)
        if not records:
            return "请先生成数据集并训练"
        return f"预测模型 · {len(records)} 个"


__all__ = ["ForwardNode", "ForwardPredictionPanel"]
