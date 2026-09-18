"""Render the home page and click each workflow card (real display)."""
import os, sys, tempfile
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-home-")
ROOT = Path(r"D:\AAAWorkspace\optical_self")
sys.path.insert(0, str(ROOT))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.core.ui_theme import apply_application_theme
from frontend_pyside.modules.home.shell import HOME_SECTIONS

app = QApplication.instance() or QApplication([])
apply_application_theme(app)
window = MainWindow(create_app_context())
window.resize(1800, 1000)
window.show()
for _ in range(8):
    QTest.qWait(150); app.processEvents()
window.navigate("home")
for _ in range(6):
    QTest.qWait(150); app.processEvents()
window.grab().save(str(ROOT / "tmp" / "home_after.png"))
print("sections:", [(s.key, len(s.nodes)) for s in HOME_SECTIONS], flush=True)
# 每张卡片点一遍，确认都能落到目标页面
for section in HOME_SECTIONS:
    for node in section.nodes:
        window.navigate("home")
        QTest.qWait(120); app.processEvents()
        window._open_workflow_node(node.module, node.kind)
        QTest.qWait(200); app.processEvents()
        current = type(window.mode_stack.currentWidget()).__name__
        print(f"  {section.key:14s} {node.kind:20s} -> {current}", flush=True)
sys.stdout.flush(); os._exit(0)
