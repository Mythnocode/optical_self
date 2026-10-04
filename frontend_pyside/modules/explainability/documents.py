"""Explainability document tabs.

The shell owns navigation and orchestration; this module owns the explainability document surfaces.
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

# Rows the picker lays out before it starts scrolling internally.
_PICKER_VISIBLE_ROWS = 8

# 设计变量的英文紧凑记号（与后端 DESIGN_SHORT 一致）。用于「物理链路」
# 单参数贡献图的横坐标与「当前系统验证」瀑布图的纵坐标。
_DESIGN_SHORT = {
    "surfaces[0].radius_mm": "L1-r",
    "surfaces[0].distance_to_next_mm": "L1-d",
    "surfaces[2].radius_mm": "L2-r",
    "surfaces[2].distance_to_next_mm": "L2-d",
    "surfaces[4].radius_mm": "L3-r",
    "surfaces[4].distance_to_next_mm": "L3-d",
    "surfaces[6].radius_mm": "L4-r",
    "surfaces[6].distance_to_next_mm": "L4-d",
}


def _design_short_label(feature: object) -> str:
    """把设计变量特征路径映射为 L1-r/L1-d 等英文记号；其余回退中文名。"""
    key = str(feature or "")
    if key == "__other_model_features__":
        return "其他模型特征（合并）"
    return _DESIGN_SHORT.get(key, display_feature_name(key))


# 以实际目标单位展示，SHAP 结果仍保持原始模型输出口径。
from shared_presentation.parameter_explanation import target_display_label as _target_display_label


def _fixed_action_row(*widgets: QWidget) -> QWidget:
    """Build a top action row that hugs its content.

    ``_action_row`` keeps the default Preferred vertical policy, so once the
    widget that actually owns the page height (the plot workspace) is hidden,
    the row swallows the leftover space and pushes the content apart.
    """
    host = _action_row(*widgets)
    host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    return host


def _notation_hint() -> QLabel:
    """图表记号说明（L-x/r/d），挂在模型选择行右侧，字号比「解释模型」小一号。"""
    hint = QLabel("L-x：第几面透镜　r：曲率半径　d：厚度")
    hint.setObjectName("ExplainNotationHint")
    hint.setToolTip("L-x：第 x 面透镜；r：前表面曲率半径；d：透镜厚度")
    hint.setStyleSheet("font-size: 11pt;")
    return hint


class AnalysisTextDocument(QWidget):
    shapRanksReady = Signal(object)

    def __init__(self, kind: str, selected: str = "", parent=None, context=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.selected = selected
        self.context = context
        self._dataset_cache: dict[str, dict[str, Any]] = {}
        self._current_cache: dict[str, dict[str, Any]] = {}
        self._global_items: list[dict[str, Any]] = []
        self._target_label = "模型输出"
        self._target_unit = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        title, subtitle = _kind_titles("explainability", kind)
        del subtitle
        self.model = QComboBox()
        self.compute = _primary_button("计算解释")
        self.compute.clicked.connect(self._compute)
        self.shap_chart = None
        self._param_view = 0
        self.param_view_buttons: list[QToolButton] = []
        self.param_view_group = QButtonGroup(self)
        self.param_view_group.setExclusive(True)
        self.feature_caption = QLabel(self._parameter_caption())
        if kind == "global_contrib":
            self.shap_chart = QComboBox()
            self.shap_chart.addItems(
                [
                    "全局特征重要性排名",
                    "蜂群图",
                    "特征依赖网格图",
                    "单变量依赖趋势图",
                    "物理一致性图",
                    "瀑布图",
                ]
            )
            self.shap_chart.currentTextChanged.connect(self._render_cached_shap)
            root.addWidget(
                _fixed_action_row(
                    QLabel("解释模型"),
                    self.model,
                    QLabel("图表"),
                    self.shap_chart,
                    self.compute,
                    _notation_hint(),
                )
            )
            message = "选择已训练模型后计算，这里把 17 特征 SHAP 经数值雅可比回传到 8 个设计变量。"
        elif kind == "param_trend":
            for index, label in enumerate(("单参数贡献图", "物理链路")):
                button = QToolButton()
                button.setObjectName("ExplainViewSwitchButton")
                button.setText(label)
                button.setCheckable(True)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                button.setFixedHeight(34)
                self.param_view_group.addButton(button, index)
                self.param_view_buttons.append(button)
            self.param_view_group.idClicked.connect(self._set_param_view)
            self.param_view_buttons[0].setChecked(True)
            root.addWidget(
                _fixed_action_row(
                    QLabel("解释模型"),
                    self.model,
                    self.compute,
                    *self.param_view_buttons,
                    _notation_hint(),
                )
            )
            message = "暂无解释结果。"
        else:
            root.addWidget(
                _fixed_action_row(
                    QLabel("解释模型"),
                    self.model,
                    self.compute,
                    _notation_hint(),
                )
            )
            message = "计算后把当前镜头当作一条样本，用瀑布图拆开各参数贡献。"
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        if kind == "param_trend":
            # Keep the plot below the top action row and let it fill the page.
            self.workspace.setMinimumHeight(0)
            self.workspace.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            root.addWidget(self.workspace, 1)
        else:
            root.addWidget(self.workspace, 1)

        self.selection_panel = QFrame(self)
        self.selection_panel.setObjectName("ExplainSelectionCard")
        self.selection_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        selection_layout = QVBoxLayout(self.selection_panel)
        selection_layout.setContentsMargins(10, 8, 10, 8)
        selection_header = QHBoxLayout()
        selection_title = QLabel("从贡献排序选择关键参数")
        selection_title.setObjectName("ExplainSectionTitle")
        selection_header.addWidget(selection_title)
        selection_header.addStretch(1)
        self.chain_button = QPushButton("生成物理链路")
        self.chain_button.setObjectName("ExplainActionButton")
        self.chain_button.clicked.connect(self._render_physical_chain)
        selection_header.addWidget(self.chain_button)
        selection_layout.addLayout(selection_header)
        self.feature_picker = QListWidget()
        self.feature_picker.setObjectName("ExplainFeaturePicker")
        self.feature_picker.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.feature_picker.itemChanged.connect(self._feature_picker_changed)
        selection_layout.addWidget(self.feature_picker)
        selection_layout.setSpacing(4)
        self.selection_panel.hide()
        if kind != "param_trend":
            root.addWidget(self.selection_panel)

        self.chain_panel = QFrame(self)
        self.chain_panel.setObjectName("ExplainChainCard")
        self.chain_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        chain_layout = QVBoxLayout(self.chain_panel)
        chain_layout.setContentsMargins(10, 8, 10, 8)
        self.chain_title = QLabel("物理链路")
        self.chain_title.setObjectName("ExplainSectionTitle")
        chain_layout.addWidget(self.chain_title)
        self.chain_rows = QVBoxLayout()
        self.chain_rows.setSpacing(6)
        chain_layout.addLayout(self.chain_rows)
        self.chain_panel.hide()
        # The chain view stacks both cards under the action row.  A formula
        # chain can be taller than the window, so it scrolls instead of being
        # clipped, and the trailing stretch keeps the cards anchored on top.
        self.chain_view: QScrollArea | None = None
        if kind == "param_trend":
            self.chain_view = QScrollArea(self)
            self.chain_view.setObjectName("ExplainChainScroll")
            self.chain_view.setWidgetResizable(True)
            self.chain_view.setFrameShape(QFrame.Shape.NoFrame)
            self.chain_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            chain_host = QWidget()
            chain_host.setObjectName("ExplainChainViewport")
            chain_host_layout = QVBoxLayout(chain_host)
            chain_host_layout.setContentsMargins(0, 0, 0, 0)
            chain_host_layout.setSpacing(8)
            chain_host_layout.addWidget(self.selection_panel)
            chain_host_layout.addWidget(self.chain_panel)
            chain_host_layout.addStretch(1)
            self.chain_view.setWidget(chain_host)
            self.chain_view.hide()
            root.addWidget(self.chain_view, 1)
        else:
            root.addWidget(self.chain_panel)

        self.summary_panel = QFrame(self)
        self.summary_panel.setObjectName("ExplainSummaryPanel")
        summary_layout = QVBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_buttons: list[QToolButton] = []
        self.summary_group = QButtonGroup(self)
        self.summary_group.setExclusive(True)
        summary_nav = QHBoxLayout()
        summary_nav.setSpacing(6)
        for index, label in enumerate(("模型分析", "物理联系", "下一步")):
            button = QToolButton()
            button.setObjectName("ExplainSummaryButton")
            button.setText(label)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            self.summary_group.addButton(button, index)
            self.summary_buttons.append(button)
            summary_nav.addWidget(button, 1)
        summary_layout.addLayout(summary_nav)
        self.summary_stack = QStackedWidget()
        self.summary_stack.setObjectName("ExplainSummaryStack")

        self.analysis_text = QLabel()
        self.analysis_text.setObjectName("ExplainSummaryBody")
        self.analysis_text.setWordWrap(True)
        self.analysis_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_stack.addWidget(self.analysis_text)

        self.formula_text = QFrame()
        self.formula_text.setObjectName("ExplainFormulaCard")
        formula_layout = QVBoxLayout(self.formula_text)
        formula_layout.setContentsMargins(8, 6, 8, 6)
        formula_layout.setSpacing(4)
        self.formula_heading = QLabel("物理联系")
        self.formula_heading.setObjectName("ExplainSectionTitle")
        formula_layout.addWidget(self.formula_heading)
        self.formula_equations = QVBoxLayout()
        self.formula_equations.setSpacing(2)
        formula_layout.addLayout(self.formula_equations)
        self.formula_details = QLabel()
        self.formula_details.setWordWrap(True)
        self.formula_details.setTextFormat(Qt.TextFormat.RichText)
        self.formula_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        formula_layout.addWidget(self.formula_details)
        self.summary_stack.addWidget(self.formula_text)

        self.next_step_text = QLabel()
        self.next_step_text.setObjectName("ExplainSummaryBody")
        self.next_step_text.setWordWrap(True)
        self.next_step_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_stack.addWidget(self.next_step_text)
        summary_layout.addWidget(self.summary_stack)
        self.summary_group.idClicked.connect(self.summary_stack.setCurrentIndex)
        self.summary_buttons[0].setChecked(True)
        self.summary_panel.hide()
        root.addWidget(self.summary_panel)
        self.model.currentIndexChanged.connect(lambda _index: self._sync_compute_enabled())
        self._show(title, message)
        self._sync_compute_enabled()

    def set_explain_cache(self, dataset_cache: dict[str, dict[str, Any]], current_cache: dict[str, dict[str, Any]]) -> None:
        self._dataset_cache = dataset_cache
        self._current_cache = current_cache

    def _render_cached_shap(self, _name: str = "") -> None:
        if self.kind != "global_contrib":
            return
        record = self._current_record()
        model_id = str(record.get("id") or "")
        key = self._design_cache_key(model_id)
        body = dict(self._dataset_cache.get(key) or {})
        if not body:
            return
        self._render_design_variable(body)

    @staticmethod
    def _design_cache_key(model_id: str) -> str:
        return f"__design_variables__:{model_id}"

    def set_trained_models(self, models: list[dict[str, Any]]) -> None:
        previous = self.model.currentData()
        previous_id = str((previous or {}).get("id") or "") if isinstance(previous, dict) else ""
        self.model.blockSignals(True)
        self.model.clear()
        for item in models:
            record = dict(item)
            self.model.addItem(str(record.get("title") or record.get("id") or "模型"), record)
        self.model.blockSignals(False)
        if previous_id:
            for index in range(self.model.count()):
                data = self.model.itemData(index)
                if isinstance(data, dict) and str(data.get("id") or "") == previous_id:
                    self.model.setCurrentIndex(index)
                    break
        self._sync_compute_enabled()

    def set_selected(self, key: str) -> None:
        self.selected = str(key or "")
        self.feature_caption.setText(self._parameter_caption())
        self._sync_compute_enabled()

    def set_model(self, title: str) -> None:
        text = str(title or "")
        if not text:
            return
        index = self.model.findText(text)
        if index >= 0:
            self.model.setCurrentIndex(index)
        self._sync_compute_enabled()

    def _parameter_caption(self) -> str:
        if self.kind != "param_trend":
            return ""
        if not self.selected:
            return "未选择参数"
        return display_feature_name(self.selected)

    def _current_record(self) -> dict[str, Any]:
        data = self.model.currentData()
        return dict(data) if isinstance(data, dict) else {}

    def _heading(self) -> str:
        return {
            "global_contrib": "贡献排序",
            "param_trend": "物理链路",
            "current_system": "当前系统验证",
        }.get(self.kind, "解释图")

    def _sync_compute_enabled(self) -> None:
        record = self._current_record()
        model_id = str(record.get("id") or "")
        family = str(record.get("family") or record.get("model_type") or "")
        enabled = bool(model_id)
        reason = ""
        if not model_id:
            reason = "请先在模型页训练，再选择该模型。"
            enabled = False
        elif not shap_supported(family):
            reason = "这一版不算 SHAP"
            enabled = False
        self.compute.setEnabled(enabled)
        self.compute.setToolTip(reason)
        if not enabled and reason and self.model.count() == 0:
            self._show(self._heading(), reason)

    def _compute(self) -> None:
        heading = self._heading()
        record = self._current_record()
        model_id = str(record.get("id") or "")
        family = str(record.get("family") or record.get("model_type") or "")
        if not model_id:
            self._show(heading, "请先在模型页训练，再选择该模型。")
            return
        if not shap_supported(family):
            self._show(heading, "这一版不算 SHAP")
            return
        if self.kind == "global_contrib":
            self._compute_design_variables(heading, model_id)
            return
        cache = self._current_cache if self.kind == "current_system" else self._dataset_cache
        cached = dict(cache.get(model_id) or {})
        if cached:
            self._render_shap(cached)
            return
        api = getattr(self.context, "api_client", None) if self.context is not None else None
        if api is None:
            self._show(heading, "后端不可用（无 API 连接）")
            return
        from uuid import uuid4

        from frontend_pyside.infrastructure.api.clients import TrainingClient

        payload: dict[str, Any] = {"top_k": 8, "max_samples": 80, "background_sample_count": 80}
        design_paths = [str(path) for path in list(record.get("design_variable_paths") or []) if str(path)]
        if design_paths:
            payload["display_feature_paths"] = design_paths
        if self.kind == "current_system":
            project = getattr(getattr(self.context, "project", None), "project", None)
            try:
                payload["features"] = model_features(project, record)
            except FeaturePathError as exc:
                self._show(heading, f"当前镜头无法构造模型特征：{exc}")
                return
        self._token = f"workbench.explain.{uuid4().hex[:8]}"
        self._show(heading, "正在计算解释…")
        if not getattr(self, "_api_bound", False):
            api.completed.connect(self._on_explain_completed)
            api.failed.connect(self._on_explain_failed)
            self._api_bound = True
        self._failure_text = explain_shap_failure
        TrainingClient(api).explain_shap(self._token, model_id, payload)

    def _on_explain_completed(self, key: str, data: object) -> None:
        if str(key) != getattr(self, "_token", ""):
            return
        body = dict(data or {}) if isinstance(data, dict) else {}
        if isinstance(body.get("result"), dict) and not body.get("top_features"):
            body = dict(body.get("result") or {})
        record = self._current_record()
        model_id = str(record.get("id") or "")
        if model_id:
            if self.kind == "global_contrib":
                self._dataset_cache[self._design_cache_key(model_id)] = body
            else:
                cache = self._current_cache if self.kind == "current_system" else self._dataset_cache
                cache[model_id] = body
        if self.kind == "global_contrib":
            self._render_design_variable(body)
        else:
            self._render_shap(body)

    def _on_explain_failed(self, key: str, message: str) -> None:
        if str(key) != getattr(self, "_token", ""):
            return
        self._show(self._heading(), explain_shap_failure(message))

    def _compute_design_variables(self, heading: str, model_id: str) -> None:
        cached = dict(self._dataset_cache.get(self._design_cache_key(model_id)) or {})
        if cached:
            self._render_design_variable(cached)
            return
        api = getattr(self.context, "api_client", None) if self.context is not None else None
        if api is None:
            self._show(heading, "后端不可用（无 API 连接）")
            return
        from uuid import uuid4

        from frontend_pyside.infrastructure.api.clients import TrainingClient

        payload: dict[str, Any] = {"max_samples": 80, "background_sample_count": 80}
        self._token = f"workbench.explain.design.{uuid4().hex[:8]}"
        self._show(heading, "计算中…")
        if not getattr(self, "_api_bound", False):
            api.completed.connect(self._on_explain_completed)
            api.failed.connect(self._on_explain_failed)
            self._api_bound = True
        self._failure_text = explain_shap_failure
        TrainingClient(api).explain_design_variables(self._token, model_id, payload)

    def _render_design_variable(self, body: dict[str, Any]) -> None:
        from shared_presentation.explainability import design_variable_plot
        chart = str(self.shap_chart.currentText()) if self.shap_chart is not None else "全局特征重要性排名"
        plot = design_variable_plot(body, chart)
        if plot.get("kind") == "empty":
            self._show("贡献排序", plot["message"])
        else:
            self.workspace.set_result(0, chart, plot)

    def _set_summary_sections(
        self,
        model_text: str,
        physics_html: str,
        next_text: str,
        *,
        active: int = 0,
        formula_steps: tuple[tuple[str, str], ...] = (),
        formula_title: str = "物理联系",
    ) -> None:
        """Show the three compact interpretation sections.

        The previous implementation concatenated every diagnostic into one
        gray paragraph.  Keeping the sections in a stack makes the reading
        order explicit without making the result page vertically noisy.
        """
        self.analysis_text.setText(str(model_text or ""))
        self.formula_heading.setText(str(formula_title or "物理联系"))
        while self.formula_equations.count():
            child = self.formula_equations.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        if formula_steps:
            from frontend_pyside.features.explainability.formula_presentation import FormulaImageLabel

            for index, (stage, latex) in enumerate(formula_steps, start=1):
                heading = QLabel(f"公式 {index} · {stage}")
                heading.setObjectName("ExplainFormulaStage")
                self.formula_equations.addWidget(heading)
                equation = FormulaImageLabel()
                equation.set_formula(latex)
                self.formula_equations.addWidget(equation)
        self.formula_details.setText(str(physics_html or "暂无可靠的物理公式映射。"))
        self.next_step_text.setText(str(next_text or "暂无下一步建议。"))
        index = max(0, min(int(active), self.summary_stack.count() - 1))
        self.summary_stack.setCurrentIndex(index)
        if 0 <= index < len(self.summary_buttons):
            self.summary_buttons[index].setChecked(True)
        self.summary_panel.show()

    def _set_feature_summary(
        self,
        feature: str,
        importance: float,
        direction: str = "",
        *,
        verified: bool = False,
        target_unit: str = "",
    ) -> None:
        from shared_presentation.current_explanation import feature_summary
        summary = feature_summary(feature, importance, direction, verified=verified, target_unit=target_unit)
        if summary is None:
            self.summary_panel.hide()
            return
        if self.kind == "current_system":
            self._set_summary_sections(
                summary['model_text'], summary['physics_html'], summary['next_text'],
                formula_steps=tuple((step['stage'], step['latex']) for step in summary['formula_steps']),
                formula_title=summary['formula_title'],
            )

    @staticmethod
    def _feature_label(feature: object) -> str:
        key = str(feature or "")
        if key == "__other_model_features__":
            return "其他模型特征（合并）"
        return display_feature_name(key)

    def _set_param_view(self, index: int) -> None:
        if self.kind != "param_trend":
            return
        self._param_view = 1 if int(index) == 1 else 0
        show_chain = self._param_view == 1
        has_chain = show_chain and bool(self._global_items)
        self.workspace.setVisible(not show_chain)
        self.selection_panel.setVisible(has_chain)
        self.chain_panel.setVisible(has_chain)
        if self.chain_view is not None:
            self.chain_view.setVisible(has_chain)

    def _feature_picker_changed(self, item: QListWidgetItem) -> None:
        if item.checkState() == Qt.CheckState.Checked:
            checked = sum(
                self.feature_picker.item(index).checkState() == Qt.CheckState.Checked
                for index in range(self.feature_picker.count())
            )
            if checked > 3:
                self.feature_picker.blockSignals(True)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.feature_picker.blockSignals(False)
                return
        if self._param_view == 1:
            self._render_physical_chain()

    def _selected_feature_keys(self) -> list[str]:
        keys: list[str] = []
        for index in range(self.feature_picker.count()):
            item = self.feature_picker.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                keys.append(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        return [key for key in keys if key]

    def _populate_feature_picker(self, items: list[dict[str, Any]], feature_label: Callable[[object], str]) -> None:
        self._global_items = [dict(item) for item in items if isinstance(item, dict)]
        self.feature_picker.blockSignals(True)
        self.feature_picker.clear()
        from shared_presentation.parameter_explanation import feature_picker_rows
        for index, row in enumerate(feature_picker_rows(self._global_items)):
            feature = row['feature']
            item = QListWidgetItem(row['text'])
            item.setData(Qt.ItemDataRole.UserRole, feature)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if index < 3 else Qt.CheckState.Unchecked)
            self.feature_picker.addItem(item)
        self.feature_picker.blockSignals(False)
        self._sync_feature_picker_height()
        self._render_physical_chain()
        self._set_param_view(self._param_view)

    def _sync_feature_picker_height(self) -> None:
        """Lay the ranking list out by row count instead of a fixed cap.

        The old 126 px ceiling cut the ranking off after four rows, so the
        contribution order users select from was never fully visible.
        """
        rows = self.feature_picker.count()
        if rows <= 0:
            return
        row_height = self.feature_picker.sizeHintForRow(0)
        if row_height <= 0:
            row_height = 30
        frame = 2 * self.feature_picker.frameWidth() + 4
        content = rows * row_height + frame
        self.feature_picker.setFixedHeight(
            min(content, _PICKER_VISIBLE_ROWS * row_height + frame)
        )

    def _clear_chain_rows(self) -> None:
        while self.chain_rows.count():
            child = self.chain_rows.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_physical_chain(self) -> None:
        if not self._global_items:
            return
        from html import escape

        from shared_presentation.parameter_explanation import physical_chain_items
        from frontend_pyside.features.explainability.formula_presentation import FormulaImageLabel

        self._clear_chain_rows()
        selected_keys = self._selected_feature_keys()
        self.chain_panel.setVisible(self._param_view == 1)
        if not selected_keys:
            self.chain_title.setText("物理链路")
            return

        chain = physical_chain_items(selected_keys, self._target_label)
        self.chain_title.setText(chain['title'])
        for row in chain['rows']:
            feature_name = row['name']
            steps = [(step['stage'], step['latex']) for step in row['steps']]
            path = row['path']

            card = QFrame()
            card.setObjectName("ExplainChainRow")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(3)
            title = QLabel(f"参数：{escape(feature_name)}")
            title.setTextFormat(Qt.TextFormat.RichText)
            title.setObjectName("ExplainSectionTitle")
            card_layout.addWidget(title)
            path_label = QLabel(escape(path))
            path_label.setWordWrap(True)
            path_label.setTextFormat(Qt.TextFormat.RichText)
            path_label.setStyleSheet("color:#155EEF; font-size:12pt;")
            card_layout.addWidget(path_label)

            if steps:
                for index, (stage, latex) in enumerate(steps, start=1):
                    stage_label = QLabel(f"公式 {index} · {escape(stage)}")
                    stage_label.setTextFormat(Qt.TextFormat.RichText)
                    stage_label.setObjectName("ExplainFormulaStage")
                    card_layout.addWidget(stage_label)
                    equation = FormulaImageLabel()
                    equation.set_formula(latex)
                    card_layout.addWidget(equation)
                    if index < len(steps):
                        arrow = QLabel("↓")
                        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        arrow.setObjectName("ExplainChainArrow")
                        card_layout.addWidget(arrow)
            else:
                note = QLabel("该变量尚无可靠的解析公式映射，建议通过正式参数扫描和仿真定位。")
                note.setWordWrap(True)
                card_layout.addWidget(note)
            self.chain_rows.addWidget(card)

        # Every valid feature-specific route terminates at the same normalized
        # complex-field overlap; keep this shared equation visibly separate
        # from the parameter-dependent formula steps above.
        overlap_formula = chain['overlap_formula']
        if overlap_formula:
            output = QFrame()
            output.setObjectName("ExplainChainRow")
            output_layout = QVBoxLayout(output)
            output_layout.setContentsMargins(10, 8, 10, 8)
            output_layout.setSpacing(3)
            heading = QLabel("共同输出公式 · 归一化复场重叠")
            heading.setObjectName("ExplainFormulaStage")
            output_layout.addWidget(heading)
            equation = FormulaImageLabel()
            equation.set_formula(overlap_formula)
            output_layout.addWidget(equation)
            output_layout.addWidget(QLabel("复场重叠结果进入当前模型解释的目标输出。"))
            self.chain_rows.addWidget(output)

    def _render_shap(self, body: dict[str, Any]) -> None:
        from frontend_pyside.shared.feature_labels import display_feature_name as label_of

        target_name = str(body.get("target_name") or "模型输出")
        target_unit = str(body.get("target_unit") or "").strip()
        target_label = _target_display_label(target_name, target_unit)
        self._target_label = target_label
        self._target_unit = target_unit

        def feature_label(value: object) -> str:
            key = str(value or "")
            return "其他模型特征（合并）" if key == "__other_model_features__" else label_of(key)

        items = list(body.get("top_features") or body.get("feature_contributions") or body.get("global_importance") or [])
        if self.kind == "param_trend":
            if not items:
                self._show("物理链路", "这次解释没有返回可用的 SHAP 参数排名。")
                return
            from shared_presentation.parameter_explanation import parameter_plot
            plot = parameter_plot(body, self.selected)
            self.workspace.set_result(
                0, "辅助：单参数 SHAP 依赖" if plot['kind'] == 'scatter' else "物理链路", plot,
            )
            self._populate_feature_picker(items, feature_label)
            return
        if self.kind == "current_system":
            from shared_presentation.current_explanation import current_explanation
            formal_result = getattr(getattr(self.context, "project", None), "formal_result", None)
            presentation = current_explanation(body, verified=isinstance(formal_result, dict) and bool(formal_result))
            plot = presentation['plot']
            if plot['kind'] == 'empty':
                self._show("当前系统瀑布图", plot['message'])
            else:
                self.workspace.set_result(0, "当前系统瀑布图", plot)
            summary = presentation['interpretation']
            if summary:
                self._set_summary_sections(
                    summary['model_text'], summary['physics_html'], summary['next_text'],
                    formula_steps=tuple((step['stage'], step['latex']) for step in summary['formula_steps']),
                    formula_title=summary['formula_title'],
                )
            return
        if not items:
            self._show("贡献排序", "这次解释没有返回全局贡献。")
            return
        labels = [feature_label(item.get("feature") or item.get("name")) for item in items]
        values = [float(item.get("mean_abs_shap", abs(float(item.get("mean_shap", 0.0) or 0.0))) or 0.0) for item in items]
        if self.kind == "global_contrib" and self.shap_chart is not None and self.shap_chart.currentText() == "SHAP分布图":
            payload = shap_beeswarm_payload(body, feature_label)
            if payload is None:
                self._show("SHAP分布图", "这次解释没有返回可绘制的样本级 SHAP 数据。")
                return
            self.workspace.set_result(0, "SHAP分布图", payload)
        else:
            self.workspace.set_result(
                0,
                "贡献排序",
                {
                    "kind": "barh",
                    "labels": labels,
                    "values": values,
                    "show_values": True,
                    "source": "模型解释",
                    "x_label": f"平均 |SHAP| · {target_label}",
                    "description": "数值越大表示模型越依赖该设计变量；不等同于物理因果。",
                },
            )
        project = getattr(getattr(self.context, "project", None), "project", None) if self.context is not None else None
        keys = [row[0] for row in _variable_rows(project)] if project is not None else []
        self.shapRanksReady.emit(_variable_shap_scores(items, keys))

    def _show(self, title: str, message: str) -> None:
        self.workspace.set_result(0, title, {"kind": "empty", "message": message})
        if self.kind == "param_trend" and self.param_view_buttons:
            self.param_view_buttons[0].setChecked(True)
            self._set_param_view(0)
        self.selection_panel.hide()
        self.chain_panel.hide()
        if self.chain_view is not None:
            self.chain_view.hide()
        self.summary_panel.hide()


__all__ = ["AnalysisTextDocument"]
