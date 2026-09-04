from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QStyledItemDelegate,
)

from frontend_pyside.features.simulation.surface_registry import surface_type_names


class SurfaceTypeDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(surface_type_names())
        return editor

    def setEditorData(self, editor, index):
        value = str(index.model().data(index, Qt.ItemDataRole.EditRole) or "球面")
        target = editor.findText(value)
        editor.setCurrentIndex(target if target >= 0 else 0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class MaterialDelegate(QStyledItemDelegate):
    """Editable material chooser for the common Surface table column."""

    COMMON_MATERIALS = ("AIR", "N-BK7", "N-SF11", "F_SILICA", "MIRROR", "自定义")

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.setEditable(True)
        editor.addItems(self.COMMON_MATERIALS)
        return editor

    def setEditorData(self, editor, index):
        value = str(index.model().data(index, Qt.ItemDataRole.EditRole) or "AIR")
        target = editor.findText(value)
        if target >= 0:
            editor.setCurrentIndex(target)
        else:
            editor.setEditText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip() or "AIR", Qt.ItemDataRole.EditRole)


class SurfaceFloatDelegate(QStyledItemDelegate):
    """Validated engineering-number editor; units remain in the table header."""

    def __init__(self, parent=None, *, minimum=-1.0e9, maximum=1.0e9, decimals=8):
        super().__init__(parent)
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.decimals = int(decimals)

    def createEditor(self, parent, option, index):
        editor = QDoubleSpinBox(parent)
        editor.setRange(self.minimum, self.maximum)
        editor.setDecimals(self.decimals)
        editor.setSingleStep(0.1)
        editor.setKeyboardTracking(False)
        return editor

    def setEditorData(self, editor, index):
        try:
            value = float(index.model().data(index, Qt.ItemDataRole.EditRole))
        except (TypeError, ValueError):
            value = 0.0
        editor.setValue(value)
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, f"{editor.value():.12g}", Qt.ItemDataRole.EditRole)


__all__ = ["MaterialDelegate", "SurfaceFloatDelegate", "SurfaceTypeDelegate"]
