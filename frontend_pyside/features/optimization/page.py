from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.infrastructure.api.clients import JobClient, OptimizationClient, ScanClient
from frontend_pyside.shared.background import BackgroundPreparer
from frontend_pyside.shared.components.basic import (
    Card,
    CollapsiblePanel,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.lazy_widgets import LazyStackedWidget
from frontend_pyside.shared.lifecycle import ManagedPageResources
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.research_summary import latest_optimization_result
from frontend_pyside.shared.settings import WorkspaceStateStore
from frontend_pyside.shared.display_names import parameter_label
from .guided_research import (
    SCAN_SUPPORTED_KEYS,
    choose_guided_mode,
    first_air_gap_surface,
    first_surface,
    friendly_failure_message,
    friendly_warning_message,
    last_surface,
    validate_guided_research,
)
from .presentation.job_behavior import OptimizationJobMixin
from .presentation.result_behavior import OptimizationResultMixin
from .presentation.submit_behavior import OptimizationSubmitMixin
from .presentation.view_behavior import OptimizationViewMixin


class OptimizationPage(
    OptimizationViewMixin,
    OptimizationSubmitMixin,
    OptimizationJobMixin,
    OptimizationResultMixin,
    QWidget,
):


    navigateRequested = Signal(str)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.lifecycle = ManagedPageResources(self)
        self.workspace_state = WorkspaceStateStore("optimization")
        self._result_preparer = BackgroundPreparer(self)
        self._prepared_result_jobs: dict[tuple[str, int], str] = {}
        self.api_client = context.api_client
        self.scan_client = ScanClient(self.api_client)
        self.optimization_client = OptimizationClient(self.api_client)
        self.job_client = JobClient(self.api_client)
        self.job_watcher = context.services.job_watcher
        self._centralized_polling = bool(getattr(self.job_watcher, "centralized_polling", False))
        self._jobs: dict[str, dict] = {}
        self._active_guided_mode = ""
        self._last_selected_contents: list[str] = []
        self._page_active = False
        self._pending_result_render: tuple[str, dict] | None = None

        self._poll_timer = self.lifecycle.manage_timer(QTimer(self))
        self._poll_timer.setProperty("stopWhenHidden", True)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_jobs)

        self.lifecycle.connect(self.api_client.completed, self._api_completed)
        self.lifecycle.connect(self.api_client.failed, self._api_failed)
        self.lifecycle.connect(self.job_watcher.job_progress, self._on_ws_progress)
        self.lifecycle.connect(self.job_watcher.job_completed, self._on_ws_completed)
        self.lifecycle.connect(self.job_watcher.job_failed, self._on_ws_failed)
        self.lifecycle.connect(context.tasks.tasks_changed, self._sync_task_context)
        self.lifecycle.connect(context.tasks.task_result_changed, self._shared_result_changed)
        self.lifecycle.connect(self._result_preparer.completed, self._prepared_result_ready)
        self.lifecycle.connect(self._result_preparer.failed, self._prepared_result_failed)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 12)
        root.setSpacing(7)

        self._build_header(root)
        main = QSplitter(Qt.Orientation.Horizontal)
        main.setObjectName("optimizationMainSplitter")
        main.setChildrenCollapsible(False)
        main.setHandleWidth(8)
        self.settings_panel = self._build_settings_panel()
        self.main_result_panel = self._build_main_result_panel()
        self.summary_panel = self._build_summary_panel()
        main.addWidget(self.settings_panel)
        main.addWidget(self.main_result_panel)
        main.addWidget(self.summary_panel)
        main.setSizes([430, 960, 300])
        main.setStretchFactor(0, 0)
        main.setStretchFactor(1, 1)
        main.setStretchFactor(2, 0)
        root.addWidget(main, 1)
        self.main_splitter = main
        self._responsive_band = ""
        self.lifecycle.single_shot(0, self._apply_responsive_layout)

        self._connect_research_controls()
        self._research_options_changed()
        self._refresh_user_summary()
        self.compare_dialog = None
        self.history_dialog = None

    
    def _build_header(self, root: QVBoxLayout) -> None:
        header = Card("研究与优化", compact=True)
        row = QHBoxLayout()
        project = self.context.project.project
        self.project_context_label = QLabel(f"当前项目：{project.name}")
        self.project_context_label.setObjectName("cardTitle")
        row.addWidget(self.project_context_label)
        row.addStretch(1)
        self.header_best = InlineMetric("当前最佳", "—", "%")
        self.header_state = InlineMetric("状态", "就绪")
        row.addWidget(self.header_best)
        row.addWidget(self.header_state)
        header.body.addLayout(row)
        root.addWidget(header)

    def _build_settings_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("optimizationSettingsScroll")
        scroll.setMinimumWidth(315)
        scroll.setMaximumWidth(450)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(7)

        object_card = Card("研究对象", compact=True)
        object_buttons = QVBoxLayout()
        object_buttons.setSpacing(6)
        self.structure_group = QButtonGroup(self)
        self.structure_group.setExclusive(True)
        self.fixed_structure_button = SecondaryButton("固定结构")
        self.variable_structure_button = SecondaryButton("可变结构")
        self.fixed_structure_button.setToolTip("镜片数量与顺序保持不变，只研究连续参数")
        self.variable_structure_button.setToolTip("允许改变镜片数量、顺序、方向或镜片组合")
        self.fixed_structure_button.setObjectName("fixedStructureButton")
        self.variable_structure_button.setObjectName("variableStructureButton")
        for index, button in enumerate((self.fixed_structure_button, self.variable_structure_button)):
            button.setCheckable(True)
            button.setMinimumHeight(42)
            self.structure_group.addButton(button, index)
            object_buttons.addWidget(button)
        self.fixed_structure_button.setChecked(True)
        object_card.body.addLayout(object_buttons)
        layout.addWidget(object_card)

        self.structure_stack = QStackedWidget()
        self.structure_stack.addWidget(self._build_fixed_contents())
        self.structure_stack.addWidget(self._build_variable_contents())
        layout.addWidget(self.structure_stack)
        self.fixed_structure_button.toggled.connect(self._research_options_changed)
        self.variable_structure_button.toggled.connect(self._research_options_changed)

        target = Card("研究目标", compact=True)
        form = QFormLayout()
        self.guided_goal = QComboBox()
        self.guided_goal.addItems(
            [
                "耦合效率最高",
                "系统效率最高",
                "多波长性能最好",
                "系统更紧凑",
                "综合性能",
            ]
        )
        form.addRow("关注目标", self.guided_goal)
        target.body.addLayout(form)
        self.preference_summary = QLabel("综合性能的后台权重仅在高级分析中显示。")
        self.preference_summary.setWordWrap(True)
        self.preference_summary.setObjectName("helperText")
        target.body.addWidget(self.preference_summary)
        layout.addWidget(target)

        depth = Card("研究范围", compact=True)
        depth_row = QHBoxLayout()
        self.depth_group = QButtonGroup(self)
        self.depth_group.setExclusive(True)
        self.depth_buttons: list[SecondaryButton] = []
        for index, label in enumerate(("快速预览", "平衡研究", "深入研究")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            self.depth_group.addButton(button, index)
            self.depth_buttons.append(button)
            depth_row.addWidget(button, 1)
        self.depth_buttons[1].setChecked(True)
        depth.body.addLayout(depth_row)
        self.depth_hint = QLabel("兼顾速度和正式复核数量。")
        self.depth_hint.setObjectName("helperText")
        self.depth_hint.setWordWrap(True)
        depth.body.addWidget(self.depth_hint)
        layout.addWidget(depth)

        self.limit_panel = CollapsiblePanel("约束设置", expanded=False)
        self.limit_summary = QLabel("总长≤50 mm · 空气间隔≥0.5 mm · 镜片≤4片 · 最低效率80%")
        self.limit_summary.setObjectName("helperText")
        self.limit_summary.setWordWrap(True)
        
        self.limit_panel.body.insertWidget(1, self.limit_summary)
        limit_form = QFormLayout()
        self.minimum_spacing = QDoubleSpinBox()
        self.minimum_spacing.setRange(0.0, 100.0)
        self.minimum_spacing.setValue(0.5)
        self.minimum_spacing.setSuffix(" mm")
        self.maximum_length = QDoubleSpinBox()
        self.maximum_length.setRange(1.0, 2000.0)
        self.maximum_length.setValue(50.0)
        self.maximum_length.setSuffix(" mm")
        self.maximum_lenses = QSpinBox()
        self.maximum_lenses.setRange(1, 20)
        self.maximum_lenses.setValue(4)
        self.minimum_efficiency = QDoubleSpinBox()
        self.minimum_efficiency.setRange(0.0, 100.0)
        self.minimum_efficiency.setValue(80.0)
        self.minimum_efficiency.setSuffix(" %")
        self.multiwave_required = QCheckBox("要求所有设置波长都满足限制")
        self.multiwave_required.setChecked(True)
        for label, widget in (
            ("最小空气间隔", self.minimum_spacing),
            ("最大系统长度", self.maximum_length),
            ("镜片数量上限", self.maximum_lenses),
            ("最低效率", self.minimum_efficiency),
        ):
            limit_form.addRow(label, widget)
        limit_form.addRow(self.multiwave_required)
        self.limit_panel.content_layout.addLayout(limit_form)
        def update_limit_summary(*_args):
            self.limit_summary.setText(
                f"总长≤{self.maximum_length.value():g} mm · "
                f"空气间隔≥{self.minimum_spacing.value():g} mm · "
                f"镜片≤{self.maximum_lenses.value()}片 · "
                f"最低效率{self.minimum_efficiency.value():g}%"
            )
        for control in (self.minimum_spacing, self.maximum_length, self.maximum_lenses, self.minimum_efficiency):
            control.valueChanged.connect(update_limit_summary)
        update_limit_summary()
        layout.addWidget(self.limit_panel)

        self.start_research_button = PrimaryButton("开始研究")
        self.start_research_button.clicked.connect(self._start_guided_research)
        layout.addWidget(self.start_research_button)
        self.guided_status = InfoRow("当前状态", "选择研究内容后开始")
        layout.addWidget(self.guided_status)
        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    def _build_fixed_contents(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.fixed_content_boxes: dict[str, QCheckBox] = {}
        groups = (
            (
                "光源",
                (("wavelength", "波长"), ("waist", "束腰"), ("waist_position", "束腰位置")),
            ),
            (
                "镜头",
                (
                    ("curvature", "曲率"),
                    ("thickness", "厚度"),
                    ("spacing", "空气间隔"),
                    ("aperture", "有效孔径"),
                    ("lens_direction", "镜片方向"),
                ),
            ),
            (
                "光纤与装调",
                (
                    ("fiber_axial", "光纤轴向位置"),
                    ("fiber_lateral", "横向位置"),
                    ("fiber_tilt", "角度倾斜"),
                    ("fiber_mode", "NA 和模场直径"),
                ),
            ),
        )
        self.fixed_group_panels: list[tuple[CollapsiblePanel, tuple[str, ...]]] = []
        for group_name, items in groups:
            panel = CollapsiblePanel(group_name, expanded=group_name == "镜头")
            grid = QGridLayout()
            keys: list[str] = []
            for index, (key, label) in enumerate(items):
                box = QCheckBox(label)
                box.setChecked(key in {"spacing", "fiber_axial"})
                self.fixed_content_boxes[key] = box
                keys.append(key)
                grid.addWidget(box, index // 2, index % 2)
            panel.content_layout.addLayout(grid)
            self.fixed_group_panels.append((panel, tuple(keys)))
            layout.addWidget(panel)
        return page

    def _build_variable_contents(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        card = Card("结构范围", compact=True)
        form = QFormLayout()
        lens_range = QWidget()
        lens_range_layout = QHBoxLayout(lens_range)
        lens_range_layout.setContentsMargins(0, 0, 0, 0)
        self.minimum_lenses = QSpinBox()
        self.minimum_lenses.setRange(1, 10)
        self.minimum_lenses.setValue(2)
        self.variable_maximum_lenses = QSpinBox()
        self.variable_maximum_lenses.setRange(1, 10)
        self.variable_maximum_lenses.setValue(4)
        lens_range_layout.addWidget(self.minimum_lenses)
        lens_range_layout.addWidget(QLabel("至"))
        lens_range_layout.addWidget(self.variable_maximum_lenses)
        lens_range_layout.addWidget(QLabel("片"))
        self.allow_reorder = QCheckBox("允许调整顺序")
        self.allow_reorder.setChecked(True)
        self.allow_reverse = QCheckBox("允许反转镜片")
        self.allow_reverse.setChecked(True)
        self.lens_source = QComboBox()
        self.lens_source.addItems(["当前项目镜片", "已导入候选镜片"])
        form.addRow("镜片数量", lens_range)
        form.addRow(self.allow_reorder)
        form.addRow(self.allow_reverse)
        form.addRow("候选来源", self.lens_source)
        card.body.addLayout(form)

        geometry_grid = QGridLayout()
        geometry_grid.setHorizontalSpacing(14)
        geometry_grid.setVerticalSpacing(6)
        self.lens_type_boxes: dict[str, QCheckBox] = {}
        geometry_labels = ("平凸", "双凸", "正弯月", "平凹", "双凹", "负弯月")
        for index, label in enumerate(geometry_labels):
            box = QCheckBox(label)
            box.setChecked(True)
            self.lens_type_boxes[label] = box
            geometry_grid.addWidget(box, index // 3, index % 3)
        card.body.addWidget(QLabel("允许的几何形状"))
        card.body.addLayout(geometry_grid)

        profile_row = QHBoxLayout()
        self.surface_profile_boxes: dict[str, QCheckBox] = {}
        for label in ("球面", "非球面"):
            box = QCheckBox(label)
            box.setChecked(True)
            self.surface_profile_boxes[label] = box
            profile_row.addWidget(box)
        profile_row.addStretch(1)
        card.body.addWidget(QLabel("允许的表面面型"))
        card.body.addLayout(profile_row)

        optimize_grid = QGridLayout()
        self.variable_content_boxes: dict[str, QCheckBox] = {}
        for index, (key, label) in enumerate(
            (
                ("spacing", "空气间隔"),
                ("fiber_axial", "光纤位置"),
                ("lens_direction", "镜片方向"),
                ("aperture", "有效孔径"),
            )
        ):
            box = QCheckBox(label)
            box.setChecked(key in {"spacing", "fiber_axial"})
            self.variable_content_boxes[key] = box
            optimize_grid.addWidget(box, index // 2, index % 2)
        card.body.addWidget(QLabel("同时优化"))
        card.body.addLayout(optimize_grid)
        layout.addWidget(card)
        return page

    def _build_main_result_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        view_row = QHBoxLayout()
        self.result_view_group = QButtonGroup(self)
        self.result_view_group.setExclusive(True)
        self.result_view_buttons: list[SecondaryButton] = []
        
        self.result_view_labels = (
            "参数响应", "优化前后", "优化收敛", "候选对比", "参数相关性"
        )
        self._main_result_payloads: list[dict] = [
            {"kind": "empty", "message": "暂无结果"} for _ in self.result_view_labels
        ]
        for index, label in enumerate(self.result_view_labels):
            button = SecondaryButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._select_main_result(i))
            self.result_view_group.addButton(button, index)
            self.result_view_buttons.append(button)
            view_row.addWidget(button)
            if index > 0:
                button.setVisible(False)
        self.result_view_buttons[0].setChecked(True)
        view_row.addStretch(1)
        layout.addLayout(view_row)

        self.main_result = ResultWorkspace()
        self.main_result.setMinimumHeight(390)
        self.main_result.set_single_view_only(True)
        self.main_result.set_toolbar_visible(False)
        self.main_result.set_maximize_controls_visible(False)
        self._main_result_payloads[0] = {
            "kind": "empty",
            "message": "选择研究对象、研究内容和目标后开始研究。",
        }
        self.main_result.set_result(0, "参数响应", self._main_result_payloads[0])
        layout.addWidget(self.main_result, 1)

        progress_frame = QWidget()
        progress_layout = QHBoxLayout(progress_frame)
        progress_layout.setContentsMargins(4, 0, 4, 0)
        progress_layout.setSpacing(8)
        self.activity_label = QLabel("尚未开始研究")
        self.activity_label.setWordWrap(True)
        progress_layout.addWidget(self.activity_label, 1)
        self.research_progress = QProgressBar()
        self.research_progress.setRange(0, 100)
        self.research_progress.setValue(0)
        self.research_progress.setMaximumWidth(260)
        progress_layout.addWidget(self.research_progress)
        layout.addWidget(progress_frame)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setDocumentMode(True)
        self.detail_tabs.setMinimumHeight(150)
        self.candidate_table = DataTable(0, 5)
        self.candidate_table.setHorizontalHeaderLabels(
            ["方案", "结构/参数", "预测/扫描", "正式结果", "状态"]
        )
        self.candidate_table.stretch_columns(1)
        self.detail_tabs.addTab(self.candidate_table, "候选方案")
        self.parameter_range_text = self._detail_label("任务完成后显示最佳值、推荐范围和当前值。")
        self.detail_tabs.addTab(self.parameter_range_text, "参数范围")
        self.multiwave_text = self._detail_label("选择多波长研究后显示各波长效率和最差波长。")
        self.detail_tabs.addTab(self.multiwave_text, "多波长结果")
        self.formal_verification_text = self._detail_label("等待独立正式仿真复核。")
        self.detail_tabs.addTab(self.formal_verification_text, "正式复核")
        self.detail_tabs.addTab(self._build_advanced_tools(), "高级分析")
        self.detail_panel = CollapsiblePanel("详细结果", expanded=False)
        self.detail_panel.content_layout.addWidget(self.detail_tabs)
        layout.addWidget(self.detail_panel)
        return page

    def _build_advanced_tools(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(7, 7, 7, 7)
        row = QHBoxLayout()
        self.legacy_buttons: list[SecondaryButton] = []
        self.legacy_group = QButtonGroup(self)
        self.legacy_group.setExclusive(True)
        for index, label in enumerate(("参数扫描设置", "正式优化设置")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._set_legacy_mode(i))
            self.legacy_group.addButton(button, index)
            self.legacy_buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        history = SecondaryButton("任务与版本")
        history.clicked.connect(self._open_history_dialog)
        row.addWidget(history)
        layout.addLayout(row)
        self.legacy_stack = LazyStackedWidget()
        self.legacy_stack.add_lazy_widget(self._scan_page, "正在准备参数扫描设置…")
        self.legacy_stack.add_lazy_widget(self._auto_page, "正在准备正式优化设置…")
        layout.addWidget(self.legacy_stack, 1)
        self.legacy_buttons[0].setChecked(True)
        return page

    def _build_summary_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("optimizationSummaryScroll")
        scroll.setMinimumWidth(270)
        scroll.setMaximumWidth(330)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(7)

        best = Card("当前最佳", compact=True)
        self.summary_coupling = InfoRow("耦合效率", "—")
        self.summary_system = InfoRow("系统效率", "—")
        self.summary_worst_wave = InfoRow("最差波长效率", "—")
        self.summary_verification = InfoRow("正式复核", "等待")
        for item in (
            self.summary_coupling,
            self.summary_system,
            self.summary_worst_wave,
            self.summary_verification,
        ):
            best.body.addWidget(item)
        layout.addWidget(best)

        comparison = Card("相比当前方案", compact=True)
        self.summary_gain = InfoRow("效率提升", "—")
        self.summary_length = InfoRow("系统长度", "—")
        self.summary_lens_count = InfoRow("镜片数量", "—")
        for item in (
            self.summary_gain,
            self.summary_length,
            self.summary_lens_count,
        ):
            comparison.body.addWidget(item)
        layout.addWidget(comparison)

        influence = Card("主要影响因素", compact=True)
        self.main_factor_text = QLabel("任务完成后显示前三个重点参数。")
        self.main_factor_text.setWordWrap(True)
        influence.body.addWidget(self.main_factor_text)
        explain = SecondaryButton("解释该方案")
        explain.clicked.connect(lambda: self.navigateRequested.emit("machine_learning"))
        influence.body.addWidget(explain)
        layout.addWidget(influence)

        advice = Card("当前建议", compact=True)
        self.advice_text = QLabel("先选择研究内容并完成正式复核。")
        self.advice_text.setWordWrap(True)
        advice.body.addWidget(self.advice_text)
        layout.addWidget(advice)
        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    @staticmethod
    def _detail_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("resultDetailText")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    
    def _connect_research_controls(self) -> None:
        for box in (*self.fixed_content_boxes.values(), *self.variable_content_boxes.values()):
            box.toggled.connect(self._research_options_changed)
        for box in (*self.lens_type_boxes.values(), *self.surface_profile_boxes.values()):
            box.toggled.connect(self._research_options_changed)
        self.guided_goal.currentIndexChanged.connect(self._research_options_changed)
        for button in self.depth_buttons:
            button.toggled.connect(self._research_options_changed)
        for widget in (
            self.minimum_lenses,
            self.variable_maximum_lenses,
            self.minimum_spacing,
            self.maximum_length,
            self.maximum_lenses,
            self.minimum_efficiency,
        ):
            widget.valueChanged.connect(self._research_options_changed)
        self.allow_reorder.toggled.connect(self._research_options_changed)
        self.allow_reverse.toggled.connect(self._research_options_changed)
        self.lens_source.currentIndexChanged.connect(self._research_options_changed)

    def _research_options_changed(self, *_args) -> None:
        variable = self.variable_structure_button.isChecked()
        self.structure_stack.setCurrentIndex(1 if variable else 0)
        if variable:
            self.fixed_structure_button.setChecked(False)
        elif not self.fixed_structure_button.isChecked():
            self.fixed_structure_button.setChecked(True)
        depth_index = self.depth_group.checkedId()
        hints = {
            0: "适合快速判断趋势，正式复核数量较少。",
            1: "兼顾速度和正式复核数量。",
            2: "扩大候选范围并增加正式复核。",
        }
        self.depth_hint.setText(hints.get(depth_index, hints[1]))
        self._publish_research_profile()

    def _selected_contents(self) -> list[str]:
        boxes = self.variable_content_boxes if self.variable_structure_button.isChecked() else self.fixed_content_boxes
        contents = [key for key, box in boxes.items() if box.isChecked()]
        if self.variable_structure_button.isChecked():
            if self.allow_reorder.isChecked():
                contents.append("lens_order")
            if self.allow_reverse.isChecked():
                contents.append("lens_direction")
            contents.append("lens_count")
            if any(box.isChecked() for box in self.lens_type_boxes.values()):
                contents.append("lens_type")
        return list(dict.fromkeys(contents))

    def _publish_research_profile(self) -> dict:
        depth_index = self.depth_group.checkedId()
        depth = {0: "快速预览", 1: "平衡研究", 2: "深入研究"}.get(depth_index, "平衡研究")
        profile = {
            "structure": "可变镜头结构" if self.variable_structure_button.isChecked() else "固定镜头结构",
            "contents": self._selected_contents(),
            "goal": self.guided_goal.currentText(),
            "depth": depth,
            "limits": {
                "minimum_spacing_mm": self.minimum_spacing.value(),
                "maximum_length_mm": self.maximum_length.value(),
                "maximum_lenses": self.maximum_lenses.value(),
                "minimum_efficiency": self.minimum_efficiency.value() / 100.0,
                "multiwave_required": self.multiwave_required.isChecked(),
            },
            "variable_structure": {
                "minimum_lenses": self.minimum_lenses.value(),
                "maximum_lenses": self.variable_maximum_lenses.value(),
                "allow_reorder": self.allow_reorder.isChecked(),
                "allow_reverse": self.allow_reverse.isChecked(),
                "lens_source": self.lens_source.currentText(),
                "lens_types": [name for name, box in self.lens_type_boxes.items() if box.isChecked()],
                "surface_profiles": [name for name, box in self.surface_profile_boxes.items() if box.isChecked()],
            },
        }
        self.context.project.update_research_profile(profile)
        return profile

    def _start_guided_research(self) -> None:
        profile = self._publish_research_profile()
        contents = list(profile.get("contents", []) or [])
        validation = validate_guided_research(
            contents=contents,
            surface_count=len(list(getattr(self.context.project.project, "surfaces", []) or [])),
            variable_structure=self.variable_structure_button.isChecked(),
            minimum_lenses=self.minimum_lenses.value(),
            maximum_lenses=self.variable_maximum_lenses.value(),
        )
        if not validation.ok:
            self._fail_guided_start(validation.message)
            return

        self._last_selected_contents = contents
        self.research_progress.setValue(3)
        self.activity_label.setText("等待中")
        self.activity_label.setToolTip("正在分析参数范围并准备研究任务")
        self.header_state.set_value("准备中")
        self.start_research_button.setEnabled(False)

        structure_only = self.variable_structure_button.isChecked() and not any(
            key in contents
            for key in {"spacing", "curvature", "fiber_axial", "fiber_lateral", "fiber_tilt", "aperture"}
        )
        if structure_only:
            self._show_structure_capability_boundary(profile)
            return

        try:
            mode = choose_guided_mode(
                contents=contents,
                variable_structure=self.variable_structure_button.isChecked(),
            )
            if mode == "scan":
                content_key = next(iter(contents), "")
                self._active_guided_mode = "scan"
                self._configure_scan_from_profile(content_key)
                self.activity_label.setText("等待中")
                self.activity_label.setToolTip("正在提交参数规律研究，完成后自动显示最佳点和推荐范围")
                submitted = self._run_scan()
            else:
                self._active_guided_mode = "optimization"
                enabled_count = self._configure_auto_from_profile(contents, profile)
                if enabled_count <= 0:
                    raise ValueError("当前选择没有对应到可优化参数")
                self.activity_label.setText("等待中")
                self.activity_label.setToolTip("正在筛选候选方案并进行正式仿真验证")
                submitted = self._run_auto()
            if submitted is False:
                raise ValueError("研究任务未提交，请检查参数范围和研究内容")
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            self._fail_guided_start(friendly_failure_message(exc))
            return
        self._set_info(self.guided_status, "当前状态", "研究任务正在提交")

    def _fail_guided_start(self, message: str) -> None:
        text = friendly_failure_message(message)
        self.research_progress.setValue(0)
        self.activity_label.setText(text)
        self.header_state.set_value("待检查")
        self.start_research_button.setEnabled(True)
        self._set_info(self.guided_status, "当前状态", text)

    @staticmethod
    def _scan_supported_keys() -> set[str]:
        return set(SCAN_SUPPORTED_KEYS)

    def _ensure_legacy_mode(self, index: int) -> None:
        self.legacy_stack.setCurrentIndex(index)
        if 0 <= index < len(self.legacy_buttons):
            self.legacy_buttons[index].setChecked(True)

    def _set_legacy_mode(self, index: int) -> None:
        self._ensure_legacy_mode(max(0, min(index, self.legacy_stack.count() - 1)))

    def _configure_scan_from_profile(self, content_key: str) -> None:
        self._ensure_legacy_mode(0)
        label = self._first_scan_label(content_key)
        index = self.scan_param.findText(label)
        if index >= 0:
            self.scan_param.setCurrentIndex(index)
        self.scan_mode.setCurrentText("一维扫描")
        self.scan_param2.setCurrentIndex(0)
        self.scan_metric.setCurrentText("耦合效率")
        current, half_width = self._scan_default_range(content_key)
        self.scan_start.setValue(current - half_width)
        self.scan_stop.setValue(current + half_width)
        depth = self.depth_group.checkedId()
        self.scan_points.setValue({0: 31, 1: 81, 2: 161}.get(depth, 81))

    def _first_scan_label(self, key: str) -> str:
        project = self.context.project.project
        if key == "wavelength":
            return "波长"
        if key == "curvature":
            surface = first_surface(project)
            return f"{surface.name} / 曲率" if surface is not None else "接收面位置"
        if key == "spacing":
            surface = first_air_gap_surface(project) or last_surface(project)
            return f"{surface.name} / 厚度/间隔" if surface is not None else "接收面位置"
        if key == "fiber_lateral":
            return "光纤 X 偏移"
        if key == "fiber_tilt":
            return "光纤倾角 X"
        return "接收面位置"

    def _scan_default_range(self, key: str) -> tuple[float, float]:
        project = self.context.project.project
        if key == "wavelength":
            return float(project.wavelength_nm), max(10.0, float(project.wavelength_nm) * 0.03)
        if key == "curvature":
            surface = first_surface(project)
            if surface is not None:
                value = float(surface.radius_mm)
                return value, max(abs(value) * 0.25, 1.0)
        if key == "spacing":
            surface = first_air_gap_surface(project)
            if surface is not None:
                value = float(surface.thickness_mm)
                return value, max(abs(value) * 0.35, 0.5)
        if key == "fiber_tilt":
            return 0.0, 0.5
        return 0.0, 0.5

    def _configure_auto_from_profile(self, contents: list[str], profile: dict) -> int:
        self._ensure_legacy_mode(1)
        enabled_count = self._enable_variable_rows(contents)
        self.objective.setCurrentText("最大化耦合效率")
        depth = self.depth_group.checkedId()
        iterations, starts = {0: (80, 3), 1: (300, 8), 2: (800, 16)}.get(depth, (300, 8))
        self.iterations.setValue(iterations)
        self.starts.setValue(starts)
        self.algorithm.setCurrentText("智能全局搜索")
        return enabled_count

    def _enable_variable_rows(self, contents: list[str]) -> int:
        selector = self.variable_selector
        table = selector.table
        table.blockSignals(True)
        enabled_count = 0
        try:
            for row in range(table.rowCount()):
                item = table.item(row, 1)
                enabled_item = table.item(row, 0)
                metadata = item.data(Qt.ItemDataRole.UserRole) if item else {}
                path = str((metadata or {}).get("path", ""))
                category = str((metadata or {}).get("category", ""))
                enabled = False
                if "curvature" in contents and category == "曲率半径":
                    enabled = True
                material = str((metadata or {}).get("material", "")).upper()
                if "thickness" in contents and category == "厚度/间隔" and material != "AIR":
                    enabled = True
                if "spacing" in contents and category == "厚度/间隔" and material == "AIR":
                    enabled = True
                if "aperture" in contents and category == "半口径":
                    enabled = True
                if "wavelength" in contents and path == "source.wavelength_nm":
                    enabled = True
                if "fiber_axial" in contents and path == "receiver.axial_offset_z_mm":
                    enabled = True
                if "fiber_lateral" in contents and path in {"receiver.offset_x_mm", "receiver.offset_y_mm"}:
                    enabled = True
                if "fiber_tilt" in contents and path in {"receiver.tilt_x_deg", "receiver.tilt_y_deg"}:
                    enabled = True
                if "fiber_mode" in contents and path == "receiver.mode_field_diameter_x_um":
                    enabled = True
                if enabled_item is not None:
                    enabled_item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                    enabled_count += int(enabled)
        finally:
            table.blockSignals(False)
        selector.actions.refresh_filter()
        return enabled_count

    def _show_structure_capability_boundary(self, profile: dict) -> None:
        models = [
            item
            for item in self.context.registry.models
            if "bilstm" in str(item.get("model_type", item.get("type", ""))).lower()
        ]
        self.research_progress.setValue(0)
        self.start_research_button.setEnabled(True)
        if not models:
            message = (
                "当前没有可用的可变结构模型。平台已保存结构研究设置，但不会伪造候选排名。\n"
                "可在“智能分析 → 高级信息”中准备结构模型，或同时勾选空气间隔/光纤位置先研究当前结构。"
            )
            self.header_state.set_value("能力不足")
            self._set_info(self.guided_status, "当前状态", "缺少可变结构模型")
        else:
            message = (
                "检测到可变结构模型，但当前前端尚未接入候选镜片自动生成接口。\n"
                "模型可用于解释已有结构；结构组合搜索将在候选生成接口上线后启用。"
            )
            self.header_state.set_value("待候选接口")
            self._set_info(self.guided_status, "当前状态", "等待结构候选接口")
        self._main_result_payloads[0] = {"kind": "empty", "message": message}
        self._select_main_result(0)
        self.activity_label.setText(message)

    def _ensure_result_workspace(self, kind: str) -> None:

        self._ensure_legacy_mode(0 if str(kind) == "scan" else 1)

    
    def _shared_result_changed(self, _task_id: str, _result: object) -> None:
        self._refresh_user_summary()

    def _refresh_user_summary(self) -> None:
        result = latest_optimization_result(self.context.tasks)
        baseline = self.context.project.project.metrics.get("coupling_efficiency")
        if isinstance(baseline, (int, float)):
            self._set_info(self.summary_coupling, "耦合效率", f"{baseline * 100:.3f}%")
            self.header_best.set_value(f"{baseline * 100:.3f}", "%")
        if not result:
            return
        metrics = dict(result.get("best_metrics", {}) or {})
        efficiency = metrics.get("coupling_efficiency")
        if isinstance(efficiency, (int, float)):
            self._set_info(self.summary_coupling, "耦合效率", f"{efficiency * 100:.3f}%")
            self.header_best.set_value(f"{efficiency * 100:.3f}", "%")
            if isinstance(baseline, (int, float)):
                self._set_info(self.summary_gain, "效率提升", f"{(efficiency - baseline) * 100:+.3f}%")
        system_eff = metrics.get("system_efficiency")
        if isinstance(system_eff, (int, float)):
            self._set_info(self.summary_system, "系统效率", f"{system_eff * 100:.3f}%")
        self._set_info(self.summary_verification, "正式复核", "已完成" if result.get("status") == "completed" else str(result.get("status", "等待")))
        variables = list(dict(result.get("best_variables", {}) or {}))
        if variables:
            lines = [
                f"{index}. {parameter_label(name)}"
                for index, name in enumerate(variables[:3], start=1)
            ]
            self.main_factor_text.setText("\n".join(lines))
        warnings = list(result.get("warnings", []) or [])
        if warnings:
            localized = [friendly_warning_message(value) for value in warnings[:3]]
            self.advice_text.setText("当前结果存在提示：\n• " + "\n• ".join(localized))
        else:
            self.advice_text.setText("正式复核完成且未返回警告，可结合多波长和工程限制决定是否采用。")

    def _select_main_result(self, index: int) -> None:
        if not 0 <= index < len(self.result_view_buttons):
            return
        payloads = getattr(self, "_main_result_payloads", [])
        payload = payloads[index] if index < len(payloads) else {"kind": "empty", "message": "暂无结果"}
        title = self.result_view_labels[index] if index < len(self.result_view_labels) else "结果"
        self.main_result.set_result(0, title, payload)
        self.main_result.select_result(0)
        self.result_view_buttons[index].setChecked(True)

    @staticmethod
    def _set_info(widget: InfoRow, label: str, value: str) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(label)
            layout.itemAt(1).widget().setText(value)

    @staticmethod
    def _make_dialog(title: str, content: QWidget, width: int, height: int):
        from PySide6.QtWidgets import QDialog

        dialog = QDialog()
        dialog.setWindowTitle(title)
        dialog.setModal(False)
        dialog.resize(width, height)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(content)
        return dialog

    def _open_compare_dialog(self) -> None:
        if self.compare_dialog is None:
            self.compare_dialog = self._make_dialog("结果对比", self._compare_page(), 1180, 760)
        self.compare_dialog.show()
        self.compare_dialog.raise_()
        self.compare_dialog.activateWindow()

    def _open_history_dialog(self) -> None:
        if self.history_dialog is None:
            self.history_dialog = self._make_dialog("任务与版本", self._history_page(), 1180, 720)
        self._refresh_history()
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()

    
    def on_activated(self) -> None:
        self._page_active = True
        self.lifecycle.activated()
        self._restore_jobs_from_tasks(self.context.tasks.tasks)
        self._refresh_user_summary()
        if self.context.tasks.should_refresh_backend(ttl_s=3.0):
            self.job_client.list_jobs("optimization.jobs.refresh", limit=200)
        for job_id in list(self._jobs):
            task = self.context.tasks.find_by_job_id(job_id)
            if not task or str(task.get("status", "")) not in {"已完成", "失败", "已取消", "未收敛"}:
                self.job_client.get_status(f"optimization.status.{job_id}", job_id)
        if self._jobs and not self._centralized_polling:
            self._poll_timer.start()
        pending, self._pending_result_render = self._pending_result_render, None
        if pending is not None:
            kind, result = pending
            if kind == "scan":
                self._render_scan_result(result)
            else:
                self._render_optimization_result(result)

    def on_deactivated(self) -> None:
        self._page_active = False
        self._poll_timer.stop()
        self.lifecycle.deactivate()

    def _apply_responsive_layout(self) -> None:

        if not hasattr(self, "main_splitter"):
            return
        width = max(1, self.width())
        if width >= 1500:
            band = "wide"
        elif width >= 1180:
            band = "medium"
        else:
            band = "compact"
        if band == self._responsive_band:
            return
        self._responsive_band = band
        if band == "wide":
            self.summary_panel.setVisible(True)
            self.main_splitter.setSizes([410, max(720, width - 770), 340])
        elif band == "medium":
            self.summary_panel.setVisible(True)
            self.main_splitter.setSizes([350, max(560, width - 675), 315])
        else:
            self.summary_panel.setVisible(False)
            self.main_splitter.setSizes([315, max(480, width - 330), 0])

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        self.on_activated()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def dispose_page(self) -> None:
        self._poll_timer.stop()
        for dialog_name in ("compare_dialog", "history_dialog"):
            dialog = getattr(self, dialog_name, None)
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
                setattr(self, dialog_name, None)
        if hasattr(self, "legacy_stack"):
            self.legacy_stack.dispose()
        self.lifecycle.dispose()
