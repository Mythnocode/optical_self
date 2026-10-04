"""Capture the original simulation editor and its property pages offscreen."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
isolation = Path(tempfile.mkdtemp(prefix="optical-simulation-baseline-"))
os.environ.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(isolation / "appdata"), LOCALAPPDATA=str(isolation / "localappdata"), OPTICAL_USAGE_DIR=str(isolation / "usage"))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QToolButton
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.app.bootstrap import create_main_window

app = QApplication([])
app.setOrganizationName("OpticalMigrationVisualCapture")
app.setApplicationName("SimulationBaseline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation / "settings"))
apply_application_theme(app)
window = create_main_window()
window.resize(1280, 800)
window.show()
output = ROOT / "tests/golden/ui-baseline"
output.mkdir(parents=True, exist_ok=True)

def captures():
    try:
        window.open_document("simulation", "lens_data")
        document = next(widget for widget in window.workbench._widgets.values() if hasattr(widget, "editor"))
        editor = document.editor
        for _ in range(4): app.processEvents()
        window.grab().save(str(output / "simulation-lens-data.png"))
        geometry = {}
        for name, widget in {"table": editor.table, "card": editor.table_card}.items():
            position = widget.mapTo(window, widget.rect().topLeft())
            geometry[name] = [position.x(), position.y(), widget.width(), widget.height()]
        (output / "simulation-geometry.json").write_text(json.dumps(geometry, indent=2), encoding="utf-8")
        fonts = [{"name": button.objectName(), "text": button.text(), "family": button.font().family(), "weight": int(button.font().weight()), "point_size": button.font().pointSizeF()} for button in window.findChildren(QToolButton) if button.objectName() in {"PrimaryModuleButton", "SecondaryFunctionButton"}]
        (output / "simulation-fonts.json").write_text(json.dumps(fonts, ensure_ascii=False, indent=2), encoding="utf-8")
        headers = [editor.table.horizontalHeaderItem(index).text() for index in range(editor.table.columnCount())]
        (output / "simulation-columns.json").write_text(json.dumps(headers, ensure_ascii=False, indent=2), encoding="utf-8")
        rail = window.workbench.object_rail
        for key in ("source", "fiber", "environment", "field", "detector", "materials"):
            rail._sections[key].header.setChecked(True)
            for _ in range(4): app.processEvents()
            window.grab().save(str(output / f"simulation-inspector-{key}.png"))
            from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QCheckBox
            widgets = rail._sections[key].findChildren(QComboBox) + rail._sections[key].findChildren(QDoubleSpinBox) + rail._sections[key].findChildren(QLabel) + rail._sections[key].findChildren(QCheckBox)
            bounds = []
            for widget in widgets:
                position = widget.mapTo(window, widget.rect().topLeft())
                text = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
                bounds.append({"kind": type(widget).__name__, "text": text, "bounds": [position.x(), position.y(), widget.width(), widget.height()], "enabled": widget.isEnabled(), "visible": widget.isVisible(), "font_size": widget.font().pointSizeF(), "font_weight": int(widget.font().weight())})
            (output / f"simulation-inspector-{key}-geometry.json").write_text(json.dumps(bounds, ensure_ascii=False, indent=2), encoding="utf-8")
            rail._sections[key].header.setChecked(False)
        rail._sections["source"].header.setChecked(True)
        for index, name in ((1, "pupil"), (2, "point")):
            rail.source_inspector.mode.setCurrentIndex(index)
            for _ in range(4): app.processEvents()
            window.grab().save(str(output / f"simulation-inspector-source-{name}.png"))
        rail.source_inspector.mode.setCurrentIndex(0)
        rail._sections["source"].header.setChecked(False)
        rail._sections["fiber"].header.setChecked(True)
        for index, name in ((1, "lp01"), (2, "he11"), (3, "imported")):
            rail.fiber_inspector.model.setCurrentIndex(index)
            for _ in range(4): app.processEvents()
            window.grab().save(str(output / f"simulation-inspector-fiber-{name}.png"))
        rail.fiber_inspector.model.setCurrentIndex(0)
        rail._sections["fiber"].header.setChecked(False)
        from frontend_pyside.modules.simulation.settings import CombinedSettingsDialog
        settings = CombinedSettingsDialog(window.context, window, calculation=window.workbench._calculation_state, alignment=window.workbench._alignment_state)
        settings.show()
        for _ in range(4): app.processEvents()
        settings.grab().save(str(output / "simulation-compute-settings.png"))
        from PySide6.QtWidgets import QScrollArea
        settings.compute.findChild(QScrollArea).verticalScrollBar().setValue(100000)
        for _ in range(4): app.processEvents()
        settings.grab().save(str(output / "simulation-compute-settings-alignment.png"))
        settings.close()
        editor._open_properties_dialog()
        for index in range(4):
            editor.property_tabs.setCurrentIndex(index)
            for _ in range(4): app.processEvents()
            editor.properties_dialog.grab().save(str(output / f"simulation-properties-{index}.png"))
        print(json.dumps({"columns": headers, "column_widths": [editor.table.columnWidth(i) for i in range(editor.table.columnCount())], "visual_indices": [editor.table.horizontalHeader().visualIndex(i) for i in range(editor.table.columnCount())], "dialog": [editor.properties_dialog.width(), editor.properties_dialog.height()]}, ensure_ascii=False))
    finally:
        window.context.services.usage.close()
        app.quit()

QTimer.singleShot(500, captures)
app.exec()
