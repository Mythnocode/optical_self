from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.explainability.actions import (
    anomaly_rows,
    build_markdown_report,
    build_structured_report_html,
    write_report,
    write_shap_csv,
    write_shap_json,
)
from frontend_pyside.shared.components.basic import (
    Card,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.data_dialogs import (
    ReportContentDialog,
    TablePreviewDialog,
)


class ExplainabilityExportMixin:
    def _show_anomaly_samples(self) -> None:
        rows = anomaly_rows(self._shap_data, limit=50)
        if not rows:
            QMessageBox.information(self, "异常样本", "请先计算真实 SHAP 结果。")
            return
        dialog = TablePreviewDialog(
            "高贡献样本列表",
            ["样本 ID", "总绝对贡献", "候选主导特征", "候选贡献", "输出"],
            rows,
            self,
        )
        dialog.exec()

    def _refresh_structured_report(self) -> None:
        editor = getattr(self, "report_editor", None)
        if editor is None:
            return
        editor.setHtml(build_structured_report_html(self._shap_data, self._report_options))

    def _select_report_contents(self) -> None:
        dialog = ReportContentDialog(self._report_options, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._report_options = dialog.options()
        labels = self._report_options.selected_labels()
        self.report_select_button.setText(f"已选择 {len(labels)} 项内容")
        self.report_select_button.setToolTip("、".join(labels))
        self._refresh_structured_report()

    def _export_shap_chart(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出解释图表", "shap_workspace.png", "PNG 图像 (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        workspace = self.plot_tabs.currentWidget() if hasattr(self, "plot_tabs") else self.shap_work
        if workspace is not None and workspace.grab().save(path, "PNG"):
            QMessageBox.information(self, "导出完成", f"图表已保存到：{path}")
        else:
            QMessageBox.warning(self, "导出失败", "无法保存当前图表。")

    def _export_shap_data(self) -> None:
        if not self._shap_data:
            QMessageBox.information(self, "导出数据", "请先计算真实 SHAP 结果。")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出 SHAP 数据",
            "shap_results.json",
            "JSON (*.json);;CSV (*.csv)",
        )
        if not path:
            return
        if path.lower().endswith(".csv") or selected_filter.startswith("CSV"):
            if not path.lower().endswith(".csv"):
                path += ".csv"
            write_shap_csv(path, self._shap_data)
        else:
            if not path.lower().endswith(".json"):
                path += ".json"
            write_shap_json(path, self._shap_data)
        QMessageBox.information(self, "导出完成", f"数据已保存到：{path}")

    def _export_explanation_report(self) -> None:
        if not self._shap_data:
            QMessageBox.information(self, "生成报告", "请先计算真实 SHAP 结果。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存模型解释报告", "model_explanation_report.md", "Markdown (*.md)"
        )
        if not path:
            return
        if not path.lower().endswith(".md"):
            path += ".md"
        narrative = ""
        editor = getattr(self, "report_editor", None)
        if editor is not None:
            narrative = editor.toPlainText()
        write_report(path, self._shap_data, narrative, self._report_options)
        QMessageBox.information(self, "导出完成", f"解释报告已保存到：{path}")

    @staticmethod
    def _report_outline_row(number: str, title: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(7)
        index = QLabel(number)
        index.setObjectName("reportOutlineIndex")
        index.setFixedWidth(24)
        index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(title)
        text.setObjectName("reportOutlineText")
        text.setWordWrap(False)
        layout.addWidget(index)
        layout.addWidget(text, 1)
        return row

    def _report(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        outline = Card("报告结构", compact=True)
        outline.setMinimumWidth(196)
        outline.setMaximumWidth(228)
        for number, title in (
            ("01", "模型与数据集"),
            ("02", "全局 SHAP 结果"),
            ("03", "局部样本解释"),
            ("04", "对应物理公式"),
            ("05", "一致性与异常"),
            ("06", "适用范围与局限"),
        ):
            outline.body.addWidget(self._report_outline_row(number, title))
        outline.body.addStretch(1)
        back_button = SecondaryButton("返回分析")
        back_button.clicked.connect(lambda: self._set_main_step(0))
        outline.body.addWidget(back_button)
        self.report_select_button = SecondaryButton("选择报告内容")
        self.report_select_button.clicked.connect(self._select_report_contents)
        outline.body.addWidget(self.report_select_button)
        root.addWidget(outline, 0)

        editor_card = Card("解释报告预览", compact=True)
        self.report_editor = QTextBrowser()
        self.report_editor.setObjectName("structuredExplainabilityReport")
        self.report_editor.setOpenExternalLinks(False)
        self.report_editor.setReadOnly(True)
        self.report_editor.setHtml(build_structured_report_html(None, self._report_options))
        editor_card.body.addWidget(self.report_editor, 1)

        row = QHBoxLayout()
        self.export_chart_button = SecondaryButton("导出图表")
        self.export_chart_button.clicked.connect(self._export_shap_chart)
        self.export_data_button = SecondaryButton("导出数据")
        self.export_data_button.clicked.connect(self._export_shap_data)
        self.generate_report_button = PrimaryButton("导出解释报告")
        self.generate_report_button.clicked.connect(self._export_explanation_report)
        row.addWidget(self.export_chart_button)
        row.addWidget(self.export_data_button)
        row.addStretch()
        row.addWidget(self.generate_report_button)
        editor_card.body.addLayout(row)
        root.addWidget(editor_card, 1)
        return page
