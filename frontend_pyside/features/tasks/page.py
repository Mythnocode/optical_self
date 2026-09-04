from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QToolButton,
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
from frontend_pyside.shared.components.workbench import MetricSummaryBar
from frontend_pyside.shared.components.foundation.headers import PageHeader
from frontend_pyside.shared import layout_tokens as ui_layout
from frontend_pyside.shared.components.fast_table import FastTableView
from frontend_pyside.shared.components.task_status_chart import (
    TaskProgressChart,
    TaskStatusDonut,
)
from frontend_pyside.shared.components.workbench import ExpandableSection
from frontend_pyside.shared.lifecycle import Debouncer, ManagedPageResources
from frontend_pyside.shared.settings import WorkspaceStateStore
from frontend_pyside.shared.icons import icon
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
        root.setContentsMargins(ui_layout.PAGE_MARGIN, ui_layout.CONTROL_GAP, ui_layout.PAGE_MARGIN, ui_layout.PAGE_MARGIN)
        root.setSpacing(ui_layout.CARD_GAP)

        header = PageHeader(
            "任务中心",
            "查看后台任务的真实运行状态、进度、失败原因和结果。任务进度来自后台，不使用前端假进度。",
        )
        root.addWidget(header)

        summary = QHBoxLayout()
        summary.setSpacing(ui_layout.CONTROL_GAP)
        self.task_summary_bar = MetricSummaryBar((("运行", "0"), ("等待", "0"), ("失败", "0"), ("完成", "0")))
        summary.addWidget(self.task_summary_bar, 1)
        # Compatibility objects kept hidden for older refresh helpers.
        self.unfinished_metric = InlineMetric("未完成", "0", "个"); self.unfinished_metric.hide()
        self.running_metric = InlineMetric("运行中", "0", "个"); self.running_metric.hide()
        self.waiting_metric = InlineMetric("等待中", "0", "个"); self.waiting_metric.hide()
        self.failed_metric = InlineMetric("失败", "0", "个"); self.failed_metric.hide()
        self.refresh_button = QToolButton()
        self.refresh_button.setObjectName("compactIconTool")
        self.refresh_button.setIcon(icon("refresh", "#344054", 18))
        self.refresh_button.setToolTip("刷新任务状态")
        self.refresh_button.clicked.connect(lambda: self._request_remote_jobs(force=True))
        self.retry_button = SecondaryButton("重试")
        self.retry_button.setIcon(icon("refresh", "#344054", 16))
        self.retry_button.clicked.connect(self._retry_selected)
        self.cancel_button = PrimaryButton("取消")
        self.cancel_button.setIcon(icon("close", "#FFFFFF", 16))
        self.cancel_button.clicked.connect(self._cancel_selected)
        self.retry_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        summary.addWidget(self.refresh_button)
        summary.addWidget(self.retry_button)
        summary.addWidget(self.cancel_button)
        root.addLayout(summary)

        self.remote_state = Badge("等待同步", "info")
        self.remote_state.setVisible(False)
        self.queue_label = QLabel("")
        self.queue_label.setObjectName("mutedText")

        workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace = workspace
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(8)

        task_card = Card("任务", compact=True)
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部任务", "运行中", "等待中", "已完成", "失败", "已暂停", "已取消"])
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型", "仿真", "参数扫描", "自动优化", "机器学习", "模型解释", "教学", "报告"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索任务")
        filters.addWidget(self.status_filter)
        filters.addWidget(self.type_filter)
        filters.addWidget(self.search, 1)
        task_card.body.addLayout(filters)

        self.table = TaskProgressChart()
        self.table.currentCellChanged.connect(self._show_selected)
        task_card.body.addWidget(self.table, 1)
        workspace.addWidget(task_card)

        detail_card = Card("任务详情", compact=True)
        self.detail_badge = Badge("未选择", "info")
        detail_card.body.addWidget(self.detail_badge)
        self.detail_empty = QLabel("选择一个任务查看运行状态、失败原因、日志和结果。")
        self.detail_empty.setObjectName("emptyHint")
        self.detail_empty.setWordWrap(True)
        self.detail_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_empty.setMinimumHeight(160)
        detail_card.body.addWidget(self.detail_empty, 1)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setDocumentMode(True)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        self.failure_banner = QLabel("")
        self.failure_banner.setObjectName("warningBanner")
        self.failure_banner.setWordWrap(True)
        self.failure_banner.hide()
        overview_layout.addWidget(self.failure_banner)
        self.detail_name = InfoRow("任务名称", "—")
        self.detail_kind = InfoRow("任务类型", "—")
        self.detail_time = InfoRow("创建时间", "—")
        self.detail_source = InfoRow("执行来源", "—")
        self.detail_duration = InfoRow("运行耗时", "—")
        self.detail_note = InfoRow("当前信息", "—")
        self.detail_job_id = InfoRow("任务 ID", "—")
        self.detail_error_code = InfoRow("错误代码", "—")
        for row in (self.detail_name, self.detail_kind, self.detail_time, self.detail_source, self.detail_duration, self.detail_note, self.detail_job_id, self.detail_error_code):
            overview_layout.addWidget(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat("进度 %p%")
        overview_layout.addWidget(self.progress)
        action_row = QHBoxLayout()
        self.detail_view_result = SecondaryButton("查看结果")
        self.detail_open_log = QToolButton()
        self.detail_open_log.setObjectName("compactIconTool")
        self.detail_open_log.setIcon(icon("log", "#344054", 18))
        self.detail_open_log.setToolTip("查看任务日志")
        self.detail_export = QToolButton()
        self.detail_export.setObjectName("compactIconTool")
        self.detail_export.setIcon(icon("download", "#344054", 18))
        self.detail_export.setToolTip("导出任务记录")
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
        self.log_text = QLabel("选择任务后显示日志。")
        self.log_text.setWordWrap(True)
        self.log_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        log_layout.addWidget(self.log_text)
        log_layout.addStretch(1)
        self.detail_tabs.addTab(log_page, "日志")

        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        self.artifact_text = QLabel("选择任务后查看结果。")
        self.artifact_text.setWordWrap(True)
        result_layout.addWidget(self.artifact_text)
        result_layout.addStretch(1)
        self.detail_tabs.addTab(result_page, "结果")
        detail_card.body.addWidget(self.detail_tabs, 1)
        self.detail_tabs.hide()
        workspace.addWidget(detail_card)
        workspace.setSizes([1000, 500])
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 0)
        root.addWidget(workspace, 1)

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
            if hasattr(self.api_client, "failed_detail"):
                self.lifecycle.connect(self.api_client.failed_detail, self._api_failed_detail)
            else:
                self.lifecycle.connect(self.api_client.failed, self._api_failed)

        self._refresh_timer = self.lifecycle.manage_timer(QTimer(self))
        self._refresh_timer.setProperty("stopWhenHidden", True)
        self._refresh_timer.setInterval(2500)
        self._refresh_timer.timeout.connect(self._request_remote_jobs)

        self.workspace_state.restore_splitter("main", workspace, [1000, 500])
        self.refresh()
        QTimer.singleShot(0, self._request_remote_jobs)

    def handle_assistant_action(self, action: dict) -> None:
        target = str(dict(action or {}).get("target", "") or "")
        if target != "tasks.current":
            return
        # Select a concrete visible task so the action has an observable business
        # result rather than merely navigating to the page. Prefer unfinished
        # work, otherwise fall back to the newest visible record.
        row = -1
        for index, task in enumerate(list(getattr(self, "_visible_tasks", []) or [])):
            if str(task.get("status", "")) not in {"已完成", "失败", "已取消", "未收敛"}:
                row = index
                break
        if row < 0 and getattr(self, "_visible_tasks", None):
            row = 0
        if row >= 0:
            self.table.setCurrentCell(row, 0)
            self._show_selected(row, 0, -1, -1)
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)

    def assistant_action_target_widget(self, action: dict):
        target = str(dict(action or {}).get("target", "") or "")
        if target == "tasks.current":
            return self.table
        return self

    def assistant_context(self) -> dict:
        rows = list(getattr(self.context.tasks, "tasks", []) or [])
        counts: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "未知") or "未知")
            counts[status] = counts.get(status, 0) + 1
        selected = None
        try:
            selected = self._task_at(self.table.currentRow())
        except Exception:
            selected = None
        selected_payload = dict(selected) if isinstance(selected, dict) else {}
        if selected_payload:
            task_id = str(selected_payload.get("id", "") or "")
            result = self.context.tasks.result(task_id, None) if task_id else None
            if result is not None:
                selected_payload["result"] = result
        return {
            "page": "任务中心",
            "current_view": "任务详情" if selected_payload else "任务列表",
            "task_count": len(rows),
            "status_counts": counts,
            "selected_task": selected_payload,
            "remote_state": self.remote_state.text() if hasattr(self, "remote_state") else "",
        }

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
