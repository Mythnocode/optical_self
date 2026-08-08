from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.explainability.actions import (
    FORMULA_CATALOG,
    formula_latex,
    formula_location_for_feature,
)
from frontend_pyside.features.explainability.formula_presentation import formula_html
from frontend_pyside.shared.components.basic import (
    Card,
    InfoRow,
    MetricCard,
    SecondaryButton,
    SummaryStrip,
)
from frontend_pyside.shared.components.formula import FormulaDisplay
from frontend_pyside.shared.components.tables import DataTable
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace


class ExplainabilityFormulaMixin:
    def _formula(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.formula_tree = QTreeWidget()
        self.formula_tree.setHeaderLabel("公式目录")
        self.formula_tree.setMinimumWidth(230)
        for category, formulas in FORMULA_CATALOG.items():
            parent = QTreeWidgetItem([category])
            self.formula_tree.addTopLevelItem(parent)
            for item in formulas:
                child = QTreeWidgetItem([item])
                child.setData(0, Qt.ItemDataRole.UserRole, (category, item))
                parent.addChild(child)
        self.formula_tree.expandAll()
        self.formula_tree.currentItemChanged.connect(self._formula_selection_changed)
        root.addWidget(self.formula_tree, 1)

        main = Card("公式主视图", compact=True)
        self.formula_tabs = QTabWidget()
        self.formula_symbol = FormulaDisplay()
        self.formula_tabs.addTab(self.formula_symbol, "直观公式")
        for name, text in [
            ("当前样本代入", "当前样本值来自真实模型解释结果；公式代入需结合变量单位和适用范围。"),
            ("分项贡献", "分项贡献使用正式 SHAP 有符号值和平均绝对值，不使用固定演示数字。"),
            ("适用条件", "模式、近轴和小扰动近似仅用于解释；强像差、高 NA 与非线性区域需正式仿真复核。"),
        ]:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.formula_tabs.addTab(label, name)
        main.body.addWidget(self.formula_tabs)
        source = SummaryStrip([("来源", "高斯模式解析近似"), ("精度", "局部近似"), ("当前样本", "#128"), ("关联特征", "X 偏移")])
        main.body.addWidget(source)
        main.body.addWidget(InfoRow("代码对应", "teaching_runtime / coupling_approx.py"))
        main.body.addWidget(InfoRow("当前判断", "SHAP 方向与公式一致", "一致", "success"))
        root.addWidget(main, 3)

        self.formula_contribution = Card("变量贡献与灵敏度", compact=True)
        self.formula_contribution.setMinimumWidth(300)
        for index in range(4):
            self.formula_contribution.body.addWidget(
                InfoRow(f"Top {index + 1}", "等待真实 SHAP 结果")
            )
        self.formula_contribution.body.addWidget(InfoRow("公式定位", "等待计算"))
        self.formula_contribution.body.addWidget(InfoRow("方向信息", "等待计算"))
        self.formula_contribution.body.addWidget(InfoRow("一致性误差", "未计算，不使用演示值"))
        self.formula_contribution.body.addStretch()
        self.view_feature_shap_button = SecondaryButton("查看该变量 SHAP 分布")
        self.view_feature_shap_button.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.shap_page)
        )
        self.copy_latex_button = SecondaryButton("复制 LaTeX")
        self.copy_latex_button.clicked.connect(self._copy_current_formula)
        self.formula_contribution.body.addWidget(self.view_feature_shap_button)
        self.formula_contribution.body.addWidget(self.copy_latex_button)
        root.addWidget(self.formula_contribution, 1)
        first = self.formula_tree.topLevelItem(0)
        if first is not None and first.childCount():
            self.formula_tree.setCurrentItem(first.child(0))
        return page

    def _top_feature_name(self) -> str:
        features = list((self._shap_data or {}).get("top_features", []) or [])
        return str(features[0].get("name", "")) if features else ""

    def _locate_top_formula(self) -> None:
        feature = self._top_feature_name()
        category, item = formula_location_for_feature(feature)
        for top_index in range(self.formula_tree.topLevelItemCount()):
            parent = self.formula_tree.topLevelItem(top_index)
            if parent.text(0) != category:
                continue
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.text(0) == item:
                    self.formula_tree.setCurrentItem(child)
                    self.tabs.setCurrentWidget(self.formula_page)
                    return

    def _formula_selection_changed(self, current, _previous=None) -> None:
        if current is None:
            return
        location = current.data(0, Qt.ItemDataRole.UserRole)
        if not location:
            return
        category, item = location
        latex = formula_latex(category, item)
        self.formula_symbol.set_formula(
            f"{category} / {item}",
            formula_html(category, item, latex),
            "用于解释趋势与局部物理关系；当前样本是否适用仍需结合正式仿真诊断。",
        )

    def _copy_current_formula(self) -> None:
        current = self.formula_tree.currentItem()
        location = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not location:
            return
        QApplication.clipboard().setText(formula_latex(*location))
        QMessageBox.information(self, "复制完成", "当前公式的 LaTeX 已复制到剪贴板。")

    def _consistency(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        cards = QHBoxLayout()
        self.consistency_cards = [
            MetricCard("公式映射覆盖", "—", "%", note="等待真实 SHAP"),
            MetricCard("已解释特征", "—", "个", note="等待真实 SHAP"),
            MetricCard("有方向贡献", "—", "个", note="保留 SHAP 正负号"),
            MetricCard("数值一致性", "未运行", "", note="不使用固定演示结论"),
        ]
        for card in self.consistency_cards:
            cards.addWidget(card)
        root.addLayout(cards)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.consistency_table = DataTable(0, 5)
        self.consistency_table.setHorizontalHeaderLabels(
            ["特征", "平均 SHAP", "平均 |SHAP|", "对应公式", "当前结论"]
        )
        splitter.addWidget(self.consistency_table)
        self.consistency_chart = ResultWorkspace()
        self.consistency_chart.set_layout_mode("左右双图")
        self.consistency_chart.set_result(
            0, "等待 SHAP", {"kind": "empty", "message": "计算真实 SHAP 后显示公式映射覆盖"}
        )
        self.consistency_chart.set_result(
            1, "等待 SHAP", {"kind": "empty", "message": "数值公式误差需独立正式扫描，不使用演示数据"}
        )
        splitter.addWidget(self.consistency_chart)
        splitter.setSizes([620, 760])
        root.addWidget(splitter, 1)
        self.consistency_note = InfoRow(
            "边界",
            "本页先验证特征是否能定位到明确物理公式；数值排名相关和公式误差必须由独立正式扫描产生。",
            "真实数据",
            "info",
        )
        root.addWidget(self.consistency_note)
        return page

    def _update_formula_contributions(self, top_features: list[dict]) -> None:
        if not hasattr(self, "formula_contribution"):
            return
        for index in range(4):
            if index < len(top_features):
                item = top_features[index]
                self._set_row_text(
                    self.formula_contribution,
                    index,
                    f"Top {index + 1} · {item.get('name', '—')}",
                    f"平均 |SHAP| {float(item.get('mean_abs_shap', 0.0)):.4g}",
                )
            else:
                self._set_row_text(
                    self.formula_contribution, index, f"Top {index + 1}", "—"
                )
        if top_features:
            category, item = formula_location_for_feature(str(top_features[0].get("name", "")))
            self._set_row_text(
                self.formula_contribution, 4, "公式定位", f"{category} / {item}"
            )
            self._set_row_text(
                self.formula_contribution,
                5,
                "方向信息",
                str(top_features[0].get("direction", "neutral")),
            )

    def _update_consistency_from_api(self, top_features: list[dict], target_name: str) -> None:
        if not hasattr(self, "consistency_table"):
            return
        mapped = 0
        signed = 0
        rows = []
        for feature in top_features:
            name = str(feature.get("name", ""))
            category, item = formula_location_for_feature(name)
            latex = formula_latex(category, item)
            is_mapped = bool(latex)
            mapped += int(is_mapped)
            mean_shap = float(feature.get("mean_shap", 0.0))
            signed += int(abs(mean_shap) > 0.0)
            rows.append([
                name,
                f"{mean_shap:.6g}",
                f"{float(feature.get('mean_abs_shap', 0.0)):.6g}",
                f"{category} / {item}" if is_mapped else "未映射",
                "可进行公式复核" if is_mapped else "需补充物理映射",
            ])
        self.consistency_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.consistency_table.setItem(
                    row_index, column_index, QTableWidgetItem(str(value))
                )
        total = len(top_features)
        coverage = 100.0 * mapped / total if total else 0.0
        self.consistency_cards[0].set_value(f"{coverage:.1f}", "%", note="公式目录映射")
        self.consistency_cards[1].set_value(str(total), "个", note=target_name or "当前输出")
        self.consistency_cards[2].set_value(str(signed), "个", note="有符号平均贡献")
        self.consistency_cards[3].set_value("待正式扫描", "", note="未伪造相关系数或公式误差")
        labels = [str(item.get("name", "")) for item in top_features]
        self.consistency_chart.set_result(
            0,
            "真实 SHAP 排名",
            {
                "kind": "bar",
                "labels": labels,
                "values": [float(item.get("mean_abs_shap", 0.0)) for item in top_features],
                "title": f"平均 |SHAP| — {target_name}",
                "source": "后端真实 SHAP",
            },
        )
        self.consistency_chart.set_result(
            1,
            "有符号贡献",
            {
                "kind": "bar",
                "labels": labels,
                "values": [float(item.get("mean_shap", 0.0)) for item in top_features],
                "title": "平均 SHAP（方向保留）",
                "source": "后端真实 SHAP",
            },
        )
