from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared import layout_tokens as ui_layout
from frontend_pyside.shared.icons import icon
from frontend_pyside.shared.components.unit_spinbox import UnitAwareDoubleSpinBox
from frontend_pyside.infrastructure.api.clients import JobClient, OptimizationClient, ScanClient, ToleranceClient
from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.shared.background import BackgroundPreparer
from frontend_pyside.shared.components.basic import (
    Card,
    CollapsiblePanel,
    FormGrid,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.components.foundation import PageHeader
from frontend_pyside.shared.lazy_widgets import CurrentPageStackedWidget, LazyStackedWidget
from frontend_pyside.shared.lifecycle import ManagedPageResources
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.dialogs.plot_actions import open_workspace_plot
from frontend_pyside.shared.research_summary import latest_optimization_result
from frontend_pyside.shared.settings import WorkspaceStateStore
from frontend_pyside.shared.display_names import parameter_label
from frontend_pyside.shared.task_display import MonotonicProgress
from .experiment_validation import ExperimentValidationMixin
from .experiment_validation_data import comparison_metrics, row_diagnostics
from .tolerance_analysis import OptimizationToleranceMixin
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
    ExperimentValidationMixin,
    OptimizationToleranceMixin,
    OptimizationViewMixin,
    OptimizationSubmitMixin,
    OptimizationJobMixin,
    OptimizationResultMixin,
    QWidget,
):


    navigateRequested = Signal(str)
    previewRequested = Signal(dict, str)
    previewCleared = Signal()
    popoutRequested = Signal(str, object)

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
        self.tolerance_client = ToleranceClient(self.api_client)
        self.job_client = JobClient(self.api_client)
        self.job_watcher = context.services.job_watcher
        self._centralized_polling = bool(getattr(self.job_watcher, "centralized_polling", False))
        self._jobs: dict[str, dict] = {}
        self._active_guided_mode = ""
        self._last_selected_contents: list[str] = []
        self._page_active = False
        self._pending_result_render: tuple[str, dict] | None = None
        self._has_research_result = False
        # Tracks which result owns the main/compact summary.  Shared task refreshes
        # must never mix an older optimisation summary into a newer scan result.
        self._active_research_result_kind = ""
        self._scan_refinement_pending = False
        self._scan_refinement_parameter = ""
        self._progress_tracker = MonotonicProgress()
        self._active_research_job_id = ""
        self._structure_models: list[dict] = []
        self._pending_structure_candidate_profile: dict | None = None
        self._inverse_design_active = False
        self._ml_inverse_prediction_active = False
        self._latest_best_variables: dict[str, float] = {}
        self._task_window_target = ""

        self._poll_timer = self.lifecycle.manage_timer(QTimer(self))
        self._poll_timer.setProperty("stopWhenHidden", True)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_jobs)

        self.lifecycle.connect(self.api_client.completed, self._api_completed)
        # failed_detail preserves 422 field-level validation context.  Connecting
        # both failed and failed_detail would handle the same request twice.
        self.lifecycle.connect(self.api_client.failed_detail, self._api_failed_detail)
        self.lifecycle.connect(self.job_watcher.job_progress, self._on_ws_progress)
        self.lifecycle.connect(self.job_watcher.job_completed, self._on_ws_completed)
        self.lifecycle.connect(self.job_watcher.job_failed, self._on_ws_failed)
        self.lifecycle.connect(context.tasks.tasks_changed, self._sync_task_context)
        self.lifecycle.connect(context.tasks.task_result_changed, self._shared_result_changed)
        if hasattr(context.project, "findings_changed"):
            self.lifecycle.connect(context.project.findings_changed, self._refresh_evidence_panel)
        if hasattr(context.registry, "current_model_changed"):
            self.lifecycle.connect(context.registry.current_model_changed, lambda _model_id: self._sync_ml_inverse_model_state())
        if hasattr(context.registry, "models_changed"):
            self.lifecycle.connect(context.registry.models_changed, lambda _models: self._sync_ml_inverse_model_state())
        self.lifecycle.connect(self._result_preparer.completed, self._prepared_result_ready)
        self.lifecycle.connect(self._result_preparer.failed, self._prepared_result_failed)

        root = QVBoxLayout(self)
        self.root_layout = root
        root.setContentsMargins(
            ui_layout.PAGE_MARGIN,
            ui_layout.CONTROL_GAP,
            ui_layout.PAGE_MARGIN,
            ui_layout.CARD_GAP,
        )
        root.setSpacing(ui_layout.CONTROL_GAP)

        self._build_header(root)

        mode_bar = QWidget()
        self.workspace_mode_bar = mode_bar
        mode_layout = QHBoxLayout(mode_bar)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(7)
        self.workspace_mode_group = QButtonGroup(self)
        self.workspace_mode_group.setExclusive(True)
        self.parameter_workspace_button = SecondaryButton("参数研究")
        self.research_workspace_button = SecondaryButton("自动优化")
        self.validation_workspace_button = SecondaryButton("物理反向设计")
        self.parameter_workspace_button.setToolTip("进入参数研究，查看参数响应、优化前后、收敛、候选和相关性结果")
        self.research_workspace_button.setToolTip("按目标搜索更优参数组合")
        self.validation_workspace_button.setToolTip("按目标性能进行物理搜索并验证候选")
        self.parameter_workspace_button.setCheckable(True)
        self.parameter_workspace_button.clicked.connect(self._open_parameter_research_workspace)
        mode_layout.addWidget(self.parameter_workspace_button)
        for index, button in enumerate((self.research_workspace_button, self.validation_workspace_button), start=1):
            button.setCheckable(True)
            self.workspace_mode_group.addButton(button, index)
            button.clicked.connect(lambda checked=False, i=index: self._select_core_optimization_task(i - 1))
            mode_layout.addWidget(button)
        self.workspace_mode_group.addButton(self.parameter_workspace_button, 0)
        # 容差分析属于候选结果的后续分析，不作为一级入口。
        self.tolerance_workspace_button = SecondaryButton("容差分析")
        self.tolerance_workspace_button.setCheckable(True)
        self.tolerance_workspace_button.hide()
        mode_layout.addStretch(1)
        self.research_workspace_button.setChecked(True)

        # Keep task switching and header actions on one compact top row.  The
        # page title/subtitle are intentionally hidden, so a separate header row
        # would only leave an empty band above the workspace.
        root.removeWidget(self.page_header)
        root.removeWidget(mode_bar)
        top_bar = QWidget(self)
        top_bar.setObjectName("optimizationTopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(ui_layout.CONTROL_GAP)
        top_layout.addWidget(mode_bar, 0)
        top_layout.addStretch(1)
        top_layout.addWidget(self.page_header, 0)
        root.insertWidget(0, top_bar)

        # Settings and results keep independent vertical ownership.  Long,
        # expandable configuration stays scrollable without moving or squeezing
        # the result canvas beside it.
        self.research_workspace = QWidget()
        research_workspace_layout = QVBoxLayout(self.research_workspace)
        research_workspace_layout.setContentsMargins(0, 0, 0, 0)
        research_workspace_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("optimizationTaskSplitter")
        self.main_splitter.setHandleWidth(6)
        self.main_splitter.setChildrenCollapsible(False)

        research_content = QWidget()
        self.task_content = research_content
        research_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        research_scroll = QScrollArea()
        self.research_scroll = research_scroll
        self.settings_scroll = research_scroll
        research_scroll.setObjectName("optimizationSettingsScroll")
        research_scroll.setWidgetResizable(True)
        research_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        research_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        research_scroll.setFrameShape(QFrame.Shape.NoFrame)
        research_scroll.setMinimumWidth(ui_layout.TASK_SETTINGS_MIN_WIDTH)
        research_scroll.setMaximumWidth(ui_layout.TASK_SETTINGS_MAX_WIDTH)

        research_content.setObjectName("optimizationSettingsColumn")
        research_layout = QVBoxLayout(research_content)
        self.task_content_layout = research_layout
        research_layout.setContentsMargins(0, 0, 0, 0)
        research_layout.setSpacing(ui_layout.CONTROL_GAP)
        research_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.settings_panel = self._build_settings_panel()
        research_layout.addWidget(self.settings_panel, 0)
        if hasattr(self, "evidence_panel"):
            research_layout.addWidget(self.evidence_panel, 0)
        if hasattr(self, "more_settings_panel"):
            research_layout.addWidget(self.more_settings_panel, 0)
        research_layout.addStretch(1)
        research_scroll.setWidget(research_content)

        result_host = QWidget()
        result_host.setObjectName("optimizationResultHost")
        result_layout = QVBoxLayout(result_host)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(ui_layout.CONTROL_GAP)
        self.main_result_panel = self._build_main_result_panel()
        result_layout.addWidget(self.main_result_panel, 1)
        self.inline_tolerance_panel = self._tolerance_page()
        self.inline_tolerance_panel.setVisible(False)
        self.inline_tolerance_panel.setObjectName("inlineToleranceAnalysis")
        result_layout.addWidget(self.inline_tolerance_panel, 1)

        self.main_splitter.addWidget(research_scroll)
        self.main_splitter.addWidget(result_host)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([ui_layout.TASK_SETTINGS_PREFERRED_WIDTH, 960])
        research_workspace_layout.addWidget(self.main_splitter, 1)

        # Compatibility summary continues to receive result updates, but is not a
        # permanent third column.
        self.summary_panel = self._build_summary_panel()
        self.summary_panel.setParent(self)
        self.summary_panel.hide()

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self.research_workspace)
        self.workspace_stack.addWidget(self._build_experiment_validation_page())
        root.addWidget(self.workspace_stack, 1)
        self._responsive_band = ""
        self.lifecycle.single_shot(0, self._apply_responsive_layout)

        self._connect_research_controls()
        # Expanded/collapsed settings update the left column's scroll extent.
        for panel in self.findChildren(CollapsiblePanel):
            if hasattr(panel, "toggle"):
                panel.toggle.toggled.connect(lambda _on=False: QTimer.singleShot(0, self._sync_task_content_height))
        self._research_options_changed()
        # The primary workspace defaults to Auto Optimization; parameter research
        # is also available directly from the same top-level task switcher.
        # Only the full Optimization workspace defaults to Auto Optimization.
        # Embedded modeless task pages are targeted by OptimizationTaskWindow.set_target();
        # an unconditional deferred switch here used to overwrite tolerance/scan/validation
        # task windows after they had already been prepared.
        if not (self.parent() is not None and self.parent().objectName() == "optimizationTaskWindow"):
            QTimer.singleShot(0, self._initialize_default_optimization_task)
        QTimer.singleShot(0, self._sync_task_content_height)
        self._refresh_user_summary()
        self._refresh_evidence_panel()
        self.compare_dialog = None
        self.history_dialog = None

    def _initialize_default_optimization_task(self) -> None:
        """Select the default only when no caller has already prepared a task."""
        if not str(getattr(self, "_task_window_target", "") or ""):
            self._select_core_optimization_task(0)

    
    def _refresh_evidence_panel(self, *_args) -> None:
        self._update_fixed_selection_summary()
        if not hasattr(self, "evidence_text"):
            return
        project_context = self.context.project
        current = project_context.findings_for(current_only=True) if hasattr(project_context, "findings_for") else []
        stale = [row for row in getattr(project_context, "findings", []) if str(row.get("status", "")) == "需更新"]
        self.evidence_panel.toggle.setText(f"已有分析（{len(current)}）" if current else "已有分析")
        if not current:
            suffix = f"；另有 {len(stale)} 条旧结果需要重新计算。" if stale else "。"
            self.evidence_text.setText("当前系统还没有可直接使用的分析结果" + suffix)
            return
        lines = []
        for row in current[:6]:
            parameter = str(row.get("display_name") or row.get("parameter") or "候选结果")
            source = str(row.get("source") or "分析")
            status = str(row.get("status") or "当前")
            lines.append(f"{parameter}　{source} · {status}")
        if stale:
            lines.append(f"另有 {len(stale)} 条旧结果需要重新计算")
        self.evidence_text.setText("\n".join(lines))

    def _select_core_optimization_task(self, index: int) -> None:
        """Keep the primary Optimization workspace focused on its core tasks.

        Do not route the main page through ``prepare_task_window``: that method is
        intentionally destructive/focused for reusable modeless task windows and
        used to hide result panes or overwrite a task window target on the next
        event-loop turn.  The full workspace only changes the active task state.
        """
        index = 0 if int(index) <= 0 else 1
        target = "optimization.variables" if index == 0 else "optimization.inverse_design"
        self.workspace_stack.setCurrentIndex(0)
        self.setProperty("taskWindowMode", False)
        self._task_window_target = target
        if hasattr(self, "main_splitter") and self.main_splitter.count() >= 2:
            self.main_splitter.widget(0).show()
            self.main_splitter.widget(1).show()
        if hasattr(self, "main_result_panel"):
            self.main_result_panel.show()
        if hasattr(self, "inline_tolerance_panel"):
            self.inline_tolerance_panel.hide()
        self._reset_focused_task_state(target)
        self.handle_assistant_action({"target": target, "level": "prepare"})
        self.workspace_mode_bar.show()
        self.parameter_workspace_button.setChecked(False)
        self.research_workspace_button.setChecked(index == 0)
        self.validation_workspace_button.setChecked(index == 1)
        self.page_header.show()
        self.page_header.title_label.setText("优化")
        self.page_header.set_subtitle("")
        self.popout_task_button.show()
        if hasattr(self, "evidence_panel"):
            self.evidence_panel.hide()
        if hasattr(self, "more_settings_panel"):
            self.more_settings_panel.show()
        # Fixed/variable structure and legacy research-mode toggles are expert
        # implementation details, not permanent first-screen navigation.
        self.fixed_structure_button.setChecked(True)
        self._set_research_form_row_visible(getattr(self, "structure_label", None), False)
        self._set_research_form_row_visible(getattr(self, "research_mode_label", None), False)
        if hasattr(self, "focus_search_button"):
            self.focus_search_button.hide()
        # Remove legacy “research” wording from the two focused optimization tasks.
        if hasattr(self, "research_settings_card"):
            self.research_settings_card.title_label.setText("优化设置" if index == 0 else "反向设计设置")
        if hasattr(self, "guided_goal_label"):
            self.guided_goal_label.setText("优化目标" if index == 0 else "设计目标")
        if hasattr(self, "parameter_selection_card"):
            self.parameter_selection_card.title_label.setText("优化变量" if index == 0 else "允许调整")
        if hasattr(self, "choose_parameters_button"):
            self.choose_parameters_button.setText("选择优化变量" if index == 0 else "编辑设计变量")
        task_title = self.TASK_TITLES.get(target, "自动优化")
        self._configure_result_tabs_for_task(task_title)
        self._sync_advanced_task_copy(task_title)
        self._responsive_band = ""
        QTimer.singleShot(0, self._sync_task_content_height)
        QTimer.singleShot(0, self._apply_responsive_layout)

    def _open_parameter_research_workspace(self) -> None:
        """Expose the existing scan surface as a first-class Optimization task."""
        self.prepare_workspace_task("optimization.scan")
        self.workspace_mode_bar.show()
        self.parameter_workspace_button.setChecked(True)
        self.research_workspace_button.setChecked(False)
        self.validation_workspace_button.setChecked(False)
        self.page_header.show()
        self._sync_advanced_task_copy("参数研究")
        QTimer.singleShot(0, self._sync_task_content_height)
        QTimer.singleShot(0, self._apply_responsive_layout)

    def _set_workspace_mode(self, index: int) -> None:
        index = max(0, min(int(index), self.workspace_stack.count() - 1))
        self.workspace_stack.setCurrentIndex(index)
        if index == 0:
            self.research_workspace_button.setChecked(True)
            self.header_state.set_value("就绪")
        elif index == 1:
            self.validation_workspace_button.setChecked(True)
            self.header_state.set_value("实验验证")
        else:
            self.header_state.set_value("容差分析")

    def _current_research_project_payload(self) -> dict:
        """Use the simulation workspace's live physical inputs when available.

        The project model stores lens structure, while the simulation workspace also
        owns source/fiber/form parameters.  Optimisation, tolerance and validation
        must therefore consume the shared simulation payload rather than silently
        falling back to the structure-only defaults.
        """
        shared = getattr(self.context.project, "simulation_project_payload", {})
        if isinstance(shared, dict) and shared.get("surfaces"):
            return dict(shared)
        return serialize_project(self.context.project.project)

    def _build_header(self, root: QVBoxLayout) -> None:
        project = self.context.project.project
        self.header_best = InlineMetric("当前最佳", "—", "%")
        self.header_best.setVisible(False)
        self.header_state = InlineMetric("状态", "就绪")
        self.popout_task_button = SecondaryButton("独立窗口")
        self.popout_task_button.setToolTip("把当前完整任务切换到非模态窗口，与主仿真工作台联动")
        self.popout_task_button.hide()
        self.popout_task_button.clicked.connect(
            lambda: self.popoutRequested.emit(str(getattr(self, "_task_window_target", "optimization.scan") or "optimization.scan"), self.export_task_state())
        )
        header = PageHeader(
            "优化",
            "",
            actions=[self.header_best, self.header_state, self.popout_task_button],
        )
        self.project_context_label = header.subtitle_label
        self.page_header = header
        self.page_header.title_label.hide()
        self.page_header.subtitle_label.hide()
        self.page_header.setMinimumHeight(0)
        root.addWidget(header)


    TASK_TITLES = {
        "optimization.scan": "参数研究",
        "optimization.tolerance": "容差分析",
        "optimization.variables": "自动优化",
        "optimization.inverse_design": "物理反向设计",
        "optimization.ml_inverse_prediction": "代理模型反向预测",
        "optimization.validation": "实验验证",
    }

    def prepare_workspace_task(self, target: str, payload: dict | None = None) -> None:
        """Open one focused task as a complete main-workspace page.

        The same OptimizationPage is used in both containers.  The floating
        window keeps only first-screen controls; this workspace version restores
        evidence and advanced settings and lets the single outer page scroll when
        those sections are expanded.
        """
        target = str(target or "optimization.scan")
        self.prepare_task_window(target)
        self.setProperty("taskWindowMode", False)
        self._task_window_target = target
        title = self.TASK_TITLES.get(target, "研究任务")
        if hasattr(self, "page_header"):
            self.page_header.show()
            self.page_header.title_label.setText(title)
            self.page_header.set_subtitle("")
        if hasattr(self, "workspace_mode_bar"):
            self.workspace_mode_bar.hide()
        if hasattr(self, "popout_task_button"):
            self.popout_task_button.show()
        if hasattr(self, "evidence_panel"):
            self.evidence_panel.hide()
        if hasattr(self, "more_settings_panel"):
            self.more_settings_panel.show()
        if hasattr(self, "root_layout"):
            self.root_layout.setContentsMargins(ui_layout.PAGE_MARGIN, ui_layout.CONTROL_GAP, ui_layout.PAGE_MARGIN, ui_layout.CARD_GAP)
            self.root_layout.setSpacing(ui_layout.CONTROL_GAP)
        if payload:
            action = {"target": target, "level": "prepare", "payload": dict(payload)}
            self.handle_assistant_action(action)
        self._responsive_band = ""
        QTimer.singleShot(0, self._sync_task_content_height)
        QTimer.singleShot(0, self._apply_responsive_layout)

    def export_task_state(self) -> dict:
        """Small presentation-state snapshot used when moving between containers."""
        state = {
            "goal": self.guided_goal.currentText() if hasattr(self, "guided_goal") else "",
            "target_efficiency": self.inverse_target_efficiency.value() if hasattr(self, "inverse_target_efficiency") else 95.0,
            "variable_structure": bool(getattr(self, "variable_structure_button", None) and self.variable_structure_button.isChecked()),
            "selected_contents": self._selected_contents() if hasattr(self, "fixed_content_boxes") else [],
            "depth_id": self.depth_group.checkedId() if hasattr(self, "depth_group") else 1,
        }
        if hasattr(self, "scan_start"):
            state.update({
                "scan_start": self.scan_start.value(), "scan_stop": self.scan_stop.value(),
                "scan_points": self.scan_points.value(),
            })
        if hasattr(self, "algorithm"):
            state.update({
                "algorithm": self.algorithm.currentText(),
                "iterations": self.iterations.value(),
                "starts": self.starts.value(),
                "tolerance": self.tolerance.value(),
            })
        return state

    def import_task_state(self, state: dict | None) -> None:
        state = dict(state or {})
        if not state:
            return
        if hasattr(self, "guided_goal") and state.get("goal"):
            self.guided_goal.setCurrentText(str(state["goal"]))
        if hasattr(self, "inverse_target_efficiency") and "target_efficiency" in state:
            self.inverse_target_efficiency.setValue(float(state["target_efficiency"]))
        if bool(state.get("variable_structure", False)):
            self.variable_structure_button.setChecked(True)
        else:
            self.fixed_structure_button.setChecked(True)
        selected = {str(item) for item in list(state.get("selected_contents", []) or [])}
        for key, box in getattr(self, "fixed_content_boxes", {}).items():
            box.setChecked(key in selected)
        depth_id = int(state.get("depth_id", 1) or 1)
        depth_button = self.depth_group.button(depth_id) if hasattr(self, "depth_group") else None
        if depth_button is not None:
            depth_button.setChecked(True)
        for name in ("scan_start", "scan_stop", "scan_points"):
            widget = getattr(self, name, None)
            if widget is not None and name in state:
                widget.setValue(state[name])
        if hasattr(self, "algorithm") and state.get("algorithm"):
            self.algorithm.setCurrentText(str(state["algorithm"]))
        for name in ("iterations", "starts", "tolerance"):
            widget = getattr(self, name, None)
            if widget is not None and name in state:
                widget.setValue(state[name])
        self._research_options_changed()
        QTimer.singleShot(0, self._sync_task_content_height)

    def _task_state_label(self, phase: str) -> str:
        """Short, task-specific button copy for submitted/running feedback."""
        target = str(getattr(self, "_task_window_target", "optimization.scan") or "optimization.scan")
        labels = {
            "optimization.scan": {"submitted": "研究已提交", "running": "研究中"},
            "optimization.variables": {"submitted": "优化已提交", "running": "优化中"},
            "optimization.inverse_design": {"submitted": "反向设计已提交", "running": "反向设计中"},
            "optimization.ml_inverse_prediction": {"submitted": "反向预测已提交", "running": "反向预测中"},
            "optimization.tolerance": {"submitted": "分析已提交", "running": "分析中"},
        }
        return labels.get(target, labels["optimization.scan"]).get(str(phase), "任务运行中")

    def _set_research_form_row_visible(self, anchor: QWidget | None, visible: bool) -> None:
        """Show/hide every widget in the FormGrid row containing *anchor*.

        Hiding only the label and field left FormGrid's empty helper cell visible,
        reserving an entire blank row in focused tasks.  That wasted height pushed
        the primary action below compact task windows.
        """
        if anchor is None:
            return
        form = getattr(self, "research_settings_form", None)
        grid = getattr(form, "grid", None) if form is not None else None
        if grid is None:
            anchor.setVisible(bool(visible))
            return
        index = grid.indexOf(anchor)
        if index < 0:
            anchor.setVisible(bool(visible))
            return
        row, _column, _row_span, _column_span = grid.getItemPosition(index)
        for item_index in range(grid.count()):
            item_row, _item_column, _rs, _cs = grid.getItemPosition(item_index)
            if item_row != row:
                continue
            widget = grid.itemAt(item_index).widget()
            if widget is not None:
                widget.setVisible(bool(visible))
        grid.invalidate()
        grid.activate()
        form.updateGeometry()

    def prepare_task_window(self, target: str) -> None:
        """Present this full-capability page as one focused modeless task surface.

        A direct task window must never retain panels from the task that was
        previously shown in the same reusable window.  In particular, direct
        tolerance analysis is a self-contained task rather than a tolerance
        panel stacked underneath an old optimisation result.
        """
        self.setProperty("taskWindowMode", True)
        self._task_window_target = str(target or "optimization.scan")
        if hasattr(self, "page_header"):
            self.page_header.hide()
        if hasattr(self, "workspace_mode_bar"):
            self.workspace_mode_bar.hide()
        if hasattr(self, "popout_task_button"):
            self.popout_task_button.hide()
        # A floating task window is intentionally focused: do not squeeze the
        # legacy evidence/advanced workflow cards into its narrow settings
        # column.  Every capability remains one click away through “完整页面”.
        # The complete workspace page shows these panels again.
        if hasattr(self, "evidence_panel"):
            self.evidence_panel.hide()
        if hasattr(self, "more_settings_panel"):
            self.more_settings_panel.hide()
        if hasattr(self, "root_layout"):
            self.root_layout.setContentsMargins(12, 10, 12, 12)
            self.root_layout.setSpacing(6)

        # Reset reusable task-surface visibility before navigating to the new
        # target.  Without this reset, switching ML inverse -> tolerance could
        # leave the old candidate preview/provenance visible above tolerance.
        if hasattr(self, "main_splitter") and self.main_splitter.count() >= 2:
            self.main_splitter.widget(0).show()
        if hasattr(self, "main_result_panel"):
            self.main_result_panel.show()
        if hasattr(self, "inline_tolerance_panel"):
            self.inline_tolerance_panel.hide()
        if hasattr(self, "tolerance_back_button"):
            self.tolerance_back_button.show()
        if hasattr(self, "tolerance_page_title"):
            self.tolerance_page_title.show()

        self.handle_assistant_action({"target": str(target or "optimization.scan"), "level": "navigate", "payload": {}})

        # When tolerance is launched directly from the toolbox it owns the task
        # surface.  Hide the unrelated research settings/result columns rather
        # than showing tolerance below a stale result.  When tolerance is opened
        # contextually from an optimisation result, _open_tolerance... keeps the
        # normal inline behaviour and the back button remains available.
        if self._task_window_target == "optimization.tolerance":
            if hasattr(self, "main_splitter") and self.main_splitter.count() >= 2:
                self.main_splitter.widget(0).hide()
            if hasattr(self, "main_result_panel"):
                self.main_result_panel.hide()
            if hasattr(self, "inline_tolerance_panel"):
                self.inline_tolerance_panel.show()
            if hasattr(self, "tolerance_back_button"):
                self.tolerance_back_button.hide()
            if hasattr(self, "tolerance_page_title"):
                self.tolerance_page_title.hide()

        title = self.TASK_TITLES.get(str(target), "研究任务")
        if hasattr(self, "ml_model_row"):
            is_ml_inverse = title == "代理模型反向预测"
            self.ml_model_row.setVisible(is_ml_inverse)
            if is_ml_inverse:
                model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
                model = self.context.registry.model(model_id) if model_id and hasattr(self.context.registry, "model") else None
                model_name = str((model or {}).get("name") or (model or {}).get("model_name") or model_id or "未采用模型")
                model_type = str((model or {}).get("model_type") or (model or {}).get("algorithm") or "")
                self.ml_model_value.setText(model_name + (f" · {model_type}" if model_type else ""))
        # In a focused task window the task itself already defines scan/optimize/inverse.
        # Hide the old mode switch instead of asking the user to choose the same thing twice.
        self._set_research_form_row_visible(getattr(self, "research_mode_label", None), False)
        if hasattr(self, "guided_goal_label"):
            self.guided_goal_label.setText({
                "参数研究": "评价指标",
                "自动优化": "优化目标",
                "物理反向设计": "设计目标",
                "代理模型反向预测": "预测目标",
            }.get(title, "任务目标"))
        if getattr(self, "parameter_selection_card", None) is not None and getattr(self.parameter_selection_card, "title_label", None) is not None:
            self.parameter_selection_card.title_label.setText({
                "参数研究": "研究参数",
                "自动优化": "优化变量",
                "物理反向设计": "允许调整",
                "代理模型反向预测": "允许反推",
            }.get(title, "任务参数"))
        if hasattr(self, "choose_parameters_button"):
            self.choose_parameters_button.setText({
                "参数研究": "选择研究参数",
                "自动优化": "选择优化变量",
                "物理反向设计": "选择允许调整变量",
                "代理模型反向预测": "选择允许反推变量",
            }.get(title, "选择参数"))
        if getattr(self.research_settings_card, "title_label", None) is not None:
            self.research_settings_card.title_label.setText({
                "参数研究": "研究设置",
                "自动优化": "优化设置",
                "物理反向设计": "反向设计设置",
                "代理模型反向预测": "反推设置",
            }.get(title, "任务设置"))
        self._configure_result_tabs_for_task(title)
        self._sync_advanced_task_copy(title)
        self._sync_ml_inverse_model_state()
        self._has_research_result = False
        self._reset_focused_task_state(str(target))
        self._refresh_research_preview()
        self._responsive_band = ""
        self._sync_task_content_height()
        QTimer.singleShot(0, self._apply_responsive_layout)
        QTimer.singleShot(0, self._sync_task_content_height)
        # Focus changes and splitter relayout can move the scroll area a few
        # pixels after handle_assistant_action() has already reset it.  A task
        # switch must always open at a clean top edge; otherwise the first-row
        # result buttons look clipped/overlapped in compact windows.
        if hasattr(self, "research_scroll"):
            QTimer.singleShot(0, self._reset_research_scroll_top)
            QTimer.singleShot(25, self._reset_research_scroll_top)

    def _reset_research_scroll_top(self) -> None:
        try:
            scroll = getattr(self, "research_scroll", None)
            if scroll is not None:
                scroll.verticalScrollBar().setValue(0)
        except RuntimeError:
            # Temporary task windows can be destroyed while a deferred layout
            # reset is still queued. This must never produce a shutdown warning.
            pass

    def _sync_advanced_task_copy(self, title: str | None = None) -> None:
        title = str(title or self.TASK_TITLES.get(str(getattr(self, "_task_window_target", "optimization.scan")), "参数研究"))
        panel_titles = {
            "参数研究": "研究范围与高级设置",
            "自动优化": "优化范围与算法",
            "物理反向设计": "设计范围与算法",
            "代理模型反向预测": "反推范围与搜索算法",
        }
        if hasattr(self, "more_settings_panel"):
            self.more_settings_panel.toggle.setText(panel_titles.get(title, "专业与高级设置"))
        if hasattr(self, "optimization_setup_card"):
            mapping = {
                "自动优化": ("优化设置", "编辑优化设置", "高级算法", "编辑优化设置", "高级算法"),
                "物理反向设计": ("物理搜索设置", "编辑设计范围", "搜索算法", "设计范围与约束", "搜索算法"),
                "代理模型反向预测": ("反向预测搜索设置", "编辑反推范围", "搜索算法", "反推范围与约束", "搜索算法"),
            }.get(title, ("优化设置", "编辑优化设置", "高级算法", "编辑优化设置", "高级算法"))
            self.optimization_setup_card.title_label.setText(mapping[0])
            self.auto_edit_settings_button.setText(mapping[1])
            self.auto_advanced_button.setText(mapping[2])
            self.auto_edit_panel.toggle.setText(mapping[3])
            self.auto_algorithm_panel.toggle.setText(mapping[4])

    def _configure_result_tabs_for_task(self, title: str) -> None:
        """Keep the five research-result tabs inside Parameter Research only."""
        buttons = list(getattr(self, "result_view_buttons", []) or [])
        if not buttons:
            return
        if str(title) == "参数研究":
            labels = tuple(getattr(self, "result_view_labels", ()))
            for index, button in enumerate(buttons):
                if index < len(labels):
                    button.setText(labels[index])
                button.setVisible(True)
            buttons[0].setChecked(True)
            return

        first_label = {
            "自动优化": "优化结果",
            "物理反向设计": "候选结果",
            "代理模型反向预测": "候选结果",
        }.get(str(title), "任务结果")
        buttons[0].setText(first_label)
        buttons[0].setVisible(True)
        buttons[0].setChecked(True)
        for button in buttons[1:]:
            button.setVisible(False)

    def _sync_ml_inverse_model_state(self) -> None:
        if not hasattr(self, "ml_model_row"):
            return
        is_ml = str(getattr(self, "_task_window_target", "")) == "optimization.ml_inverse_prediction"
        self.ml_model_row.setVisible(is_ml)
        if not is_ml:
            return
        model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
        model = self.context.registry.model(model_id) if model_id and hasattr(self.context.registry, "model") else None
        model_name = str((model or {}).get("name") or (model or {}).get("model_name") or model_id or "未采用模型")
        model_type = str((model or {}).get("model_type") or (model or {}).get("algorithm") or "")
        self.ml_model_value.setText(model_name + (f" · {model_type}" if model_type else ""))
        if hasattr(self, "start_research_button"):
            self.start_research_button.setEnabled(bool(model_id))
        if hasattr(self, "guided_status"):
            self._set_info(
                self.guided_status, "状态",
                "设置已准备好，可以开始反向预测" if model_id else "请先采用一个可用模型",
            )

    def _reset_focused_task_state(self, target: str) -> None:
        """Clear stale result/progress state when the reusable task surface changes task."""
        target = str(target or "optimization.scan")
        if hasattr(self, "research_progress"):
            self.research_progress.hide()
            self.research_progress.setRange(0, 100)
            self.research_progress.setValue(0)
            self.research_progress.setFormat("%p%")
        if hasattr(self, "detail_panel"):
            self.detail_panel.hide()
        if hasattr(self, "scan_point_actions"):
            self.scan_point_actions.hide()
        for name in ("preview_best_design_button", "clear_preview_button", "apply_best_design_button",
                     "verify_best_design_button", "compact_tolerance_button"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.hide()
        if hasattr(self, "compact_status_hint"):
            self.compact_status_hint.show()
        for name in ("compact_efficiency", "compact_gain", "compact_range"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.hide()
        if hasattr(self, "candidate_table"):
            self.candidate_table.setRowCount(0)
        if hasattr(self, "start_research_button") and hasattr(self.start_research_button, "reset_task_state"):
            self.start_research_button.reset_task_state(self.start_research_button.text())
            if target != "optimization.ml_inverse_prediction":
                self.start_research_button.setEnabled(True)
        activity = {
            "optimization.scan": "尚未开始参数研究。",
            "optimization.variables": "尚未开始自动优化。",
            "optimization.inverse_design": "尚未开始物理反向设计。",
            "optimization.ml_inverse_prediction": "尚未开始代理模型反向预测。",
        }.get(target, "尚未开始任务。")
        if target == "optimization.ml_inverse_prediction":
            model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
            if not model_id:
                activity = "代理模型反向预测需要先采用一个可用模型。"
        if hasattr(self, "activity_label"):
            self.activity_label.setText(activity)
        if target == "optimization.ml_inverse_prediction" and hasattr(self, "guided_status"):
            model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
            self._set_info(
                self.guided_status,
                "状态",
                "设置已准备好，可以开始反向预测" if model_id else "请先采用一个可用模型",
            )
        if hasattr(self, "header_state"):
            self.header_state.set_value("就绪")
        self._sync_ml_inverse_model_state()

    def _selected_candidate_changes(self) -> dict[str, float]:
        candidates = list(getattr(self, "_latest_candidate_variables", []) or [])
        table = getattr(self, "candidate_table", None)
        row = table.currentRow() if table is not None else -1
        if 0 <= row < len(candidates):
            return {str(k): float(v) for k, v in dict(candidates[row] or {}).items() if isinstance(v, (int, float))}
        return {str(k): float(v) for k, v in dict(getattr(self, "_latest_best_variables", {}) or {}).items() if isinstance(v, (int, float))}

    def _preview_best_design(self) -> None:
        changes = self._selected_candidate_changes()
        if not changes:
            self.activity_label.setText("当前还没有可以预览的候选参数。")
            return
        label = "代理模型候选" if bool(getattr(self, "_ml_inverse_prediction_active", False)) else (
            "物理反向设计候选" if bool(getattr(self, "_inverse_design_active", False)) else "优化候选"
        )
        self.previewRequested.emit(changes, label)
        self.activity_label.setText("已把候选发送到主仿真工作台进行临时预览；尚未写入当前系统。")
        if hasattr(self, "clear_preview_button"):
            self.clear_preview_button.show()

    def _preview_selected_scan_point(self) -> None:
        point = getattr(self, "_selected_scan_point", None)
        if not point:
            return
        label = self.scan_param.currentText()
        path = self._path_for_label(label)
        updater = getattr(self.context.project, "update_research_context", None)
        if callable(updater):
            updater(active_parameter_scan={
                "path": path,
                "label": label,
                "unit": self._unit_for_label(label),
                "start": float(self.scan_start.value()),
                "stop": float(self.scan_stop.value()),
                "points": int(self.scan_points.value()),
                "selected": float(point[0]),
            })
        self.previewRequested.emit({path: float(point[0])}, f"参数研究 · {label}")
        self.activity_label.setText("已把所选采样点发送到主仿真工作台临时预览；轴向位置扫描还可直接同步多平面演化范围。")
        if hasattr(self, "clear_preview_button"):
            self.clear_preview_button.show()

    def _clear_external_preview(self) -> None:
        self.previewCleared.emit()
        if hasattr(self, "clear_preview_button"):
            self.clear_preview_button.hide()
        self.activity_label.setText("已退出候选预览，主工作台恢复当前系统。")

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("optimizationSettingsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_layout.CARD_GAP)

        settings = Card("研究设置", compact=True)
        self.research_settings_card = settings
        settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        settings_form = FormGrid(label_width=92)
        self.research_settings_form = settings_form

        mode_widget = QWidget()
        mode_row = QHBoxLayout(mode_widget)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(6)
        self.research_mode_group = QButtonGroup(self)
        self.research_mode_group.setExclusive(True)
        self.parameter_research_button = SecondaryButton("参数研究")
        self.parameter_optimization_button = SecondaryButton("参数优化")
        for idx, button in enumerate((self.parameter_research_button, self.parameter_optimization_button)):
            button.setCheckable(True)
            self.research_mode_group.addButton(button, idx)
            button.setMinimumWidth(96); button.setMaximumWidth(112)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.parameter_research_button.setChecked(True)
        mode_widget.setMaximumWidth(250)
        mode_widget.setToolTip("先研究规律，或直接寻找更优参数")
        self.research_mode_widget = mode_widget
        self.research_mode_label = settings_form.add_row("研究方式", mode_widget)

        structure_widget = QWidget()
        structure_row = QHBoxLayout(structure_widget)
        structure_row.setContentsMargins(0, 0, 0, 0)
        structure_row.setSpacing(6)
        self.structure_group = QButtonGroup(self)
        self.structure_group.setExclusive(True)
        self.fixed_structure_button = SecondaryButton("固定")
        self.variable_structure_button = SecondaryButton("可变")
        for index, button in enumerate((self.fixed_structure_button, self.variable_structure_button)):
            button.setCheckable(True)
            self.structure_group.addButton(button, index)
            button.setMinimumWidth(84); button.setMaximumWidth(96)
            structure_row.addWidget(button)
        structure_row.addStretch(1)
        self.fixed_structure_button.setChecked(True)
        structure_widget.setMaximumWidth(216)
        # FormGrid gives compound fields a fixed row height.  Explicitly reserve
        # the button height so checked/hover borders never spill into the next row.
        structure_widget.setMinimumHeight(40)
        structure_widget.setToolTip("固定结构调参数；可变结构先筛选镜片序列")
        self.structure_widget = structure_widget
        self.structure_label = settings_form.add_row("结构", structure_widget)

        self.guided_goal = QComboBox()
        self.guided_goal.addItems([
            "耦合效率最高",
            "系统效率最高",
            "多波长性能最好",
            "系统更紧凑",
            "综合性能",
        ])
        self.guided_goal.setMaximumWidth(250)
        self.guided_goal.setToolTip("决定扫描/优化的评价指标")
        self.guided_goal_label = settings_form.add_row("研究目标", self.guided_goal)

        self.ml_model_row = QWidget(settings)
        ml_model_row_layout = QHBoxLayout(self.ml_model_row)
        ml_model_row_layout.setContentsMargins(0, 0, 0, 0)
        ml_model_row_layout.setSpacing(ui_layout.CONTROL_GAP)
        self.ml_model_label = QLabel("当前模型", self.ml_model_row)
        self.ml_model_label.setObjectName("propertyFieldLabel")
        self.ml_model_label.setMinimumWidth(78)
        self.ml_model_label.setMaximumWidth(78)
        self.ml_model_value = QLabel("未采用模型", self.ml_model_row)
        self.ml_model_value.setObjectName("compactContext")
        self.ml_model_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ml_model_row_layout.addWidget(self.ml_model_label)
        ml_model_row_layout.addWidget(self.ml_model_value, 1)
        self.ml_model_row.setMinimumHeight(34)
        self.ml_model_row.hide()

        self.inverse_target_efficiency = UnitAwareDoubleSpinBox()
        self.inverse_target_efficiency.setRange(0.0, 100.0)
        self.inverse_target_efficiency.setDecimals(2)
        self.inverse_target_efficiency.setValue(95.0)
        self.inverse_target_efficiency.setTargetUnit("%")
        self.inverse_target_efficiency.setMinimumWidth(196)
        self.inverse_target_efficiency.setMaximumWidth(250)
        self.inverse_target_efficiency.setToolTip("反向设计按此目标搜索参数；结果仍需正式物理仿真验证")
        # This task-specific row is kept outside FormGrid. Hiding/showing a row
        # inside QGridLayout at the 13.5 pt application font caused the grid to
        # retain its old height for one layout pass, so the target spin box could
        # visually run under the following “允许调整” card. A standalone row
        # participates cleanly in the page's vertical layout and scroll owner.
        self.inverse_target_row = QWidget(settings)
        inverse_target_row_layout = QHBoxLayout(self.inverse_target_row)
        inverse_target_row_layout.setContentsMargins(0, 0, 0, 0)
        inverse_target_row_layout.setSpacing(ui_layout.CONTROL_GAP)
        self.inverse_target_label = QLabel("目标效率", self.inverse_target_row)
        self.inverse_target_label.setObjectName("propertyFieldLabel")
        self.inverse_target_label.setMinimumWidth(78)
        self.inverse_target_label.setMaximumWidth(78)
        inverse_target_row_layout.addWidget(self.inverse_target_label)
        inverse_target_row_layout.addWidget(self.inverse_target_efficiency)
        inverse_target_row_layout.addStretch(1)
        self.inverse_target_row.setMinimumHeight(max(34, self.inverse_target_efficiency.sizeHint().height()))
        self.inverse_target_row.hide()

        self.structure_stack = CurrentPageStackedWidget()
        self.structure_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.structure_stack.addWidget(self._build_fixed_contents())
        self.structure_stack.addWidget(self._build_variable_contents())

        amount_row = QHBoxLayout()
        amount_row.setSpacing(6)
        amount_row.addWidget(QLabel("计算量"))
        self.depth_group = QButtonGroup(self)
        self.depth_group.setExclusive(True)
        self.depth_buttons: list[SecondaryButton] = []
        for index, label in enumerate(("31 点", "81 点", "161 点")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            self.depth_group.addButton(button, index)
            self.depth_buttons.append(button)
            button.setMinimumWidth(66); button.setMaximumWidth(82)
            amount_row.addWidget(button)
        amount_row.addStretch(1)
        self.depth_buttons[1].setChecked(True)
        self.depth_hint = QLabel("")
        self.depth_hint.hide()

        self.start_research_button = PrimaryButton("开始研究")
        self.start_research_button.setMaximumWidth(220)
        self.start_research_button.clicked.connect(self._start_guided_research)
        self.guided_status = InfoRow("状态", "请选择研究参数")
        # This lives in a 310–348 px task-settings column.  The shared 94 px
        # InfoRow key is appropriate for wide reports but wastes too much space
        # here, forcing ordinary status messages onto a second line.
        self.guided_status.key_label.setMinimumWidth(48)
        self.guided_status.key_label.setMaximumWidth(48)

        # Compact settings column.  Dense controls use vertical grouping so the
        # right side can remain a large plot instead of competing with a wide form.
        settings.body.addWidget(settings_form)
        settings.body.addWidget(self.ml_model_row)
        settings.body.addWidget(self.inverse_target_row)
        settings.body.addWidget(self.structure_stack)
        settings.body.addLayout(amount_row)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.start_research_button, 0)
        action_row.addStretch(1)
        settings.body.addLayout(action_row)
        settings.body.addWidget(self.guided_status)
        layout.addWidget(settings)

        # 跨功能联动只带入“已有证据”，不自动改写研究变量或范围。
        self.evidence_panel = CollapsiblePanel("已有分析", expanded=False)
        self.evidence_text = QLabel("当前系统还没有可直接使用的分析结果。")
        self.evidence_text.setWordWrap(True)
        self.evidence_text.setObjectName("mutedText")
        self.evidence_panel.content_layout.addWidget(self.evidence_text)

        # 详细扫描范围、优化变量和任务版本属于低频内容，放到主图之后。
        self.more_settings_panel = CollapsiblePanel("更多设置", expanded=False)
        self.more_settings_panel.content_layout.addWidget(self._build_advanced_tools())

        # 兼容当前研究配置对象。尚未完整接入优化器的限制不在主界面展示。
        compatibility = QWidget(panel)
        compatibility.hide()
        self.preference_summary = QLabel("")
        self.minimum_spacing = UnitAwareDoubleSpinBox(); self.minimum_spacing.setRange(0.0, 100.0); self.minimum_spacing.setValue(0.5); self.minimum_spacing.setTargetUnit("mm")
        self.maximum_length = UnitAwareDoubleSpinBox(); self.maximum_length.setRange(1.0, 2000.0); self.maximum_length.setValue(50.0); self.maximum_length.setTargetUnit("mm")
        self.maximum_lenses = QSpinBox(); self.maximum_lenses.setRange(1, 20); self.maximum_lenses.setValue(4)
        self.minimum_efficiency = UnitAwareDoubleSpinBox(); self.minimum_efficiency.setRange(0.0, 100.0); self.minimum_efficiency.setValue(80.0); self.minimum_efficiency.setTargetUnit("%")
        self.multiwave_required = QCheckBox(); self.multiwave_required.setChecked(True)
        self.limit_summary = QLabel("")
        self.limit_panel = QWidget()
        for widget in (self.preference_summary, self.minimum_spacing, self.maximum_length, self.maximum_lenses,
                       self.minimum_efficiency, self.multiwave_required, self.limit_summary, self.limit_panel):
            widget.setParent(compatibility)

        for button in (self.parameter_research_button, self.parameter_optimization_button,
                       self.fixed_structure_button, self.variable_structure_button):
            button.toggled.connect(self._research_options_changed)
        return panel

    def _build_fixed_contents(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(5)
        self.fixed_content_boxes: dict[str, QCheckBox] = {}
        self._fixed_parameter_labels = {
            "wavelength": "波长",
            "waist": "束腰",
            "waist_position": "束腰位置",
            "curvature": "曲率",
            "thickness": "厚度",
            "spacing": "空气间隔",
            "aperture": "有效孔径",
            "lens_direction": "镜片方向",
            "fiber_axial": "光纤轴向位置",
            "fiber_lateral": "光纤横向位置",
            "fiber_tilt": "光纤角度倾斜",
            "fiber_mode": "NA / 模场直径",
        }
        # 真实选项仍由这些 checkbox 持有，主界面只显示选择摘要，降低新用户认知负担。
        for key, label in self._fixed_parameter_labels.items():
            box = QCheckBox(label, page)
            box.setChecked(key in {"spacing", "fiber_axial"})
            box.hide()
            self.fixed_content_boxes[key] = box

        parameter_card = Card("研究参数", compact=True)
        parameter_card.setMinimumHeight(124)
        self.parameter_selection_card = parameter_card
        self.fixed_selection_summary = QLabel()
        self.fixed_selection_summary.setWordWrap(True)
        self.fixed_selection_summary.setObjectName("compactContext")
        parameter_card.body.addWidget(self.fixed_selection_summary)
        selector_row = QHBoxLayout()
        choose = SecondaryButton("选择研究参数")
        self.choose_parameters_button = choose
        choose.clicked.connect(self._open_fixed_parameter_selector)
        selector_row.addWidget(choose)
        self.focus_search_button = SecondaryButton("焦面搜索")
        self.focus_search_button.clicked.connect(self._prepare_focus_search)
        selector_row.addWidget(self.focus_search_button)
        selector_row.addStretch(1)
        parameter_card.body.addLayout(selector_row)
        layout.addWidget(parameter_card)
        self.fixed_group_panels = []
        self._update_fixed_selection_summary()
        return page

    def _open_fixed_parameter_selector(self) -> None:
        task_title = self.TASK_TITLES.get(str(getattr(self, "_task_window_target", "optimization.scan")), "参数研究")
        # Optimisation/inverse design have one source of truth for variable
        # selection: the full resizable OptimizationVariableSelector.  The old
        # category checkbox dialog and the detailed variable matrix described the
        # same setting at two different levels and made users configure it twice.
        if task_title in {"自动优化", "物理反向设计", "代理模型反向预测"}:
            dialog = getattr(self, "variable_selector_dialog", None)
            if dialog is not None:
                dialog.setWindowTitle({
                    "自动优化": "选择优化变量",
                    "物理反向设计": "选择允许调整变量",
                    "代理模型反向预测": "选择允许反推变量",
                }[task_title])
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            return

        # Parameter research keeps the lighter semantic category chooser: its job
        # is to pick a scan topic, not to configure a many-variable optimisation.
        dialog = QDialog(self)
        dialog.setWindowTitle("选择研究参数")
        dialog.setModal(True)
        dialog.setSizeGripEnabled(True)
        dialog.resize(520, 430)
        dialog.setMinimumSize(420, 340)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel("只选择本次真正要研究的变量。已有 SHAP/扫描结果会作为小标签显示，但不会自动替你选择。")
        hint.setWordWrap(True)
        hint.setObjectName("mutedText")
        root.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        groups = (
            ("光源", ("wavelength", "waist", "waist_position")),
            ("镜头", ("curvature", "thickness", "spacing", "aperture", "lens_direction")),
            ("光纤", ("fiber_axial", "fiber_lateral", "fiber_tilt", "fiber_mode")),
        )
        evidence_text = self._parameter_evidence_labels()
        temporary: dict[str, QCheckBox] = {}
        row = 0
        for title, keys in groups:
            group_label = QLabel(title)
            group_label.setObjectName("sectionTitle")
            grid.addWidget(group_label, row, 0, 1, 2)
            row += 1
            for key in keys:
                label = self._fixed_parameter_labels[key]
                suffix = evidence_text.get(key, "")
                box = QCheckBox(f"{label}{'　' + suffix if suffix else ''}")
                box.setChecked(self.fixed_content_boxes[key].isChecked())
                temporary[key] = box
                grid.addWidget(box, row, 0, 1, 2)
                row += 1
        root.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for key, box in temporary.items():
            self.fixed_content_boxes[key].setChecked(box.isChecked())
        self._update_fixed_selection_summary()
        self._research_options_changed()

    def _parameter_evidence_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {}
        rows = self.context.project.findings_for(current_only=True) if hasattr(self.context.project, "findings_for") else []
        aliases = {
            "spacing": ("spacing", "air_gap", "空气间隔"),
            "fiber_axial": ("fiber_axial", "axial", "轴向"),
            "fiber_lateral": ("fiber_lateral", "offset_x", "offset_y", "横向"),
            "fiber_tilt": ("fiber_tilt", "tilt", "角度"),
            "fiber_mode": ("mfd", "mode_field", "na", "模场"),
            "curvature": ("curvature", "radius", "曲率"),
            "wavelength": ("wavelength", "波长"),
            "waist": ("waist", "束腰"),
        }
        for key, tokens in aliases.items():
            matches = []
            for row in rows:
                text = (str(row.get("parameter", "")) + " " + str(row.get("display_name", ""))).lower()
                if any(token.lower() in text for token in tokens):
                    matches.append(row)
            if not matches:
                continue
            sources = []
            for row in matches[:2]:
                source = str(row.get("source", "分析"))
                if source not in sources:
                    sources.append(source)
            labels[key] = "·".join(sources)
        return labels

    def _update_fixed_selection_summary(self) -> None:
        if not hasattr(self, "fixed_selection_summary"):
            return
        task_title = self.TASK_TITLES.get(str(getattr(self, "_task_window_target", "optimization.scan")), "参数研究")
        if task_title in {"自动优化", "物理反向设计", "代理模型反向预测"} and hasattr(self, "variable_selector"):
            variables = list(self.variable_selector.get_variables())
            labels = [str(item.get("label") or parameter_label(str(item.get("path", "")))) for item in variables]
            # Compact summary, same underlying selector: group repeated air-gap
            # rows instead of spelling out L1/L2/L3/L4 in the 300 px settings
            # column.  The dedicated editor still shows the exact rows/bounds.
            gap_count = sum(1 for item in variables if "厚度/间隔" in str(item.get("label", "")) and str(item.get("path", "")).startswith("surfaces["))
            compact: list[str] = []
            if gap_count:
                compact.append(f"空气间隔（{gap_count}）")
            for item, label in zip(variables, labels):
                if "厚度/间隔" in label and str(item.get("path", "")).startswith("surfaces["):
                    continue
                compact.append(label)
            empty = {
                "自动优化": "尚未选择优化变量",
                "物理反向设计": "尚未选择允许调整的变量",
                "代理模型反向预测": "尚未选择允许反推的变量",
            }[task_title]
            text = "、".join(compact[:4]) + (f" 等{len(compact)}类" if len(compact) > 4 else "") if compact else empty
            self.fixed_selection_summary.setText("当前选择：" + text)
            return
        evidence = self._parameter_evidence_labels()
        parts = []
        for key, box in self.fixed_content_boxes.items():
            if not box.isChecked():
                continue
            label = self._fixed_parameter_labels.get(key, key)
            if evidence.get(key):
                label += f"（已有 {evidence[key]}）"
            parts.append(label)
        self.fixed_selection_summary.setText("当前选择：" + ("、".join(parts) if parts else "尚未选择研究参数"))

    def _build_variable_contents(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(5)

        card = Card("可变结构", compact=True)
        form = QFormLayout()
        self.lens_source = QComboBox()
        self.lens_source.addItems(["当前结构模型", "已导入结构数据"])
        form.addRow("数据来源", self.lens_source)
        self.structure_model_combo = QComboBox()
        self.structure_model_combo.addItem("自动选择可用模型", "")
        form.addRow("结构模型", self.structure_model_combo)
        self.minimum_lenses = QSpinBox(); self.minimum_lenses.setRange(1, 10); self.minimum_lenses.setValue(2)
        self.variable_maximum_lenses = QSpinBox(); self.variable_maximum_lenses.setRange(1, 10); self.variable_maximum_lenses.setValue(4)
        lens_count = QWidget()
        lens_row = QHBoxLayout(lens_count); lens_row.setContentsMargins(0, 0, 0, 0); lens_row.setSpacing(6)
        lens_row.addWidget(self.minimum_lenses); lens_row.addWidget(QLabel("至")); lens_row.addWidget(self.variable_maximum_lenses); lens_row.addWidget(QLabel("片")); lens_row.addStretch(1)
        form.addRow("镜片数量", lens_count)
        self.structure_candidate_count = QSpinBox(); self.structure_candidate_count.setRange(5, 100); self.structure_candidate_count.setValue(20); self.structure_candidate_count.setSuffix(" 个")
        form.addRow("候选数量", self.structure_candidate_count)
        card.body.addLayout(form)

        self.structure_model_status = QLabel("候选由 BiLSTM 筛选结构顺序；如果模型预测还不够可靠，就不会给候选排序。")
        self.structure_model_status.setWordWrap(True)
        self.structure_model_status.setObjectName("mutedText")
        card.body.addWidget(self.structure_model_status)
        self.generate_structure_button = SecondaryButton("生成结构候选")
        self.generate_structure_button.clicked.connect(self._generate_structure_candidates)
        card.body.addWidget(self.generate_structure_button)
        layout.addWidget(card)

        # 保留高级结构约束供旧项目读取；当前候选生成先做“结构序列筛选”，
        # 物理处方和工程约束仍必须进入正式仿真阶段。
        compatibility = QWidget(page)
        compatibility.hide()
        self.allow_reorder = QCheckBox(); self.allow_reorder.setChecked(True)
        self.allow_reverse = QCheckBox(); self.allow_reverse.setChecked(False)
        self.lens_type_boxes = {}
        for label in ("平凸", "双凸", "正弯月", "平凹", "双凹", "负弯月"):
            box = QCheckBox(); box.setChecked(False); box.setParent(compatibility); self.lens_type_boxes[label] = box
        self.surface_profile_boxes = {}
        for label in ("球面", "非球面"):
            box = QCheckBox(); box.setChecked(False); box.setParent(compatibility); self.surface_profile_boxes[label] = box
        self.variable_content_boxes = {}
        for key in ("spacing", "fiber_axial", "lens_direction", "aperture"):
            box = QCheckBox(); box.setChecked(False); box.setParent(compatibility); self.variable_content_boxes[key] = box
        for widget in (self.allow_reorder, self.allow_reverse):
            widget.setParent(compatibility)
        return page

    def _research_preview_payload(self) -> dict:
        variable = bool(getattr(self, "variable_structure_button", None) and self.variable_structure_button.isChecked())
        is_ml_inverse = bool(getattr(self, "_ml_inverse_prediction_active", False))
        is_physical_inverse = bool(getattr(self, "_inverse_design_active", False)) and not is_ml_inverse
        is_optimization = bool(getattr(self, "parameter_optimization_button", None) and self.parameter_optimization_button.isChecked())
        mode = (
            "代理模型反向预测" if is_ml_inverse else
            "物理反向设计" if is_physical_inverse else
            "自动优化" if is_optimization else
            "参数研究"
        )
        structure = "可变结构" if variable else "固定结构"
        if variable:
            labels = ["镜片结构", "连续参数"]
        else:
            labels = [
                self._fixed_parameter_labels.get(key, key)
                for key, box in getattr(self, "fixed_content_boxes", {}).items()
                if box.isChecked()
            ]
        depth_index = self.depth_group.checkedId() if hasattr(self, "depth_group") else 1
        sample_count = ({0: 31, 1: 81, 2: 161}.get(depth_index, 81) if mode == "参数研究" else {0: 80, 1: 300, 2: 800}.get(depth_index, 300))
        if is_ml_inverse:
            source = "等待代理模型反向预测"
            summary = "开始后这里显示代理模型产生的候选参数；候选必须再由正式光学仿真验证。"
        elif is_physical_inverse:
            source = "等待物理反向设计"
            summary = "开始后这里显示由物理搜索产生并验证的候选参数。"
        elif is_optimization:
            source = "等待自动优化"
            summary = "开始后这里显示收敛过程与当前最佳候选；候选可临时预览到主仿真工作台。"
        else:
            source = "研究设计预览"
            summary = "这里只显示研究设计，不代表任何计算结果；开始研究后会在同一位置替换为真实结果。"
        return {
            "kind": "research_preview",
            "labels": labels[:2],
            "sample_count": sample_count,
            "mode": mode,
            "structure": structure,
            "target": self.guided_goal.currentText() if hasattr(self, "guided_goal") else "耦合效率最高",
            "source": source,
            "summary": summary,
        }

    def _refresh_research_preview(self) -> None:
        if bool(getattr(self, "_has_research_result", False)) or not hasattr(self, "main_result"):
            return
        payload = self._research_preview_payload()
        self._main_result_payloads[0] = payload
        mode = str(payload.get("mode", "参数研究"))
        title = {
            "参数研究": "研究预览",
            "自动优化": "优化结果",
            "物理反向设计": "候选结果",
            "代理模型反向预测": "候选结果",
        }.get(mode, "任务结果")
        candidate_task = mode in {"自动优化", "物理反向设计", "代理模型反向预测"}
        if hasattr(self, "task_empty_state"):
            self.task_empty_state.setVisible(candidate_task)
            if candidate_task:
                empty_copy = {
                    "自动优化": ("尚未开始优化", "运行后这里显示收敛状态、最佳候选和正式验证入口。"),
                    "物理反向设计": ("尚未开始物理反向设计", "运行后这里显示由真实光学搜索得到的候选参数。"),
                    "代理模型反向预测": ("尚未开始代理模型反向预测", "运行后这里显示 ML 候选、训练域状态和正式仿真验证入口。"),
                }.get(mode, ("尚未开始任务", "完成设置后开始任务。"))
                self.task_empty_title.setText(empty_copy[0])
                self.task_empty_text.setText(empty_copy[1])
        self.main_result.setVisible(not candidate_task)
        if not candidate_task:
            self.main_result.set_result(0, title, payload)
            self.main_result.select_result(0)
        if hasattr(self, "popout_research_plot_button"):
            self.popout_research_plot_button.setVisible(not candidate_task)
        if self.result_view_buttons:
            self.result_view_buttons[0].setText(
                self.result_view_labels[0]
                if str(getattr(self, "_task_window_target", "")) == "optimization.scan"
                else title
            )
            self.result_view_buttons[0].setChecked(True)
        if hasattr(self, "result_provenance"):
            self._set_result_provenance(f"结果来源：{payload.get('source', '等待计算')}")
        if hasattr(self, "compact_status_hint"):
            names = "、".join(payload.get("labels", [])) or "尚未选择参数"
            if mode == "参数研究":
                self.compact_status_hint.setText(f"等待研究结果｜当前设计：{names} · {payload.get('sample_count', '—')} 点")
            else:
                self.compact_status_hint.setText(f"等待{mode}｜可调：{names} · 预算 {payload.get('sample_count', '—')}")

    def _set_result_provenance(self, text: str) -> None:
        if hasattr(self, "result_provenance"):
            self.result_provenance.setText(str(text or ""))
            self.result_provenance.setVisible(bool(text))

    def _set_result_summary_values(self, *, first: str = "", second: str = "", third: str = "") -> None:
        if not hasattr(self, "compact_status_hint"):
            return
        self.compact_status_hint.hide()
        self.compact_efficiency.setText(first)
        self.compact_gain.setText(second)
        self.compact_range.setText(third)
        self.compact_efficiency.setVisible(bool(first))
        self.compact_gain.setVisible(bool(second))
        self.compact_range.setVisible(bool(third))
        self.compact_tolerance_button.show()

    def _build_main_result_panel(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        view_row = QHBoxLayout()
        self.result_view_group = QButtonGroup(self)
        self.result_view_group.setExclusive(True)
        self.result_view_buttons: list[SecondaryButton] = []
        self.result_view_labels = ("参数响应", "优化前后", "优化收敛", "候选对比", "参数相关性")
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
        self.popout_research_plot_button = QToolButton()
        self.popout_research_plot_button.setObjectName("plotIconTool")
        self.popout_research_plot_button.setIcon(icon("popout", theme.TEXT_SECONDARY, 17))
        self.popout_research_plot_button.setIconSize(QSize(17, 17))
        self.popout_research_plot_button.setToolTip("在独立科研图窗中查看当前结果，可自由缩放和平移")
        self.popout_research_plot_button.clicked.connect(lambda: open_workspace_plot(self, self.main_result))
        view_row.addWidget(self.popout_research_plot_button)
        layout.addLayout(view_row)

        self.task_empty_state = Card("", compact=True)
        self.task_empty_state.setObjectName("taskEmptyState")
        self.task_empty_state.setMinimumHeight(220)
        self.task_empty_title = QLabel("尚未开始任务")
        self.task_empty_title.setObjectName("sectionTitle")
        self.task_empty_text = QLabel("完成设置后开始任务，结果将在这里出现。")
        self.task_empty_text.setObjectName("mutedText")
        self.task_empty_text.setWordWrap(True)
        self.task_empty_text.setMinimumHeight(48)
        self.task_empty_state.body.addStretch(1)
        self.task_empty_state.body.addWidget(self.task_empty_title, 0, Qt.AlignmentFlag.AlignHCenter)
        self.task_empty_state.body.addWidget(self.task_empty_text, 0, Qt.AlignmentFlag.AlignHCenter)
        self.task_empty_state.body.addStretch(1)
        self.task_empty_state.hide()
        layout.addWidget(self.task_empty_state, 0)

        self.main_result = ResultWorkspace()
        self.main_result.setMinimumHeight(360)
        self.main_result.set_single_view_only(True)
        self.main_result.set_toolbar_visible(False)
        self.main_result.set_maximize_controls_visible(False)
        self.main_result.set_pane_title_visible(False)
        self.main_result.set_pane_source_visible(False)
        # The task result header already owns pop-out/data actions. Keeping the
        # per-plot reset/"更多" tools here duplicates controls and can clip at
        # 900–1100 px widths, so focused task surfaces hide them.
        self.main_result.set_plot_tools_visible(False)
        self.main_result.set_footer_visible(False)
        self._main_result_payloads[0] = self._research_preview_payload()
        self.main_result.set_result(0, "研究预览", self._main_result_payloads[0])
        self.main_result.setVisible(True)
        self.result_view_buttons[0].setText("研究预览")
        self.main_result.pointSelected.connect(self._scan_point_selected)
        layout.addWidget(self.main_result, 1)
        self.result_provenance = QLabel("结果来源：研究设计预览 · 尚未计算")
        self.result_provenance.setObjectName("helperText")
        self.result_provenance.setWordWrap(True)
        self.result_provenance.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(self.result_provenance)

        self.scan_point_actions = QWidget()
        point_row = QHBoxLayout(self.scan_point_actions)
        point_row.setContentsMargins(4, 0, 4, 0)
        point_row.setSpacing(7)
        self.scan_point_label = QLabel("")
        point_row.addWidget(self.scan_point_label, 1)
        self.preview_scan_point_button = SecondaryButton("预览此参数")
        self.preview_scan_point_button.clicked.connect(self._preview_selected_scan_point)
        self.apply_scan_point_button = SecondaryButton("应用此参数")
        self.apply_scan_point_button.clicked.connect(self._apply_selected_scan_point)
        self.refine_scan_point_button = SecondaryButton("在此附近细化")
        self.refine_scan_point_button.clicked.connect(self._refine_selected_scan_point)
        point_row.addWidget(self.preview_scan_point_button)
        point_row.addWidget(self.apply_scan_point_button)
        point_row.addWidget(self.refine_scan_point_button)
        self.scan_point_actions.hide()
        self._selected_scan_point = None
        layout.addWidget(self.scan_point_actions)

        self.compact_summary = QWidget()
        compact_stack = QVBoxLayout(self.compact_summary)
        compact_stack.setContentsMargins(4, 2, 4, 2)
        compact_stack.setSpacing(5)

        metric_row = QHBoxLayout()
        metric_row.setContentsMargins(0, 0, 0, 0)
        metric_row.setSpacing(12)
        self.compact_status_hint = QLabel("等待研究结果｜完成后显示最佳参数、峰值和高效区间")
        self.compact_status_hint.setObjectName("mutedText")
        self.compact_status_hint.setWordWrap(True)
        self.compact_status_hint.setMinimumWidth(0)
        self.compact_status_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.compact_efficiency = QLabel("")
        self.compact_gain = QLabel("")
        self.compact_range = QLabel("")
        metric_row.addWidget(self.compact_status_hint, 1)
        metric_row.addWidget(self.compact_efficiency)
        metric_row.addWidget(self.compact_gain)
        metric_row.addWidget(self.compact_range)
        compact_stack.addLayout(metric_row)

        # Result actions belong together on a dedicated row.  A single long
        # horizontal line used to collide/clamp when several actions became
        # visible at once.  The extra 34 px is cheaper than overlapping buttons
        # and the whole task already has one vertical scroll owner.
        primary_actions = QHBoxLayout()
        primary_actions.setContentsMargins(0, 0, 0, 0)
        primary_actions.setSpacing(6)
        primary_actions.addStretch(1)
        self.preview_best_design_button = SecondaryButton("预览候选")
        self.preview_best_design_button.clicked.connect(self._preview_best_design)
        self.preview_best_design_button.hide()
        primary_actions.addWidget(self.preview_best_design_button)
        self.clear_preview_button = SecondaryButton("退出预览")
        self.clear_preview_button.clicked.connect(self._clear_external_preview)
        self.clear_preview_button.hide()
        primary_actions.addWidget(self.clear_preview_button)
        self.apply_best_design_button = PrimaryButton("应用到当前系统")
        self.apply_best_design_button.clicked.connect(self._apply_best_design)
        self.apply_best_design_button.hide()
        primary_actions.addWidget(self.apply_best_design_button)
        compact_stack.addLayout(primary_actions)

        secondary_actions = QHBoxLayout()
        secondary_actions.setContentsMargins(0, 0, 0, 0)
        secondary_actions.setSpacing(6)
        secondary_actions.addStretch(1)
        self.verify_best_design_button = SecondaryButton("正式仿真验证")
        self.verify_best_design_button.clicked.connect(self._verify_best_design)
        self.verify_best_design_button.hide()
        secondary_actions.addWidget(self.verify_best_design_button)
        self.compact_tolerance_button = SecondaryButton("容差分析")
        self.compact_tolerance_button.clicked.connect(self._open_tolerance_from_optimization)
        self.compact_tolerance_button.hide()
        secondary_actions.addWidget(self.compact_tolerance_button)
        compact_stack.addLayout(secondary_actions)
        self.compact_summary.setVisible(True)
        layout.addWidget(self.compact_summary)

        # Progress is shown where the result will appear.  Put the status text
        # above a full-width bar rather than forcing a 300 px bar beside a long
        # sentence; this remains legible on compact task windows and makes the
        # submitted/running state unmistakable.
        progress_frame = QFrame()
        progress_frame.setObjectName("taskProgressPanel")
        progress_layout = QVBoxLayout(progress_frame)
        progress_layout.setContentsMargins(8, 6, 8, 7)
        progress_layout.setSpacing(5)
        self.activity_label = QLabel("尚未开始研究")
        self.activity_label.setWordWrap(True)
        self.activity_label.setObjectName("taskProgressTitle")
        progress_layout.addWidget(self.activity_label)
        self.research_progress = QProgressBar()
        self.research_progress.setRange(0, 100)
        self.research_progress.setValue(0)
        self.research_progress.setObjectName("taskProgressBar")
        self.research_progress.setVisible(False)
        progress_layout.addWidget(self.research_progress)
        # Keep progress immediately under the result canvas so it stays visible
        # on short windows; metrics/actions can scroll below it when necessary.
        layout.insertWidget(2, progress_frame)

        # 候选结果是主结果；参数明细与正式仿真属于候选结果详情，不再做平级页签。
        self.detail_panel = CollapsiblePanel("候选结果与详细结果", expanded=False)
        candidate_section = CollapsiblePanel("候选结果", expanded=True)
        self.candidate_table = DataTable(0, 5)
        self.candidate_table.setHorizontalHeaderLabels(["候选", "结构/参数", "预测/扫描", "正式结果", "状态"])
        self.candidate_table.stretch_columns(1)
        self.candidate_table.setMinimumHeight(180)
        candidate_section.content_layout.addWidget(self.candidate_table)
        self.detail_panel.content_layout.addWidget(candidate_section)

        self.parameter_range_text = self._detail_label("")
        self.multiwave_text = self._detail_label("")
        self.formal_verification_text = self._detail_label("")
        for label, widget in (("参数与范围", self.parameter_range_text), ("多波长结果", self.multiwave_text), ("正式仿真状态", self.formal_verification_text)):
            section = CollapsiblePanel(label, expanded=False)
            section.content_layout.addWidget(widget)
            self.detail_panel.content_layout.addWidget(section)
        self.detail_panel.setVisible(False)
        layout.addWidget(self.detail_panel)
        return page

    def _build_advanced_tools(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        history = SecondaryButton("任务历史")
        history.clicked.connect(self._open_history_dialog)
        row.addWidget(history)
        layout.addLayout(row)
        self.legacy_buttons: list[SecondaryButton] = []
        self.legacy_group = QButtonGroup(self)
        self.legacy_group.setExclusive(True)
        # 旧代码仍通过 legacy_buttons 检查当前设置页，按钮本身不再显示。
        for index in range(2):
            button = SecondaryButton("")
            button.setCheckable(True)
            button.hide()
            self.legacy_group.addButton(button, index)
            self.legacy_buttons.append(button)
        self.legacy_stack = LazyStackedWidget()
        self.legacy_stack.add_lazy_widget(self._scan_page, "正在准备参数范围…")
        self.legacy_stack.add_lazy_widget(self._auto_page, "正在准备优化变量…")
        self.legacy_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.legacy_stack, 0)
        self.legacy_buttons[0].setChecked(True)
        return page

    def _build_summary_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("optimizationSummaryScroll")
        scroll.setMinimumWidth(230)
        scroll.setMaximumWidth(285)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(7)

        best = Card("结果摘要", compact=True)
        self.summary_coupling = InfoRow("耦合效率", "—")
        self.summary_gain = InfoRow("相比当前", "—")
        self.summary_verification = InfoRow("仿真验证", "等待")
        for item in (self.summary_coupling, self.summary_gain, self.summary_verification):
            best.body.addWidget(item)
        self.summary_tolerance_button = SecondaryButton("容差分析")
        self.summary_tolerance_button.setToolTip("使用当前最优候选检查装调和制造误差的影响。")
        self.summary_tolerance_button.clicked.connect(self._open_tolerance_from_optimization)
        best.body.addWidget(self.summary_tolerance_button)
        explain = SecondaryButton("查看主要影响参数")
        explain.clicked.connect(lambda: self.navigateRequested.emit("machine_learning"))
        best.body.addWidget(explain)
        layout.addWidget(best)

        # 保留旧属性供结果更新逻辑使用，但不再把低频信息长期铺在页面上。
        compatibility = QWidget(panel)
        compatibility.hide()
        self.summary_system = InfoRow("系统效率", "—")
        self.summary_worst_wave = InfoRow("最差波长效率", "—")
        self.summary_length = InfoRow("系统长度", "—")
        self.summary_lens_count = InfoRow("镜片数量", "—")
        self.main_factor_text = QLabel("")
        self.advice_text = QLabel("")
        for item in (self.summary_system, self.summary_worst_wave, self.summary_length, self.summary_lens_count, self.main_factor_text, self.advice_text):
            item.setParent(compatibility)

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
        self.inverse_target_efficiency.valueChanged.connect(self._research_options_changed)
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
        self._update_fixed_selection_summary()
        variable = self.variable_structure_button.isChecked()
        self.structure_stack.setCurrentIndex(1 if variable else 0)
        QTimer.singleShot(0, self._sync_research_settings_height)
        if variable:
            self.fixed_structure_button.setChecked(False)
        elif not self.fixed_structure_button.isChecked():
            self.fixed_structure_button.setChecked(True)
        depth_index = self.depth_group.checkedId()
        research_mode = self.parameter_research_button.isChecked() if hasattr(self, "parameter_research_button") else True
        inverse_active = bool(getattr(self, "_inverse_design_active", False)) and not research_mode
        if hasattr(self, "inverse_target_row"):
            self.inverse_target_row.setVisible(inverse_active)
        if research_mode:
            labels = ("31 点", "81 点", "161 点")
            hints = {0: "参数研究使用 31 个采样点。", 1: "参数研究使用 81 个采样点。", 2: "参数研究使用 161 个采样点。"}
            self.start_research_button.setText("开始研究")
        else:
            labels = ("80 次", "300 次", "800 次")
            hints = {0: "优化最多 80 次迭代。", 1: "优化最多 300 次迭代。", 2: "优化最多 800 次迭代。"}
            if bool(getattr(self, "_ml_inverse_prediction_active", False)):
                self.start_research_button.setText("开始反向预测")
            else:
                self.start_research_button.setText("开始反向设计" if bool(getattr(self, "_inverse_design_active", False)) else "开始优化")
        for button, label in zip(self.depth_buttons, labels):
            button.setText(label)
        self.depth_hint.setText(hints.get(depth_index, hints[1]))
        if hasattr(self, "legacy_stack"):
            self._ensure_legacy_mode(0 if research_mode else 1)
        self._publish_research_profile()
        self._refresh_research_preview()
        # 没有任务在运行、也还没有结果时，状态应与当前选择保持一致。
        # 过去这里一直停留在“请选择研究参数”，即使界面上已经选好了参数，
        # 容易让新手误以为还缺一步。
        if not bool(getattr(self, "_has_research_result", False)):
            selected = self._selected_contents()
            if selected:
                ml_inverse = bool(getattr(self, "_ml_inverse_prediction_active", False))
                if ml_inverse and not str(getattr(self.context.registry, "current_model_id", "") or ""):
                    self._set_info(self.guided_status, "状态", "请先采用一个可用模型")
                else:
                    if research_mode:
                        action_text = "开始研究"
                    elif ml_inverse:
                        action_text = "开始反向预测"
                    else:
                        action_text = "开始反向设计" if inverse_active else "开始优化"
                    self._set_info(self.guided_status, "状态", f"设置已准备好，可以{action_text}")
            else:
                self._set_info(self.guided_status, "状态", "请先选择要研究的参数")

    def _sync_research_settings_height(self) -> None:
        stack = getattr(self, "structure_stack", None)
        card = getattr(self, "research_settings_card", None)
        if stack is not None:
            current = stack.currentWidget()
            if current is not None:
                current.updateGeometry()
                required = max(current.minimumSizeHint().height(), current.sizeHint().height())
                stack.setMinimumHeight(required)
            stack.updateGeometry()
        form = getattr(self, "research_settings_form", None)
        if form is not None:
            # Recompute the form's required height after task-specific rows are
            # shown/hidden. With the 13.5 pt application font the inverse-target
            # row needs more height than the scan form; leaving the old compact
            # geometry causes the combo and spin box borders to overlap.
            form.setMinimumHeight(0)
            form.grid.invalidate()
            form.grid.activate()
            form.setMinimumHeight(form.sizeHint().height())
            form.updateGeometry()
        if card is not None:
            # Keep the primary settings card at its natural content height.  Letting
            # it absorb all spare height created large blank bands between the goal,
            # variable selector and primary action in compact task windows.  This is
            # recomputed whenever task-specific rows change, so added ML/inverse rows
            # still grow the card safely; overflow belongs to the one outer page scroll.
            card.setMaximumHeight(16777215)
            card.setMinimumHeight(0)
            card.body.invalidate()
            card.body.activate()
            required = max(card.minimumSizeHint().height(), card.body.sizeHint().height())
            card.setMinimumHeight(required)
            card.setMaximumHeight(required)
            card.updateGeometry()
        self._sync_task_content_height()

    def _sync_visible_collapsible_geometry(self) -> None:
        """Make expanded task sections report their natural height.

        Advanced optimisation/ML forms expand inside the settings scroll.  They
        must push following controls downward rather than being compressed.
        """
        for panel in self.findChildren(CollapsiblePanel):
            if panel.isVisible():
                sync = getattr(panel, "_sync_expanded_geometry", None)
                if callable(sync):
                    sync()
        stack = getattr(self, "legacy_stack", None)
        if stack is not None and stack.isVisible():
            sync = getattr(stack, "_sync_current_geometry", None)
            if callable(sync):
                sync()

    def _sync_task_content_height(self) -> None:
        """Refresh the independent settings column's vertical scroll extent."""
        content = getattr(self, "task_content", None)
        scroll = getattr(self, "settings_scroll", None)
        if content is None or scroll is None:
            return
        # Candidate actions are terminal-result UI.  When they become visible,
        # the result canvas must own the space again even if the task previously
        # showed its empty state.  This prevents Qt from keeping the old compact
        # minimum and laying provenance/actions over the 360 px plot.
        terminal_actions = (
            getattr(self, "preview_best_design_button", None),
            getattr(self, "apply_best_design_button", None),
            getattr(self, "verify_best_design_button", None),
        )
        if any(widget is not None and not widget.isHidden() for widget in terminal_actions):
            if hasattr(self, "task_empty_state"):
                self.task_empty_state.hide()
            if hasattr(self, "main_result"):
                self.main_result.show()
        self._sync_visible_collapsible_geometry()
        layout = getattr(self, "task_content_layout", None) or content.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
            desired = max(layout.minimumSize().height(), layout.sizeHint().height())
        else:
            desired = max(content.minimumSizeHint().height(), content.sizeHint().height())
        content.setMinimumHeight(max(0, desired))
        content.updateGeometry()
        scroll.updateGeometry()

    def _prepare_focus_search(self) -> None:
        self.parameter_research_button.setChecked(True)
        self.fixed_structure_button.setChecked(True)
        for key, box in self.fixed_content_boxes.items():
            box.setChecked(key == "fiber_axial")
        self.guided_goal.setCurrentText("耦合效率最高")
        self._set_info(self.guided_status, "状态", "已选择轴向位置；点击“开始研究”进行焦面搜索")

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
        depth = ({0: "31 点", 1: "81 点", 2: "161 点"}.get(depth_index, "81 点") if self.parameter_research_button.isChecked() else {0: "80 次", 1: "300 次", 2: "800 次"}.get(depth_index, "300 次"))
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
        # 提交阶段尚未收到后端进度，使用不确定进度，不伪造 3% 等数值。
        self.research_progress.setRange(0, 0)
        self.research_progress.setFormat("正在提交后台…")
        self.research_progress.setVisible(True)
        self.activity_label.setText("等待中")
        self.activity_label.setToolTip("正在分析参数范围并准备研究任务")
        self.header_state.set_value("准备中")
        if hasattr(self.start_research_button, "set_task_state"):
            self.start_research_button.set_task_state("submitted", self._task_state_label("submitted"))
        else:
            self.start_research_button.setEnabled(False)

        structure_only = self.variable_structure_button.isChecked() and not any(
            key in contents
            for key in {"spacing", "curvature", "fiber_axial", "fiber_lateral", "fiber_tilt", "aperture"}
        )
        if structure_only:
            self._generate_structure_candidates(profile=profile)
            return

        try:
            mode = (
                "scan" if self.parameter_research_button.isChecked()
                else "optimization"
            )
            if mode == "scan":
                content_key = next(iter(contents), "")
                self._active_guided_mode = "scan"
                expected_label = self._first_scan_label(content_key)
                preserve_refinement = bool(getattr(self, "_scan_refinement_pending", False)) and (
                    not str(getattr(self, "_scan_refinement_parameter", ""))
                    or str(getattr(self, "_scan_refinement_parameter", "")) == expected_label
                ) and self.scan_param.currentText() == expected_label
                if preserve_refinement:
                    # “在此附近细化” is an explicit user edit.  Do not call the
                    # profile configurator here because it would silently restore
                    # the original broad range and make the second request
                    # identical to the first one.
                    self._ensure_legacy_mode(0)
                    self.scan_mode.setCurrentText("一维扫描")
                    self.scan_param2.setCurrentIndex(0)
                    self.scan_metric.setCurrentText("耦合效率")
                else:
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
                self.activity_label.setToolTip("正在筛选候选结果并进行完整仿真验证")
                submitted = self._run_auto()
            if submitted is False:
                raise ValueError("研究任务未提交，请检查参数范围和研究内容")
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            self._fail_guided_start(friendly_failure_message(exc))
            return
        self._set_info(self.guided_status, "当前状态", "研究任务正在提交")

    def _fail_guided_start(self, message: str) -> None:
        text = friendly_failure_message(message)
        self.research_progress.setRange(0, 100)
        self.research_progress.setValue(0)
        self.research_progress.setFormat("%p%")
        self.activity_label.setText(text)
        if hasattr(self.start_research_button, "set_task_state"):
            self.start_research_button.set_task_state("error", "提交失败")
            QTimer.singleShot(1400, lambda: self.start_research_button.reset_task_state())
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
        self._scan_refinement_pending = False
        self._scan_refinement_parameter = ""
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

    def _available_structure_model(self) -> dict | None:
        models = [dict(item) for item in self._structure_models if str(item.get("status", "available")) == "available"]
        models.extend(
            dict(item) for item in self.context.registry.models
            if "bilstm" in str(item.get("model_type", item.get("type", ""))).lower()
            and str(item.get("model_id", item.get("id", ""))) not in {str(row.get("model_id", "")) for row in models}
        )
        selected_id = ""
        if hasattr(self, "structure_model_combo"):
            selected_id = str(self.structure_model_combo.currentData() or "")
        current_id = selected_id or str(getattr(self.context.registry, "current_model_id", "") or "")
        for item in models:
            if str(item.get("model_id", item.get("id", "")) or "") == current_id:
                return item
        return models[0] if models else None

    def _generate_structure_candidates(self, checked: bool = False, *, profile: dict | None = None) -> None:
        del checked
        profile = profile or self._publish_research_profile()
        model = self._available_structure_model()
        # 结构候选接口返回前没有可量化后台进度，显示忙碌状态而非假百分比。
        self.research_progress.setRange(0, 0)
        self.research_progress.setFormat("正在读取后台结果…")
        self.research_progress.setVisible(True)
        self.start_research_button.setEnabled(False)
        if hasattr(self, "generate_structure_button"):
            self.generate_structure_button.setEnabled(False)
        if not model:
            self._pending_structure_candidate_profile = dict(profile or {})
            self.header_state.set_value("刷新模型")
            self._set_info(self.guided_status, "当前状态", "正在读取结构模型")
            self.activity_label.setText("正在刷新可变结构模型列表…")
            self.api_client.get("structure.models", "/structure-models")
            return
        model_id = str(model.get("model_id", model.get("id", "")) or "")
        if not model_id:
            self._fail_guided_start("可变结构模型缺少 model_id")
            if hasattr(self, "generate_structure_button"):
                self.generate_structure_button.setEnabled(True)
            return
        targets = [str(name) for name in list(model.get("target_names", []) or [])]
        target = "coupling_efficiency" if "coupling_efficiency" in targets else ("system_efficiency" if "system_efficiency" in targets else (targets[0] if targets else None))
        goal = "minimize" if target and "loss" in target.lower() else "maximize"
        payload = {
            "min_elements": int(self.minimum_lenses.value()),
            "max_elements": int(self.variable_maximum_lenses.value()),
            "max_candidates": int(getattr(self, "structure_candidate_count", self.variable_maximum_lenses).value()),
            "target_name": target,
            "goal": goal,
            "allow_weak_model": False,
        }
        self.header_state.set_value("筛选中")
        self._set_info(self.guided_status, "当前状态", "正在生成结构候选")
        self.activity_label.setText("正在用可变结构模型筛选候选；不会自动应用到当前系统")
        self.api_client.post("structure.candidates", f"/structure-models/{model_id}/candidates", payload)

    def _structure_models_completed(self, body: object) -> None:
        payload = dict(body or {}) if isinstance(body, dict) else {}
        data = dict(payload.get("data", payload) or {})
        self._structure_models = [dict(item) for item in list(data.get("models", []) or []) if isinstance(item, dict)]
        if hasattr(self, "structure_model_combo"):
            previous = str(self.structure_model_combo.currentData() or "")
            self.structure_model_combo.blockSignals(True)
            self.structure_model_combo.clear()
            self.structure_model_combo.addItem("自动选择可用模型", "")
            for item in self._structure_models:
                if str(item.get("status", "available")) != "available":
                    continue
                model_id = str(item.get("model_id", "") or "")
                name = str(item.get("name") or model_id)
                self.structure_model_combo.addItem(name, model_id)
            if previous:
                index = self.structure_model_combo.findData(previous)
                if index >= 0:
                    self.structure_model_combo.setCurrentIndex(index)
            self.structure_model_combo.blockSignals(False)
        available = [item for item in self._structure_models if str(item.get("status", "available")) == "available"]
        if hasattr(self, "structure_model_status"):
            if available:
                model = self._available_structure_model() or available[0]
                metrics = dict(model.get("metrics", {}) or {})
                r2_values = []
                for value in metrics.values():
                    if isinstance(value, dict) and isinstance(value.get("r2"), (int, float)):
                        r2_values.append(float(value["r2"]))
                quality = f"；最低测试 R²={min(r2_values):.3f}" if r2_values else "；尚缺独立测试 R²"
                self.structure_model_status.setText(f"已发现 {len(available)} 个 BiLSTM 结构模型{quality}。候选只用于序列筛选，仍需正式复场仿真。")
            else:
                self.structure_model_status.setText("未发现已训练的 BiLSTM 结构模型；平台不会伪造结构候选。")
        pending = self._pending_structure_candidate_profile
        self._pending_structure_candidate_profile = None
        if pending is not None:
            if self._available_structure_model() is None:
                if hasattr(self, "generate_structure_button"):
                    self.generate_structure_button.setEnabled(True)
                self.start_research_button.setEnabled(True)
                self._show_structure_capability_boundary(pending)
            else:
                self._generate_structure_candidates(profile=pending)

    def _structure_models_failed(self, message: str) -> None:
        pending = self._pending_structure_candidate_profile
        self._pending_structure_candidate_profile = None
        if pending is not None:
            if hasattr(self, "generate_structure_button"):
                self.generate_structure_button.setEnabled(True)
            self.start_research_button.setEnabled(True)
            self._fail_guided_start("读取结构模型失败：" + str(message))

    def _structure_candidates_completed(self, body: object) -> None:
        if hasattr(self, "generate_structure_button"):
            self.generate_structure_button.setEnabled(True)
        self.start_research_button.setEnabled(True)
        payload = dict(body or {}) if isinstance(body, dict) else {}
        data = dict(payload.get("data", payload) or {})
        status = str(data.get("status", ""))
        warnings = [str(item) for item in list(data.get("warnings", []) or [])]
        if status == "blocked":
            message = warnings[0] if warnings else "结构模型可靠性门控未通过，已阻止候选排序。"
            self.research_progress.setRange(0, 100)
            self.research_progress.setValue(0)
            self.research_progress.setFormat("%p%")
            self.header_state.set_value("模型不可靠")
            self._set_info(self.guided_status, "当前状态", "候选生成已阻止")
            self.activity_label.setText(message)
            self._main_result_payloads[0] = {"kind": "empty", "message": message}
            self._select_main_result(0)
            return
        rows = [dict(item) for item in list(data.get("candidates", []) or []) if isinstance(item, dict)]
        if not rows:
            self._fail_guided_start("结构模型没有返回有效候选")
            return
        target = str(data.get("target_name", "目标值"))
        is_efficiency = target in {"coupling_efficiency", "system_efficiency", "total_coupling_efficiency"}
        normalized = []
        lines = []
        for item in rows[:10]:
            sequence = [str(value) for value in list(item.get("element_types", []) or [])]
            score = item.get("score")
            value = float(score) if isinstance(score, (int, float)) else float("nan")
            display_value = value * 100.0 if is_efficiency and abs(value) <= 1.000001 else value
            label = f"#{item.get('rank', len(normalized)+1)} " + "→".join(sequence)
            normalized.append({"label": label, "predicted": display_value, "formal": None, "feasible": True, "verified": False})
            lines.append(f"{label}　预测 {display_value:.4g}{'%' if is_efficiency else ''}")
        summary = {
            "kind": "text",
            "title": "结构候选（仅预测筛选）",
            "text": "\n".join(lines[:8]) + "\n\n候选尚未经过正式复场仿真，不会自动应用到当前系统。",
        }
        comparison = {
            "kind": "candidate_compare",
            "title": "结构候选预测对比",
            "candidates": normalized,
            "y_label": ("预测效率 / %" if is_efficiency else target),
            "source": "BiLSTM结构筛选",
        }
        self._main_result_payloads = [summary, {"kind": "empty", "message": "结构候选需正式仿真后才能形成优化前后对比"}, {"kind": "empty", "message": "当前为候选生成，不是连续参数优化"}, comparison, {"kind": "empty", "message": "结构序列候选暂不提供参数相关性"}]
        self._set_result_view_visibility((True, False, False, True, False))
        self._select_main_result(3)
        self._has_research_result = True
        self._active_research_result_kind = "structure"
        if hasattr(self, "main_result"):
            self.main_result.setVisible(True)
        self.research_progress.setRange(0, 100)
        self.research_progress.setValue(100)
        self.research_progress.setFormat("已完成 · 100%")
        self.header_state.set_value("候选已生成")
        self._set_info(self.guided_status, "当前状态", f"已生成 {len(rows)} 个候选")
        self.activity_label.setText("候选只完成模型筛选；下一步需选择候选并进行正式复场仿真验证。" + (" " + warnings[0] if warnings else ""))
        self.context.project.update_research_context(current_task="可变结构候选筛选", current_target=target)
        self.context.project.publish_finding(
            source="结构候选",
            parameter="lens_structure_sequence",
            display_name="镜片结构序列",
            scope="当前系统",
            evidence={
                "candidate_count": len(rows),
                "target": target,
                "best_sequence": list(rows[0].get("element_types", []) or []),
                "best_predicted": rows[0].get("score"),
                "verified": False,
                "screening_scope": data.get("screening_scope", "structure_sequence_only"),
            },
            status="当前",
        )

    def _structure_candidates_failed(self, message: str) -> None:
        if hasattr(self, "generate_structure_button"):
            self.generate_structure_button.setEnabled(True)
        self.start_research_button.setEnabled(True)
        self._fail_guided_start("结构候选生成失败：" + str(message))

    def _show_structure_capability_boundary(self, profile: dict) -> None:
        models = [dict(item) for item in self._structure_models if str(item.get("status", "available")) == "available"]
        self.research_progress.setRange(0, 100)
        self.research_progress.setValue(0)
        self.research_progress.setFormat("%p%")
        self.start_research_button.setEnabled(True)
        if not models:
            message = (
                "当前没有可用的可变结构模型。平台已保存结构研究设置，但不会伪造候选排名。\n"
                "需要先通过已有 BiLSTM 结构训练流程准备模型；也可以先勾选空气间隔/光纤位置研究当前固定结构。"
            )
            self.header_state.set_value("能力不足")
            self._set_info(self.guided_status, "当前状态", "缺少可变结构模型")
        else:
            message = "已检测到可变结构模型，可以使用“生成结构候选”进行序列筛选。候选仍需工程约束与正式复场仿真复核。"
            self.header_state.set_value("结构模型可用")
            self._set_info(self.guided_status, "当前状态", "可生成结构候选")
        self._main_result_payloads[0] = {"kind": "empty", "message": message}
        self._select_main_result(0)
        self.activity_label.setText(message)

    def _ensure_result_workspace(self, kind: str) -> None:
        kind = str(kind)
        if kind == "tolerance":
            self._open_tolerance_from_optimization()
            return
        self._set_workspace_mode(0)
        self._ensure_legacy_mode(0 if kind == "scan" else 1)

    
    def _apply_best_design(self) -> None:
        changes = {}
        candidates = list(getattr(self, "_latest_candidate_variables", []) or [])
        table = getattr(self, "candidate_table", None)
        row = table.currentRow() if table is not None else -1
        if 0 <= row < len(candidates):
            changes = dict(candidates[row] or {})
        if not changes:
            changes = dict(getattr(self, "_latest_best_variables", {}) or {})
        if not changes:
            self.activity_label.setText("当前没有可应用的正式候选参数。")
            return
        apply_changes = getattr(self.context.project, "apply_parameter_changes", None)
        if not callable(apply_changes):
            self.activity_label.setText("当前工程上下文不支持参数写回。")
            return
        changed = bool(apply_changes(changes, reason="采用优化/反向设计的正式候选结果"))
        self.activity_label.setText("候选参数已写回当前系统；建议立即执行正式仿真验证。" if changed else "当前工程已处于该候选参数。")
        self.header_state.set_value("已应用候选")

    def _verify_best_design(self) -> None:
        # Verification is deliberately explicit: applying a candidate never silently
        # claims physical truth. The simulation workbench owns the formal run.
        self.navigateRequested.emit("simulation")

    def _shared_result_changed(self, _task_id: str, _result: object) -> None:
        self._refresh_user_summary()

    def _refresh_user_summary(self) -> None:
        # When a scan/structure result is on screen, that result owns the compact
        # summary and header.  Previously this method rewrote those widgets from
        # the latest optimisation/current-project metrics, producing impossible
        # combinations such as "耦合效率 75% / 峰值 16%" beside a scan curve.
        if bool(getattr(self, "_has_research_result", False)) and str(
            getattr(self, "_active_research_result_kind", "")
        ) not in {"", "optimization"}:
            return
        result = latest_optimization_result(self.context.tasks)
        baseline = self.context.project.project.metrics.get("coupling_efficiency")
        if isinstance(baseline, (int, float)):
            text = f"{baseline * 100:.3f}%"
            self._set_info(self.summary_coupling, "耦合效率", text)
            self.compact_efficiency.setText(f"耦合效率 {text}")
            self.header_best.set_value(f"{baseline * 100:.3f}", "%")
        if not result:
            return
        metrics = dict(result.get("best_metrics", {}) or {})
        efficiency = metrics.get("coupling_efficiency")
        if isinstance(efficiency, (int, float)):
            text = f"{efficiency * 100:.3f}%"
            self._set_info(self.summary_coupling, "耦合效率", text)
            self.compact_efficiency.setText(f"耦合效率 {text}")
            self.header_best.set_value(f"{efficiency * 100:.3f}", "%")
            if isinstance(baseline, (int, float)):
                gain_text = f"{(efficiency - baseline) * 100:+.3f}%"
                self._set_info(self.summary_gain, "相比当前", gain_text)
                self.compact_gain.setText(f"相比当前 {gain_text}")
        system_eff = metrics.get("system_efficiency")
        if isinstance(system_eff, (int, float)):
            self._set_info(self.summary_system, "系统效率", f"{system_eff * 100:.3f}%")
        self._set_info(self.summary_verification, "仿真验证", "已完成" if result.get("status") == "completed" else str(result.get("status", "等待")))
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
            self.advice_text.setText("仿真验证完成且未返回警告，可结合多波长和工程限制决定是否采用。")

    def _scan_point_selected(self, x: float, y: float) -> None:
        if not bool(getattr(self, "_has_research_result", False)):
            return
        self._selected_scan_point = (float(x), float(y))
        unit = self._unit_for_label(self.scan_param.currentText())
        metric = self.scan_metric.currentText()
        metric_suffix = "%" if self._metric_key(metric) == "coupling_efficiency" else ""
        self.scan_point_label.setText(
            f"已选采样点：{x:.6g}{(' ' + unit) if unit else ''} · {metric} {y:.6g}{metric_suffix}"
        )
        updater = getattr(self.context.project, "update_research_context", None)
        if callable(updater):
            label = self.scan_param.currentText()
            updater(active_parameter_scan={
                "path": self._path_for_label(label),
                "label": label,
                "unit": self._unit_for_label(label),
                "start": float(self.scan_start.value()),
                "stop": float(self.scan_stop.value()),
                "points": int(self.scan_points.value()),
                "selected": float(x),
            })
        self.scan_point_actions.show()

    def _apply_selected_scan_point(self) -> None:
        point = getattr(self, "_selected_scan_point", None)
        if not point:
            return
        path = self._path_for_label(self.scan_param.currentText())
        changed = False
        if hasattr(self.context.project, "apply_parameter_changes"):
            changed = self.context.project.apply_parameter_changes(
                {path: float(point[0])},
                reason=f"采用参数扫描采样点：{self.scan_param.currentText()}",
            )
        self.activity_label.setText("已应用所选参数到当前系统。" if changed else "当前系统已经是该参数值。")

    def _refine_selected_scan_point(self) -> None:
        point = getattr(self, "_selected_scan_point", None)
        if not point:
            return
        low = float(self.scan_start.value()); high = float(self.scan_stop.value())
        span = max(abs(high - low), 1e-12)
        half = span * 0.10
        centre = float(point[0])
        self.scan_start.setValue(centre - half)
        self.scan_stop.setValue(centre + half)
        self.scan_points.setValue(max(int(self.scan_points.value()), 81))
        self._scan_refinement_pending = True
        self._scan_refinement_parameter = self.scan_param.currentText()
        self.activity_label.setText(
            f"已把扫描范围缩到所选点附近；再次开始研究时将保留 {self.scan_start.value():.6g}～{self.scan_stop.value():.6g} 的细化范围。"
        )

    def _select_main_result(self, index: int) -> None:
        if not 0 <= index < len(self.result_view_buttons):
            return
        if bool(getattr(self, "_has_research_result", False)):
            if hasattr(self, "task_empty_state"):
                self.task_empty_state.hide()
            if hasattr(self, "main_result"):
                self.main_result.show()
            if hasattr(self, "popout_research_plot_button"):
                self.popout_research_plot_button.show()
        payloads = getattr(self, "_main_result_payloads", [])
        payload = payloads[index] if index < len(payloads) else {"kind": "empty", "message": "暂无结果"}
        title = self.result_view_buttons[index].text() or (
            self.result_view_labels[index] if index < len(self.result_view_labels) else "结果"
        )
        if hasattr(self, "scan_point_actions") and index != 0:
            self.scan_point_actions.hide()
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
        dialog.setSizeGripEnabled(True)
        dialog.resize(width, height)
        dialog.setMinimumSize(min(680, max(420, width // 2)), min(460, max(320, height // 2)))
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
            self.history_dialog = self._make_dialog("任务历史", self._history_page(), 1180, 720)
        self._refresh_history()
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()

    
    def _has_active_optimization_job(self) -> bool:
        active = {"运行中", "等待后端", "等待中", "已提交", "queued", "running", "submitting"}
        terminal = {"已完成", "失败", "已取消", "未收敛"}
        for task in self.context.tasks.tasks:
            if not isinstance(task, dict):
                continue
            page = str(task.get("page", ""))
            kind_text = str(task.get("kind", ""))
            name = str(task.get("name", ""))
            if page != "optimization" and kind_text != "参数研究" and not any(
                token in name for token in ("参数扫描", "自动优化", "自动调参", "容差")
            ):
                continue
            status = str(task.get("status", ""))
            if status in active:
                return True
            if status and status not in terminal:
                return True
        return False

    def _sync_primary_action_idle_state(self) -> None:
        button = getattr(self, "start_research_button", None)
        if button is None or not hasattr(button, "reset_task_state"):
            return
        if self._has_active_optimization_job():
            return
        self._active_research_job_id = ""
        state = str(button.property("taskState") or "")
        if state in {"running", "submitted"}:
            inverse = bool(getattr(self, "_inverse_design_active", False))
            default = "开始反向设计" if inverse else "开始优化"
            button.reset_task_state(default)

    def on_activated(self) -> None:
        self._page_active = True
        self.lifecycle.activated()
        if hasattr(self, "research_scroll"):
            self.workspace_state.restore_scroll("research", self.research_scroll, 0)
        self._restore_jobs_from_tasks(self.context.tasks.tasks)
        self._refresh_user_summary()
        self.api_client.get("structure.models", "/structure-models")
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
        self._sync_primary_action_idle_state()

    def on_deactivated(self) -> None:
        if hasattr(self, "research_scroll"):
            self.workspace_state.save_scroll("research", self.research_scroll)
        self._page_active = False
        self._poll_timer.stop()
        self.lifecycle.deactivate()

    def _apply_responsive_layout(self) -> None:
        # 纵向工作流不再根据窗口宽度挤压三栏；结果摘要在主结果区内显示。
        has_result = bool(getattr(self, "_has_research_result", False))
        if hasattr(self, "compact_summary"):
            self.compact_summary.setVisible(True)
        if hasattr(self, "summary_panel"):
            self.summary_panel.hide()

    def _scroll_to_results(self) -> None:
        # Results are always visible in the right task pane after the refactor.
        # Keep this compatibility hook because submit/result mixins still call it.
        return

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        self.on_activated()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def handle_assistant_action(self, action: dict) -> None:
        payload = dict(action or {})
        target = str(payload.get("target", "") or "")
        if target == "optimization.tolerance":
            self._open_tolerance_from_optimization()
            if str(payload.get("research_owner", "") or "") == "simulation":
                # A tolerance task launched from Simulation is robustness analysis
                # of the one current system, not a follow-up of an optimisation
                # candidate.  Keep candidate analysis available when the task is
                # launched from an optimisation result, but never make it the
                # default for the Simulation-owned entry.
                if hasattr(self, "tolerance_candidate"):
                    self.tolerance_candidate.setCurrentText("当前系统")
                if hasattr(self, "tolerance_template"):
                    self.tolerance_template.setCurrentText("常用装调")
                self._tolerance_apply_template()
                if hasattr(self, "tolerance_source_info"):
                    self.tolerance_source_info.setText(
                        "来源：当前正式系统 · 使用仿真工作台当前参数与正式数值设置进行稳健性分析。"
                    )
                if hasattr(self, "tolerance_status"):
                    self._set_info(self.tolerance_status, "状态", "已基于当前系统准备容差参数")
            return
        if target == "optimization.validation":
            self._set_workspace_mode(1)
            if hasattr(self, "validation_run_button"):
                self.validation_run_button.setFocus()
            return
        if target == "optimization.scan":
            self._inverse_design_active = False
            self._ml_inverse_prediction_active = False
            self.parameter_research_button.setChecked(True)
            self.fixed_structure_button.setChecked(True)
            hint = " ".join([str(payload.get("prefill_parameter", "") or ""), str(payload.get("prefill_feature", "") or "")]).lower()
            aliases = {
                "spacing": ("间距", "spacing", "air gap", "后间距", "空气间隔", "distance_to_next"),
                "fiber_axial": ("轴向", "fiber axial", "z 方向", "接收面", "像面", "image_distance"),
                "fiber_lateral": ("横向", "offset", "x 方向", "y 方向"),
                "fiber_tilt": ("倾角", "角度", "tilt"),
                "curvature": ("曲率", "radius"),
                "waist": ("束腰", "waist"),
                "wavelength": ("波长", "wavelength"),
            }
            matched = [key for key, tokens in aliases.items() if hint and any(token in hint for token in tokens)]
            for key in matched[:1]:
                if hasattr(self, "fixed_content_boxes"):
                    for current_key, box in self.fixed_content_boxes.items():
                        box.setChecked(current_key == key)
                # This also pre-fills a physically scaled default range and point count.
                self._configure_scan_from_profile(key)
            prefill_range = payload.get("prefill_range")
            if isinstance(prefill_range, (list, tuple)) and len(prefill_range) >= 2 and hasattr(self, "scan_start"):
                try:
                    low, high = sorted((float(prefill_range[0]), float(prefill_range[1])))
                except (TypeError, ValueError):
                    pass
                else:
                    if high > low:
                        self.scan_start.setValue(low)
                        self.scan_stop.setValue(high)
                        requested_points = int(payload.get("prefill_points", 161) or 161)
                        requested_points = max(31, min(requested_points, 161))
                        self.scan_points.setValue(requested_points)
                        depth_id = 2 if requested_points >= 161 else (1 if requested_points >= 81 else 0)
                        button = self.depth_group.button(depth_id) if hasattr(self, "depth_group") else None
                        if button is not None:
                            button.setChecked(True)
                        self.activity_label.setText(
                            f"已把扫描范围准备为 {low:.4g} ～ {high:.4g}；请确认后开始研究。"
                        )
            self._research_options_changed()
            self.start_research_button.setFocus()
        elif target == "optimization.inverse_design":
            self._inverse_design_active = True
            self._ml_inverse_prediction_active = False
            # 物理反向设计：目标 -> 可调变量 -> 物理搜索 -> 正式候选。
            self.parameter_optimization_button.setChecked(True)
            self.fixed_structure_button.setChecked(True)
            self._research_options_changed()
            self.start_research_button.setText("开始反向设计")
            if hasattr(self, "activity_label"):
                self.activity_label.setText("物理反向设计：设定目标与允许调整的变量，由正式光学计算搜索候选。")
            if hasattr(self, "guided_goal"):
                self.guided_goal.setFocus()
        elif target == "optimization.ml_inverse_prediction":
            self._inverse_design_active = True
            self._ml_inverse_prediction_active = True
            self.parameter_optimization_button.setChecked(True)
            self.fixed_structure_button.setChecked(True)
            self._research_options_changed()
            self.start_research_button.setText("开始反向预测")
            model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
            if hasattr(self, "activity_label"):
                if model_id:
                    self.activity_label.setText("代理模型反向预测：由当前模型快速搜索目标参数候选，并保留正式仿真验证。")
                else:
                    self.activity_label.setText("代理模型反向预测需要先在“模型构建/模型比较”中采用一个可用模型。")
            if hasattr(self, "guided_goal"):
                self.guided_goal.setFocus()
        elif target == "optimization.variables":
            self._inverse_design_active = False
            self._ml_inverse_prediction_active = False
            self.parameter_optimization_button.setChecked(True)
            self.fixed_structure_button.setChecked(True)
            hints = [str(item or "").lower() for item in list(payload.get("prefill_parameters", []) or [])]
            aliases = {
                "spacing": ("间距", "spacing", "air gap", "后间距", "空气间隔", "distance_to_next"),
                "fiber_axial": ("轴向", "fiber axial", "z 方向", "接收面", "像面", "image_distance"),
                "fiber_lateral": ("横向", "offset", "x 方向", "y 方向"),
                "fiber_tilt": ("倾角", "角度", "tilt"),
                "curvature": ("曲率", "radius"),
                "waist": ("束腰", "waist"),
                "wavelength": ("波长", "wavelength"),
            }
            contents = [key for key, tokens in aliases.items() if any(any(token in hint for token in tokens) for hint in hints)]
            if not contents:
                contents = [key for key, box in self.fixed_content_boxes.items() if box.isChecked()]
            self._configure_auto_from_profile(contents[:4], {"source": "智能助手准备"})
            self._research_options_changed()
            self.start_research_button.setFocus()
        elif target == "optimization.variable_structure":
            self._inverse_design_active = False
            self._ml_inverse_prediction_active = False
            self.parameter_optimization_button.setChecked(True)
            self.variable_structure_button.setChecked(True)
            self._research_options_changed()
            self.start_research_button.setFocus()
        if hasattr(self, "research_scroll"):
            self.research_scroll.verticalScrollBar().setValue(0)

    def assistant_action_target_widget(self, action: dict):
        target = str(dict(action or {}).get("target", "") or "")
        if target == "optimization.scan":
            return self.start_research_button
        if target in {"optimization.inverse_design", "optimization.ml_inverse_prediction"}:
            return getattr(self, "guided_goal", self.start_research_button)
        if target == "optimization.variables":
            return self.start_research_button
        if target == "optimization.variable_structure":
            return self.start_research_button
        if target == "optimization.tolerance":
            return self.inline_tolerance_panel
        if target == "optimization.validation" and hasattr(self, "validation_run_button"):
            return self.validation_run_button
        if target == "optimization.current":
            return self.research_scroll
        return self

    def assistant_context(self) -> dict:
        workspace_index = self.workspace_stack.currentIndex() if hasattr(self, "workspace_stack") else 0
        if workspace_index == 1:
            rows = self._validation_rows() if hasattr(self, "_validation_rows") else []
            metrics = comparison_metrics(rows) if rows else {}
            return {
                "page": "实验验证",
                "validation_kind": self.validation_kind.currentText() if hasattr(self, "validation_kind") else "",
                "reference_type": self.validation_reference_type.currentText() if hasattr(self, "validation_reference_type") else "",
                "status": self.validation_data_status.value_label.text() if hasattr(self, "validation_data_status") and hasattr(self.validation_data_status, "value_label") else "",
                "rows": [
                    {
                        "case": row.case,
                        "reference": row.reference,
                        "reference_uncertainty": row.reference_uncertainty,
                        "platform": row.platform,
                        "numerical_uncertainty": row.numerical_uncertainty,
                        "input_uncertainty": row.input_uncertainty,
                        "unit": row.unit,
                        "parameter_changes": dict(row.parameter_changes or {}),
                        "diagnostics": row_diagnostics(row),
                    }
                    for row in rows
                ],
                "comparison_metrics": dict(metrics or {}),
                "current_plot": self.validation_result.current_data() if hasattr(self, "validation_result") else {},
            }
        if self.parameter_research_button.isChecked():
            mode = "参数研究"
        elif bool(getattr(self, "_ml_inverse_prediction_active", False)):
            mode = "代理模型反向预测"
        elif bool(getattr(self, "_inverse_design_active", False)):
            mode = "物理反向设计"
        else:
            mode = "参数优化"
        selected = self._selected_contents() if hasattr(self, "fixed_content_boxes") else []
        result_view = ""
        if hasattr(self, "result_view_group"):
            idx = self.result_view_group.checkedId()
            if 0 <= idx < len(getattr(self, "result_view_buttons", [])):
                result_view = self.result_view_buttons[idx].text()
        return {
            "page": "参数研究与优化",
            "mode": mode,
            "structure": "可变结构" if self.variable_structure_button.isChecked() else "固定结构",
            "structure_model": (self._available_structure_model() or {}).get("model_id", "") if self.variable_structure_button.isChecked() else "",
            "selected_parameters": list(selected),
            "goal": self.guided_goal.currentText() if hasattr(self, "guided_goal") else "",
            "current_result_view": result_view,
            "status": self.header_state.value_label.text() if hasattr(self.header_state, "value_label") else "",
            "progress": self.research_progress.value() if hasattr(self, "research_progress") else 0,
            "activity": self.activity_label.text() if hasattr(self, "activity_label") else "",
            "latest_optimization": latest_optimization_result(self.context.tasks),
            "current_plot": self.main_result.current_data() if hasattr(self, "main_result") else {},
            "tolerance_visible": bool(getattr(self, "inline_tolerance_panel", None) and self.inline_tolerance_panel.isVisible()),
            "tolerance_summary": {
                "mean": self.tolerance_mean.value_label.text() if hasattr(self, "tolerance_mean") else "",
                "std": self.tolerance_std.value_label.text() if hasattr(self, "tolerance_std") else "",
                "p05": self.tolerance_p05.value_label.text() if hasattr(self, "tolerance_p05") else "",
                "yield": self.tolerance_yield.value_label.text() if hasattr(self, "tolerance_yield") else "",
            },
        }

    def dispose_page(self) -> None:
        if hasattr(self, "research_scroll"):
            self.workspace_state.save_scroll("research", self.research_scroll)
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
