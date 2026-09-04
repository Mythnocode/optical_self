from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon
from frontend_pyside.infrastructure.api.clients import (
    DatasetClient,
    HeadlessDatasetClient,
    JobClient,
    TrainingClient,
)
from frontend_pyside.shared.components.basic import Badge, Card, CollapsiblePanel, InfoRow, SecondaryButton
from frontend_pyside.shared.components.foundation import PageHeader
from frontend_pyside.shared.components.workbench import ExpandableSection
from frontend_pyside.shared.lazy_widgets import LazyStackedWidget
from frontend_pyside.shared.lifecycle import ManagedPageResources
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.dialogs.plot_actions import open_workspace_plot
from frontend_pyside.shared.research_summary import (
    current_model_quality,
    explain_factor,
    humanize_parameter_name,
    latest_optimization_result,
    research_profile_text,
    top_influences,
)
from frontend_pyside.shared.settings import WorkspaceStateStore
from frontend_pyside.shared.display_names import RegistryAliasStore
from frontend_pyside.shared.task_display import MonotonicProgress
from frontend_pyside.shared import layout_tokens as ui_layout
from .presentation.api_behavior import MachineLearningApiMixin
from .presentation.job_behavior import MachineLearningJobMixin
from .presentation.view_behavior import MachineLearningViewMixin


