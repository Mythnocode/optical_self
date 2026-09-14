from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.shared.plotting.fast_heatmap import fitted_physical_rect, physical_span


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_heatmap_letterboxes_physical_aspect():
    _app()
    available = QRect(0, 0, 400, 200)
    rect = fitted_physical_rect(available, 50.0, 50.0)
    assert rect.width() == rect.height() == 200
    assert rect.x() == 100
    wide = fitted_physical_rect(QRect(10, 20, 200, 200), 80.0, 40.0)
    assert wide.width() == 200
    assert wide.height() == 100
    assert wide.y() == 70
    span_x, span_y = physical_span({"x": [-20.0, 20.0], "y": [-10.0, 10.0]})
    assert span_x == 40.0
    assert span_y == 20.0


def test_main_window_backend_status_is_not_window_tooltip():
    app = _app()
    window = MainWindow(create_app_context())
    try:
        window._backend_status("后端已连接", "ok")
        assert window.toolTip() == ""
        assert "后端已连接" in window.windowTitle()
    finally:
        window.close()
        app.processEvents()
