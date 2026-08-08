
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
)

from frontend_pyside.features.explainability.actions import ReportContentOptions
from frontend_pyside.shared.components.tables import DataTable


class TablePreviewDialog(QDialog):
    def __init__(self, title: str, headers: list[str], rows: list[list[object]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 520)
        root = QVBoxLayout(self)
        table = DataTable(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
        root.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


class ReportContentDialog(QDialog):


    _FIELDS = (
        ("model_dataset", "模型与数据集信息"),
        ("global_shap", "全局有符号 / 绝对 SHAP"),
        ("local_samples", "局部样本与高贡献样本"),
        ("physical_formulas", "对应物理公式"),
        ("consistency_anomalies", "一致性与异常说明"),
        ("limitations", "适用范围与局限"),
    )

    def __init__(self, options: ReportContentOptions | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择解释报告内容")
        self.setMinimumWidth(440)
        options = options or ReportContentOptions()
        root = QVBoxLayout(self)
        label = QLabel("所选内容将控制解释报告结构；至少保留一个部分。")
        label.setWordWrap(True)
        root.addWidget(label)
        self._checks: dict[str, QCheckBox] = {}
        for field, text in self._FIELDS:
            check = QCheckBox(text)
            check.setChecked(bool(getattr(options, field)))
            self._checks[field] = check
            root.addWidget(check)
        root.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        if not any(check.isChecked() for check in self._checks.values()):
            self._checks["limitations"].setChecked(True)
        self.accept()

    def options(self) -> ReportContentOptions:
        values = {field: check.isChecked() for field, check in self._checks.items()}
        return ReportContentOptions(**values)


__all__ = ["ReportContentDialog", "TablePreviewDialog"]
