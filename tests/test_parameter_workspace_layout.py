from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.compact_shell import CATEGORY_BY_KEY
from frontend_pyside.features.optimization.page import OptimizationPage
from frontend_pyside.features.optimization.presentation.result_behavior import (
    _parameter_result_rows,
)
from frontend_pyside.features.simulation.page import SimulationPage
from frontend_pyside.shared import layout_tokens as ui_layout
from frontend_pyside.shared.plotting.canvas import PlotCanvas


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settle(app: QApplication, turns: int = 12) -> None:
    for _ in range(turns):
        app.processEvents()


def test_simulation_parameter_column_keeps_inputs_inside_its_viewport() -> None:
    app = _app()
    page = SimulationPage(create_app_context())
    page.resize(1366, 768)
    page.show()
    try:
        _settle(app)
        assert page.params.width() >= ui_layout.SIM_PARAMETER_MIN_WIDTH
        assert not page.main_splitter.isCollapsible(0)

        viewport = page.params.viewport()
        for widget_type in (QComboBox, QAbstractSpinBox):
            for control in page.params.findChildren(widget_type):
                if not control.isVisible():
                    continue
                right_edge = control.mapTo(viewport, control.rect().bottomRight()).x()
                assert right_edge <= viewport.rect().right()
    finally:
        page.close()


def test_expanded_optimization_settings_scroll_without_moving_result_column() -> None:
    app = _app()
    page = OptimizationPage(create_app_context())
    page.prepare_workspace_task("optimization.variables")
    page.resize(1100, 650)
    page.show()
    try:
        _settle(app)
        result_host = page.main_splitter.widget(1)
        result_top = result_host.mapToGlobal(result_host.rect().topLeft()).y()

        page.more_settings_panel.set_expanded(True)
        page.auto_edit_panel.set_expanded(True)
        page.auto_collimation_panel.set_expanded(True)
        page.auto_algorithm_panel.set_expanded(True)
        _settle(app)

        scrollbar = page.settings_scroll.verticalScrollBar()
        assert scrollbar.maximum() > 0
        scrollbar.setValue(scrollbar.maximum())
        _settle(app, 2)
        assert scrollbar.value() == scrollbar.maximum()
        assert result_host.mapToGlobal(result_host.rect().topLeft()).y() == result_top

        viewport = page.settings_scroll.viewport()
        fields = (
            page.objective,
            page.collimation_surface,
            page.collimation_span,
            page.collimation_radius_change,
            page.collimation_curvature,
            page.collimation_centroid_drift,
            page.collimation_axis_tilt,
            page.algorithm,
            page.iterations,
            page.starts,
            page.tolerance,
        )
        for field in fields:
            right_edge = field.mapTo(viewport, field.rect().bottomRight()).x()
            assert right_edge <= viewport.rect().right()
    finally:
        page.close()


def test_five_result_tabs_belong_to_parameter_research_ui() -> None:
    app = _app()
    page = OptimizationPage(create_app_context())
    page.resize(1100, 700)
    page.show()
    try:
        page.prepare_workspace_task("optimization.scan")
        _settle(app)
        expected = ["参数响应", "优化前后", "优化收敛", "候选对比", "参数相关性"]
        assert [button.text() for button in page.result_view_buttons] == expected
        assert all(button.isVisible() for button in page.result_view_buttons)

        page.prepare_workspace_task("optimization.variables")
        _settle(app)
        assert page.result_view_buttons[0].text() == "优化结果"
        assert page.result_view_buttons[0].isVisible()
        assert not any(button.isVisible() for button in page.result_view_buttons[1:])
    finally:
        page.close()


def test_optimization_page_exposes_parameter_research_entry() -> None:
    app = _app()
    page = OptimizationPage(create_app_context())
    page.resize(1100, 700)
    page.show()
    try:
        _settle(app)
        assert page.parameter_workspace_button.isVisible()
        page.parameter_workspace_button.click()
        _settle(app)
        assert page._task_window_target == "optimization.scan"
        assert page.workspace_mode_bar.isVisible()
        assert [button.text() for button in page.result_view_buttons] == [
            "参数响应", "优化前后", "优化收敛", "候选对比", "参数相关性"
        ]
        assert all(button.isVisible() for button in page.result_view_buttons)
        page.research_workspace_button.click()
        _settle(app)
        assert page._task_window_target == "optimization.variables"
        page.validation_workspace_button.click()
        _settle(app)
        assert page._task_window_target == "optimization.inverse_design"
    finally:
        page.close()


def test_toolbox_optimization_category_contains_parameter_research() -> None:
    actions = [
        action
        for _group_title, group_actions in CATEGORY_BY_KEY["research"].groups
        for action in group_actions
    ]
    research = next(action for action in actions if action.target == "optimization.scan")
    assert research.title == "参数研究"
    assert research.page_key == "optimization"


def test_optimization_result_snapshot_includes_enabled_and_fixed_parameters() -> None:
    app = _app()
    page = OptimizationPage(create_app_context())
    try:
        page.prepare_workspace_task("optimization.variables")
        _settle(app)
        snapshot = page.variable_selector.get_parameter_snapshot()
        variables = page.variable_selector.get_variables()
        optimized_paths = {item["path"] for item in variables}

        assert snapshot
        assert optimized_paths
        assert optimized_paths <= {item["path"] for item in snapshot}
        assert any(item["optimized"] for item in snapshot)
        assert any(not item["optimized"] for item in snapshot)
        wavelength = next(item for item in snapshot if item["path"] == "source.wavelength_nm")
        assert wavelength["label"] == "波长"
        assert wavelength["unit"] == "nm"
    finally:
        page.close()
        _settle(app, 2)


def test_best_parameter_plot_groups_optimized_and_fixed_snapshot_rows() -> None:
    app = _app()
    snapshot = [
        {
            "path": "receiver.axial_offset_z_mm",
            "label": "光纤轴向位置",
            "value": 0.0,
            "unit": "mm",
            "optimized": True,
        },
        {
            "path": "source.wavelength_nm",
            "label": "波长",
            "value": 1550.0,
            "unit": "nm",
            "optimized": False,
        },
    ]
    optimized, fixed = _parameter_result_rows(
        {"receiver.axial_offset_z_mm": -0.00266524}, snapshot
    )
    assert optimized == [{
        "path": "receiver.axial_offset_z_mm",
        "label": "光纤轴向位置",
        "value": -0.00266524,
        "unit": "mm",
    }]
    assert fixed == [{
        "path": "source.wavelength_nm",
        "label": "波长",
        "value": 1550.0,
        "unit": "nm",
    }]

    canvas = PlotCanvas()
    canvas.resize(980, 560)
    canvas.set_plot({
        "kind": "parameter_summary",
        "title": "最佳参数",
        "optimized": optimized,
        "fixed": fixed,
    })
    try:
        canvas.draw()
        rendered = " ".join(text.get_text() for text in canvas.figure.axes[0].texts)
        assert "已优化变量" in rendered
        assert "固定参数（未参与本次优化）" in rendered
        assert "光纤轴向位置" in rendered
        assert "波长" in rendered
        assert "1550 nm" in rendered
    finally:
        canvas.close()
        _settle(app, 2)
