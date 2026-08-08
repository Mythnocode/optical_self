from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import (
    Badge,
    Card,
    CollapsiblePanel,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.lazy_widgets import LazyTabWidget


class TeachingWorkspaceMixin:
    def _build_workspace(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)

        heading = QHBoxLayout()
        self.course_label = QLabel()
        self.course_label.setObjectName("cardTitle")
        heading.addWidget(self.course_label)
        heading.addStretch()
        self.source_badge = Badge("结果来源：教学近似", "warning")
        heading.addWidget(self.source_badge)
        root.addLayout(heading)
        self.stage_focus_label = QLabel("本环节重点：沿完整物理链路观察参数如何传递")
        self.stage_focus_label.setObjectName("helperText")
        self.stage_focus_label.setWordWrap(True)
        root.addWidget(self.stage_focus_label)

        self.pred_card = CollapsiblePanel("教学任务", expanded=False)
        prediction_row = QHBoxLayout()
        self.pred_prompt = QLabel()
        self.pred_prompt.setWordWrap(True)
        self.pred_prompt.setMinimumWidth(300)
        prediction_row.addWidget(self.pred_prompt, 2)
        self.pred_group = QButtonGroup(self)
        self.pred_options = QHBoxLayout()
        prediction_row.addLayout(self.pred_options, 3)
        self.pred_submit = PrimaryButton("提交预测")
        self.pred_submit.clicked.connect(self._submit_prediction)
        prediction_row.addWidget(self.pred_submit)
        self.pred_card.content_layout.addLayout(prediction_row)
        self.pred_feedback = QLabel()
        self.pred_feedback.setWordWrap(True)
        self.pred_card.content_layout.addWidget(self.pred_feedback)
        root.addWidget(self.pred_card)

        self.metric_frame = QWidget()
        self.metric_row = QHBoxLayout(self.metric_frame)
        self.metric_row.setContentsMargins(0, 0, 0, 0)
        self.metric_row.setSpacing(7)
        root.addWidget(self.metric_frame)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.parameter_card = Card("参数控制", compact=True)
        self.parameter_card.setMinimumWidth(320)
        self.parameter_card.setMaximumWidth(420)
        self.parameter_layout = QVBoxLayout()
        self.parameter_layout.setSpacing(4)
        self.parameter_card.body.addLayout(self.parameter_layout)
        self.task_label = QLabel()
        self.task_label.setWordWrap(True)
        self.parameter_card.body.addWidget(self.task_label)
        self.task_status = Badge("等待计算", "info")
        self.parameter_card.body.addWidget(self.task_status)
        splitter.addWidget(self.parameter_card)

        result_side = QWidget()
        result_layout = QVBoxLayout(result_side)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(7)

        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("结果视图"))
        self.teaching_view_selector = QComboBox()
        self.teaching_view_selector.addItems(["主视图", "辅助视图"])
        self.teaching_view_selector.currentIndexChanged.connect(
            self._teaching_view_changed
        )
        view_row.addWidget(self.teaching_view_selector)
        view_row.addStretch(1)
        result_layout.addLayout(view_row)

        self.result_workspace = ResultWorkspace()
        self.result_workspace.set_single_view_only(True)
        self.result_workspace.set_toolbar_visible(False)
        self.result_workspace.set_maximize_controls_visible(False)
        result_layout.addWidget(self.result_workspace, 1)

        self.explanation_card = Card("诊断摘要", compact=True)
        self.explanation_card.setMinimumWidth(300)
        self.explanation_card.setMaximumWidth(410)
        self.formula_label = QLabel()
        self.formula_label.setWordWrap(True)
        self.formula_label.setObjectName("cardTitle")
        self.explanation_card.body.addWidget(self.formula_label)
        self.theory_label = QLabel()
        self.theory_label.setWordWrap(True)
        self.explanation_card.body.addWidget(self.theory_label)
        self.assumption_label = QLabel()
        self.assumption_label.setWordWrap(True)
        self.assumption_label.setObjectName("helperText")
        self.explanation_card.body.addWidget(self.assumption_label)
        self.observation_label = QLabel()
        self.observation_label.setWordWrap(True)
        self.explanation_card.body.addWidget(self.observation_label)
        self.full_theory_button = SecondaryButton("查看完整理论资源")
        self.full_theory_button.clicked.connect(self._open_current_theory)
        self.explanation_card.body.addWidget(self.full_theory_button)
        splitter.addWidget(result_side)
        splitter.addWidget(self.explanation_card)
        splitter.setSizes([340, 900, 360])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self.generic_workspace_splitter = splitter
        root.addWidget(splitter, 1)

        self.generic_action_frame = QWidget()
        action = QHBoxLayout(self.generic_action_frame)
        action.setContentsMargins(0, 0, 0, 0)
        rec = SecondaryButton("记录当前数据")
        rec.clicked.connect(self._record)
        reset = SecondaryButton("恢复默认")
        reset.clicked.connect(lambda: self.load_module(self.current_module))
        theory = SecondaryButton("打开理论资源")
        theory.clicked.connect(self._open_current_theory)
        score = PrimaryButton("自动评分")
        score.clicked.connect(self._score)
        action.addWidget(rec)
        action.addWidget(reset)
        action.addWidget(theory)
        action.addStretch()
        action.addWidget(score)
        root.addWidget(self.generic_action_frame)

        console = LazyTabWidget()
        console.setDocumentMode(True)
        console.setMinimumHeight(190)
        console.setMaximumHeight(280)
        self.data_table = DataTable(0, 5)
        self.data_table.setHorizontalHeaderLabels(["时间", "主要参数", "主要指标", "任务", "备注"])
        self.data_table.setToolTip("尚未记录实验数据。调整参数后点击‘记录当前数据’。")
        console.addTab(self.data_table, "观察记录")
        console.add_lazy_tab(self._scan_panel, "参数扫描", "打开后再加载扫描图表。")
        console.add_lazy_tab(self._trajectory_panel, "调节轨迹", "记录两个以上状态后显示调节过程。")
        console.add_lazy_tab(self._mismatch_panel, "模场失配分析", "打开后再创建光强、相位和复场诊断工作区。")
        self.mismatch_console = console
        console.add_lazy_tab(self._compare_panel, "方案比较", "打开后再创建方案比较表。")
        console.add_lazy_tab(self._diagnostic_panel, "数值诊断", "打开后再创建诊断控件。")
        console.add_lazy_tab(self._report_panel, "练习与报告", "打开后再生成报告编辑区。")
        root.addWidget(console)
        return page

    def _set_mismatch_focus_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self.pred_card.setVisible(not enabled)
        self.metric_frame.setVisible(not enabled)
        self.generic_workspace_splitter.setVisible(not enabled)
        self.generic_action_frame.setVisible(not enabled)
        if enabled:
            self.mismatch_console.setCurrentIndex(3)
            self.mismatch_console.tabBar().setVisible(False)
            self.mismatch_console.setMinimumHeight(560)
            self.mismatch_console.setMaximumHeight(16777215)
        else:
            self.mismatch_console.tabBar().setVisible(True)
            self.mismatch_console.setMinimumHeight(190)
            self.mismatch_console.setMaximumHeight(280)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _inputs(self):
        spec = self.catalog["modules"][self.current_module]
        values = {key: value["default"] for key, value in spec["parameters"].items()}
        values.update({key: control.value() for key, control in self.controls.items()})
        return values

    def _rebuild_metric_cards(self, spec):
        self._clear_layout(self.metric_row)
        self.metric_cards = {}
        for key, metric in spec["metrics"].items():
            card = InlineMetric(metric["label"], "—", metric["unit"])
            self.metric_row.addWidget(card)
            self.metric_cards[key] = card

    def _evaluate(self, *_):
        self.current_inputs = self._inputs()
        self.current_result = self.workflow.evaluate(self.current_module, self.current_inputs)
        spec = self.catalog["modules"][self.current_module]
        for key, card in self.metric_cards.items():
            value = self.current_result["metrics"].get(key)
            metric = spec["metrics"][key]
            card.set_value(f"{value * metric.get('scale', 1):.{metric.get('digits', 3)}f}", metric["unit"])
        plots = self.current_result.get("plots", {})
        primary = plots.get("primary", {})
        secondary = plots.get("secondary", plots.get("factors", {}))
        primary = dict(primary)
        secondary = dict(secondary)
        primary.setdefault("source", "教学近似")
        secondary.setdefault("source", "教学近似")
        primary_title = primary.get("title", "主视图")
        secondary_title = secondary.get("title", "辅助视图")
        self.result_workspace.set_result(0, primary_title, primary)
        self.result_workspace.set_result(1, secondary_title, secondary)
        self.teaching_view_selector.setItemText(0, primary_title)
        self.teaching_view_selector.setItemText(1, secondary_title)
        self.teaching_view_selector.setCurrentIndex(0)
        self.result_workspace.select_result(0)
        status = self.current_result.get("task_status", {})
        self.task_status.setText(status.get("label", ""))
        self.task_status.set_tone("success" if status.get("passed") else "warning")
        observations = self.current_result.get("observations", [])
        if observations:
            self.observation_label.setText("当前观察\n• " + "\n• ".join(observations[:4]))
        else:
            self.observation_label.setText("当前观察\n调节参数并比较指标与曲线变化。")
        if hasattr(self, "_refresh_mismatch_panel"):
            self._refresh_mismatch_panel()

    def _teaching_view_changed(self, index: int) -> None:
        self.result_workspace.select_result(index)

    def _submit_prediction(self):
        checked = self.pred_group.checkedButton()
        if not checked:
            self.pred_feedback.setText("请先选择一个答案。")
            return
        out = self.workflow.prediction(self.current_module, checked.property("choice_id"))
        self.pred_feedback.setText(("✓ 正确。" if out["correct"] else "✗ 不正确。") + out["explanation"])
        if out["correct"]:
            self.pred_card.set_expanded(False)

    def _record(self):
        self.workflow.record(self.current_module, self.current_inputs, self.current_result)
        self._refresh_records()
        self._refresh_all_records()
        if hasattr(self, "_refresh_trajectory_plot"):
            self._refresh_trajectory_plot()
        self.context.tasks.add(self.catalog["modules"][self.current_module]["title"] + "数据记录", "教学", "已完成", 100)

    def _refresh_records(self):
        records = self.workflow.session(self.current_module)["records"]
        self.data_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [
                record["time"],
                str(next(iter(record["inputs"].items()), "")),
                str(next(iter(record["metrics"].items()), "")),
                self.current_result.get("task_status", {}).get("label", ""),
                record.get("note", ""),
            ]
            for column, value in enumerate(values):
                self.data_table.setItem(row, column, QTableWidgetItem(str(value)))
