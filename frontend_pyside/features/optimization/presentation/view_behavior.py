from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.unit_spinbox import UnitAwareDoubleSpinBox
from frontend_pyside.features.optimization.panels import OptimizationVariableSelector
from frontend_pyside.shared.components.basic import (
    Card,
    CollapsiblePanel,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace


class OptimizationViewMixin:
    @staticmethod
    def _sidebar_form(vertical_spacing: int = 6) -> QFormLayout:
        """Create a form that cannot grow wider than the settings viewport."""
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(vertical_spacing)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return form

    @staticmethod
    def _fit_sidebar_field(widget: QWidget) -> QWidget:
        # Combo/spin minimumSizeHint includes their longest text or numeric
        # suffix.  In a narrow sidebar that hint can be wider than the viewport,
        # so let the layout size the control and keep the text clipped internally.
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
        return widget

    def _parameter_names(self) -> list[str]:
        names = ["波长"]
        for surface in self.context.project.project.surfaces:
            names.append(f"{surface.name} / 曲率")
            names.append(f"{surface.name} / 厚度/间隔")
        names.extend(
            [
                "光纤模场直径",
                "接收面位置",
                "光纤 X 偏移",
                "光纤 Y 偏移",
                "光纤倾角 X",
                "光纤倾角 Y",
            ]
        )
        return names

    def _scan_page(self):
        """扫描高级设置。

        该页位于“更多设置”内，因此只承载设置，不再复制主结果图和数据表。
        结果统一回到外层主图工作区，避免“页面主图 + 更多设置内第二张同图”。
        """
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        settings = Card("扫描设置", compact=True)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.scan_mode = QComboBox(); self.scan_mode.addItems(["一维扫描", "二维扫描", "多参数采样"])
        self.scan_param = QComboBox(); self.scan_param.addItems(self._parameter_names())
        self.scan_param2 = QComboBox(); self.scan_param2.addItems(["不启用"] + self._parameter_names())
        self.scan_start = self._range_spin(-2.0); self.scan_stop = self._range_spin(2.0); self.scan_points = self._points_spin(81)
        self.scan_start2 = self._range_spin(-2.0); self.scan_stop2 = self._range_spin(2.0); self.scan_points2 = self._points_spin(41)
        self.scan_metric = QComboBox(); self.scan_metric.addItems(["耦合效率", "RMS 光斑", "Strehl", "边缘功率"])
        self.scan_scale = QComboBox(); self.scan_scale.addItems(["线性采样", "对数采样", "自适应加密"])
        self.scan_range_row = self._range_row(self.scan_start, self.scan_stop, self.scan_points)
        self.scan_range_row2 = self._range_row(self.scan_start2, self.scan_stop2, self.scan_points2)
        for label, widget in [
            ("扫描模式", self.scan_mode), ("主变量", self.scan_param), ("第二变量", self.scan_param2),
            ("主范围", self.scan_range_row), ("第二范围", self.scan_range_row2),
            ("采样方式", self.scan_scale), ("输出指标", self.scan_metric),
        ]:
            form.addRow(label, widget)
        self.include_baseline = QCheckBox("标记当前系统当前点"); self.include_baseline.setChecked(True)
        self.local_refine = QCheckBox("识别高效区域"); self.local_refine.setChecked(True)
        form.addRow(self.include_baseline); form.addRow(self.local_refine)
        settings.body.addLayout(form)

        range_card = Card("范围概览", compact=True)
        self.scan_range_preview = QLabel(); self.scan_range_preview.setObjectName("scanRangePreview")
        self.scan_range_preview.setWordWrap(True); range_card.body.addWidget(self.scan_range_preview)
        settings.body.addWidget(range_card)
        self.scan_legacy_run = PrimaryButton("开始规律扫描")
        self.scan_legacy_run.clicked.connect(self._run_scan)
        self.scan_legacy_run.hide()
        self.scan_legacy_run.setParent(page)
        self.scan_status = InfoRow("任务状态", "等待提交")
        self.scan_status.hide()
        self.scan_status.setParent(page)
        root.addWidget(settings)

        # 兼容旧结果刷新逻辑：这些控件仍接收数据，但不再显示在“更多设置”。
        # 外层 main_result/main_result_views 是用户唯一看到的结果工作区。
        compatibility = QWidget(page); compatibility.hide()
        hidden_layout = QVBoxLayout(compatibility)
        self.scan_best = InlineMetric("最佳参数", "—")
        self.scan_width = InlineMetric("峰值结果", "—")
        self.scan_sensitivity = InlineMetric("高效区间", "—")
        self.scan_samples = InlineMetric("有效点数", "0")
        self.scan_result = ResultWorkspace(); self.scan_result.set_single_view_only(True); self.scan_result.set_toolbar_visible(False); self.scan_result.set_maximize_controls_visible(False)
        self._set_empty_result(self.scan_result, "尚未提交扫描任务")
        self.scan_details = QTabWidget(); self.scan_details.setDocumentMode(True)
        self.scan_data_table = DataTable(0, 4); self.scan_data_table.setHorizontalHeaderLabels(["序号", "参数值", "结果", "状态"])
        self.scan_region_table = DataTable(0, 5); self.scan_region_table.setHorizontalHeaderLabels(["标准", "下限", "上限", "区间宽度", "相对最佳点"])
        self.scan_compare_table = DataTable(0, 5); self.scan_compare_table.setHorizontalHeaderLabels(["参数", "最佳值", "峰值结果", "区间宽度", "灵敏度"])
        self.scan_verification_table = DataTable(0, 5); self.scan_verification_table.setHorizontalHeaderLabels(["参数点", "曲线结果", "正式仿真", "偏差", "状态"])
        for table, label in ((self.scan_data_table, "采样数据"), (self.scan_region_table, "高效区间"), (self.scan_compare_table, "参数对比"), (self.scan_verification_table, "完整仿真")):
            self.scan_details.addTab(table, label)
        for widget in (self.scan_best, self.scan_width, self.scan_sensitivity, self.scan_samples, self.scan_result, self.scan_details):
            hidden_layout.addWidget(widget)

        self.scan_param.currentTextChanged.connect(lambda *_: self._sync_scan_units())
        self.scan_param2.currentTextChanged.connect(lambda *_: self._sync_scan_units())
        self._sync_scan_units()
        for widget in (self.scan_mode, self.scan_param, self.scan_param2, self.scan_scale, self.scan_metric, self.scan_start, self.scan_stop, self.scan_points, self.scan_start2, self.scan_stop2, self.scan_points2):
            signal = getattr(widget, "currentTextChanged", None) or getattr(widget, "valueChanged", None)
            if signal is not None:
                signal.connect(self._update_scan_range_preview)
        self._update_scan_range_preview()
        root.addStretch(1)
        return page


    def _sync_scan_units(self) -> None:
        def unit(label: str) -> str:
            if label == "波长":
                return " nm"
            if "模场直径" in label:
                return " μm"
            if "倾角" in label:
                return " °"
            return " mm"
        if hasattr(self, "scan_start"):
            suffix = unit(self.scan_param.currentText())
            self.scan_start.setSuffix(suffix); self.scan_stop.setSuffix(suffix)
        if hasattr(self, "scan_start2"):
            suffix = unit(self.scan_param2.currentText()) if self.scan_param2.currentIndex() > 0 else ""
            self.scan_start2.setSuffix(suffix); self.scan_stop2.setSuffix(suffix)

    def _update_scan_range_preview(self, *_):
        mode = self.scan_mode.currentText()
        main_points = self.scan_points.value()
        second_enabled = mode == "二维扫描" or self.scan_param2.currentText() != "不启用"
        total = main_points * self.scan_points2.value() if second_enabled else main_points
        main_step = (
            (self.scan_stop.value() - self.scan_start.value()) / max(1, main_points - 1)
        )
        lines = [
            f"主变量：{self.scan_param.currentText()}",
            f"范围：{self.scan_start.value():.6g} ～ {self.scan_stop.value():.6g}",
            f"采样点：{main_points}　步长约 {main_step:.4g}",
        ]
        if second_enabled:
            lines.append(
                f"第二变量：{self.scan_param2.currentText()}　{self.scan_points2.value()} 点"
            )
        lines.extend(
            [
                f"预计计算点：{total}",
                f"输出：{self.scan_metric.currentText()} · {self.scan_scale.currentText()}",
            ]
        )
        self.scan_range_preview.setText("\n".join(lines))

    def _auto_page(self):
        """优化采用纵向连续工作流：设置 → 运行 → 候选 → 进一步分析。"""
        # 外层“更多设置”已经位于页面滚动区，内部不再嵌套第二层滚动。
        page = QWidget()
        page.setObjectName("optimizationAutoPage")
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 12, 16)
        root.setSpacing(10)

        # --- 优化设置摘要：新用户默认只需要知道目标、变量数、约束与计算量。 ---
        setup = Card("优化设置", compact=True)
        self.optimization_setup_card = setup
        self.optimization_setup_summary = QLabel()
        self.optimization_setup_summary.setObjectName("compactContext")
        self.optimization_setup_summary.setWordWrap(True)
        setup.body.addWidget(self.optimization_setup_summary)
        setup_actions = QHBoxLayout()
        self.auto_edit_settings_button = SecondaryButton("编辑优化设置")
        self.auto_advanced_button = SecondaryButton("高级算法")
        setup_actions.addWidget(self.auto_edit_settings_button)
        setup_actions.addWidget(self.auto_advanced_button)
        setup_actions.addStretch(1)
        setup.body.addLayout(setup_actions)
        root.addWidget(setup)

        # 完整变量范围、目标与工程约束属于同一件事，统一收进一个按需展开区。
        self.auto_edit_panel = CollapsiblePanel("编辑优化设置", expanded=False)
        # The full variable matrix is a professional editor, not a 300 px sidebar
        # table.  Keep only a summary/action in the task page and open the same
        # persistent selector in a resizable dialog.
        variable_summary_card = Card("优化变量", compact=True)
        self.auto_variable_summary = QLabel("选择本次允许调整的变量；完整范围在变量编辑器中设置。")
        self.auto_variable_summary.setWordWrap(True)
        self.auto_variable_summary.setObjectName("compactContext")
        variable_summary_card.body.addWidget(self.auto_variable_summary)
        open_variable_editor = SecondaryButton("打开变量编辑器")
        variable_summary_card.body.addWidget(open_variable_editor)
        self.auto_edit_panel.content_layout.addWidget(variable_summary_card)

        self.variable_selector_dialog = QDialog(page)
        self.variable_selector_dialog.setWindowTitle("优化变量编辑器")
        self.variable_selector_dialog.setModal(False)
        self.variable_selector_dialog.setSizeGripEnabled(True)
        self.variable_selector_dialog.resize(1180, 760)
        self.variable_selector_dialog.setMinimumSize(860, 600)
        variable_dialog_layout = QVBoxLayout(self.variable_selector_dialog)
        variable_dialog_layout.setContentsMargins(14, 14, 14, 12)
        variable_dialog_layout.setSpacing(8)
        variable_hint = QLabel("筛选并启用变量，再设置上下限。关闭窗口不会丢失本次设置。")
        variable_hint.setObjectName("mutedText")
        variable_dialog_layout.addWidget(variable_hint)
        self.variable_selector = OptimizationVariableSelector(self.context.project, self.variable_selector_dialog)
        self.variable_selector.changed.connect(self._update_fixed_selection_summary)
        self.variable_selector.changed.connect(self._refresh_auto_setup_summary)
        variable_dialog_layout.addWidget(self.variable_selector, 1)
        variable_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        variable_buttons.rejected.connect(self.variable_selector_dialog.hide)
        variable_dialog_layout.addWidget(variable_buttons)
        open_variable_editor.clicked.connect(self.variable_selector_dialog.show)

        target_form = self._sidebar_form(7)
        self.objective = QComboBox()
        self.objective.addItems(["最大化耦合效率", "最小化 RMS 光斑", "多目标加权"])
        self._fit_sidebar_field(self.objective)
        constraints = QLabel("中心厚度 ≥ 0.5 mm　空气间隔 ≥ 0.5 mm　|R| ≥ 1.5 mm　总长 ≤ 50 mm")
        constraints.setWordWrap(True)
        constraints.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        target_form.addRow("目标函数", self.objective)
        target_form.addRow("工程约束", constraints)
        self.auto_edit_panel.content_layout.addLayout(target_form)

        self.collimation_enabled = QCheckBox("启用准直硬约束")
        self.collimation_surface = QComboBox()
        self.collimation_surface.addItem("自动识别准直输出面", None)
        for position, surface in enumerate(self.context.project.project.surfaces):
            surface_index = getattr(surface, "index", position)
            surface_name = getattr(surface, "name", f"表面 {surface_index}")
            self.collimation_surface.addItem(f"{surface_name}（表面 {surface_index} 后）", int(surface_index))
        self.collimation_span = UnitAwareDoubleSpinBox(); self.collimation_span.setRange(0.1, 1000.0); self.collimation_span.setDecimals(3); self.collimation_span.setValue(10.0); self.collimation_span.setSuffix(" mm")
        self.collimation_radius_change = UnitAwareDoubleSpinBox(); self.collimation_radius_change.setRange(0.01, 100.0); self.collimation_radius_change.setDecimals(3); self.collimation_radius_change.setValue(2.0); self.collimation_radius_change.setSuffix(" %")
        self.collimation_curvature = UnitAwareDoubleSpinBox(); self.collimation_curvature.setRange(1e-5, 10.0); self.collimation_curvature.setDecimals(5); self.collimation_curvature.setValue(0.05)
        self.collimation_centroid_drift = UnitAwareDoubleSpinBox(); self.collimation_centroid_drift.setRange(0.001, 100.0); self.collimation_centroid_drift.setDecimals(3); self.collimation_centroid_drift.setValue(1.0); self.collimation_centroid_drift.setSuffix(" % 光斑半径")
        self.collimation_axis_tilt = UnitAwareDoubleSpinBox(); self.collimation_axis_tilt.setRange(0.001, 1000.0); self.collimation_axis_tilt.setDecimals(3); self.collimation_axis_tilt.setValue(1.0); self.collimation_axis_tilt.setSuffix(" mrad")
        self.auto_collimation_panel = CollapsiblePanel("准直约束", expanded=False)
        collimation_form = self._sidebar_form(6)
        for field in (
            self.collimation_surface,
            self.collimation_span,
            self.collimation_radius_change,
            self.collimation_curvature,
            self.collimation_centroid_drift,
            self.collimation_axis_tilt,
        ):
            self._fit_sidebar_field(field)
        collimation_form.addRow(self.collimation_enabled)
        collimation_form.addRow("评价位置", self.collimation_surface)
        collimation_form.addRow("评价段长度", self.collimation_span)
        collimation_form.addRow("最大半径变化", self.collimation_radius_change)
        collimation_form.addRow("最大归一化曲率", self.collimation_curvature)
        collimation_form.addRow("最大质心漂移", self.collimation_centroid_drift)
        collimation_form.addRow("最大光轴倾角", self.collimation_axis_tilt)
        self.auto_collimation_panel.content_layout.addLayout(collimation_form)
        self.auto_edit_panel.content_layout.addWidget(self.auto_collimation_panel)
        root.addWidget(self.auto_edit_panel)

        self.auto_algorithm_panel = CollapsiblePanel("高级算法", expanded=False)
        algorithm_form = self._sidebar_form(6)
        self.algorithm = QComboBox(); self.algorithm.addItems(["智能全局搜索", "贝叶斯粗搜", "差分进化粗搜"])
        self.iterations = QSpinBox(); self.iterations.setRange(10, 5000); self.iterations.setValue(300)
        self.starts = QSpinBox(); self.starts.setRange(1, 100); self.starts.setValue(8)
        self.tolerance = UnitAwareDoubleSpinBox(); self.tolerance.setDecimals(8); self.tolerance.setRange(1e-10, 1e-2); self.tolerance.setValue(1e-6)
        for label, widget in [("算法", self.algorithm), ("最大迭代", self.iterations), ("多起点", self.starts), ("收敛阈值", self.tolerance)]:
            self._fit_sidebar_field(widget)
            algorithm_form.addRow(label, widget)
        self.auto_algorithm_panel.content_layout.addLayout(algorithm_form)
        root.addWidget(self.auto_algorithm_panel)

        self.auto_edit_settings_button.clicked.connect(lambda: self.auto_edit_panel.set_expanded(not self.auto_edit_panel.toggle.isChecked()))
        self.auto_advanced_button.clicked.connect(lambda: self.auto_algorithm_panel.set_expanded(not self.auto_algorithm_panel.toggle.isChecked()))

        # Legacy run/result controls still receive backend updates for compatibility,
        # but the focused task has exactly one primary action and one result area.
        # Keep this old workflow under a permanently hidden parent instead of
        # duplicating “开始优化” and a second result canvas inside advanced settings.
        self.auto_runtime_compat = QWidget(page)
        self.auto_runtime_compat.hide()
        auto_runtime_layout = QVBoxLayout(self.auto_runtime_compat)
        auto_runtime_layout.setContentsMargins(0, 0, 0, 0)
        run_card = Card("运行", self.auto_runtime_compat, compact=True)
        self.auto_status = InfoRow("状态", "准备就绪")
        run_card.body.addWidget(self.auto_status)
        self.auto_legacy_run = PrimaryButton("开始优化")
        self.auto_legacy_run.clicked.connect(self._run_auto)
        run_card.body.addWidget(self.auto_legacy_run)
        auto_runtime_layout.addWidget(run_card)

        # 兼容旧结果逻辑，但不再在主界面重复提供“自动同步 + 手动容差”两套动作。
        self.auto_prepare_tolerance = QCheckBox("优化完成后自动准备容差")
        self.auto_prepare_tolerance.setChecked(False)
        self.auto_prepare_tolerance.hide()

        # --- 结果区：没有结果时完全隐藏，避免空卡片。 ---
        self.auto_results_block = QWidget(self.auto_runtime_compat)
        results_layout = QVBoxLayout(self.auto_results_block)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(10)
        self.auto_results_block.hide()

        summary = Card("优化结果", compact=True)
        cards = QHBoxLayout(); cards.setSpacing(7)
        self.auto_baseline = InlineMetric("当前系统", "—", "%")
        self.auto_candidate = InlineMetric("最佳候选", "—", "%")
        self.auto_gain = InlineMetric("提升", "—", "%")
        self.auto_constraint = InlineMetric("约束", "待运行")
        for card in (self.auto_baseline, self.auto_candidate, self.auto_gain, self.auto_constraint):
            card.note_label.hide()
            cards.addWidget(card, 1)
        summary.body.addLayout(cards)
        results_layout.addWidget(summary)

        self.auto_result = ResultWorkspace()
        self.auto_result.set_single_view_only(True)
        self.auto_result.set_toolbar_visible(False)
        self.auto_result.set_maximize_controls_visible(False)
        self.auto_result.setMinimumHeight(470)
        self._set_empty_result(self.auto_result, "等待优化结果")
        results_layout.addWidget(self.auto_result)

        candidate_section = CollapsiblePanel("候选结果", expanded=True)
        self.auto_candidate_table = DataTable(0, 6)
        self.auto_candidate_table.setHorizontalHeaderLabels(["排名", "候选结果", "耦合效率", "系统效率", "约束", "验证状态"])
        self.auto_candidate_table.stretch_columns(1)
        self.auto_candidate_table.setMinimumHeight(190)
        candidate_section.content_layout.addWidget(self.auto_candidate_table)
        action_row = QHBoxLayout()
        self.auto_tolerance_button = SecondaryButton("容差分析")
        self.auto_tolerance_button.setEnabled(False)
        self.auto_tolerance_button.setToolTip("完成优化并选定候选后，在当前研究流下方展开容差分析。")
        self.auto_tolerance_button.clicked.connect(self._open_tolerance_from_optimization)
        action_row.addStretch(1); action_row.addWidget(self.auto_tolerance_button)
        candidate_section.content_layout.addLayout(action_row)
        results_layout.addWidget(candidate_section)

        detail_section = CollapsiblePanel("候选详情", expanded=False)
        self.auto_parameter_table = DataTable(0, 5)
        self.auto_parameter_table.setHorizontalHeaderLabels(["参数", "初始值", "最优值", "改变量", "单位"])
        self.auto_parameter_table.stretch_columns(0)
        self.auto_parameter_table.setMinimumHeight(180)
        detail_section.content_layout.addWidget(self.auto_parameter_table)
        self.auto_verification_table = DataTable(0, 5)
        self.auto_verification_table.setHorizontalHeaderLabels(["候选", "模型预测", "正式仿真", "偏差", "状态"])
        self.auto_verification_table.stretch_columns(0)
        self.auto_verification_table.setMinimumHeight(110)
        detail_section.content_layout.addWidget(self.auto_verification_table)
        results_layout.addWidget(detail_section)

        compare_section = CollapsiblePanel("候选对比", expanded=False)
        self.auto_compare_table = DataTable(0, 4)
        self.auto_compare_table.setHorizontalHeaderLabels(["指标", "当前系统", "最优候选", "变化"])
        self.auto_compare_table.stretch_columns(0)
        self.auto_compare_table.setMinimumHeight(130)
        compare_section.content_layout.addWidget(self.auto_compare_table)
        results_layout.addWidget(compare_section)

        # 兼容旧字段；真正容差结果在研究主流程中原地展开，不再作为平级页签。
        self.auto_tolerance_text = QLabel("完成优化后可在下方展开容差分析。")
        self.auto_tolerance_text.hide()
        self.auto_details = None

        auto_runtime_layout.addWidget(self.auto_results_block)
        root.addStretch(1)
        for signal in (
            self.variable_selector.changed,
            self.objective.currentTextChanged,
            self.collimation_enabled.toggled,
            self.iterations.valueChanged,
        ):
            signal.connect(self._refresh_auto_setup_summary)
        self._refresh_auto_setup_summary()
        return page

    def _refresh_auto_setup_summary(self, *_args) -> None:
        if not hasattr(self, "optimization_setup_summary"):
            return
        try:
            count = len(self.variable_selector.get_variables())
        except Exception:
            count = 0
        constraint_count = 4 + (1 if getattr(self, "collimation_enabled", None) and self.collimation_enabled.isChecked() else 0)
        objective = self.objective.currentText() if hasattr(self, "objective") else "最大化耦合效率"
        iterations = self.iterations.value() if hasattr(self, "iterations") else 300
        self.optimization_setup_summary.setText(
            f"目标：{objective}　｜　变量：{count} 个　｜　约束：{constraint_count} 项　｜　搜索次数：{iterations}"
        )
        if hasattr(self, "auto_variable_summary"):
            labels = []
            try:
                for item in self.variable_selector.get_variables()[:4]:
                    labels.append(str(item.get("label") or item.get("path") or "变量"))
            except Exception:
                labels = []
            self.auto_variable_summary.setText(
                "当前选择：" + ("、".join(labels) if labels else "尚未选择优化变量")
                + (f" 等 {count} 个" if count > len(labels) and labels else "")
            )

    def _compare_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.compare_baseline = InlineMetric("当前系统", "\u2014", note="当前系统指标")
        self.compare_scan = InlineMetric("\u626b\u63cf\u6700\u4f73\u70b9", "\u2014", note="\u540e\u7aef\u626b\u63cf\u7ed3\u679c")
        self.compare_auto = InlineMetric("\u4f18\u5316\u5019\u9009", "\u2014", note="\u5f85\u6b63\u5f0f\u4eff\u771f\u590d\u6838")
        self.compare_status = InlineMetric("\u4efb\u52a1\u72b6\u6001", "\u7b49\u5f85")
        for card in (self.compare_baseline, self.compare_scan, self.compare_auto, self.compare_status):
            row.addWidget(card)
        root.addLayout(row)
        self.compare_result = ResultWorkspace()
        self.compare_result.set_layout_mode("左右双图")
        self._set_empty_result(self.compare_result, "\u7b49\u5f85\u626b\u63cf\u6216\u4f18\u5316\u4efb\u52a1\u5b8c\u6210")
        root.addWidget(self.compare_result, 1)
        return page

    def _history_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("\u4efb\u52a1\u7c7b\u578b"))
        self.history_type = QComboBox()
        self.history_type.addItems(["\u5168\u90e8\u7c7b\u578b", "\u53c2\u6570\u904d\u5386", "\u81ea\u52a8\u8c03\u53c2"])
        toolbar.addWidget(self.history_type)
        toolbar.addStretch()
        refresh = SecondaryButton("\u5237\u65b0\u5f53\u524d\u4efb\u52a1")
        refresh.clicked.connect(self._refresh_history)
        toolbar.addWidget(refresh)
        root.addLayout(toolbar)
        self.history_table = DataTable(0, 7)
        self.history_table.setHorizontalHeaderLabels(["\u4efb\u52a1", "\u7c7b\u578b", "\u72b6\u6001", "\u8fdb\u5ea6", "\u53d8\u91cf\u6570", "\u4efb\u52a1 ID", "\u8bf4\u660e"])
        self.history_table.stretch_columns(0, 6)
        root.addWidget(self.history_table, 1)
        return page

    @staticmethod
    def _range_spin(value: float) -> QDoubleSpinBox:
        spin = UnitAwareDoubleSpinBox()
        spin.setRange(-10000, 10000)
        spin.setDecimals(6)
        spin.setValue(value)
        spin.setMinimumWidth(88)
        spin.setMaximumWidth(118)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def _points_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(2, 501)
        spin.setValue(value)
        spin.setMinimumWidth(58)
        spin.setMaximumWidth(72)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def _range_row(start, stop, points) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(start)
        layout.addWidget(QLabel("\u81f3"))
        layout.addWidget(stop)
        layout.addWidget(QLabel("\u70b9"))
        layout.addWidget(points)
        layout.addStretch(1)
        row.setMinimumWidth(285)
        return row
