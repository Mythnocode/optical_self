from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QWidget,
)

from .badges import Badge
from .cards import Card

class InfoRow(QWidget):


    def __init__(self, label: str, value: str, status: str = "", tone="info", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(8)
        key = QLabel(label)
        key.setObjectName("mutedText")
        key.setMinimumWidth(94)
        val = QLabel(value)
        val.setWordWrap(True)
        layout.addWidget(key)
        layout.addWidget(val, 1)
        if status:
            layout.addWidget(Badge(status, tone))

class PageScrollArea(QScrollArea):


    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("pageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(content)

class KeyValueGrid(Card):


    def __init__(self, title: str, rows: Iterable[tuple[str, str]], parent=None):
        super().__init__(title, parent, compact=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for index, (label, value) in enumerate(rows):
            r, c = divmod(index, 2)
            cell = InfoRow(label, value)
            grid.addWidget(cell, r, c)
        self.body.addLayout(grid)
