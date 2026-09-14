"""计算设置原生节点：中心只显示摘要，详细参数由分类胶囊编辑。"""

from __future__ import annotations

import json

from PySide6.QtCore import QRectF, QSettings, Qt
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

from frontend_pyside.features.canvas.config_form import FIELD_SCHEMA
from frontend_pyside.features.canvas.model_node import ParameterCapsule, ParameterEdge
from frontend_pyside.features.canvas.node import CanvasNode
from frontend_pyside.features.canvas.theme import C
from frontend_pyside.shared.qt_zh import localize_dialog_buttons


def _font(px: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


_GROUPS = (
    ("sampling", "主网格", ("calc_precision", "grid_size")),
    ("ray_sampling", "光路采样", ("layout_pupil", "pupil", "sample_count")),
    ("propagation", "传播算法", ("algorithm",)),
    ("spectrum", "光谱设置", ("wavelength_nm",)),
)


class ConfigNode(CanvasNode):
    """不嵌表单页面的计算配置节点。"""

    SETTINGS_KEY = "canvas/compute_settings"

    def __init__(self, node_id: str, spec, task_kind: str = "compute_settings", parent=None):
        super().__init__(node_id, spec, parent)
        self.task_kind = str(task_kind or "compute_settings")
        self._chrome_settings = True
        self._config = self._default_config()
        self._config.update(self._load_settings())
        self._capsules: list[ParameterCapsule] = []
        self._parameter_edges: list[ParameterEdge] = []
        self._parameters_open = False
        self.settingsRequested.connect(self.toggle_parameter_capsules)

    def _default_config(self) -> dict:
        return {
            field.key: field.default
            for field in FIELD_SCHEMA.get(self.task_kind, ())
            if field.default is not None
        }

    def _load_settings(self) -> dict:
        try:
            raw = QSettings().value(self.SETTINGS_KEY, "")
            if isinstance(raw, str) and raw.strip():
                data = json.loads(raw)
                return dict(data) if isinstance(data, dict) else {}
            return dict(raw) if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save_settings(self) -> None:
        QSettings().setValue(self.SETTINGS_KEY, json.dumps(self._config, ensure_ascii=False))

    @property
    def config(self) -> dict:
        return self._config

    def restore_config(self, config: dict | None) -> None:
        if not isinstance(config, dict):
            return
        allowed = {field.key for field in FIELD_SCHEMA.get(self.task_kind, ())}
        self._config.update({key: value for key, value in config.items() if key in allowed})
        self._save_settings()
        if self._parameters_open:
            self._layout_parameter_capsules()
        self.update()

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
        direction = self._parameter_direction(len(_GROUPS))
        for index, (key, title, field_keys) in enumerate(_GROUPS):
            summary = " · ".join(str(self._config.get(item, "—")) for item in field_keys)
            capsule = ParameterCapsule(key, title, summary, self)
            capsule.setPos(
                -ParameterCapsule.WIDTH - 24.0 if direction < 0 else self._w + 24.0,
                34.0 + index * (ParameterCapsule.HEIGHT + 7.0),
            )
            capsule.clicked.connect(self._edit_group)
            edge = ParameterEdge(self, capsule, direction, self)
            self._capsules.append(capsule)
            self._parameter_edges.append(edge)
        self.update()

    def _parameter_direction(self, count: int) -> int:
        scene = self.scene()
        if scene is None:
            return -1
        rect = QRectF(
            self.pos().x() - ParameterCapsule.WIDTH - 24.0,
            self.pos().y() + 28.0,
            ParameterCapsule.WIDTH,
            count * (ParameterCapsule.HEIGHT + 7.0),
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
        fields = {field.key: field for field in FIELD_SCHEMA.get(self.task_kind, ())}
        dialog = QDialog()
        dialog.setSizeGripEnabled(True)
        dialog.setWindowTitle(f"计算设置 · {title}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        editors = {}
        for field_key in field_keys:
            field = fields[field_key]
            current = self._config.get(field.key, field.default)
            if field.kind == "choice":
                editor = QComboBox(dialog)
                editor.addItems(list(field.choices))
                editor.setCurrentText(str(current))
            elif field.kind == "int":
                editor = QSpinBox(dialog)
                editor.setRange(int(field.minimum), int(field.maximum))
                editor.setValue(int(current or 0))
            else:
                editor = QDoubleSpinBox(dialog)
                editor.setRange(float(field.minimum), float(field.maximum))
                editor.setDecimals(field.decimals)
                editor.setValue(float(current or 0.0))
                if field.suffix:
                    editor.setSuffix(field.suffix)
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
        for key, editor in editors.items():
            if isinstance(editor, QComboBox):
                self._config[key] = editor.currentText()
            elif isinstance(editor, QSpinBox):
                self._config[key] = int(editor.value())
            else:
                self._config[key] = float(editor.value())
        self._save_settings()
        self.set_stale(True, f"{title}已修改")
        self._layout_parameter_capsules()
        self.update()

    def summary_text(self) -> str:
        return f"{self._config.get('algorithm', '—')} · {self._config.get('grid_size', '—')}"

    def _paint_content(self, painter, rect: QRectF) -> None:
        rows = (
            ("传播算法", str(self._config.get("algorithm", "—"))),
            ("采样点数", str(self._config.get("sample_count", "—"))),
            ("接收面网格", str(self._config.get('grid_size', '—'))),
            ("光路 / 光瞳", f"{self._config.get('layout_pupil', '—')} · {self._config.get('pupil', '—')}"),
            ("工作波长", f"{self._config.get('wavelength_nm', '—')} nm"),
        )
        painter.setClipRect(rect)
        painter.setFont(_font(10))
        for index, (label, value) in enumerate(rows):
            y = rect.top() + 8.0 + index * 24.0
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(QRectF(rect.left(), y, rect.width() * 0.42, 18.0), Qt.AlignmentFlag.AlignLeft, label)
            painter.setPen(QColor(C["text"]))
            painter.setFont(_font(10, True))
            painter.drawText(
                QRectF(rect.left() + rect.width() * 0.42, y, rect.width() * 0.58, 18.0),
                Qt.AlignmentFlag.AlignRight,
                value,
            )
            painter.setFont(_font(10))
        painter.setPen(QColor(C["text_muted"]))
        painter.drawText(
            QRectF(rect.left(), rect.bottom() - 24.0, rect.width(), 18.0),
            Qt.AlignmentFlag.AlignCenter,
            "点击齿轮按分类设置参数",
        )
        painter.setClipping(False)


__all__ = ["ConfigNode"]