class MachineLearningPage(
    MachineLearningViewMixin,
    MachineLearningApiMixin,
    MachineLearningJobMixin,
    QWidget,
):


    navigateRequested = Signal(str)
    predictionPopoutRequested = Signal()
    inversePredictionRequested = Signal()

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.lifecycle = ManagedPageResources(self)
        self.workspace_state = WorkspaceStateStore("machine_learning")
        self.registry_aliases = RegistryAliasStore()
        self.api_client = context.api_client
        self.dataset_client = DatasetClient(self.api_client)
        self.headless_client = HeadlessDatasetClient(self.api_client)
        self.training_client = TrainingClient(self.api_client)
        self.job_client = JobClient(self.api_client)
        self.job_watcher = context.services.job_watcher
        self._centralized_polling = bool(getattr(self.job_watcher, "centralized_polling", False))
        self._jobs: dict[str, dict] = {}
        self._pending_training: dict[str, dict] = {}
        self._selected_model_id: str | None = None
        self._background_workers: set[object] = set()
        self._page_active = False
        self._analysis_refresh_pending = True
        self._loaded_ml_results: set[str] = set()
        self._training_progress_tracker = MonotonicProgress()
        self._dataset_progress_tracker = MonotonicProgress()
        self._active_training_job_id = ""
        self._active_dataset_job_id = ""

        self._poll_timer = self.lifecycle.manage_timer(QTimer(self))
        self._poll_timer.setProperty("stopWhenHidden", True)
        self._poll_timer.setInterval(1000)
        self.lifecycle.connect(self._poll_timer.timeout, self._poll_jobs)
        self.lifecycle.connect(self.api_client.completed, self._api_completed)
        self.lifecycle.connect(self.api_client.failed, self._api_failed)
        self.lifecycle.connect(self.api_client.binary_completed, self._binary_completed)
        self.lifecycle.connect(self.job_watcher.job_progress, self._on_ws_progress)
        self.lifecycle.connect(self.job_watcher.job_completed, self._on_ws_completed)
        self.lifecycle.connect(self.job_watcher.job_failed, self._on_ws_failed)
        self.lifecycle.connect(context.tasks.tasks_changed, self._sync_task_context)
        self.lifecycle.connect(context.tasks.tasks_changed, self._refresh_analysis)
        self.lifecycle.connect(context.tasks.task_result_changed, self._refresh_analysis)
        self.lifecycle.connect(context.project.research_profile_changed, self._refresh_analysis)
        self.lifecycle.connect(context.registry.datasets_changed, self._registry_datasets_changed)
        self.lifecycle.connect(context.registry.models_changed, self._registry_models_changed)
        self.lifecycle.connect(context.registry.current_dataset_changed, self._select_training_dataset)
        self.lifecycle.connect(context.registry.current_model_changed, self._select_model_by_id)
        self.lifecycle.connect(context.registry.current_model_changed, self._refresh_analysis)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            ui_layout.PAGE_MARGIN,
            ui_layout.CONTROL_GAP,
            ui_layout.PAGE_MARGIN,
            ui_layout.CARD_GAP,
        )
        outer.setSpacing(ui_layout.CONTROL_GAP)

        self.popout_prediction_button = SecondaryButton("独立窗口")
        self.popout_prediction_button.setToolTip("把正向预测切换到非模态窗口，与主仿真工作台并排验证")
        self.popout_prediction_button.clicked.connect(self.predictionPopoutRequested.emit)
        self.popout_prediction_button.hide()
        header = PageHeader(
            "代理模型",
            "",
            actions=[self.popout_prediction_button],
        )
        self.page_header = header
        self.page_header.title_label.hide()
        self.page_header.subtitle_label.hide()
        self.page_header.setMinimumHeight(0)
        self.research_header = header.subtitle_label
        outer.addWidget(header)

        # One explicit workflow, not a summary page plus a separate hidden
        # training application.  Each stage owns the whole central workspace.
        stage_bar = QFrame(self)
        self.workflow_bar = stage_bar
        stage_bar.setObjectName("mlWorkflowBar")
        stage_layout = QHBoxLayout(stage_bar)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(7)
        self.workflow_group = QButtonGroup(self)
        self.workflow_group.setExclusive(True)
        self.workflow_buttons: list[SecondaryButton] = []
        # 模型概览不再占用一个中转页面。模型状态跟随构建/预测任务；
        # 可见流程直接从“数据准备”开始。栈索引 0 仅保留为兼容摘要。
        for stack_index, label in ((1, "数据准备"), (2, "模型训练"), (3, "模型比较"), (4, "预测")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=stack_index: self._set_workflow_step(i))
            self.workflow_group.addButton(button, stack_index)
            self.workflow_buttons.append(button)
            stage_layout.addWidget(button)
        stage_layout.addStretch(1)
        refresh = SecondaryButton("刷新")
        refresh.clicked.connect(lambda: self.refresh_remote(force=True))
        stage_layout.addWidget(refresh)
        outer.addWidget(stage_bar)

        self.workflow_stack = QStackedWidget(self)
        self.workflow_stack.setObjectName("mlWorkflowStack")

        overview = QWidget(self.workflow_stack)
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(ui_layout.CONTROL_GAP)
        overview_layout.addWidget(self._build_explanation_panel(), 0)
        self.analysis_main_panel = self._build_analysis_main()
        overview_layout.addWidget(self.analysis_main_panel, 1)
        if hasattr(self, "model_details_panel"):
            overview_layout.addWidget(self.model_details_panel, 0)
        self.workflow_stack.addWidget(self._workflow_scroll(overview, "mlOverviewScroll"))
        self.workflow_stack.addWidget(self._workflow_scroll(self._dataset(), "mlDatasetScroll"))
        self.workflow_stack.addWidget(self._workflow_scroll(self._training(), "mlTrainingScroll"))
        self.workflow_stack.addWidget(self._workflow_scroll(self._models_page(), "mlModelsScroll"))
        self.workflow_stack.addWidget(self._workflow_scroll(self._prediction_page(), "mlPredictionScroll"))
        outer.addWidget(self.workflow_stack, 1)

        # Existing background/job code still probes these objects.  Keep hidden
        # compatibility anchors without reintroducing a second scroll/section UI.
        self.analysis_scroll = QScrollArea(self)
        self.analysis_scroll.hide()
        self.advanced_section = ExpandableSection("数据、训练与应用", QWidget(), expanded=False)
        self.advanced_section.setParent(self)
        self.advanced_section.hide()
        self.model_scene_label = QLabel("固定结构：RF / XGBoost　｜　可变结构：BiLSTM（已有结构数据）")
        self.model_scene_label.hide()
        self.analysis_empty_hint = QLabel("")
        self.analysis_empty_hint.hide()

        self.analysis_detail_stack = QStackedWidget()
        self.analysis_detail_stack.setObjectName("analysisDetailStack")
        self.analysis_detail_stack.setMinimumHeight(92)
        self.consistency_text = self._text_panel("等待模型测试集结果。")
        self.residual_text = self._text_panel("等待残差数据。")
        self.feature_importance_text = self._text_panel("")
        for widget in (self.consistency_text, self.residual_text, self.feature_importance_text):
            self.analysis_detail_stack.addWidget(widget)
        self.analysis_detail_stack.hide()

        self.workflow_buttons[0].setChecked(True)
        self.workflow_stack.setCurrentIndex(1)
        self._model_manager_dialog = None
        self.lifecycle.connect(
            context.project.simulation_project_payload_changed,
            self._update_dataset_config_summary,
        )

        self.workspace_state.restore_tab("workflow", self.workflow_stack, 1)
        current = max(1, min(self.workflow_stack.currentIndex(), 4))
        self.workflow_stack.setCurrentIndex(current)
        self.workflow_buttons[current - 1].setChecked(True)
        self._refresh_analysis()
        self.lifecycle.single_shot(100, self.refresh_remote)

    def _workflow_scroll(self, content: QWidget, object_name: str) -> QScrollArea:
        """Give each ML task one whole-page vertical scroll owner.

        Compact windows must scroll instead of compressing fixed-height form
        controls into one another.  Horizontal scrolling remains disabled; wide
        data belongs in dedicated tables/windows rather than the task shell.
        """
        scroll = QScrollArea(self)
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content.setMinimumHeight(content.minimumSizeHint().height())
        scroll.setWidget(content)
        return scroll

    def _restore_standard_workspace_chrome(self) -> None:
        if hasattr(self, "page_header"):
            self.page_header.show()
            self.page_header.title_label.setText("代理模型")
            self.page_header.set_subtitle("")
        if hasattr(self, "workflow_bar"):
            self.workflow_bar.show()
        if hasattr(self, "popout_prediction_button"):
            self.popout_prediction_button.hide()
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(
                ui_layout.PAGE_MARGIN, ui_layout.CONTROL_GAP,
                ui_layout.PAGE_MARGIN, ui_layout.CARD_GAP,
            )
            layout.setSpacing(ui_layout.CONTROL_GAP)

    def prepare_prediction_workspace(self) -> None:
        """Show forward prediction as a complete main-workspace task page."""
        if hasattr(self, "page_header"):
            self.page_header.show()
            self.page_header.title_label.setText("正向预测")
            self.page_header.set_subtitle("")
        if hasattr(self, "workflow_bar"):
            self.workflow_bar.hide()
        if hasattr(self, "popout_prediction_button"):
            self.popout_prediction_button.show()
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(
                ui_layout.PAGE_MARGIN, ui_layout.CONTROL_GAP,
                ui_layout.PAGE_MARGIN, ui_layout.CARD_GAP,
            )
            layout.setSpacing(ui_layout.CONTROL_GAP)
        self._set_workflow_step(4)
        self.workflow_stack.setCurrentIndex(4)
        self.workflow_stack.setMinimumHeight(0)
        QTimer.singleShot(0, lambda: getattr(self, "prediction_button", self).setFocus())

    def prepare_prediction_task_window(self) -> None:
        """Present forward prediction as a focused task beside the simulation workbench.

        Model construction remains the explicit data -> training -> comparison flow.
        This mode hides that workflow chrome so forward prediction opens directly,
        without creating another landing page or duplicating the simulation plots.
        """
        if hasattr(self, "page_header"):
            self.page_header.hide()
        if hasattr(self, "popout_prediction_button"):
            self.popout_prediction_button.hide()
        if hasattr(self, "workflow_bar"):
            self.workflow_bar.hide()
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(12, 8, 12, 12)
            layout.setSpacing(8)
        self._set_workflow_step(4)
        self.workflow_stack.setCurrentIndex(4)
        self.workflow_stack.setMinimumHeight(0)
        QTimer.singleShot(0, lambda: getattr(self, "prediction_button", self).setFocus())

    def _open_model_manager(self) -> None:
        """Enter the explicit data/training workflow instead of expanding a long page."""
        self._set_workflow_step(1)

    def _scroll_to_training_section(self) -> None:
        self._set_workflow_step(2)

    def _build_analysis_main(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_layout.CONTROL_GAP)

        toolbar = QHBoxLayout()
        self.analysis_view_group = QButtonGroup(self)
        self.analysis_view_group.setExclusive(True)
        self.analysis_view_buttons: list[SecondaryButton] = []
        for index, label in enumerate(("预测效果", "预测误差", "影响因素")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._select_analysis_view(i))
            self.analysis_view_group.addButton(button, index)
            self.analysis_view_buttons.append(button)
            toolbar.addWidget(button)
        self.analysis_view_buttons[0].setChecked(True)
        toolbar.addStretch(1)
        self.analysis_popout_button = QToolButton()
        self.analysis_popout_button.setObjectName("plotIconTool")
        self.analysis_popout_button.setIcon(icon("popout", theme.TEXT_SECONDARY, 17))
        self.analysis_popout_button.setIconSize(QSize(17, 17))
        self.analysis_popout_button.setToolTip("在独立科研图窗中查看当前分析图")
        self.analysis_popout_button.clicked.connect(lambda: open_workspace_plot(self, self.analysis_result))
        toolbar.addWidget(self.analysis_popout_button)
        layout.addLayout(toolbar)

        self.analysis_result = ResultWorkspace()
        self.analysis_result.setMinimumHeight(ui_layout.PLOT_MIN_HEIGHT)
        self.analysis_result.setMaximumHeight(ui_layout.PLOT_PREFERRED_HEIGHT)
        self.analysis_result.set_single_view_only(True)
        self.analysis_result.set_toolbar_visible(False)
        self.analysis_result.set_maximize_controls_visible(False)
        self.analysis_result.set_pane_title_visible(False)
        self.analysis_result.set_pane_source_visible(False)
        self.analysis_result.set_result(
            0,
            "预测效果",
            {
                "kind": "empty",
                "message": "这里会显示模型预测与完整仿真的对比\n\n点越接近理想线，说明预测越准确\n训练模型并完成独立测试后，本区域会直接替换为真实结果",
            },
        )
        layout.addWidget(self.analysis_result, 1)
        return panel

    def _build_explanation_panel(self) -> QWidget:
        panel = QWidget()
        self.model_summary_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        risk = Card("模型摘要", compact=True)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(3)
        self.compatibility = InfoRow("当前模型", "等待读取")
        self.model_r2 = InfoRow("R²", "—")
        self.model_rmse = InfoRow("RMSE", "—")
        self.training_domain = InfoRow("是否超出训练范围", "—")
        self.formal_state = InfoRow("完整仿真", "等待")
        rows = (self.compatibility, self.model_r2, self.model_rmse, self.training_domain, self.formal_state)
        self.model_summary_rows = rows
        for index, row in enumerate(rows):
            grid.addWidget(row, index // 3, index % 3)
        risk.body.addLayout(grid)
        badge_row = QHBoxLayout()
        badge_row.addStretch(1)
        self.model_quality_badge = Badge("— 未评估", "info")
        badge_row.addWidget(self.model_quality_badge)
        risk.body.addLayout(badge_row)
        self.model_conclusion = QLabel("选择模型后显示是否适合继续用于解释、正向预测和优化筛选。")
        self.model_conclusion.setWordWrap(True)
        self.model_conclusion.setObjectName("mutedText")
        risk.body.addWidget(self.model_conclusion)
        layout.addWidget(risk)

        details = CollapsiblePanel("详细指标", expanded=False)
        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setHorizontalSpacing(18)
        detail_grid.setVerticalSpacing(3)
        self.prediction_gap = InfoRow("当前系统偏差", "—")
        self.model_mae = InfoRow("MAE", "—")
        self.high_efficiency_mae = InfoRow("高效率区 MAE", "—")
        self.model_samples = InfoRow("测试样本", "—")
        for index, row in enumerate((self.prediction_gap, self.model_mae, self.high_efficiency_mae, self.model_samples)):
            detail_grid.addWidget(row, index // 2, index % 2)
        details.content_layout.addLayout(detail_grid)
        self.model_details_panel = details

        # 兼容旧刷新逻辑，但不再把长文字常驻在结果页。
        self.profile_text = QLabel(); self.profile_text.hide()
        self.explanation_text = QLabel(); self.explanation_text.hide()
        self.risk_text = QLabel(); self.risk_text.hide()
        return panel

    def _build_advanced_section(self) -> ExpandableSection:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(7)
        toolbar = QHBoxLayout()
        self.workflow_group = QButtonGroup(self)
        self.workflow_group.setExclusive(True)
        self.workflow_buttons: list[SecondaryButton] = []
        for index, label in enumerate(("数据与特征", "模型训练", "版本与应用")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._set_workflow_step(i))
            self.workflow_group.addButton(button, index)
            self.workflow_buttons.append(button)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        refresh = SecondaryButton("刷新")
        refresh.clicked.connect(lambda: self.refresh_remote(force=True))
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        self.workflow_stack = LazyStackedWidget()
        self.workflow_stack.add_lazy_widget(self._dataset, "正在准备数据与特征工作区…")
        self.workflow_stack.add_lazy_widget(self._training, "打开训练工具时再加载图表。")
        self.workflow_stack.add_lazy_widget(self._models_page, "打开模型版本时再加载列表。")
        layout.addWidget(self.workflow_stack, 1)
        return ExpandableSection(
            "数据、训练与应用",
            widget,
            expanded=False,
        )

    @staticmethod
    def _text_panel(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("resultDetailText")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _select_analysis_view(self, index: int) -> None:
        index = max(0, min(int(index), len(self.analysis_view_buttons) - 1))
        self.analysis_result.select_result(index)
        self.analysis_detail_stack.setCurrentIndex(index)
        if 0 <= index < len(self.analysis_view_buttons):
            self.analysis_view_buttons[index].setChecked(True)

    def _refresh_analysis(self, *_args) -> None:
        if not bool(getattr(self, "_page_active", False)):
            self._analysis_refresh_pending = True
            return
        self._analysis_refresh_pending = False
        profile = self.context.project.research_profile
        self.profile_text.setText(research_profile_text(profile))
        # 页面标题只说明当前工作区，不再把研究 profile 或内部字段当作“方案/任务名称”长期展示。
        if self.workflow_stack.currentIndex() != 4:
            self.research_header.setText("数据准备 → 模型训练 → 模型比较 → 预测")

        quality = current_model_quality(self.context.registry)
        result = latest_optimization_result(self.context.tasks)
        status = str(result.get("status", "")) if result else ""
        self._set_info(self.formal_state, "完整仿真", "已完成" if status == "completed" else (status or "等待"))

        model_name = quality.get("name") or quality.get("model_type") or quality.get("model_id")
        has_model = bool(model_name)
        if hasattr(self, "model_summary_panel"):
            self.model_summary_panel.setVisible(True)
        for row in getattr(self, "model_summary_rows", ())[1:]:
            row.setVisible(has_model)
        if hasattr(self, "model_quality_badge"):
            self.model_quality_badge.setVisible(has_model)
        if hasattr(self, "model_details_panel"):
            self.model_details_panel.setVisible(has_model)
        available_models = list(getattr(self.context.registry, "models", []) or [])
        current_text = str(model_name) if model_name else ("尚未选择" if available_models else "还没有模型")
        self._set_info(self.compatibility, "当前模型", current_text)
        r2 = quality.get("r2")
        mae = quality.get("mae")
        rmse = quality.get("rmse")
        high_mae = quality.get("high_efficiency_mae")
        
        test_metrics = dict(quality.get("test_metrics", {}) or {})
        if not isinstance(r2, (int, float)):
            r2 = test_metrics.get("r2")
        if not isinstance(mae, (int, float)):
            mae = test_metrics.get("mae")
        if not isinstance(rmse, (int, float)):
            rmse = test_metrics.get("rmse")
        self._set_info(self.model_r2, "测试集 R²", f"{float(r2):.4f}" if isinstance(r2, (int, float)) else "—")
        if hasattr(self, "model_quality_badge"):
            if isinstance(r2, (int, float)) and float(r2) < 0:
                self.model_quality_badge.setText("× 表现较差")
                self.model_quality_badge.set_tone("danger")
            elif isinstance(r2, (int, float)) and float(r2) >= 0.8:
                self.model_quality_badge.setText("✓ 表现较好")
                self.model_quality_badge.set_tone("success")
            elif isinstance(r2, (int, float)):
                self.model_quality_badge.setText("⚠ 需要结合误差判断")
                self.model_quality_badge.set_tone("warning")
            else:
                self.model_quality_badge.setText("— 未评估")
                self.model_quality_badge.set_tone("info")
        if hasattr(self, "model_conclusion"):
            if isinstance(r2, (int, float)) and float(r2) < 0.0:
                self.model_conclusion.setText("当前模型与独立测试结果一致性不足，不建议用于 SHAP 指导或优化筛选。")
            elif isinstance(r2, (int, float)) and float(r2) < 0.60:
                self.model_conclusion.setText("当前模型仅适合探索，不建议据此直接调整当前系统。")
            elif isinstance(r2, (int, float)) and float(r2) < 0.80:
                self.model_conclusion.setText("当前模型可以作为辅助参考，候选结果仍需完整仿真确认。")
            elif isinstance(r2, (int, float)):
                self.model_conclusion.setText("当前模型可用于辅助筛选与解释，最终结论仍以正式物理仿真为准。")
            else:
                self.model_conclusion.setText(
                    "还没有选择当前模型。点击右上角“训练与版本”，可以选择已有模型或开始训练。"
                    if not has_model else
                    "缺少独立测试指标，暂不建议使用模型指导研究。"
                )
        self._set_info(self.model_mae, "MAE", f"{float(mae):.4g}" if isinstance(mae, (int, float)) else "—")
        self._set_info(self.model_rmse, "RMSE", f"{float(rmse):.4g}" if isinstance(rmse, (int, float)) else "—")
        self._set_info(
            self.high_efficiency_mae,
            "高效率区 MAE",
            f"{float(high_mae):.4g}" if isinstance(high_mae, (int, float)) else "未计算",
        )

        evaluation = dict(quality.get("evaluation", {}) or {})
        actual_raw = list(evaluation.get("actual", []) or [])
        predicted_raw = list(evaluation.get("predicted", []) or [])

        def first_target(rows):
            values = []
            for row in rows:
                if isinstance(row, (list, tuple)):
                    if row:
                        values.append(float(row[0]))
                elif isinstance(row, (int, float)):
                    values.append(float(row))
            return values

        actual = first_target(actual_raw)
        predicted = first_target(predicted_raw)
        count = min(len(actual), len(predicted))
        actual, predicted = actual[:count], predicted[:count]
        residual = [p - a for a, p in zip(actual, predicted)]
        self._set_info(self.model_samples, "测试样本", str(count) if count else "—")
        influences, influence_source = top_influences(self.context.tasks, self.context.registry, limit=8)
        # 视图只在当前模型真正有对应数据时出现。不可生成的“影响因素”不再
        # 留一个空白页和无效导出工具。
        if hasattr(self, "analysis_view_buttons") and len(self.analysis_view_buttons) >= 3:
            self.analysis_view_buttons[2].setVisible(bool(influences))
            if not influences and self.analysis_view_group.checkedId() == 2:
                self._select_analysis_view(0 if count else 1)
        has_renderable_analysis = bool(count or influences)
        if hasattr(self, "analysis_main_panel"):
            self.analysis_main_panel.setVisible(True)
        # 只显示当前真实可用的视图；主槽位本身始终存在。
        if hasattr(self, "analysis_view_buttons") and len(self.analysis_view_buttons) >= 3:
            self.analysis_view_buttons[0].setVisible(bool(count) or not has_renderable_analysis)
            self.analysis_view_buttons[1].setVisible(bool(count))
            self.analysis_view_buttons[2].setVisible(bool(influences))
            if not has_renderable_analysis:
                self.analysis_view_buttons[0].setChecked(True)
                self.analysis_result.set_result(
                    0,
                    "预测效果",
                    {
                        "kind": "empty",
                        "message": (
                            "这个模型还没有独立测试结果。\n\n1. 点击顶部“数据”或“训练”\n2. 重新训练并查看测试结果\n3. 测试完成后，这里会直接显示预测值和完整仿真的对比"
                            if model_name
                            else "还没有选择当前模型。\n\n1. 点击顶部“模型比较”或“训练”\n2. 选择已有模型，或先训练一个模型\n3. 确认测试结果后点“设为当前模型”\n\n选好后，这里会直接显示预测效果。"
                        ),
                    },
                )
                self.analysis_result.select_result(0)

        metadata = dict(result.get("metadata", {}) or {}) if result else {}
        metrics = dict(result.get("best_metrics", {}) or {}) if result else {}
        formal_value = metrics.get("coupling_efficiency")
        predicted_value = metadata.get(
            "surrogate_predicted_efficiency",
            metadata.get("predicted_efficiency", metadata.get("model_prediction")),
        )
        current_point = None
        current_residual = None
        if isinstance(formal_value, (int, float)) and isinstance(predicted_value, (int, float)):
            current_point = [float(formal_value), float(predicted_value)]
            current_residual = [float(formal_value), float(predicted_value) - float(formal_value)]
            self._set_info(self.prediction_gap, "当前系统偏差", f"{current_residual[1]:+.4g}")
        else:
            gap = metadata.get("surrogate_error", metadata.get("prediction_error"))
            self._set_info(self.prediction_gap, "当前系统偏差", f"{float(gap):+.4g}" if isinstance(gap, (int, float)) else "—")

        in_domain = metadata.get("within_training_domain", metadata.get("in_training_domain"))
        self._set_info(
            self.training_domain,
            "是否超出训练范围",
            "否" if in_domain is True else ("是" if in_domain is False else "未判定"),
        )

        if count:
            metric_labels = {}
            if isinstance(r2, (int, float)):
                metric_labels["R²"] = f"{float(r2):.4f}"
            if isinstance(rmse, (int, float)):
                metric_labels["RMSE"] = f"{float(rmse):.4g}"
            self.analysis_result.set_result(
                0,
                "预测效果",
                {
                    "kind": "validation_scatter",
                    "simple": True,
                    "actual": actual,
                    "predicted": predicted,
                    "current_point": current_point,
                    "metrics": metric_labels,
                    "title": "",
                    "x_label": "完整仿真结果",
                    "y_label": "模型预测",
                },
            )
            self.analysis_result.set_result(
                1,
                "预测误差",
                {
                    "kind": "residual",
                    "simple": True,
                    "predicted": predicted,
                    "residual": residual,
                    "actual": actual,
                    "current_point": current_residual,
                    "metrics": metric_labels,
                    "title": "",
                    "x_label": "完整仿真结果",
                    "y_label": "预测值 − 仿真值",
                },
            )
            if influences:
                labels = [name for name, _value in influences]
                values = [float(value) for _name, value in influences]
                self.analysis_result.set_result(
                    2,
                    "影响因素",
                    {
                        "kind": "barh",
                        "labels": labels,
                        "values": values,
                        "show_values": True,
                        "title": "",
                        "x_label": "相对影响",
                        "source": influence_source,
                    },
                )
            else:
                # 不可用视图直接隐藏；不要给用户展示一整块无法生成的空图。
                self.analysis_result.set_result(2, "影响因素", {"kind": "empty", "message": ""})
            mean_residual = sum(residual) / len(residual)
            self.consistency_text.setText("")
            self.residual_text.setText(f"{mean_residual:+.4g}")
            self.explanation_text.setText("")
            self.risk_text.setText("")
        else:
            if model_name:
                message = (
                    "这个模型还没有可用的独立测试预测。\n\n"
                    "1. 点击顶部“数据”或“训练”\n"
                    "2. 重新训练并完成独立测试\n"
                    "3. 测试完成后，这里会直接显示预测值和完整仿真的对比"
                )
            else:
                message = (
                    "还没有选择当前模型。\n\n"
                    "1. 点击顶部“模型比较”或“训练”\n"
                    "2. 选择已有模型，或先训练一个模型\n"
                    "3. 查看测试结果后点“设为当前模型”\n\n"
                    "选好后，这里会直接显示预测效果。"
                )
            self.analysis_result.set_result(0, "预测效果", {"kind": "empty", "message": message})
            self.analysis_result.set_result(1, "预测误差", {"kind": "empty", "message": message})
            if influences:
                self.analysis_result.set_result(2, "影响因素", {"kind": "barh", "labels": [n for n, _ in influences], "values": [float(v) for _, v in influences], "show_values": True, "title": "", "source": influence_source})
            else:
                self.analysis_result.set_result(2, "影响因素", {"kind": "empty", "message": ""})
            self.consistency_text.setText(message)
            self.residual_text.setText("")
            self.explanation_text.setText("")
            self.risk_text.setText("")

    def _set_workflow_step(self, index: int) -> None:
        index = max(0, min(int(index), self.workflow_stack.count() - 1))
        self.workflow_stack.setCurrentIndex(index)
        if 1 <= index <= len(self.workflow_buttons):
            self.workflow_buttons[index - 1].setChecked(True)
        if index == 1:  # 数据
            self._set_datasets({"items": self.context.registry.datasets})
        elif index == 2:  # 训练
            self._set_datasets({"items": self.context.registry.datasets})
            self._select_training_dataset(self.context.registry.current_dataset_id)
        elif index == 3:  # 模型比较
            self._set_models({"models": self.context.registry.models})
            self._select_model_by_id(self.context.registry.current_model_id)
        elif index == 4:  # 正向预测
            self._set_models({"models": self.context.registry.models})
            model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
            if model_id:
                self._selected_model_id = model_id
                self._select_model_by_id(model_id)
        QTimer.singleShot(0, self._apply_responsive_workflow_layout)

    def _apply_responsive_workflow_layout(self) -> None:
        """Stack the data-preparation task on portrait/narrow windows.

        The normal two-column layout is intentionally dense at desktop widths,
        but at 768 px it forced the selected-dataset action row past the viewport.
        The page already owns one vertical scroll area, so narrow screens should
        grow vertically rather than crop the right-hand task results.
        """
        splitter = self.findChild(QSplitter, "mlDataTaskSplitter")
        if splitter is None:
            return
        try:
            config = splitter.widget(0)
            results = splitter.widget(1)
            compact = self.width() < 900
            if compact:
                splitter.setOrientation(Qt.Orientation.Vertical)
                config.setMinimumWidth(0)
                config.setMaximumWidth(16777215)
                config.setMinimumHeight(600)
                results.setMinimumHeight(620)
                splitter.setMinimumHeight(1230)
                host = splitter.parentWidget()
                if host is not None:
                    host.setMinimumHeight(1230)
                splitter.setSizes([600, 623])
            else:
                splitter.setOrientation(Qt.Orientation.Horizontal)
                config.setMinimumWidth(350)
                config.setMaximumWidth(430)
                config.setMinimumHeight(0)
                results.setMinimumHeight(0)
                splitter.setMinimumHeight(0)
                host = splitter.parentWidget()
                if host is not None:
                    host.setMinimumHeight(0)
                splitter.setSizes([390, max(700, splitter.width() - 390)])
        except RuntimeError:
            return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._apply_responsive_workflow_layout)

    def _select_training_dataset(self, dataset_id: str) -> None:
        if not hasattr(self, "training_dataset"):
            return
        index = self.training_dataset.findData(str(dataset_id or ""))
        if index >= 0:
            self.training_dataset.setCurrentIndex(index)

    def _select_model_by_id(self, model_id: str) -> None:
        if not model_id or not hasattr(self, "models_table"):
            return
        for row, item in enumerate(self.context.registry.models):
            value = str(item.get("model_id", item.get("id", "")))
            if value == model_id:
                self.models_table.selectRow(row)
                self._on_model_selected(row)
                return

    def _registry_datasets_changed(self, records: list) -> None:
        if hasattr(self, "datasets_table") or hasattr(self, "training_dataset"):
            self._set_datasets({"items": records}, publish=False)
        self._refresh_analysis()

    def _registry_models_changed(self, records: list) -> None:
        if hasattr(self, "models_table"):
            self._set_models({"models": records}, publish=False)
        self._refresh_analysis()

    def on_activated(self) -> None:
        self._page_active = True
        self.lifecycle.activated()
        if hasattr(self, "analysis_scroll"):
            self.refresh_remote()
        self._refresh_analysis()
        self._sync_task_context(self.context.tasks.tasks)
        for job_id in list(self._jobs):
            task = self.context.tasks.find_by_job_id(job_id)
            if not task or str(task.get("status", "")) not in {"已完成", "失败", "已取消"}:
                self.job_client.get_status(f"ml.status.{job_id}", job_id)
        if self._jobs and not self._centralized_polling:
            self._poll_timer.start()

    def on_deactivated(self) -> None:
        self._page_active = False
        self._poll_timer.stop()
        self.lifecycle.deactivate()

    def showEvent(self, event) -> None:
        self.on_activated()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def handle_assistant_action(self, action: dict) -> None:
        target = str(dict(action or {}).get("target", "") or "")
        if target in {"machine_learning.build", "machine_learning.data"}:
            self._restore_standard_workspace_chrome()
            self._set_workflow_step(1)
            if hasattr(self, "datasets_table"):
                self.datasets_table.setFocus()
        elif target == "machine_learning.training":
            self._restore_standard_workspace_chrome()
            if not self.advanced_section.isVisible():
                self._open_model_manager()
            # Open the actual training workflow rather than only exposing the
            # parent section.  This is a prepare action: fields are made ready,
            # but the Start Training button is never clicked by the assistant.
            self._set_workflow_step(2)
            # Reuse the project's adopted dataset when available; keep model
            # hyperparameters editable and never click the start button.
            current_dataset = str(getattr(self.context.registry, "current_dataset_id", "") or "")
            if current_dataset and hasattr(self, "training_dataset"):
                index = self.training_dataset.findData(current_dataset)
                if index >= 0:
                    self.training_dataset.setCurrentIndex(index)
            QTimer.singleShot(0, lambda: getattr(self, "training_dataset", self.advanced_section).setFocus())
        elif target == "machine_learning.prediction":
            self._set_workflow_step(4)
            def focus_prediction() -> None:
                button = getattr(self, "prediction_button", None)
                if button is not None:
                    button.setFocus()
                    button.setToolTip("选择可用模型后预测当前工程；预测完成后应回正式仿真验证。")
            QTimer.singleShot(0, focus_prediction)
            QTimer.singleShot(80, focus_prediction)
        elif target in {"machine_learning.current", "machine_learning.current_model", "machine_learning.models"}:
            self._restore_standard_workspace_chrome()
            self._set_workflow_step(3)
            if hasattr(self, "models_table"):
                self.models_table.setFocus()

    def assistant_action_target_widget(self, action: dict):
        target = str(dict(action or {}).get("target", "") or "")
        if target in {"machine_learning.build", "machine_learning.data"}:
            return getattr(self, "datasets_table", self)
        if target == "machine_learning.training":
            return getattr(self, "training_dataset", self)
        if target == "machine_learning.prediction":
            return getattr(self, "prediction_button", self)
        if target in {"machine_learning.current", "machine_learning.current_model", "machine_learning.models"}:
            return getattr(self, "models_table", self)
        return self

    def assistant_context(self) -> dict:
        idx = self.analysis_view_group.checkedId() if hasattr(self, "analysis_view_group") else 0
        view = self.analysis_view_buttons[idx].text() if 0 <= idx < len(getattr(self, "analysis_view_buttons", [])) else ""
        return {
            "page": "代理模型",
            "current_view": view,
            "current_model": self.compatibility.value_label.text() if hasattr(self, "compatibility") and hasattr(self.compatibility, "value_label") else "",
            "current_model_id": str(getattr(self.context.registry, "current_model_id", "") or ""),
            "recent_model_id": str(getattr(self.context.registry, "recent_model_id", "") or ""),
            "quality_status": self.model_quality_badge.text() if hasattr(self, "model_quality_badge") else "",
            "task": self.research_header.text() if hasattr(self, "research_header") else "",
            "r2": self.model_r2.value_label.text() if hasattr(self, "model_r2") and hasattr(self.model_r2, "value_label") else "",
            "rmse": self.model_rmse.value_label.text() if hasattr(self, "model_rmse") and hasattr(self.model_rmse, "value_label") else "",
            "mae": self.model_mae.value_label.text() if hasattr(self, "model_mae") and hasattr(self.model_mae, "value_label") else "",
            "training_domain": self.training_domain.value_label.text() if hasattr(self, "training_domain") and hasattr(self.training_domain, "value_label") else "",
            "formal_validation": self.formal_state.value_label.text() if hasattr(self, "formal_state") and hasattr(self.formal_state, "value_label") else "",
            "current_plot": self.analysis_result.current_data() if hasattr(self, "analysis_result") else {},
        }

    def dispose_page(self) -> None:
        self.workspace_state.save_tab("workflow", self.workflow_stack)
        self._poll_timer.stop()
        dispose = getattr(self.workflow_stack, "dispose", None)
        if callable(dispose):
            dispose()
        for worker in tuple(self._background_workers):
            for method_name in ("cancel", "requestInterruption", "quit"):
                method = getattr(worker, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
        self._background_workers.clear()
        self.lifecycle.dispose()
