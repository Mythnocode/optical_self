from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QToolButton, QWidget


class AssistantFloatingButton(QToolButton):


    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantFloatingButton")
        self.setText("AI")
        self.setToolTip("打开AI助手")
        self.setFixedSize(54, 54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            """
            QToolButton#assistantFloatingButton {
                background: #1768e5;
                color: white;
                border: 2px solid white;
                border-radius: 27px;
                font-size: 16px;
                font-weight: 700;
            }
            QToolButton#assistantFloatingButton:hover { background: #0f57c8; }
            QToolButton#assistantFloatingButton:pressed,
            QToolButton#assistantFloatingButton[active="true"] { background: #0a438f; }
            """
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 85))
        self.setGraphicsEffect(shadow)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)
