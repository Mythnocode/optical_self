"""M6 tool/task 节点：参数研究 / 容差 / 优化任务卡片。

- 展开态：可编辑参数表单（✓ 确认参数，不关节点；× 关闭）+ 「运行」按钮 +
  进度条（job_watcher 实时进度）+ 结果区（scan 曲线 / tolerance 统计 / optimize 收敛）；
- 提交链路：taskRunRequested(node_id) → TaskRunner 构造 payload →
  HTTP 任务（/scan|/tolerance|/optimization /jobs）→ 进度 → 完成取回结果；
- 脏传播：镜头组变更 → 标「!」→ 菜单支持「重新运行 / 实时重跑 / 忽略」。
"""

from __future__ import annotations

import math

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.canvas.config_form import FIELD_SCHEMA
from frontend_pyside.features.canvas.model_node import ParameterCapsule, ParameterEdge
from frontend_pyside.shared.qt_zh import localize_dialog_buttons
from frontend_pyside.features.canvas.parameter_catalog import (
    OPTIMIZATION_ALGORITHM_CHOICES,
    OPTIMIZATION_OBJECTIVE_CHOICES,
    SCAN_MODE_CHOICES,
    SCAN_RESPONSE_CHOICES,
    SCAN_SCALE_CHOICES,
    TOLERANCE_CANDIDATE_CHOICES,
    TOLERANCE_DISTRIBUTION_CHOICES,
    TOLERANCE_SAMPLING_CHOICES,
    TOLERANCE_TEMPLATE_CHOICES,
    VALIDATION_METRIC_CHOICES,
    VALIDATION_REFERENCE_CHOICES,
    VARIABLE_FILTER_CHOICES,
    VARIABLE_SCALE_CHOICES,
)
from frontend_pyside.features.canvas.node import CanvasNode, find_view
from frontend_pyside.features.canvas.theme import C


def _font(px: int, bold: bool = False):
    from PySide6.QtGui import QFont

    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


# ---- 任务默认配置（key → 参数；正式提交时由 TaskRunner 读取） --------------

TASK_CONFIGS: dict[str, dict] = {
    "scan": {
        "param_path": "surfaces[0].radius_mm",
        "param_label": "L1 前表面半径",
        "scan_mode": SCAN_MODE_CHOICES[0],
        "param_path2": "",
        "param_label2": "",
        "start": 4.6,
        "stop": 5.6,
        "points": 81,
        "start2": -2.0,
        "stop2": 2.0,
        "points2": 41,
        "response": SCAN_RESPONSE_CHOICES[0],
        "scale": SCAN_SCALE_CHOICES[0],
        "include_baseline": True,
        "local_refine": True,
    },
    "tolerance": {
        "params": [
            ("surfaces[0].radius_mm", "L1 前表面半径", 5.11, 0.02),
            ("surfaces[2].radius_mm", "L2 前表面半径", 4.088, 0.02),
        ],
        "sample_count": 256,
        "sampling": TOLERANCE_SAMPLING_CHOICES[0],
        "distribution": TOLERANCE_DISTRIBUTION_CHOICES[0],
        "candidate": TOLERANCE_CANDIDATE_CHOICES[1],
        "template": TOLERANCE_TEMPLATE_CHOICES[0],
        "threshold_efficiency": 0.8,
        "include_deterministic_sensitivity": True,
    },
    "optimize": {
        "param_path": "surfaces[0].radius_mm",
        "param_label": "L1 前表面半径",
        "objective": OPTIMIZATION_OBJECTIVE_CHOICES[0],
        "variable_filter": VARIABLE_FILTER_CHOICES[0],
        "variable_scale": VARIABLE_SCALE_CHOICES[0],
        "algorithm": OPTIMIZATION_ALGORITHM_CHOICES[0],
        "starts": 8,
        "collimation_surface": "",
        "collimation_enabled": False,
        "collimation_span": 10.0,
        "collimation_radius_change": 2.0,
        "collimation_curvature": 0.05,
        "collimation_centroid_drift": 1.0,
        "collimation_axis_tilt": 1.0,
        "lower": 4.0,
        "upper": 6.5,
        "initial": 5.11,
        "max_iterations": 300,
        "convergence_tolerance": 1e-6,
        "validation_metric": VALIDATION_METRIC_CHOICES[0],
        "validation_reference": VALIDATION_REFERENCE_CHOICES[0],
    },
    "physical_inverse": {
        "param_path": "surfaces[0].radius_mm",
        "param_label": "L1 前表面半径",
        "lower": 4.0,
        "upper": 6.5,
        "initial": 5.11,
        "target_efficiency": 0.95,
        "max_iterations": 20,
    },
    "ml_inverse": {
        "surrogate_model_id": "",
        "param_path": "surfaces[0].radius_mm",
        "param_label": "L1 前表面半径",
        "lower": 4.0,
        "upper": 6.5,
        "initial": 5.11,
        "target_efficiency": 0.95,
        "max_iterations": 20,
    },
}

TASK_TITLES = {
    "scan": "参数研究",
    "tolerance": "容差分析",
    "optimize": "自动优化",
    "physical_inverse": "物理反向设计",
    "ml_inverse": "代理模型反向预测",
}

