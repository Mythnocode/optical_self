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
    datasetSelectionChanged = Signal(str)
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

    def current_source_mode(self) -> str:
        combo = getattr(self, "source_mode", None)
        if combo is None:
            return "import"
        return str(combo.currentData() or "import")

    def current_dataset_source(self) -> str:
        return str(getattr(self, "_active_dataset_source", "") or "")

    def selected_dataset_id(self) -> str:
        if self.current_dataset_source() == "generated_pending":
            return ""
        return str(getattr(self, "_active_dataset_id", "") or "")

    def register_generated_sequence_dataset(self, dataset_id: str, config: dict[str, Any]) -> None:
        """Remember the local long-table contract for a generated dataset."""
        ident = str(dataset_id or "").strip()
        if ident:
            self._generated_sequence_datasets[ident] = dict(config or {})

    def generated_sequence_config(self) -> dict[str, Any]:
        return dict(self._generated_sequence_datasets.get(self.selected_dataset_id(), {}))

    def _build_dataset(self, root: QVBoxLayout) -> None:
        layout = root
        self._active_dataset_source = ""
        self._active_dataset_id = ""
        self._import_busy = False
        self._generation_busy = False
        self._generated_sequence_datasets: dict[str, dict[str, Any]] = {}

        source, source_layout = _field_group("1. 数据")
        self.data_group = source
        source.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        source_mode_row = QHBoxLayout()
        source_mode_row.setContentsMargins(0, 0, 0, 0)
        source_mode_row.setSpacing(8)
        self.source_mode = QComboBox()
        self.source_mode.addItem("导入", "import")
        self.source_mode.addItem("生成", "generate")
        source_mode_row.addWidget(QLabel("数据来源"))
        source_mode_row.addWidget(self.source_mode, 1)
        source_layout.addLayout(source_mode_row)

        self.import_host = QWidget()
        import_layout = QVBoxLayout(self.import_host)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.setSpacing(6)
        kind_row = QHBoxLayout()
        kind_row.setContentsMargins(0, 0, 0, 0)
        kind_row.setSpacing(8)
        self.data_kind = QComboBox()
        self.data_kind.addItem("按照镜头", "tabular")
        self.data_kind.addItem("按照元件", "sequence")
        kind_row.addWidget(QLabel("采样方式"))
        kind_row.addWidget(self.data_kind, 1)
        import_layout.addLayout(kind_row)

        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.setSpacing(8)
        self.builtin = QComboBox()
        self.builtin.setObjectName("builtinDatasetSelector")
        self.builtin.setVisible(False)
        self.file_path = QLineEdit()
        self.file_path.setReadOnly(True)
        self.file_path.setPlaceholderText("选择 CSV / JSONL 样本文件")
        self.browse_button = QPushButton("选择文件")
        self.browse_button.clicked.connect(self._choose_file)
        self.import_button = QPushButton("导入")
        self.import_button.setProperty("kind", "secondary")
        self.import_button.clicked.connect(self._import_selected_file)
        self.builtin_button = QPushButton("内置")
        self.builtin_button.setProperty("kind", "secondary")
        self.builtin_button.setCheckable(True)
        self.builtin_button.clicked.connect(self._select_builtin)
        pick_row.addWidget(self.file_path, 1)
        pick_row.addWidget(self.browse_button)
        pick_row.addWidget(self.import_button)
        pick_row.addWidget(self.builtin_button)
        import_layout.addLayout(pick_row)
        source_layout.addWidget(self.import_host)

        generate = QWidget()
        generate_layout = QVBoxLayout(generate)
        generate_layout.setContentsMargins(0, 0, 0, 0)
        generate_layout.setSpacing(6)
        self.generate_host = generate
        sample_target_grid = QGridLayout()
        sample_target_grid.setContentsMargins(0, 0, 0, 0)
        sample_target_grid.setHorizontalSpacing(12)
        sample_target_grid.setColumnStretch(1, 1)
        sample_target_grid.setColumnStretch(3, 1)
        self.samples = _spin(8, 100000, 0, "", 50)
        self.target = QComboBox()
        self.target.addItems(list(DATASET_TARGET_CHOICES))
        sample_target_grid.addWidget(QLabel("样本数"), 0, 0)
        sample_target_grid.addWidget(self.samples, 0, 1)
        sample_target_grid.addWidget(QLabel("目标变量"), 0, 2)
        sample_target_grid.addWidget(self.target, 0, 3)
        generate_layout.addLayout(sample_target_grid)

        generation_mode_row = QHBoxLayout()
        generation_mode_row.setContentsMargins(0, 0, 0, 0)
        generation_mode_row.setSpacing(8)
        generation_mode_row.addWidget(QLabel("镜头结构"))
        self.generation_mode_button = QPushButton("固定镜头数")
        self.generation_mode_button.setObjectName("generationModeButton")
        self.generation_mode_button.setProperty("kind", "secondary")
        self.generation_mode_button.setProperty("generationMode", "fixed")
        self.generation_mode_button.setCheckable(True)
        self.generation_mode_button.setMinimumWidth(132)
        self.generation_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generation_mode_button.toggled.connect(self._set_generation_mode)
        generation_mode_row.addWidget(self.generation_mode_button)
        generation_mode_row.addStretch(1)
        generate_layout.addLayout(generation_mode_row)

        self.generate_more_button = QToolButton()
        self.generate_more_button.setObjectName("datasetMoreButton")
        self.generate_more_button.setText("更多参数")
        self.generate_more_button.setCheckable(True)
        self.generate_more_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.generate_more_button.setArrowType(Qt.ArrowType.RightArrow)
        self.generate_more_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.generate_more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generate_more_button.toggled.connect(self._toggle_generation_options)
        more_row = QHBoxLayout()
        more_row.setContentsMargins(0, 0, 0, 0)
        more_row.addStretch(1)
        more_row.addWidget(self.generate_more_button)
        generate_layout.addLayout(more_row)

        self.generate_more_host = QWidget()
        more_layout = QVBoxLayout(self.generate_more_host)
        more_layout.setContentsMargins(0, 0, 0, 0)
        more_layout.setSpacing(6)
        self.fixed_generation_host = QWidget()
        fixed_generation_layout = QVBoxLayout(self.fixed_generation_host)
        fixed_generation_layout.setContentsMargins(0, 0, 0, 0)
        fixed_generation_layout.setSpacing(6)
        param_grid = QGridLayout()
        param_grid.setContentsMargins(0, 0, 0, 0)
        param_grid.setHorizontalSpacing(12)
        # Keep label columns compact and let only the editor columns absorb
        # the available width. Without explicit stretch factors Qt distributes
        # the four columns by size hints, which makes the fields drift apart
        # on wide windows.
        for column in (0, 2):
            param_grid.setColumnMinimumWidth(column, 92)
        for column in (1, 3):
            param_grid.setColumnStretch(column, 1)
        self.generate_checks: dict[str, QCheckBox] = {}
        self.lens_count = QComboBox()
        for label, value in (("单透镜", 1), ("双透镜", 2), ("三透镜", 3), ("四透镜", 4)):
            self.lens_count.addItem(label, value)
        self.lens_count.setCurrentIndex(3)
        self.variable_scheme = QComboBox()
        self.variable_scheme.addItem("曲率半径 + 厚度", "basic")
        self.variable_scheme.addItem("曲率半径 + 厚度 + 圆锥系数", "asphere")
        # self.scheme_summary = QLabel("四透镜·基础方案 · 12 个设计变量；内部物理量自动计算")
        # self.scheme_summary.setObjectName("HelperText")
        param_grid.addWidget(QLabel("研究对象"), 0, 0)
        param_grid.addWidget(self.lens_count, 0, 1)
        param_grid.addWidget(QLabel("变量方案"), 0, 2)
        param_grid.addWidget(self.variable_scheme, 0, 3)
        # param_grid.addWidget(self.scheme_summary, 1, 0, 1, 4)
        self.lens_count.currentIndexChanged.connect(self._sync_scheme_summary)
        self.variable_scheme.currentIndexChanged.connect(self._sync_scheme_summary)
        fixed_generation_layout.addLayout(param_grid)
        more_layout.addWidget(self.fixed_generation_host)

        self.sequence_generation_host = QWidget()
        sequence_generation_layout = QVBoxLayout(self.sequence_generation_host)
        sequence_generation_layout.setContentsMargins(0, 0, 0, 0)
        sequence_generation_layout.setSpacing(6)
        sequence_range_grid = QGridLayout()
        sequence_range_grid.setContentsMargins(0, 0, 0, 0)
        sequence_range_grid.setHorizontalSpacing(12)
        sequence_range_grid.setColumnStretch(1, 1)
        sequence_range_grid.setColumnStretch(3, 1)
        self.sequence_lens_count = QLabel("正在识别当前系统…")
        self.sequence_lens_count.setObjectName("HelperText")
        sequence_range_grid.addWidget(QLabel("当前系统镜头数"), 0, 0)
        sequence_range_grid.addWidget(self.sequence_lens_count, 0, 1, 1, 3)
        sequence_generation_layout.addLayout(sequence_range_grid)
        variable_actions = QHBoxLayout()
        variable_actions.setContentsMargins(0, 0, 0, 0)
        variable_actions.setSpacing(8)
        self.sequence_variable_summary = QLabel("未选择变量")
        self.sequence_variable_summary.setObjectName("HelperText")
        self.sequence_variable_button = QToolButton()
        self.sequence_variable_button.setObjectName("sequenceVariableButton")
        self.sequence_variable_button.setText("选择变量")
        self.sequence_variable_button.setCheckable(True)
        self.sequence_variable_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sequence_variable_button.setArrowType(Qt.ArrowType.RightArrow)
        self.sequence_variable_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.sequence_variable_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sequence_variable_button.toggled.connect(self._toggle_sequence_variables)
        variable_actions.addWidget(QLabel("变量方案"))
        variable_actions.addWidget(self.sequence_variable_summary, 1)
        variable_actions.addWidget(self.sequence_variable_button)
        sequence_generation_layout.addLayout(variable_actions)
        self.sequence_variable_host = QWidget()
        sequence_variables_grid = QGridLayout(self.sequence_variable_host)
        sequence_variables_grid.setContentsMargins(0, 0, 0, 0)
        sequence_variables_grid.setHorizontalSpacing(12)
        sequence_variables_grid.setVerticalSpacing(4)
        self.sequence_variable_checks: dict[str, QCheckBox] = {}
        for index, row in enumerate(_variable_rows(self.context.project.project)):
            path, group, face, parameter = row
            check = QCheckBox(f"{group} / {face} / {parameter}")
            check.setToolTip(path)
            check.toggled.connect(self._sync_sequence_variable_summary)
            sequence_variables_grid.addWidget(check, index // 2, index % 2)
            self.sequence_variable_checks[path] = check
        if self.sequence_variable_checks:
            # A useful default makes generated sequence data immediately
            # trainable while leaving every variable available for adjustment.
            for path, check in self.sequence_variable_checks.items():
                if path.endswith((".radius_mm", ".distance_to_next_mm")):
                    check.setChecked(True)
        self.sequence_variable_host.setVisible(False)
        sequence_generation_layout.addWidget(self.sequence_variable_host)

        self.sequence_generation_host.setVisible(False)
        more_layout.addWidget(self.sequence_generation_host)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.sampling = QComboBox()
        self.sampling.addItems(list(DATASET_SAMPLING_CHOICES))
        self.split = _spin(0.05, 0.4, 2, "", 0.15)
        self.seed = _spin(0, 1e9, 0, "", 42)
        self.precision = QComboBox()
        self.precision.addItems(list(DATASET_PRECISION_CHOICES))
        self.precision.setCurrentText("257×257")
        grid.addWidget(QLabel("采样方法"), 0, 0)
        grid.addWidget(self.sampling, 0, 1)
        grid.addWidget(QLabel("验证集比例"), 0, 2)
        grid.addWidget(self.split, 0, 3)
        grid.addWidget(QLabel("随机种子"), 1, 0)
        grid.addWidget(self.seed, 1, 1)
        grid.addWidget(QLabel("计算精度"), 1, 2)
        grid.addWidget(self.precision, 1, 3)
        more_layout.addLayout(grid)
        self.generate_more_host.setVisible(False)
        generate_layout.addWidget(self.generate_more_host)
        self.generate_button = _primary_button("生成数据集")
        self.generate_button.clicked.connect(self.generateRequested.emit)
        generate_layout.addWidget(self.generate_button, 0, Qt.AlignmentFlag.AlignLeft)
        source_layout.addWidget(generate)

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
        import_layout.addWidget(sequence)
        layout.addWidget(source)

        train_box, train_layout = _field_group("2. 训练")
        self.training_group = train_box
        train_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.model_type = QComboBox(train_box)
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
        sequence_train_layout.addLayout(_field_grid([
            _labeled_field("最大轮数", self.lstm_epochs),
            _labeled_field("批大小", self.lstm_batch),
        ], columns=2))
        self.training_parameters_host = QWidget()
        training_parameters_layout = QVBoxLayout(self.training_parameters_host)
        training_parameters_layout.setContentsMargins(0, 0, 0, 0)
        training_parameters_layout.setSpacing(4)
        training_parameters_layout.addWidget(self.rf_training_group)
        training_parameters_layout.addWidget(self.xgb_training_group)
        training_parameters_layout.addWidget(self.sequence_training_group)
        self.training_parameters_host.setVisible(False)
        train_layout.addWidget(self.training_parameters_host)

        self.training_more_button = QToolButton()
        self.training_more_button.setObjectName("trainingMoreButton")
        self.training_more_button.setText("更多参数")
        self.training_more_button.setCheckable(True)
        self.training_more_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.training_more_button.setArrowType(Qt.ArrowType.RightArrow)
        self.training_more_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.training_more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.training_more_button.toggled.connect(self._toggle_training_options)

        self.training_mode_button = QPushButton("固定镜头数")
        self.training_mode_button.setObjectName("trainingModeButton")
        self.training_mode_button.setProperty("kind", "secondary")
        self.training_mode_button.setProperty("trainingMode", "fixed")
        self.training_mode_button.setCheckable(True)
        self.training_mode_button.setMinimumWidth(132)
        self.training_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.training_mode_button.toggled.connect(self._set_training_mode)
        self.train_button = _primary_button("开始训练")
        self.train_button.clicked.connect(self.trainRequested.emit)
        train_actions = QHBoxLayout()
        train_actions.setContentsMargins(0, 0, 0, 0)
        train_actions.setSpacing(8)
        train_actions.addStretch(1)
        train_actions.addWidget(self.training_mode_button)
        train_actions.addWidget(self.training_more_button)
        train_actions.addWidget(self.train_button)
        train_layout.addLayout(train_actions)
        layout.addWidget(train_box)
        layout.addStretch(1)
        self.source_mode.currentIndexChanged.connect(lambda _index: self._apply_source_mode())
        self.data_kind.currentIndexChanged.connect(lambda _index: self._apply_family())
        self.file_path.textChanged.connect(lambda _text: self._sync_import_actions())
        self.model_type.currentTextChanged.connect(lambda _text: self._sync_train_hypers())
        self._apply_family(emit=False)
        self._apply_source_mode(emit=False)
        self._sync_scheme_summary()
        self._sync_generation_mode()

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
        # self.scheme_summary.setText(
        #     f"{prefix}透镜·{'非球面' if conic else '基础'}方案 · {total} 个当前可变设计变量；内部物理量自动计算"
        # )

    def _toggle_generation_options(self, expanded: bool) -> None:
        self.generate_more_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.generate_more_host.setVisible(bool(expanded))

    def _toggle_sequence_variables(self, expanded: bool) -> None:
        self.sequence_variable_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.sequence_variable_host.setVisible(bool(expanded))

    def _sync_sequence_variable_summary(self, _checked: bool = False) -> None:
        count = sum(check.isChecked() for check in self.sequence_variable_checks.values())
        self.sequence_variable_summary.setText(
            f"已选择 {count} 个变量" if count else "未选择变量"
        )

    def _sync_sequence_lens_count(self) -> None:
        try:
            from machine_learning.datasets.variable_schemes import resolve_lens_bindings

            project = serialize_project(self.context.project.project)
            count = len(resolve_lens_bindings(project))
            text = f"已识别 {count} 个实体镜片（每个系统样本保留此序列长度）"
        except (AttributeError, TypeError, ValueError, IndexError):
            text = "无法识别当前系统的实体镜片"
        self.sequence_lens_count.setText(text)

    def sequence_variable_paths(self) -> list[str]:
        """Return the user-selected variable paths for a future sequence dataset."""
        return [
            path for path, check in self.sequence_variable_checks.items()
            if check.isChecked()
        ]

    def _set_generation_mode(self, arbitrary_lens_count: bool) -> None:
        family = "sequence" if arbitrary_lens_count else "tabular"
        if self.current_family() != family:
            self._set_family(family)
        else:
            self._sync_generation_mode()

    def _sync_generation_mode(self) -> None:
        """Keep generation controls aligned with the selected training family."""
        arbitrary_lens_count = self.current_family() == "sequence"
        self.fixed_generation_host.setVisible(not arbitrary_lens_count)
        self.sequence_generation_host.setVisible(arbitrary_lens_count)
        blocked = self.generation_mode_button.blockSignals(True)
        self.generation_mode_button.setChecked(arbitrary_lens_count)
        self.generation_mode_button.setText(
            "任意镜头数" if arbitrary_lens_count else "固定镜头数"
        )
        self.generation_mode_button.setToolTip(
            "BiLSTM：元件数量可以变化，变量由本页选择"
            if arbitrary_lens_count else "随机森林 + XGBoost：使用固定镜头数量"
        )
        self.generation_mode_button.blockSignals(blocked)
        self._set_generation_mode_appearance(
            "arbitrary" if arbitrary_lens_count else "fixed"
        )
        self._sync_sequence_lens_count()
        self.samples.setMinimum(10 if arbitrary_lens_count else 8)
        self._sync_generate_action()

    def _set_generation_mode_appearance(self, mode: str) -> None:
        button = self.generation_mode_button
        if str(button.property("generationMode") or "") == mode:
            return
        button.setProperty("generationMode", mode)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def _sync_generate_action(self) -> None:
        self.generate_button.setText("生成数据集")
        self.generate_button.setEnabled(not self._generation_busy)
        self.generate_button.setToolTip(
            "按当前光学系统的实际镜片序列生成 BiLSTM 长表数据"
            if self.current_family() == "sequence" else ""
        )

    def _toggle_training_options(self, expanded: bool) -> None:
        self.training_more_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.training_parameters_host.setVisible(bool(expanded))
        tabular = self.current_family() == "tabular"
        self.rf_training_group.setVisible(bool(expanded) and tabular)
        self.xgb_training_group.setVisible(bool(expanded) and tabular)
        self.sequence_training_group.setVisible(bool(expanded) and not tabular)

    def _apply_source_mode(self, *, emit: bool = True) -> None:
        mode = self.current_source_mode()
        if mode == "generate" and self.current_dataset_source() in {"builtin", "file", "file_pending"}:
            self._active_dataset_source = ""
            self._active_dataset_id = ""
            self.datasetSelectionChanged.emit("")
        elif mode == "import" and self.current_dataset_source() == "generated":
            self._active_dataset_source = ""
            self._active_dataset_id = ""
            self.datasetSelectionChanged.emit("")
        if mode == "import":
            self._apply_family(emit=emit)
        self.import_host.setVisible(mode == "import")
        self.generate_host.setVisible(mode == "generate")
        self._refresh_sequence_mapping()
        self._sync_import_actions()
        self._sync_generation_mode()

    def _sync_import_actions(self) -> None:
        path_selected = bool(self.file_path.text().strip())
        builtin_available = any(
            bool(self.builtin.itemData(index))
            for index in range(self.builtin.count())
        )
        source = self.current_dataset_source()
        self.import_button.setEnabled(
            not self._import_busy and path_selected and source != "builtin"
        )
        self.builtin_button.setEnabled(
            not self._import_busy and builtin_available and source != "file"
        )
        self.builtin_button.setChecked(source == "builtin")
        self.browse_button.setEnabled(not self._import_busy)

    def _select_builtin(self) -> None:
        if self.current_source_mode() != "import":
            return
        index = self.builtin.currentIndex()
        if index < 0 or not self.builtin.itemData(index):
            index = next(
                (
                    candidate
                    for candidate in range(self.builtin.count())
                    if self.builtin.itemData(candidate)
                ),
                -1,
            )
        if index < 0:
            self.builtin_button.setChecked(False)
            return
        dataset_id = str(self.builtin.itemData(index) or "")
        if not dataset_id:
            self.builtin_button.setChecked(False)
            return
        self.builtin.setCurrentIndex(index)
        self._active_dataset_source = "builtin"
        self._active_dataset_id = dataset_id
        blocked = self.file_path.blockSignals(True)
        self.file_path.clear()
        self.file_path.blockSignals(blocked)
        self._refresh_sequence_mapping()
        self._sync_import_actions()
        self.datasetSelectionChanged.emit(dataset_id)

    def _import_selected_file(self) -> None:
        if self.current_source_mode() != "import":
            return
        path = str(self.file_path.text() or "").strip()
        if not path:
            return
        self._active_dataset_source = "file_pending"
        self._active_dataset_id = ""
        self.set_import_busy(True)
        self.fileImportRequested.emit(path)

    def set_import_busy(self, busy: bool) -> None:
        self._import_busy = bool(busy)
        self._sync_import_actions()

    def mark_file_imported(self, dataset_id: str = "") -> None:
        self._active_dataset_source = "file"
        self._active_dataset_id = str(dataset_id or "")
        self.set_import_busy(False)
        self._refresh_sequence_mapping()
        self.datasetSelectionChanged.emit(self._active_dataset_id)

    def set_active_dataset(self, dataset_id: str, source: str) -> None:
        self._active_dataset_id = str(dataset_id or "")
        self._active_dataset_source = str(source or "")
        index = self.builtin.findData(self._active_dataset_id)
        if index >= 0:
            self.builtin.setCurrentIndex(index)
        self._sync_import_actions()
        self.datasetSelectionChanged.emit(
            self._active_dataset_id if self._active_dataset_source != "generated_pending" else ""
        )

    def _refresh_sequence_mapping(self) -> None:
        family = self.current_family()
        has_file = bool(self.file_path.text().strip())
        host = getattr(self, "sequence_host", None)
        if host is not None:
            host.setVisible(
                self.current_source_mode() == "import"
                and family == "sequence"
                and has_file
                and self.current_dataset_source() == "file"
            )

    def _fill_builtins(self, family: str) -> None:
        # The packaged item below is an actual registered dataset ID.  Do not
        # offer decorative names that cannot be submitted to the training API.
        records = (
            (("内置演示·780 nm 四透镜耦合", "dataset-880bdde6c292"),)
            if family == "tabular" else ()
        )
        active_id = self.selected_dataset_id()
        self.builtin.blockSignals(True)
        self.builtin.clear()
        for label, dataset_id in records:
            self.builtin.addItem(label, dataset_id)
        if not records:
            self.builtin.addItem("序列模型请使用自定义文件", "")
        index = self.builtin.findData(active_id)
        if index >= 0:
            self.builtin.setCurrentIndex(index)
        else:
            self.builtin.setCurrentIndex(0 if records else -1)
            if self.current_dataset_source() == "builtin":
                self._active_dataset_source = ""
                self._active_dataset_id = ""
        self.builtin.blockSignals(False)

    def _apply_family(self, *, emit: bool = True) -> None:
        family = self.current_family()
        self._fill_builtins(family)
        self.model_type.clear()
        self.model_type.addItems(list(TABULAR_MODEL_CHOICES if family == "tabular" else SEQUENCE_MODEL_CHOICES))
        self._sync_train_hypers()
        if family == "tabular":
            self.file_path.setPlaceholderText("选择 CSV / JSONL 表格样本")
        else:
            self.file_path.setPlaceholderText("选择自定义长表后映射列；内置结构表无需映射")
        self._refresh_sequence_mapping()
        self._sync_import_actions()
        self._sync_generation_mode()
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
        self.model_type.setVisible(False)
        self.training_parameters_host.setVisible(False)
        self.rf_training_group.setVisible(False)
        self.xgb_training_group.setVisible(False)
        self.sequence_training_group.setVisible(False)
        blocked_more = self.training_more_button.blockSignals(True)
        self.training_more_button.setChecked(False)
        self.training_more_button.blockSignals(blocked_more)
        self.training_more_button.setArrowType(Qt.ArrowType.RightArrow)
        blocked = self.training_mode_button.blockSignals(True)
        self.training_mode_button.setChecked(not tabular)
        self.training_mode_button.setText("固定镜头数" if tabular else "任意镜头数")
        self._set_training_mode_appearance("fixed" if tabular else "arbitrary")
        self.training_mode_button.setToolTip(
            "使用随机森林 + XGBoost 训练"
            if tabular else "使用 BiLSTM 训练可变镜头数量的序列数据"
        )
        self.training_mode_button.blockSignals(blocked)
        self.train_button.setText("开始训练")

    def _set_training_mode_appearance(self, mode: str) -> None:
        """Refresh the mode button after its QSS selector changes."""
        button = self.training_mode_button
        if str(button.property("trainingMode") or "") == mode:
            return
        button.setProperty("trainingMode", mode)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def _set_training_mode(self, arbitrary_lens_count: bool) -> None:
        family = "sequence" if arbitrary_lens_count else "tabular"
        if self.current_family() != family:
            self._set_family(family)
        else:
            self._sync_train_hypers()

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
        self._generation_busy = bool(busy)
        if generate is not None:
            self._sync_generate_action()
        if train is not None:
            train.setEnabled(not busy)

    def _build_train_result(self, root: QVBoxLayout) -> None:
        self.chart = QComboBox()
        self.chart.addItems(["残差图", "实测值与预测值对照", "残差分布", "验证误差曲线"])
        self.chart.currentTextChanged.connect(self._show_train_chart)
        root.addWidget(_action_row(self.chart))
        self.train_summary = QLabel("尚未训练")
        self.train_summary.setObjectName("DocumentMetric")
        self.train_summary.setWordWrap(True)
        root.addWidget(self.train_summary)
        self.train_progress_host = QWidget()
        train_progress_layout = QHBoxLayout(self.train_progress_host)
        train_progress_layout.setContentsMargins(0, 2, 0, 2)
        train_progress_layout.setSpacing(8)
        self.train_progress_label = QLabel("训练尚未开始")
        self.train_progress_label.setObjectName("trainingProgressText")
        self.train_progress_label.setMinimumWidth(128)
        self.train_progress = QProgressBar()
        self.train_progress.setObjectName("trainingProgressBar")
        self.train_progress.setRange(0, 100)
        self.train_progress.setValue(0)
        self.train_progress.setTextVisible(False)
        train_progress_layout.addWidget(self.train_progress_label)
        train_progress_layout.addWidget(self.train_progress, 1)
        self.train_progress_host.setVisible(False)
        root.addWidget(self.train_progress_host)
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
            self._active_dataset_source = ""
            self._active_dataset_id = ""
            self.file_path.setText(path)
            self._sync_import_actions()
            self.datasetSelectionChanged.emit("")

    def _generate(self) -> None:
        self.generateRequested.emit()

    def show_generate_status(self, message: str, rows: list[tuple[str, str, str, str]] | None = None) -> None:
        # Kept as a compatibility hook for callers from older workflow code.
        # Generation/import progress is rendered in the left dataset rail now;
        # the old full-width status table is intentionally gone.
        self._last_dataset_status = str(message or "")

    def select_dataset(self, title: str) -> None:
        text = str(title or "")
        if text in SEQUENCE_DATASET_CHOICES:
            self._set_family("sequence")
        elif text in TABULAR_DATASET_CHOICES:
            self._set_family("tabular")
        index = self.builtin.findText(text)
        if index >= 0:
            mode_index = self.source_mode.findData("import")
            if mode_index >= 0 and self.source_mode.currentIndex() != mode_index:
                self.source_mode.setCurrentIndex(mode_index)
            self.builtin.setCurrentIndex(index)
            self._select_builtin()

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
        self.show_train_progress(1.0, "训练完成", state="complete")
        summary = dict(self._train_result.get("training_summary") or {})
        test = training_test_metrics(self._train_result)
        parts = ["训练完成"]
        sample_count = summary.get("sample_count") or summary.get("training_samples")
        if sample_count is None:
            split_counts = dict(self._train_result.get("split_counts") or {})
            sample_count = split_counts.get("train")
        if sample_count is not None:
            parts.append(f"训练样本 {sample_count}")
        if test.get("r2") is not None:
            parts.append(f"测试 R²={float(test['r2']):.3f}")
        if test.get("rmse") is not None:
            parts.append(f"RMSE={float(test['rmse']):.4g}")
        if getattr(self, "train_summary", None) is not None:
            self.train_summary.setText(" ".join(parts))
        if self.kind == "train_result":
            self._show_train_chart(self.chart.currentText())

    def mark_joint_trained(self, result: dict[str, Any]) -> None:
        body = dict(result or {})
        self.show_train_progress(1.0, "训练完成", state="complete")
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
                f"训练部分完成 随机森林 {score(rf)} XGBoost 未完成。"
                + (f"原因：{warning}" if warning else "")
                + " 随机森林结果可用于设计变量解释；请修复数据后再训练 XGBoost。"
            )
        else:
            self.train_summary.setText(
                f"训练完成 随机森林 {score(rf)} XGBoost {score(xgb)} "
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

    def show_train_progress(
        self,
        progress: float,
        message: str = "训练中",
        *,
        state: str = "running",
    ) -> None:
        """Render training progress while keeping the result workspace stable."""
        bar = getattr(self, "train_progress", None)
        host = getattr(self, "train_progress_host", None)
        label = getattr(self, "train_progress_label", None)
        if bar is None or host is None or label is None:
            return
        value = max(0.0, min(1.0, float(progress)))
        host.setVisible(True)
        bar.setValue(round(value * 100))
        next_state = str(state or "running")
        state_changed = bar.property("progressState") != next_state
        bar.setProperty("progressState", next_state)
        label.setText(f"{str(message or '训练中')} {value:.0%}")
        if state_changed:
            style = bar.style()
            style.unpolish(bar)
            style.polish(bar)
        bar.update()

    def show_train_failed(self, message: str) -> None:
        bar = getattr(self, "train_progress", None)
        current = (bar.value() / 100.0) if bar is not None else 0.0
        self.show_train_progress(current, message or "训练失败", state="error")

    def show_train_cancelled(self, message: str = "训练已取消") -> None:
        bar = getattr(self, "train_progress", None)
        current = (bar.value() / 100.0) if bar is not None else 0.0
        self.show_train_progress(current, message, state="cancelled")

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
