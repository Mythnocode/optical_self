"""Measure the teaching inspector layout on the real display (no engine)."""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-insp-probe-")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel
from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import TeachingShell
from frontend_pyside.core.ui_theme import apply_application_theme


def wait(ms=200):
    QTest.qWait(ms)
    app = QApplication.instance()
    if app:
        app.processEvents()


app = QApplication.instance() or QApplication([])
apply_application_theme(app)
shell = TeachingShell(create_app_context())
shell.resize(1200, 800)
shell.show()
for _ in range(6):
    wait(150)
shell._apply_scheme(2)
shell.store.select("lens-002")
wait(300)
insp = shell.inspector
insp.show()
wait(300)
print("popup size:", insp.size(), "hint:", insp.sizeHint(), "min:", insp.minimumSizeHint())
body = insp.object_body
print("body size:", body.size(), "hint:", body.sizeHint(), "minHint:", body.minimumSizeHint())
print("scroll viewport:", insp.object_scroll.viewport().size(),
      "hbar visible:", insp.object_scroll.horizontalScrollBar().isVisible())
print("hint label:", insp.object_body.findChildren(QLabel)[-3].text()[:30] if insp.object_body.findChildren(QLabel) else None)
spin_heights, unit_heights, spin_widths, pixel_sizes = set(), set(), set(), set()
for lbl in insp.object_body.findChildren(QLabel):
    if len(lbl.text()) > 20:
        print("long label sizeHint:", lbl.sizeHint().width(), lbl.text()[:26])
for name, editor in insp._pose_editors.items():
    spin_heights.add(editor.height())
    spin_widths.add(editor.width())
    pixel_sizes.add(editor.fontMetrics().height())
    holder = editor.parentWidget()
    for label in holder.findChildren(QLabel):
        unit_heights.add(label.height())
print("spin heights:", spin_heights, "widths:", spin_widths, "font px:", pixel_sizes)
print("unit label heights:", unit_heights)
insp.grab().save(str(ROOT / "tmp" / "inspector_live.png"))
sys.stdout.flush()
os._exit(0)
