from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QMessageBox,
    QProgressBar,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.machine_learning.feature_adapter import (
    FeaturePathError,
    features_from_project,
)
from frontend_pyside.shared.components.basic import (
    Card,
    FormGrid,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared import layout_tokens as ui_layout
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.components.fast_table import FastTableView
from frontend_pyside.shared.display_names import readable_dataset_name, readable_model_name


class MachineLearningViewMixin:
    def _dataset(self) -> QWidget:
        """Data preparation as a settings/result task workspace.

        At 1366×768 the former vertical page compressed three form rows into each
        other.  Data generation is a complex task, so use the same pattern as
        parameter research: compact settings on the left, datasets/results on the
        right, with no page scrolling required.
        """
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal, page)
        splitter.setObjectName("mlDataTaskSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        config = Card("数据集设置", compact=True)
        config.setObjectName("datasetGenerationConfigCard")
        config.setMinimumWidth(350); config.setMaximumWidth(430)
        self.sampling = QComboBox(); self.sampling.addItems(["Latin Hypercube", "Sobol低差异采样"])
        self.dataset_count = QSpinBox(); self.dataset_count.setRange(20, 100000); self.dataset_count.setValue(50); self.dataset_count.setMinimumWidth(196)
        self.dataset_precision = QComboBox(); self.dataset_precision.addItems(["129×129", "257×257", "513×513"])
        self.dataset_target = QComboBox(); self.dataset_target.addItems(["耦合损耗(dB)", "耦合效率", "RMS 光斑", "Strehl"])
        self.validation_split = QDoubleSpinBox(); self.validation_split.setRange(0.05, 0.45); self.validation_split.setSingleStep(0.05); self.validation_split.setValue(0.15); self.validation_split.setMinimumWidth(196)
        self.dataset_seed = QSpinBox(); self.dataset_seed.setRange(0, 999999); self.dataset_seed.setValue(42); self.dataset_seed.setMinimumWidth(196)
        form = FormGrid(label_width=88)
        for label, widget in (("采样方式", self.sampling), ("样本数", self.dataset_count),
                              ("采样网格", self.dataset_precision), ("目标变量", self.dataset_target),
                              ("验证比例", self.validation_split), ("随机种子", self.dataset_seed)):
            widget.setMaximumWidth(230)
            form.add_row(label, widget)
        config.body.addWidget(form)
        self.dataset_config_summary = QLabel()
        self.dataset_config_summary.setObjectName("datasetConfigSummary")
        self.dataset_config_summary.setWordWrap(True)
        config.body.addWidget(self.dataset_config_summary)
        self.dataset_status = InfoRow("任务状态", "等待提交"); config.body.addWidget(self.dataset_status)
        self.dataset_progress = QProgressBar(); self.dataset_progress.setRange(0,100); self.dataset_progress.setValue(0); self.dataset_progress.setTextVisible(True); self.dataset_progress.setFormat("等待开始")
        config.body.addWidget(self.dataset_progress)
        self.coupling_status = InfoRow("正式数据", "未提交"); config.body.addWidget(self.coupling_status)
        action_row = QHBoxLayout(); action_row.setSpacing(ui_layout.CONTROL_GAP)
        self.coupling_submit_btn = SecondaryButton("正式耦合数据"); self.coupling_submit_btn.clicked.connect(self._submit_coupling_dataset); action_row.addWidget(self.coupling_submit_btn)
        submit = PrimaryButton("生成数据集"); submit.clicked.connect(self._submit_dataset); action_row.addWidget(submit)
        action_row.addStretch(1); config.body.addLayout(action_row)
        config.body.addStretch(1)
        splitter.addWidget(config)

        results = QWidget(page)
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(ui_layout.CONTROL_GAP, 0, 0, 0)
        results_layout.setSpacing(ui_layout.CONTROL_GAP)
        list_card = Card("已有数据集", compact=True)
        summary_row = QHBoxLayout(); summary_row.setContentsMargins(0,0,0,0)
        self.dataset_summary_label = QLabel("0个数据集 · 0条样本"); self.dataset_summary_label.setObjectName("datasetCompactSummary")
        summary_row.addWidget(self.dataset_summary_label, 1)
        refresh = SecondaryButton("刷新"); refresh.clicked.connect(self.refresh_remote); summary_row.addWidget(refresh)
        list_card.body.addLayout(summary_row)
        self.datasets_table = FastTableView(["数据集", "样本数", "目标", "状态", "创建时间", "ID"])
        self.datasets_table.stretch_columns(0,2); self.datasets_table.setColumnHidden(5,True)
        self.datasets_table.currentCellChanged.connect(self._load_dataset_detail)
        self.datasets_table.setMinimumHeight(260)
        list_card.body.addWidget(self.datasets_table, 1)
        results_layout.addWidget(list_card, 1)

        detail = Card("选中数据集", compact=True)
        self.dataset_detail = InfoRow("未选择", "请从上方列表中选择")
        detail.body.addWidget(self.dataset_detail)
        btn_row = QHBoxLayout(); btn_row.setSpacing(7)
        self.rename_dataset_button = SecondaryButton("重命名"); self.rename_dataset_button.clicked.connect(self._rename_selected_dataset); btn_row.addWidget(self.rename_dataset_button)
        self.download_manifest_button = SecondaryButton("查看清单"); self.download_manifest_button.clicked.connect(self._download_manifest); btn_row.addWidget(self.download_manifest_button)
        self.download_flat_button = SecondaryButton("导出 CSV"); self.download_flat_button.clicked.connect(self._download_samples_flat); btn_row.addWidget(self.download_flat_button)
        self.download_jsonl_button = SecondaryButton("导出 JSON"); self.download_jsonl_button.clicked.connect(self._download_samples_jsonl); btn_row.addWidget(self.download_jsonl_button)
        btn_row.addStretch(1); detail.body.addLayout(btn_row)
        results_layout.addWidget(detail, 0)
        splitter.addWidget(results)
        splitter.setStretchFactor(0,0); splitter.setStretchFactor(1,1); splitter.setSizes([390,900])
        root.addWidget(splitter,1)

        for widget in (self.sampling, self.dataset_count, self.dataset_precision, self.dataset_target, self.validation_split):
            signal = getattr(widget, "currentTextChanged", None) or getattr(widget, "valueChanged", None)
            if signal is not None: signal.connect(self._update_dataset_config_summary)
        self._update_dataset_config_summary()
        return page

    def _update_dataset_config_summary(self, *_args) -> None:
        # 该方法会被多个控件的 valueChanged/currentIndexChanged 信号触发。
        # 页面首次懒加载时，信号可能早于全部控件创建完成，因此先确认
        # 摘要所依赖的控件已经存在，避免第一次打开“训练与版本”时报错。
        required = (
            "validation_split",
            "dataset_count",
            "dataset_target",
            "dataset_config_summary",
        )
        if not all(hasattr(self, name) for name in required):
            return
        try:
            from frontend_pyside.features.machine_learning.dataset_configuration import build_dataset_parameters
            feature_count = len(build_dataset_parameters(self._current_dataset_project_payload()))
        except Exception:
            feature_count = 0
        validation = self.validation_split.value()
        test = min(0.15, max(0.05, validation))
        train = max(0.0, 1.0 - validation - test)
        self.dataset_config_summary.setText(
            f"预计样本：{self.dataset_count.value()}\n"
            f"输入特征：{feature_count if feature_count else '未检测到'} 项\n"
            f"输出目标：{self.dataset_target.currentText()}\n"
            f"数据划分：训练 {train:.0%} · 验证 {validation:.0%} · 测试 {test:.0%}"
        )

    def _training(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(ui_layout.CARD_GAP)

        config = Card("训练配置", compact=True)
        config.setObjectName("trainingConfigCard")
        self.training_dataset = QComboBox(); self.training_dataset.currentIndexChanged.connect(self._training_dataset_changed)
        self.model_type = QComboBox()
        self.model_type.addItem("随机森林", "random_forest")
        self.model_type.addItem("XGBoost物理残差", "xgboost_physics_residual")
        self.model_type.currentIndexChanged.connect(self._update_training_parameter_label)
        self.training_epochs = QSpinBox(); self.training_epochs.setRange(10, 10000); self.training_epochs.setValue(300)
        self.training_epochs.setToolTip("随机森林表示树数量；XGBoost表示允许的最大提升轮数")
        self.training_seed = QSpinBox(); self.training_seed.setRange(0, 999999); self.training_seed.setValue(42)
        self.training_parameter_label = QLabel("决策树数量")
        self.training_early_stop = QCheckBox("启用早停")
        self.training_early_stop.setChecked(True)
        self.training_early_stop.setToolTip("仅用于支持验证集早停的迭代模型；随机森林不显示此项")
        self.training_patience = QSpinBox(); self.training_patience.setRange(2, 500); self.training_patience.setValue(20)
        self.training_patience.setToolTip("验证指标连续多少轮没有改善后提前停止，并恢复最佳轮次")
        # Do not rely on a parent QSS selector for the minimum touch target: the
        # training page can be embedded in more than one shell and some shells
        # deliberately replace the application stylesheet.  A local minimum
        # keeps every editable field usable at high DPI and 1366×768 alike.
        for control in (
            self.training_dataset,
            self.model_type,
            self.training_epochs,
            self.training_seed,
            self.training_patience,
        ):
            control.setMinimumHeight(38)
        form = FormGrid()
        self.training_dataset.setMaximumWidth(360)
        form.add_row("数据集", self.training_dataset, "用于训练、验证和独立测试的数据")
        form.add_row("模型", self.model_type, "不同模型显示与自身训练机制匹配的参数")
        form.add_row("决策树数量", self.training_epochs, "随机森林：树数量；XGBoost：最大提升轮数")
        self._training_parameter_form_label = form.grid.itemAtPosition(2, 0).widget()
        self._training_early_stop_form_label = form.add_row("早停", self.training_early_stop, "XGBoost使用验证集监控；达到耐心值后恢复最佳轮次")
        self._training_patience_form_label = form.add_row("耐心轮数", self.training_patience, "连续无改善轮数")
        form.add_row("随机种子", self.training_seed, "保证同一设置可复现")
        config.body.addWidget(form)
        submit_row = QHBoxLayout(); submit_row.addStretch(1)
        self.training_submit_button = PrimaryButton("开始训练")
        self.training_submit_button.clicked.connect(self._submit_training)
        submit_row.addWidget(self.training_submit_button)
        config.body.addLayout(submit_row)
        root.addWidget(config)

        result_card = Card("训练状态与结果", compact=True)
        training_progress_panel = QFrame()
        training_progress_panel.setObjectName("taskProgressPanel")
        training_progress_layout = QVBoxLayout(training_progress_panel)
        training_progress_layout.setContentsMargins(8, 6, 8, 7)
        training_progress_layout.setSpacing(5)
        self.training_status = InfoRow("状态", "等待提交")
        training_progress_layout.addWidget(self.training_status)
        self.training_progress = QProgressBar()
        self.training_progress.setValue(0)
        self.training_progress.setTextVisible(True)
        self.training_progress.setObjectName("taskProgressBar")
        training_progress_layout.addWidget(self.training_progress)
        result_card.body.addWidget(training_progress_panel)
        cards = QHBoxLayout(); cards.setSpacing(7)
        self.training_r2 = InlineMetric("验证 R²", "—")
        self.training_mae = InlineMetric("验证 MAE", "—")
        self.training_rmse = InlineMetric("验证 RMSE", "—")
        self.training_time = InlineMetric("训练时间", "—", "ms")
        for card in (self.training_r2, self.training_mae, self.training_rmse, self.training_time): cards.addWidget(card, 1)
        result_card.body.addLayout(cards)
        self.training_run_summary = QLabel("训练完成后显示训练预算、实际执行量、最佳轮次、早停与收敛状态。")
        self.training_run_summary.setObjectName("mutedText")
        self.training_run_summary.setWordWrap(True)
        result_card.body.addWidget(self.training_run_summary)
        note_row = QHBoxLayout()
        self.training_adopt_note = QLabel("训练完成只产生新模型版本，不会自动替换当前模型。")
        self.training_adopt_note.setObjectName("mutedText"); self.training_adopt_note.setWordWrap(True)
        note_row.addWidget(self.training_adopt_note, 1)
        self.training_adopt_button = SecondaryButton("设为当前模型"); self.training_adopt_button.setEnabled(False)
        self.training_adopt_button.clicked.connect(self._adopt_recent_model)
        note_row.addWidget(self.training_adopt_button); result_card.body.addLayout(note_row)
        from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
        self.training_result = ResultWorkspace(); self.training_result.setMinimumHeight(300)
        self.training_result.set_single_view_only(True); self.training_result.set_toolbar_visible(False); self.training_result.set_maximize_controls_visible(False)
        self.training_result.set_plot_tools_visible(False); self.training_result.set_footer_visible(False)
        self.training_result.set_result(0, "训练诊断", {"kind":"empty","message":"训练完成后显示与当前模型相匹配的诊断图"})
        result_card.body.addWidget(self.training_result)
        root.addWidget(result_card)
        # Apply model-specific visibility once all FormGrid rows exist.  The
        # default random-forest selection does not emit currentIndexChanged on
        # construction, otherwise early-stop controls incorrectly remain visible.
        self._update_training_parameter_label()
        return page

    def _adopt_recent_model(self) -> None:
        model_id = str(getattr(self.context.registry, "recent_model_id", "") or "")
        if not model_id:
            self._set_info(self.training_status, "状态", "没有可采用的新模型")
            return
        self.context.registry.set_current_model(model_id)
        self.training_adopt_note.setText(f"已将 {model_id} 设为当前模型；SHAP、优化和智能助手将统一读取该版本。")
        self.training_adopt_button.setEnabled(False)

    def _update_training_parameter_label(self, *_args) -> None:
        if not hasattr(self, "training_parameter_label"):
            return
        model_type = str(self.model_type.currentData() or "random_forest")
        is_rf = model_type == "random_forest"
        text = "决策树数量" if is_rf else "最大提升轮数"
        self.training_parameter_label.setText(text)
        if hasattr(self, "_training_parameter_form_label"):
            self._training_parameter_form_label.setText(text)
        grid = getattr(getattr(self, "_training_parameter_form_label", None), "parentWidget", lambda: None)()
        form_grid = None
        # The labels returned by FormGrid share its QGridLayout parent. Hide every cell
        # in the early-stop rows so helper text never remains as an orphan line.
        for anchor_name in ("_training_early_stop_form_label", "_training_patience_form_label"):
            anchor = getattr(self, anchor_name, None)
            if anchor is None:
                continue
            parent = anchor.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is not None and hasattr(layout, "getItemPosition"):
                index = layout.indexOf(anchor)
                if index >= 0:
                    row, _col, _rs, _cs = layout.getItemPosition(index)
                    for item_index in range(layout.count()):
                        item_row, _item_col, _irs, _ics = layout.getItemPosition(item_index)
                        if item_row == row:
                            widget = layout.itemAt(item_index).widget()
                            if widget is not None:
                                widget.setVisible(not is_rf)

    def _models_page(self) -> QWidget:
        """Model comparison/version selection; prediction lives in its own next stage."""
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(ui_layout.CARD_GAP)

        versions = Card("模型比较与版本", compact=True)
        top = QHBoxLayout()
        top.addWidget(QLabel("随机森林、XGBoost 与已有结构模型在同一张表中比较；选定后再进入正向预测。"), 1)
        refresh = SecondaryButton("刷新")
        refresh.clicked.connect(self._refresh_models)
        top.addWidget(refresh)
        versions.body.addLayout(top)
        self.models_table = FastTableView(["模型", "类型", "数据集", "测试 R²", "测试 MAE", "测试 RMSE", "创建时间", "ID"])
        self.models_table.stretch_columns(0, 1)
        self.models_table.setColumnHidden(7, True)
        self.models_table.currentCellChanged.connect(self._on_model_selected)
        self.models_table.setMinimumHeight(300)
        versions.body.addWidget(self.models_table)
        root.addWidget(versions, 1)

        detail = Card("当前选择", compact=True)
        info_grid = QGridLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setHorizontalSpacing(18)
        info_grid.setVerticalSpacing(5)
        self.model_detail = InfoRow("模型", "等待后端数据")
        self.model_selection_state = InfoRow("使用状态", "未选择")
        info_grid.addWidget(self.model_detail, 0, 0)
        info_grid.addWidget(self.model_selection_state, 0, 1)
        detail.body.addLayout(info_grid)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        apply_btn = PrimaryButton("设为当前模型")
        apply_btn.clicked.connect(self._apply_selected_model_globally)
        actions.addWidget(apply_btn)
        to_prediction = SecondaryButton("进入正向预测")
        to_prediction.clicked.connect(lambda: self._set_workflow_step(4))
        actions.addWidget(to_prediction)
        rename_btn = SecondaryButton("重命名")
        rename_btn.clicked.connect(self._rename_selected_model)
        actions.addWidget(rename_btn)
        actions.addStretch(1)
        detail.body.addLayout(actions)
        root.addWidget(detail)
        return page

    def _prediction_page(self) -> QWidget:
        """Focused forward prediction: current system -> surrogate -> physical verification."""
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(ui_layout.CARD_GAP)

        card = Card("预测", compact=True)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(ui_layout.CONTROL_GAP)
        forward_mode = PrimaryButton("正向预测")
        forward_mode.setEnabled(False)
        inverse_mode = SecondaryButton("反向预测")
        self.inverse_prediction_button = inverse_mode
        inverse_mode.setToolTip("目标性能 → 参数候选 → 正式物理验证")
        inverse_mode.clicked.connect(self.inversePredictionRequested.emit)
        mode_row.addWidget(forward_mode)
        mode_row.addWidget(inverse_mode)
        mode_row.addStretch(1)
        card.body.addLayout(mode_row)
        intro = QLabel("当前系统参数 → 代理模型快速预测；预测值不是正式物理结果，结果旁可直接解释或正式验证。")
        intro.setWordWrap(True)
        intro.setObjectName("mutedText")
        card.body.addWidget(intro)

        info = QGridLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setHorizontalSpacing(18)
        info.setVerticalSpacing(5)
        self.pred_model_label = InfoRow("当前模型", "尚未选择")
        self.pred_input_label = InfoRow("输入", "当前系统")
        self.pred_result_label = InfoRow("预测结果", "—")
        self.pred_warning_label = InfoRow("模型范围", "等待预测")
        for i, item in enumerate((self.pred_model_label, self.pred_input_label, self.pred_result_label, self.pred_warning_label)):
            info.addWidget(item, i // 2, i % 2)
        card.body.addLayout(info)

        self.prediction_progress_panel = QFrame(page)
        self.prediction_progress_panel.setObjectName("taskProgressPanel")
        progress_layout = QVBoxLayout(self.prediction_progress_panel)
        progress_layout.setContentsMargins(10, 8, 10, 8)
        progress_layout.setSpacing(5)
        self.prediction_progress_label = QLabel("准备预测")
        self.prediction_progress_label.setObjectName("taskProgressLabel")
        self.prediction_progress = QProgressBar()
        self.prediction_progress.setObjectName("taskProgressBar")
        self.prediction_progress.setRange(0, 0)
        self.prediction_progress.setTextVisible(False)
        progress_layout.addWidget(self.prediction_progress_label)
        progress_layout.addWidget(self.prediction_progress)
        self.prediction_progress_panel.hide()
        card.body.addWidget(self.prediction_progress_panel)

        actions = QHBoxLayout()
        actions.setSpacing(ui_layout.CONTROL_GAP)
        self.prediction_button = PrimaryButton("开始预测")
        self.prediction_button.clicked.connect(self._predict_current_project)
        actions.addWidget(self.prediction_button)
        explain = SecondaryButton("解释结果")
        explain.clicked.connect(lambda: self.navigateRequested.emit("explainability"))
        actions.addWidget(explain)
        verify = SecondaryButton("正式仿真验证")
        verify.clicked.connect(lambda: self.navigateRequested.emit("simulation"))
        actions.addWidget(verify)
        actions.addStretch(1)
        card.body.addLayout(actions)
        root.addWidget(card)

        note = QLabel("预测完成后可直接解释结果或回到主仿真工作台做正式验证。")
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)
        return page

    def _predict_current_project(self) -> None:
        model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
        if not model_id and getattr(self, "_selected_model_id", None):
            model_id = str(self._selected_model_id or "")
        if not model_id and self.context.registry.models:
            record = self.context.registry.models[0]
            model_id = str(record.get("model_id", record.get("id", "")) or "")
        if not model_id:
            self._set_info(self.pred_result_label, "预测结果", "没有可用模型；请先完成训练或从模型比较中选择一个模型")
            if hasattr(self, "prediction_button"):
                self.prediction_button.set_task_state("error", "没有可用模型")
            return
        self._selected_model_id = model_id
        self._select_model_by_id(model_id)
        self._predict_with_current()

    def _rename_selected_dataset(self) -> None:
        dataset_id = self._selected_dataset_id()
        if not dataset_id:
            return
        record = self.context.registry.dataset(dataset_id) or {}
        current = readable_dataset_name(record, aliases=getattr(self, "registry_aliases", None))
        name, accepted = QInputDialog.getText(self, "重命名数据集", "名称", text=current)
        if not accepted or not str(name).strip():
            return
        self.registry_aliases.set("dataset", dataset_id, str(name).strip())
        self._set_datasets({"items": self.context.registry.datasets}, publish=False)

    def _rename_selected_model(self) -> None:
        row = self.models_table.currentRow()
        models = self.context.registry.models
        if not 0 <= row < len(models):
            return
        record = models[row]
        model_id = str(record.get("model_id", record.get("id", "")) or "")
        current = readable_model_name(record, row, aliases=getattr(self, "registry_aliases", None))
        name, accepted = QInputDialog.getText(self, "重命名模型", "名称", text=current)
        if not accepted or not str(name).strip():
            return
        self.registry_aliases.set("model", model_id, str(name).strip())
        self._set_models({"models": self.context.registry.models}, publish=False)

    def _apply_selected_model_globally(self) -> None:
        row = self.models_table.currentRow()
        models = self.context.registry.models
        if not 0 <= row < len(models):
            return
        record = models[row]
        model_id = str(record.get("model_id", record.get("id", "")) or "")
        if not model_id:
            return
        self.context.registry.set_current_model(model_id)
        name = readable_model_name(record, row, aliases=getattr(self, "registry_aliases", None))
        if hasattr(self, "model_selection_state"):
            self._set_info(self.model_selection_state, "当前模型", f"{name} · 已应用")
        if hasattr(self, "pred_model_label"):
            self._set_info(self.pred_model_label, "当前模型", f"{name} · 已应用")

    def _training_dataset_changed(self, *_args) -> None:
        dataset_id = str(self.training_dataset.currentData() or "")
        if dataset_id:
            self.context.registry.set_current_dataset(dataset_id)

    def _on_model_selected(self, row: int, *_args) -> None:
        models = self.context.registry.models
        if not 0 <= row < len(models):
            return
        record = models[row]
        model_id = str(record.get("model_id", record.get("id", "")))
        friendly = getattr(self, "_friendly_model_name", None)
        name = friendly(record, row) if callable(friendly) else str(record.get("name", model_id))
        feature_count = len(record.get("feature_paths", []) or [])
        adopted_id = str(getattr(self.context.registry, "current_model_id", "") or "")
        target = getattr(self, "model_selection_state", None)
        if target is not None:
            self._set_info(
                target,
                "当前模型" if model_id == adopted_id else "已选模型",
                f"{name} · {feature_count}项输入" + (" · 当前" if model_id == adopted_id else " · 尚未应用"),
            )
        if hasattr(self, "pred_model_label"):
            self._set_info(self.pred_model_label, "当前模型", f"{name} · {feature_count}项输入")
        self._selected_model_id = model_id

    def _predict_with_current(self) -> None:
        model_id = getattr(self, "_selected_model_id", None)
        if not model_id:
            self._set_info(self.pred_result_label, "预测结果", "请先从列表选择模型")
            if hasattr(self, "prediction_button"):
                self.prediction_button.set_task_state("error", "请先选择模型")
            return

        model_record = next(
            (
                item
                for item in self.context.registry.models
                if str(item.get("model_id", item.get("id", ""))) == model_id
            ),
            None,
        )
        if not model_record:
            self._set_info(
                self.pred_result_label,
                "预测结果",
                "模型 manifest 不在当前列表中，请刷新模型列表",
            )
            if hasattr(self, "prediction_button"):
                self.prediction_button.set_task_state("error", "模型不可用")
            return

        feature_paths = list(model_record.get("feature_paths", []) or [])
        try:
            project_payload = self._current_dataset_project_payload()
            features = features_from_project(project_payload, feature_paths)
        except FeaturePathError as exc:
            self._set_info(
                self.pred_result_label,
                "预测结果",
                f"当前项目无法构造模型特征：{exc}",
            )
            self._set_info(
                self.pred_warning_label,
                "提示",
                "模型预测严格使用 manifest.feature_paths；请检查项目与训练数据契约",
            )
            if hasattr(self, "prediction_button"):
                self.prediction_button.set_task_state("error", "特征不匹配")
            return

        if hasattr(self, "prediction_button"):
            self.prediction_button.set_task_state("running", "预测中")
        if hasattr(self, "prediction_progress_panel"):
            self.prediction_progress_label.setText(f"正在调用当前代理模型 · {len(features)} 项输入")
            self.prediction_progress.setRange(0, 0)
            self.prediction_progress_panel.show()

        token = self.lifecycle.generations.next("ml-predict")
        self.training_client.predict(f"ml.predict.{token}.{model_id}", model_id, features)
        self._set_info(
            self.pred_result_label,
            "预测结果",
            f"正在请求后端预测（{len(features)} 个 manifest 特征）",
        )
