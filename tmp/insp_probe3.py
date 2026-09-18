import os, sys, tempfile
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-insp-dbg-")
sys.path.insert(0, r"D:\AAAWorkspace\optical_self")
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
print("param editors:", len(insp._param_editors), list(insp._param_editors)[:14])
for name, editor in insp._param_editors.items():
    if editor.height() > 100:
        print("  tall editor:", name, editor.height(), editor.sizeHint())
for lbl in insp.object_body.findChildren(QLabel):
    if lbl.objectName() == "teachingV2UnitLabel" and lbl.height() > 100:
        print("  tall unit chip:", repr(lbl.text()), lbl.height(), "parent:", lbl.parentWidget())
secret = [w for w in insp.object_body.findChildren(QLabel) if len(w.text()) > 40]
for w in secret[:5]:
    print("  long label:", w.height(), w.text()[:40])
sys.stdout.flush(); os._exit(0)
