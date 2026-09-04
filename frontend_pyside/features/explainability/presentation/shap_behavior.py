from __future__ import annotations

from math import sqrt
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared import layout_tokens as ui_layout
from frontend_pyside.shared.icons import icon
from frontend_pyside.features.explainability.actions import (
    build_structured_report_html,
    feature_display_name,
    formula_binding_for_feature,
    formula_latex,
    physical_mechanism_for_feature,
    physical_mismatch_category,
    physical_category_totals,
    diagnosis_confidence,
    suggested_action_for_feature,
)
from frontend_pyside.shared.components.basic import (
    Card,
    CollapsiblePanel,
    FormGrid,
    InfoRow,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.foundation import PageHeader
from frontend_pyside.shared.components.workbench import MetricSummaryBar
from frontend_pyside.features.explainability.formula_presentation import formula_compact_text, formula_html
from frontend_pyside.shared.lazy_widgets import LazyTabWidget
from frontend_pyside.shared.dialogs.plot_actions import open_plot_data
from frontend_pyside.shared.feature_labels import is_unmapped_feature_name, is_adjustable_feature_name
from frontend_pyside.shared.display_names import metric_label


class _DeferredPlotSlot:


    def __init__(self, title: str, workspace_factory) -> None:
        self.title = str(title)
        self.workspace_factory = workspace_factory
        self.container: QStackedWidget | None = None
        self.placeholder: QLabel | None = None
        self.workspace = None
        self.pending: tuple[int, str, dict] | None = None

    def attach(self, container: QStackedWidget, placeholder: QLabel) -> None:
        self.container = container
        self.placeholder = placeholder
        self._apply_pending()

    def set_result(self, index: int, title: str, payload: dict) -> None:
        self.pending = (int(index), str(title), dict(payload or {}))
        self._apply_pending()

    def _ensure_workspace(self):
        if self.workspace is None:
            self.workspace = self.workspace_factory()
            if self.container is not None:
                self.container.addWidget(self.workspace)
        return self.workspace

    def _apply_pending(self) -> None:
        if self.pending is None or self.container is None or self.placeholder is None:
            return
        index, title, payload = self.pending
        if str(payload.get("kind", "empty")) == "empty":
            self.placeholder.setText(str(payload.get("message", "等待分析结果")))
            self.container.setCurrentWidget(self.placeholder)
            return
        workspace = self._ensure_workspace()
        workspace.set_result(index, title, payload)
        self.container.setCurrentWidget(workspace)


class ExplainabilityShapMixin:


    def _shap(self) -> QWidget:
        page = QScrollArea()
        page.setObjectName("shapAnalysisScroll")
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setMaximumWidth(ui_layout.MAX_CONTENT_WIDTH)
        page.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, ui_layout.CARD_GAP)
        root.setSpacing(ui_layout.CARD_GAP)

        root.addWidget(PageHeader("模型解释（SHAP）", "SHAP 只给出模型中的候选因素；解析公式、正式扫描与适用范围共同完成物理核验。"))
        control = Card("分析设置", compact=True)
        method_label = QLabel("模型解释方法：SHAP")
        method_label.setObjectName("mutedText")
        control.body.addWidget(method_label)
        self.shap_metric_bar = MetricSummaryBar(
            [("候选因素", "—"), ("预测可靠性", "—"), ("物理核验", "—")]
        )
        self.shap_metric_bar.hide()
        control.body.addWidget(self.shap_metric_bar)

        self.shap_sample = QComboBox()
        self.shap_sample.addItems(["当前系统", "高贡献样本", "边界样本"])
        self.shap_sample.currentIndexChanged.connect(self._sample_selection_changed)
        for combo in (self.model, self.dataset, self.output, self.shap_sample):
            combo.setMinimumWidth(120)
            combo.setMaximumWidth(230)
        settings_form = FormGrid(label_width=120)
        settings_form.add_row("当前模型", self.model, "解释始终绑定这个模型版本")
        settings_form.add_row("对应数据", self.dataset, "应与模型训练数据一致")
        settings_form.add_row("解释对象", self.shap_sample, "当前系统或数据集中的代表样本")
        control.body.addWidget(settings_form)
        self.shap_start_btn = PrimaryButton("开始分析")
        self.shap_start_btn.clicked.connect(self._request_explain)
        settings_actions = QHBoxLayout()
        settings_actions.addStretch(1)
        settings_actions.addWidget(self.shap_start_btn)
        control.body.addLayout(settings_actions)
        self.shap_report_button = SecondaryButton("报告")
        self.shap_report_button.hide()
        self.shap_report_button.clicked.connect(lambda: self._set_main_step(1))
        self.shap_popout_button = SecondaryButton("独立窗口查看")
        self.shap_popout_button.setIcon(icon("popout", theme.TEXT_SECONDARY, 17))
        self.shap_popout_button.setEnabled(False)
        self.shap_popout_button.setToolTip("在独立科研图窗中查看当前 SHAP 图")
        self.shap_popout_button.clicked.connect(self._popout_current_shap)

        self.shap_group_mode = QComboBox(); self.shap_group_mode.addItems(["按物理类别", "按原始参数"])
        self.shap_group_mode.currentIndexChanged.connect(self._group_mode_changed)
        self.shap_topn = QSpinBox(); self.shap_topn.setRange(3, 30); self.shap_topn.setValue(8)
        self.shap_topn.valueChanged.connect(lambda _value: self._rerender_current_shap())
        self.shap_scope = QComboBox(); self.shap_scope.addItems(["全局 + 当前系统", "仅全局", "当前系统"])
        self.shap_background = QSpinBox(); self.shap_background.setRange(20, 2000); self.shap_background.setValue(200)
        advanced = CollapsiblePanel("分析设置", expanded=False)
        advanced_form = QFormLayout(); advanced_form.setVerticalSpacing(5)
        advanced_form.addRow("输出", self.output)
        advanced_form.addRow("分组", self.shap_group_mode)
        advanced_form.addRow("显示数量", self.shap_topn)
        advanced_form.addRow("范围", self.shap_scope)
        advanced_form.addRow("背景样本", self.shap_background)
        advanced.content_layout.addLayout(advanced_form)
        self._show_all_features = False
        self.feature_list = QListWidget()
        self.feature_list.setObjectName("weightedFeatureList")
        self.feature_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feature_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feature_list.currentItemChanged.connect(self._feature_selected)
        control.body.addWidget(advanced)
        root.addWidget(control)
        self.shap_empty_card = Card("还不能开始解释", compact=True)
        self.shap_empty_hint = QLabel(
            "先准备一个测试结果足够可靠的模型和它对应的数据。完成后，这里会用同一个主图位置依次查看主要因素、当前系统、整体规律和单参数规律。"
        )
        self.shap_empty_hint.setObjectName("emptyHint")
        self.shap_empty_hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.shap_empty_hint.setWordWrap(True)
        self.shap_empty_hint.setMinimumHeight(58)
        self.shap_empty_card.body.addWidget(self.shap_empty_hint)
        empty_actions = QHBoxLayout()
        empty_actions.addStretch(1)
        self.shap_prepare_button = SecondaryButton("去准备模型和数据")
        self.shap_prepare_button.setToolTip("打开模型分析中的训练与版本区域，不会自动开始训练")
        self.shap_prepare_button.clicked.connect(self._prepare_model_data_for_shap)
        empty_actions.addWidget(self.shap_prepare_button)
        self.shap_empty_card.body.addLayout(empty_actions)
        root.addWidget(self.shap_empty_card)
        self.shap_mapping_warning = QLabel("")
        self.shap_mapping_warning.setObjectName("warningBanner")
        self.shap_mapping_warning.setWordWrap(True)
        self.shap_mapping_warning.hide()
        root.addWidget(self.shap_mapping_warning)

        # 具体参数属于分析内容，不放进“分析设置”的小滚动框。默认 Top 5，展开后随整页自然向下。
        self.feature_panel = CollapsiblePanel("具体参数 · Top 5", expanded=True)
        self.feature_panel.content_layout.addWidget(self.feature_list)
        feature_actions = QHBoxLayout()
        feature_actions.addStretch(1)
        self.feature_expand_button = SecondaryButton("展开全部因素")
        self.feature_expand_button.clicked.connect(self._toggle_all_features)
        feature_actions.addWidget(self.feature_expand_button)
        self.feature_panel.content_layout.addLayout(feature_actions)
        self.feature_panel.hide()
        root.addWidget(self.feature_panel)

        # 统一成与模型分析相同的单主图工作区。用户只需要记住：
        # “上方切视图，中间看主图，下方选参数/看物理依据”。
        self.plot_tabs = None  # 兼容旧接口；当前视图由 _selected_shap_section 记录。
        self._selected_shap_section = "主要因素"
        self.plot_workspaces: dict[str, _DeferredPlotSlot] = {}
        shap_views = ("主要因素", "当前系统", "整体参数规律", "单参数规律")
        for title in shap_views:
            slot = _DeferredPlotSlot(title, lambda current_title=title: self._create_plot_workspace(current_title))
            message = (
                "准备好后点“开始分析”。\n\n"
                "分析完成后，这个位置可以依次查看：\n"
                "• 主要因素：先看哪类问题最明显\n"
                "• 当前系统：看哪些参数在推高或拉低结果\n"
                "• 整体规律：看所有样本中的总体规律\n"
                "• 单参数规律：再看某一个参数怎样影响结果"
                if title == "主要因素" else "完成分析后可查看这个结果。"
            )
            slot.set_result(0, title, {"kind": "empty", "message": message})
            self.plot_workspaces[title] = slot

        self.shap_view_card = Card("解释视图", compact=True)
        self.shap_view_tabs = QTabWidget()
        self.shap_view_tabs.setDocumentMode(True)
        self.shap_view_tabs.setMinimumHeight(ui_layout.PLOT_MIN_HEIGHT + 30)
        self.shap_view_tabs.setMaximumHeight(ui_layout.PLOT_PREFERRED_HEIGHT + 40)
        for title, tab_label in (("主要因素", "主要因素"), ("当前系统", "当前系统"), ("整体参数规律", "整体规律"), ("单参数规律", "单参数规律")):
            self.shap_view_tabs.addTab(self._build_plot_workspace(title), tab_label)
        self.shap_view_tabs.setTabVisible(2, False)
        self.shap_view_tabs.setTabVisible(3, False)
        self.shap_view_tabs.currentChanged.connect(self._shap_view_tab_changed)

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(5)
        self.study_feature_button = SecondaryButton("研究这个参数")
        self.study_feature_button.setEnabled(False)
        self.study_feature_button.setToolTip("带着当前参数进入参数研究并预填设置，不会自动启动计算")
        self.study_feature_button.clicked.connect(self._prepare_selected_feature_scan)
        corner_layout.addWidget(self.study_feature_button)
        self.shap_view_popout = QToolButton()
        self.shap_view_popout.setObjectName("plotIconTool")
        self.shap_view_popout.setIcon(icon("popout", theme.TEXT_SECONDARY, 17))
        self.shap_view_popout.setIconSize(QSize(17, 17))
        self.shap_view_popout.setToolTip("弹出当前图")
        self.shap_view_popout.clicked.connect(self._popout_current_shap)
        corner_layout.addWidget(self.shap_view_popout)
        self.shap_view_tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        self.shap_view_card.body.addWidget(self.shap_view_tabs)
        self.shap_provenance = QLabel("结果来源：等待分析")
        self.shap_provenance.setObjectName("helperText")
        self.shap_provenance.setWordWrap(True)
        self.shap_view_card.body.addWidget(self.shap_provenance)
        self.shap_view_card.hide()
        root.addWidget(self.shap_view_card)
        self.shap_work = self.plot_workspaces["主要因素"]

        # 具体参数仍是解释链的一部分，但不再夹在多张大图之间。
        root.addWidget(self.feature_panel)

        result_actions = QHBoxLayout()
        result_actions.addStretch(1)
        result_actions.addWidget(self.shap_popout_button)
        result_actions.addWidget(self.shap_report_button)
        root.addLayout(result_actions)

        linkage = CollapsiblePanel("物理核验：SHAP × 解析公式 × 正式仿真", expanded=True)
        self.shap_linkage_card = linkage
        linkage.setVisible(False)
        self.physics_rows = {
            "feature": InfoRow("当前参数", "请选择参数"),
            "raw": InfoRow("当前值", "—"),
            "formula": InfoRow("公式", "—"),
            "shap": InfoRow("SHAP 贡献", "—"),
            "formula_contribution": InfoRow("公式对照", "—"),
            "residual": InfoRow("趋势差异", "—"),
            "mechanism": InfoRow("物理关系", "—"),
            "action": InfoRow("下一步", "—"),
        }
        for key in ("feature", "formula", "shap", "mechanism"):
            linkage.content_layout.addWidget(self.physics_rows[key])
        root.addWidget(linkage)

        compatibility = QWidget(page); compatibility.hide()
        self.shap_status_info = InfoRow("状态", "请选择模型和数据集")
        self.shap_source_info = InfoRow("数据来源", "等待分析")
        self.linkage_consistency = InfoRow("趋势一致性", "—")
        self.mismatch_rows = [InfoRow("1", "等待分析"), InfoRow("2", "—"), InfoRow("3", "—")]
        self.adjustment_rows = [InfoRow("建议 1", "—"), InfoRow("建议 2", "—"), InfoRow("建议 3", "—")]
        self.evidence_rows = {
            "evidence": InfoRow("依据", "—"),
            "confidence": InfoRow("预测可靠性", "—"),
            "boundary": InfoRow("完整仿真", "—"),
        }
        for widget in [
            self.shap_status_info, self.shap_source_info, self.linkage_consistency,
            *self.mismatch_rows, *self.adjustment_rows, *self.evidence_rows.values(),
            self.physics_rows["raw"], self.physics_rows["formula_contribution"], self.physics_rows["residual"],
        ]:
            widget.setParent(compatibility)
        self.shap_diagnosis = compatibility
        self.adjustment_card = compatibility
        self.dominant_rows = [InfoRow("", "") for _ in range(5)]
        self.quality_rows = {key: InfoRow("", "") for key in ("coverage", "additivity", "anomaly", "consistency", "mapping")}
        for widget in [*self.dominant_rows, *self.quality_rows.values()]:
            widget.setParent(compatibility)
        self.anomaly_button = SecondaryButton("高贡献样本")
        self.anomaly_button.clicked.connect(self._show_anomaly_samples)
        self.anomaly_button.setParent(compatibility)
        self.dominant_card = compatibility
        self.quality_card = compatibility
        self.physics_card = compatibility
        root.addStretch(1)
        page.setWidget(content)
        self.shap_scroll = page
        try:
            self.workspace_state.restore_scroll("analysis", page, 0)
        except Exception:
            pass
        return page


    def _prepare_model_data_for_shap(self) -> None:
        """Bring the user to the model/data workflow without starting training."""
        signal = getattr(self, "assistantActionRequested", None)
        if signal is not None:
            signal.emit({
                "label": "去准备模型和数据",
                "target": "machine_learning.training",
                "level": "prepare",
            })
            return
        # Fallback for isolated page tests where the main-window action router is absent.
        self.navigateRequested.emit("machine_learning")

    def _apply_shap_responsive_layout(self, compact: bool) -> None:
        if compact and hasattr(self, "shap_linkage_card") and self.shap_linkage_card.toggle.isChecked():
            self.shap_linkage_card.set_expanded(False)

    def _popout_shap_section(self, title: str) -> None:
        self._selected_shap_section = str(title)
        slot = self.plot_workspaces.get(str(title)) if hasattr(self, "plot_workspaces") else None
        pending = getattr(slot, "pending", None) if slot is not None else None
        if not pending:
            return
        _plot_index, plot_title, payload = pending
        open_plot_data(self, plot_title, payload, allow_follow=False)

    def _popout_current_shap(self) -> None:
        self._popout_shap_section(getattr(self, "_selected_shap_section", "主要因素"))

    def _build_plot_workspace(self, title: str) -> QWidget:
        container = QStackedWidget()
        placeholder = QLabel("等待分析结果")
        placeholder.setObjectName("compactEmptyState")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setMinimumHeight(110)
        container.addWidget(placeholder)
        self.plot_workspaces[title].attach(container, placeholder)
        return container

    def _create_plot_workspace(self, _title: str):
        from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace

        workspace = ResultWorkspace()
        workspace.set_single_view_only(True)
        workspace.set_toolbar_visible(False)
        workspace.set_maximize_controls_visible(False)
        # 模块/Tab 已经承担标题语义，主图内部不再重复同名标题或“预览”标签。
        workspace.set_pane_title_visible(False)
        workspace.set_pane_source_visible(False)
        workspace.itemSelected.connect(self._select_feature_by_name)
        return workspace

    def _update_shap_from_api(self, data: dict) -> None:

        self._shap_data = dict(data)
        if hasattr(self, "shap_provenance"):
            model_id = str(self.model.currentData() or self.model.currentText() or "—")
            dataset_id = str(self.dataset.currentData() or self.dataset.currentText() or "—")
            revision = int(getattr(self.context.project, "design_revision", 0) or 0)
            quality = getattr(self.context.registry, "current_model_record", None)
            record = quality if isinstance(quality, dict) else {}
            metrics = dict(record.get("test_metrics") or {})
            r2 = metrics.get("r2", metrics.get("r2_score"))
            r2_text = f" · 测试 R² {float(r2):.3f}" if isinstance(r2, (int, float)) else ""
            self.shap_provenance.setText(f"结果来源：模型 {model_id}{r2_text} · 数据 {dataset_id} · 系统 Rev.{revision}")
        if hasattr(self, "shap_linkage_card"):
            self.shap_linkage_card.setVisible(True)
        targets = list(data.get("targets", []) or [])
        first_target = targets[0] if targets and isinstance(targets[0], dict) else {}
        target_name = str(data.get("target_name") or first_target.get("target_name") or "模型输出")
        sample_count = int(
            data.get("sample_count", first_target.get("sample_count", 0)) or 0
        )
        background_count = int(
            data.get(
                "background_sample_count",
                first_target.get("background_sample_count", 0),
            )
            or 0
        )
        elapsed_ms = float(data.get("elapsed_ms", first_target.get("elapsed_ms", 0)) or 0)
        explainer = str(data.get("explainer", first_target.get("explainer", "SHAP")))

        top_features = list(
            data.get("top_features") or first_target.get("top_features") or []
        )
        enriched = list(
            data.get("feature_contributions")
            or first_target.get("feature_contributions")
            or []
        )
        global_importance = list(
            data.get("global_importance") or first_target.get("global_importance") or []
        )
        source_records = enriched or top_features or global_importance
        if not source_records:
            source_records = self._feature_records_from_samples(data)
            global_importance = list(source_records)
        self._feature_records = self._normalize_feature_records(
            source_records, top_features, global_importance
        )
        unmapped = [
            str(record.get("feature", "") or "")
            for record in self._feature_records
            if is_unmapped_feature_name(record.get("feature", ""))
            or str(record.get("display_name", "") or "").startswith("未登记特征")
        ]
        if hasattr(self, "shap_mapping_warning"):
            if unmapped:
                preview = "、".join(item or "<空字段>" for item in unmapped[:4])
                suffix = f" 等 {len(unmapped)} 个" if len(unmapped) > 4 else ""
                self.shap_mapping_warning.setText(
                    f"⚠ 发现未登记特征：{preview}{suffix}。这些字段不会被伪装成‘未命名参数’，请先检查数据集字段映射后再用于解释或优化。"
                )
                self.shap_mapping_warning.show()
            else:
                self.shap_mapping_warning.hide()
        self._local_shap_by_feature = self._selected_local_sample_values(data)
        has_result = bool(self._feature_records)
        if hasattr(self, "shap_empty_card"):
            self.shap_empty_card.setVisible(not has_result)
        if hasattr(self, "shap_empty_hint") and not has_result:
            self.shap_empty_hint.setText("这次分析没有得到可用的影响因素。请先检查当前模型和数据是否对应，再重新分析。")
        if hasattr(self, "shap_metric_bar"):
            self.shap_metric_bar.setVisible(has_result)
        if hasattr(self, "shap_report_button"):
            self.shap_report_button.setVisible(has_result)
        if hasattr(self, "shap_popout_button"):
            self.shap_popout_button.setEnabled(has_result)
        if hasattr(self, "feature_panel"):
            self.feature_panel.setVisible(has_result)
        if hasattr(self, "shap_view_card"):
            self.shap_view_card.setVisible(has_result)
        if hasattr(self, "shap_view_tabs"):
            self.shap_view_tabs.setTabVisible(0, True)
            self.shap_view_tabs.setTabVisible(1, has_result)
            if not has_result:
                self.shap_view_tabs.setTabVisible(2, False)
                self.shap_view_tabs.setTabVisible(3, False)

        self._set_info(
            self.shap_status_info,
            "当前状态",
            f"已解释 {sample_count} 个真实样本（{elapsed_ms:.1f} ms）",
        )
        self._set_info(
            self.shap_source_info,
            "计算来源",
            f"后端 {explainer} · 背景样本 {background_count}",
        )

        category_rows = physical_category_totals(self._feature_records)
        dominant_category = str(category_rows[0]["category"]) if category_rows else "—"
        confidence, confidence_note = diagnosis_confidence(data)
        selected_row = self._selected_sample_row(data)
        formal_value = selected_row.get("formal_value", selected_row.get("actual", selected_row.get("target_value")))
        formal_reviewed = isinstance(formal_value, (int, float))
        self.shap_metric_bar.set_items(
            [
                ("候选因素", dominant_category),
                ("预测可靠性", confidence),
                ("完整仿真", "已完成" if formal_reviewed else "待计算"),
            ]
        )
        self._update_physical_diagnosis(category_rows, confidence, confidence_note, formal_reviewed)

        
        
        mapping_levels = [
            formula_binding_for_feature(str(record.get("feature", "")))[2]
            for record in self._feature_records
        ]
        mapped = sum(level != "未映射" for level in mapping_levels)
        direct = sum(level == "直接" for level in mapping_levels)
        additivity = data.get("additivity_error")
        warnings = list(data.get("warnings", []) or [])
        anomaly_count = data.get("anomaly_sample_count")
        self._set_info(self.quality_rows["coverage"], "公式映射", f"直接 {direct} / 间接 {mapped - direct} / 总计 {len(self._feature_records)}")
        self._set_info(self.quality_rows["additivity"], "加性误差", f"{float(additivity):.6g}" if isinstance(additivity, (int, float)) else "未返回")
        self._set_info(self.quality_rows["anomaly"], "高贡献样本", str(int(anomaly_count)) if isinstance(anomaly_count, (int, float)) else (f"警告 {len(warnings)} 项" if warnings else "未返回"))

        self._populate_feature_list()
        self._update_dominant_rows()
        self._render_shap_plots(data, target_name, explainer)
        if self.feature_list.count():
            self.feature_list.setCurrentRow(0)

        if hasattr(self, "report_editor"):
            self.report_editor.setHtml(build_structured_report_html(data, self._report_options))

    @staticmethod
    def _category_action(category: str) -> str:
        return {
            "中心位置失配": "微调光纤 X/Y 或双镜指向，使光斑中心重新落在纤芯中心。",
            "尺寸失配": "调整输入束径、扩束倍率或末级焦距，使 X/Y 尺寸比接近 1。",
            "焦面与曲率失配": "优先扫描光纤 Z，再检查空气间隔、透镜曲率和端面波前。",
            "椭圆与像散失配": "调整柱面镜间距/方向，并比较 X、Y 束腰位置。",
            "角度与波前失配": "调整反射镜或五轴架角度，同时用 X/Y 补偿中心走离。",
            "光束结构与像差": "查看端面匹配、波前和 PSF，必要时更换透镜或收紧孔径。",
        }.get(str(category), "运行正式参数扫描并比较端面复场变化。")

    def _update_physical_diagnosis(self, rows: list[dict], confidence: str, confidence_note: str, formal_reviewed: bool = False) -> None:
        maximum = max((float(row.get("value", 0.0) or 0.0) for row in rows), default=1.0) or 1.0
        for index in range(3):
            if index < len(rows):
                row = rows[index]
                category = str(row.get("category", "—"))
                ratio = float(row.get("value", 0.0) or 0.0) / maximum
                level = "主要" if ratio >= 0.72 else ("次要" if ratio >= 0.35 else "轻微")
                self._set_info(self.mismatch_rows[index], str(index + 1), f"{category} · {level}")
                self._set_info(self.adjustment_rows[index], ("第一步", "第二步", "第三步")[index], self._category_action(category))
            else:
                self._set_info(self.mismatch_rows[index], str(index + 1), "—")
                self._set_info(self.adjustment_rows[index], ("第一步", "第二步", "第三步")[index], "—")
        evidence = "；".join(
            f"{str(row.get('category', '—'))}关联 {len(list(row.get('features', []) or []))} 个原始参数"
            for row in rows[:3]
        ) or "等待真实 SHAP 与正式光学结果"
        self._set_info(self.evidence_rows["evidence"], "物理依据", evidence)
        self._set_info(self.evidence_rows["confidence"], "预测可靠性", confidence)
        self.evidence_rows["confidence"].setToolTip(str(confidence_note or ""))
        self._set_info(self.evidence_rows["boundary"], "完整仿真", "已完成" if formal_reviewed else "待计算")

    def _group_mode_changed(self, _index: int) -> None:
        self._populate_feature_list()
        self._rerender_current_shap()

    def _rerender_current_shap(self) -> None:
        data = getattr(self, "_shap_data", None)
        if not isinstance(data, dict) or not data:
            return
        targets = list(data.get("targets", []) or [])
        first_target = targets[0] if targets and isinstance(targets[0], dict) else {}
        target_name = str(data.get("target_name") or first_target.get("target_name") or "模型输出")
        self._render_shap_plots(data, target_name, str(data.get("explainer", "SHAP")))

    def _use_physical_grouping(self) -> bool:
        return not hasattr(self, "shap_group_mode") or self.shap_group_mode.currentIndex() == 0

    def _feature_records_from_samples(self, data: dict) -> list[dict]:
        rows = self._sample_rows(data)
        by_feature: dict[str, list[float]] = {}
        for row in rows:
            for feature, value in self._value_map(row, "shap_values", "values").items():
                by_feature.setdefault(feature, []).append(float(value))
        records: list[dict] = []
        for feature, values in by_feature.items():
            if not values:
                continue
            records.append(
                {
                    "feature": feature,
                    "mean_shap": float(sum(values) / len(values)),
                    "mean_abs_shap": float(sum(abs(value) for value in values) / len(values)),
                }
            )
        records.sort(key=lambda item: float(item["mean_abs_shap"]), reverse=True)
        return records

    def _normalize_feature_records(
        self,
        records: list[dict],
        top_features: list[dict],
        global_importance: list[dict],
    ) -> list[dict]:
        top_by_name = {
            str(item.get("feature", item.get("name", ""))): item
            for item in top_features
        }
        global_by_name = {
            str(item.get("feature", item.get("name", ""))): item
            for item in global_importance
        }
        normalized: list[dict] = []
        for index, raw in enumerate(records):
            record = dict(raw)
            feature = str(record.get("feature", record.get("name", f"feature_{index}")))
            top = top_by_name.get(feature, {})
            global_item = global_by_name.get(feature, {})
            record["feature"] = feature
            record["display_name"] = str(
                record.get("display_name")
                or feature_display_name(feature)
                or record.get("name")
                or feature
            )
            if "mean_shap" not in record and "shap_value" in record:
                record["mean_shap"] = record.get("shap_value")
            if "mean_abs_shap" not in record:
                record["mean_abs_shap"] = global_item.get(
                    "mean_abs_shap",
                    record.get(
                        "abs_shap_value",
                        abs(float(record.get("mean_shap", 0.0) or 0.0)),
                    ),
                )
            if "sample_value" not in record:
                record["sample_value"] = record.get(
                    "value", top.get("sample_value", global_item.get("sample_value"))
                )
            normalized.append(record)
        normalized.sort(
            key=lambda item: float(item.get("mean_abs_shap", 0.0) or 0.0),
            reverse=True,
        )
        return normalized

    @staticmethod
    def _sample_rows(data: dict) -> list[dict]:
        targets = list(data.get("targets", []) or [])
        if not targets or not isinstance(targets[0], dict):
            return []
        return [
            dict(row)
            for row in list(targets[0].get("sample_shap_values", []) or [])
            if isinstance(row, dict)
        ]

    @staticmethod
    def _value_map(row: dict, primary: str, compatibility: str = "") -> dict[str, float]:
        raw = row.get(primary)
        if not isinstance(raw, dict) and compatibility:
            raw = row.get(compatibility)
        if not isinstance(raw, dict):
            return {}
        values: dict[str, float] = {}
        for name, value in raw.items():
            try:
                values[str(name)] = float(value)
            except (TypeError, ValueError):
                continue
        return values

    def _selected_sample_row(self, data: dict) -> dict:
        rows = self._sample_rows(data)
        if not rows:
            return {}
        mode = self.shap_sample.currentIndex() if hasattr(self, "shap_sample") else 0
        totals = [
            sum(abs(value) for value in self._value_map(row, "shap_values", "values").values())
            for row in rows
        ]
        if mode == 1:
            return rows[max(range(len(rows)), key=lambda index: totals[index])]
        if mode == 2:
            margin_candidates: list[tuple[float, int]] = []
            for index, row in enumerate(rows):
                margin = row.get("prediction_margin", row.get("margin"))
                if isinstance(margin, (int, float)):
                    margin_candidates.append((abs(float(margin)), index))
            if margin_candidates:
                return rows[min(margin_candidates)[1]]
            ordered = sorted(totals)
            median = ordered[len(ordered) // 2]
            return rows[min(range(len(rows)), key=lambda index: abs(totals[index] - median))]
        return rows[0]

    def _selected_local_sample_values(self, data: dict) -> dict[str, float]:
        return self._value_map(self._selected_sample_row(data), "shap_values", "values")

    def _sample_selection_changed(self, _index: int) -> None:
        data = getattr(self, "_shap_data", None)
        if not isinstance(data, dict) or not data:
            return
        self._local_shap_by_feature = self._selected_local_sample_values(data)
        targets = list(data.get("targets", []) or [])
        first_target = targets[0] if targets and isinstance(targets[0], dict) else {}
        target_name = str(data.get("target_name") or first_target.get("target_name") or "模型输出")
        self._render_shap_plots(data, target_name, str(data.get("explainer", "SHAP")))
        current = self.feature_list.currentItem()
        if current is not None:
            self._feature_selected(current)

    def _toggle_all_features(self) -> None:
        self._show_all_features = not bool(getattr(self, "_show_all_features", False))
        self.feature_expand_button.setText("收起到 Top 5" if self._show_all_features else "展开全部因素")
        self._populate_feature_list()

    def _populate_feature_list(self) -> None:
        self.feature_list.clear()
        values = [float(item.get("mean_abs_shap", 0.0) or 0.0) for item in self._feature_records]
        maximum = max(values, default=1.0) or 1.0
        records = list(enumerate(self._feature_records))
        if not getattr(self, "_show_all_features", False):
            records = records[:5]

        # First show the physical problem, then the concrete parameter.  Category rows are headers, not selectable results.
        groups: dict[str, list[tuple[int, dict]]] = {}
        order: list[str] = []
        for index, record in records:
            category = physical_mismatch_category(str(record.get("feature", "")))
            if category not in groups:
                groups[category] = []; order.append(category)
            groups[category].append((index, record))

        for category in order:
            header = QListWidgetItem(f"▾ {category}")
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header.setForeground(QBrush(QColor("#1D4ED8")))
            font = header.font(); font.setBold(True); header.setFont(font)
            self.feature_list.addItem(header)
            for index, record in groups[category]:
                name = str(record.get("display_name", record.get("feature", f"特征 {index + 1}")))
                weight = float(record.get("mean_abs_shap", 0.0) or 0.0) / maximum
                mean_shap = float(record.get("mean_shap", 0.0) or 0.0)
                # Length/value are the primary encoding; color is secondary and high-contrast.
                bar = "█" * max(1, min(12, round(weight * 12)))
                item = QListWidgetItem(f"    {name:<22} {bar}  {100.0 * weight:.0f}%")
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setForeground(QBrush(QColor(theme.TEXT_PRIMARY)))
                item.setToolTip(f"物理类别：{category}；全局平均贡献方向：{mean_shap:+.3g}。")
                self.feature_list.addItem(item)

        # No nested scrolling: height follows content and the page owns the only vertical scrollbar.
        rows = max(1, self.feature_list.count())
        # The whole SHAP page owns vertical scrolling.  Never clip expanded
        # factors inside a scroll-disabled mini list.
        self.feature_list.setFixedHeight(42 * rows + 10)
        if hasattr(self, "feature_panel"):
            total = len(self._feature_records)
            self.feature_panel.toggle.setText((f"具体参数 · 全部 {total}" if self._show_all_features else f"具体参数 · Top {min(5, total)}"))
            self.feature_expand_button.setVisible(total > 5)

    def _update_dominant_rows(self) -> None:
        maximum = max(
            (float(item.get("mean_abs_shap", 0.0) or 0.0) for item in self._feature_records),
            default=1.0,
        ) or 1.0
        for index in range(3):
            if index < len(self._feature_records):
                record = self._feature_records[index]
                name = str(record.get("display_name", record.get("feature", "—")))
                value = float(record.get("mean_abs_shap", 0.0) or 0.0)
                self._set_info(
                    self.dominant_rows[index],
                    str(index + 1),
                    f"{name} · {100.0 * value / maximum:.0f}%",
                )
            else:
                self._set_info(self.dominant_rows[index], str(index + 1), "—")

    def _render_shap_plots(self, data: dict, target_name: str, explainer: str) -> None:

        grouped = self._use_physical_grouping()
        category_rows = physical_category_totals(self._feature_records)
        sample_rows = self._sample_rows(data)
        sample_count = len(sample_rows)
        row = self._selected_sample_row(data)
        local_values_map = self._value_map(row, "shap_values", "values")
        self._local_shap_by_feature = local_values_map

        targets = list(data.get("targets", []) or [])
        first_target = targets[0] if targets and isinstance(targets[0], dict) else {}
        base_value = data.get(
            "base_value",
            data.get("expected_value", first_target.get("base_value", first_target.get("expected_value", 0.0))),
        )
        if isinstance(base_value, (list, tuple)):
            base_value = base_value[0] if base_value else 0.0
        try:
            base_value = float(base_value)
        except (TypeError, ValueError):
            base_value = 0.0
        formal_value = row.get("formal_value", row.get("actual", row.get("target_value")))
        if isinstance(formal_value, (list, tuple)):
            formal_value = formal_value[0] if formal_value else None
        formal_value = float(formal_value) if isinstance(formal_value, (int, float)) else None
        predicted_value = base_value + sum(float(value) for value in local_values_map.values())
        within_training_domain = data.get("within_training_domain", data.get("in_training_domain"))
        if within_training_domain is None:
            within_training_domain = first_target.get(
                "within_training_domain", first_target.get("in_training_domain")
            )

        
        local_category_rows = physical_category_totals(
            self._feature_records, local_values_map, absolute=False
        )
        local_by_category = {
            str(item.get("category", "")): float(item.get("value", 0.0) or 0.0)
            for item in local_category_rows
        }
        category_labels = [str(item.get("category", "—")) for item in category_rows]
        global_values = [float(item.get("value", 0.0) or 0.0) for item in category_rows]
        local_values = [local_by_category.get(label, 0.0) for label in category_labels]
        global_total = sum(global_values) or 1.0
        top_two_share = 100.0 * sum(global_values[:2]) / global_total
        dominant_category = category_labels[0] if category_labels else "—"
        review_text = (
            f"完整仿真偏差 {predicted_value - formal_value:+.3g}"
            if formal_value is not None
            else "完整仿真：待补充"
        )
        domain_text = (
            "在训练范围内" if within_training_domain is True
            else "超出训练范围" if within_training_domain is False
            else "训练范围未知"
        )
        self.plot_workspaces["主要因素"].set_result(
            0,
            "主要因素",
            {
                "kind": "mismatch_budget",
                "y_label": "物理失配类别",
                "labels": category_labels,
                "global_values": global_values,
                "local_values": local_values,
                "title": "",
                "x_label": "贡献占比 / %",
                "summary": (
                    f"候选类别：{dominant_category}   |   Top-2 全局贡献：{top_two_share:.0f}%"
                    f"   |   预测值：{predicted_value:.4g}   |   {review_text}   |   {domain_text}"
                ),
            }
            if category_rows
            else {"kind": "empty", "message": "尚无可聚合的物理失配结果。"},
        )

        
        global_y_label = "物理失配类别" if grouped else "原始参数"
        if grouped:
            labels = category_labels
            beeswarm_points: list[dict] = []
            for sample_index, sample in enumerate(sample_rows[:400]):
                shap_map = self._value_map(sample, "shap_values", "values")
                totals: dict[str, float] = {name: 0.0 for name in labels}
                for feature, value in shap_map.items():
                    category = physical_mismatch_category(feature)
                    if category in totals:
                        totals[category] += float(value)
                scale = max((abs(value) for value in totals.values()), default=1.0) or 1.0
                for category in labels:
                    value = totals.get(category, 0.0)
                    beeswarm_points.append({
                        "feature": category,
                        "value": value,
                        "sample_index": sample_index,
                        "feature_value": None,
                        "color": self._feature_value_color(0.5 + 0.5 * value / scale).name(),
                    })
            importance = global_values
            global_title = "参数整体影响规律 · 物理类别"
            global_description = "每个点为一个样本在该物理类别下的累计SHAP贡献；右侧细条表示平均绝对贡献。"
        else:
            labels = [str(item.get("display_name", item.get("feature", "—"))) for item in self._feature_records]
            beeswarm_points = self._beeswarm_points(data)
            importance = [float(item.get("mean_abs_shap", 0.0) or 0.0) for item in self._feature_records]
            global_title = "参数整体影响规律 · 原始参数"
            global_description = "纵轴按平均绝对SHAP排序；横轴保留贡献方向；颜色对应样本参数值。"
        top_global = min(10, len(labels))
        labels = labels[:top_global]
        importance = importance[:top_global]
        label_set = set(labels)
        beeswarm_points = [point for point in beeswarm_points if str(point.get("feature", "")) in label_set]
        has_rule_data = bool(beeswarm_points and sample_count >= 2)
        self.plot_workspaces["整体参数规律"].set_result(
            0,
            "整体参数规律",
            {
                "kind": "beeswarm",
                "y_label": global_y_label,
                "labels": labels,
                "points": beeswarm_points,
                "importance": importance,
                "sample_count": sample_count,
                "source": "真实 SHAP",
                "title": "",
                "x_label": "有符号 SHAP 贡献",
                "summary": global_description,
            }
            if has_rule_data
            else {"kind": "empty", "message": "样本级SHAP数据不足，无法绘制真实蜂群图。"},
        )
        if hasattr(self, "shap_view_tabs"):
            # 只有真实样本级 SHAP 数据存在时才出现规律视图。
            self.shap_view_tabs.setTabVisible(2, has_rule_data)
            self.shap_view_tabs.setTabVisible(3, has_rule_data)

        
        waterfall_y_label = "物理失配类别" if grouped else "原始参数"
        if grouped:
            selected_records = [
                (str(item["category"]), str(item["category"]), float(item["value"]))
                for item in local_category_rows
            ]
            waterfall_title = "当前系统的物理失配贡献"
        else:
            local_records: list[tuple[str, str, float]] = []
            for record in self._feature_records:
                feature = str(record.get("feature", ""))
                value = local_values_map.get(feature, record.get("shap_value"))
                if isinstance(value, (int, float)):
                    category = physical_mismatch_category(feature)
                    display = str(record.get("display_name", feature))
                    local_records.append((feature, f"{category}｜{display}", float(value)))
            local_records.sort(key=lambda item: abs(item[2]), reverse=True)
            topn = max(1, int(self.shap_topn.value()))
            selected_records = local_records[:topn]
            if len(local_records) > topn:
                selected_records.append(("__other__", "其他参数", sum(item[2] for item in local_records[topn:])))
            waterfall_title = "当前系统的原始参数贡献"

        sample_id = str(row.get("sample_id", row.get("id", self.shap_sample.currentText())))
        waterfall_values = [item[2] for item in selected_records]
        displayed_prediction = base_value + sum(waterfall_values)
        self.plot_workspaces["当前系统"].set_result(
            0,
            "当前系统",
            {
                "kind": "waterfall",
                "y_label": waterfall_y_label,
                "labels": [item[1] for item in selected_records],
                "values": waterfall_values,
                "base_value": base_value,
                "formal_value": formal_value,
                "prediction_value": displayed_prediction,
                "within_training_domain": within_training_domain,
                "title": "",
                "x_label": metric_label(target_name),
                "summary": (
                    f"模型平均基准 {base_value:.4g} → 当前预测 {displayed_prediction:.4g}"
                    + (f" · 正式仿真 {formal_value:.4g} · 误差 {displayed_prediction - formal_value:+.3g}" if formal_value is not None else " · 正式仿真待复核")
                ),
            }
            if selected_records
            else {"kind": "empty", "message": "当前样本没有SHAP值。"},
        )

    def _beeswarm_points(self, data: dict) -> list[dict[str, Any]]:
        local_rows = self._sample_rows(data)
        if not local_rows:
            return []
        feature_order = [str(item.get("feature", "")) for item in self._feature_records]
        display = {str(item.get("feature", "")): str(item.get("display_name", "")) for item in self._feature_records}
        ranges: dict[str, tuple[float, float]] = {}
        for feature in feature_order:
            values = [self._value_map(row, "feature_values").get(feature) for row in local_rows]
            numeric = [float(value) for value in values if isinstance(value, (int, float))]
            if numeric:
                ranges[feature] = (min(numeric), max(numeric))
        points: list[dict[str, Any]] = []
        for sample_index, row in enumerate(local_rows[:400]):
            shap_map = self._value_map(row, "shap_values", "values")
            feature_map = self._value_map(row, "feature_values")
            for feature in feature_order:
                if feature not in shap_map:
                    continue
                raw = feature_map.get(feature)
                if isinstance(raw, (int, float)) and feature in ranges:
                    low, high = ranges[feature]
                    normalized = (float(raw) - low) / (high - low or 1.0)
                    color = self._feature_value_color(normalized).name()
                else:
                    color = "#64748b"
                points.append({"feature": display.get(feature, feature), "value": float(shap_map[feature]), "sample_index": sample_index, "feature_value": raw, "color": color})
        return points

    @staticmethod
    def _feature_value_color(normalized: float) -> QColor:
        t = max(0.0, min(1.0, float(normalized)))
        low = QColor(theme.CHART_BLUE)
        high = QColor(theme.CHART_ORANGE)
        return QColor(
            round(low.red() + (high.red() - low.red()) * t),
            round(low.green() + (high.green() - low.green()) * t),
            round(low.blue() + (high.blue() - low.blue()) * t),
        )

    def _feature_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        index = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not 0 <= index < len(self._feature_records):
            return
        record = self._feature_records[index]
        self._selected_feature_name = str(record.get("feature", ""))
        if hasattr(self, "study_feature_button"):
            adjustable = is_adjustable_feature_name(self._selected_feature_name)
            self.study_feature_button.setEnabled(bool(self._selected_feature_name) and adjustable)
            self.study_feature_button.setToolTip(
                "带着这个实际参数进入参数研究并填好设置，不会自动开始计算"
                if adjustable else
                "这是由多个物理量计算出来的模型特征，不能直接当作一个参数扫描。请先查看它关联的实际参数。"
            )
        self._update_linkage(record)
        self._update_dependence_plot(record)
        self._refresh_selected_plot_highlight()

    def _update_dependence_plot(self, record: dict) -> None:
        slot = self.plot_workspaces.get("单参数规律")
        if slot is None:
            return
        feature = str(record.get("feature", "") or "")
        display = str(record.get("display_name", feature) or feature)
        rows = self._sample_rows(dict(self._shap_data or {}))
        x_values: list[float] = []
        y_values: list[float] = []
        for row in rows[:400]:
            raw = self._value_map(row, "feature_values").get(feature)
            shap_value = self._value_map(row, "shap_values", "values").get(feature)
            if isinstance(raw, (int, float)) and isinstance(shap_value, (int, float)):
                x_values.append(float(raw)); y_values.append(float(shap_value))
        if len(x_values) >= 2:
            slot.set_result(0, "单参数规律", {
                "kind": "scatter", "x": x_values, "y": y_values,
                "title": "",
                "x_label": display, "y_label": "SHAP 贡献",
                "summary": "该图用于发现取值与模型贡献的关系；规律必须再用正式参数扫描和复场仿真验证。",
            })
            if hasattr(self, "shap_view_tabs"):
                self.shap_view_tabs.setTabVisible(3, True)
        else:
            slot.set_result(0, "单参数规律", {"kind":"empty","message":"当前数据没有足够的样本级参数值，无法绘制单参数影响图。"})

    def _select_feature_by_name(self, name: str) -> None:
        normalized = str(name).strip()
        target_index = None
        for index, record in enumerate(self._feature_records):
            if normalized in {
                str(record.get("feature", "")),
                str(record.get("display_name", "")),
            }:
                target_index = index
                break
        if target_index is None:
            return
        # The list also contains physical-category header rows, therefore the
        # record index is not the same as the visible QListWidget row.
        for row in range(self.feature_list.count()):
            item = self.feature_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == target_index:
                self.feature_list.setCurrentRow(row)
                # 从蜂群图点击参数时直接进入单参数规律，不要求用户手动展开/切换。
                if hasattr(self, "shap_view_tabs"):
                    self.shap_view_tabs.setCurrentIndex(3)
                return

    def _prepare_selected_feature_scan(self) -> None:
        feature = str(getattr(self, "_selected_feature_name", "") or "").strip()
        if not feature:
            return
        display = feature
        for record in list(getattr(self, "_feature_records", []) or []):
            if str(record.get("feature", "")) == feature:
                display = str(record.get("display_name", feature) or feature)
                break
        signal = getattr(self, "assistantActionRequested", None)
        if signal is not None:
            signal.emit({
                "label": "研究这个参数",
                "target": "optimization.scan",
                "level": "prepare",
                "prefill_parameter": display,
                "prefill_feature": feature,
                "source": "shap",
            })

    def _shap_view_tab_changed(self, index: int) -> None:
        titles = ("主要因素", "当前系统", "整体参数规律", "单参数规律")
        if 0 <= int(index) < len(titles):
            self._selected_shap_section = titles[int(index)]
        self._plot_tab_changed(index)

    def _plot_tab_changed(self, _index: int) -> None:
        if self._selected_feature_name:
            self._refresh_selected_plot_highlight()
            record = next(
                (
                    item
                    for item in self._feature_records
                    if str(item.get("feature", "")) == self._selected_feature_name
                ),
                None,
            )
            if record:
                self._update_linkage(record)

    def _refresh_selected_plot_highlight(self) -> None:
        display_name = ""
        for record in self._feature_records:
            if str(record.get("feature", "")) == self._selected_feature_name:
                display_name = str(record.get("display_name", ""))
                break
        if not display_name:
            return
        for title in ("当前系统",):
            slot = self.plot_workspaces.get(title)
            workspace = slot.workspace if slot is not None else None
            if workspace is None or not getattr(workspace, "panes", None):
                continue
            pane = workspace.panes[0]
            data = pane.canvas.data
            if data.get("kind") in {"bar", "barh"}:
                data["selected_label"] = display_name
                pane.set_result(pane.title.text(), data)

    def _update_linkage(self, record: dict) -> None:
        feature = str(record.get("feature", record.get("name", "")))
        display = str(record.get("display_name", feature_display_name(feature)))
        fallback_category, fallback_item, fallback_level, fallback_note = formula_binding_for_feature(feature)
        category = str(record.get("formula_category") or fallback_category)
        item = str(record.get("formula_item") or fallback_item)
        mapping_level = str(record.get("mapping_level") or fallback_level)
        mapping_note = str(record.get("mapping_note") or fallback_note)
        latex = str(record.get("formula_latex") or formula_latex(category, item) or "")

        # 统一图形工作区后不再依赖旧的 plot_tabs；当前视图由
        # _selected_shap_section / 统一解释视图 Tab 共同维护。
        current_tab = str(getattr(self, "_selected_shap_section", "主要因素") or "主要因素")
        if current_tab == "当前系统" and feature in self._local_shap_by_feature:
            contribution = self._local_shap_by_feature[feature]
            contribution_label = "当前系统 SHAP"
        else:
            contribution = float(record.get("mean_shap", 0.0) or 0.0)
            contribution_label = "平均 SHAP"

        formula_contribution = record.get("formula_centered_contribution")
        formula_loss = record.get("formula_loss")
        residual = None
        if isinstance(formula_contribution, (int, float)):
            residual = float(contribution) - float(formula_contribution)

        maximum = max(
            (float(item.get("mean_abs_shap", 0.0) or 0.0) for item in self._feature_records),
            default=1.0,
        ) or 1.0
        weight = float(record.get("mean_abs_shap", 0.0) or 0.0) / maximum
        self._set_info(self.dominant_rows[3], "当前选择", display)
        self._set_info(self.dominant_rows[4], "当前权重", f"{100.0 * weight:.1f}%")

        sample_value = record.get("sample_value", record.get("feature_value"))
        source_parameters = record.get("source_parameters") or []
        raw_text = (
            f"{float(sample_value):.6g}"
            if isinstance(sample_value, (int, float))
            else ("、".join(map(str, source_parameters)) if source_parameters else "当前接口未返回")
        )
        self._set_info(self.physics_rows["feature"], "当前参数", display)
        self._set_info(self.physics_rows["raw"], "原始参数", raw_text)
        if latex:
            self._set_formula_info(
                self.physics_rows["formula"],
                "公式",
                formula_html(category, item, latex),
            )
        else:
            self._set_info(
                self.physics_rows["formula"],
                "公式",
                "未建立公式映射",
            )
        self._set_info(
            self.physics_rows["shap"],
            contribution_label,
            f"{float(contribution):+.6g}",
        )
        comparison_status = str(record.get("formula_comparison_status") or "")
        formula_efficiency = record.get("formula_efficiency")
        if isinstance(formula_contribution, (int, float)):
            formula_text = f"{float(formula_contribution):+.6g} dB"
        elif comparison_status == "indirect_parameter" or mapping_level == "间接":
            formula_text = "不适用（结构参数）"
        elif comparison_status == "requires_derived_feature" or mapping_level == "组合":
            formula_text = "需先计算组合失配量"
        elif comparison_status == "target_domain_mismatch":
            formula_text = (
                f"解析相对效率 {100.0 * float(formula_efficiency):.3f}%"
                if isinstance(formula_efficiency, (int, float))
                else "仅显示公式，不作加性比较"
            )
        elif isinstance(formula_loss, (int, float)):
            formula_text = f"解析损失 {float(formula_loss):.6g} dB"
        else:
            formula_text = "不适用"
        self._set_info(
            self.physics_rows["formula_contribution"],
            "公式对照",
            formula_text,
        )

        if residual is not None:
            residual_text = f"{residual:+.6g} dB"
        elif comparison_status == "indirect_parameter" or mapping_level == "间接":
            residual_text = "不适用（间接机制）"
        elif comparison_status == "requires_derived_feature" or mapping_level == "组合":
            residual_text = "不适用（缺少组合量）"
        elif comparison_status == "target_domain_mismatch":
            residual_text = "不适用（输出单位不同）"
        else:
            residual_text = "不适用"
        self._set_info(
            self.physics_rows["residual"],
            "趋势差异",
            residual_text,
        )
        self._set_info(
            self.physics_rows["mechanism"],
            "物理关系",
            str(record.get("description") or physical_mechanism_for_feature(feature)),
        )
        self._set_info(
            self.physics_rows["action"],
            "下一步",
            suggested_action_for_feature(feature),
        )

        consistency = self._consistency_record(feature)
        if consistency:
            level = str(consistency.get("level", "—"))
            sign = consistency.get("sign_agreement")
            sign_text = (
                f"方向一致 {100.0 * float(sign):.1f}%"
                if isinstance(sign, (int, float))
                else "方向一致率未返回"
            )
            consistency_text = f"{level} · {sign_text}"
        else:
            if mapping_level == "间接":
                consistency_text = "不适用（间接参数）"
            elif mapping_level == "组合":
                consistency_text = "需先生成组合物理特征"
            elif comparison_status == "target_domain_mismatch":
                consistency_text = "不适用（输出单位不同）"
            else:
                consistency_text = "暂无一致性结果"
        self._set_info(
            self.quality_rows["consistency"],
            "公式一致性",
            consistency_text,
        )
        if hasattr(self, "linkage_consistency"):
            self._set_info(self.linkage_consistency, "趋势一致性", consistency_text)
        self._set_info(
            self.quality_rows["mapping"],
            "当前映射",
            f"{mapping_level} · {mapping_note}",
        )

        color = self._contribution_color(contribution, weight)
        self._set_value_color(self.physics_rows["feature"], color)
        self._set_value_color(self.physics_rows["shap"], color)

    def _consistency_record(self, feature: str) -> dict:
        for item in list((self._shap_data or {}).get("formula_consistency", []) or []):
            if str(item.get("feature", "")) == feature:
                return dict(item)
        return {}

    @staticmethod
    def _set_info(widget: InfoRow, label: str, value: str) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(str(label))
            layout.itemAt(1).widget().setText(str(value))

    @staticmethod
    def _set_formula_info(widget: InfoRow, label: str, html: str) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            key = layout.itemAt(0).widget()
            value = layout.itemAt(1).widget()
            key.setText(str(label))
            value.setTextFormat(Qt.TextFormat.RichText)
            value.setWordWrap(True)
            value.setText(str(html))
            value.setMinimumHeight(72)

    @staticmethod
    def _set_value_color(widget: InfoRow, color: QColor) -> None:
        layout = widget.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(1).widget().setStyleSheet(
                f"color: {color.name()}; font-weight: 700;"
            )

    @staticmethod
    def _importance_color(weight: float) -> QColor:
        weight = max(0.0, min(1.0, float(weight)))
        start = QColor(theme.SURFACE_SECONDARY)
        end = QColor(theme.PRIMARY)
        return QColor(
            round(start.red() + (end.red() - start.red()) * weight),
            round(start.green() + (end.green() - start.green()) * weight),
            round(start.blue() + (end.blue() - start.blue()) * weight),
        )

    @staticmethod
    def _contribution_color(value: float, weight: float) -> QColor:
        intensity = 0.2 + 0.8 * sqrt(max(0.0, min(1.0, float(weight))))
        neutral = QColor(theme.SURFACE_SECONDARY)
        target = QColor(theme.CHART_ORANGE if value >= 0 else theme.CHART_CYAN)
        return QColor(
            round(neutral.red() + (target.red() - neutral.red()) * intensity),
            round(neutral.green() + (target.green() - neutral.green()) * intensity),
            round(neutral.blue() + (target.blue() - neutral.blue()) * intensity),
        )
