from __future__ import annotations


from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class PageHeader(QWidget):


    def __init__(self, title, subtitle="", actions=None, parent=None):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 3)
        layout.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        text.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("pageSubtitle")
            sub.setWordWrap(True)
            text.addWidget(sub)
        layout.addLayout(text, 1)

        action_widgets = list(actions or [])
        if action_widgets:
            action_row = QHBoxLayout()
            action_row.setSpacing(7)
            for widget in action_widgets:
                action_row.addWidget(widget)
            layout.addLayout(action_row)

class SectionTitle(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sectionTitle")
