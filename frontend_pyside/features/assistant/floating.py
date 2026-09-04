from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QToolButton, QWidget


class AssistantFloatingButton(QToolButton):
    """Floating AI button with simple click-or-drag behaviour.

    A normal click keeps the existing assistant toggle action. Dragging moves the
    button inside its parent so it can be moved away from text or plots.
    """

    dragFinished = Signal(QPoint)
    DRAG_THRESHOLD = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantFloatingButton")
        self.setText("AI")
        self.setToolTip("打开AI助手；按住可拖动")
        self.setFixedSize(46, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._press_global: QPoint | None = None
        self._start_pos = QPoint()
        self._dragging = False
        self._user_moved = False
        self.setStyleSheet(
            """
            QToolButton#assistantFloatingButton {
                background: #1768e5;
                color: white;
                border: 2px solid white;
                border-radius: 23px;
                font-size: 14px;
                font-weight: 700;
            }
            QToolButton#assistantFloatingButton:hover { background: #0f57c8; }
            QToolButton#assistantFloatingButton:pressed,
            QToolButton#assistantFloatingButton[active="true"] { background: #0a438f; }
            """
        )
        self._attention_badge = QLabel("", self)
        self._attention_badge.setObjectName("assistantAttentionBadge")
        self._attention_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._attention_badge.setFixedSize(18, 18)
        self._attention_badge.move(self.width() - 18, 0)
        self._attention_badge.setStyleSheet(
            "QLabel#assistantAttentionBadge { background:#C5221F; color:white; border:2px solid white; "
            "border-radius:9px; font-size:10px; font-weight:700; }"
        )
        self._attention_badge.hide()

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 85))
        self.setGraphicsEffect(shadow)

    def set_attention_count(self, count: int, detail: str = "") -> None:
        count = max(0, int(count))
        self._attention_badge.setText("9+" if count > 9 else str(count))
        self._attention_badge.setVisible(count > 0)
        if count > 0:
            self.setToolTip(detail or f"AI 发现 {count} 项值得关注的当前状态；点击查看建议")
        else:
            self.setToolTip("打开AI助手；按住可拖动")

    def set_active(self, active: bool) -> None:
        self.setProperty("active", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_pos = self.pos()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() < self.DRAG_THRESHOLD:
            return
        self._dragging = True
        self._user_moved = True
        parent = self.parentWidget()
        target = self._start_pos + delta
        if parent is not None:
            max_x = max(0, parent.width() - self.width())
            max_y = max(0, parent.height() - self.height())
            target.setX(max(0, min(target.x(), max_x)))
            target.setY(max(0, min(target.y(), max_y)))
        self.move(target)
        self.raise_()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        dragged = self._dragging
        self._press_global = None
        self._dragging = False
        if dragged and event.button() == Qt.MouseButton.LeftButton:
            self.setDown(False)
            self.dragFinished.emit(self.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)
