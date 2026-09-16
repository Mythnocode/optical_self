"""Model document tabs.

The shell owns navigation and orchestration; this module owns the model and training/prediction document surfaces.
"""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared

# Shared Qt imports and helper functions remain in the neutral tab-shared
# module during this compatibility-preserving extraction.
globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

class ModelDocument(QWidget):
    trainRequested = Signal()
    generateRequested = Signal()
    predictRequested = Signal()
    datasetGenerated = Signal(str)
    fileImportRequested = Signal(str)
    dataKindChanged = Signal(str)

    def __init__(self, kind: str, context, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.context = context
        self._trained = False
        self._train_result: dict[str, Any] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        if kind == "dataset":
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(8)
            self._build_dataset(content_layout)
            scroll.setWidget(content)
            root.addWidget(scroll)
            self.dataset_scroll = scroll
        elif kind == "train_result":
            self._build_train_result(root)
        else:
            self._build_predict(root)

    def current_family(self) -> str:
        combo = getattr(self, "data_kind", None)
        if combo is None:
            return "tabular"
        return str(combo.currentData() or "tabular")

    def _build_dataset(self, root: QVBoxLayout) -> None:
        layout = root
        source, source_layout = _field_group("1. 选择数据")
        kind_row = QHBoxLayout()
        kind_row.setContentsMargins(0, 0, 0, 0)
        kind_row.setSpacing(8)
        self.data_kind = QComboBox()
        self.data_kind.addItem("按镜头采样", "tabular")
        self.data_kind.addItem("按元件排列", "sequence")
        kind_row.addWidget(QLabel("方式"))
        kind_row.addWidget(self.data_kind, 1)
        source_layout.addLayout(kind_row)
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.setSpacing(8)
        self.builtin = QComboBox()
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("选择 CSV / JSONL 样本文件")
        browse = QPushButton("选择文件")
        browse.clicked.connect(self._choose_file)
        pick_row.addWidget(QLabel("内置"))
        pick_row.addWidget(self.builtin, 1)
        pick_row.addWidget(self.file_path, 2)
        pick_row.addWidget(browse)
        source_layout.addLayout(pick_row)
        layout.addWidget(source)

        generate, generate_layout = _field_group("2. 生成样本")
        self.generate_host = generate
        param_grid = QGridLayout()
        param_grid.setContentsMargins(0, 0, 0, 0)
        param_grid.setHorizontalSpacing(12)
        self.generate_checks: dict[str, QCheckBox] = {}
        self.lens_count = QComboBox()
        for label, value in (("单透镜", 1), ("双透镜", 2), ("三透镜", 3), ("四透镜", 4)):
            self.lens_count.addItem(label, value)
        self.lens_count.setCurrentIndex(3)
        self.variable_scheme = QComboBox()
        self.variable_scheme.addItem("曲率半径 + 厚度", "basic")
        self.variable_scheme.addItem("曲率半径 + 厚度 + 圆锥系数", "asphere")
        self.scheme_summary = QLabel("四透镜·基础方案 · 12 个设计变量；内部物理量自动计算")
        self.scheme_summary.setObjectName("HelperText")
        param_grid.addWidget(QLabel("研究对象"), 0, 0)
        param_grid.addWidget(self.lens_count, 0, 1)
        param_grid.addWidget(QLabel("变量方案"), 0, 2)
        param_grid.addWidget(self.variable_scheme, 0, 3)
        param_grid.addWidget(self.scheme_summary, 1, 0, 1, 4)
        self.lens_count.currentIndexChanged.connect(self._sync_scheme_summary)
        self.variable_scheme.currentIndexChanged.connect(self._sync_scheme_summary)
        generate_layout.addLayout(param_grid)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.sampling = QComboBox()
        self.sampling.addItems(list(DATASET_SAMPLING_CHOICES))
        self.samples = _spin(8, 100000, 0, "", 50)
        self.target = QComboBox()
        self.target.addItems(list(DATASET_TARGET_CHOICES))
        self.split = _spin(0.05, 0.4, 2, "", 0.15)
        self.seed = _spin(0, 1e9, 0, "", 42)
        self.precision = QComboBox()
        self.precision.addItems(list(DATASET_PRECISION_CHOICES))
        self.precision.setCurrentText("257×257")
        grid.addWidget(QLabel("采样方法"), 0, 0)
        grid.addWidget(self.sampling, 0, 1)
        grid.addWidget(QLabel("样本数"), 0, 2)
        grid.addWidget(self.samples, 0, 3)
        grid.addWidget(QLabel("目标变量"), 1, 0)
        grid.addWidget(self.target, 1, 1)
        grid.addWidget(QLabel("验证集比例"), 1, 2)
        grid.addWidget(self.split, 1, 3)
        grid.addWidget(QLabel("随机种子"), 2, 0)
        grid.addWidget(self.seed, 2, 1)
        grid.addWidget(QLabel("计算精度"), 2, 2)
        grid.addWidget(self.precision, 2, 3)
        generate_layout.addLayout(grid)
        self.generate_button = _primary_button("生成数据集")
        self.generate_button.clicked.connect(self.generateRequested.emit)
        generate_layout.addWidget(self.generate_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(generate)

        sequence, sequence_layout = _field_group("列对应（自定义文件）")
        self.sequence_host = sequence
        self.system_id_column = QLineEdit("system_id")
        self.order_column = QLineEdit("element_index")
        self.element_type_column = QLineEdit("element_type")
        self.numeric_columns = QLineEdit("radius_mm,thickness_mm")
        self.sequence_target = QLineEdit("coupling_efficiency")
        sequence_layout.addLayout(
            _field_grid(
                [
                    _labeled_field("系统编号列", self.system_id_column),
                    _labeled_field("元件顺序列", self.order_column),
                    _labeled_field("元件类型列", self.element_type_column),
                    _labeled_field("半径/厚度列", self.numeric_columns),
                    _labeled_field("目标列", self.sequence_target),
                ],
                columns=2,
            )
        )
        layout.addWidget(sequence)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["编号", "选择的参数", "波长属性", "状态"])
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setMinimumHeight(120)
        _stretch_table(self.table)
        layout.addWidget(self.table, 1)

        train_box, train_layout = _field_group("3. 训练")
        self.model_type = QComboBox()
        self.rf_trees = _spin(1, 10000, 0, "", 300)
        self.rf_depth = _spin(0, 256, 0, "", 0)
        self.rf_min_leaf = _spin(1, 100, 0, "", 1)
        self.rf_max_features = QComboBox()
        self.rf_max_features.addItems(["sqrt", "log2", "1.0"])
        self.xgb_rounds = _spin(10, 10000, 0, "", 300)
        self.xgb_lr = _spin(0.000001, 1.0, 6, "", 0.05)
        self.xgb_depth = _spin(1, 32, 0, "", 4)
        self.xgb_subsample = _spin(0.01, 1.0, 2, "", 0.9)
        self.xgb_colsample = _spin(0.01, 1.0, 2, "", 0.95)
        self.lstm_epochs = _spin(1, 5000, 0, "", 200)
        self.lstm_batch = _spin(1, 1024, 0, "", 32)
        self.rf_training_group, rf_layout = _field_group("随机森林 · 直接效率基准")
        rf_layout.addLayout(_field_grid([
            _labeled_field("树数量", self.rf_trees),
            _labeled_field("最大深度（0=自动）", self.rf_depth),
            _labeled_field("叶节点最小样本", self.rf_min_leaf),
            _labeled_field("最大特征", self.rf_max_features),
        ], columns=2))
        self.xgb_training_group, xgb_layout = _field_group("XGBoost · 物理公式残差主模型")
        xgb_layout.addLayout(_field_grid([
            _labeled_field("迭代轮数", self.xgb_rounds),
            _labeled_field("学习率", self.xgb_lr),
            _labeled_field("最大深度", self.xgb_depth),
            _labeled_field("样本采样率", self.xgb_subsample),
            _labeled_field("特征采样率", self.xgb_colsample),
        ], columns=2))
        self.sequence_training_group, sequence_train_layout = _field_group("BiLSTM · 序列模型")
        self.bilstm_placeholder = QLabel("暂未纳入当前闭环；仅在选择序列数据时启用。")
        self.bilstm_placeholder.setObjectName("HelperText")
        sequence_train_layout.addWidget(self.bilstm_placeholder)
        sequence_train_layout.addLayout(_field_grid([
            _labeled_field("最大轮数", self.lstm_epochs),
            _labeled_field("批大小", self.lstm_batch),
        ], columns=2))
        train_layout.addWidget(self.rf_training_group)
        train_layout.addWidget(self.xgb_training_group)
        train_layout.addWidget(self.sequence_training_group)
        self.train_button = _primary_button("开始联合训练")
        self.train_button.clicked.connect(self.trainRequested.emit)
        train_layout.addWidget(_action_row(self.model_type, self.train_button))
        layout.addWidget(train_box)
        self.data_kind.currentIndexChanged.connect(lambda _index: self._apply_family())
        self.file_path.textChanged.connect(lambda _text: self._refresh_sequence_mapping())
        self.model_type.currentTextChanged.connect(lambda _text: self._sync_train_hypers())
        self._apply_family(emit=False)
        self._sync_scheme_summary()

    def _sync_scheme_summary(self) -> None:
        count = int(self.lens_count.currentData() or 1)
        conic = self.variable_scheme.currentData() == "asphere"
        total = count * (5 if conic else 3)
        try:
            from machine_learning.datasets.variable_schemes import resolve_variable_scheme

            project = serialize_project(self.context.project.project)
            total = len(resolve_variable_scheme(
                project, lens_count=count, include_conic=conic
            ).design_variable_paths)
        except (AttributeError, TypeError, ValueError, IndexError):
            pass
        prefix = ("单", "双", "三", "四")[count - 1]
        self.scheme_summary.setText(
            f"{prefix}透镜·{'非球面' if conic else '基础'}方案 · {total} 个当前可变设计变量；内部物理量自动计算"
        )

    def _refresh_sequence_mapping(self) -> None:
        family = self.current_family()
        has_file = bool(self.file_path.text().strip())
        host = getattr(self, "sequence_host", None)
        if host is not None:
            host.setVisible(family == "sequence" and has_file)

    def _fill_builtins(self, family: str) -> None:
        # The packaged item below is an actual registered dataset ID.  Do not
        # offer decorative names that cannot be submitted to the training API.
        records = (
            (("内置演示·780 nm 四透镜耦合", "dataset-880bdde6c292"),)
            if family == "tabular" else ()
        )
        current = self.builtin.currentText()
        self.builtin.blockSignals(True)
        self.builtin.clear()
        for label, dataset_id in records:
            self.builtin.addItem(label, dataset_id)
        if not records:
            self.builtin.addItem("序列模型请使用自定义文件", "")
        index = self.builtin.findText(current)
        if index >= 0:
            self.builtin.setCurrentIndex(index)
        self.builtin.blockSignals(False)

    def _apply_family(self, *, emit: bool = True) -> None:
        family = self.current_family()
        has_file = bool(self.file_path.text().strip())
        self.generate_host.setVisible(family == "tabular")
        self.sequence_host.setVisible(family == "sequence" and has_file)
        self._fill_builtins(family)
        self.model_type.clear()
        self.model_type.addItems(list(TABULAR_MODEL_CHOICES if family == "tabular" else SEQUENCE_MODEL_CHOICES))
        self._sync_train_hypers()
        if family == "tabular":
            self.table.setHorizontalHeaderLabels(["编号", "选择的参数", "波长属性", "状态"])
            self.file_path.setPlaceholderText("选择 CSV / JSONL 表格样本")
        else:
            self.table.setHorizontalHeaderLabels(["系统", "元件顺序", "类型", "状态"])
            if not has_file:
                self.table.setRowCount(0)
            self.file_path.setPlaceholderText("选择自定义长表后映射列；内置结构表无需映射")
        _stretch_table(self.table)
        if emit:
            self.dataKindChanged.emit(family)

    def _set_family(self, family: str) -> None:
        index = self.data_kind.findData(family)
        if index < 0:
            return
        if self.data_kind.currentIndex() != index:
            blocked = self.data_kind.blockSignals(True)
            self.data_kind.setCurrentIndex(index)
            self.data_kind.blockSignals(blocked)
            self._apply_family()
        elif str(self.data_kind.currentData() or "") != family:
            self._apply_family()

    def _sync_train_hypers(self) -> None:
        tabular = self.current_family() == "tabular"
        self.model_type.setVisible(not tabular)
        self.rf_training_group.setVisible(tabular)
        self.xgb_training_group.setVisible(tabular)
        self.sequence_training_group.setVisible(not tabular)
        self.train_button.setText("开始联合训练" if tabular else "训练 BiLSTM")

    def train_hyperparameters(self) -> dict[str, Any]:
        name = str(self.model_type.currentText() or "")
        if name == "随机森林":
            return {"n_estimators": int(self.rf_trees.value()), "max_depth": int(self.rf_depth.value())}
        if name == "XGBoost物理残差":
            return {"n_estimators": int(self.xgb_rounds.value()), "learning_rate": float(self.xgb_lr.value())}
        if name == "BiLSTM":
            return {"max_epochs": int(self.lstm_epochs.value()), "batch_size": int(self.lstm_batch.value())}
        return {}

    def random_forest_hyperparameters(self) -> dict[str, Any]:
        value = str(self.rf_max_features.currentText() or "sqrt")
        max_features: Any = float(value) if value == "1.0" else value
        return {
            "n_estimators": int(self.rf_trees.value()),
            "max_depth": int(self.rf_depth.value()),
            "min_samples_leaf": int(self.rf_min_leaf.value()),
            "max_features": max_features,
        }

    def xgboost_hyperparameters(self) -> dict[str, Any]:
        return {
            "n_estimators": int(self.xgb_rounds.value()),
            "learning_rate": float(self.xgb_lr.value()),
            "max_depth": int(self.xgb_depth.value()),
            "subsample": float(self.xgb_subsample.value()),
            "colsample_bytree": float(self.xgb_colsample.value()),
        }

    def set_job_busy(self, busy: bool) -> None:
        generate = getattr(self, "generate_button", None)
        train = getattr(self, "train_button", None)
        if generate is not None:
            generate.setEnabled(not busy)
        if train is not None:
            train.setEnabled(not busy)

    def _build_train_result(self, root: QVBoxLayout) -> None:
        self.chart = QComboBox()
        self.chart.addItems(["残差图", "实测对照", "学习曲线"])
        self.chart.currentTextChanged.connect(self._show_train_chart)
        root.addWidget(_action_row(self.chart))
        self.train_summary = QLabel("尚未训练")
        self.train_summary.setObjectName("DocumentMetric")
        self.train_summary.setWordWrap(True)
        root.addWidget(self.train_summary)
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        root.addWidget(self.workspace, 1)
        self._show_train_chart(self.chart.currentText())

    def _build_predict(self, root: QVBoxLayout) -> None:
        setup, setup_layout = _field_group("1. 设置")
        self.predict_model = QComboBox()
        self.predict_target = QLabel("尚未训练")
        self.predict_target.setObjectName("HelperText")
        run = _primary_button("预测")
        self.predict_run = run
        setup_layout.addWidget(
            _action_row(QLabel("已训练模型"), self.predict_model, QLabel("目标"), self.predict_target, run)
        )
        root.addWidget(setup)

        inputs, input_layout = _field_group("2. 当前镜头")
        inputs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.input_table = QTableWidget(0, 2)
        self.input_table.setHorizontalHeaderLabels(["参数", "当前值"])
        _stretch_table(self.input_table)
        input_layout.addWidget(self.input_table, 1)
        root.addWidget(inputs, 1)

        result, result_layout = _field_group("3. 结果")
        self.result_table = QTableWidget(0, 2)
        self.result_table.setHorizontalHeaderLabels(["量", "值"])
        _stretch_table(self.result_table)
        result_layout.addWidget(self.result_table)
        self.metrics = QLabel("选择已训练模型后，用上面这组当前镜头参数做预测。")
        self.metrics.setObjectName("DocumentMetric")
        self.metrics.setWordWrap(True)
        result_layout.addWidget(self.metrics)
        root.addWidget(result)
        run.clicked.connect(self.predictRequested.emit)
        self.predict_model.currentIndexChanged.connect(self._sync_predict_target)
        self._fill_predict_inputs()
        self._set_predict_models([])

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        if self.kind != "predict_eval" and self.kind != "predict":
            return
        self._set_predict_models(models)

    def _set_predict_models(self, models: list[dict[str, Any]]) -> None:
        combo = getattr(self, "predict_model", None)
        if combo is None:
            return
        previous = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        for item in models:
            record = dict(item)
            title = str(record.get("title") or record.get("id") or "模型")
            _usable, reason = model_prediction_status(record)
            combo.addItem(title, record)
            index = combo.count() - 1
            if reason:
                combo.setItemData(index, reason, Qt.ItemDataRole.ToolTipRole)
        combo.blockSignals(False)
        if previous and combo.findText(previous) >= 0:
            combo.setCurrentText(previous)
        elif combo.count():
            combo.setCurrentIndex(0)
        self._sync_predict_target()

    def _sync_predict_target(self) -> None:
        label = getattr(self, "predict_target", None)
        combo = getattr(self, "predict_model", None)
        if label is None or combo is None:
            return
        record = combo.currentData()
        if isinstance(record, dict) and record.get("target"):
            target = str(record.get("target"))
            usable, reason = model_prediction_status(record)
            label.setText(target if usable else f"{target}（模型质量未达标）")
            label.setToolTip(reason)
        elif combo.count() == 0:
            label.setText("尚未训练")
            label.setToolTip("")
        else:
            label.setText("耦合损耗(dB)")
            label.setToolTip("")
        button = getattr(self, "predict_run", None)
        if button is not None:
            usable, reason = model_prediction_status(record if isinstance(record, dict) else None)
            button.setEnabled(combo.count() > 0 and usable)
            button.setToolTip(reason)
        self._fill_predict_inputs()

    def _fill_predict_inputs(self) -> None:
        table = getattr(self, "input_table", None)
        if table is None:
            return
        record = self.predict_model.currentData() if getattr(self, "predict_model", None) is not None else None
        if isinstance(record, dict) and record.get("feature_paths"):
            try:
                values = model_features(self.context.project.project, record)
                raw_units = record.get("feature_units") or []
                units = (
                    {str(key): str(value) for key, value in raw_units.items()}
                    if isinstance(raw_units, dict)
                    else {
                        str(path): str(raw_units[index])
                        for index, path in enumerate(record.get("feature_paths") or [])
                        if index < len(raw_units)
                    }
                )
                display_paths = [str(path) for path in (record.get("design_variable_paths") or [])]
                if not display_paths:
                    display_paths = [
                        str(path)
                        for path in record.get("feature_paths") or []
                        if str(path).endswith((".radius_mm", ".distance_to_next_mm", ".conic"))
                    ]
                if not display_paths:
                    display_paths = [str(path) for path in record.get("feature_paths") or []]
                rows = [
                    (
                        display_feature_name(path),
                        f"{float(values[path]):.6g} {units.get(str(path), '')}".rstrip(),
                    )
                    for path in display_paths
                    if str(path) in values
                ]
            except FeaturePathError as exc:
                rows = [("模型输入", f"当前镜头无法构造：{exc}")]
        else:
            rows = _current_lens_feature_rows(self.context)
        table.setRowCount(len(rows))
        for index, (name, value) in enumerate(rows):
            table.setItem(index, 0, QTableWidgetItem(name))
            table.setItem(index, 1, QTableWidgetItem(value))
        _stretch_table(table)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择数据集文件", "", "数据文件 (*.csv *.jsonl *.json)")
        if path:
            self.file_path.setText(path)
            self.fileImportRequested.emit(path)

    def _generate(self) -> None:
        self.generateRequested.emit()

    def show_generate_status(self, message: str, rows: list[tuple[str, str, str, str]] | None = None) -> None:
        table = getattr(self, "table", None)
        if table is None:
            return
        records = list(rows or [("—", "—", "—", message)])
        table.setRowCount(len(records))
        for index, (ident, selected, wavelength, status) in enumerate(records):
            table.setItem(index, 0, QTableWidgetItem(ident))
            table.setItem(index, 1, QTableWidgetItem(selected))
            table.setItem(index, 2, QTableWidgetItem(wavelength))
            table.setItem(index, 3, QTableWidgetItem(status))
        _stretch_table(table)

    def select_dataset(self, title: str) -> None:
        text = str(title or "")
        if text in SEQUENCE_DATASET_CHOICES:
            self._set_family("sequence")
        elif text in TABULAR_DATASET_CHOICES:
            self._set_family("tabular")
        index = self.builtin.findText(text)
        if index >= 0:
            self.builtin.setCurrentIndex(index)

    def select_predict_model(self, title: str) -> None:
        combo = getattr(self, "predict_model", None)
        if combo is None:
            return
        text = str(title)
        if combo.findText(text) >= 0:
            combo.setCurrentText(text)
        self._sync_predict_target()

    def show_train_chart(self, name: str) -> None:
        combo = getattr(self, "chart", None)
        if combo is not None:
            combo.setCurrentText(str(name))

    def mark_trained(self, result: dict[str, Any] | None = None) -> None:
        self._trained = True
        self._train_result = dict(result or {})
        summary = dict(self._train_result.get("training_summary") or {})
        test = dict(self._train_result.get("test_metrics") or {})
        parts = ["训练完成"]
        sample_count = summary.get("sample_count") or summary.get("training_samples")
        if sample_count is not None:
            parts.append(f"训练样本 {sample_count}")
        if test.get("r2") is not None:
            parts.append(f"测试 R²={float(test['r2']):.3f}")
        if test.get("rmse") is not None:
            parts.append(f"RMSE={float(test['rmse']):.4g}")
        if getattr(self, "train_summary", None) is not None:
            self.train_summary.setText(" · ".join(parts) + "。图中只展示返回的真实测试集记录。")
        if self.kind == "train_result":
            self._show_train_chart(self.chart.currentText())

    def mark_joint_trained(self, result: dict[str, Any]) -> None:
        body = dict(result or {})
        rf = dict(body.get("random_forest") or {})
        xgb = dict(body.get("xgboost") or {})
        partial = str(body.get("status") or "completed") == "partial" or not xgb
        self._trained = bool(xgb or rf)
        self._train_result = xgb or rf

        def score(item: dict[str, Any]) -> str:
            value = dict(item.get("test_metrics") or {}).get("r2")
            return f"R²={float(value):.3f}" if isinstance(value, (int, float)) else "已完成"

        if partial:
            warning = "；".join(str(item) for item in list(body.get("warnings") or []))
            self.train_summary.setText(
                f"联合训练部分完成 · 随机森林 {score(rf)} · XGBoost 未完成。"
                + (f"原因：{warning}" if warning else "")
                + " 随机森林结果可用于设计变量解释；请修复数据后再训练 XGBoost。"
            )
        else:
            self.train_summary.setText(
                f"联合训练完成 · 随机森林 {score(rf)} · XGBoost {score(xgb)} · "
                "XGBoost为主预测，随机森林用于设计变量解释和对照。"
            )
        self._show_train_chart(self.chart.currentText())

    def show_train_status(self, message: str) -> None:
        self._trained = False
        self._train_result = {}
        if getattr(self, "train_summary", None) is not None:
            self.train_summary.setText(str(message))
        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            workspace.set_result(0, "训练结果", {"kind": "empty", "message": message})

    def _show_train_chart(self, name: str) -> None:
        if not self._trained:
            self.workspace.set_result(0, name, {"kind": "empty", "message": "先在数据集页训练，再查看残差图等训练结果。"})
            return
        payload = train_chart_payload(getattr(self, "_train_result", {}) or {}, name)
        if payload is None:
            self.workspace.set_result(
                0,
                name,
                {"kind": "empty", "message": train_chart_unavailable_message(self._train_result, name)},
            )
            return
        self.workspace.set_result(0, name, payload)

    def show_predict_status(self, message: str) -> None:
        self.metrics.setVisible(True)
        self.metrics.setText(message)
        self.result_table.setRowCount(0)

    def show_predict_result(self, rows: list[tuple[str, str]]) -> None:
        self.metrics.hide()
        self.result_table.setRowCount(len(rows))
        for index, (name, value) in enumerate(rows):
            self.result_table.setItem(index, 0, QTableWidgetItem(name))
            self.result_table.setItem(index, 1, QTableWidgetItem(value))
        _stretch_table(self.result_table)

    def _run_predict(self) -> None:
        self.predictRequested.emit()


__all__ = ["ModelDocument"]
