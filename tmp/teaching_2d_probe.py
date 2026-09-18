"""Render the teaching plan (2D) canvas to PNGs, including a wheel-zoom check.

Usage:  py -3 tmp/teaching_2d_probe.py <prefix> [lens_count]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="optical-2d-probe-")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import TeachingShell
from frontend_pyside.core.ui_theme import apply_application_theme


def wait(ms: int = 200) -> None:
    QTest.qWait(ms)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def wheel(view, delta: int, times: int = 1, at=None) -> None:
    for _ in range(times):
        point = at or view.viewport().rect().center()
        event = QWheelEvent(
            QPointF(point), view.viewport().mapToGlobal(point), QPoint(0, 0), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
        )
        QApplication.sendEvent(view.viewport(), event)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()


def main() -> int:
    prefix = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp" / "teaching_2d"
    lens_count = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    app = QApplication.instance() or QApplication([])
    apply_application_theme(app)
    shell = TeachingShell(create_app_context())
    shell.resize(1400, 860)
    # 探针窗口开在真实桌面上，忽略鼠标避免误拖器件。
    shell.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    shell.show()
    for _ in range(12):
        wait(150)
    shell._apply_scheme(lens_count)
    wait(250)
    shell.canvas_mode.setCurrentText("二维")
    wait(400)
    view = shell.view
    print("mode:", shell.canvas_mode.currentText(), "m11:", round(view.transform().m11(), 4),
          "fitted viewport:", view._fitted_viewport.width(), "x", view._fitted_viewport.height())
    view.grab().save(str(prefix.with_name(prefix.name + "_fitted.png")))
    wheel(view, 120, 8)
    print("after 8 wheel-up:", round(view.transform().m11(), 4))
    view.grab().save(str(prefix.with_name(prefix.name + "_zoomed.png")))
    wheel(view, -120, 16)
    print("after 16 wheel-down:", round(view.transform().m11(), 4))
    view.grab().save(str(prefix.with_name(prefix.name + "_out.png")))
    print("saved", prefix.with_name(prefix.name + "_{fitted,zoomed,out}.png"))
    shell.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
