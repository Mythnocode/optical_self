from __future__ import annotations

from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.optimization.page import OptimizationPage
from frontend_pyside.infrastructure.api.errors import ApiError


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page() -> OptimizationPage:
    app = _app()
    page = OptimizationPage(create_app_context())
    page.resize(1366, 768)
    page.show()
    app.processEvents()
    return page


def _scan_result() -> dict:
    return {
        "status": "completed",
        "parameter_grid": [[14.0], [14.5], [15.0], [15.5], [16.0]],
        "parameter_names": ["receiver.axial_offset_z_mm"],
        "response_values": {
            "coupling_efficiency": [0.05, 0.40, 0.75, 0.40, 0.05]
        },
        "warnings": [],
        "errors": [],
        "metadata": {},
    }


def test_scan_summary_remains_owned_by_scan_result_after_shared_refresh():
    page = _page()
    try:
        page.scan_param.setCurrentText("接收面位置")
        page.scan_metric.setCurrentText("耦合效率")
        page._render_scan_result(_scan_result())
        before = (
            page.compact_efficiency.text(),
            page.compact_gain.text(),
            page.compact_range.text(),
        )
        assert before[0].startswith("最佳参数 ")
        assert before[1].startswith("峰值 ")
        page._refresh_user_summary()
        after = (
            page.compact_efficiency.text(),
            page.compact_gain.text(),
            page.compact_range.text(),
        )
        assert after == before

        page._scan_point_selected(14.5, 40.0)
        assert page.scan_point_label.text().endswith("40%")
    finally:
        page.close()


def test_refine_scan_range_survives_next_guided_submission(monkeypatch):
    page = _page()
    try:
        for key, box in page.fixed_content_boxes.items():
            box.setChecked(key == "fiber_axial")
        page.parameter_research_button.setChecked(True)
        page.depth_buttons[0].setChecked(True)
        page._research_options_changed()
        # Mimic the first guided run, which configures the legacy scan widgets
        # for the selected research parameter before a result can be refined.
        page._configure_scan_from_profile("fiber_axial")
        page._render_scan_result(_scan_result())
        page._scan_point_selected(15.0, 75.0)
        page._refine_selected_scan_point()
        expected = (page.scan_start.value(), page.scan_stop.value())
        assert expected != (-0.5, 0.5)

        captured: dict[str, float] = {}

        def fake_run_scan() -> bool:
            captured["start"] = page.scan_start.value()
            captured["stop"] = page.scan_stop.value()
            captured["points"] = page.scan_points.value()
            return True

        monkeypatch.setattr(page, "_run_scan", fake_run_scan)
        page._start_guided_research()
        assert captured["start"] == expected[0]
        assert captured["stop"] == expected[1]
        assert captured["points"] >= 81
    finally:
        page.close()


def test_scan_tolerance_uses_current_plan_instead_of_stale_optimisation():
    page = _page()
    try:
        page.scan_param.setCurrentText("接收面位置")
        page._render_scan_result(_scan_result())
        page._open_tolerance_from_optimization()
        assert page.tolerance_candidate.currentText() == "当前系统"
        assert page.tolerance_template.currentText() == "常用装调"
        assert "参数扫描本身不会自动改写当前系统" in page.tolerance_source_info.text()
    finally:
        page.close()


def test_invalid_submit_recovers_ui_and_surfaces_field_level_reason():
    page = _page()
    try:
        page.start_research_button.setEnabled(False)
        page.research_progress.setRange(0, 0)
        page.research_progress.setVisible(True)
        error = ApiError(
            code="INVALID_REQUEST",
            message="request parameters are invalid",
            context={
                "errors": [
                    {
                        "loc": ["body", "scan_parameters", 0, "points"],
                        "msg": "Input should be greater than or equal to 2",
                    }
                ]
            },
        )
        page._api_failed_detail("optimization.scan.submit", error)
        assert page.start_research_button.isEnabled()
        assert not page.research_progress.isVisible()
        assert "scan_parameters.0.points" in page.activity_label.text()
        assert "上方已完成结果仍然有效" in page.activity_label.text()
    finally:
        page.close()


def test_same_backend_job_id_does_not_create_duplicate_local_task_rows():
    page = _page()
    try:
        response = {"job_id": "job-idempotent-scan"}
        page._api_completed("optimization.scan.submit", response)
        page._api_completed("optimization.scan.submit", response)
        matching = [
            task
            for task in page.context.tasks.tasks
            if str(task.get("job_id", "")) == "job-idempotent-scan"
        ]
        assert len(matching) == 1
    finally:
        page.close()
