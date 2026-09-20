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


# 目标显示名：XGBoost 物理残差模型的输出已按 η 口径换算，与随机森林
# 一致显示为「耦合效率」，而非「耦合损耗(dB)」。
_TARGET_DISPLAY = {
    "coupling_efficiency": "耦合效率",
    "coupling_loss_db": "耦合效率",
}


def _target_display_label(target_name: object, target_unit: object = "") -> str:
    """把目标名映射为中文显示名；已换算为效率的目标不附带 dB 单位。"""
    name = str(target_name or "模型输出")
    unit = str(target_unit or "").strip()
    if name in _TARGET_DISPLAY:
        return _TARGET_DISPLAY[name]
    return f"{name}（{unit}）" if unit else name


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

        self.formula_text = QLabel()
        self.formula_text.setObjectName("ExplainFormulaCard")
        self.formula_text.setWordWrap(True)
        self.formula_text.setTextFormat(Qt.TextFormat.RichText)
        self.formula_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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
        import numpy as np

        design_paths = [str(p) for p in list(body.get("design_paths") or [])]
        labels = [str(v) for v in list(body.get("design_labels") or [])]
        importance = [dict(item) for item in list(body.get("importance") or []) if isinstance(item, dict)]
        total = np.asarray(body.get("total") or [], dtype=float)
        design_values = np.asarray(body.get("design_values") or [], dtype=float)
        target_label = _TARGET_DISPLAY.get(
            str(body.get("target_name") or ""), "模型输出"
        )
        if not design_paths or total.ndim != 2 or total.shape[1] != len(design_paths) or not importance:
            self._show("贡献排序", "这次解释没有返回设计变量的贡献值。")
            return
        n = int(total.shape[0])
        if not labels:
            labels = design_paths
        labels = labels[: len(design_paths)]
        chart = str(self.shap_chart.currentText()) if self.shap_chart is not None else "全局特征重要性排名"

        ranked_labels = [str(item.get("label") or item.get("feature") or "") for item in importance]
        ranked_indices = [design_paths.index(str(item.get("feature") or "")) for item in importance if str(item.get("feature") or "") in design_paths]
        ranked_values = [float(item.get("mean_abs") or 0.0) for item in importance]
        total_ranked = total[:, ranked_indices]
        design_ranked = design_values[:, ranked_indices]

        if chart == "蜂群图":
            points: list[dict[str, Any]] = []
            for sample_index in range(n):
                for j, col in enumerate(ranked_indices):
                    column = design_values[:, col]
                    low = float(column.min())
                    high = float(column.max())
                    raw = float(design_values[sample_index, col])
                    scaled = (raw - low) / (high - low) if high > low else 0.5
                    points.append(
                        {
                            "feature": ranked_labels[j],
                            "value": float(total[sample_index, col]),
                            "sample_index": sample_index,
                            "color": "#dc2626" if scaled >= 0.5 else "#2563eb",
                        }
                    )
            self.workspace.set_result(
                0,
                "蜂群图",
                {
                    "kind": "beeswarm",
                    "labels": ranked_labels,
                    "points": points,
                    "importance": ranked_values,
                    "sample_count": n,
                    "x_label": "SHAP 值",
                    "source": "模型解释",
                    "summary": "红色表示该设计变量取值偏高，蓝色表示偏低；横轴为对模型输出的正负 SHAP 值。",
                    "description": f"设计变量 SHAP 值分布 · {n} 个样本",
                },
            )
            return
        if chart == "特征依赖网格图" or chart == "单变量依赖趋势图":
            corr = np.corrcoef(design_values.T) if n >= 2 and design_values.shape[1] >= 2 else np.eye(len(design_paths))
            panels: list[dict[str, Any]] = []
            for j, col in enumerate(range(len(design_paths))):
                x = design_values[:, col]
                y = total[:, col]
                others = [k for k in range(len(design_paths)) if k != col]
                jmax = max(others, key=lambda k: abs(float(corr[col, k]))) if others else col
                panels.append(
                    {
                        "label": labels[col],
                        "x": x.tolist(),
                        "y": y.tolist(),
                        "color": design_values[:, jmax].tolist(),
                        "color_label": labels[jmax],
                    }
                )
            if chart == "特征依赖网格图":
                self.workspace.set_result(
                    0,
                    "特征依赖网格图",
                    {"kind": "dependence_grid", "panels": panels, "title": "SHAP 特征依赖网格图", "y_label": "SHAP Value"},
                )
            else:
                self.workspace.set_result(
                    0,
                    "单变量依赖趋势图",
                    {"kind": "dependence_fit_ci", "panels": panels, "title": "SHAP 单变量依赖趋势图", "y_label": "SHAP Value"},
                )
            return
        if chart == "物理一致性图":
            consistency = dict(body.get("physics_consistency") or {})
            x = [float(v) for v in list(consistency.get("shap_importance") or [])]
            y = [float(v) for v in list(consistency.get("physics_elasticity") or [])]
            self.workspace.set_result(
                0,
                "物理一致性图",
                {
                    "kind": "physics_consistency",
                    "x": x,
                    "y": y,
                    "labels": labels,
                    "pearson": consistency.get("pearson"),
                    "spearman": consistency.get("spearman"),
                    "x_label": "平均SHAP",
                    "y_label": "物理解析重要性",
                    "summary": "横轴为 ML 学到的变量重要性，纵轴为光学理论敏感度；二者共线说明模型与物理一致。",
                },
            )
            return
        if chart == "瀑布图":
            waterfall = dict(body.get("waterfall") or {})
            wf_values = [float(v) for v in list(waterfall.get("values") or [])]
            if len(wf_values) != len(labels):
                wf_values = total_ranked[0].tolist() if n > 0 else [0.0] * len(labels)
                wf_labels = list(ranked_labels)
            else:
                wf_labels = list(labels)
            order = sorted(range(len(wf_values)), key=lambda index: -abs(wf_values[index]))
            self.workspace.set_result(
                0,
                "瀑布图",
                {
                    "kind": "waterfall",
                    "labels": [wf_labels[i] for i in order],
                    "values": [wf_values[i] for i in order],
                    "base_value": float(waterfall.get("base_value") or 0.0),
                    "x_label": "耦合效率",
                    "summary": f"目标：{target_label}",
                },
            )
            return
        # 默认：全局特征重要性排名
        self.workspace.set_result(
            0,
            "全局特征重要性排名",
            {
                "kind": "barh",
                "labels": ranked_labels,
                "values": ranked_values,
                "show_values": True,
                "source": "模型解释",
                "x_label": "平均贡献",
                "description": "数值越大表示模型越依赖该设计变量；不等同于物理因果。",
            },
        )

    def _set_summary_sections(
        self,
        model_text: str,
        physics_html: str,
        next_text: str,
        *,
        active: int = 0,
    ) -> None:
        """Show the three compact interpretation sections.

        The previous implementation concatenated every diagnostic into one
        gray paragraph.  Keeping the sections in a stack makes the reading
        order explicit without making the result page vertically noisy.
        """
        self.analysis_text.setText(str(model_text or ""))
        self.formula_text.setText(str(physics_html or "暂无可靠的物理公式映射。"))
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
        from frontend_pyside.features.explainability.actions import (
            formula_binding_for_feature,
            formula_latex,
            physical_mechanism_for_feature,
            suggested_action_for_feature,
        )
        from frontend_pyside.features.explainability.formula_presentation import formula_html

        if not feature:
            self.summary_panel.hide()
            return
        name = self._feature_label(feature)
        category, item, level, note = formula_binding_for_feature(feature)
        mechanism = physical_mechanism_for_feature(feature)
        action = suggested_action_for_feature(feature)
        unit = f" {target_unit}" if target_unit else ""
        model_text = f"{name} 的平均 |SHAP| 为 {float(importance):.4g}{unit}。"
        if direction:
            model_text += f"\n{direction}"
        if category and item:
            relation = formula_html(category, item, formula_latex(category, item))
            physics_html = (
                f"<b>公式：{category} · {item}</b>{relation}"
                f"<div style='padding:0 8px 8px; color:#465467;'>"
                f"物理联系：{mechanism}<br>关联方式：{level}。{note}<br>"
                "SHAP 仅用于模型贡献排序，箭头表示光学计算依赖，结论须由正式仿真验证。"
                "</div>"
            )
        else:
            physics_html = (
                f"<b>物理联系</b><div style='padding:8px; color:#465467;'>"
                f"{mechanism}<br>当前特征尚无可靠的闭式公式映射，建议通过参数扫描定位。"
                "<br>SHAP 仅用于模型贡献排序，不能单独证明物理因果。</div>"
            )
        next_text = f"{action}，再用正式光学计算复核。"
        if verified:
            next_text += " 当前项目已有正式仿真结果，可继续做数值对照。"
        else:
            next_text += " 当前结论仍是模型线索，尚未由本次正式仿真确认。"
        if self.kind == "current_system":
            self._set_summary_sections(model_text, physics_html, next_text)

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
        for index, record in enumerate(self._global_items):
            feature = str(record.get("feature") or record.get("name") or "")
            value = float(
                record.get("mean_abs_shap", abs(float(record.get("mean_shap", 0.0) or 0.0))) or 0.0
            )
            item = QListWidgetItem(f"{index + 1}. {feature_label(feature)}    |SHAP| {value:.4g}")
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

    @staticmethod
    def _physical_path(category: str, item: str, target_label: str) -> tuple[str, str]:
        paths = {
            "结构参数": ("设计参数", "表面光焦度 / 传播矩阵", "焦面复场"),
            "对准误差": ("对准参数", "失配无量纲量", "复场重叠"),
            "模式失配": ("模式参数", "尺寸 / 曲率失配", "复场重叠"),
            "波前质量": ("波前特征", "波前误差 / Strehl", "焦面复场"),
            "成像质量": ("成像特征", "PSF / MTF", "焦面复场"),
        }
        source, middle, output = paths.get(category, ("模型特征", "内部物理量", "模型输出"))
        return f"{source} → {category} · {item} → {middle} → {output} → {target_label}", output

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

        from frontend_pyside.features.explainability.actions import formula_binding_for_feature, formula_latex
        from frontend_pyside.features.explainability.formula_presentation import formula_html

        self._clear_chain_rows()
        selected_keys = self._selected_feature_keys()
        self.chain_panel.setVisible(self._param_view == 1)
        if not selected_keys:
            self.chain_title.setText("物理链路")
            return

        self.chain_title.setText(f"物理链路（已选择 {len(selected_keys)} 个参数）")
        feature_names = [self._feature_label(feature) for feature in selected_keys]
        formula_steps: list[tuple[str, str]] = []
        seen_steps: set[tuple[str, str]] = set()
        for feature in selected_keys:
            category, item, _level, _note = formula_binding_for_feature(feature)
            step = (str(category), str(item))
            if category and item and step not in seen_steps:
                seen_steps.add(step)
                formula_steps.append(step)

        # All selected optical factors ultimately enter the same overlap
        # calculation. Add that downstream node once so the display is a
        # formula chain rather than several independent copies of one formula.
        output_step = ("总耦合效率", "复场重叠")
        if output_step not in seen_steps:
            formula_steps.append(output_step)

        if not formula_steps:
            row = QLabel(
                f"<b>输入参数：{escape('、'.join(feature_names))}</b><br>"
                f"<span style='color:#155EEF; font-size:16px;'>参数输入 → {escape(self._target_label)}</span>"
            )
            row.setObjectName("ExplainChainRow")
            row.setWordWrap(True)
            row.setTextFormat(Qt.TextFormat.RichText)
            self.chain_rows.addWidget(row)
            return

        path = "参数输入 → " + " → ".join(
            f"{category} · {item}" for category, item in formula_steps
        ) + f" → {self._target_label}"
        for index, (category, item) in enumerate(formula_steps, start=1):
            if index > 1:
                arrow = QLabel("↓")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setObjectName("ExplainChainArrow")
                self.chain_rows.addWidget(arrow)
            formula = formula_html(category, item, formula_latex(category, item))
            lead = (
                f"<b>输入参数：{escape('、'.join(feature_names))}</b><br>"
                f"<span style='color:#155EEF; font-size:16px;'>{escape(path)}</span><br>"
                if index == 1
                else ""
            )
            row = QLabel(
                f"{lead}<b>公式 {index}：{escape(category)} · {escape(item)}</b>{formula}"
            )
            row.setObjectName("ExplainChainRow")
            row.setWordWrap(True)
            row.setTextFormat(Qt.TextFormat.RichText)
            self.chain_rows.addWidget(row)

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

        def show_analysis(feature: str, importance: float, direction: str, *, verified: bool = False) -> None:
            self._set_feature_summary(
                feature,
                importance,
                direction,
                verified=verified,
                target_unit=target_unit,
            )

        items = list(body.get("top_features") or body.get("feature_contributions") or body.get("global_importance") or [])
        if self.kind == "param_trend":
            if not items:
                self._show("物理链路", "这次解释没有返回可用的 SHAP 参数排名。")
                return
            selected_feature = self.selected or str(items[0].get("feature") or items[0].get("name") or "")
            item = shap_dependence_item(body, selected_feature)
            if not item and selected_feature:
                for feature, data in dict(body.get("shap_dependence") or {}).items():
                    if _shap_feature_key(str(feature), [selected_feature]) == selected_feature:
                        item = dict(data)
                        break
            xs = list(item.get("feature_value") or item.get("x") or []) if item else []
            ys = list(item.get("shap_value") or item.get("y") or []) if item else []
            if xs and ys:
                self.workspace.set_result(
                    0,
                    "辅助：单参数 SHAP 依赖",
                    {
                        "kind": "scatter",
                        "x": xs,
                        "y": ys,
                        "x_label": _design_short_label(selected_feature),
                        "y_label": f"SHAP（{target_unit}）" if target_unit else "SHAP",
                        "zero_line": True,
                    },
                )
            else:
                self.workspace.set_result(
                    0,
                    "物理链路",
                    {"kind": "empty", "message": "已生成物理链路；当前没有返回该参数的单参数依赖曲线。"},
                )
            self._populate_feature_picker(items, feature_label)
            return
        if self.kind == "current_system":
            targets = list(body.get("targets") or [])
            sample = {}
            if targets:
                rows = list(targets[0].get("sample_shap_values") or [])
                sample = dict(rows[0]) if rows else {}
            values = sample.get("shap_values") or sample.get("values") or {}
            if not isinstance(values, dict) or not values:
                contrib = list(body.get("feature_contributions") or body.get("top_features") or [])
                labels = [label_of(item.get("feature")) for item in contrib]
                shap_values = [float(item.get("shap_value", item.get("mean_shap", 0.0)) or 0.0) for item in contrib]
            else:
                labels = [label_of(name) for name in values]
                shap_values = [float(values[name] or 0.0) for name in values]
            if not labels:
                self._show("当前系统瀑布图", "这次解释没有返回当前样本的贡献。")
                return
            additivity_error = sample.get("additivity_error", body.get("additivity_error"))
            prediction = sample.get("prediction")
            if additivity_error is not None:
                tolerance = 1.0e-6 * max(1.0, abs(float(prediction or 0.0)))
                if abs(float(additivity_error)) > tolerance:
                    self._show(
                        "当前系统瀑布图",
                        f"SHAP贡献无法闭合当前预测（加性误差 {float(additivity_error):.4g}），已停止绘图。",
                    )
                    self._set_summary_sections(
                        "解释结果无效：基准值与各变量贡献之和不等于模型预测值。",
                        "当前没有可用的物理联系。",
                        "请检查模型特征与当前镜头组是否匹配后重试。",
                    )
                    return
            self.workspace.set_result(
                0,
                "当前系统瀑布图",
                {
                    "kind": "waterfall",
                    "labels": [_design_short_label(label) for label in (values.keys() if isinstance(values, dict) and values else labels)],
                    "values": shap_values,
                    "base_value": float((body.get("base_values") or {}).get(str(body.get("target_name") or ""), 0.0) or 0.0),
                    "summary": f"目标：{target_label}",
                    "legend_loc": "lower right",
                    "value_labels_right": True,
                },
            )
            top_index = max(range(len(shap_values)), key=lambda index: abs(shap_values[index]))
            raw_features = list(values.keys()) if isinstance(values, dict) and values else labels
            top_feature = str(raw_features[top_index])
            if top_feature == "__other_model_features__":
                self._set_summary_sections(
                    "当前样本主要受内部物理特征的合并贡献影响，不能直接当作一个可调整参数。",
                    "这些量由设计变量和正式光学计算共同产生，当前没有可靠的一对一闭式公式。",
                    "返回贡献排序或物理链路，选择曲率半径、厚度或圆锥系数继续验证。",
                )
            else:
                formal_result = getattr(getattr(self.context, "project", None), "formal_result", None)
                show_analysis(
                    top_feature,
                    abs(shap_values[top_index]),
                    "该变量在当前样本中提高模型输出。" if shap_values[top_index] >= 0 else "该变量在当前样本中降低模型输出。",
                    verified=isinstance(formal_result, dict) and bool(formal_result),
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
