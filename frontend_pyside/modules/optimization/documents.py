"""Optimization document tabs.

The shell owns navigation and orchestration; this module owns the optimization document surfaces.
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared
from .goal import OptimizationGoalInspector

# Shared Qt imports and helper functions remain in the neutral tab-shared
# module during this compatibility-preserving extraction.
globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

class QSpinBoxCompat(QDoubleSpinBox):
    """Integer-looking control without adding another dependency to the shell."""

    def __init__(self, value: int, minimum: int, maximum: int, parent=None) -> None:
        super().__init__(parent)
        self.setDecimals(0)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setRange(minimum, maximum)
        self.setValue(value)


def _optimization_card(title: str, parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame(parent)
    card.setObjectName("optimizationCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(10)
    heading = QLabel(title)
    heading.setObjectName("optimizationStepTitle")
    layout.addWidget(heading)
    return card, layout


def _refresh_widget_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class OptimizationDocument(QWidget):
    startRequested = Signal()
    scanRequested = Signal()
    applyAndVerifyRequested = Signal(object, str, object)

    def __init__(
        self,
        kind: str,
        context,
        selected: set[str],
        parent=None,
        *,
        goal=None,
        max_evaluations=None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.context = context
        self.selected = selected
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        if kind == "scan":
            settings, settings_layout = _field_group("设置")
            self.mode = QComboBox()
            self.mode.addItems(list(SCAN_MODE_CHOICES))
            self.response = QComboBox()
            self.response.addItems(list(SCAN_RESPONSE_CHOICES))
            self.scale = QComboBox()
            self.scale.addItems(list(SCAN_SCALE_CHOICES))
            self.points = _spin(5, 401, 0, "", 21)
            self.scan_summary = QLabel("（未勾选）")
            self.range_table = QTableWidget(0, 3)
            self.range_table.setHorizontalHeaderLabels(["参数", "最小", "最大"])
            _stretch_table(self.range_table)
            settings_layout.addLayout(
                _field_grid(
                    [
                        _labeled_field("模式", self.mode),
                        _labeled_field("响应量", self.response),
                        _labeled_field("采样尺度", self.scale),
                        _labeled_field("采样点数", self.points),
                        _labeled_field("变量", self.scan_summary),
                    ],
                    columns=2,
                )
            )
            settings_layout.addWidget(self.range_table)
            self.run_button = _primary_button("运行")
            self.run_button.clicked.connect(self.scanRequested.emit)
            settings_layout.addWidget(self.run_button, 0, Qt.AlignmentFlag.AlignLeft)
            self.scan_progress_host = QWidget()
            scan_progress_layout = QHBoxLayout(self.scan_progress_host)
            scan_progress_layout.setContentsMargins(0, 2, 0, 2)
            scan_progress_layout.setSpacing(8)
            self.scan_progress_label = QLabel("扫描尚未开始")
            self.scan_progress_label.setObjectName("scanProgressText")
            self.scan_progress_label.setMinimumWidth(128)
            self.scan_progress = QProgressBar()
            self.scan_progress.setObjectName("scanProgressBar")
            self.scan_progress.setRange(0, 100)
            self.scan_progress.setValue(0)
            self.scan_progress.setTextVisible(False)
            scan_progress_layout.addWidget(self.scan_progress_label)
            scan_progress_layout.addWidget(self.scan_progress, 1)
            self.scan_progress_host.setVisible(False)
            settings_layout.addWidget(self.scan_progress_host)
            root.addWidget(settings)
            self.workspace = LazyResultWorkspace(self)
            self.workspace.set_single_view_only(True)
            self.workspace.set_toolbar_visible(False)
            self.workspace.set_pane_header_visible(False)
            root.addWidget(self.workspace, 1)
            self.workspace.set_result(0, "响应曲线", {"kind": "empty", "message": "勾选 1～2 个变量并运行后，这里显示响应曲线。"})
            self._fill_scan()
        elif kind == "opt_vars":
            shared_advanced_controls = goal is not None and max_evaluations is not None
            self.goal = goal or OptimizationGoalInspector(self.context)

            title = QLabel("优化")
            title.setObjectName("optimizationPageTitle")
            # subtitle = QLabel("在当前镜头结构基础上，自动调整选定参数，使目标指标变得更好。")
            # subtitle.setObjectName("optimizationPageSubtitle")
            # subtitle.setWordWrap(True)
            root.addWidget(title)
            # root.addWidget(subtitle)

            method_card, method_layout = _optimization_card("1. 优化方式")
            method_options = QHBoxLayout()
            method_options.setContentsMargins(0, 0, 0, 0)
            method_options.setSpacing(10)
            self.formal_option = QRadioButton("当前仿真（推荐）")
            self.formal_option.setObjectName("optimizationModeRadio")
            self.formal_option.setChecked(True)
            self.formal_option.setToolTip("直接调用当前光学仿真，准确但可能需要更长时间。")
            self.surrogate_option = QRadioButton("训练模型辅助")
            self.surrogate_option.setObjectName("optimizationModeRadio")
            self.surrogate_option.setToolTip("使用已训练模型加速候选方案搜索，最后仍会进行正式仿真验证。")
            self.mode_group = QButtonGroup(self)
            self.mode_group.setExclusive(True)
            self.mode_group.addButton(self.formal_option)
            self.mode_group.addButton(self.surrogate_option)
            self._formal_mode_card = QFrame()
            self._formal_mode_card.setObjectName("optimizationModeOption")
            formal_layout = QVBoxLayout(self._formal_mode_card)
            formal_layout.setContentsMargins(14, 10, 14, 10)
            formal_layout.setSpacing(3)
            formal_layout.addWidget(self.formal_option)
            formal_hint = QLabel("基于当前镜头和仿真设置直接搜索。")
            formal_hint.setObjectName("optimizationModeHint")
            formal_layout.addWidget(formal_hint)
            self._surrogate_mode_card = QFrame()
            self._surrogate_mode_card.setObjectName("optimizationModeOption")
            surrogate_layout = QVBoxLayout(self._surrogate_mode_card)
            surrogate_layout.setContentsMargins(14, 10, 14, 10)
            surrogate_layout.setSpacing(3)
            surrogate_layout.addWidget(self.surrogate_option)
            surrogate_hint = QLabel("基于已训练的模型快速筛选候选方案。")
            surrogate_hint.setObjectName("optimizationModeHint")
            surrogate_layout.addWidget(surrogate_hint)
            method_options.addWidget(self._formal_mode_card, 1)
            method_options.addWidget(self._surrogate_mode_card, 1)
            method_layout.addLayout(method_options)
            self.model_selector = QComboBox()
            self.model_selector.setPlaceholderText("请先在模型页训练")
            self.model_selector.setToolTip("选择用于候选筛选的训练模型，最终结果仍以正式仿真为准。")
            self.model_selector_row = _labeled_field("训练模型", self.model_selector)
            self.model_selector_row.setVisible(False)
            method_layout.addWidget(self.model_selector_row)
            # method_helper = QLabel("没有训练模型也可以直接优化。")
            # method_helper.setObjectName("optimizationHelperText")
            # method_layout.addWidget(method_helper)
            root.addWidget(method_card)

            objective_card, objective_layout = _optimization_card("2. 优化目标")
            objective_row = QHBoxLayout()
            objective_row.setContentsMargins(0, 0, 0, 0)
            objective_row.setSpacing(12)
            self.objective_selector = QComboBox()
            self.objective_selector.addItem("提高耦合效率", "最大化耦合效率")
            self.objective_selector.addItem("减小 RMS 光斑", "最小化 RMS 光斑")
            self.objective_selector.setToolTip("选择优化完成后希望变好的指标。")
            objective_row.addWidget(self.objective_selector, 2)
            divider = QFrame()
            divider.setObjectName("optimizationMetricDivider")
            divider.setFixedWidth(1)
            objective_row.addWidget(divider)
            metric_card = QFrame()
            metric_card.setObjectName("optimizationMetricCard")
            metric_layout = QVBoxLayout(metric_card)
            metric_layout.setContentsMargins(16, 8, 16, 8)
            metric_layout.setSpacing(0)
            metric_title = QLabel("当前值")
            metric_title.setObjectName("optimizationMetricTitle")
            self.current_metric = QLabel("—")
            self.current_metric.setObjectName("optimizationMetricValue")
            metric_layout.addWidget(metric_title)
            metric_layout.addWidget(self.current_metric)
            objective_row.addWidget(metric_card, 0)
            self.secondary_objective = QCheckBox("同时减小 RMS 光斑")
            self.secondary_objective.setObjectName("optimizationSecondaryObjective")
            self.secondary_objective.setToolTip("启用后使用耦合效率和 RMS 光斑的加权目标。")
            # The metric card has two stacked labels while the checkbox has one
            # line, so let both controls share the larger natural height.
            objective_control_height = max(
                metric_card.sizeHint().height(),
                self.secondary_objective.sizeHint().height(),
            )
            metric_card.setFixedHeight(objective_control_height)
            self.secondary_objective.setFixedHeight(objective_control_height)
            objective_row.addWidget(self.secondary_objective, 1)
            objective_layout.addLayout(objective_row)
            root.addWidget(objective_card)

            parameter_card, parameter_layout = _optimization_card("3. 参数范围")
            self.table = QTableWidget(0, 4)
            self.table.setObjectName("optimizationParameterTable")
            self.table.setHorizontalHeaderLabels(["参数", "当前值", "最小值", "最大值"])
            self.table.setMinimumHeight(128)
            self.table.setAlternatingRowColors(True)
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            _stretch_table(self.table)
            parameter_layout.addWidget(self.table, 1)
            self.more_button = None
            if not shared_advanced_controls:
                self.more_button = QToolButton()
                self.more_button.setObjectName("optimizationMoreButton")
                self.more_button.setText("更多参数")
                self.more_button.setCheckable(True)
                self.more_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                self.more_button.toggled.connect(self._toggle_advanced_options)
                parameter_layout.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignLeft)
            root.addWidget(parameter_card, 1)

            self.max_evaluations = max_evaluations or _spin(10, 100000, 0, "", 300)
            self.advanced_panel = None
            if not shared_advanced_controls:
                advanced_panel = QFrame()
                advanced_panel.setObjectName("optimizationAdvancedPanel")
                advanced_layout = QVBoxLayout(advanced_panel)
                advanced_layout.setContentsMargins(12, 10, 12, 10)
                advanced_layout.setSpacing(8)
                advanced_layout.addWidget(self.goal)
                advanced_layout.addWidget(_labeled_field("最大评价次数", self.max_evaluations))
                advanced_panel.setVisible(False)
                self.advanced_panel = advanced_panel
                root.addWidget(advanced_panel)

            self.start_button = _primary_button("开始优化")
            self.start_button.clicked.connect(self.startRequested.emit)
            self.start_button.setEnabled(bool(self.selected))
            self.start_button.setToolTip("" if self.selected else "请先在左栏勾选优化变量。")
            # self.help_button = QPushButton("查看说明")
            # self.help_button.setProperty("kind", "secondary")
            # self.help_button.clicked.connect(self._show_optimization_help)
            footer = QWidget()
            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(0, 0, 0, 0)
            footer_layout.setSpacing(10)
            # footer_hint = QLabel("完成后可查看方案对比并正式验证。")
            # footer_hint.setObjectName("optimizationFooterHint")
            # footer_layout.addWidget(footer_hint)
            footer_layout.addStretch(1)
            # footer_layout.addWidget(self.help_button)
            footer_layout.addWidget(self.start_button)
            root.addWidget(footer)
            self.formal_option.toggled.connect(self._sync_beginner_controls)
            self.surrogate_option.toggled.connect(self._sync_beginner_controls)
            self.model_selector.currentIndexChanged.connect(self._sync_selected_model)
            self.objective_selector.currentIndexChanged.connect(self._primary_objective_changed)
            self.secondary_objective.toggled.connect(self._sync_secondary_objective)
            self.goal.goal.currentTextChanged.connect(self._sync_simple_objective_from_goal)
            self._sync_beginner_controls()
            self._load_simple_objective_from_goal()
            self._sync_objective()
            self._refresh_baseline_metric()
            formal_signal = getattr(getattr(self.context, "project", None), "formal_result_changed", None)
            if formal_signal is not None and hasattr(formal_signal, "connect"):
                formal_signal.connect(self._refresh_baseline_metric)
            self._rebuild_table()
        elif kind == "opt_progress":
            self.opt_progress_host = QWidget()
            opt_progress_layout = QHBoxLayout(self.opt_progress_host)
            opt_progress_layout.setContentsMargins(0, 2, 0, 2)
            opt_progress_layout.setSpacing(8)
            self.opt_progress_label = QLabel("优化尚未开始")
            self.opt_progress_label.setObjectName("optimizationProgressText")
            self.opt_progress_label.setMinimumWidth(128)
            self.opt_progress = QProgressBar()
            self.opt_progress.setObjectName("optimizationProgressBar")
            self.opt_progress.setRange(0, 100)
            self.opt_progress.setValue(0)
            self.opt_progress.setTextVisible(False)
            opt_progress_layout.addWidget(self.opt_progress_label)
            opt_progress_layout.addWidget(self.opt_progress, 1)
            self.opt_progress_host.setVisible(False)
            root.addWidget(self.opt_progress_host)
            self.workspace = LazyResultWorkspace(self)
            self.workspace.set_single_view_only(True)
            self.workspace.set_toolbar_visible(False)
            root.addWidget(self.workspace, 1)
            self.workspace.set_result(0, "过程曲线", {"kind": "empty", "message": "开始优化后，这里显示过程曲线。"})
        else:
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["方案", "总耦合效率", "光斑半径", "状态"])
            _stretch_table(self.table)
            self.table.itemSelectionChanged.connect(self._sync_apply_button)
            self.table.setMinimumHeight(140)
            self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            self.chart = QComboBox()
            self.chart.addItems(["过程曲线", "候选对照"])
            self.chart.currentTextChanged.connect(self._show_opt_chart)
            self.apply_button = _primary_button("应用方案")
            self.apply_button.setEnabled(False)
            self.apply_button.setToolTip("先在上方候选方案表中选择一行")
            self.apply_button.clicked.connect(self._apply_selected_result)
            self.apply_status = QLabel("")
            self.apply_status.setObjectName("HelperText")
            self.apply_status.setMinimumWidth(360)
            self.apply_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.apply_status.setWordWrap(False)
            self.opt_progress_host = QWidget()
            opt_progress_layout = QHBoxLayout(self.opt_progress_host)
            opt_progress_layout.setContentsMargins(0, 2, 0, 2)
            opt_progress_layout.setSpacing(8)
            self.opt_progress_label = QLabel("优化尚未开始")
            self.opt_progress_label.setObjectName("optimizationProgressText")
            self.opt_progress_label.setMinimumWidth(128)
            self.opt_progress = QProgressBar()
            self.opt_progress.setObjectName("optimizationProgressBar")
            self.opt_progress.setRange(0, 100)
            self.opt_progress.setValue(0)
            self.opt_progress.setTextVisible(False)
            opt_progress_layout.addWidget(self.opt_progress_label)
            opt_progress_layout.addWidget(self.opt_progress, 1)
            self.opt_progress_host.setVisible(False)
            root.addWidget(self.opt_progress_host)
            root.addWidget(_action_row(self.chart))
            self.workspace = LazyResultWorkspace(self)
            self.workspace.set_single_view_only(True)
            self.workspace.set_toolbar_visible(False)
            self.workspace.set_pane_header_visible(False)
            root.addWidget(self.workspace, 1)
            root.addWidget(self.table)
            root.addWidget(_action_row(self.apply_button, self.apply_status))
            self._started = False
            self._progress_path = ""
            self._progress_selected = ""
            self._opt_result: dict[str, Any] = {}
            self._show_opt_chart(self.chart.currentText())

    def set_selected(self, selected: set[str]) -> None:
        self.selected = set(selected)
        if self.kind == "opt_vars":
            self._rebuild_table()
            button = getattr(self, "start_button", None)
            if button is not None:
                button.setEnabled(bool(self.selected))
                button.setToolTip("" if self.selected else "请先在左栏勾选优化变量。")
        elif self.kind == "scan":
            self._fill_scan()

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        goal = getattr(self, "goal", None)
        setter = getattr(goal, "set_trained_models", None)
        if callable(setter):
            setter(models)
        selector = getattr(self, "model_selector", None)
        if selector is None:
            return
        previous = str(selector.currentData() or selector.currentText() or "")
        selector.blockSignals(True)
        selector.clear()
        for item in models:
            model_id = str(item.get("id") or item.get("model_id") or "")
            selector.addItem(str(item.get("title") or model_id or "模型"), dict(item))
        if previous:
            for index in range(selector.count()):
                data = selector.itemData(index)
                if isinstance(data, dict) and str(data.get("id") or data.get("model_id") or "") == previous:
                    selector.setCurrentIndex(index)
                    break
        selector.blockSignals(False)
        self._sync_selected_model()

    def _sync_selected_model(self, *_args) -> None:
        selector = getattr(self, "model_selector", None)
        goal = getattr(self, "goal", None)
        predict_model = getattr(goal, "predict_model", None)
        if selector is None or predict_model is None:
            return
        data = selector.currentData()
        model_id = str(data.get("id") or data.get("model_id") or "") if isinstance(data, dict) else ""
        for index in range(predict_model.count()):
            item = predict_model.itemData(index)
            candidate_id = str(item.get("id") or item.get("model_id") or "") if isinstance(item, dict) else ""
            if model_id and candidate_id == model_id:
                predict_model.setCurrentIndex(index)
                return
        if selector.currentText() and predict_model.findText(selector.currentText()) >= 0:
            predict_model.setCurrentText(selector.currentText())

    def _sync_beginner_controls(self, *_args) -> None:
        surrogate = bool(getattr(self, "surrogate_option", None) and self.surrogate_option.isChecked())
        goal = getattr(self, "goal", None)
        if goal is not None:
            mode = "surrogate" if surrogate else "formal"
            index = goal.eval_mode.findData(mode)
            if index >= 0 and goal.eval_mode.currentIndex() != index:
                goal.eval_mode.setCurrentIndex(index)
        model_row = getattr(self, "model_selector_row", None)
        if model_row is not None:
            model_row.setVisible(surrogate)
        for card, selected in (
            (getattr(self, "_formal_mode_card", None), not surrogate),
            (getattr(self, "_surrogate_mode_card", None), surrogate),
        ):
            if card is None:
                continue
            card.setProperty("selected", bool(selected))
            _refresh_widget_style(card)

    def _load_simple_objective_from_goal(self) -> None:
        goal_value = str(self.goal.goal.currentText() or "最大化耦合效率")
        if goal_value == "多目标加权":
            self.secondary_objective.setChecked(True)
            return
        index = self.objective_selector.findData(goal_value)
        if index >= 0:
            self.objective_selector.setCurrentIndex(index)

    def _sync_simple_objective_from_goal(self, value: str) -> None:
        if getattr(self, "_syncing_objective", False):
            return
        if str(value or "") == "多目标加权":
            self.secondary_objective.setChecked(True)
            return
        blocked = self.secondary_objective.blockSignals(True)
        self.secondary_objective.setChecked(False)
        self.secondary_objective.blockSignals(blocked)
        index = self.objective_selector.findData(str(value or ""))
        if index >= 0:
            self.objective_selector.setCurrentIndex(index)

    def _sync_objective(self, *_args) -> None:
        selector = getattr(self, "objective_selector", None)
        goal = getattr(self, "goal", None)
        if selector is None or goal is None or getattr(self, "_syncing_objective", False):
            return
        self._syncing_objective = True
        try:
            value = str(selector.currentData() or "最大化耦合效率")
            if self.secondary_objective.isChecked():
                value = "多目标加权"
            goal.goal.setCurrentText(value)
        finally:
            self._syncing_objective = False
        self._refresh_baseline_metric()

    def _primary_objective_changed(self, *_args) -> None:
        secondary = getattr(self, "secondary_objective", None)
        if secondary is not None and secondary.isChecked():
            blocked = secondary.blockSignals(True)
            secondary.setChecked(False)
            secondary.blockSignals(blocked)
        self._sync_objective()

    def _sync_secondary_objective(self, checked: bool) -> None:
        if checked:
            self._sync_objective()
            return
        self._sync_objective()

    def _toggle_advanced_options(self, expanded: bool) -> None:
        panel = getattr(self, "advanced_panel", None)
        if panel is not None:
            panel.setVisible(bool(expanded))
        button = getattr(self, "more_button", None)
        if button is not None:
            button.setText("收起参数" if expanded else "更多参数")

    def _refresh_baseline_metric(self, *_args) -> None:
        label = getattr(self, "current_metric", None)
        if label is None:
            return
        result = getattr(getattr(self.context, "project", None), "formal_result", None)
        metrics = result.get("metrics") if isinstance(result, dict) and isinstance(result.get("metrics"), dict) else result
        objective = str(self.objective_selector.currentData() or "最大化耦合效率") if getattr(self, "objective_selector", None) is not None else "最大化耦合效率"
        key = "rms_spot_radius_um" if objective == "最小化 RMS 光斑" else "coupling_efficiency"
        value = metrics.get(key) if isinstance(metrics, dict) else None
        try:
            number = float(value)
        except (TypeError, ValueError):
            label.setText("—")
            return
        if key == "coupling_efficiency" and 0.0 <= number <= 1.0:
            label.setText(f"{number * 100.0:.1f}%")
        else:
            label.setText(f"{number:.4g} μm" if key == "rms_spot_radius_um" else f"{number:.4g}")

    def _show_optimization_help(self) -> None:
        QMessageBox.information(
            self,
            "如何使用优化",
            "先在左侧勾选需要调整的参数，再选择优化目标并检查参数范围。\n\n"
            "默认使用当前仿真直接搜索；如果选择训练模型辅助，模型只用于加速候选筛选，最终仍会进行正式仿真验证。",
        )

    def _fill_scan(self) -> None:
        rows = _variable_rows(self.context.project.project)
        labels = [_display_variable(row) for row in rows if row[0] in self.selected]
        self.scan_summary.setText("、".join(labels[:2]) if labels else "（未勾选）")
        selected = [row for row in rows if row[0] in self.selected][:2]
        table = getattr(self, "range_table", None)
        if table is not None:
            table.setRowCount(len(selected))
            for index, (key, _group, _face, parameter) in enumerate(selected):
                current = _current_value(self.context.project.project, key)
                try:
                    number = float(current)
                    span = max(abs(number) * 0.10, 1e-6)
                    low, high = f"{number - span:g}", f"{number + span:g}"
                except ValueError:
                    low = high = "—"
                table.setItem(index, 0, QTableWidgetItem(parameter))
                table.setItem(index, 1, QTableWidgetItem(low))
                table.setItem(index, 2, QTableWidgetItem(high))
                table.item(index, 0).setData(Qt.ItemDataRole.UserRole, key)
            _stretch_table(table)
        button = getattr(self, "run_button", None)
        if button is not None:
            button.setEnabled(bool(selected))
            button.setToolTip("" if selected else "请先在左栏勾选 1～2 个变量。")

    def show_progress_started(self, path: str = "", selected: str = "") -> None:
        self._started = True
        self._progress_path = path or "光学仿真"
        self._progress_selected = selected or "未勾选变量"
        self._opt_result = {}
        self.show_opt_progress(0.0, "优化已提交")
        chart = getattr(self, "chart", None)
        if chart is not None:
            chart.setCurrentText("过程曲线")
        self._show_opt_chart("过程曲线")

    def apply_opt_result(self, result: dict[str, Any]) -> None:
        self._started = True
        self._opt_result = dict(result or {})
        self.show_opt_progress(1.0, "优化完成", state="complete")
        self._fill_result_table(self._opt_result)
        self._show_opt_chart(self.chart.currentText() if getattr(self, "chart", None) is not None else "过程曲线")

    def _fill_result_table(self, result: dict[str, Any]) -> None:
        table = getattr(self, "table", None)
        if table is None:
            return
        candidates = list(result.get("candidates") or [])
        history = candidates or list(result.get("history") or [])
        active_paths = [str(path) for path in list(result.get("metadata", {}).get("active_variables") or [])]
        rows = []
        row_variables: list[dict[str, float]] = []
        for index, item in enumerate(history[:100]):
            if not isinstance(item, dict):
                continue
            metrics = dict(item.get("metrics") or {})
            coupling = metrics.get(
                "total_coupling_efficiency",
                metrics.get("coupling_efficiency", item.get("coupling_efficiency")),
            )
            spot = metrics.get("rms_spot_radius_um", item.get("rms_spot_radius_um", item.get("spot_radius_um")))
            if coupling is None and spot is None and not item.get("status"):
                continue
            rows.append((
                str(item.get("label") or item.get("name") or f"候选 {index + 1}"),
                "—" if coupling is None else f"{float(coupling):.4g}",
                "—" if spot is None else f"{float(spot):.4g}",
                _optimization_status_label(item.get("status") or item.get("verification_status") or "已评估"),
            ))
            variables = item.get("variables")
            if isinstance(variables, dict):
                row_variables.append({str(key): float(value) for key, value in variables.items()})
            elif isinstance(variables, (list, tuple)) and len(variables) == len(active_paths):
                row_variables.append({path: float(value) for path, value in zip(active_paths, variables)})
            else:
                row_variables.append({})
        best = dict(result.get("best_metrics") or {})
        if best and not rows:
            rows.append(("最佳方案", str(best.get("coupling_efficiency", "—")), str(best.get("rms_spot_radius_um", "—")), "最佳"))
            row_variables.append({str(key): float(value) for key, value in dict(result.get("best_variables") or {}).items()})
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
            if row < len(row_variables) and table.item(row, 0) is not None:
                table.item(row, 0).setData(Qt.ItemDataRole.UserRole, row_variables[row])
        _stretch_table(table)
        self._sync_apply_button()

    def _sync_apply_button(self) -> None:
        button = getattr(self, "apply_button", None)
        table = getattr(self, "table", None)
        if button is None or table is None:
            return
        item = table.item(table.currentRow(), 0) if table.currentRow() >= 0 else None
        variables = item.data(Qt.ItemDataRole.UserRole) if item is not None else {}
        enabled = isinstance(variables, dict) and bool(variables)
        button.setEnabled(enabled)
        button.setToolTip("" if enabled else "先在上方候选方案表中选择一行")

    def _apply_selected_result(self) -> None:
        table = getattr(self, "table", None)
        context = getattr(self, "context", None)
        if table is None or context is None or table.currentRow() < 0:
            return
        item = table.item(table.currentRow(), 0)
        variables = item.data(Qt.ItemDataRole.UserRole) if item is not None else {}
        if not isinstance(variables, dict) or not variables:
            self.apply_status.setText("该行没有可应用的变量")
            return
        updater = getattr(getattr(context, "project", None), "apply_parameter_changes", None)
        if not callable(updater):
            self.apply_status.setText("当前项目不支持应用方案")
            return
        previous_result = getattr(getattr(context, "project", None), "formal_result", None)
        baseline = _coupling_efficiency_from_result(previous_result)
        if updater(variables, reason="应用优化候选方案"):
            self.apply_status.setText(f"已应用：{item.text()}，正在正式验证…")
            self.apply_button.setEnabled(False)
            self.applyAndVerifyRequested.emit(dict(variables), item.text(), baseline)
        else:
            self.apply_status.setText("方案与当前系统相同")

    def complete_candidate_validation(
        self,
        label: str,
        before: float | None,
        after: float | None,
        *,
        error: str = "",
    ) -> None:
        if error:
            self.apply_status.setText(f"{label} 正式验证失败：{error}")
        elif after is None:
            self.apply_status.setText(f"{label} 已应用，但正式结果没有返回耦合效率")
        elif before is None:
            self.apply_status.setText(f"{label} 正式验证完成：耦合效率 {after:.4g}（缺少应用前基线）")
        else:
            delta = after - before
            conclusion = "提高" if delta > 0 else "降低" if delta < 0 else "不变"
            self.apply_status.setText(
                f"{label} 正式验证完成：{before:.4g} → {after:.4g}，{conclusion} {abs(delta):.4g}"
            )
        self._sync_apply_button()

    def show_scan_status(self, message: str) -> None:
        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            workspace.set_result(0, "响应曲线", {"kind": "empty", "message": message})

    @staticmethod
    def _update_progress_bar(
        bar: QProgressBar | None,
        host: QWidget | None,
        label: QLabel | None,
        progress: float,
        message: str,
        state: str,
    ) -> None:
        if bar is None or host is None or label is None:
            return
        value = max(0.0, min(1.0, float(progress)))
        host.setVisible(True)
        bar.setValue(round(value * 100))
        next_state = str(state or "running")
        state_changed = bar.property("progressState") != next_state
        bar.setProperty("progressState", next_state)
        label.setText(f"{str(message or '处理中')} {value:.0%}")
        if state_changed:
            style = bar.style()
            style.unpolish(bar)
            style.polish(bar)
        bar.update()

    def show_scan_progress(
        self,
        progress: float,
        message: str = "扫描中",
        *,
        state: str = "running",
    ) -> None:
        self._update_progress_bar(
            getattr(self, "scan_progress", None),
            getattr(self, "scan_progress_host", None),
            getattr(self, "scan_progress_label", None),
            progress,
            message,
            state,
        )

    def show_scan_failed(self, message: str) -> None:
        bar = getattr(self, "scan_progress", None)
        current = (bar.value() / 100.0) if bar is not None else 0.0
        self.show_scan_progress(current, message or "扫描失败", state="error")

    def show_scan_cancelled(self, message: str = "扫描已取消") -> None:
        bar = getattr(self, "scan_progress", None)
        current = (bar.value() / 100.0) if bar is not None else 0.0
        self.show_scan_progress(current, message, state="cancelled")

    def show_opt_progress(
        self,
        progress: float,
        message: str = "优化中",
        *,
        state: str = "running",
    ) -> None:
        self._update_progress_bar(
            getattr(self, "opt_progress", None),
            getattr(self, "opt_progress_host", None),
            getattr(self, "opt_progress_label", None),
            progress,
            message,
            state,
        )

    def show_opt_failed(self, message: str) -> None:
        bar = getattr(self, "opt_progress", None)
        current = (bar.value() / 100.0) if bar is not None else 0.0
        self.show_opt_progress(current, message or "优化失败", state="error")

    def show_opt_cancelled(self, message: str = "优化已取消") -> None:
        bar = getattr(self, "opt_progress", None)
        current = (bar.value() / 100.0) if bar is not None else 0.0
        self.show_opt_progress(current, message, state="cancelled")

    def apply_scan_result(self, result: dict[str, Any], response: str) -> None:
        payload = scan_curve_payload(result, response)
        if payload is None:
            self.show_scan_status("扫描完成，但没有可绘制的响应曲线。")
            return
        self.workspace.set_result(0, "响应曲线", payload)

    def scan_ranges(self) -> list[tuple[str, float, float]]:
        table = getattr(self, "range_table", None)
        if table is None:
            return []
        rows: list[tuple[str, float, float]] = []
        for index in range(table.rowCount()):
            item = table.item(index, 0)
            key = str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""
            if not key:
                continue
            try:
                low = float(table.item(index, 1).text()) if table.item(index, 1) is not None else 0.0
                high = float(table.item(index, 2).text()) if table.item(index, 2) is not None else 0.0
            except (TypeError, ValueError):
                continue
            rows.append((key, low, high))
        return rows

    def _show_opt_chart(self, name: str) -> None:
        workspace = getattr(self, "workspace", None)
        if workspace is None:
            return
        result = dict(getattr(self, "_opt_result", {}) or {})
        if result:
            payload = opt_chart_payload(result, name)
            if payload is not None:
                workspace.set_result(0, name, payload)
                return
            workspace.set_result(0, name, {"kind": "empty", "message": "优化完成，暂无该图数据。"})
            return
        started = bool(getattr(self, "_started", False))
        path = str(getattr(self, "_progress_path", "") or "光学仿真")
        selected = str(getattr(self, "_progress_selected", "") or "未勾选变量")
        if name == "候选对照":
            message = (
                "优化完成后，这里显示候选方案对照。"
                if not started
                else f"已按{path}提交。候选对照将显示在这里。"
            )
        else:
            message = (
                "开始优化后，这里显示过程曲线。"
            )
        workspace.set_result(0, name, {"kind": "empty", "message": message})

    def _run_scan(self) -> None:
        self.scanRequested.emit()

    def _rebuild_table(self) -> None:
        table = getattr(self, "table", None)
        if table is None:
            return
        table.setRowCount(0)
        for key, group, face, parameter in _variable_rows(self.context.project.project):
            if key not in self.selected:
                continue
            row = table.rowCount()
            table.insertRow(row)
            label = f"{group} / {face} / {parameter}"
            table.setItem(row, 0, QTableWidgetItem(label))
            current = _current_value(self.context.project.project, key)
            table.setItem(row, 1, QTableWidgetItem(current))
            try:
                number = float(current)
                span = max(abs(number) * 0.10, 1e-6)
                low, high = f"{number - span:g}", f"{number + span:g}"
            except ValueError:
                low = high = "—"
            table.setItem(row, 2, QTableWidgetItem(low))
            table.setItem(row, 3, QTableWidgetItem(high))
            table.item(row, 0).setData(Qt.ItemDataRole.UserRole, key)


__all__ = ["OptimizationDocument", "QSpinBoxCompat"]
