from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QWidget

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.shared.plotting.engineering_views import (
    build_multi_plane_evolution,
    rebuild_multi_plane_evolution_range,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(count: int = 12) -> None:
    app = _app()
    for _ in range(count):
        app.processEvents()


def test_shell_is_two_mode_without_legacy_feature_windows():
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1200, 760)
    window.show()
    try:
        _pump()
        assert not hasattr(window, "command_buttons")
        assert not hasattr(window, "open_feature_window")
        assert not hasattr(window, "_pages")
        assert getattr(window, "canvas_workspace", None) is None
        assert window.findChild(QWidget, "canvasHost") is None
        assert window.findChild(QWidget, "WorkbenchShell") is window.workbench
        assert window.findChild(QWidget, "TeachingShell") is window.teaching
        window.navigate("simulation")
        assert window.mode_stack.currentWidget() is window.workbench
        window.navigate("teaching")
        assert window.mode_stack.currentWidget() is window.teaching
    finally:
        window.close()
        app.processEvents()


def test_multi_plane_auto_range_is_capped_and_axial_range_can_be_rebuilt():
    n = 129
    yy, xx = np.indices((n, n), dtype=float)
    center = (n - 1) / 2
    frame = np.exp(-((xx - center) ** 2 + (yy - center) ** 2) / (2 * 12.0**2))
    beam = {"z": frame.tolist()}
    waist = {
        "metrics": {
            "waist_x_um": 12.0,
            "waist_y_um": 11.0,
            "waist_x_z_mm": 0.0,
            "waist_y_z_mm": 0.0,
            "rayleigh_x_mm": 16700.0,
            "rayleigh_y_mm": 14500.0,
        }
    }
    result = build_multi_plane_evolution({}, beam, waist, source="test")
    assert result["range_mm"] == [-12.0, 12.0]
    assert result["auto_range_capped"] is True
    assert len(result["planes"]) == 7

    linked = rebuild_multi_plane_evolution_range(result, -2.0, 2.0, 7)
    assert linked["range_mm"] == [-2.0, 2.0]
    z_values = [float(plane["z"]) for plane in linked["planes"]]
    assert min(z_values) >= -2.0 - 1e-9
    assert max(z_values) <= 2.0 + 1e-9
    assert len(z_values) == 7


def test_inline_metric_value_reserves_safe_cjk_text_height():
    from frontend_pyside.shared.components.foundation.metrics import InlineMetric

    _app()
    metric = InlineMetric("耦合效率", "99.50", "%")
    assert metric.value_label.minimumHeight() >= 28
