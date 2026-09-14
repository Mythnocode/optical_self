from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from frontend_pyside.shared.plotting.canvas import PlotCanvas


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(count: int = 12) -> None:
    app = _app()
    for _ in range(count):
        app.processEvents()
        QTest.qWait(8)


def test_embedded_line_plot_reserves_title_and_axis_label_margins():
    _app()
    canvas = PlotCanvas()
    canvas.resize(900, 340)
    canvas.set_plot(
        {
            "kind": "line_multi",
            "x": list(range(1, 10)),
            "series": [{"label": "验证集", "y": [9 - i * 0.6 for i in range(9)]}],
            "title": "真实训练历史",
            "x_label": "训练轮次",
            "y_label": "验证误差",
        }
    )
    try:
        _pump(5)
        params = canvas.figure.subplotpars
        assert params.left >= 0.15
        assert params.bottom >= 0.24
        assert params.top <= 0.86
        assert params.right >= 0.96
    finally:
        canvas.close()
