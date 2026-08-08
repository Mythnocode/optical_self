from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)


class ParameterControl(QWidget):
    valueChanged = Signal(float)

    def __init__(self, label, unit, minimum, maximum, step, value, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(42)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)

        self.label = QLabel(label)
        self.label.setMinimumWidth(112)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(4 if step < 0.01 else 2)
        self.spin.setValue(value)
        self.spin.setMinimumWidth(118)
        self.spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.unit = QLabel(unit)
        self.unit.setObjectName("mutedText")
        self.unit.setMinimumWidth(56)

        layout.addWidget(self.label, 0, 0)
        layout.addWidget(self.spin, 0, 1)
        layout.addWidget(self.unit, 0, 2)
        layout.setColumnStretch(1, 1)
        self.spin.valueChanged.connect(self.valueChanged)

    def value(self):
        return self.spin.value()

    def setValue(self, value):
        self.spin.setValue(value)
