from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
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
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.components.fast_table import FastTableView
from frontend_pyside.shared.display_names import readable_dataset_name, readable_model_name


class MachineLearningViewMixin:
    def _dataset(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        workbench = QSplitter(Qt.Orientation.Horizontal)
        workbench.setObjectName("machineLearningDatasetSplitter")
        workbench.setChildrenCollapsible(False)
        workbench.setHandleWidth(8)

        config = Card("数据集生成配置", compact=True)
        config.setObjectName("datasetGenerationConfigCard")
        config.setMinimumWidth(300)
        config.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.sampling = QComboBox()
        self.sampling.addItems(["Latin Hypercube", "Sobol低差异采样"])
        self.dataset_count = QSpinBox()
        self.dataset_count.setRange(20, 100000)
        self.dataset_count.setValue(50)
        self.dataset_precision = QComboBox()
        self.dataset_precision.addItems(["预览", "标准", "高精度"])
        self.dataset_target = QComboBox()
        self.dataset_target.addItems(["耦合损耗(dB)", "耦合效率", "RMS 光斑", "Strehl"])
        self.validation_split = QDoubleSpinBox()
        self.validation_split.setRange(0.05, 0.45)
        self.validation_split.setSingleStep(0.05)
        self.validation_split.setValue(0.15)
        self.dataset_seed = QSpinBox()
        self.dataset_seed.setRange(0, 999999)
        self.dataset_seed.setValue(42)

        for label, widget in [
            ("采样方式", self.sampling),
            ("样本数", self.dataset_count),
            ("仿真精度", self.dataset_precision),
            ("目标变量", self.dataset_target),
            ("验证比例", self.validation_split),
            ("随机种子", self.dataset_seed),
        ]:
            label_widget = QLabel(label)
            label_widget.setMinimumHeight(34)
            label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            widget.setMinimumHeight(36)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            form.addRow(label_widget, widget)
        config.body.addLayout(form)

        self.dataset_config_summary = QLabel()
        self.dataset_config_summary.setObjectName("datasetConfigSummary")
        self.dataset_config_summary.setWordWrap(True)
        config.body.addWidget(self.dataset_config_summary)

        submit = PrimaryButton("提交数据集任务")
        submit.clicked.connect(self._submit_dataset)
        config.body.addWidget(submit)
        self.dataset_status = InfoRow("任务状态", "等待提交")
        config.body.addWidget(self.dataset_status)
        config.body.addWidget(InfoRow("输入变量", "仅采样有效曲面曲率、镜间空气间隔和像面距离"))

        self.coupling_submit_btn = SecondaryButton("提交正式耦合数据集任务")
        self.coupling_submit_btn.clicked.connect(self._submit_coupling_dataset)
        config.body.addWidget(self.coupling_submit_btn)
        self.coupling_status = InfoRow("耦合任务", "未提交")
        config.body.addWidget(self.coupling_status)

        
        
        
        
        config.setMinimumHeight(610)
        config_scroll = QScrollArea()
        config_scroll.setObjectName("datasetGenerationConfigScroll")
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        config_scroll.setMinimumWidth(320)
        config_scroll.setMaximumWidth(430)
        config_scroll.setWidget(config)
        workbench.addWidget(config_scroll)

        work = QWidget()
        work_layout = QVBoxLayout(work)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(7)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        self.dataset_summary_label = QLabel("0个数据集 · 0条样本 · 0项输入 · 0项目标")
        self.dataset_summary_label.setObjectName("datasetCompactSummary")
        summary_row.addWidget(self.dataset_summary_label, 1)
        refresh = SecondaryButton("刷新")
        refresh.clicked.connect(self.refresh_remote)
        summary_row.addWidget(refresh)
        work_layout.addLayout(summary_row)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setObjectName("machineLearningDatasetDetailSplitter")
        vertical.setChildrenCollapsible(False)
        self.datasets_table = FastTableView(
            ["数据集", "样本数", "输入维度", "目标", "状态", "创建时间", "ID"]
        )
        self.datasets_table.stretch_columns(0, 3)
        self.datasets_table.setColumnHidden(6, True)
        self.datasets_table.currentCellChanged.connect(self._load_dataset_detail)
        vertical.addWidget(self.datasets_table)

        detail = Card("选中数据集详情", compact=True)
        self.dataset_detail = InfoRow("未选择", "请从上方列表中选择")
        detail.body.addWidget(self.dataset_detail)
        btn_row = QHBoxLayout()
        self.rename_dataset_button = SecondaryButton("重命名")
        self.rename_dataset_button.clicked.connect(self._rename_selected_dataset)
        btn_row.addWidget(self.rename_dataset_button)
        self.download_manifest_button = SecondaryButton("查看清单")
        self.download_manifest_button.clicked.connect(self._download_manifest)
        btn_row.addWidget(self.download_manifest_button)
        self.download_flat_button = SecondaryButton("导出 CSV")
        self.download_flat_button.clicked.connect(self._download_samples_flat)
        btn_row.addWidget(self.download_flat_button)
        self.download_jsonl_button = SecondaryButton("导出 JSON")
        self.download_jsonl_button.clicked.connect(self._download_samples_jsonl)
        btn_row.addWidget(self.download_jsonl_button)
        btn_row.addStretch(1)
        detail.body.addLayout(btn_row)
        vertical.addWidget(detail)
        vertical.setStretchFactor(0, 7)
        vertical.setStretchFactor(1, 3)
        vertical.setSizes([680, 220])
        work_layout.addWidget(vertical, 1)

        workbench.addWidget(work)
        workbench.setStretchFactor(0, 0)
        workbench.setStretchFactor(1, 1)
        workbench.setSizes([340, 1180])
        root.addWidget(workbench, 1)

        for widget in (
            self.sampling,
            self.dataset_count,
            self.dataset_precision,
            self.dataset_target,
            self.validation_split,
        ):
            signal = getattr(widget, "currentTextChanged", None) or getattr(
                widget, "valueChanged", None
            )
            if signal is not None:
                signal.connect(self._update_dataset_config_summary)
        self._update_dataset_config_summary()
        return page

    def _update_dataset_config_summary(self, *_args) -> None:
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
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        workbench = QSplitter(Qt.Orientation.Horizontal)
        workbench.setObjectName("machineLearningTrainingSplitter")
        workbench.setChildrenCollapsible(False)
        workbench.setHandleWidth(8)

        config = Card("训练配置", compact=True)
        config.setObjectName("trainingConfigCard")
        config.setMinimumWidth(300)
        config.setMaximumWidth(390)
        form = QFormLayout()
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(10)
        self.training_dataset = QComboBox()
        self.training_dataset.currentIndexChanged.connect(self._training_dataset_changed)
        self.model_type = QComboBox()
        self.model_type.addItem("随机森林", "random_forest")
        self.model_type.addItem("XGBoost物理残差", "xgboost_physics_residual")
        self.model_type.currentIndexChanged.connect(self._update_training_parameter_label)
        self.training_epochs = QSpinBox()
        self.training_epochs.setRange(10, 10000)
        self.training_epochs.setValue(300)
        self.training_seed = QSpinBox()
        self.training_seed.setRange(0, 999999)
        self.training_seed.setValue(42)
        self.training_parameter_label = QLabel("决策树数量")
        form.addRow("数据集", self.training_dataset)
        form.addRow("模型", self.model_type)
        form.addRow(self.training_parameter_label, self.training_epochs)
        form.addRow("随机种子", self.training_seed)
        config.body.addLayout(form)
        submit = PrimaryButton("开始训练")
        submit.clicked.connect(self._submit_training)
        config.body.addWidget(submit)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(7)
        self.training_progress = QProgressBar()
        self.training_progress.setValue(0)
        self.training_progress.setTextVisible(True)
        progress_row.addWidget(self.training_progress, 1)
        self.training_status = InfoRow("状态", "等待提交")
        progress_row.addWidget(self.training_status)
        config.body.addLayout(progress_row)
        workbench.addWidget(config)

        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        cards = QHBoxLayout()
        cards.setSpacing(7)
        self.training_r2 = InlineMetric("R²", "—")
        self.training_mae = InlineMetric("MAE", "—")
        self.training_rmse = InlineMetric("RMSE", "—")
        self.training_time = InlineMetric("训练时间", "—", "ms")
        for card in (self.training_r2, self.training_mae, self.training_rmse, self.training_time):
            cards.addWidget(card, 1)
        layout.addLayout(cards)

        from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
        self.training_result = ResultWorkspace()
        self.training_result.set_single_view_only(True)
        self.training_result.set_toolbar_visible(False)
        self.training_result.set_maximize_controls_visible(False)
        self.training_result.set_result(0, "训练结果", {"kind": "empty", "message": "训练完成后显示评估结果"})
        layout.addWidget(self.training_result, 1)
        workbench.addWidget(right)
        workbench.setStretchFactor(0, 0)
        workbench.setStretchFactor(1, 1)
        workbench.setSizes([340, 1180])
        root.addWidget(workbench, 1)
        return page

    def _update_training_parameter_label(self, *_args) -> None:
        if not hasattr(self, "training_parameter_label"):
            return
        model_type = str(self.model_type.currentData() or "random_forest")
        self.training_parameter_label.setText(
            "决策树数量" if model_type == "random_forest" else "提升轮次"
        )

    def _models_page(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        workbench = QSplitter(Qt.Orientation.Horizontal)
        workbench.setObjectName("machineLearningModelSplitter")
        workbench.setChildrenCollapsible(False)
        workbench.setHandleWidth(8)

        self.models_table = FastTableView(
            ["模型", "类型", "数据集", "R²", "MAE", "RMSE", "创建时间", "ID"]
        )
        self.models_table.stretch_columns(0, 1)
        self.models_table.setColumnHidden(7, True)
        self.models_table.currentCellChanged.connect(self._on_model_selected)
        workbench.addWidget(self.models_table)

        detail = Card("模型操作", compact=True)
        detail.setMinimumWidth(300)
        detail.setMaximumWidth(420)
        self.model_detail = InfoRow("模型列表", "等待后端数据")
        detail.body.addWidget(self.model_detail)
        self.pred_model_label = InfoRow("当前模型", "未选择")
        detail.body.addWidget(self.pred_model_label)
        self.pred_result_label = InfoRow("预测结果", "—")
        detail.body.addWidget(self.pred_result_label)
        self.pred_warning_label = InfoRow("提示", "—")
        detail.body.addWidget(self.pred_warning_label)
        apply_btn = PrimaryButton("应用到全部功能")
        apply_btn.clicked.connect(self._apply_selected_model_globally)
        detail.body.addWidget(apply_btn)
        rename_btn = SecondaryButton("重命名")
        rename_btn.clicked.connect(self._rename_selected_model)
        detail.body.addWidget(rename_btn)
        pred_btn = SecondaryButton("预测当前方案")
        pred_btn.clicked.connect(self._predict_with_current)
        detail.body.addWidget(pred_btn)
        refresh = SecondaryButton("刷新")
        refresh.clicked.connect(self._refresh_models)
        detail.body.addWidget(refresh)
        workbench.addWidget(detail)
        workbench.setStretchFactor(0, 1)
        workbench.setStretchFactor(1, 0)
        workbench.setSizes([1120, 360])
        root.addWidget(workbench, 1)
        return page

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
        self._set_info(
            self.pred_model_label,
            "当前模型",
            f"{name} · {feature_count}项输入",
        )
        self._selected_model_id = model_id
        self.context.registry.set_current_model(model_id)

    def _predict_with_current(self) -> None:
        model_id = getattr(self, "_selected_model_id", None)
        if not model_id:
            self._set_info(self.pred_result_label, "预测结果", "请先从列表选择模型")
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
            return

        token = self.lifecycle.generations.next("ml-predict")
        self.training_client.predict(f"ml.predict.{token}.{model_id}", model_id, features)
        self._set_info(
            self.pred_result_label,
            "预测结果",
            f"正在请求后端预测（{len(features)} 个 manifest 特征）",
        )

