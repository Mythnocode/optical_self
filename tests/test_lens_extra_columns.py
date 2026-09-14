from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.simulation.components.optical_system_editor import OpticalSystemEditor
from frontend_pyside.features.simulation.surface_registry import apply_type_defaults


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_type_specific_columns_use_named_headers_and_unused_cells():
    app = _app()
    context = create_app_context()
    editor = OpticalSystemEditor(context.project)
    editor.show()
    try:
        headers = [
            editor.table.horizontalHeaderItem(index).text()
            for index in range(editor.table.columnCount())
        ]
        assert "关键参数" not in headers
        assert editor.table.isColumnHidden(editor.COL_GROUP)
        apply_type_defaults(editor.context.project.surfaces[0], "柱面")
        apply_type_defaults(editor.context.project.surfaces[1], "非球面")
        editor.reload()
        headers = [
            editor.table.horizontalHeaderItem(index).text()
            for index in range(editor.table.columnCount())
        ]
        axis_col = next(index for index, text in enumerate(headers) if "柱轴方位角" in text)
        a4_col = next(index for index, text in enumerate(headers) if "非球面 A4" in text)
        assert editor.table.item(0, axis_col).text() != "未使用"
        assert editor.table.item(1, axis_col).text() == "未使用"
        assert not (editor.table.item(1, axis_col).flags() & Qt.ItemFlag.ItemIsEditable)
        assert editor.table.item(1, a4_col).text() != "未使用"
        assert editor.table.item(0, a4_col).text() == "未使用"
        assert editor.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    finally:
        editor.close()
        app.processEvents()
