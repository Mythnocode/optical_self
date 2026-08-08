from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
)


class Badge(QLabel):
    def __init__(self, text="", tone="info", parent=None):
        super().__init__(text, parent)
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone):
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
