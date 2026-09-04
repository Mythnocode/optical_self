from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.optimization.page import OptimizationPage
from frontend_pyside.features.simulation.windows.lens_editor import LensEditorWindow
from frontend_pyside.features.teaching.page import TeachingPage
from optical_runtime.dependency_graph import build_project_dependency_keys


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(count: int = 15) -> None:
    app = _app()
    for _ in range(count):
        app.processEvents()
        QTest.qWait(5)


def _right_in_viewport(widget, viewport) -> int:
    top_left = widget.mapTo(viewport, QPoint(0, 0))
    return int(top_left.x() + widget.width())


def test_teaching_mismatch_panel_reflows_within_768_portrait_viewport():
    _app()
    page = TeachingPage(create_app_context())
    page.resize(768, 1366)
    page.show()
    try:
        _pump()
        page._show_exploration("mismatch", "lateral")
        _pump(30)
        assert page.workspace_splitter.orientation() == Qt.Orientation.Vertical
        viewport = page.page_scroll.viewport()
        assert viewport.width() >= 730
        panel = page.exploration_panel
        # These were the controls visibly clipped in the previous 768x1366 audit.
        for widget in (
            panel.mismatch_selector,
            panel.mismatch_value,
            panel.mismatch_observe,
            panel.mismatch_adjustment,
            panel.return_button,
        ):
            assert _right_in_viewport(widget, viewport) <= viewport.width() + 2
        assert page.page_scroll.horizontalScrollBar().maximum() == 0
        # Compact teaching uses the single outer page scroll instead of compression.
        assert page.page_scroll.verticalScrollBar().maximum() > 0
    finally:
        page.close()
        _pump(3)


def test_surface_common_numeric_column_really_enters_inline_editor_on_double_click():
    _app()
    context = create_app_context()
    window = LensEditorWindow(context.project)
    window.resize(1100, 680)
    window.show()
    try:
        _pump(20)
        editor = window.editor
        table = editor.table
        row, col = 0, editor.COL_RADIUS
        index = table.model().index(row, col)
        point = table.visualRect(index).center()
        # Real user sequence: select the row/cell, then double-click the common field.
        QTest.mouseClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        _pump(3)
        QTest.mouseDClick(table.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        _pump(10)
        visible_editors = [child for child in table.findChildren(QDoubleSpinBox) if child.isVisible()]
        assert visible_editors, "double-click should open the numeric delegate editor"
        assert not window.property_dialog.isVisible(), "common inline edit must not be stolen by the advanced dialog"
        spin = visible_editors[-1]
        spin.setValue(35.5)
        QTest.keyClick(spin, Qt.Key_Enter)
        _pump(10)
        assert float(context.project.project.surfaces[row].radius_mm) == 35.5
    finally:
        window.close()
        _pump(3)


def test_optimization_terminal_result_height_reserves_plot_provenance_and_actions():
    _app()
    page = OptimizationPage(create_app_context())
    page.resize(1050, 700)
    page.show()
    try:
        _pump(20)
        # Mimic the rows revealed only after an optimisation task reaches terminal state.
        page.preview_best_design_button.show()
        page.apply_best_design_button.show()
        page.verify_best_design_button.show()
        page.compact_tolerance_button.show()
        page.result_provenance.show()
        page.main_result_panel.updateGeometry()
        _pump(10)
        page._sync_task_content_height()
        _pump(10)
        panel_min = page.main_result_panel.minimumSizeHint().height()
        assert page.main_splitter.minimumHeight() >= panel_min
        # In the real result panel the 360 px plot must end before provenance starts.
        result_bottom = page.main_result.y() + page.main_result.height()
        assert page.result_provenance.y() >= result_bottom
    finally:
        page.close()
        _pump(3)


def test_native_gui_tilt_unit_is_part_of_overlap_dependency_key():
    project = {
        "source": {"wavelength_nm": 780.0},
        "receiver": {"tilt_x_deg": 0.0, "tilt_y_deg": 0.0},
        "surfaces": [],
    }
    key0 = build_project_dependency_keys(project, {"hybrid": {"tilt_x_urad": 0.0}})["overlap"]
    key20 = build_project_dependency_keys(project, {"hybrid": {"tilt_x_urad": 20_000.0}})["overlap"]
    assert key0 != key20


def test_automatic_numerics_restores_scaled_fresnel_even_from_stale_manual_profile(monkeypatch):
    from PySide6.QtWidgets import QWidget
    from frontend_pyside.features.simulation.components.parameter_tabs import SimpleParameterTabs
    from frontend_pyside.shared.settings import SimulationNumericsProfileStore

    stale = {
        "automatic": True,
        "precision": "257×257",
        "grid_size": 257,
        "pupil_sample_count": 49,
        "layout_pupil_sample_count": 9,
        "propagation": "带限角谱",
        "padding": 2.0,
        "extent_mm": 0.032,
        "sampling_convergence": True,
    }
    monkeypatch.setattr(SimulationNumericsProfileStore, "load", lambda self: dict(stale))
    monkeypatch.setattr(SimulationNumericsProfileStore, "save", lambda self, profile: dict(profile))
    _app()
    tabs = SimpleParameterTabs(QWidget())
    try:
        assert tabs.calc_auto_numerics.isChecked()
        # Automatic sampling must be a complete numerical strategy, not only grid/padding.
        assert tabs.calc_propagation.currentText() == "缩放 Fresnel"
        assert tabs.calc_extent.value() == 0.024
        state = tabs.collect_state()
        assert state.calculation.propagation_model == "scaled_fresnel"
        assert state.calculation.output_extent_mm == 0.024
        assert "缩放 Fresnel" in tabs.calc_sampling_summary.text()
    finally:
        tabs.close()


def test_research_tasks_inherit_automatic_scaled_fresnel_numerics():
    from frontend_pyside.features.optimization.numerics import research_simulation_numerics

    precision, options = research_simulation_numerics({
        "automatic": True,
        "precision": "257×257",
        # Stale values must not override the automatic recommendation.
        "grid_size": 65,
        "pupil_sample_count": 17,
        "propagation": "带限角谱",
        "padding": 1.0,
        "extent_mm": 1.0,
        "sampling_convergence": True,
    })
    hybrid = options["hybrid"]
    assert precision == "standard"
    assert hybrid["grid_size"] == 257
    assert hybrid["pupil_sample_count"] == 49
    assert hybrid["propagation_model"] == "scaled_fresnel"
    assert hybrid["output_extent_x_mm"] == 0.024
    assert hybrid["output_extent_y_mm"] == 0.024
    assert hybrid["zero_padding_factor"] == 2.0


def test_research_tasks_preserve_explicit_manual_numerics():
    from frontend_pyside.features.optimization.numerics import research_simulation_numerics

    precision, options = research_simulation_numerics({
        "automatic": False,
        "precision": "513×513",
        "grid_size": 513,
        "pupil_sample_count": 65,
        "propagation": "带限角谱",
        "padding": 3.0,
        "extent_mm": 0.032,
        "sampling_convergence": False,
    })
    hybrid = options["hybrid"]
    assert precision == "high"
    assert hybrid["grid_size"] == 513
    assert hybrid["propagation_model"] == "band_limited_angular_spectrum"
    assert hybrid["output_extent_x_mm"] == 0.032
    assert hybrid["zero_padding_factor"] == 3.0
    assert hybrid["sampling_convergence_enabled"] is False
