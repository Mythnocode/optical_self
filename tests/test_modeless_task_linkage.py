from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.main_window import MainWindow
from frontend_pyside.shared.components.foundation import PrimaryButton


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _window() -> MainWindow:
    app = _app()
    window = MainWindow(create_app_context())
    window.resize(1366, 768)
    window.show()
    for _ in range(8):
        app.processEvents()
    return window


def test_optimization_opens_modeless_beside_simulation():
    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.variables", {})
        for _ in range(8):
            app.processEvents()
        task = window._optimization_task_window
        assert task is not None and task.isVisible()
        assert task.isModal() is False
        assert window._current_key == "simulation"
        assert task.page.page_header.isVisible() is False
        assert task.page.workspace_mode_bar.isVisible() is False
    finally:
        window.close()
        app.processEvents()


def test_candidate_preview_is_temporary_and_clearable():
    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.variables", {})
        for _ in range(8):
            app.processEvents()
        task = window._optimization_task_window
        assert task is not None
        task.previewRequested.emit({"receiver.lateral_offset_x_um": 2.5}, "候选 #1")
        for _ in range(20):
            app.processEvents()
        simulation = window._pages["simulation"].loaded_page
        assert simulation is not None
        assert simulation.preview_banner.isVisible()
        assert simulation._candidate_preview_changes == {"receiver.lateral_offset_x_um": 2.5}
        # Temporary preview must not become an implicit multi-scheme/project write.
        window._clear_task_candidate_preview()
        app.processEvents()
        assert simulation._candidate_preview_changes == {}
        assert not simulation.preview_banner.isVisible()
    finally:
        window.close()
        app.processEvents()


def test_forward_prediction_is_modeless_and_direct():
    app = _app()
    window = _window()
    try:
        window._open_ml_prediction_task()
        for _ in range(8):
            app.processEvents()
        task = window._ml_prediction_task_window
        assert task is not None and task.isVisible()
        assert task.isModal() is False
        assert window._current_key == "simulation"
        assert task.page.workflow_stack.currentIndex() == 4
        assert not task.page.page_header.isVisible()
        assert not task.page.workflow_bar.isVisible()
        assert task.page.prediction_button.text() == "开始预测"
    finally:
        window.close()
        app.processEvents()


def test_primary_button_task_state_is_visible():
    app = _app()
    button = PrimaryButton("开始优化")
    button.show()
    try:
        button.set_task_state("running", "优化中")
        app.processEvents()
        assert button.property("taskState") == "running"
        assert "优化中" in button.text()
        assert button.isEnabled() is False
        button.set_task_state("success", "优化完成")
        app.processEvents()
        assert button.property("taskState") == "success"
        assert "✓" in button.text()
        assert button.isEnabled() is True
    finally:
        button.close()


def _global_rect(widget):
    from PySide6.QtCore import QPoint, QRect
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def _assert_visible_buttons_not_clipped_or_overlapping(window):
    from PySide6.QtWidgets import QAbstractButton

    buttons = [
        button
        for button in window.findChildren(QAbstractButton)
        if button.isVisible() and button.width() > 0 and button.height() > 0
    ]
    for button in buttons:
        rect = _global_rect(button)
        ancestor = button.parentWidget()
        while ancestor is not None and ancestor is not window:
            if ancestor.isVisible():
                visible_rect = _global_rect(ancestor)
                intersection = rect.intersected(visible_rect)
                assert intersection.width() >= rect.width() - 1
                assert intersection.height() >= rect.height() - 1
            ancestor = ancestor.parentWidget()

    for index, first in enumerate(buttons):
        first_rect = _global_rect(first)
        for second in buttons[index + 1 :]:
            if first.isAncestorOf(second) or second.isAncestorOf(first):
                continue
            intersection = first_rect.intersected(_global_rect(second))
            assert intersection.width() <= 2 or intersection.height() <= 2




def _visible_interactive_widgets(root):
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QDoubleSpinBox,
        QLineEdit,
        QSpinBox,
        QWidget,
    )

    types = (QAbstractButton, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit)
    widgets = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, types) or not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
            continue
        # Combo/spin-box line edits are implementation children of the parent
        # interactive control, not separate user controls.
        if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), (QComboBox, QSpinBox, QDoubleSpinBox)):
            continue
        widgets.append(widget)
    return widgets


