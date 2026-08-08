from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.infrastructure.api.clients import (
    DatasetClient,
    HeadlessDatasetClient,
    JobClient,
    TrainingClient,
)
from frontend_pyside.shared.components.basic import Card, InfoRow, SecondaryButton
from frontend_pyside.shared.components.workbench import ExpandableSection
from frontend_pyside.shared.lazy_widgets import LazyStackedWidget
from frontend_pyside.shared.lifecycle import ManagedPageResources
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
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

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 9, 14, 12)
        root.setSpacing(7)

        header = Card("智能分析", compact=True)
        header_row = QHBoxLayout()
        self.research_header = QLabel("当前研究：尚未设置")
        self.research_header.setObjectName("cardTitle")
        header_row.addWidget(self.research_header, 1)
        research_button = SecondaryButton("返回研究")
        research_button.clicked.connect(lambda: self.navigateRequested.emit("optimization"))
        header_row.addWidget(research_button)
        header.body.addLayout(header_row)
        root.addWidget(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)
        split.addWidget(self._build_analysis_main())
        split.addWidget(self._build_explanation_panel())
        split.setSizes([950, 430])
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        root.addWidget(split, 1)

        
        
        
        self.analysis_detail_stack = QStackedWidget()
        self.analysis_detail_stack.setObjectName("analysisDetailStack")
        self.analysis_detail_stack.setMinimumHeight(92)
        self.consistency_text = self._text_panel("等待模型测试集与正式复核结果。")
        self.residual_text = self._text_panel("等待残差数据。")
        self.analysis_detail_stack.addWidget(self.consistency_text)
        self.analysis_detail_stack.addWidget(self.residual_text)
        self.analysis_detail_stack.hide()

        self.advanced_section = self._build_advanced_section()
        root.addWidget(self.advanced_section)
        self.lifecycle.connect(
            context.project.simulation_project_payload_changed,
            self._update_dataset_config_summary,
        )

        self.workspace_state.restore_tab("workflow", self.workflow_stack, 0)
        self.workflow_buttons[self.workflow_stack.currentIndex()].setChecked(True)
        self._refresh_analysis()
        self.lifecycle.single_shot(100, self.refresh_remote)

    def _build_analysis_main(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        toolbar = QHBoxLayout()
        self.analysis_view_group = QButtonGroup(self)
        self.analysis_view_group.setExclusive(True)
        self.analysis_view_buttons: list[SecondaryButton] = []
        for index, label in enumerate(("预测一致性", "残差诊断")):
            button = SecondaryButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._select_analysis_view(i))
            self.analysis_view_group.addButton(button, index)
            self.analysis_view_buttons.append(button)
            toolbar.addWidget(button)
        self.analysis_view_buttons[0].setChecked(True)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.analysis_result = ResultWorkspace()
        self.analysis_result.set_single_view_only(True)
        self.analysis_result.set_toolbar_visible(False)
        self.analysis_result.set_maximize_controls_visible(False)
        self.analysis_result.set_result(
            0,
            "预测一致性",
            {"kind": "empty", "message": "请先训练并登记模型，测试集预测与正式值将显示在这里。"},
        )
        layout.addWidget(self.analysis_result, 1)
        return panel

    def _build_explanation_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(410)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(7)

        summary = Card("当前研究", compact=True)
        self.profile_text = QLabel()
        self.profile_text.setWordWrap(True)
        self.profile_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.body.addWidget(self.profile_text)
        layout.addWidget(summary)

        risk = Card("模型结果", compact=True)
        self.compatibility = InfoRow("当前模型", "等待读取")
        self.formal_state = InfoRow("正式复核", "等待")
        self.prediction_gap = InfoRow("当前方案偏差", "—")
        self.model_r2 = InfoRow("R²", "—")
        self.model_mae = InfoRow("MAE", "—")
        self.high_efficiency_mae = InfoRow("高效率区MAE", "—")
        self.model_samples = InfoRow("测试样本", "—")
        self.training_domain = InfoRow("训练域", "—")
        for row in (
            self.compatibility, self.formal_state, self.prediction_gap,
            self.model_r2, self.model_mae, self.high_efficiency_mae,
            self.model_samples, self.training_domain,
        ):
            risk.body.addWidget(row)
        layout.addWidget(risk)

        action = SecondaryButton("参数研究")
        action.clicked.connect(lambda: self.navigateRequested.emit("optimization"))
        layout.addWidget(action)
        advanced = SecondaryButton("SHAP分析")
        advanced.clicked.connect(lambda: self.navigateRequested.emit("explainability"))
        layout.addWidget(advanced)
        self.explanation_text = QLabel()
        self.explanation_text.hide()
        self.risk_text = QLabel()
        self.risk_text.hide()
        layout.addStretch(1)
        scroll.setWidget(panel)
        return scroll

    def _build_advanced_section(self) -> ExpandableSection:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(7)
        toolbar = QHBoxLayout()
        self.workflow_group = QButtonGroup(self)
        self.workflow_group.setExclusive(True)
        self.workflow_buttons: list[SecondaryButton] = []
        for index, label in enumerate(("数据与特征", "模型训练", "模型版本")):
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
            "高级信息",
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
        if profile:
            contents = "、".join(
                humanize_parameter_name(str(item)) for item in profile.get("contents", []) or []
            ) or "未选择"
            self.research_header.setText(
                f"当前研究：{profile.get('structure', '—')} · {profile.get('goal', '—')} · {contents}"
            )
        else:
            self.research_header.setText("当前研究：尚未设置")

        quality = current_model_quality(self.context.registry)
        result = latest_optimization_result(self.context.tasks)
        status = str(result.get("status", "")) if result else ""
        self._set_info(self.formal_state, "正式复核", "已完成" if status == "completed" else (status or "等待"))

        model_name = quality.get("name") or quality.get("model_type") or quality.get("model_id")
        self._set_info(self.compatibility, "当前模型", str(model_name or "尚无可用模型"))
        r2 = quality.get("r2")
        mae = quality.get("mae")
        high_mae = quality.get("high_efficiency_mae")
        
        test_metrics = dict(quality.get("test_metrics", {}) or {})
        if not isinstance(r2, (int, float)):
            r2 = test_metrics.get("r2")
        if not isinstance(mae, (int, float)):
            mae = test_metrics.get("mae")
        self._set_info(self.model_r2, "测试集 R²", f"{float(r2):.4f}" if isinstance(r2, (int, float)) else "—")
        self._set_info(self.model_mae, "测试集 MAE", f"{float(mae):.4g}" if isinstance(mae, (int, float)) else "—")
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
            self._set_info(self.prediction_gap, "当前方案偏差", f"{current_residual[1]:+.4g}")
        else:
            gap = metadata.get("surrogate_error", metadata.get("prediction_error"))
            self._set_info(self.prediction_gap, "当前方案偏差", f"{float(gap):+.4g}" if isinstance(gap, (int, float)) else "—")

        in_domain = metadata.get("within_training_domain", metadata.get("in_training_domain"))
        self._set_info(
            self.training_domain,
            "当前方案训练域",
            "是" if in_domain is True else ("否" if in_domain is False else "未判定"),
        )

        if count:
            metric_labels = {}
            if isinstance(r2, (int, float)):
                metric_labels["R²"] = f"{float(r2):.4f}"
            if isinstance(mae, (int, float)):
                metric_labels["MAE"] = f"{float(mae):.4g}"
            metric_labels["样本数"] = str(count)
            self.analysis_result.set_result(
                0,
                "预测一致性",
                {
                    "kind": "validation_scatter",
                    "actual": actual,
                    "predicted": predicted,
                    "current_point": current_point,
                    "metrics": metric_labels,
                    "title": "模型预测—正式仿真一致性",
                    "x_label": "正式仿真结果",
                    "y_label": "模型预测结果",
                },
            )
            self.analysis_result.set_result(
                1,
                "残差诊断",
                {
                    "kind": "residual",
                    "predicted": predicted,
                    "residual": residual,
                    "actual": actual,
                    "current_point": current_residual,
                    "metrics": metric_labels,
                    "title": "残差诊断",
                    "x_label": "正式仿真结果",
                    "y_label": "预测值 − 正式值",
                },
            )
            mean_residual = sum(residual) / len(residual)
            self.consistency_text.setText("")
            self.residual_text.setText(f"{mean_residual:+.4g}")
            self.explanation_text.setText("")
            self.risk_text.setText("")
        else:
            message = "当前注册模型没有保存独立测试集预测，不能绘制真实一致性或残差图。请重新训练模型。"
            self.analysis_result.set_result(0, "预测一致性", {"kind": "empty", "message": message})
            self.analysis_result.set_result(1, "残差诊断", {"kind": "empty", "message": message})
            self.consistency_text.setText(message)
            self.residual_text.setText("")
            self.explanation_text.setText("")
            self.risk_text.setText("")

    def _set_workflow_step(self, index: int) -> None:
        index = max(0, min(int(index), self.workflow_stack.count() - 1))
        self.workflow_stack.setCurrentIndex(index)
        if 0 <= index < len(self.workflow_buttons):
            self.workflow_buttons[index].setChecked(True)
        if index == 1:
            self._set_datasets({"items": self.context.registry.datasets})
            self._select_training_dataset(self.context.registry.current_dataset_id)
        elif index == 2:
            self._set_models({"models": self.context.registry.models})
            self._select_model_by_id(self.context.registry.current_model_id)

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

    def dispose_page(self) -> None:
        self.workspace_state.save_tab("workflow", self.workflow_stack)
        self._poll_timer.stop()
        self.workflow_stack.dispose()
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
