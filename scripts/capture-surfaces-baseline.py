"""Render original surface dialogs and record their client geometry for visual review."""
from pathlib import Path
import json
import os
import sys
import tempfile
import copy
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
isolation = Path(tempfile.mkdtemp(prefix="optical-surfaces-baseline-"))
os.environ.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(isolation / "appdata"), LOCALAPPDATA=str(isolation / "localappdata"), OPTICAL_USAGE_DIR=str(isolation / "usage"))
from PySide6.QtCore import QSettings, QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QAbstractSpinBox, QCheckBox
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.features.simulation.components.optical_system_editor import OpticalSystemEditor
from shared_presentation.surface_registry import SURFACE_TYPES, apply_type_defaults
from shared_presentation.surface_payloads import _surface_type

app = QApplication([])
app.setOrganizationName("OpticalMigrationVisualCapture")
app.setApplicationName("SurfacesBaseline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation / "settings"))
apply_application_theme(app)
window = create_main_window(); window.resize(1280, 800); window.show()
output = ROOT / "tests/golden/ui-baseline/surfaces"; output.mkdir(parents=True, exist_ok=True)
geometry = {}

def table_columns(editor):
    columns = []
    for i in range(editor.table.columnCount()):
        text = editor.table.horizontalHeaderItem(i).text()
        preferred = editor.table.columnWidth(i)
        if editor.COL_COMMON_COUNT <= i < editor.table.columnCount() - 1:
            preferred = max(120, min(240, editor.table.fontMetrics().horizontalAdvance(text) + 28))
        columns.append({"text": text, "width": editor.table.columnWidth(i), "hidden": editor.table.isColumnHidden(i), "preferred_width": preferred})
    return columns

def capture(name, widget):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(6): app.processEvents()
    widget.grab().save(str(output / f"{name}.png"))
    rows = []
    for child in widget.findChildren(QWidget):
        if not child.isVisible() or not isinstance(child, (QLabel, QPushButton, QLineEdit, QComboBox, QAbstractSpinBox, QCheckBox)): continue
        position = child.mapTo(widget, child.rect().topLeft())
        text = child.currentText() if isinstance(child, QComboBox) else child.text() if hasattr(child, "text") else ""
        rows.append({"kind": type(child).__name__, "text": text, "bounds": [position.x(), position.y(), child.width(), child.height()], "enabled": child.isEnabled(), "font_size": child.font().pointSizeF(), "font_family": child.font().family()})
    geometry[name] = {"size": [widget.width(), widget.height()], "widgets": rows}

def captures():
    try:
        window.open_document("simulation", "lens_data")
        editor = window.findChild(OpticalSystemEditor)
        original_surfaces = copy.deepcopy(editor.context.project.surfaces)
        capture("default-table", window)
        for spec in SURFACE_TYPES:
            apply_type_defaults(editor.context.project.surfaces[0], spec.name)
            editor.reload(); editor.table.setCurrentCell(0, editor.COL_NAME); editor._select(0)
            editor._open_properties_dialog()
            for tab, name in ((0, "common"), (1, "profile"), (2, "dynamic"), (3, "engineering")):
                editor.property_tabs.setCurrentIndex(tab)
                capture(f"{_surface_type(spec.name)}-{name}", editor.properties_dialog)
            editor.properties_dialog.close()
            capture(f"{_surface_type(spec.name)}-table", window)
            geometry[f"{_surface_type(spec.name)}-table"]["columns"] = table_columns(editor)
        for spec in SURFACE_TYPES:
            editor.context.project.surfaces = copy.deepcopy(original_surfaces)
            editor.reload(); editor.table.setCurrentCell(0, editor.COL_NAME)
            editor._add_surface_type(spec.name)
            for tab, name in ((0, "common"), (1, "profile"), (2, "dynamic"), (3, "engineering")):
                editor.property_tabs.setCurrentIndex(tab)
                capture(f"new-{_surface_type(spec.name)}-{name}", editor.properties_dialog)
            if spec.name == "球面":
                editor.property_tabs.setCurrentIndex(0)
                editor.radius.setFocus()
                capture("new-spherical-focused", editor.properties_dialog)
                editor.radius.lineEdit().setText("-123456789.12345678")
                capture("new-spherical-long-input", editor.properties_dialog)
                editor.radius.clearFocus()
                editor.radius.setValue(50)
            if spec.name == "坐标断点":
                editor.property_tabs.setCurrentIndex(2)
                editor._dynamic_controls["decenter_x_mm"].setValue(2.25)
                editor._dynamic_controls["tilt_y_deg"].setValue(-12.5)
                editor._apply()
                capture("coordinate_break-edited", editor.properties_dialog)
            editor.properties_dialog.close()
            capture(f"new-{_surface_type(spec.name)}-table", window)
            geometry[f"new-{_surface_type(spec.name)}-table"]["columns"] = table_columns(editor)
        (output / "geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"captures": len(geometry)}, ensure_ascii=False))
    finally:
        window.context.services.usage.close(); app.quit()
QTimer.singleShot(500, captures)
app.exec()