TASK_GROUPS = {
    "scan": (
        ("target", "输入与目标", ("scan_mode", "param_path", "param_path2", "param_label", "param_label2")),
        ("range", "扫描范围", ("start", "stop", "points", "start2", "stop2", "points2")),
        ("response", "采样与响应", ("scale", "response", "include_baseline", "local_refine")),
    ),
    "tolerance": (
        ("parameters", "容差参数", ("params",)),
        ("sampling", "采样设置", ("candidate", "template", "sample_count", "sampling")),
        ("threshold", "判定条件", ("threshold_efficiency", "include_deterministic_sensitivity")),
    ),
    "optimize": (
        ("target", "变量与目标", ("param_path", "param_label", "objective")),
        ("range", "变量范围", ("lower", "upper", "initial")),
        ("algorithm", "搜索算法", ("algorithm", "starts", "variable_filter", "variable_scale")),
        ("constraint", "准直约束", ("collimation_enabled", "collimation_surface", "collimation_span", "collimation_radius_change")),
        ("stop", "停止条件", ("max_iterations", "convergence_tolerance")),
        ("validation", "实验验证", ("validation_metric", "validation_reference")),
    ),
    "physical_inverse": (
        ("target", "变量与目标", ("param_label", "target_efficiency")),
        ("range", "变量范围", ("lower", "upper", "initial")),
        ("stop", "停止条件", ("max_iterations",)),
    ),
    "ml_inverse": (
        ("model", "代理模型", ("surrogate_model_id",)),
        ("target", "变量与目标", ("param_label", "target_efficiency")),
        ("range", "变量范围", ("lower", "upper", "initial")),
        ("stop", "停止条件", ("max_iterations",)),
    ),
}


