"""Check the unit chips fit their text (real display)."""
import os, sys, tempfile
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-insp-unit-")
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
insp.show(); insp.detail_button.setChecked(True)
for _ in range(8):
    QTest.qWait(200); app.processEvents()
bad = []
for lbl in insp.object_body.findChildren(QLabel):
    if lbl.objectName() != "teachingV2UnitLabel":
        continue
    need = lbl.fontMetrics().horizontalAdvance(lbl.text())
    inner = lbl.width() - 2 * 5 - 2      # QSS padding 1px 5px + border
    if inner < need:
        bad.append((lbl.text(), lbl.width(), need))
heights = sorted({e.height() for e in insp._pose_editors.values()} |
                 {lbl.height() for lbl in insp.object_body.findChildren(QLabel)
                  if lbl.objectName() == "teachingV2UnitLabel"})
print("unit chip widths:", sorted({lbl.width() for lbl in insp.object_body.findChildren(QLabel)
                                   if lbl.objectName() == "teachingV2UnitLabel"}))
print("clipped unit chips:", bad)
print("heights:", heights)
print("hbar:", insp.object_scroll.horizontalScrollBar().isVisible())
insp.resize(insp.width(), min(720, insp.object_body.sizeHint().height() + 8))
for _ in range(4):
    QTest.qWait(150); app.processEvents()
insp.grab().save(str(ROOT / "tmp" / "inspector_units.png"))
print("saved")
sys.stdout.flush(); os._exit(0)
