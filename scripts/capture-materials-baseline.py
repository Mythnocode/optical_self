"""Record original material library and dialog content for visual migration."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
isolation = Path(tempfile.mkdtemp(prefix="optical-materials-baseline-"))
os.environ.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(isolation / "appdata"), LOCALAPPDATA=str(isolation / "localappdata"), OPTICAL_USAGE_DIR=str(isolation / "usage"))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QDoubleSpinBox
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.app.bootstrap import create_main_window
from frontend_pyside.features.simulation.material_library import MaterialDetailDialog, CustomMaterialDialog, all_material_records, used_lens_materials, custom_material_records

app = QApplication([])
app.setOrganizationName("OpticalMigrationVisualCapture")
app.setApplicationName("MaterialsBaseline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation / "settings"))
apply_application_theme(app)
window = create_main_window()
window.resize(1280, 800)
window.show()
output = ROOT / "tests/golden/ui-baseline/materials"
output.mkdir(parents=True, exist_ok=True)
geometry = {}

def capture(name, widget):
    for _ in range(6): app.processEvents()
    widget.grab().save(str(output / f"{name}.png"))
    rows = []
    for child in widget.findChildren(QWidget):
        if not child.isVisible() or not isinstance(child, (QLabel, QPushButton, QLineEdit, QComboBox, QDoubleSpinBox)): continue
        position = child.mapTo(widget, child.rect().topLeft())
        text = child.currentText() if isinstance(child, QComboBox) else child.text()
        rows.append({"kind": type(child).__name__, "text": text, "bounds": [position.x(), position.y(), child.width(), child.height()], "font_family": child.font().family(), "font_size": child.font().pointSizeF(), "font_weight": int(child.font().weight()), "coefficient_width": child.fontMetrics().horizontalAdvance("1.03961, 0.0774642, 0.231792, 0.141485,")})
    geometry[name] = {"size": [widget.width(), widget.height()], "widgets": rows}

def captures():
    try:
        project = window.context.project.project
        records = all_material_records(project, float(project.wavelength_nm))
        used = used_lens_materials(project, float(project.wavelength_nm))
        (output / "records.json").write_text(json.dumps({"wavelength_nm": project.wavelength_nm, "records": records, "used": used}, ensure_ascii=False, indent=2), encoding="utf-8")
        window.open_document("simulation", "lens_data")
        rail = window.workbench.object_rail
        rail._sections["materials"].header.setChecked(True)
        capture("used", window)
        detail = MaterialDetailDialog(used[0], window)
        detail.show(); capture("detail-builtin", detail); detail.close()
        window.open_document("simulation", "material_library")
        document = next(w for w in window.workbench._widgets.values() if getattr(w, "kind", "") == "material_library")
        capture("library", window)
        position = document.table.mapTo(window, document.table.rect().topLeft())
        geometry["library"]["table"] = [position.x(), position.y(), document.table.width(), document.table.height()]
        geometry["library"]["columns"] = [document.table.columnWidth(i) for i in range(4)]
        geometry["library"]["header_height"] = document.table.horizontalHeader().height()
        geometry["library"]["row_height"] = document.table.rowHeight(0)
        document.search.setText("N-BK7"); capture("library-filtered", window)
        for name, model in (("constant", 0), ("cauchy", 1), ("sellmeier", 2)):
            dialog = CustomMaterialDialog(parent=window)
            dialog.model.setCurrentIndex(model)
            dialog.show(); capture(f"custom-{name}", dialog); dialog.close()
        record = {"name": "QA-Cauchy", "custom": True, "model": "cauchy", "a": 1.45, "b_um2": .004, "c_um4": .0001, "n": 1.456,
            "wavelength_nm": 780}
        record = custom_material_records(SimpleNamespace(custom_materials=[record]), 780)[0]
        detail = MaterialDetailDialog(record, window)
        detail.show(); capture("detail-custom", detail); detail.close()
        (output / "geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"catalog_count": len(records), "used": [r["name"] for r in used], "table": geometry["library"]["table"], "columns": geometry["library"]["columns"], "header_height": geometry["library"]["header_height"], "row_height": geometry["library"]["row_height"]}, ensure_ascii=False))
    finally:
        window.context.services.usage.close()
        app.quit()

QTimer.singleShot(500, captures)
app.exec()
