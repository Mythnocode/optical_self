from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from frontend_pyside.features.assistant.guidance_session import GuidanceSession
from frontend_pyside.features.simulation.live_preview import LivePreviewWorkspace


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _combo_keys(widget: LivePreviewWorkspace) -> list[str]:
    return [
        str(widget.result_selector.itemData(index) or "")
        for index in range(widget.result_selector.count())
        if str(widget.result_selector.itemData(index) or "")
    ]


def test_result_catalogue_keeps_uncomputed_views_visible():
    app = _app()
    widget = LivePreviewWorkspace()
    try:
        # The refactored UI exposes capabilities through analysis -> view instead of
        # flattening every result into one long selector.  Every legacy result must
        # still be discoverable, including results that have not been computed yet.
        discovered: list[str] = []
        for analysis_index in range(widget.analysis_selector.count()):
            widget.analysis_selector.setCurrentIndex(analysis_index)
            app.processEvents()
            for key in _combo_keys(widget):
                if key not in discovered:
                    discovered.append(key)
                combo_index = next(
                    i for i in range(widget.result_selector.count())
                    if widget.result_selector.itemData(i) == key
                )
                assert "点此计算" in widget.result_selector.itemText(combo_index)
        assert set(discovered) == set(widget.RESULT_ORDER)
        assert len(discovered) == len(widget.RESULT_ORDER)
    finally:
        widget.dispose()


def test_selecting_missing_view_emits_lazy_compute_request_without_loading_plot_engine():
    app = _app()
    widget = LivePreviewWorkspace()
    events: list[tuple[str, ...]] = []
    widget.visibleResultsChanged.connect(lambda value: events.append(tuple(value or ())))
    try:
        assert widget.workspace._real is None
        widget.set_current_result("PSF")
        app.processEvents()
        assert events and events[-1] == ("PSF",)
        # Empty placeholder remains cheap until a real plot is available.
        assert widget.workspace._real is None
        assert "尚未计算" in widget.workspace.current_data().get("message", "")
    finally:
        widget.dispose()


def test_one_analysis_marks_all_derived_views_as_available_without_rendering_them():
    app = _app()
    widget = LivePreviewWorkspace()
    try:
        widget.set_available_analyses({"psf"})
        analysis_index = widget.analysis_selector.findData("焦面分析")
        assert analysis_index >= 0
        widget.analysis_selector.setCurrentIndex(analysis_index)
        app.processEvents()
        for key in ("PSF", "焦面截面", "光斑尺寸"):
            combo_index = next(i for i in range(widget.result_selector.count()) if widget.result_selector.itemData(i) == key)
            assert "已有" not in widget.result_selector.itemText(combo_index)
            assert widget.result_selector.itemText(combo_index).strip() == widget.DISPLAY_LABELS.get(key, key)
        assert widget.workspace._real is None
    finally:
        widget.dispose()


def test_guidance_session_tracks_real_scan_job_and_continues_after_completion():
    session = GuidanceSession()
    session.begin(
        {"target": "optimization.scan", "label": "查看研究设置", "why": "先扫描再判断"},
        [{"job_id": "old", "page": "optimization", "name": "后端参数扫描", "status": "已完成"}],
    )
    view, transition = session.observe([])
    assert view is not None and view.phase == "await_user"
    assert transition is None

    tasks = [{
        "job_id": "new-scan",
        "page": "optimization",
        "kind": "参数研究",
        "name": "后端参数扫描",
        "status": "运行中",
        "progress": 37,
        "result_available": False,
    }]
    view, transition = session.observe(tasks)
    assert view is not None and view.phase == "running"
    assert view.job_id == "new-scan"
    assert "37%" in view.state
    assert transition is None

    tasks[0].update(status="已完成", progress=100, result_available=True)
    view, transition = session.observe(tasks)
    assert view is not None and view.phase == "completed"
    assert "参数扫描已经完成" in view.title
    assert transition is not None and transition["phase"] == "completed"

    # User starts local refinement from the scan page without asking AI again.
    tasks.insert(0, {
        "job_id": "refined-scan",
        "page": "optimization",
        "kind": "参数研究",
        "name": "后端参数扫描",
        "status": "等待后端",
        "progress": 0,
    })
    view, transition = session.observe(tasks)
    assert view is not None and view.phase == "running"
    assert view.job_id == "refined-scan"
    assert transition is None


