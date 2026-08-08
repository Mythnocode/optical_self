
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class FormulaDisplay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        self.title = QLabel("公式")
        self.title.setObjectName("cardTitle")
        self.formula = QLabel()
        self.formula.setTextFormat(Qt.TextFormat.RichText)
        self.formula.setWordWrap(True)
        self.formula.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formula.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note = QLabel()
        self.note.setObjectName("helperText")
        self.note.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.formula, 1)
        layout.addWidget(self.note)

    def set_formula(self, title: str, html: str, note: str = "") -> None:
        self.title.setText(str(title or "公式"))
        self.formula.setText(str(html or ""))
        self.note.setText(str(note or ""))
        self.note.setVisible(bool(note))


__all__ = ["FormulaDisplay"]
