from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .badges import Badge
from .buttons import SecondaryButton

class Card(QFrame):
    def __init__(self, title="", parent=None, *, compact=False):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        margins = (13, 11, 13, 11) if compact else (15, 13, 15, 13)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(8)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("cardTitle")
            self.body.addWidget(self.title_label)

class FeatureCard(Card):
    activated = Signal()

    def __init__(
        self,
        title,
        description,
        button_text="进入",
        parent=None,
        *,
        details: Iterable[str] | None = None,
        status: str = "",
    ):
        super().__init__(title, parent, compact=True)
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setObjectName("mutedText")
        self.body.addWidget(description_label)
        if details:
            detail_label = QLabel("　·　".join(str(x) for x in details))
            detail_label.setWordWrap(True)
            detail_label.setObjectName("helperText")
            self.body.addWidget(detail_label)
        self.body.addStretch()
        footer = QHBoxLayout()
        if status:
            badge = Badge(status, "success" if "可用" in status or "完成" in status else "info")
            footer.addWidget(badge)
        footer.addStretch()
        button = SecondaryButton(button_text)
        button.clicked.connect(self.activated)
        footer.addWidget(button)
        self.body.addLayout(footer)

class CollapsiblePanel(Card):
    def __init__(self, title, parent=None, expanded=True):
        super().__init__("", parent, compact=True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.toggle = QToolButton(text=title, checkable=True, checked=expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.body.addWidget(self.toggle)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 2, 0, 0)
        self.content_layout.setSpacing(7)
        self.content.setVisible(expanded)
        self.body.addWidget(self.content)
        self.toggle.toggled.connect(self._toggle)

    def _toggle(self, on):
        self.content.setVisible(on)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow
        )
        self.content.updateGeometry()
        self.updateGeometry()
        if self.parentWidget() is not None:
            self.parentWidget().updateGeometry()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)
