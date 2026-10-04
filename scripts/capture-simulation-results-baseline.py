"""Record original result pages and widget bounds for migration acceptance."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
isolation = Path(tempfile.mkdtemp(prefix="optical-results-baseline-"))
os.environ.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(isolation / "appdata"), LOCALAPPDATA=str(isolation / "localappdata"), OPTICAL_USAGE_DIR=str(isolation / "usage"))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.app.bootstrap import create_main_window

app = QApplication([])
app.setOrganizationName("OpticalMigrationVisualCapture")
app.setApplicationName("ResultBaseline")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(isolation / "settings"))
apply_application_theme(app)
window = create_main_window()
window.resize(1280, 800)
window.show()
output = ROOT / "tests/golden/ui-baseline/simulation-results"
output.mkdir(parents=True, exist_ok=True)
geometry = {}

def capture(kind, state, document):
    for _ in range(6): app.processEvents()
    window.grab().save(str(output / f"{kind}-{state}.png"))
    widgets = {}
    for name in ("workspace", "coup", "center", "source", "_text", "text_button", "zoom_button", "export_button"):
        widget = getattr(document, name, None)
        if widget is not None and widget.isVisible():
            position = widget.mapTo(window, widget.rect().topLeft())
            widgets[name] = [position.x(), position.y(), widget.width(), widget.height()]
    for widget in document.findChildren(__import__('PySide6.QtWidgets', fromlist=['QWidget']).QWidget):
        if widget.isVisible() and (widget.objectName() or type(widget).__name__ in {"PlotCanvas", "FastHeatmapWidget", "QPushButton"}):
            pos = widget.mapTo(window, widget.rect().topLeft())
            widgets[f"{type(widget).__name__}:{widget.objectName()}"] = [pos.x(), pos.y(), widget.width(), widget.height()]
    geometry[f"{kind}-{state}"] = {"widgets": widgets, "fonts": [{"text": w.text(), "family": w.font().family(), "size": w.font().pointSizeF(), "weight": int(w.font().weight())} for w in document.findChildren(__import__('PySide6.QtWidgets', fromlist=['QLabel']).QLabel) if w.isVisible()]}
    if state == "completed":
        (output / f"{kind}-plot.json").write_text(json.dumps(document._last_plot, ensure_ascii=False, default=lambda value: value.tolist() if hasattr(value, "tolist") else value.item()), encoding="utf-8")
        if kind == "layout_3d":
            from frontend_pyside.shared.plotting.canvas import PlotCanvas
            from mpl_toolkits.mplot3d import proj3d
            import numpy as np
            canvas = document.findChild(PlotCanvas)
            ax = canvas._axis
            vertices = np.asarray([point for ray in document._last_plot["rays"] for point in ray["points"]])[:, [2, 0, 1]]
            projected = np.column_stack(proj3d.proj_transform(*vertices.T, ax.get_proj()))
            origin = canvas.mapTo(window, canvas.rect().topLeft())
            pixels = ax.transData.transform(projected[:, :2])
            pixels[:, 0] += origin.x()
            pixels[:, 1] = origin.y() + canvas.height() - pixels[:, 1]
            (output / "layout_3d-projection.json").write_text(json.dumps({"projection": ax.get_proj().tolist(), "vertices": vertices.tolist(), "pixels": pixels.tolist(), "canvas": [origin.x(), origin.y(), canvas.width(), canvas.height()]}, ensure_ascii=False), encoding="utf-8")

def captures():
    try:
        kinds = ("ray_layout", "spot", "coupling", "wavefront", "layout_3d")
        for kind in kinds:
            if kind == "layout_3d": window.open_document("simulation", "ray_layout")
            window.open_document("simulation", kind)
            document = next(w for w in window.workbench._widgets.values() if getattr(w, "kind", "") == kind)
            capture(kind, "empty", document)
        fixtures = ROOT / "tests/golden/simulation/results"
        window.context.project.set_simulation_project_payload(json.loads((fixtures / "reference-project.json").read_text(encoding="utf-8")))
        window.context.project.set_formal_result(json.loads((fixtures / "reference-result.json").read_text(encoding="utf-8")))
        for kind in kinds:
            if kind == "layout_3d": window.open_document("simulation", "ray_layout")
            window.open_document("simulation", kind)
            document = next(w for w in window.workbench._widgets.values() if getattr(w, "kind", "") == kind)
            capture(kind, "completed", document)
        (output / "geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(geometry, ensure_ascii=False))
    finally:
        window.context.services.usage.close()
        app.quit()

QTimer.singleShot(500, captures)
app.exec()
