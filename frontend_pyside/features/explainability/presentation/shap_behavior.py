from __future__ import annotations

from math import sqrt
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
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
    InfoRow,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.workbench import MetricSummaryBar
from frontend_pyside.features.explainability.formula_presentation import formula_compact_text, formula_html
from frontend_pyside.shared.lazy_widgets import LazyTabWidget


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
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(7)

        header = Card("智能失配诊断", compact=True)
        self.shap_metric_bar = MetricSummaryBar(
            [
                ("主要失配", "—"),
                ("诊断可信度", "—"),
                ("解释样本", "—"),
                ("正式复核", "—"),
            ]
        )
        header.body.addWidget(self.shap_metric_bar)
        root.addWidget(header)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(8)

        settings = Card("诊断设置", compact=True)
        settings.setMinimumWidth(250)
        settings.setMaximumWidth(330)
        form = QFormLayout()
        form.setVerticalSpacing(6)
        self.shap_sample = QComboBox()
        self.shap_sample.addItems(["当前方案", "高贡献样本", "边界样本"])
        self.shap_sample.currentIndexChanged.connect(self._sample_selection_changed)
        self.shap_group_mode = QComboBox()
        self.shap_group_mode.addItems(["按物理失配类别", "按原始参数"])
        self.shap_group_mode.currentIndexChanged.connect(self._group_mode_changed)
        self.shap_topn = QSpinBox()
        self.shap_topn.setRange(3, 30)
        self.shap_topn.setValue(10)
        self.shap_topn.valueChanged.connect(lambda _value: self._rerender_current_shap())
        for label, widget in [
            ("模型", self.model),
            ("数据集", self.dataset),
            ("输出", self.output),
            ("分析对象", self.shap_sample),
            ("图表", self.shap_group_mode),
            ("显示数量", self.shap_topn),
        ]:
            form.addRow(label, widget)
        settings.body.addLayout(form)

        
        
        self.shap_scope = QComboBox()
        self.shap_scope.addItems(["全局 + 单样本", "仅全局", "单样本"])
        self.shap_background = QSpinBox()
        self.shap_background.setRange(20, 2000)
        self.shap_background.setValue(200)

        settings.body.addWidget(QLabel("原始参数与物理类别"))
        self.feature_list = QListWidget()
        self.feature_list.setObjectName("weightedFeatureList")
        self.feature_list.setMinimumHeight(250)
        self.feature_list.currentItemChanged.connect(self._feature_selected)
        settings.body.addWidget(self.feature_list, 1)

        self.shap_start_btn = PrimaryButton("开始分析")
        self.shap_start_btn.clicked.connect(self._request_explain)
        settings.body.addWidget(self.shap_start_btn)
        self.shap_source_info = InfoRow("数据来源", "等待分析")
        settings.body.addWidget(self.shap_source_info)
        self.shap_status_info = InfoRow("当前状态", "请选择模型和数据集")
        settings.body.addWidget(self.shap_status_info)
        body.addWidget(settings)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.plot_tabs = LazyTabWidget()
        self.plot_tabs.setDocumentMode(True)
        self.plot_workspaces: dict[str, _DeferredPlotSlot] = {}
        for title in ["失配总览", "SHAP蜂群图", "SHAP瀑布图"]:
            slot = _DeferredPlotSlot(
                title,
                lambda current_title=title: self._create_plot_workspace(current_title),
            )
            slot.set_result(0, title, {"kind": "empty", "message": "等待诊断结果"})
            self.plot_workspaces[title] = slot
            self.plot_tabs.add_lazy_tab(
                lambda current_title=title: self._build_plot_workspace(current_title),
                title,
                f"打开{title}时按需创建绘图画布。",
            )
        self.plot_tabs.currentChanged.connect(self._plot_tab_changed)
        self.plot_tabs.ensure_current_deferred()
        self.shap_work = self.plot_workspaces["失配总览"]

        plot_linkage = QSplitter(Qt.Orientation.Horizontal)
        plot_linkage.setChildrenCollapsible(False)
        plot_linkage.setHandleWidth(7)
        plot_linkage.addWidget(self.plot_tabs)
        linkage = Card("物理联动", compact=True)
        linkage.setMinimumWidth(285)
        linkage.setMaximumWidth(390)
        self.physics_rows = {
            "feature": InfoRow("当前参数", "请选择参数"),
            "raw": InfoRow("当前值", "—"),
            "formula": InfoRow("关联公式", "—"),
            "shap": InfoRow("SHAP贡献", "—"),
            "formula_contribution": InfoRow("公式对照", "—"),
            "residual": InfoRow("趋势差异", "—"),
            "mechanism": InfoRow("物理作用", "—"),
            "action": InfoRow("调整建议", "—"),
        }
        for row in self.physics_rows.values():
            linkage.body.addWidget(row)
        self.linkage_consistency = InfoRow("趋势一致性", "—")
        linkage.body.addWidget(self.linkage_consistency)
        plot_linkage.addWidget(linkage)
        plot_linkage.setStretchFactor(0, 1)
        plot_linkage.setStretchFactor(1, 0)
        plot_linkage.setSizes([900, 330])
        right_layout.addWidget(plot_linkage, 1)

        diagnosis = QWidget()
        diagnosis_layout = QGridLayout(diagnosis)
        diagnosis_layout.setContentsMargins(0, 0, 0, 0)
        diagnosis_layout.setHorizontalSpacing(7)
        diagnosis_layout.setVerticalSpacing(0)

        self.mismatch_card = Card("主要失配", compact=True)
        self.mismatch_rows = [InfoRow("1", "等待诊断"), InfoRow("2", "—"), InfoRow("3", "—")]
        for row in self.mismatch_rows:
            self.mismatch_card.body.addWidget(row)
        diagnosis_layout.addWidget(self.mismatch_card, 0, 0)

        self.adjustment_card = Card("调整顺序", compact=True)
        self.adjustment_rows = [InfoRow("第一步", "等待诊断"), InfoRow("第二步", "—"), InfoRow("第三步", "—")]
        for row in self.adjustment_rows:
            self.adjustment_card.body.addWidget(row)
        diagnosis_layout.addWidget(self.adjustment_card, 0, 1)

        self.evidence_card = Card("可信度", compact=True)
        self.evidence_rows = {
            "evidence": InfoRow("物理依据", "—"),
            "confidence": InfoRow("可信度", "—"),
            "boundary": InfoRow("正式复核", "—"),
        }
        for row in self.evidence_rows.values():
            self.evidence_card.body.addWidget(row)
        report_row = QHBoxLayout()
        report_row.addStretch(1)
        report_button = SecondaryButton("查看解释报告")
        report_button.clicked.connect(lambda: self._set_main_step(1))
        report_row.addWidget(report_button)
        self.evidence_card.body.addLayout(report_row)
        diagnosis_layout.addWidget(self.evidence_card, 0, 2)
        diagnosis_layout.setColumnStretch(0, 2)
        diagnosis_layout.setColumnStretch(1, 2)
        diagnosis_layout.setColumnStretch(2, 3)
        right_layout.addWidget(diagnosis)
        body.addWidget(right)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([290, 1180])
        root.addWidget(body, 1)

        
        compatibility = QWidget(page)
        compatibility.hide()
        self.dominant_rows = [InfoRow("", "") for _ in range(5)]
        self.quality_rows = {key: InfoRow("", "") for key in ("coverage", "additivity", "anomaly", "consistency", "mapping")}
        self.anomaly_button = SecondaryButton("高贡献样本")
        self.anomaly_button.clicked.connect(self._show_anomaly_samples)
        self.dominant_card = compatibility
        self.quality_card = compatibility
        self.physics_card = compatibility
        return page

    def _apply_shap_responsive_layout(self, compact: bool) -> None:
        
        
        return

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
        workspace.itemSelected.connect(self._select_feature_by_name)
        return workspace

    def _update_shap_from_api(self, data: dict) -> None:

        self._shap_data = dict(data)
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
        self._local_shap_by_feature = self._selected_local_sample_values(data)

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
                ("主要失配", dominant_category),
                ("诊断可信度", confidence),
                ("解释样本", str(sample_count) if sample_count else "—"),
                ("正式复核", "已完成" if formal_reviewed else "待复核"),
            ]
        )
        self._update_physical_diagnosis(category_rows, confidence, confidence_note)

        
        
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

    def _update_physical_diagnosis(self, rows: list[dict], confidence: str, confidence_note: str) -> None:
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
        self._set_info(self.evidence_rows["confidence"], "诊断可信度", f"{confidence}：{confidence_note}")
        self._set_info(self.evidence_rows["boundary"], "使用边界", "SHAP用于判断方向；最终效率和机制以正式仿真为准。")

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

    def _populate_feature_list(self) -> None:
        self.feature_list.clear()
        values = [float(item.get("mean_abs_shap", 0.0) or 0.0) for item in self._feature_records]
        maximum = max(values, default=1.0) or 1.0
        for index, record in enumerate(self._feature_records):
            name = str(record.get("display_name", record.get("feature", f"特征 {index + 1}")))
            weight = float(record.get("mean_abs_shap", 0.0) or 0.0) / maximum
            mean_shap = float(record.get("mean_shap", 0.0) or 0.0)
            category = physical_mismatch_category(str(record.get("feature", "")))
            item = QListWidgetItem(
                f"{category}｜{name}　{100.0 * weight:.0f}%"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            color = self._importance_color(weight)
            item.setBackground(QBrush(color.lighter(176)))
            item.setForeground(QBrush(QColor(theme.TEXT_PRIMARY)))
            item.setToolTip(
                f"物理类别：{category}；全局平均贡献方向：{mean_shap:+.3g}。"
            )
            self.feature_list.addItem(item)

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
            f"正式复核偏差 {predicted_value - formal_value:+.3g}"
            if formal_value is not None
            else "正式复核：待补充"
        )
        domain_text = (
            "训练域内" if within_training_domain is True
            else "训练域外" if within_training_domain is False
            else "训练域状态未知"
        )
        self.plot_workspaces["失配总览"].set_result(
            0,
            "失配总览",
            {
                "kind": "mismatch_budget",
                "y_label": "物理失配类别",
                "labels": category_labels,
                "global_values": global_values,
                "local_values": local_values,
                "title": "失配贡献预算 · 当前方案与全局样本",
                "x_label": "贡献占比 / %",
                "summary": (
                    f"主导类别：{dominant_category}   |   Top-2 全局贡献：{top_two_share:.0f}%"
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
            global_title = "全局 SHAP 分布 · 物理失配类别"
            global_description = "每个点为一个样本在该物理类别下的累计SHAP贡献；右侧细条表示平均绝对贡献。"
        else:
            labels = [str(item.get("display_name", item.get("feature", "—"))) for item in self._feature_records]
            beeswarm_points = self._beeswarm_points(data)
            importance = [float(item.get("mean_abs_shap", 0.0) or 0.0) for item in self._feature_records]
            global_title = "全局 SHAP 分布 · 原始参数"
            global_description = "纵轴按平均绝对SHAP排序；横轴保留贡献方向；颜色对应样本参数值。"
        top_global = min(15, len(labels))
        labels = labels[:top_global]
        importance = importance[:top_global]
        label_set = set(labels)
        beeswarm_points = [point for point in beeswarm_points if str(point.get("feature", "")) in label_set]
        self.plot_workspaces["SHAP蜂群图"].set_result(
            0,
            "SHAP蜂群图",
            {
                "kind": "beeswarm",
                "y_label": global_y_label,
                "labels": labels,
                "points": beeswarm_points,
                "importance": importance,
                "title": global_title,
                "x_label": "有符号 SHAP 贡献",
                "summary": global_description,
            }
            if beeswarm_points and sample_count >= 2
            else {"kind": "empty", "message": "样本级SHAP数据不足，无法绘制真实蜂群图。"},
        )

        
        waterfall_y_label = "物理失配类别" if grouped else "原始参数"
        if grouped:
            selected_records = [
                (str(item["category"]), str(item["category"]), float(item["value"]))
                for item in local_category_rows
            ]
            waterfall_title = "当前方案的物理失配贡献"
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
            waterfall_title = "当前方案的原始参数贡献"

        sample_id = str(row.get("sample_id", row.get("id", self.shap_sample.currentText())))
        waterfall_values = [item[2] for item in selected_records]
        displayed_prediction = base_value + sum(waterfall_values)
        self.plot_workspaces["SHAP瀑布图"].set_result(
            0,
            "SHAP瀑布图",
            {
                "kind": "waterfall",
                "y_label": waterfall_y_label,
                "labels": [item[1] for item in selected_records],
                "values": waterfall_values,
                "base_value": base_value,
                "formal_value": formal_value,
                "prediction_value": displayed_prediction,
                "within_training_domain": within_training_domain,
                "title": f"{waterfall_title} — {sample_id}",
                "x_label": target_name,
                "summary": (
                    f"基准值 {base_value:.4g} → 预测值 {displayed_prediction:.4g}"
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
        high = QColor(theme.CHART_RED)
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
        self._update_linkage(record)
        
        
        
        self._refresh_selected_plot_highlight()

    def _select_feature_by_name(self, name: str) -> None:
        normalized = str(name).strip()
        for index, record in enumerate(self._feature_records):
            if normalized in {
                str(record.get("feature", "")),
                str(record.get("display_name", "")),
            }:
                self.feature_list.setCurrentRow(index)
                return

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
        for title in ("SHAP瀑布图",):
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

        current_tab = self.plot_tabs.tabText(self.plot_tabs.currentIndex())
        if current_tab == "SHAP瀑布图" and feature in self._local_shap_by_feature:
            contribution = self._local_shap_by_feature[feature]
            contribution_label = "当前方案 SHAP"
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
        self._set_info(self.physics_rows["feature"], "当前变量", display)
        self._set_info(self.physics_rows["raw"], "原始参数", raw_text)
        if latex:
            self._set_formula_info(
                self.physics_rows["formula"],
                "关联公式",
                formula_html(category, item, latex),
            )
        else:
            self._set_info(
                self.physics_rows["formula"],
                "关联公式",
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
            "可能机制",
            str(record.get("description") or physical_mechanism_for_feature(feature)),
        )
        self._set_info(
            self.physics_rows["action"],
            "建议操作",
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
        target = QColor(theme.CHART_RED if value >= 0 else theme.CHART_BLUE)
        return QColor(
            round(neutral.red() + (target.red() - neutral.red()) * intensity),
            round(neutral.green() + (target.green() - neutral.green()) * intensity),
            round(neutral.blue() + (target.blue() - neutral.blue()) * intensity),
        )
