from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

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
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        workbench = QSplitter(Qt.Orientation.Horizontal)
        workbench.setObjectName("optimizationScanSplitter")
        workbench.setChildrenCollapsible(False)
        workbench.setHandleWidth(8)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setMinimumWidth(390)
        settings_scroll.setMaximumWidth(500)
        settings = Card("扫描设置", compact=True)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.scan_mode = QComboBox()
        self.scan_mode.addItems(["一维扫描", "二维扫描", "多参数采样"])
        self.scan_param = QComboBox()
        self.scan_param.addItems(self._parameter_names())
        self.scan_param2 = QComboBox()
        self.scan_param2.addItems(["不启用"] + self._parameter_names())
        self.scan_start = self._range_spin(-2.0)
        self.scan_stop = self._range_spin(2.0)
        self.scan_points = self._points_spin(81)
        self.scan_start2 = self._range_spin(-2.0)
        self.scan_stop2 = self._range_spin(2.0)
        self.scan_points2 = self._points_spin(41)
        self.scan_metric = QComboBox()
        self.scan_metric.addItems(["耦合效率", "RMS 光斑", "Strehl", "边缘功率"])
        self.scan_scale = QComboBox()
        self.scan_scale.addItems(["线性采样", "对数采样", "自适应加密"])
        self.scan_range_row = self._range_row(self.scan_start, self.scan_stop, self.scan_points)
        self.scan_range_row2 = self._range_row(self.scan_start2, self.scan_stop2, self.scan_points2)
        for label, widget in [
            ("扫描模式", self.scan_mode),
            ("主变量", self.scan_param),
            ("第二变量", self.scan_param2),
            ("主范围", self.scan_range_row),
            ("第二范围", self.scan_range_row2),
            ("采样方式", self.scan_scale),
            ("输出指标", self.scan_metric),
        ]:
            form.addRow(label, widget)
        self.include_baseline = QCheckBox("标记当前项目基准点")
        self.include_baseline.setChecked(True)
        self.local_refine = QCheckBox("识别高效区域")
        self.local_refine.setChecked(True)
        form.addRow(self.include_baseline)
        form.addRow(self.local_refine)
        settings.body.addLayout(form)

        range_card = Card("范围概览", compact=True)
        self.scan_range_preview = QLabel()
        self.scan_range_preview.setObjectName("scanRangePreview")
        self.scan_range_preview.setWordWrap(True)
        range_card.body.addWidget(self.scan_range_preview)
        settings.body.addWidget(range_card)

        run = PrimaryButton("开始规律扫描")
        run.clicked.connect(self._run_scan)
        settings.body.addWidget(run)
        self.scan_status = InfoRow("任务状态", "等待提交")
        settings.body.addWidget(self.scan_status)
        settings_scroll.setWidget(settings)
        workbench.addWidget(settings_scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(7)
        summary_frame = QWidget()
        summary = QHBoxLayout(summary_frame)
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(7)
        self.scan_best = InlineMetric("最佳参数", "—")
        self.scan_width = InlineMetric("峰值结果", "—")
        self.scan_sensitivity = InlineMetric("高效区间", "—")
        self.scan_samples = InlineMetric("有效点数", "0")
        for card in (self.scan_best, self.scan_width, self.scan_sensitivity, self.scan_samples):
            summary.addWidget(card, 1)
        right_layout.addWidget(summary_frame)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)
        self.scan_result = ResultWorkspace()
        self.scan_result.set_single_view_only(True)
        self.scan_result.set_toolbar_visible(False)
        self.scan_result.set_maximize_controls_visible(False)
        self._set_empty_result(
            self.scan_result,
            "尚未提交扫描任务\n提交后在此显示正式曲线、采样点和最佳区域",
        )
        vertical.addWidget(self.scan_result)

        self.scan_details = QTabWidget()
        self.scan_details.setDocumentMode(True)
        self.scan_details.setMinimumHeight(220)
        self.scan_data_table = DataTable(0, 4)
        self.scan_data_table.setHorizontalHeaderLabels(["序号", "参数值", "结果", "状态"])
        self.scan_data_table.stretch_columns(1, 2)
        self.scan_details.addTab(self.scan_data_table, "采样数据")
        self.scan_region_table = DataTable(0, 5)
        self.scan_region_table.setHorizontalHeaderLabels(["标准", "下限", "上限", "区间宽度", "相对最佳点"])
        self.scan_region_table.stretch_columns(0)
        self.scan_details.addTab(self.scan_region_table, "高效区间")
        self.scan_compare_table = DataTable(0, 5)
        self.scan_compare_table.setHorizontalHeaderLabels(["参数", "最佳值", "峰值结果", "区间宽度", "灵敏度"])
        self.scan_compare_table.stretch_columns(0)
        self.scan_details.addTab(self.scan_compare_table, "参数对比")
        self.scan_verification_table = DataTable(0, 5)
        self.scan_verification_table.setHorizontalHeaderLabels(["参数点", "曲线结果", "正式仿真", "偏差", "状态"])
        self.scan_verification_table.stretch_columns(0)
        self.scan_details.addTab(self.scan_verification_table, "正式复核")
        vertical.addWidget(self.scan_details)
        vertical.setSizes([680, 220])
        vertical.setStretchFactor(0, 1)
        vertical.setStretchFactor(1, 0)
        right_layout.addWidget(vertical, 1)
        workbench.addWidget(right)
        workbench.setStretchFactor(0, 0)
        workbench.setStretchFactor(1, 1)
        workbench.setSizes([430, 1090])
        root.addWidget(workbench, 1)

        for widget in (
            self.scan_mode,
            self.scan_param,
            self.scan_param2,
            self.scan_scale,
            self.scan_metric,
            self.scan_start,
            self.scan_stop,
            self.scan_points,
            self.scan_start2,
            self.scan_stop2,
            self.scan_points2,
        ):
            signal = getattr(widget, "currentTextChanged", None) or getattr(widget, "valueChanged", None)
            if signal is not None:
                signal.connect(self._update_scan_range_preview)
        self._update_scan_range_preview()
        return page

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
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        workbench = QSplitter(Qt.Orientation.Horizontal)
        workbench.setObjectName("optimizationAutoSplitter")
        workbench.setChildrenCollapsible(False)
        workbench.setHandleWidth(8)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setMinimumWidth(440)
        settings_scroll.setMaximumWidth(620)
        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(0, 0, 8, 0)
        settings_layout.setSpacing(7)

        self.variable_selector = OptimizationVariableSelector(self.context.project)
        variable_panel = CollapsiblePanel("参数范围", expanded=False)
        variable_panel.content_layout.addWidget(self.variable_selector)
        settings_layout.addWidget(variable_panel)

        target_panel = CollapsiblePanel("目标与限制", expanded=True)
        target_form = QFormLayout()
        target_form.setVerticalSpacing(6)
        self.objective = QComboBox()
        self.objective.addItems(["最大化耦合效率", "最小化 RMS 光斑", "多目标加权"])
        constraints = QLabel(
            "中心厚度 ≥ 0.5 mm　空气间隔 ≥ 0.5 mm　|R| ≥ 1.5 mm　总长 ≤ 50 mm"
        )
        constraints.setWordWrap(True)
        target_form.addRow("目标函数", self.objective)
        target_form.addRow("工程约束", constraints)
        target_panel.content_layout.addLayout(target_form)
        settings_layout.addWidget(target_panel)

        collimation_panel = CollapsiblePanel("准直约束", expanded=False)
        collimation_form = QFormLayout()
        collimation_form.setVerticalSpacing(6)
        self.collimation_enabled = QCheckBox("启用准直硬约束")
        self.collimation_surface = QComboBox()
        self.collimation_surface.addItem("自动识别准直输出面", None)
        for position, surface in enumerate(self.context.project.project.surfaces):
            surface_index = getattr(surface, "index", position)
            surface_name = getattr(surface, "name", f"表面 {surface_index}")
            self.collimation_surface.addItem(
                f"{surface_name}（表面 {surface_index} 后）", int(surface_index)
            )
        self.collimation_span = QDoubleSpinBox()
        self.collimation_span.setRange(0.1, 1000.0)
        self.collimation_span.setDecimals(3)
        self.collimation_span.setValue(10.0)
        self.collimation_span.setSuffix(" mm")
        self.collimation_radius_change = QDoubleSpinBox()
        self.collimation_radius_change.setRange(0.01, 100.0)
        self.collimation_radius_change.setDecimals(3)
        self.collimation_radius_change.setValue(2.0)
        self.collimation_radius_change.setSuffix(" %")
        self.collimation_curvature = QDoubleSpinBox()
        self.collimation_curvature.setRange(1e-5, 10.0)
        self.collimation_curvature.setDecimals(5)
        self.collimation_curvature.setValue(0.05)
        self.collimation_centroid_drift = QDoubleSpinBox()
        self.collimation_centroid_drift.setRange(0.001, 100.0)
        self.collimation_centroid_drift.setDecimals(3)
        self.collimation_centroid_drift.setValue(1.0)
        self.collimation_centroid_drift.setSuffix(" % 光斑半径")
        self.collimation_axis_tilt = QDoubleSpinBox()
        self.collimation_axis_tilt.setRange(0.001, 1000.0)
        self.collimation_axis_tilt.setDecimals(3)
        self.collimation_axis_tilt.setValue(1.0)
        self.collimation_axis_tilt.setSuffix(" mrad")
        collimation_form.addRow(self.collimation_enabled)
        collimation_form.addRow("评价位置", self.collimation_surface)
        collimation_form.addRow("评价段长度", self.collimation_span)
        collimation_form.addRow("最大半径变化", self.collimation_radius_change)
        collimation_form.addRow("最大归一化曲率", self.collimation_curvature)
        collimation_form.addRow("最大质心漂移", self.collimation_centroid_drift)
        collimation_form.addRow("最大光轴倾角", self.collimation_axis_tilt)
        collimation_hint = QLabel(
            "满足准直约束的候选才比较耦合效率；粗搜、Powell精调和独立复核使用同一组约束。"
        )
        collimation_hint.setWordWrap(True)
        collimation_form.addRow(collimation_hint)
        collimation_panel.content_layout.addLayout(collimation_form)
        settings_layout.addWidget(collimation_panel)

        algorithm_panel = CollapsiblePanel("高级算法", expanded=False)
        algorithm_form = QFormLayout()
        algorithm_form.setVerticalSpacing(6)
        self.algorithm = QComboBox()
        self.algorithm.addItems(["智能全局搜索", "贝叶斯粗搜", "差分进化粗搜"])
        self.iterations = QSpinBox()
        self.iterations.setRange(10, 5000)
        self.iterations.setValue(300)
        self.starts = QSpinBox()
        self.starts.setRange(1, 100)
        self.starts.setValue(8)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(8)
        self.tolerance.setRange(1e-10, 1e-2)
        self.tolerance.setValue(1e-6)
        for label, widget in [
            ("算法", self.algorithm),
            ("最大迭代", self.iterations),
            ("多起点", self.starts),
            ("收敛阈值", self.tolerance),
        ]:
            algorithm_form.addRow(label, widget)
        algorithm_panel.content_layout.addLayout(algorithm_form)
        settings_layout.addWidget(algorithm_panel)

        self.auto_status = InfoRow("研究状态", "等待开始")
        settings_layout.addWidget(self.auto_status)
        run = PrimaryButton("开始研究")
        run.clicked.connect(self._run_auto)
        settings_layout.addWidget(run)
        settings_scroll.setWidget(settings_panel)
        workbench.addWidget(settings_scroll)

        right = QWidget()
        result_layout = QVBoxLayout(right)
        result_layout.setContentsMargins(8, 0, 0, 0)
        result_layout.setSpacing(7)
        cards = QHBoxLayout()
        cards.setSpacing(7)
        self.auto_baseline = InlineMetric("基准效率", "—", "%")
        self.auto_candidate = InlineMetric("候选效率", "—", "%")
        self.auto_gain = InlineMetric("预计提升", "—", "%")
        self.auto_constraint = InlineMetric("约束状态", "待运行")
        for card in (self.auto_baseline, self.auto_candidate, self.auto_gain, self.auto_constraint):
            cards.addWidget(card, 1)
        result_layout.addLayout(cards)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)
        self.auto_result = ResultWorkspace()
        self.auto_result.set_single_view_only(True)
        self.auto_result.set_toolbar_visible(False)
        self.auto_result.set_maximize_controls_visible(False)
        self._set_empty_result(
            self.auto_result,
            "尚未开始研究\n平台将根据研究对象和内容自动搜索候选，并用正式仿真复核",
        )
        vertical.addWidget(self.auto_result)

        self.auto_details = QTabWidget()
        self.auto_details.setDocumentMode(True)
        self.auto_details.setMinimumHeight(220)
        self.auto_candidate_table = DataTable(0, 6)
        self.auto_candidate_table.setHorizontalHeaderLabels(
            ["排名", "候选方案", "耦合效率", "系统效率", "约束", "正式复核"]
        )
        self.auto_candidate_table.stretch_columns(1)
        self.auto_details.addTab(self.auto_candidate_table, "候选方案")
        self.auto_parameter_table = DataTable(0, 5)
        self.auto_parameter_table.setHorizontalHeaderLabels(["参数", "初始值", "最优值", "改变量", "单位"])
        self.auto_parameter_table.stretch_columns(0)
        self.auto_details.addTab(self.auto_parameter_table, "参数明细")
        self.auto_compare_table = DataTable(0, 4)
        self.auto_compare_table.setHorizontalHeaderLabels(["指标", "当前方案", "最优方案", "变化"])
        self.auto_compare_table.stretch_columns(0)
        self.auto_details.addTab(self.auto_compare_table, "结果对比")
        self.auto_verification_table = DataTable(0, 5)
        self.auto_verification_table.setHorizontalHeaderLabels(["方案", "优化结果", "正式仿真", "偏差", "状态"])
        self.auto_verification_table.stretch_columns(0)
        self.auto_details.addTab(self.auto_verification_table, "正式复核")
        vertical.addWidget(self.auto_details)
        vertical.setSizes([680, 220])
        vertical.setStretchFactor(0, 1)
        vertical.setStretchFactor(1, 0)
        result_layout.addWidget(vertical, 1)

        workbench.addWidget(right)
        workbench.setStretchFactor(0, 0)
        workbench.setStretchFactor(1, 1)
        workbench.setSizes([520, 1080])
        root.addWidget(workbench, 1)
        return page

    def _compare_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.compare_baseline = InlineMetric("\u57fa\u51c6\u65b9\u6848", "\u2014", note="\u5f53\u524d\u9879\u76ee\u6307\u6807")
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
        spin = QDoubleSpinBox()
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
