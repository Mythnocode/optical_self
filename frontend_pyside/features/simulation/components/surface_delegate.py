from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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
