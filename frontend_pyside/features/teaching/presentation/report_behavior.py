from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import (
    Card,
    InfoRow,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable

from ..export_service import write_learning_records

class TeachingReportMixin:
    def _report_panel(self):
        widget = QWidget()
        root = QHBoxLayout(widget)
        root.setContentsMargins(8, 8, 8, 8)
        editor = Card("实验结论", compact=True)
        self.conclusion = QTextEdit()
        self.conclusion.setPlaceholderText("写出观察到的规律、物理原因以及近似模型的适用条件。")
        editor.body.addWidget(self.conclusion)
        root.addWidget(editor, 2)
        score_card = Card("评分与导出", compact=True)
        self.score_label = QLabel("尚未评分")
        self.score_label.setWordWrap(True)
        score_card.body.addWidget(self.score_label)
        score_card.body.addWidget(InfoRow("评分维度", "预测、任务、记录、解释和数值可信度"))
        score_card.body.addWidget(InfoRow("报告内容", "参数、图表、记录、诊断、结论和得分"))
        score = SecondaryButton("评分")
        score.clicked.connect(self._score)
        export = PrimaryButton("导出实验报告")
        export.clicked.connect(self._export_report)
        score_card.body.addStretch()
        score_card.body.addWidget(score)
        score_card.body.addWidget(export)
        root.addWidget(score_card, 1)
        return widget

    def _score(self):
        output = self.workflow.score(self.current_module, self.current_result, self.conclusion.toPlainText())
        self._refresh_all_records()
        self.score_label.setText(
            "总分：%d/100\n%s"
            % (output["total"], "\n".join(f"{key}：{value}" for key, value in output["parts"].items()))
        )

    def _export_report(self):
        bundle = self.workflow.report(
            self.current_module,
            self.current_inputs,
            self.current_result,
            self.conclusion.toPlainText(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存教学实验报告",
            f"{self.current_module}_teaching_report.md",
            "Markdown (*.md);;JSON (*.json);;CSV (*.csv)",
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        content = bundle["json"] if suffix == ".json" else bundle["csv"] if suffix == ".csv" else bundle["markdown"]
        Path(path).write_text(content, encoding="utf-8")
        QMessageBox.information(self, "导出完成", f"已保存到：{path}")

    def _build_theory(self):
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        left = Card("理论目录", compact=True)
        left.setMinimumWidth(260)
        left.setMaximumWidth(330)
        self.theory_list = QComboBox()
        self.theory_list.addItems([value["title"] for value in self.catalog["modules"].values()])
        self.theory_list.currentIndexChanged.connect(lambda _: self._update_theory())
        left.body.addWidget(self.theory_list)
        left.body.addWidget(InfoRow("内容", "概念、公式、变量、适用条件和学习目标"))
        left.body.addWidget(InfoRow("关联", "可直接跳转到对应实验"))
        left.body.addStretch()
        jump = PrimaryButton("进入对应实验")
        jump.clicked.connect(lambda: self._open_module(list(self.catalog["modules"])[self.theory_list.currentIndex()]))
        left.body.addWidget(jump)
        root.addWidget(left)

        theory_card = Card("理论正文", compact=True)
        self.theory_text = QTextEdit()
        self.theory_text.setReadOnly(True)
        theory_card.body.addWidget(self.theory_text)
        root.addWidget(theory_card, 2)

        related = Card("学习提示", compact=True)
        related.setMinimumWidth(300)
        self.theory_side = QLabel()
        self.theory_side.setWordWrap(True)
        related.body.addWidget(self.theory_side)
        root.addWidget(related, 1)
        return page

    def _update_theory(self):
        if not hasattr(self, "theory_text"):
            return
        key = list(self.catalog["modules"])[self.theory_list.currentIndex()]
        spec = self.catalog["modules"][key]
        self.theory_text.setPlainText(
            f"{spec['title']}\n\n"
            f"核心公式\n{spec['formula']}\n\n"
            f"物理含义\n{spec['theory']}\n\n"
            "适用条件\n- "
            + "\n- ".join(spec["assumptions"])
            + "\n\n学习目标\n- "
            + "\n- ".join(spec["objectives"])
        )
        self.theory_side.setText(
            "建议学习方式\n"
            "1. 先依据公式预测变量变化方向。\n"
            "2. 在实验工作台中只改变一个变量。\n"
            "3. 记录指标和图形变化。\n"
            "4. 说明公式在哪些条件下可能失效。\n\n"
            "结果边界\n当前内容采用教学近似，不替代正式光学仿真。"
        )

    def _open_current_theory(self) -> None:
        keys = list(self.catalog["modules"])
        if self.current_module in keys:
            self.theory_list.setCurrentIndex(keys.index(self.current_module))
        self._update_theory()
        self.tabs.setCurrentWidget(self.theory)

    def _export_all_records(self) -> None:
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出全部学习记录",
            "teaching_learning_records.json",
            "JSON (*.json);;CSV (*.csv)",
        )
        if not path:
            return
        if selected_filter.startswith("CSV") and not path.lower().endswith(".csv"):
            path += ".csv"
        elif not path.lower().endswith((".json", ".csv")):
            path += ".json"
        write_learning_records(
            path,
            self.catalog["modules"],
            self.workflow.sessions,
        )
        QMessageBox.information(self, "导出完成", f"全部学习记录已保存到：{path}")

    def _build_records(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        cards = QHBoxLayout()
        self.record_progress = InlineMetric("总进度", str(len(self.catalog["modules"])), "个模块")
        self.record_done = InlineMetric("已完成", "0", "个")
        self.record_average = InlineMetric("平均分", "—")
        self.record_reports = InlineMetric("报告", "0", "份")
        for card in (self.record_progress, self.record_done, self.record_average, self.record_reports):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.all_records = DataTable(0, 6)
        self.all_records.setHorizontalHeaderLabels(["模块", "记录数", "预测", "诊断", "得分", "建议"])
        splitter.addWidget(self.all_records)
        advice = Card("学习建议", compact=True)
        advice.setMinimumWidth(330)
        advice.body.addWidget(InfoRow("当前重点", "完成当前模块的结论与评分"))
        advice.body.addWidget(InfoRow("薄弱环节", "数值诊断尚未完成"))
        advice.body.addWidget(InfoRow("推荐下一课", "按学习路径继续下一个可用实验"))
        advice.body.addWidget(InfoRow("报告要求", "写清规律、原因和适用条件"))
        advice.body.addStretch()
        self.export_all_records_button = SecondaryButton("导出全部学习记录")
        self.export_all_records_button.clicked.connect(self._export_all_records)
        advice.body.addWidget(self.export_all_records_button)
        splitter.addWidget(advice)
        splitter.setSizes([930, 360])
        root.addWidget(splitter, 1)
        return page

    def _refresh_all_records(self):
        if not hasattr(self, "all_records"):
            return
        rows = []
        scores = []
        completed = 0
        reports = 0
        for key, spec in self.catalog["modules"].items():
            session = self.workflow.session(key)
            score = session.get("score", {}).get("total", "—")
            if isinstance(score, (int, float)):
                scores.append(float(score))
            if session.get("prediction_correct") and session.get("records"):
                completed += 1
            if session.get("score"):
                reports += 1
            advice = "继续实验"
            if not session.get("prediction_correct"):
                advice = "先完成预测"
            elif not session.get("diagnostic", {}).get("sampling_pass"):
                advice = "完成数值诊断"
            elif score == "—":
                advice = "撰写结论并评分"
            else:
                advice = "已形成闭环"
            rows.append(
                [
                    spec["title"],
                    len(session["records"]),
                    "正确" if session.get("prediction_correct") else "未完成",
                    "通过" if session.get("diagnostic", {}).get("sampling_pass") else "未完成",
                    score,
                    advice,
                ]
            )
        self.all_records.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.all_records.setItem(row, column, QTableWidgetItem(str(value)))
        self.record_done.set_value(completed, "个")
        self.record_average.set_value(f"{sum(scores) / len(scores):.1f}" if scores else "—")
        self.record_reports.set_value(reports, "份")
