from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
    QVBoxLayout,
)
from frontend_pyside.shared import layout_tokens as ui_layout

from .cards import Card

class MetricCard(Card):
    def __init__(self, title, value="—", unit="", parent=None, note=""):
        super().__init__("", parent, compact=True)
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.value_label.setMinimumWidth(54)
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("metricUnit")
        self.note_label = QLabel(note)
        self.note_label.setObjectName("helperText")
        self.note_label.setWordWrap(True)

        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self.value_label)
        row.addWidget(self.unit_label)
        row.addStretch()
        self.body.addWidget(self.title_label)
        self.body.addLayout(row)
        if note:
            self.body.addWidget(self.note_label)

    def set_value(self, value, unit=None, note=None):
        self.value_label.setText(str(value))
        self.unit_label.setText(self.unit_label.text() if unit is None else unit)
        if note is not None:
            self.note_label.setText(note)
            self.note_label.setVisible(bool(note))

class InlineMetric(QFrame):


    def __init__(self, title, value="—", unit="", parent=None, note=""):
        super().__init__(parent)
        self.setObjectName("inlineMetric")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(48)
        self.setMaximumHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 6, 11, 6)
        layout.setSpacing(7)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("inlineMetricTitle")
        self.value_label = QLabel(str(value))
        self.value_label.setObjectName("inlineMetricValue")
        self.value_label.setMinimumWidth(54)
        # 14–15 pt metric text needs a little more vertical breathing room than
        # QLabel's compact size hint under the Linux CJK fallback font.  Without
        # this, the simulation summary values are squeezed to ~24 px and can clip
        # glyph tops/bottoms even though the metric frame itself has spare height.
        self.value_label.setMinimumHeight(28)
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("inlineMetricUnit")
        self.note_label = QLabel(note)
        self.note_label.setObjectName("inlineMetricNote")
        self.note_label.setVisible(bool(note))

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.unit_label)
        layout.addStretch(1)
        layout.addWidget(self.note_label)

    def set_value(self, value, unit=None, note=None):
        self.value_label.setText(str(value))
        if unit is not None:
            self.unit_label.setText(str(unit))
        if note is not None:
            self.note_label.setText(str(note))
            self.note_label.setVisible(bool(note))

class SummaryStrip(QFrame):


    def __init__(self, items: Iterable[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("summaryStrip")
        self.setMinimumHeight(66)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            ui_layout.CARD_PADDING,
            ui_layout.CONTROL_GAP,
            ui_layout.CARD_PADDING,
            ui_layout.CONTROL_GAP,
        )
        self._layout.setSpacing(ui_layout.CONTROL_GAP)
        self._value_labels: list[QLabel] = []
        self.set_items(items)

    def set_items(self, items: Iterable[tuple[str, str]]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._value_labels.clear()
        values = [(str(label), str(value)) for label, value in items]
        for index, (label, value) in enumerate(values):
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)
            key_label = QLabel(label)
            key_label.setObjectName("summaryKey")
            value_label = QLabel(value)
            value_label.setObjectName("summaryValue")
            item_layout.addWidget(key_label)
            item_layout.addWidget(value_label)
            self._value_labels.append(value_label)
            self._layout.addWidget(item, 1)
            if index < len(values) - 1:
                divider = QFrame()
                divider.setFrameShape(QFrame.Shape.VLine)
                divider.setObjectName("summaryDivider")
                self._layout.addWidget(divider)

    def set_values(self, values: Iterable[str]) -> None:
        for label, value in zip(self._value_labels, values):
            label.setText(str(value))