def _assert_interactive_controls_do_not_overlap(root):
    widgets = _visible_interactive_widgets(root)
    for index, first in enumerate(widgets):
        first_rect = _global_rect(first)
        for second in widgets[index + 1 :]:
            if first.isAncestorOf(second) or second.isAncestorOf(first):
                continue
            intersection = first_rect.intersected(_global_rect(second))
            assert intersection.width() <= 2 or intersection.height() <= 2, (
                first.objectName(),
                getattr(first, "text", lambda: "")(),
                second.objectName(),
                getattr(second, "text", lambda: "")(),
                intersection.getRect(),
            )

def test_optimization_task_buttons_do_not_overlap_at_compact_desktop_width():
    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.variables", {})
        for _ in range(10):
            app.processEvents()
        task = window._optimization_task_window
        task.resize(1020, 700)
        for _ in range(10):
            app.processEvents()
        _assert_visible_buttons_not_clipped_or_overlapping(task)

        task.set_target("optimization.ml_inverse_prediction", {})
        for _ in range(10):
            app.processEvents()
        _assert_visible_buttons_not_clipped_or_overlapping(task)
    finally:
        window.close()
        app.processEvents()


def test_direct_tolerance_task_owns_surface_without_stale_optimization_panels():
    app = _app()
    window = _window()
    try:
        # Reuse the same window after another task to reproduce the historical
        # stale-result overlap seen in screenshot acceptance.
        window._open_optimization_task("optimization.ml_inverse_prediction", {})
        for _ in range(8):
            app.processEvents()
        task = window._optimization_task_window
        task.set_target("optimization.tolerance", {})
        task.resize(1020, 700)
        for _ in range(10):
            app.processEvents()

        page = task.page
        assert page.inline_tolerance_panel.isVisible()
        assert not page.main_result_panel.isVisible()
        assert not page.main_splitter.widget(0).isVisible()
        assert not page.tolerance_back_button.isVisible()
        _assert_visible_buttons_not_clipped_or_overlapping(task)

        # Switching back to a research task must restore the normal two-column
        # surface; the focus fix must not permanently hide capabilities.
        task.set_target("optimization.scan", {})
        for _ in range(10):
            app.processEvents()
        assert page.main_result_panel.isVisible()
        assert page.main_splitter.widget(0).isVisible()
        assert not page.inline_tolerance_panel.isVisible()
        _assert_visible_buttons_not_clipped_or_overlapping(task)
    finally:
        window.close()
        app.processEvents()


def test_all_research_task_modes_have_no_button_overlap_at_1020_width():
    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.scan", {})
        task = window._optimization_task_window
        task.resize(1020, 700)
        for target in (
            "optimization.scan",
            "optimization.variables",
            "optimization.inverse_design",
            "optimization.ml_inverse_prediction",
            "optimization.tolerance",
            "optimization.validation",
        ):
            task.set_target(target, {})
            for _ in range(8):
                app.processEvents()
            _assert_visible_buttons_not_clipped_or_overlapping(task)
    finally:
        window.close()
        app.processEvents()


def test_ml_training_form_uses_page_scroll_instead_of_overlapping_fields():
    app = _app()
    window = _window()
    try:
        window.navigate("machine_learning", update_document=False)
        for _ in range(12):
            app.processEvents()
        page = window._pages["machine_learning"].loaded_page
        page.workflow_stack.setCurrentIndex(2)
        window.resize(900, 650)
        for _ in range(12):
            app.processEvents()

        fields = [
            page.training_dataset,
            page.model_type,
            page.training_epochs,
            page.training_seed,
        ]
        rects = [_global_rect(field) for field in fields]
        for index, first in enumerate(rects):
            for second in rects[index + 1 :]:
                intersection = first.intersected(second)
                assert intersection.width() <= 1 or intersection.height() <= 1

        # The training workflow has one outer vertical scroll owner; controls
        # retain their normal height instead of being compressed into overlap.
        scroll = page.workflow_stack.currentWidget()
        assert scroll.objectName() == "mlTrainingScroll"
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() > 0
        assert all(field.height() >= 30 for field in fields)
    finally:
        window.close()
        app.processEvents()


