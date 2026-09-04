from __future__ import annotations

from uuid import uuid4
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.unit_spinbox import UnitAwareDoubleSpinBox
from frontend_pyside.shared.components.basic import (
    Card,
    CollapsiblePanel,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.components.foundation import FormGrid
from frontend_pyside.shared.display_names import parameter_label
from frontend_pyside.shared.feature_labels import is_adjustable_feature_name
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared import layout_tokens as ui_layout
from frontend_pyside.shared.research_summary import latest_optimization_result, latest_optimization_reference, latest_tolerance_result
from frontend_pyside.shared.settings import SimulationNumericsProfileStore
from frontend_pyside.features.machine_learning.feature_adapter import FeaturePathError, resolve_feature_path
from frontend_pyside.features.optimization.numerics import research_simulation_numerics


_METHOD_MAP = {"LHS": "lhs", "Sobol": "sobol", "随机": "random"}
_DISTRIBUTION_MAP = {"正态": "normal", "均匀": "uniform", "三角": "triangular"}
_TOLERANCE_MIN_SCALE = 1.0e-6


def tolerance_scale_limits(path: str, nominal: float = 0.0) -> tuple[float, float]:
    """Return (min, max) half-range / sigma for a tolerance parameter path."""
    text = str(path).lower()
    nominal_abs = abs(float(nominal))
    if "offset_x" in text or "offset_y" in text:
        return _TOLERANCE_MIN_SCALE, 0.05
    if "axial" in text:
        return _TOLERANCE_MIN_SCALE, 0.5
    if "tilt" in text:
        return 1.0e-6, 2.0
    if "wavelength" in text:
        return 1.0e-4, 10.0
    if "mode_field" in text or "waist" in text:
        return 1.0e-4, max(5.0, nominal_abs * 0.5 if nominal_abs > 0 else 5.0)
    surface = re.fullmatch(r"surfaces?(?:\[(\d+)\]|\.(\d+))\.(.+)", text)
    if surface:
        field = surface.group(3)
        if field == "radius_mm":
            cap = max(0.05, nominal_abs * 0.2) if nominal_abs > 0 else 2.0
            return _TOLERANCE_MIN_SCALE, min(5.0, cap)
        if field in {"distance_to_next_mm", "thickness_mm"}:
            cap = max(0.01, nominal_abs * 0.2) if nominal_abs > 0 else 1.0
            return _TOLERANCE_MIN_SCALE, min(2.0, cap)
    return _TOLERANCE_MIN_SCALE, max(0.01, nominal_abs * 0.2 if nominal_abs > 0 else 1.0)


class OptimizationToleranceMixin:
    """Reusable tolerance task UI for Simulation robustness and candidate checks.

    The backend owns the Monte-Carlo/LHS/Sobol implementation.  Simulation is
    the first-level owner of current-system tolerance analysis; an optimisation
    result may still open the same task explicitly for a verified candidate.
    """

    def _tolerance_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(ui_layout.CARD_GAP)

        top_row = QHBoxLayout()
        back = SecondaryButton("收起容差分析")
        self.tolerance_back_button = back
        back.clicked.connect(lambda: self.inline_tolerance_panel.setVisible(False) if hasattr(self, "inline_tolerance_panel") else self._set_workspace_mode(0))
        top_row.addWidget(back)
        title = QLabel("容差分析")
        self.tolerance_page_title = title
        title.setObjectName("cardTitle")
        top_row.addWidget(title)
        top_row.addStretch(1)
        root.addLayout(top_row)

        setup = Card("分析设置", compact=True)
        self.tolerance_candidate = QComboBox()
        self.tolerance_candidate.addItems(["当前最优候选", "当前系统"])
        self.tolerance_candidate.setToolTip("当前最优候选使用最近一次优化结果；当前系统使用仿真系统中的参数。")
        self.tolerance_template = QComboBox()
        self.tolerance_template.addItems(["优化参数 + 常用装调", "常用装调", "自定义"])
        self.tolerance_samples = QSpinBox()
        self.tolerance_samples.setRange(16, 200000)
        self.tolerance_samples.setValue(256)
        self.tolerance_samples.setSingleStep(16)
        self.tolerance_threshold = UnitAwareDoubleSpinBox()
        self.tolerance_threshold.setRange(0.0, 100.0)
        self.tolerance_threshold.setDecimals(1)
        self.tolerance_threshold.setValue(80.0)
        self.tolerance_threshold.setSuffix(" %")
        setup_form = FormGrid(label_width=ui_layout.FORM_LABEL_WIDTH)
        setup_form.add_row("分析对象", self.tolerance_candidate, "选择最近一次优化候选，或直接检查当前系统")
        setup_form.add_row("参数模板", self.tolerance_template, "默认同时包含研究参数和常见装调误差")
        setup_form.add_row("样本数", self.tolerance_samples, "正式分析建议根据稳定性逐步增加样本")
        setup_form.add_row("效率阈值", self.tolerance_threshold, "用于计算达标概率")
        setup.body.addWidget(setup_form)
        self.tolerance_run_button = PrimaryButton("开始分析")
        self.tolerance_run_button.clicked.connect(self._run_tolerance_analysis)
        setup_actions = QHBoxLayout()
        setup_actions.addStretch(1)
        setup_actions.addWidget(self.tolerance_run_button)
        setup.body.addLayout(setup_actions)
        self.tolerance_source_info = QLabel("")
        self.tolerance_source_info.setObjectName("mutedText")
        self.tolerance_source_info.setWordWrap(True)
        setup.body.addWidget(self.tolerance_source_info)
        self.tolerance_validation_hint = QLabel("")
        self.tolerance_validation_hint.setObjectName("mutedText")
        self.tolerance_validation_hint.setWordWrap(True)
        self.tolerance_validation_hint.setProperty("tone", "warning")
        setup.body.addWidget(self.tolerance_validation_hint)
        root.addWidget(setup)

        self.tolerance_parameter_panel = CollapsiblePanel("容差参数", expanded=False)
        self.tolerance_table = DataTable(0, 7)
        self.tolerance_table.setHorizontalHeaderLabels([
            "启用", "参数", "名义值", "分布", "σ / ±容差", "单位", "路径",
        ])
        self.tolerance_table.stretch_columns(1)
        self.tolerance_table.setColumnHidden(6, True)
        self.tolerance_table.setMinimumHeight(210)
        self.tolerance_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tolerance_parameter_panel.content_layout.addWidget(self.tolerance_table)
        root.addWidget(self.tolerance_parameter_panel)

        advanced = CollapsiblePanel("高级设置", expanded=False)
        advanced_form = QFormLayout()
        self.tolerance_method = QComboBox()
        self.tolerance_method.addItems(list(_METHOD_MAP))
        self.tolerance_deterministic = QCheckBox("同时计算一阶灵敏度估计")
        self.tolerance_deterministic.setChecked(True)
        advanced_form.addRow("采样方法", self.tolerance_method)
        advanced_form.addRow(self.tolerance_deterministic)
        advanced.content_layout.addLayout(advanced_form)
        root.addWidget(advanced)

        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(ui_layout.CONTROL_GAP)

        # 结果遵循“任务状态 → 一张主图 → 关键数字 → 详细诊断”。
        # Long tolerance runs must expose progress where the result will appear,
        # rather than only changing a button or the global task center.
        self.tolerance_progress_panel = QFrame(result_panel)
        self.tolerance_progress_panel.setObjectName("taskProgressPanel")
        tolerance_progress_layout = QVBoxLayout(self.tolerance_progress_panel)
        tolerance_progress_layout.setContentsMargins(10, 7, 10, 8)
        tolerance_progress_layout.setSpacing(5)
        self.tolerance_progress_label = QLabel("准备容差分析", self.tolerance_progress_panel)
        self.tolerance_progress_label.setObjectName("taskProgressLabel")
        self.tolerance_progress = QProgressBar(self.tolerance_progress_panel)
        self.tolerance_progress.setObjectName("taskProgressBar")
        self.tolerance_progress.setRange(0, 100)
        self.tolerance_progress.setValue(0)
        self.tolerance_progress.setTextVisible(True)
        tolerance_progress_layout.addWidget(self.tolerance_progress_label)
        tolerance_progress_layout.addWidget(self.tolerance_progress)
        self.tolerance_progress_panel.hide()
        result_layout.addWidget(self.tolerance_progress_panel)

        self.tolerance_notice = QLabel("")
        self.tolerance_notice.setWordWrap(True)
        self.tolerance_notice.setProperty("tone", "warning")
        self.tolerance_notice.setVisible(False)
        result_layout.addWidget(self.tolerance_notice)

        self.tolerance_result = ResultWorkspace()
        self.tolerance_result.set_single_view_only(True)
        self.tolerance_result.set_toolbar_visible(False)
        self.tolerance_result.set_maximize_controls_visible(False)
        self.tolerance_result.set_plot_tools_visible(False)
        self.tolerance_result.set_footer_visible(False)
        self.tolerance_result.set_result(0, "效率分布", {"kind": "empty", "message": "运行后显示效率分布。"})
        # The plot owns a real chart area; metrics live below it.  The old 300 px
        # minimum plus the ResultPane footer let x-axis text slip underneath the
        # four metric cards at 1366x768.
        self.tolerance_result.setMinimumHeight(390)
        result_layout.addWidget(self.tolerance_result, 1)

        metrics = QHBoxLayout()
        self.tolerance_mean = InlineMetric("平均效率", "—", "%")
        self.tolerance_std = InlineMetric("标准差", "—", "百分点")
        self.tolerance_p05 = InlineMetric("P05", "—", "%")
        self.tolerance_yield = InlineMetric("达标比例", "—", "%")
        for widget in (self.tolerance_mean, self.tolerance_std, self.tolerance_p05, self.tolerance_yield):
            metrics.addWidget(widget, 1)
        # 兼容旧结果更新逻辑；有效样本只放到详细结果中。
        self.tolerance_acceptance = InlineMetric("有效样本", "—", "%")
        self.tolerance_acceptance.hide()
        result_layout.addLayout(metrics)

        detail_panel = CollapsiblePanel("详细结果", expanded=False)
        self.tolerance_status = InfoRow("状态", "等待设置")
        detail_panel.content_layout.addWidget(self.tolerance_status)
        self.tolerance_detail = DataTable(0, 4)
        self.tolerance_detail.setHorizontalHeaderLabels(["参数", "相关系数", "局部导数", "标准差/σ"])
        self.tolerance_detail.stretch_columns(0)
        self.tolerance_detail.setMinimumHeight(150)
        self.tolerance_detail.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_panel.content_layout.addWidget(self.tolerance_detail)
        result_layout.addWidget(detail_panel)
        self.tolerance_result_panel = result_panel
        result_panel.setVisible(False)
        root.addWidget(result_panel, 1)

        self.tolerance_candidate.currentTextChanged.connect(lambda *_: self._tolerance_apply_template())
        self.tolerance_template.currentTextChanged.connect(lambda *_: self._tolerance_apply_template())
        self.tolerance_samples.valueChanged.connect(lambda *_: self._tolerance_refresh_input_state())
        self.tolerance_method.currentTextChanged.connect(lambda *_: self._tolerance_refresh_input_state())
        self._tolerance_table_updating = False
        self._tolerance_apply_template()
        return page

    def _tolerance_apply_template(self) -> None:
        if not hasattr(self, "tolerance_table"):
            return
        template = self.tolerance_template.currentText() if hasattr(self, "tolerance_template") else "优化参数 + 常用装调"
        if template == "自定义":
            self._tolerance_refresh_input_state()
            return
        self._tolerance_table_updating = True
        try:
            self.tolerance_table.setRowCount(0)
            if template == "优化参数 + 常用装调" and self.tolerance_candidate.currentText() == "当前最优候选":
                self._tolerance_sync_from_optimization(silent=True)
            self._tolerance_add_alignment_presets()
            if hasattr(self, "tolerance_status"):
                self._set_info(self.tolerance_status, "状态", f"已准备 {self.tolerance_table.rowCount()} 个参数")
        finally:
            self._tolerance_table_updating = False
        self._tolerance_refresh_input_state()

    def _open_tolerance_from_optimization(self) -> None:
        # 强上下文后续分析原地展开，避免从候选结果跳到完全独立页面。
        # 参数扫描不是“自动优化最优候选”。扫描结果后直接打开容差时，
        # 必须分析当前正式系统；若用户希望分析某个采样点，应先明确
        # 点击“应用此参数”。旧逻辑强制选择“当前最优候选”，容易把旧
        # 优化结果与新扫描结果混在一起。
        self._set_workspace_mode(0)
        if hasattr(self, "inline_tolerance_panel"):
            self.inline_tolerance_panel.setVisible(True)
        source_kind = str(getattr(self, "_active_research_result_kind", ""))
        from_scan = source_kind == "scan"
        if hasattr(self, "tolerance_candidate"):
            self.tolerance_candidate.setCurrentText("当前系统" if from_scan else "当前最优候选")
        if hasattr(self, "tolerance_template"):
            self.tolerance_template.setCurrentText("常用装调" if from_scan else "优化参数 + 常用装调")
        self._tolerance_apply_template()
        if hasattr(self, "tolerance_status"):
            status = (
                "基于当前系统；如需分析图中采样点，请先点击“应用此参数”"
                if from_scan
                else "已使用当前最优候选，可直接开始分析"
            )
            self._set_info(self.tolerance_status, "状态", status)
        if hasattr(self, "tolerance_source_info") and from_scan:
            self.tolerance_source_info.setText(
                "来源：当前正式系统。参数扫描本身不会自动改写当前系统，也不会被当成自动优化结果。"
            )
        self._tolerance_refresh_input_state()
        if hasattr(self, "research_scroll") and hasattr(self, "inline_tolerance_panel"):
            try:
                bar = self.research_scroll.verticalScrollBar()
                target = self.inline_tolerance_panel.mapTo(self.research_scroll.widget(), self.inline_tolerance_panel.rect().topLeft()).y() - 12
                bar.setValue(max(0, target))
            except Exception:
                pass

    def _tolerance_sync_from_optimization(self, _checked=False, *, silent: bool = False) -> None:
        variables = []
        selector = getattr(self, "variable_selector", None)
        if selector is not None:
            variables = list(selector.get_variables() or [])
        if not variables:
            result = latest_optimization_result(self.context.tasks)
            best = dict(result.get("best_variables", {}) or {}) if isinstance(result, dict) else {}
            for path, value in best.items():
                if isinstance(value, (int, float)):
                    variables.append({
                        "path": str(path),
                        "label": parameter_label(path),
                        "unit": self._tolerance_unit_for_path(path),
                        "initial_value": float(value),
                        "lower_bound": float(value),
                        "upper_bound": float(value),
                    })
        if not variables:
            if not silent:
                QMessageBox.information(self, "没有优化参数", "请先在优化设置中选择参数，或先完成一次优化。")
            return

        latest = latest_optimization_result(self.context.tasks)
        best = dict(latest.get("best_variables", {}) or {}) if isinstance(latest, dict) else {}
        self._tolerance_table_updating = True
        try:
            self.tolerance_table.setRowCount(0)
            for item in variables:
                path = str(item.get("path", ""))
                if not path:
                    continue
                nominal = best.get(path, item.get("initial_value", 0.0))
                try:
                    nominal = float(nominal)
                except (TypeError, ValueError):
                    continue
                low = item.get("lower_bound", nominal)
                high = item.get("upper_bound", nominal)
                try:
                    span = abs(float(high) - float(low))
                except (TypeError, ValueError):
                    span = 0.0
                tolerance = max(span * 0.01, abs(nominal) * 0.005, self._tolerance_default_scale(path))
                min_scale, max_scale = tolerance_scale_limits(path, nominal)
                tolerance = min(max(abs(float(tolerance)), min_scale), max_scale)
                self._tolerance_append_row(
                    label=str(item.get("label") or parameter_label(path)),
                    path=path,
                    nominal=nominal,
                    unit=str(item.get("unit") or self._tolerance_unit_for_path(path)),
                    tolerance=tolerance,
                    distribution="正态",
                )
        finally:
            self._tolerance_table_updating = False
        if hasattr(self, "tolerance_status"):
            self._set_info(self.tolerance_status, "状态", f"已同步 {self.tolerance_table.rowCount()} 个优化参数")
        self._tolerance_refresh_input_state()

    def _tolerance_add_alignment_presets(self) -> None:
        presets = [
            ("光纤 X 偏移", "receiver.offset_x_mm", "mm", 0.001),
            ("光纤 Y 偏移", "receiver.offset_y_mm", "mm", 0.001),
            ("光纤轴向位置", "receiver.axial_offset_z_mm", "mm", 0.005),
            ("光纤 X 倾角", "receiver.tilt_x_deg", "deg", 0.01),
            ("光纤 Y 倾角", "receiver.tilt_y_deg", "deg", 0.01),
        ]
        existing = {
            str(self.tolerance_table.item(row, 6).text())
            for row in range(self.tolerance_table.rowCount())
            if self.tolerance_table.item(row, 6)
        }
        added = 0
        for label, path, unit, tolerance in presets:
            if path in existing:
                continue
            nominal = self._tolerance_nominal_for_path(path, 0.0)
            min_scale, max_scale = tolerance_scale_limits(path, nominal)
            preset_tolerance = min(max(abs(float(tolerance)), min_scale), max_scale)
            self._tolerance_append_row(label, path, nominal, unit, preset_tolerance, "正态")
            added += 1
        self._set_info(self.tolerance_status, "状态", f"已添加 {added} 个常用装调参数")
        self._tolerance_refresh_input_state()

    def _tolerance_append_row(
        self,
        label: str,
        path: str,
        nominal: float,
        unit: str,
        tolerance: float,
        distribution: str,
    ) -> None:
        row = self.tolerance_table.rowCount()
        self.tolerance_table.insertRow(row)
        enabled_host = QWidget()
        enabled_layout = QHBoxLayout(enabled_host)
        enabled_layout.setContentsMargins(0, 0, 0, 0)
        enabled_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        enabled = QCheckBox()
        enabled.setChecked(True)
        enabled.setToolTip("启用或停用该容差参数")
        enabled.stateChanged.connect(lambda *_: self._tolerance_refresh_input_state())
        enabled_layout.addWidget(enabled)
        self.tolerance_table.setCellWidget(row, 0, enabled_host)
        self.tolerance_table.setItem(row, 1, QTableWidgetItem(str(label)))

        min_scale, max_scale = tolerance_scale_limits(path, nominal)
        nominal_spin = QDoubleSpinBox()
        nominal_spin.setDecimals(6)
        nominal_spin.setRange(-1.0e6, 1.0e6)
        nominal_spin.setSingleStep(max(min_scale, abs(float(nominal)) * 0.01 if nominal else min_scale))
        nominal_spin.setValue(float(nominal))
        nominal_spin.setToolTip("名义值：随机扰动围绕该值展开")
        nominal_spin.valueChanged.connect(lambda *_: self._tolerance_on_nominal_changed(row))
        self.tolerance_table.setCellWidget(row, 2, nominal_spin)

        combo = QComboBox()
        combo.addItems(list(_DISTRIBUTION_MAP))
        combo.setCurrentText(distribution if distribution in _DISTRIBUTION_MAP else "正态")
        combo.setToolTip("正态=σ；均匀/三角=±半宽")
        combo.currentTextChanged.connect(lambda *_: self._tolerance_refresh_input_state())
        self.tolerance_table.setCellWidget(row, 3, combo)

        scale_spin = QDoubleSpinBox()
        scale_spin.setObjectName("toleranceScaleSpin")
        scale_spin.setDecimals(6)
        scale_spin.setRange(min_scale, max_scale)
        scale_spin.setSingleStep(max(min_scale, abs(float(tolerance)) * 0.1 if tolerance else min_scale * 10.0))
        scale_spin.setValue(min(max(abs(float(tolerance)), min_scale), max_scale))
        scale_spin.setToolTip(f"容差范围：{min_scale:g} – {max_scale:g} {unit or ''}".strip())
        scale_spin.valueChanged.connect(lambda *_: self._tolerance_refresh_input_state())
        self.tolerance_table.setCellWidget(row, 4, scale_spin)

        self.tolerance_table.setItem(row, 5, QTableWidgetItem(str(unit or "")))
        path_item = QTableWidgetItem(str(path))
        path_item.setFlags(path_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.tolerance_table.setItem(row, 6, path_item)
        header = self.tolerance_table.horizontalHeader().height()
        rows_height = sum(self.tolerance_table.rowHeight(i) for i in range(self.tolerance_table.rowCount()))
        content_height = max(120, header + rows_height + 8)
        self.tolerance_table.setMinimumHeight(content_height)
        self.tolerance_table.setMaximumHeight(content_height)

    def _tolerance_row_path(self, row: int) -> str:
        path_item = self.tolerance_table.item(row, 6)
        return str(path_item.text() if path_item else "").strip()

    def _tolerance_row_enabled(self, row: int) -> bool:
        enabled_host = self.tolerance_table.cellWidget(row, 0)
        enabled = enabled_host.findChild(QCheckBox) if enabled_host is not None else None
        return enabled is not None and enabled.isChecked()

    def _tolerance_row_nominal(self, row: int) -> float:
        widget = self.tolerance_table.cellWidget(row, 2)
        if isinstance(widget, QDoubleSpinBox):
            return float(widget.value())
        item = self.tolerance_table.item(row, 2)
        return float(item.text()) if item else 0.0

    def _tolerance_row_scale(self, row: int) -> float:
        widget = self.tolerance_table.cellWidget(row, 4)
        if isinstance(widget, QDoubleSpinBox):
            return float(widget.value())
        item = self.tolerance_table.item(row, 4)
        return float(item.text()) if item else 0.0

    def _tolerance_row_distribution(self, row: int) -> str:
        combo = self.tolerance_table.cellWidget(row, 3)
        if isinstance(combo, QComboBox):
            return _DISTRIBUTION_MAP.get(combo.currentText(), "normal")
        return "normal"

    def _tolerance_on_nominal_changed(self, row: int) -> None:
        if getattr(self, "_tolerance_table_updating", False):
            return
        path = self._tolerance_row_path(row)
        nominal = self._tolerance_row_nominal(row)
        min_scale, max_scale = tolerance_scale_limits(path, nominal)
        scale_spin = self.tolerance_table.cellWidget(row, 4)
        if isinstance(scale_spin, QDoubleSpinBox):
            current = float(scale_spin.value())
            scale_spin.blockSignals(True)
            scale_spin.setRange(min_scale, max_scale)
            scale_spin.setValue(min(max(current, min_scale), max_scale))
            unit_item = self.tolerance_table.item(row, 5)
            unit = str(unit_item.text() if unit_item else "")
            scale_spin.setToolTip(f"容差范围：{min_scale:g} – {max_scale:g} {unit}".strip())
            scale_spin.blockSignals(False)
        self._tolerance_refresh_input_state()

    def _tolerance_path_resolves(self, path: str, payload: dict) -> bool:
        text = str(path).strip()
        if not text:
            return False
        if is_adjustable_feature_name(text):
            if text.startswith("receiver."):
                return isinstance(payload.get("receiver"), dict)
            if text.startswith("source."):
                return isinstance(payload.get("source"), dict)
            surface = re.fullmatch(r"surfaces?(?:\[(\d+)\]|\.(\d+))\.(.+)", text.lower())
            if surface:
                raw_index = surface.group(1) if surface.group(1) is not None else surface.group(2)
                surfaces = payload.get("surfaces") if isinstance(payload, dict) else None
                return isinstance(surfaces, list) and 0 <= int(raw_index) < len(surfaces)
            return True
        try:
            resolve_feature_path(payload, text)
            return True
        except FeaturePathError:
            return False

    def _tolerance_collect_input_issues(self) -> tuple[list[str], list[str]]:
        blocking: list[str] = []
        warnings: list[str] = []
        payload = self._current_research_project_payload()
        if not isinstance(payload, dict) or not list(payload.get("surfaces") or []):
            blocking.append("当前系统缺少光学表面，请先在仿真工作台完成系统设计。")
        receiver = payload.get("receiver") if isinstance(payload, dict) else None
        if not isinstance(receiver, dict) or not receiver:
            blocking.append("当前系统缺少接收端（光纤/探测器），无法做耦合容差分析。")

        if hasattr(self, "tolerance_candidate") and self.tolerance_candidate.currentText() == "当前最优候选":
            if not self._tolerance_optimization_reference():
                blocking.append("未找到与当前系统版本一致的最优候选；请重新优化或切换为「当前系统」。")

        enabled_count = 0
        paths_seen: set[str] = set()
        for row in range(self.tolerance_table.rowCount()):
            if not self._tolerance_row_enabled(row):
                continue
            label_item = self.tolerance_table.item(row, 1)
            label = str(label_item.text() if label_item else f"第 {row + 1} 行")
            path = self._tolerance_row_path(row)
            if not path:
                blocking.append(f"「{label}」缺少参数路径。")
                continue
            if path in paths_seen:
                blocking.append(f"参数路径 {path} 重复，请只保留一行。")
            paths_seen.add(path)
            if not self._tolerance_path_resolves(path, payload):
                blocking.append(f"「{label}」在当前系统中找不到路径 {path}。")
            try:
                nominal = self._tolerance_row_nominal(row)
                scale = abs(self._tolerance_row_scale(row))
            except (TypeError, ValueError):
                blocking.append(f"「{label}」的名义值或容差不是有效数字。")
                continue
            if not (-1.0e12 < nominal < 1.0e12):
                blocking.append(f"「{label}」名义值超出允许范围。")
            min_scale, max_scale = tolerance_scale_limits(path, nominal)
            if scale < min_scale:
                blocking.append(f"「{label}」容差过小（<{min_scale:g}），扰动将低于数值分辨率。")
            elif scale > max_scale:
                blocking.append(f"「{label}」容差过大（>{max_scale:g}），易导致能量/边缘截断失败。")
            distribution = self._tolerance_row_distribution(row)
            if distribution in {"uniform", "triangular"} and scale <= 0.0:
                blocking.append(f"「{label}」均匀/三角分布要求 ±容差 > 0。")
            enabled_count += 1

        if enabled_count == 0:
            blocking.append("请至少勾选一个容差参数。")

        sample_count = int(self.tolerance_samples.value()) if hasattr(self, "tolerance_samples") else 256
        method = _METHOD_MAP.get(self.tolerance_method.currentText(), "lhs") if hasattr(self, "tolerance_method") else "lhs"
        if enabled_count and method == "lhs" and sample_count < enabled_count:
            blocking.append(f"LHS 样本数（{sample_count}）不能少于启用参数数（{enabled_count}）。")
        elif enabled_count and sample_count < max(16, enabled_count * 4):
            warnings.append(f"样本数偏少，建议不少于 {max(16, enabled_count * 4)} 以保证统计稳定。")

        return blocking, warnings

    def _tolerance_refresh_input_state(self) -> None:
        if getattr(self, "_tolerance_table_updating", False):
            return
        if not hasattr(self, "tolerance_run_button"):
            return
        blocking, warnings = self._tolerance_collect_input_issues()
        hint = ""
        if blocking:
            hint = "；".join(blocking[:3])
            if len(blocking) > 3:
                hint += f"；另有 {len(blocking) - 3} 项问题"
        elif warnings:
            hint = "；".join(warnings[:2])
        if hasattr(self, "tolerance_validation_hint"):
            self.tolerance_validation_hint.setText(hint)
            self.tolerance_validation_hint.setVisible(bool(hint))
        running = self.tolerance_run_button.property("taskState") in {"running", "submitted"}
        if not running:
            self.tolerance_run_button.setEnabled(not blocking)
            if blocking:
                self.tolerance_run_button.setToolTip(hint)
            else:
                self.tolerance_run_button.setToolTip("检查名义参数质量后运行 Monte Carlo / LHS 容差传播")

    def _tolerance_parameters(self) -> list[dict]:
        parameters: list[dict] = []
        for row in range(self.tolerance_table.rowCount()):
            if not self._tolerance_row_enabled(row):
                continue
            nominal = self._tolerance_row_nominal(row)
            scale = abs(self._tolerance_row_scale(row))
            path_item = self.tolerance_table.item(row, 6)
            unit_item = self.tolerance_table.item(row, 5)
            path = str(path_item.text() if path_item else "").strip()
            unit = str(unit_item.text() if unit_item else "").strip()
            if not path:
                raise ValueError(f"第 {row + 1} 行缺少参数路径")
            distribution_name = self._tolerance_row_distribution(row)
            if distribution_name == "normal":
                distribution = {"name": "normal", "sigma": scale}
            elif distribution_name == "uniform":
                distribution = {"name": "uniform", "lower": nominal - scale, "upper": nominal + scale}
            else:
                distribution = {"name": "triangular", "lower": nominal - scale, "upper": nominal + scale, "mode": nominal}
            parameters.append({
                "path": path,
                "nominal": nominal,
                "unit": unit,
                "distribution": distribution,
                "enabled": True,
                "group": "optimization_tolerance",
            })
        return parameters

    def _tolerance_optimization_reference(self) -> dict:
        if not hasattr(self, "tolerance_candidate") or self.tolerance_candidate.currentText() != "当前最优候选":
            return {}
        reference = latest_optimization_reference(self.context.tasks, self.context.project)
        if not reference:
            return {}
        reference_revision = str(reference.get("project_revision", "") or "")
        current_revision = str(getattr(self.context.project, "design_revision", "") or getattr(self.context.project, "revision", "") or "")
        if reference_revision and current_revision and reference_revision != current_revision:
            # Do not silently combine an old optimum with a newly revised base
            # design.  The user can re-run optimisation or analyse 当前系统.
            return {}
        return reference

    def _tolerance_nominal_changes(self) -> list[dict]:
        reference = self._tolerance_optimization_reference()
        if not reference:
            return []
        best = dict(reference.get("best_variables", {}) or {})
        changes = []
        for path, value in best.items():
            if not isinstance(value, (int, float)):
                continue
            changes.append({"path": str(path), "value": float(value), "unit": self._tolerance_unit_for_path(path) or None})
        return changes

    def _run_tolerance_analysis(self) -> bool:
        blocking, warnings = self._tolerance_collect_input_issues()
        if blocking:
            QMessageBox.warning(self, "容差设置未通过检查", "\n".join(blocking))
            self._tolerance_refresh_input_state()
            return False
        if warnings and hasattr(self, "tolerance_validation_hint"):
            self.tolerance_validation_hint.setText("；".join(warnings))
            self.tolerance_validation_hint.setVisible(True)
        try:
            parameters = self._tolerance_parameters()
        except ValueError as exc:
            QMessageBox.warning(self, "容差参数无效", str(exc))
            return False
        if not parameters:
            QMessageBox.information(self, "没有容差参数", "请先同步优化参数或添加装调误差，并至少勾选一个参数。")
            return False
        reference = self._tolerance_optimization_reference()
        if self.tolerance_candidate.currentText() == "当前最优候选" and not reference:
            QMessageBox.information(self, "没有可用最优候选", "没有找到与当前系统版本一致的自动优化结果。请重新运行优化，或切换为“当前系统”后再进行容差分析。")
            self.tolerance_run_button.setEnabled(True)
            return False
        sample_count = int(self.tolerance_samples.value())
        method = _METHOD_MAP.get(self.tolerance_method.currentText(), "lhs")
        threshold = float(self.tolerance_threshold.value()) / 100.0
        profile = SimulationNumericsProfileStore().load()
        precision, simulation_options = research_simulation_numerics(profile)
        payload = {
            "request_id": f"tol-{uuid4().hex[:10]}",
            "project": self._current_research_project_payload(),
            "analyses": ["coupling"],
            "parameter_changes": self._tolerance_nominal_changes(),
            "precision": precision,
            "random_seed": 42,
            "options": simulation_options,
            "tolerance_parameters": parameters,
            "tolerance_sampling_method": method,
            "tolerance_sample_count": sample_count,
            "tolerance_threshold_efficiency": threshold,
            "tolerance_threshold_loss_db": None,
            "tolerance_confidence_level": 0.95,
            "tolerance_options": {
                "response_metric": "coupling_efficiency",
                "include_deterministic_budget": bool(self.tolerance_deterministic.isChecked()),
                "require_converged": False,
                "reject_energy_failure": True,
                "reject_edge_failure": True,
                "reject_nyquist_failure": True,
                "provenance": reference or {
                    "source": "当前系统",
                    "project_revision": str(getattr(self.context.project, "design_revision", "") or getattr(self.context.project, "revision", "") or ""),
                    "best_variables": {},
                },
            },
        }
        try:
            self.tolerance_client.submit("optimization.tolerance.submit", payload)
        except Exception as exc:
            self._set_info(self.tolerance_status, "状态", f"提交失败：{exc}")
            if hasattr(self.tolerance_run_button, "set_task_state"):
                self.tolerance_run_button.set_task_state("error", "提交失败")
                QTimer.singleShot(1400, lambda: self.tolerance_run_button.reset_task_state("开始分析"))
            return False
        if hasattr(self.tolerance_run_button, "set_task_state"):
            self.tolerance_run_button.set_task_state("submitted", "分析已提交")
        else:
            self.tolerance_run_button.setEnabled(False)
        if hasattr(self, "tolerance_result_panel"):
            self.tolerance_result_panel.setVisible(True)
        if hasattr(self, "_sync_task_content_height"):
            self._sync_task_content_height()
            QTimer.singleShot(0, self._sync_task_content_height)
        if hasattr(self, "tolerance_progress_panel"):
            self.tolerance_progress_panel.setVisible(True)
            self.tolerance_progress_label.setText("任务已提交 · 等待后端开始容差分析")
            self.tolerance_progress.setRange(0, 0)
            self.tolerance_progress.setTextVisible(False)
        self.tolerance_notice.setText("正在检查名义参数的能量、边缘截断与 Nyquist 采样；通过后才会运行随机容差样本。")
        self.tolerance_notice.setVisible(True)
        self._set_info(self.tolerance_status, "状态", "正在进行名义参数质量预检；通过后才会运行容差样本")
        if hasattr(self, "tolerance_source_info"):
            src = reference.get("source", "当前系统") if reference else "当前系统"
            rev = reference.get("project_revision", "") if reference else str(getattr(self.context.project, "design_revision", "") or "")
            self.tolerance_source_info.setText(f"分析来源：{src}" + (f" · 系统版本 {rev}" if rev else ""))
        return True

    def _render_tolerance_result(self, result: dict) -> None:
        if hasattr(self, "tolerance_result_panel"):
            self.tolerance_result_panel.setVisible(True)
        if hasattr(self, "_sync_task_content_height"):
            self._sync_task_content_height()
            QTimer.singleShot(0, self._sync_task_content_height)
        metrics = dict(result.get("metrics", {}) or {})
        arrays = dict(result.get("arrays", {}) or {})
        mean = metrics.get("system_tolerance_mean")
        std = metrics.get("system_tolerance_std")
        p05 = metrics.get("system_tolerance_p05")
        yield_value = metrics.get("system_tolerance_yield")
        acceptance = metrics.get("system_tolerance_acceptance_ratio")
        self.tolerance_mean.set_value(self._percent_text(mean), "%")
        self.tolerance_std.set_value(self._percentage_point_text(std), "百分点")
        self.tolerance_p05.set_value(self._percent_text(p05), "%")
        self.tolerance_yield.set_value(self._percent_text(yield_value), "%")
        self.tolerance_acceptance.set_value(self._percent_text(acceptance), "%")

        values = [float(v) for v in list(arrays.get("system_tolerance_response_samples", []) or []) if isinstance(v, (int, float))]
        notices = [str(item) for item in list(result.get("warnings", []) or []) if str(item).strip()]
        if values:
            response_span = max(values) - min(values)
            response_scale = max(max(abs(v) for v in values), 1.0e-15)
            if response_span <= max(1.0e-14, response_scale * 1.0e-10):
                notices.append(
                    "当前容差样本的输出几乎没有变化。它可能表示该工况对所选参数确实不敏感，也可能表示容差量级小于当前空间采样/数值分辨能力；建议增大测试容差或提高精度后复核，不要把“0 波动”直接解释为绝对无不确定度。"
                )
        deterministic_sigma = metrics.get("system_tolerance_linear_rss_response_sigma")
        if isinstance(std, (int, float)) and isinstance(deterministic_sigma, (int, float)):
            mc_sigma = abs(float(std))
            linear_sigma = abs(float(deterministic_sigma))
            if mc_sigma > 1.0e-12 and linear_sigma <= max(1.0e-14, mc_sigma * 0.05):
                notices.append(
                    "一阶确定性容差预算明显小于随机传播结果。名义点可能位于对称点或驻点附近，此时一阶导数会低估二阶敏感性；鲁棒性判断应优先采用 Monte Carlo/LHS/Sobol 的标准差、P05 和合格率。"
                )
        if notices:
            self.tolerance_notice.setText("；".join(dict.fromkeys(notices)))
            self.tolerance_notice.setVisible(True)
        else:
            self.tolerance_notice.clear()
            self.tolerance_notice.setVisible(False)
        if values:
            percent_values = [v * 100.0 if abs(v) <= 1.000001 else v for v in values]
            mean_percent = (float(mean) * 100.0 if isinstance(mean, (int, float)) and abs(float(mean)) <= 1.000001 else mean)
            p05_percent = (float(p05) * 100.0 if isinstance(p05, (int, float)) and abs(float(p05)) <= 1.000001 else p05)
            self.tolerance_result.set_result(0, "效率分布", {
                "kind": "histogram",
                "values": percent_values,
                "title": "",
                "x_label": "模式耦合效率 / %",
                "y_label": "样本数",
                "mean": mean_percent,
                "p05": p05_percent,
                "threshold": float(self.tolerance_threshold.value()),
                "source": "正式容差分析",
            })
            self.tolerance_result.select_result(0)
        else:
            self.tolerance_result.set_result(0, "效率分布", {"kind": "empty", "message": "没有通过质量检查的容差样本。"})

        paths = list(arrays.get("system_tolerance_parameter_paths", []) or [])
        correlations = list(arrays.get("system_tolerance_parameter_response_correlations", []) or [])
        det_paths = list(arrays.get("system_tolerance_deterministic_parameter_paths", []) or [])
        derivatives = list(arrays.get("system_tolerance_local_derivatives", []) or [])
        sigmas = list(arrays.get("system_tolerance_parameter_standard_deviations", []) or [])
        derivative_by_path = {str(p): derivatives[i] for i, p in enumerate(det_paths) if i < len(derivatives)}
        sigma_by_path = {str(p): sigmas[i] for i, p in enumerate(det_paths) if i < len(sigmas)}
        rows = []
        for index, path in enumerate(paths):
            corr = correlations[index] if index < len(correlations) else None
            rows.append((str(path), corr, derivative_by_path.get(str(path)), sigma_by_path.get(str(path))))
        if not rows and det_paths:
            rows = [(str(path), None, derivative_by_path.get(str(path)), sigma_by_path.get(str(path))) for path in det_paths]
        self.tolerance_detail.setRowCount(len(rows))
        detail_header = self.tolerance_detail.horizontalHeader().height()
        detail_rows_height = sum(self.tolerance_detail.rowHeight(i) for i in range(len(rows)))
        detail_height = max(120, detail_header + detail_rows_height + 8)
        self.tolerance_detail.setMinimumHeight(detail_height)
        self.tolerance_detail.setMaximumHeight(detail_height)
        for row_index, (path, corr, derivative, sigma) in enumerate(rows):
            values_row = [
                parameter_label(path),
                "—" if corr is None else f"{float(corr):+.4f}",
                "—" if derivative is None else f"{float(derivative):.5g}",
                "—" if sigma is None else f"{float(sigma):.5g}",
            ]
            for column, value in enumerate(values_row):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.tolerance_detail.setItem(row_index, column, item)
        self._latest_tolerance_result = dict(result or {})
        if hasattr(self, "auto_tolerance_text"):
            mean_text = self._percent_text(mean)
            std_text = self._percentage_point_text(std)
            p05_text = self._percent_text(p05)
            yield_text = self._percent_text(yield_value)
            self.auto_tolerance_text.setText(
                "当前候选容差分析\n"
                f"平均耦合效率：{mean_text}%\n"
                f"输入参数传播标准不确定度：{std_text} 个百分点\n"
                f"P05：{p05_text}%\n"
                f"合格率：{yield_text}%\n"
                "建议同时关注名义最优值与 P05/合格率，避免采用对装调误差过于敏感的候选结果。"
            )
        if hasattr(self, "tolerance_progress_panel"):
            self.tolerance_progress_panel.setVisible(True)
            self.tolerance_progress_label.setText("容差分析完成")
            self.tolerance_progress.setRange(0, 100)
            self.tolerance_progress.setValue(100)
            self.tolerance_progress.setFormat("已完成 · 100%")
            self.tolerance_progress.setTextVisible(True)
        if hasattr(self.tolerance_run_button, "set_task_state"):
            self.tolerance_run_button.set_task_state("success", "分析完成")
            QTimer.singleShot(1400, lambda: self.tolerance_run_button.reset_task_state("开始分析"))
        else:
            self.tolerance_run_button.setEnabled(True)
        # A finished tolerance task should land on the result, not leave the user
        # staring at the setup rows while the chart is only half visible below the
        # fold.  The page still has one vertical scroll owner, so this does not
        # introduce nested scrolling or hide the settings permanently.
        scroll = getattr(self, "research_scroll", None)
        panel = getattr(self, "tolerance_result_panel", None)
        if scroll is not None and panel is not None:
            QTimer.singleShot(0, lambda s=scroll, p=panel: s.ensureWidgetVisible(p, 12, 16))
        accepted = int(metrics.get("system_tolerance_accepted_sample_count", 0) or 0)
        requested = int(metrics.get("system_tolerance_requested_sample_count", 0) or 0)
        attempted = int(metrics.get("system_tolerance_attempted_sample_count", requested) or 0)
        rejected = int(metrics.get("system_tolerance_rejected_sample_count", max(0, attempted - accepted)) or 0)
        energy = int(metrics.get("system_tolerance_energy_failure_count", 0) or 0)
        edge = int(metrics.get("system_tolerance_edge_failure_count", 0) or 0)
        nyquist = int(metrics.get("system_tolerance_nyquist_failure_count", 0) or 0)
        backend = int(metrics.get("system_tolerance_backend_failure_count", 0) or 0)
        preflight_pass = metrics.get("system_tolerance_preflight_pass", True)
        if str(result.get("status", "")) == "failed" or not accepted:
            if not preflight_pass:
                advice = "名义参数本身未通过正式仿真质量检查；请先处理数值采样/窗口或当前系统，再进行随机传播。"
            elif nyquist:
                advice = "主要失败来自 Nyquist 采样检查；建议提高空间采样或检查焦区窗口。"
            elif edge:
                advice = "主要失败来自边缘截断；建议扩大计算窗口。"
            elif energy:
                advice = "主要失败来自能量检查；建议检查传播设置和数值收敛。"
            else:
                advice = "请查看任务日志中的后端异常或无效响应指标。"
            self.tolerance_notice.setText(
                f"容差分析未得到有效结果。请求 {requested}，实际运行 {attempted}，有效 {accepted}，拒绝 {rejected}。"
                f" 能量失败 {energy}，边缘失败 {edge}，Nyquist 失败 {nyquist}，后端/指标异常 {backend}。{advice}"
            )
            self.tolerance_notice.setVisible(True)
            self._set_info(self.tolerance_status, "状态", "分析失败 · 已显示拒绝原因")
        else:
            self._set_info(self.tolerance_status, "状态", f"已完成 · 有效 {accepted}/{requested} 个样本")

    def _latest_input_uncertainty(self) -> float | None:
        result = dict(getattr(self, "_latest_tolerance_result", {}) or {})
        if not result:
            result = latest_tolerance_result(self.context.tasks)
        metrics = dict(result.get("metrics", {}) or {}) if isinstance(result, dict) else {}
        value = metrics.get("system_tolerance_std")
        if not isinstance(value, (int, float)):
            return None
        return float(value) * 100.0 if abs(float(value)) <= 1.000001 else float(value)

    @staticmethod
    def _percent_text(value) -> str:
        if not isinstance(value, (int, float)):
            return "—"
        value = float(value)
        return f"{(value * 100.0 if abs(value) <= 1.000001 else value):.3f}"

    @staticmethod
    def _percentage_point_text(value) -> str:
        if not isinstance(value, (int, float)):
            return "—"
        value = float(value)
        return f"{(value * 100.0 if abs(value) <= 1.000001 else value):.4g}"

    def _tolerance_nominal_for_path(self, path: str, fallback: float = 0.0) -> float:
        if hasattr(self, "tolerance_candidate") and self.tolerance_candidate.currentText() == "当前最优候选":
            reference = self._tolerance_optimization_reference()
            best = dict(reference.get("best_variables", {}) or {}) if reference else {}
            value = best.get(str(path))
            if isinstance(value, (int, float)):
                return float(value)
        data = self._current_research_project_payload()
        current = data
        try:
            parts: list[str | int] = []
            for name, index in re.findall(r"([^\.\[\]]+)|\[(\d+)\]", str(path)):
                parts.append(int(index) if index else name)
            for part in parts:
                current = current[part]
            if isinstance(current, (int, float)):
                return float(current)
        except (IndexError, KeyError, TypeError, ValueError):
            pass
        return float(fallback)

    @staticmethod
    def _tolerance_unit_for_path(path: str) -> str:
        text = str(path)
        if text.endswith("_nm") or "wavelength" in text:
            return "nm"
        if text.endswith("_um") or "diameter" in text:
            return "μm"
        if text.endswith("_deg") or "tilt" in text:
            return "deg"
        if text.endswith("_mm") or "surfaces[" in text:
            return "mm"
        return ""

    @staticmethod
    def _tolerance_default_scale(path: str) -> float:
        text = str(path)
        if "tilt" in text:
            return 0.005
        if "offset_x" in text or "offset_y" in text:
            return 0.0005
        if "axial" in text:
            return 0.002
        if "wavelength" in text:
            return 0.05
        if "mode_field" in text:
            return 0.01
        return 1.0e-4
