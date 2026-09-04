from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import SummaryStrip
from frontend_pyside.shared.components.unit_spinbox import UnitAwareDoubleSpinBox



class ScrollSafeDoubleSpinBox(UnitAwareDoubleSpinBox):


    def wheelEvent(self, event: QWheelEvent) -> None:  
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class ParameterControlMixin:
    def _connect_change_signals(self):
        for widget in self.findChildren(QDoubleSpinBox):
            widget.valueChanged.connect(lambda _value: self.changed.emit())
        for widget in self.findChildren(QSpinBox):
            widget.valueChanged.connect(lambda _value: self.changed.emit())
        for widget in self.findChildren(QComboBox):
            widget.currentIndexChanged.connect(lambda _index: self.changed.emit())
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(lambda _checked: self.changed.emit())
        for widget in self.findChildren(QLineEdit):
            widget.editingFinished.connect(self.changed.emit)

    def _set_alignment_controls_enabled(self, _enabled: bool) -> None:
        pass

    @staticmethod
    def _spin(value, minimum, maximum, suffix="", decimals=4):
        widget = ScrollSafeDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        if suffix:
            widget.setSuffix(f" {suffix}")
        widget.setKeyboardTracking(False)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.setMinimumWidth(150)
        widget.setMinimumHeight(30)
        widget.setMaximumHeight(34)
        return widget

    @staticmethod
    def _compact_form() -> QFormLayout:
        form = QFormLayout()
        form.setVerticalSpacing(5)
        form.setHorizontalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return form

    def _page_shell(self, summary_items):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        if summary_items:
            layout.addWidget(SummaryStrip(summary_items))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        layout.addLayout(grid, 0)
        layout.addStretch(1)
        return page, layout, grid