def test_tolerance_progress_is_rendered_in_tolerance_result_region():
    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.tolerance", {})
        for _ in range(8):
            app.processEvents()
        task = window._optimization_task_window
        task.resize(1020, 700)
        page = task.page
        page.tolerance_result_panel.setVisible(True)
        page._jobs["tol-ui"] = {"kind": "tolerance", "task_id": "tol-ui", "result_requested": False}
        page._active_research_job_id = "tol-ui"
        page._progress_tracker.reset("tol-ui")
        page._update_research_progress("tol-ui", "running", 0.63)
        for _ in range(4):
            app.processEvents()

        assert page.tolerance_progress_panel.isVisible()
        assert page.tolerance_progress.value() == 63
        assert page.tolerance_progress.isTextVisible()
        assert "容差" in page.tolerance_progress_label.text()
        assert page.tolerance_run_button.property("taskState") == "running"
        assert "分析中" in page.tolerance_run_button.text()
    finally:
        window.close()
        app.processEvents()

def test_all_research_task_modes_have_no_interactive_overlap_at_900_width():
    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.scan", {})
        task = window._optimization_task_window
        task.resize(900, 620)
        for target in (
            "optimization.scan",
            "optimization.variables",
            "optimization.inverse_design",
            "optimization.ml_inverse_prediction",
            "optimization.tolerance",
            "optimization.validation",
        ):
            task.set_target(target, {})
            for _ in range(10):
                app.processEvents()
            _assert_interactive_controls_do_not_overlap(task)
    finally:
        window.close()
        app.processEvents()


def test_teaching_short_window_scrolls_whole_page_instead_of_overlapping_canvas():
    app = _app()
    window = _window()
    try:
        window.resize(900, 650)
        window.navigate("teaching", update_document=False)
        for _ in range(40):
            app.processEvents()

        page = window._pages["teaching"].loaded_page
        workbench = page.workbench
        host_rect = _global_rect(workbench.overlay_host)
        metric_rect = _global_rect(workbench.total_metric)
        undo_rect = _global_rect(workbench.undo_button)

        # The status strip is a separate semantic row.  At short desktop height
        # it must remain below the optical bench and the page must become the
        # single vertical scroll owner rather than letting Qt squeeze the two
        # regions into the same pixels.
        assert host_rect.intersected(metric_rect).isEmpty()
        assert host_rect.intersected(undo_rect).isEmpty()
        assert page.page_scroll.horizontalScrollBar().maximum() == 0
        assert page.page_scroll.verticalScrollBar().maximum() > 0
        assert workbench.height() >= 650

        # Floating canvas tools must remain fully inside the canvas even at the
        # compact width; this guards the clipped right-edge controls seen in the
        # screenshot review.
        for button in workbench.view_control_buttons:
            rect = _global_rect(button)
            assert host_rect.contains(rect.topLeft())
            assert host_rect.contains(rect.bottomRight())
    finally:
        window.close()
        app.processEvents()

def test_experiment_validation_shows_result_region_progress_on_submit():
    from types import SimpleNamespace

    app = _app()
    window = _window()
    try:
        window._open_optimization_task("optimization.validation", {})
        task = window._optimization_task_window
        task.resize(900, 620)
        for _ in range(10):
            app.processEvents()
        page = task.page
        page._validation_rows = lambda: [SimpleNamespace(case="工况1", parameter_changes={})]
        page._current_research_project_payload = lambda: {"surfaces": [{"type": "plane"}]}
        calls = []
        page.api_client.post = lambda key, path, payload: calls.append((key, path, payload))

        page._validation_run_platform()
        for _ in range(4):
            app.processEvents()

        assert calls and calls[-1][0] == "validation.run"
        assert page.validation_result_panel.isVisible()
        assert page.validation_progress_panel.isVisible()
        assert page.validation_progress.minimum() == 0
        assert page.validation_progress.maximum() == 0
        assert "正在计算" in page.validation_progress_label.text()
        assert page.validation_run_platform_button.property("taskState") == "running"
        assert "比较中" in page.validation_run_platform_button.text()
        _assert_interactive_controls_do_not_overlap(task)
    finally:
        window.close()
        app.processEvents()

