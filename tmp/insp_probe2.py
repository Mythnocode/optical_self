"""Render the inspector with 更多参数 expanded (real display, no engine)."""
import os, sys, tempfile
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-insp-expanded-")
ROOT = Path(r"D:\AAAWorkspace\optical_self")
sys.path.insert(0, str(ROOT))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import TeachingShell
from frontend_pyside.core.ui_theme import apply_application_theme

app = QApplication.instance() or QApplication([])
apply_application_theme(app)
shell = TeachingShell(create_app_context())
shell.show()
for _ in range(6):
    QTest.qWait(150); app.processEvents()
shell._apply_scheme(2)
shell.store.select("lens-002")
for _ in range(6):
    QTest.qWait(150); app.processEvents()
insp = shell.inspector
insp.show()
for _ in range(4):
    QTest.qWait(150); app.processEvents()
insp.detail_button.setChecked(True)
for _ in range(8):
    QTest.qWait(200); app.processEvents()
heights = sorted({e.height() for e in insp._pose_editors.values()} |
                 {e.height() for e in insp._param_editors.values() if hasattr(e, "height")} |
                 {lbl.height() for lbl in insp.object_body.findChildren(QLabel)
                  if lbl.objectName() == "teachingV2UnitLabel"})
print("heights:", heights)
print("vbar visible:", insp.object_scroll.verticalScrollBar().isVisible(),
      "body hint:", insp.object_body.sizeHint().height(), "viewport:", insp.object_scroll.viewport().height())
insp.resize(insp.width(), min(760, insp.object_body.sizeHint().height() + 8))
for _ in range(4):
    QTest.qWait(150); app.processEvents()
insp.grab().save(str(ROOT / "tmp" / "inspector_expanded.png"))
print("saved")
sys.stdout.flush(); os._exit(0)
