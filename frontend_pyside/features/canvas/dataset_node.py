"""数据集原生节点：选择已有数据集或提交数据集生成任务。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.model_node import ParameterCapsule, ParameterEdge
from frontend_pyside.features.canvas.parameter_catalog import (
    DATASET_PRECISION_CHOICES,
    DATASET_SAMPLING_CHOICES,
    DATASET_TARGET_CHOICES,
)
from frontend_pyside.features.canvas.theme import C
from frontend_pyside.shared.qt_zh import localize_dialog_buttons


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


_GROUPS = (
    ("selection", "已有数据集", ("selected_dataset_id",)),
    ("generation", "数据生成", ("sampling_method", "sample_count", "precision")),
    ("target", "目标变量", ("target",)),
    ("split", "数据划分", ("validation_ratio", "random_seed")),
)


QUICK_LOOP_SAMPLE_COUNT = 16


class DatasetNode(CanvasNode):
    """数据集工作流节点；无完整页面、无代理 QWidget。"""

    taskRunRequested = Signal(str)

    def __init__(self, node_id: str, spec, context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self.context = context
        self.task_kind = "dataset"
        self._chrome_settings = True
        self._chrome_run = True
        self._config = {
            "selected_dataset_id": "",
            "sampling_method": "latin_hypercube",
            "sample_count": 50,
            "precision": "standard",
            "target": "coupling_efficiency",
            "validation_ratio": 0.15,
            "random_seed": 42,
        }
        self._phase = "idle"
        self._progress = 0.0
        self._stage = ""
        self._job_id = ""
        self._note = ""
        self._result_rows: list[tuple[str, str]] = []
        self._capsules: list[ParameterCapsule] = []
        self._parameter_edges: list[ParameterEdge] = []
        self._parameters_open = False
        self.settingsRequested.connect(self.toggle_parameter_capsules)
        self.runRequested.connect(self.run_task)
        self._bind_context()
        self._request_dataset_list()

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def project_context(self):
        """TaskRunner 需要的项目源；节点本身不复制项目数据。"""
        return getattr(self.context, "project", None)

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def job_id(self) -> str:
        return self._job_id

    def restore_config(self, config: dict | None) -> None:
        if not isinstance(config, dict):
            return
        allowed = set(self._config)
        self._config.update({key: value for key, value in config.items() if key in allowed})
        self._sync_registry_selection()
        if self._parameters_open:
            self._layout_parameter_capsules()
        self.update()

    def _bind_context(self) -> None:
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.datasets_changed.connect(self._on_datasets_changed)
            registry.current_dataset_changed.connect(self._on_current_dataset_changed)

    def _request_dataset_list(self) -> None:
        services = getattr(self.context, "services", None)
        api = getattr(self.context, "api_client", None)
        client = getattr(services, "dataset", None)
        if api is None or client is None:
            return
        self._dataset_list_key = f"canvas.datasets.list.{uuid4().hex[:8]}"
        api.completed.connect(self._on_api_completed)
        client.list_datasets(self._dataset_list_key)

    def _on_api_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_dataset_list_key", ""):
            return
        records = data.get("items", data) if isinstance(data, dict) else data
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.set_datasets([item for item in (records or []) if isinstance(item, dict)])

    def _on_datasets_changed(self, _records: list) -> None:
        self._sync_registry_selection()
        self.update()

    def _on_current_dataset_changed(self, dataset_id: str) -> None:
        if str(dataset_id or ""):
            self._config["selected_dataset_id"] = str(dataset_id)
        self.update()

    def _sync_registry_selection(self) -> None:
        registry = getattr(self.context, "registry", None)
        if registry is None:
            return
        current = str(getattr(registry, "current_dataset_id", "") or "")
        if current and not str(self._config.get("selected_dataset_id", "") or ""):
            self._config["selected_dataset_id"] = current

    def _datasets(self) -> list[dict]:
        registry = getattr(self.context, "registry", None)
        return list(getattr(registry, "datasets", []) or []) if registry is not None else []

    @staticmethod
    def _dataset_id(record: dict) -> str:
        return str(record.get("dataset_id", record.get("id", "")) or "")

    @staticmethod
    def _dataset_label(record: dict) -> str:
        dataset_id = DatasetNode._dataset_id(record)
        name = str(record.get("dataset_name", record.get("name", "")) or "")
        samples = record.get("sample_count")
        suffix = f" · {int(samples)} 条" if isinstance(samples, (int, float)) else ""
        return f"{name or dataset_id}{suffix}" if dataset_id else name

    def toggle_parameter_capsules(self) -> None:
        if self._parameters_open:
            self._clear_parameter_capsules()
            return
        self._parameters_open = True
        self._layout_parameter_capsules()

    def _clear_parameter_capsules(self) -> None:
        for edge in self._parameter_edges:
            if edge.scene() is not None:
                edge.scene().removeItem(edge)
            edge.setParentItem(None)
        for capsule in self._capsules:
            if capsule.scene() is not None:
                capsule.scene().removeItem(capsule)
            capsule.setParentItem(None)
        self._parameter_edges.clear()
        self._capsules.clear()
        self._parameters_open = False

    def _on_resize(self) -> None:
        self._layout_parameter_capsules()

    def _on_expand_state(self) -> None:
        self._layout_parameter_capsules()

    def _layout_parameter_capsules(self) -> None:
        if not self._parameters_open:
            return
        self._clear_parameter_capsules()
        self._parameters_open = True
        direction = self._parameter_direction()
        for index, (key, title, keys) in enumerate(_GROUPS):
            summary = " · ".join(str(self._config.get(item, "—")) for item in keys[:2])
            capsule = ParameterCapsule(key, title, summary, self)
            capsule.setPos(
                -ParameterCapsule.WIDTH - 24.0 if direction < 0 else self._w + 24.0,
                34.0 + index * (ParameterCapsule.HEIGHT + 7.0),
            )
            capsule.clicked.connect(self._edit_group)
            self._capsules.append(capsule)
            self._parameter_edges.append(ParameterEdge(self, capsule, direction, self))
        self.update()

    def _parameter_direction(self) -> int:
        scene = self.scene()
        if scene is None:
            return -1
        rect = QRectF(
            self.pos().x() - ParameterCapsule.WIDTH - 24.0,
            self.pos().y() + 28.0,
            ParameterCapsule.WIDTH,
            len(_GROUPS) * (ParameterCapsule.HEIGHT + 7.0),
        )
        for item in scene.items(rect):
            if item is self or item in self._capsules or item in self._parameter_edges:
                continue
            if hasattr(item, "spec"):
                return 1
        return -1

    def _edit_group(self, group_key: str) -> None:
        group = next((item for item in _GROUPS if item[0] == group_key), None)
        if group is None:
            return
        _key, title, field_keys = group
        dialog = QDialog()
        dialog.setSizeGripEnabled(True)
        dialog.setWindowTitle(f"数据集 · {title}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        editors: dict[str, object] = {}
        for field_key in field_keys:
            if field_key == "selected_dataset_id":
                editor = QComboBox(dialog)
                editor.addItem("未选择", "")
                for record in self._datasets():
                    editor.addItem(self._dataset_label(record), self._dataset_id(record))
                current = str(self._config.get(field_key, "") or "")
                index = editor.findData(current)
                if index >= 0:
                    editor.setCurrentIndex(index)
                editors[field_key] = editor
                form.addRow(QLabel("数据集", dialog), editor)
            elif field_key == "sampling_method":
                editor = QComboBox(dialog)
                editor.addItem(DATASET_SAMPLING_CHOICES[0], "latin_hypercube")
                editor.addItem(DATASET_SAMPLING_CHOICES[1], "sobol")
                editor.setCurrentIndex(max(0, editor.findData(self._config.get(field_key))))
                editors[field_key] = editor
                form.addRow(QLabel("采样方式", dialog), editor)
            elif field_key == "precision":
                editor = QComboBox(dialog)
                for label, value in zip(DATASET_PRECISION_CHOICES, ("preview", "standard", "high")):
                    editor.addItem(label, value)
                editor.setCurrentIndex(max(0, editor.findData(self._config.get(field_key))))
                editors[field_key] = editor
                form.addRow(QLabel("采样精度", dialog), editor)
            elif field_key == "target":
                editor = QComboBox(dialog)
                for label, value in zip(DATASET_TARGET_CHOICES, ("coupling_loss_db", "coupling_efficiency", "rms_spot_radius_um", "strehl_estimate_marechal")):
                    editor.addItem(label, value)
                editor.setCurrentIndex(max(0, editor.findData(self._config.get(field_key))))
                editors[field_key] = editor
                form.addRow(QLabel("目标变量", dialog), editor)
            elif field_key == "sample_count":
                editor = QSpinBox(dialog)
                editor.setRange(20, 100000)
                editor.setValue(int(self._config.get(field_key, 50)))
                editors[field_key] = editor
                form.addRow(QLabel("样本数", dialog), editor)
            elif field_key == "validation_ratio":
                editor = QDoubleSpinBox(dialog)
                editor.setRange(0.05, 0.45)
                editor.setSingleStep(0.05)
                editor.setDecimals(2)
                editor.setValue(float(self._config.get(field_key, 0.15)))
                editors[field_key] = editor
                form.addRow(QLabel("验证比例", dialog), editor)
            else:
                editor = QSpinBox(dialog)
                editor.setRange(0, 999999)
                editor.setValue(int(self._config.get(field_key, 42)))
                editors[field_key] = editor
                form.addRow(QLabel("随机种子", dialog), editor)
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
        for key, editor in editors.items():
            if isinstance(editor, QComboBox):
                value = editor.currentData()
            elif isinstance(editor, QSpinBox):
                value = int(editor.value())
            else:
                value = float(editor.value())
            self._config[key] = value
        if group_key == "selection":
            self._sync_registry_selection()
            registry = getattr(self.context, "registry", None)
            if registry is not None:
                registry.set_current_dataset(str(self._config.get("selected_dataset_id", "") or ""))
        self.set_stale(True, f"{title}已修改")
        self._layout_parameter_capsules()
        self.update()

    def prepare_quick_loop(self) -> None:
        """Empty-path demo: keep a short sample so outsiders can finish one loop."""
        if self._datasets() or str(self._config.get("selected_dataset_id", "") or ""):
            return
        self._config["sample_count"] = QUICK_LOOP_SAMPLE_COUNT
        self._note = ""
        self.update()

    def run_task(self) -> None:
        if self._phase in {"submitting", "running"}:
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
        body = dict(result or {})
        self._phase, self._progress, self._job_id = "done", 1.0, ""
        dataset_id = self._dataset_id(body)
        if dataset_id:
            self._config["selected_dataset_id"] = dataset_id
            registry = getattr(self.context, "registry", None)
            if registry is not None:
                registry.merge_dataset(body)
                registry.set_current_dataset(dataset_id)
        self._result_rows = [
            ("数据集", dataset_id or "已生成"),
            ("样本数", str(body.get("sample_count", "—"))),
            ("状态", str(body.get("status", "已完成"))),
        ]
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
            return f"{self._stage or '生成中'} {self._progress:.0%}"
        if self._phase == "failed":
            return self._note[:22] or "失败"
        selected = str(self._config.get("selected_dataset_id", "") or "")
        return selected[:22] if selected else "请选择或生成数据集"

    def _paint_content(self, painter, rect: QRectF) -> None:
        painter.setClipRect(rect)
        painter.setPen(QColor(C["text"]))
        painter.setFont(_font(11, True))
        painter.drawText(QRectF(rect.left(), rect.top(), rect.width(), 18.0), Qt.AlignmentFlag.AlignLeft, "数据集工作流")
        rows = (
            ("当前数据集", str(self._config.get("selected_dataset_id", "") or "未选择")),
            ("样本 / 采样", f"{self._config.get('sample_count', 50)} · {self._config.get('sampling_method', 'latin_hypercube')}"),
            ("目标变量", str(self._config.get("target", "coupling_efficiency"))),
            ("划分", f"训练 {1.0 - float(self._config.get('validation_ratio', 0.15)) - 0.15:.0%} · 验证 {float(self._config.get('validation_ratio', 0.15)):.0%} · 测试 15%"),
        )
        painter.setFont(_font(10))
        for index, (label, value) in enumerate(rows):
            y = rect.top() + 25.0 + index * 23.0
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(QRectF(rect.left(), y, rect.width() * 0.38, 17.0), Qt.AlignmentFlag.AlignLeft, label)
            painter.setPen(QColor(C["text"]))
            painter.drawText(QRectF(rect.left() + rect.width() * 0.38, y, rect.width() * 0.62, 17.0), Qt.AlignmentFlag.AlignRight, value[:42])
        if self._phase in {"submitting", "running"}:
            bar = QRectF(rect.left(), rect.bottom() - 34.0, rect.width(), 8.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(C["grid_dot"]))
            painter.drawRoundedRect(bar, 4.0, 4.0)
            painter.setBrush(QColor(C["badge"]))
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * self._progress, bar.height()), 4.0, 4.0)
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(QRectF(rect.left(), bar.top() - 18.0, rect.width(), 16.0), Qt.AlignmentFlag.AlignRight, f"{self._stage} {self._progress:.0%}")
        elif self._result_rows:
            painter.setPen(QColor(C["text_muted"]))
            painter.setFont(_font(10))
            painter.drawText(QRectF(rect.left(), rect.bottom() - 50.0, rect.width(), 17.0), Qt.AlignmentFlag.AlignLeft, " · ".join(f"{k}: {v}" for k, v in self._result_rows)[:100])
        elif self._note:
            painter.setPen(QColor("#B00020"))
            painter.drawText(QRectF(rect.left(), rect.bottom() - 45.0, rect.width(), 32.0), Qt.TextFlag.TextWordWrap, self._note[:100])
        elif not self._datasets():
            painter.setPen(QColor(C["text"]))
            painter.setFont(_font(10, True))
            painter.drawText(
                QRectF(rect.left(), rect.bottom() - 52.0, rect.width(), 44.0),
                Qt.TextFlag.TextWordWrap,
                "尚无数据集。点右上角 ▶ 按当前镜头组采样（闭环默认 16 条），完成后去模型节点点 ▶ 训练。",
            )
        painter.setClipping(False)


__all__ = ["DatasetNode"]