def test_guidance_failure_routes_to_real_task_recovery():
    session = GuidanceSession()
    session.begin({"target": "simulation.formal", "label": "准备正式仿真"}, [])
    tasks = [{
        "job_id": "sim-fail",
        "page": "simulation",
        "kind": "仿真",
        "name": "正式光学仿真",
        "status": "失败",
        "progress": 28,
        "error_code": "BACKEND_RESTARTED",
    }]
    view, transition = session.observe(tasks)
    assert view is not None and view.phase == "failed"
    assert view.action.get("target") == "tasks.current"
    assert transition is not None and transition["phase"] == "failed"


def test_mtf_shares_psf_analysis_and_can_be_derived_from_formal_psf():
    import numpy as np
    from frontend_pyside.features.simulation.analysis_planner import VIEW_ANALYSES
    from frontend_pyside.features.simulation.adapters.wave_results import _mtf_plot

    assert VIEW_ANALYSES["MTF"] == frozenset({"psf"})
    axis = np.linspace(-0.024, 0.024, 65)
    xx, yy = np.meshgrid(axis, axis)
    psf = np.exp(-2.0 * (xx * xx + yy * yy) / (0.004 ** 2))
    plot = _mtf_plot({
        "psf_intensity": psf,
        "coupling_grid_x_mm": axis,
        "coupling_grid_y_mm": axis,
    })
    assert plot is not None
    assert plot["kind"] == "line"
    assert plot["x_label"] == "空间频率 / cycles·mm⁻¹"
    assert len(plot["x"]) == len(plot["y"]) > 10
    assert max(plot["y"]) <= 1.0 + 1e-12
    assert "无需重复物理计算" in plot["description"]


def test_default_formal_calculation_is_lazy_for_current_result_only():
    from frontend_pyside.features.simulation.form_state import SimulationFormState
    from frontend_pyside.features.simulation.analysis_planner import plan_analyses

    state = SimulationFormState()
    assert state.calculation.only_visible_results is True
    assert plan_analyses(
        state.calculation.analyses,
        ("光路",),
        visible_only=state.calculation.only_visible_results,
    ) == ("raytrace",)
    assert plan_analyses(
        state.calculation.analyses,
        ("PSF",),
        visible_only=state.calculation.only_visible_results,
    ) == ("psf",)
    assert plan_analyses(
        state.calculation.analyses,
        ("相位",),
        visible_only=state.calculation.only_visible_results,
    ) == ("coupling",)


def test_detailed_view_has_one_analysis_specific_title_after_refresh():
    app = _app()
    widget = LivePreviewWorkspace()
    widget.resize(1000, 700)
    widget.show()
    try:
        widget.set_current_result("光路")
        app.processEvents()
        widget.detail_mode_button.click()
        for _ in range(4):
            app.processEvents()

        titles = [
            label
            for label in widget.detail_report.findChildren(QLabel)
            if label.objectName() == "analysisDetailTitle" and label.isVisible()
        ]
        assert len(titles) == 1
        assert titles[0].text() == "光路 · 详细数据"
        assert widget.workspace.isVisible() is False

        # A rerender used to leave the old deferred-delete title on top of the
        # new one for one event turn. Refreshing must still leave exactly one.
        widget._render()
        for _ in range(4):
            app.processEvents()
        titles = [
            label
            for label in widget.detail_report.findChildren(QLabel)
            if label.objectName() == "analysisDetailTitle" and label.isVisible()
        ]
        assert len(titles) == 1
        assert titles[0].text() == "光路 · 详细数据"
    finally:
        widget.dispose()
