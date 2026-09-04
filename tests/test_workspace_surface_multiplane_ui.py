from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QWidget

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.features.simulation.windows.lens_editor import LensEditorWindow
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


def test_top_navigation_uses_real_workspace_boundaries():
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1200, 760)
    window.show()
    try:
        _pump()
        assert {key: button.text() for key, button in window.command_buttons.items()} == {
            "simulation": "仿真",
            "optimization": "优化",
            "surrogate": "代理模型",
            "explainability": "模型解释",
            "teaching": "教学",
        }
        for action, expected in (
            ("simulation", "simulation"),
            ("optimization", "optimization"),
            ("machine_learning", "surrogate"),
            ("explainability", "explainability"),
            ("teaching", "teaching"),
        ):
            window.navigate(action, update_document=False)
            _pump(6)
            checked = [key for key, button in window.command_buttons.items() if button.isChecked()]
            assert checked == [expected]
    finally:
        window.close()
        app.processEvents()


def test_sequential_surface_editor_has_no_permanent_tree_or_inspector_and_allows_three_surface_group():
    app = _app()
    context = create_app_context()
    editor = LensEditorWindow(context.project)
    editor.resize(1200, 700)
    editor.show()
    try:
        _pump()
        assert editor.findChild(QWidget, "lensElementTree") is None
        assert editor.findChild(QWidget, "surfacePropertyDialog") is not None
        assert editor.editor.search.isVisible() is False

        group_id = str(context.project.project.surfaces[0].group_id)
        before = sum(1 for surface in context.project.project.surfaces if str(surface.group_id) == group_id)
        assert before == 2
        editor.editor.table.setCurrentCell(0, editor.editor.COL_NAME)
        editor.editor._add_surface_to_current_group()
        _pump()
        after = sum(1 for surface in context.project.project.surfaces if str(surface.group_id) == group_id)
        assert after == 3
        assert len(context.project.project.surfaces) == 9

        editor._open_surface_properties(1)
        _pump()
        assert editor.property_dialog.isModal() is False
        assert editor.property_dialog.isSizeGripEnabled() is True
        old = editor.property_dialog.size()
        editor.property_dialog.resize(old.width() + 80, old.height() - 40)
        _pump()
        assert editor.property_dialog.width() == old.width() + 80
    finally:
        editor.close()
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
            # Deliberately absurd fitted Rayleigh ranges: the UI must not produce
            # a tens-of-metres multi-plane plot from these values.
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
