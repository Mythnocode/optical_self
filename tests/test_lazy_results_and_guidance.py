from __future__ import annotations

from frontend_pyside.features.assistant.guidance_session import GuidanceSession


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
        "status": "失败",
        "progress": 28,
        "error_code": "BACKEND_RESTARTED",
        "name": "正式光学仿真",
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
