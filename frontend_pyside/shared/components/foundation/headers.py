from __future__ import annotations


from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from frontend_pyside.shared import layout_tokens as ui_layout


class PageHeader(QWidget):


    def __init__(self, title, subtitle="", actions=None, parent=None):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setMinimumHeight(70)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, ui_layout.CONTROL_GAP)
        layout.setSpacing(ui_layout.CONTENT_GAP)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        text.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        text.addWidget(self.subtitle_label)
        layout.addLayout(text, 1)

        action_widgets = list(actions or [])
        if action_widgets:
            action_row = QHBoxLayout()
            action_row.setSpacing(7)
            for widget in action_widgets:
                action_row.addWidget(widget)
            layout.addLayout(action_row)

    def set_subtitle(self, text: str) -> None:
        value = str(text or "")
        self.subtitle_label.setText(value)
        self.subtitle_label.setVisible(bool(value))


class SectionTitle(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sectionTitle")