class TaskNode(CanvasNode):
    """tool 节点：提交后端任务 + 实时进度 + 结果摘要/曲线。"""

    REALTIME_DEBOUNCE_MS = 700

    taskRunRequested = Signal(str)  # node_id（请求壳层提交后端任务）

    def __init__(self, node_id: str, spec, task_kind: str, context=None, parent=None):
        super().__init__(node_id, spec, parent)
        self.context = context
        self.task_kind = str(task_kind)
        self._chrome_settings = True
        self._chrome_run = True
        self._config = dict(TASK_CONFIGS.get(self.task_kind, {}))
        # phase: idle / submitting / running / done / failed
        self._phase = "idle"
        self._progress = 0.0
        self._stage = ""
        self._job_id = ""
        self._note = ""
        self._confirmed_note = ""
        # 结果缓存
        self._curve: tuple[np.ndarray, np.ndarray] | None = None  # scan 曲线
        self._result_rows: list[tuple[str, str]] = []  # 文本摘要行
        self._history: list[float] = []  # optimize 收敛历史
        self._summary_metric = "未运行"

        self._parameter_capsules: list[ParameterCapsule] = []
        self._parameter_edges: list[ParameterEdge] = []
        self._parameters_open = False
        self.settingsRequested.connect(self.toggle_parameter_capsules)
        self.runRequested.connect(self.run_task)

        self._rt_timer = QTimer(self)
        self._rt_timer.setSingleShot(True)
        self._rt_timer.setInterval(self.REALTIME_DEBOUNCE_MS)
        self._rt_timer.timeout.connect(self.run_task)
        self._bind_registry()

    def _bind_registry(self) -> None:
        registry = getattr(self.context, "registry", None)
        if registry is None:
            return
        if self.task_kind == "ml_inverse":
            registry.models_changed.connect(lambda _records: self._on_registry_models_changed())
            registry.current_model_changed.connect(self._on_current_model_changed)
            current = str(getattr(registry, "current_model_id", "") or "")
            if current and not str(self._config.get("surrogate_model_id", "") or ""):
                self._config["surrogate_model_id"] = current
            services = getattr(self.context, "services", None)
            api = getattr(self.context, "api_client", None)
            client = getattr(services, "training", None)
            if api is not None and client is not None and not getattr(registry, "models", None):
                self._model_list_key = f"canvas.inverse.models.list.{id(self)}"
                api.completed.connect(self._on_registry_api_completed)
                client.list_models(self._model_list_key)

    def _on_registry_api_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_model_list_key", ""):
            return
        records = data.get("models", data.get("items", data)) if isinstance(data, dict) else data
        registry = getattr(self.context, "registry", None)
        if registry is not None:
            registry.set_models([item for item in (records or []) if isinstance(item, dict)])

    def _on_registry_models_changed(self) -> None:
        if self._parameters_open:
            self._layout_parameter_capsules()
        self.update()

    def _on_current_model_changed(self, model_id: str) -> None:
        if self.task_kind == "ml_inverse" and str(model_id or ""):
            self._config["surrogate_model_id"] = str(model_id)
            self.set_stale(True, "当前代理模型已切换，请确认反向预测参数")
            if self._parameters_open:
                self._layout_parameter_capsules()
            self.update()

    # ---- 参数表单 ------------------------------------------------------------

    def _form_geometry(self) -> tuple[float, float, float, float]:
        rows = max(1, len(self._config_lines()))
        height = 8.0 + rows * 18.0
        return (12.0, self.HEADER_H + 6.0, self._full_w - 24.0, height)

    def _run_button_rect(self) -> QRectF:
        form = self._form_geometry()
        return QRectF(12.0, form[1] + form[3] + 8.0, 96.0, 24.0)

    def _on_resize(self) -> None:
        self._layout_parameter_capsules()

    def _on_expand_state(self) -> None:
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
        for capsule in self._parameter_capsules:
            scene = capsule.scene()
            if scene is not None:
                scene.removeItem(capsule)
            capsule.setParentItem(None)
        self._parameter_edges.clear()
        self._parameter_capsules.clear()
        self._parameters_open = False

    def _layout_parameter_capsules(self) -> None:
        if not self._parameters_open:
            return
        self._clear_parameter_capsules()
        self._parameters_open = True
        groups = TASK_GROUPS.get(self.task_kind, ())
        direction = self._parameter_direction(len(groups))
        for index, (key, title, field_keys) in enumerate(groups):
            summary = " · ".join(str(self._config.get(field_key, "—")) for field_key in field_keys[:2])
            capsule = ParameterCapsule(key, title, summary, self)
            capsule.setPos(
                -ParameterCapsule.WIDTH - 24.0 if direction < 0 else self._w + 24.0,
                34.0 + index * (ParameterCapsule.HEIGHT + 7.0),
            )
            capsule.clicked.connect(self._edit_parameter_group)
            edge = ParameterEdge(self, capsule, direction, self)
            self._parameter_capsules.append(capsule)
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
            if item is self or item in self._parameter_capsules or item in self._parameter_edges:
                continue
            if hasattr(item, "spec"):
                return 1
        return -1

    def _edit_parameter_group(self, group_key: str) -> None:
        group = next((item for item in TASK_GROUPS.get(self.task_kind, ()) if item[0] == group_key), None)
        if group is None:
            return
        _key, title, field_keys = group
        if self.task_kind == "tolerance" and group_key == "parameters":
            self._edit_tolerance_parameters()
            return
        fields = {field.key: field for field in FIELD_SCHEMA.get(self.task_kind, ())}
        dialog = QDialog()
        dialog.setSizeGripEnabled(True)
        dialog.setWindowTitle(f"{TASK_TITLES.get(self.task_kind, self.title)} · {title}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        editors = {}
        for field_key in field_keys:
            field = fields.get(field_key)
            if field is None:
                continue
            current = self._config.get(field.key, field.default)
            if field.key in {"param_path", "param_path2"}:
                editor = QComboBox(dialog)
                if field.key == "param_path2":
                    editor.addItem("不启用", "")
                for label, path in self._available_parameter_options():
                    editor.addItem(label, path)
                selected = str(current or "")
                index = editor.findData(selected)
                editor.setCurrentIndex(index if index >= 0 else 0)
            elif field.key == "collimation_surface":
                editor = QComboBox(dialog)
                editor.addItem("自动识别准直输出面", "")
                for label, index in self._available_collimation_options():
                    editor.addItem(label, index)
                selected = str(current or "")
                index = editor.findData(int(selected)) if selected.isdigit() else editor.findData(selected)
                editor.setCurrentIndex(index if index >= 0 else 0)
            elif field.key == "surrogate_model_id":
                editor = QComboBox(dialog)
                editor.addItem("未选择代理模型", "")
                registry = getattr(self.context, "registry", None)
                records = list(getattr(registry, "models", []) or []) if registry is not None else []
                for record in records:
                    model_id = str(record.get("model_id", record.get("id", "")) or "")
                    if not model_id:
                        continue
                    name = str(record.get("name", record.get("model_name", model_id)) or model_id)
                    editor.addItem(name, model_id)
                selected = str(current or "")
                index = editor.findData(selected)
                editor.setCurrentIndex(index if index >= 0 else 0)
            elif field.kind == "bool":
                editor = QCheckBox(field.label, dialog)
                editor.setChecked(bool(current))
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
        for field_key, editor in editors.items():
            field = fields[field_key]
            if field.key in {"param_path", "param_path2"}:
                value = str(editor.currentData() or "")
                self._config[field_key] = value
                if field.key == "param_path":
                    selected_label = editor.currentText()
                    self._config["param_label"] = selected_label.split(" · ", 1)[-1] if " · " in selected_label else selected_label
                continue
            if field.key == "collimation_surface":
                value = editor.currentData()
                self._config[field_key] = "" if value in (None, "") else int(value)
                continue
            if field.key == "surrogate_model_id":
                self._config[field_key] = str(editor.currentData() or "")
                continue
            if field.kind == "bool":
                self._config[field_key] = bool(editor.isChecked())
                continue
            if field.kind == "choice":
                value = editor.currentText()
            elif field.kind == "int":
                value = int(editor.value())
            elif field.kind == "float":
                value = float(editor.value())
            else:
                value = editor.text().strip()
            self._config[field_key] = value
        self.set_stale(True, f"{title}参数已修改")
        self._layout_parameter_capsules()
        self.update()

    def _edit_tolerance_parameters(self) -> None:
        """编辑容差参数表；每一行保留旧版的参数、分布和启用状态。"""
        dialog = QDialog()
        dialog.setWindowTitle("容差分析 · 容差参数")
        dialog.setMinimumSize(760, 360)
        layout = QVBoxLayout(dialog)
        hint = QLabel("可从镜头组动态参数中选择多行；正态使用 σ，均匀/三角使用 ±容差。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        table = QTableWidget(0, 6, dialog)
        table.setHorizontalHeaderLabels(("启用", "参数", "名义值", "分布", "σ / ±容差", "单位"))
        table.setMinimumHeight(230)
        table.setColumnWidth(0, 48)
        table.setColumnWidth(1, 250)
        table.setColumnWidth(2, 108)
        table.setColumnWidth(3, 90)
        table.setColumnWidth(4, 110)
        table.setColumnWidth(5, 64)
        layout.addWidget(table)

        choices = self._available_parameter_options()

        def append_row(item=None) -> None:
            row = table.rowCount()
            table.insertRow(row)
            item_dict = item if isinstance(item, dict) else {}
            if isinstance(item, (tuple, list)):
                values = list(item)
                item_dict = {
                    "path": values[0] if len(values) > 0 else "",
                    "label": values[1] if len(values) > 1 else "",
                    "nominal": values[2] if len(values) > 2 else 0.0,
                    "sigma": values[3] if len(values) > 3 else 0.01,
                }
            path = str(item_dict.get("path", "") or (choices[0][1] if choices else ""))
            label = str(item_dict.get("label", "") or path)
            nominal = float(item_dict.get("nominal", 0.0) or 0.0)
            sigma = abs(float(item_dict.get("sigma", 0.01) or 0.01))
            distribution = str(item_dict.get("distribution_label", item_dict.get("distribution", "正态")) or "正态")
            if distribution in {"normal", "uniform", "triangular"}:
                distribution = {"normal": "正态", "uniform": "均匀", "triangular": "三角"}[distribution]
            enabled = bool(item_dict.get("enabled", True))

            enabled_box = QCheckBox(dialog)
            enabled_box.setChecked(enabled)
            enabled_host = QWidget(dialog)
            enabled_layout = QHBoxLayout(enabled_host)
            enabled_layout.setContentsMargins(0, 0, 0, 0)
            enabled_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            enabled_layout.addWidget(enabled_box)
            table.setCellWidget(row, 0, enabled_host)

            path_combo = QComboBox(dialog)
            for option_label, option_path in choices:
                path_combo.addItem(option_label, option_path)
            if path and path_combo.findData(path) < 0:
                path_combo.addItem(label or path, path)
            path_combo.setCurrentIndex(max(0, path_combo.findData(path)))
            table.setCellWidget(row, 1, path_combo)

            nominal_spin = QDoubleSpinBox(dialog)
            nominal_spin.setDecimals(6)
            nominal_spin.setRange(-1.0e9, 1.0e9)
            nominal_spin.setValue(nominal)
            table.setCellWidget(row, 2, nominal_spin)

            distribution_combo = QComboBox(dialog)
            distribution_combo.addItems(list(TOLERANCE_DISTRIBUTION_CHOICES))
            distribution_combo.setCurrentText(distribution if distribution in TOLERANCE_DISTRIBUTION_CHOICES else "正态")
            table.setCellWidget(row, 3, distribution_combo)

            sigma_spin = QDoubleSpinBox(dialog)
            sigma_spin.setDecimals(6)
            sigma_spin.setRange(0.0, 1.0e9)
            sigma_spin.setValue(sigma)
            table.setCellWidget(row, 4, sigma_spin)
            table.setItem(row, 5, QTableWidgetItem(self._parameter_unit(path)))

            def update_row_unit(index: int, row_index: int = row) -> None:
                path_value = str(path_combo.itemData(index) or "")
                unit_item = table.item(row_index, 5)
                if unit_item is not None:
                    unit_item.setText(self._parameter_unit(path_value))

            path_combo.currentIndexChanged.connect(update_row_unit)

        for item in list(self._config.get("params") or []):
            append_row(item)
        if table.rowCount() == 0:
            append_row()

        actions = QHBoxLayout()
        add_button = QPushButton("添加参数", dialog)
        remove_button = QPushButton("删除选中行", dialog)
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        def remove_selected() -> None:
            rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
            for row in rows:
                table.removeRow(row)

        add_button.clicked.connect(lambda: append_row())
        remove_button.clicked.connect(remove_selected)
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

        values: list[dict[str, Any]] = []
        for row in range(table.rowCount()):
            enabled_host = table.cellWidget(row, 0)
            enabled_box = enabled_host.findChild(QCheckBox) if enabled_host is not None else None
            path_combo = table.cellWidget(row, 1)
            nominal_spin = table.cellWidget(row, 2)
            distribution_combo = table.cellWidget(row, 3)
            sigma_spin = table.cellWidget(row, 4)
            path = str(path_combo.currentData() or "") if isinstance(path_combo, QComboBox) else ""
            if not path:
                continue
            label = str(path_combo.currentText() or path).split(" · ", 1)[-1]
            values.append({
                "path": path,
                "label": label,
                "nominal": float(nominal_spin.value()) if isinstance(nominal_spin, QDoubleSpinBox) else 0.0,
                "sigma": abs(float(sigma_spin.value())) if isinstance(sigma_spin, QDoubleSpinBox) else 0.0,
                "distribution_label": distribution_combo.currentText() if isinstance(distribution_combo, QComboBox) else "正态",
                "enabled": bool(enabled_box.isChecked()) if enabled_box is not None else True,
            })
        self._config["params"] = values
        self.set_stale(True, "容差参数已修改")
        self._layout_parameter_capsules()
        self.update()

    def _available_parameter_options(self) -> list[tuple[str, str]]:
        """返回旧版参数研究使用的动态变量列表。"""
        options: list[tuple[str, str]] = [("波长 · source.wavelength_nm", "source.wavelength_nm")]
        lens = None
        scene = self.scene()
        if scene is not None:
            lens = next(iter(scene.nodes_by_key("lens_editor")), None)
        rows = lens.surface_rows() if lens is not None and hasattr(lens, "surface_rows") else []
        for index, row in enumerate(rows):
            name = str(row.get("name", f"S{index + 1}"))
            options.append((f"{name} · 曲率", f"surfaces[{index}].radius_mm"))
            options.append((f"{name} · 厚度", f"surfaces[{index}].distance_to_next_mm"))
        options.extend([
            ("光纤模场直径 · receiver.mode_field_diameter_x_um", "receiver.mode_field_diameter_x_um"),
            ("接收面位置 · image_distance_mm", "image_distance_mm"),
            ("光纤 X 偏移 · receiver.offset_x_mm", "receiver.offset_x_mm"),
            ("光纤 Y 偏移 · receiver.offset_y_mm", "receiver.offset_y_mm"),
            ("光纤倾角 X · receiver.tilt_x_deg", "receiver.tilt_x_deg"),
            ("光纤倾角 Y · receiver.tilt_y_deg", "receiver.tilt_y_deg"),
        ])
        return options

    def _available_collimation_options(self) -> list[tuple[str, int]]:
        """镜头组变化后动态重建旧版“评价位置”下拉项。"""
        scene = self.scene()
        lens = next(iter(scene.nodes_by_key("lens_editor")), None) if scene is not None else None
        rows = lens.surface_rows() if lens is not None and hasattr(lens, "surface_rows") else []
        return [
            (f"{row.get('name', f'表面 {index + 1}')}（表面 {index} 后）", index)
            for index, row in enumerate(rows)
        ]

    def _on_confirm(self) -> None:
        """兼容旧调用方；新界面通过参数胶囊即时写回配置。"""
        self._confirmed_note = "参数已更新（点 ▶ 运行任务生效）"
        self.update()

    def confirm(self) -> None:
        self._on_confirm()

    # ---- 对外 API（TaskRunner / 壳层调用） ----------------------------------

    @property
    def config(self) -> dict:
        return self._config

    def restore_config(self, config: dict | None) -> None:
        """恢复画布快照中的参数，但只接受当前任务类型已声明的字段。"""
        if not isinstance(config, dict):
            return
        allowed = {field.key for field in FIELD_SCHEMA.get(self.task_kind, ())}
        if self.task_kind == "tolerance":
            allowed.add("params")
        for key, value in config.items():
            if key in allowed:
                self._config[key] = value
        if self._parameters_open:
            self._layout_parameter_capsules()
        self.update()

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def phase(self) -> str:
        return self._phase

    def run_task(self) -> None:
        """用户点击「运行」/ 实时重跑：请求壳层提交任务。"""
        self._rt_timer.stop()
        if self._phase in ("submitting", "running"):
            return
        self.taskRunRequested.emit(self.node_id)

    def set_submitting(self) -> None:
        self._phase = "submitting"
        self._progress = 0.0
        self._stage = "提交任务…"
        self._note = ""
        self.set_stale(False)
        self.update()

    def set_job(self, job_id: str) -> None:
        self._job_id = str(job_id or "")
        self._phase = "running"
        self._stage = "排队中"
        self._summary_metric = "运行中"
        self.update()

    def set_progress(self, progress: float, stage: str) -> None:
        if self._phase != "running":
            return
        self._progress = max(0.0, min(1.0, float(progress or 0.0)))
        if stage:
            self._stage = str(stage)
        self._summary_metric = f"进度 {self._progress:.0%}"
        self.update()

    def set_task_result(self, result: dict) -> None:
        """任务结果到达：按 task_kind 提取摘要并重绘。"""
        self._job_id = ""
        self._phase = "done"
        self._progress = 1.0
        self._curve = None
        self._result_rows = []
        self._history = []
        status = str((result or {}).get("status", "") or "")
        if status and status != "completed":
            self._set_failure(f"任务{status}")
            return
        if self.task_kind == "scan":
            self._ingest_scan(result or {})
        elif self.task_kind == "tolerance":
            self._ingest_tolerance(result or {})
        elif self.task_kind in {"optimize", "physical_inverse", "ml_inverse"}:
            self._ingest_optimize(result or {})
        else:
            metrics = (result or {}).get("metrics") or {}
            self._result_rows = [("状态", "已完成")]
            self._summary_metric = "已完成"
        self.set_stale(False)
        self.update()

    def set_task_failed(self, message: str) -> None:
        self._set_failure(str(message or "任务失败"))

    def _set_failure(self, message: str) -> None:
        self._job_id = ""
        self._phase = "failed"
        self._stage = ""
        self._note = message
        self._summary_metric = "失败"
        self.set_refreshing(False)
        self.update()

    # ---- 结果提取 -----------------------------------------------------------

    def _ingest_scan(self, result: dict) -> None:
        grid = result.get("parameter_grid") or []
        # grid 为"点列表"（line_1d 每点 [x]）→ 取第 0 列作为扫描轴
        xs = np.asarray(
            [point[0] for point in grid if isinstance(point, (list, tuple)) and point],
            dtype=float,
        )
        response_key = {
            "耦合效率": "coupling_efficiency", "RMS 光斑": "rms_spot_radius_um",
            "Strehl": "strehl_estimate_marechal", "边缘功率": "edge_power",
        }.get(str(self._config.get("response", "耦合效率")), "coupling_efficiency")
        values = (result.get("response_values") or {}).get(response_key) or []
        ys = np.asarray(list(values), dtype=float)
        if xs.size and ys.size and xs.size == ys.size:
            self._curve = (xs, ys)
            best = int(np.argmax(ys))
            self._result_rows = [
                ("扫描范围", f"{xs[0]:.3g} → {xs[-1]:.3g} mm"),
                ("最佳半径", f"{xs[best]:.4g} mm"),
                ("最佳 η", f"{ys[best]:.4f}"),
            ]
            self._summary_metric = f"最佳η={ys[best]:.3f}"
        else:
            self._result_rows = [("结果", "无响应数据")]
            self._summary_metric = "无数据"

    def _ingest_tolerance(self, result: dict) -> None:
        metrics = result.get("metrics") or {}
        rows: list[tuple[str, str]] = []
        label_map = (
            ("system_tolerance_mean", "平均 η"),
            ("system_tolerance_std", "标准差 σ"),
            ("system_tolerance_p05", "P5 分位"),
            ("system_tolerance_min", "最差样本"),
            ("system_tolerance_yield", "良率"),
        )
        for key, label in label_map:
            value = metrics.get(key)
            if value is not None:
                rows.append((label, f"{float(value):.4f}"))
        samples = metrics.get("system_tolerance_response_samples")
        if isinstance(samples, (list, tuple)) and len(samples) > 1:
            self._history = [float(v) for v in samples]
        self._result_rows = rows or [("结果", "无统计数据")]
        yield_v = metrics.get("system_tolerance_yield")
        self._summary_metric = f"良率{float(yield_v):.0%}" if yield_v is not None else "已完成"

    def _ingest_optimize(self, result: dict) -> None:
        best_vars = result.get("best_variables") or {}
        best_metrics = result.get("best_metrics") or {}
        eta = best_metrics.get("coupling_efficiency")
        path = self._config.get("param_path", "")
        best_value = best_vars.get(path)
        rows: list[tuple[str, str]] = []
        if best_value is not None:
            rows.append(("最佳半径", f"{float(best_value):.4g} mm"))
        if eta is not None:
            rows.append(("最佳 η", f"{float(eta):.4f}"))
        iterations = result.get("total_iterations")
        if iterations is not None:
            rows.append(("迭代次数", str(int(iterations))))
        rows.append(("评估次数", str(int(result.get("total_evaluations", 0) or 0))))
        history = result.get("history") or []
        merits: list[float] = []
        for item in history:
            if isinstance(item, dict):
                value = item.get("merit")
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    merits.append(float(value))
        if merits:
            self._history = merits
        self._result_rows = rows or [("状态", "已完成")]
        self._summary_metric = f"η={float(eta):.3f}" if eta is not None else "已完成"

    # ---- 脏传播 -------------------------------------------------------------

    def apply_source_change(self, reason: str) -> None:
        """镜头组变更：已有结果的任务节点标「!」（实时模式防抖重跑）。"""
        self.setToolTip(reason)
        if self._phase in ("submitting", "running"):
            return  # 在途任务沿用提交时的快照，完成后自然标脏
        self.set_stale(True, reason)
        if self._realtime and self._phase in ("done", "failed"):
            self._rt_timer.start()

    # ---- 徽标菜单 -----------------------------------------------------------

    def _open_badge_menu(self, pos) -> bool:
        if not (self._stale or self._ignored):
            return False
        view = find_view(self)
        menu = QMenu(view)
        act_now = menu.addAction("重新运行任务（最新镜头组）")
        act_rt = menu.addAction("实时重跑（跟随修改）")
        act_rt.setCheckable(True)
        act_rt.setChecked(self._realtime)
        act_ignore = menu.addAction("忽略此版本")
        chosen = menu.exec(QCursor.pos())
        if chosen is act_now:
            self.run_task()
        elif chosen is act_rt:
            self._realtime = not self._realtime
            if self._realtime and self._stale:
                self._rt_timer.start()
        elif chosen is act_ignore:
            self.set_ignored()
        return True

    # ---- 交互 ---------------------------------------------------------------

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._collapsed
            and self._run_button_rect().contains(event.pos())
            and self._phase not in ("submitting", "running")
        ):
            self.run_task()
            event.accept()
            return
        super().mousePressEvent(event)

    def summary_text(self) -> str:
        if self._phase == "running":
            return f"{self._stage or '运行中'} {self._progress:.0%}"
        if self._phase == "submitting":
            return "提交中…"
        if self._phase == "failed":
            return self._note[:20] or "失败"
        return self._summary_metric

    # ---- 绘制 ---------------------------------------------------------------

    def _paint_content(self, painter, rect: QRectF) -> None:
        painter.setClipRect(rect)
        if self._phase == "running" or self._phase == "submitting":
            self._paint_progress(painter, rect)
        else:
            self._paint_body(painter, rect)
        painter.setClipping(False)

    def _paint_progress(self, painter, rect: QRectF) -> None:
        top = rect.top() + 10.0
        painter.setPen(QColor(C["text"]))
        painter.setFont(_font(12, True))
        stage = self._stage or "计算中"
        painter.drawText(
            QRectF(rect.left(), top, rect.width(), 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{stage} {self._progress:.0%}",
        )
        bar = QRectF(rect.left(), top + 26.0, rect.width(), 8.0)
        track = QColor(C["grid_dot"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(bar, 4.0, 4.0)
        if self._progress > 0.0:
            fill = QRectF(bar.left(), bar.top(), bar.width() * self._progress, bar.height())
            painter.setBrush(QColor(C["badge"]))
            painter.drawRoundedRect(fill, 4.0, 4.0)
        if self._job_id:
            painter.setPen(QColor(C["text_muted"]))
            painter.setFont(_font(10))
            painter.drawText(
                QRectF(rect.left(), bar.bottom() + 8.0, rect.width(), 14.0),
                Qt.AlignmentFlag.AlignLeft,
                f"job {self._job_id[:18]}",
            )

    def _paint_body(self, painter, rect: QRectF) -> None:
        # 任务节点主体只画关键配置摘要；详细编辑通过齿轮展开的参数胶囊完成。
        config_top = rect.top() + 2.0
        painter.setFont(_font(10))
        for index, (label, value) in enumerate(self._config_lines()):
            y = config_top + index * 18.0
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(QRectF(rect.left(), y, rect.width() * 0.38, 16.0), Qt.AlignmentFlag.AlignLeft, label)
            painter.setPen(QColor(C["text"]))
            painter.drawText(
                QRectF(rect.left() + rect.width() * 0.38, y, rect.width() * 0.62, 16.0),
                Qt.AlignmentFlag.AlignRight,
                str(value),
            )

        # 运行按钮
        button = self._run_button_rect()
        running = self._phase in ("submitting", "running")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C["badge_dim"] if running else C["badge"]))
        painter.drawRoundedRect(button, 6.0, 6.0)
        painter.setPen(QColor(C["text_inverse"]))
        painter.setFont(_font(12, True))
        text = "运行中…" if running else ("重新运行" if self._phase == "done" else "运行任务")
        painter.drawText(button, Qt.AlignmentFlag.AlignCenter, text)

        # 反馈行（✓ 已确认 / 错误信息）：画在运行按钮右侧，不与表单重叠
        if self._confirmed_note or self._note:
            painter.setFont(_font(10))
            painter.setPen(QColor("#3F7D44") if self._confirmed_note else QColor("#B00020"))
            feedback_rect = QRectF(
                button.right() + 10.0, button.top(), rect.right() - button.right() - 12.0, button.height()
            )
            painter.drawText(
                feedback_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine,
                (self._confirmed_note or self._note)[:72],
            )

        # 结果区
        result_rect = QRectF(rect.left(), button.bottom() + 8.0, rect.width(), rect.bottom() - button.bottom() - 10.0)
        if result_rect.height() > 40.0:
            if self._curve is not None and result_rect.height() > 90.0:
                self._paint_curve(painter, result_rect)
            elif self._history and result_rect.height() > 90.0:
                self._paint_history(painter, result_rect)
            elif self._result_rows:
                self._paint_rows(painter, result_rect)
            elif self._phase == "idle":
                painter.setPen(QColor(C["text_muted"]))
                painter.setFont(_font(11))
                painter.drawText(result_rect, Qt.AlignmentFlag.AlignCenter, "点击齿轮按分类设置参数，再点 ▶ 运行任务")

    def _config_lines(self) -> list[tuple[str, str]]:
        cfg = self._config
        if self.task_kind == "scan":
            unit = self._parameter_unit(str(cfg.get("param_path", "")))
            second = str(cfg.get("param_path2", "") or "")
            return [
                ("扫描参数", str(cfg.get("param_label", "—"))),
                ("范围 / 点数", f"{cfg.get('start', 0):.3g}–{cfg.get('stop', 0):.3g} {unit} × {cfg.get('points', 0)}"),
                ("扫描模式", str(cfg.get("scan_mode", "一维扫描"))),
                ("响应指标", str(cfg.get("response", "耦合效率"))),
                ("第二变量", str(cfg.get("param_label2") or second or "不启用")),
            ]
        if self.task_kind == "tolerance":
            params = cfg.get("params") or []
            first = params[0] if params else None
            lines = [("容差参数", f"{len(params)} 项 · {cfg.get('candidate', '当前系统')}")]
            if first:
                lines.append(("样本 / 方法", f"{cfg.get('sample_count', 0)} · {cfg.get('sampling', 'LHS')} · {cfg.get('distribution', '正态')}"))
                lines.append(("参数模板", str(cfg.get("template", "优化参数 + 常用装调"))))
                lines.append(("良率阈值", f"η ≥ {cfg.get('threshold_efficiency', 0):.2f}"))
            return lines
        if self.task_kind in {"optimize", "physical_inverse", "ml_inverse"}:
            if self.task_kind == "physical_inverse":
                objective = f"target η={cfg.get('target_efficiency', 0.95):.3f}"
            elif self.task_kind == "ml_inverse":
                model = str(cfg.get("surrogate_model_id", "") or "未选择")
                objective = f"模型 {model[:14]} · η={cfg.get('target_efficiency', 0.95):.3f}"
            else:
                objective = str(cfg.get("objective", "最大化耦合效率"))
            return [
                ("优化变量", str(cfg.get("param_label", "—"))),
                ("变量范围", f"{cfg.get('lower', 0):.3g}–{cfg.get('upper', 0):.3g} {self._parameter_unit(str(cfg.get('param_path', '')))}"),
                ("目标 / 迭代", f"{objective} · ≤{cfg.get('max_iterations', 0)} 次"),
                ("变量筛选", f"{cfg.get('variable_filter', '全部参数')} · {cfg.get('variable_scale', '线性')}"),
                ("实验验证", f"{cfg.get('validation_metric', 'E003 耦合效率')} · {cfg.get('validation_reference', '实验数据')}"),
            ]
        return [("任务", TASK_TITLES.get(self.task_kind, self.title))]

    @staticmethod
    def _parameter_unit(path: str) -> str:
        text = str(path or "")
        if text == "source.wavelength_nm":
            return "nm"
        if "mode_field_diameter" in text:
            return "μm"
        if "tilt_" in text:
            return "°"
        return "mm"

    def _paint_rows(self, painter, rect: QRectF) -> None:
        line_h = 16.0
        painter.setFont(_font(11))
        top = rect.top() + 2.0
        for index, (label, value) in enumerate(self._result_rows):
            y = top + index * line_h
            if y + line_h > rect.bottom():
                break
            painter.setPen(QColor(C["text"]))
            painter.drawText(
                QRectF(rect.left(), y, rect.width() * 0.45, line_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(
                QRectF(rect.left() + rect.width() * 0.45, y, rect.width() * 0.55, line_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                value,
            )

    def _paint_curve(self, painter, rect: QRectF) -> None:
        xs, ys = self._curve
        if xs.size < 2:
            self._paint_rows(painter, rect)
            return
        # 曲线区占上部 70%，摘要行在下部
        curve_rect = QRectF(rect.left(), rect.top() + 2.0, rect.width(), rect.height() * 0.7)
        self._paint_axes(painter, curve_rect)
        x_min, x_max = float(xs.min()), float(xs.max())
        span_x = max(x_max - x_min, 1e-9)
        y_min, y_max = float(ys.min()), float(ys.max())
        pad = max((y_max - y_min) * 0.08, 1e-6)
        y_min, y_max = y_min - pad, y_max + pad
        span_y = max(y_max - y_min, 1e-9)

        def to_px(x: float, y: float) -> QPointF:
            px = curve_rect.left() + 4.0 + (x - x_min) / span_x * (curve_rect.width() - 8.0)
            py = curve_rect.bottom() - 4.0 - (y - y_min) / span_y * (curve_rect.height() - 8.0)
            return QPointF(px, py)

        pts = QPolygonF([to_px(float(x), float(y)) for x, y in zip(xs, ys)])
        pen = QPen(QColor(C["text"]))
        pen.setWidthF(1.8)
        painter.setPen(pen)
        painter.drawPolyline(pts)
        # 最佳点标记
        best = int(np.argmax(ys))
        painter.setBrush(QColor(C["badge"]))
        painter.drawEllipse(to_px(float(xs[best]), float(ys[best])), 3.0, 3.0)
        # 轴标签
        painter.setPen(QColor(C["text_muted"]))
        painter.setFont(_font(9))
        painter.drawText(
            QRectF(curve_rect.left(), curve_rect.bottom() + 1.0, curve_rect.width(), 12.0),
            Qt.AlignmentFlag.AlignLeft,
            f"{x_min:.3g}",
        )
        painter.drawText(
            QRectF(curve_rect.left(), curve_rect.bottom() + 1.0, curve_rect.width(), 12.0),
            Qt.AlignmentFlag.AlignRight,
            f"{x_max:.3g} mm",
        )
        rows_rect = QRectF(rect.left(), curve_rect.bottom() + 14.0, rect.width(), rect.bottom() - curve_rect.bottom() - 14.0)
        if rows_rect.height() > 14.0:
            self._paint_rows(painter, rows_rect)

    def _paint_history(self, painter, rect: QRectF) -> None:
        """tolerance 样本分布 / optimize 收敛历史的迷你折线。"""
        values = np.asarray([v for v in self._history if math.isfinite(v)], dtype=float)
        if values.size < 2:
            self._paint_rows(painter, rect)
            return
        plot_rect = QRectF(rect.left(), rect.top() + 2.0, rect.width(), rect.height() * 0.55)
        self._paint_axes(painter, plot_rect)
        n = values.size
        v_min, v_max = float(values.min()), float(values.max())
        pad = max((v_max - v_min) * 0.08, 1e-6)
        v_min, v_max = v_min - pad, v_max + pad

        def to_px(i: int, v: float) -> QPointF:
            px = plot_rect.left() + 4.0 + i / (n - 1) * (plot_rect.width() - 8.0)
            py = plot_rect.bottom() - 4.0 - (v - v_min) / (v_max - v_min) * (plot_rect.height() - 8.0)
            return QPointF(px, py)

        pts = QPolygonF([to_px(i, float(v)) for i, v in enumerate(values)])
        pen = QPen(QColor(C["text_muted"]))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawPolyline(pts)
        rows_rect = QRectF(rect.left(), plot_rect.bottom() + 6.0, rect.width(), rect.bottom() - plot_rect.bottom() - 6.0)
        if rows_rect.height() > 14.0:
            self._paint_rows(painter, rows_rect)

    def _paint_axes(self, painter, rect: QRectF) -> None:
        pen = QPen(QColor(C["grid_dot"]))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()))
        painter.drawLine(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))


__all__ = ["TASK_CONFIGS", "TASK_TITLES", "TaskNode"]
