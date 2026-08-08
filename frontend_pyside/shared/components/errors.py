
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from frontend_pyside.shared.components.basic import Card, PrimaryButton, SecondaryButton


class PageLoadErrorWidget(QWidget):
    retryRequested = Signal()

    def __init__(self, title: str, message: str, details: str = "", parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(12)

        card = Card(f"{title}暂时无法加载")
        summary = QLabel(message or "页面初始化失败。")
        summary.setObjectName("errorSummary")
        summary.setWordWrap(True)
        card.body.addWidget(summary)

        detail_box = QPlainTextEdit()
        detail_box.setObjectName("errorDetails")
        detail_box.setReadOnly(True)
        detail_box.setPlainText(details or message)
        detail_box.setMinimumHeight(180)
        card.body.addWidget(detail_box)

        actions = QHBoxLayout()
        retry = PrimaryButton("重新加载")
        retry.clicked.connect(lambda: self.retryRequested.emit())
        actions.addWidget(retry)
        actions.addStretch()
        copy_button = SecondaryButton("复制错误详情")
        copy_button.clicked.connect(lambda: detail_box.selectAll())
        copy_button.clicked.connect(detail_box.copy)
        actions.addWidget(copy_button)
        card.body.addLayout(actions)
        root.addWidget(card)
        root.addStretch(1)


__all__ = ["PageLoadErrorWidget"]
