from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.infrastructure.api.clients import JobClient
from frontend_pyside.shared.components.basic import (
    Badge,
    Card,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.fast_table import FastTableView
from frontend_pyside.shared.components.task_status_chart import (
    TaskProgressChart,
    TaskStatusDonut,
)
from frontend_pyside.shared.components.workbench import ExpandableSection
from frontend_pyside.shared.lifecycle import Debouncer, ManagedPageResources
from frontend_pyside.shared.settings import WorkspaceStateStore
from .presentation.detail_behavior import TaskDetailMixin
from .presentation.remote_behavior import TaskRemoteMixin


class TasksPage(TaskDetailMixin, TaskRemoteMixin, QWidget):


    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.setObjectName("tasksPage")
        self.context = context
        self.lifecycle = ManagedPageResources(self)
        self.workspace_state = WorkspaceStateStore("tasks")
        self.api_client = context.api_client
        self.job_client = JobClient(self.api_client)
        self._remote_list_pending = False
        self._remote_list_available: bool | None = None
        self._all_tasks: list[dict] = []
        self._visible_tasks: list[dict] = []
        self._completed_tasks: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 12)
        root.setSpacing(7)

        summary = QHBoxLayout()
        summary.setSpacing(7)
        self.unfinished_metric = InlineMetric("未完成", "0", "个")
        self.running_metric = InlineMetric("运行中", "0", "个")
        self.waiting_metric = InlineMetric("等待中", "0", "个")
        self.failed_metric = InlineMetric("失败", "0", "个")
        for metric in (
            self.unfinished_metric,
            self.running_metric,
            self.waiting_metric,
            self.failed_metric,
        ):
            summary.addWidget(metric, 1)
        self.refresh_button = SecondaryButton("刷新")
        self.refresh_button.clicked.connect(lambda: self._request_remote_jobs(force=True))
        self.retry_button = SecondaryButton("重试")
        self.retry_button.clicked.connect(self._retry_selected)
        self.cancel_button = PrimaryButton("取消")
        self.cancel_button.clicked.connect(self._cancel_selected)
        self.retry_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        summary.addWidget(self.refresh_button)
        summary.addWidget(self.retry_button)
        summary.addWidget(self.cancel_button)
        root.addLayout(summary)

        self.remote_state = Badge("等待同步", "info")
        self.remote_state.setVisible(False)
        self.queue_label = QLabel("当前没有未完成任务")
        self.queue_label.setObjectName("mutedText")

        workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace = workspace
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(8)

        current_card = Card("当前任务", compact=True)
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部未完成", "运行中", "等待中", "已暂停"])
        self.type_filter = QComboBox()
        self.type_filter.addItems(
            ["全部类型", "仿真", "参数扫描", "自动优化", "机器学习", "模型解释", "教学", "报告"]
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索未完成任务")
        filters.addWidget(self.status_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.queue_label)
        current_card.body.addLayout(filters)

        self.table = TaskProgressChart()
        self.table.currentCellChanged.connect(self._show_selected)
        current_scroll = QScrollArea()
        current_scroll.setWidgetResizable(True)
        current_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        current_scroll.setWidget(self.table)
        current_card.body.addWidget(current_scroll, 1)
        workspace.addWidget(current_card)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(7)
        self.chart_card = Card("未完成任务分布", compact=True)
        self.status_donut = TaskStatusDonut()
        self.empty_chart_text = QLabel("暂无活动任务")
        self.empty_chart_text.setObjectName("compactEmptyState")
        self.empty_chart_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_chart_text.setMinimumHeight(86)
        self.empty_chart_text.setVisible(False)
        self.chart_card.body.addWidget(self.status_donut, 1)
        self.chart_card.body.addWidget(self.empty_chart_text)
        side_layout.addWidget(self.chart_card, 1)

        attention = Card("需要处理", compact=True)
        self.attention_text = QLabel("当前没有需要处理的任务。")
        self.attention_text.setWordWrap(True)
        self.attention_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        attention.body.addWidget(self.attention_text)
        side_layout.addWidget(attention)
        workspace.addWidget(side)
        workspace.setSizes([1120, 400])
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 0)
        root.addWidget(workspace, 1)

        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(7, 7, 7, 7)
        self.completed_table = FastTableView(
            ["完成时间", "任务", "类型", "耗时", "结果"],
            page_size=50,
        )
        self.completed_table.stretch_columns(1)
        self.completed_table.content_columns(0, 2, 3, 4)
        self.completed_table.currentCellChanged.connect(self._show_completed_selected)
        history_layout.addWidget(self.completed_table)
        self.history_section = ExpandableSection(
            "任务历史",
            history_widget,
            subtitle="完成、失败和取消任务统一归档",
            expanded=False,
        )
        root.addWidget(self.history_section)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(7, 7, 7, 7)
        detail_layout.setSpacing(7)
        self.detail_badge = Badge("未选择", "info")
        detail_layout.addWidget(self.detail_badge)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setDocumentMode(True)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        self.detail_name = InfoRow("任务名称", "—")
        self.detail_kind = InfoRow("任务类型", "—")
        self.detail_time = InfoRow("创建时间", "—")
        self.detail_source = InfoRow("执行来源", "—")
        self.detail_duration = InfoRow("运行耗时", "—")
        self.detail_note = InfoRow("当前信息", "—")
        for row in (
            self.detail_name,
            self.detail_kind,
            self.detail_time,
            self.detail_source,
            self.detail_duration,
            self.detail_note,
        ):
            overview_layout.addWidget(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat("进度 %p%")
        overview_layout.addWidget(self.progress)
        action_row = QHBoxLayout()
        self.detail_view_result = SecondaryButton("查看结果")
        self.detail_open_log = SecondaryButton("查看日志")
        self.detail_export = SecondaryButton("导出")
        self.detail_view_result.clicked.connect(self._view_selected_result)
        self.detail_open_log.clicked.connect(self._open_selected_log)
        self.detail_export.clicked.connect(self._export_selected_record)
        action_row.addWidget(self.detail_view_result)
        action_row.addWidget(self.detail_open_log)
        action_row.addWidget(self.detail_export)
        action_row.addStretch(1)
        overview_layout.addLayout(action_row)
        overview_layout.addStretch(1)
        self.detail_tabs.addTab(overview, "概览")

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        self.log_text = QLabel("选择任务后显示关键日志。")
        self.log_text.setWordWrap(True)
        self.log_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        log_layout.addWidget(self.log_text)
        log_layout.addStretch(1)
        self.detail_tabs.addTab(log_page, "日志")

        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        self.artifact_text = QLabel("选择任务后查看结果或产物。")
        self.artifact_text.setWordWrap(True)
        result_layout.addWidget(self.artifact_text)
        result_layout.addStretch(1)
        self.detail_tabs.addTab(result_page, "结果")
        detail_layout.addWidget(self.detail_tabs)
        self.detail_section = ExpandableSection(
            "任务详情",
            detail_widget,
            subtitle="选择任务后按需展开",
            expanded=False,
        )
        root.addWidget(self.detail_section)

        self._filter_debouncer = Debouncer(200, self._apply_filter, self)
        self.lifecycle.connect(context.tasks.tasks_changed, self.refresh)
        self.lifecycle.connect(context.tasks.task_updated, self._on_task_updated)
        self.lifecycle.connect(context.tasks.task_result_changed, self._on_task_result)
        self.lifecycle.connect(context.tasks.task_log_changed, self._on_task_log)
        self.lifecycle.connect(self.search.textChanged, self._filter_debouncer.trigger)
        self.lifecycle.connect(self.type_filter.currentTextChanged, self._apply_filter)
        self.lifecycle.connect(self.status_filter.currentTextChanged, self._apply_filter)
        if self.api_client is not None:
            self.lifecycle.connect(self.api_client.completed, self._api_completed)
            self.lifecycle.connect(self.api_client.failed, self._api_failed)

        self._refresh_timer = self.lifecycle.manage_timer(QTimer(self))
        self._refresh_timer.setProperty("stopWhenHidden", True)
        self._refresh_timer.setInterval(2500)
        self._refresh_timer.timeout.connect(self._request_remote_jobs)

        self.workspace_state.restore_splitter("main", workspace, [1120, 400])
        self.refresh()
        QTimer.singleShot(0, self._request_remote_jobs)

    def _show_completed_selected(self, row: int, *_args) -> None:
        if not 0 <= row < len(self._completed_tasks):
            return
        task = self._completed_tasks[row]
        self._selected_task_override = task
        self._show_task_detail(task)

    def on_activated(self) -> None:
        self.lifecycle.activated()
        self._request_remote_jobs()
        self._refresh_timer.start()

    def on_deactivated(self) -> None:
        self._refresh_timer.stop()
        self.lifecycle.deactivate()

    def showEvent(self, event) -> None:
        self.on_activated()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.on_deactivated()
        super().hideEvent(event)

    def _on_task_updated(self, _task_id: str, _task: dict) -> None:
        self.refresh()

    def _on_task_result(self, task_id: str, result) -> None:
        selected = self._task_at(self.table.currentRow())
        if selected and str(selected.get("id", "")) == str(task_id):
            self.artifact_text.setText(f"后端结果已缓存。\n{str(result)[:800]}")

    def _on_task_log(self, task_id: str, rows: list[dict]) -> None:
        selected = self._task_at(self.table.currentRow())
        if not selected or str(selected.get("id", "")) != str(task_id):
            return
        self.log_text.setText(
            "\n".join(
                f"{item.get('time', '')} [{item.get('level', 'INFO')}] {item.get('message', '')}"
                for item in rows[-500:]
            )
            or "暂无日志"
        )

    def dispose_page(self) -> None:
        self.workspace_state.save_splitter("main", self.workspace)
        self._filter_debouncer.cancel()
        self.lifecycle.dispose()
