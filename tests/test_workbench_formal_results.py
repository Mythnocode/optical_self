from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.app.workbench_shell import (
    FORMAL_RESULT_VIEWS,
    RESULT_PLOT_KEYS,
    WorkbenchShell,
)
from frontend_pyside.features.simulation.analysis_planner import plan_analyses
from frontend_pyside.features.simulation.payloads import build_simulation_payload
from optical_runtime import create_optical_simulation_engine
from shared_contracts.simulation import SimulationRequest


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_formal_submit_requests_result_document_views():
    planned = plan_analyses(
        ("raytrace", "spot", "coupling", "psf"),
        FORMAL_RESULT_VIEWS,
        visible_only=True,
    )
    assert "coupling" in planned
    assert "raytrace" in planned
    assert "spot" in planned
    assert "psf" in planned
    assert "wavefront_quality" in planned


def test_workbench_payload_keeps_scaled_fresnel_for_psf():
    app = _app()
    shell = WorkbenchShell(create_app_context())
    try:
        state = shell.collect_simulation_state()
        payload = build_simulation_payload(shell.context.project.project, state)
        assert "psf" in payload["analyses"]
        assert payload["options"]["hybrid"]["propagation_model"] == "scaled_fresnel"
        assert payload["options"]["wave"]["method"] == "fresnel"
    finally:
        shell.close()
        app.processEvents()


def test_result_documents_plot_live_preview_engine_output():
    app = _app()
    shell = WorkbenchShell(create_app_context())
    shell.resize(1200, 800)
    try:
        shell._calculation_state = replace(
            shell._calculation_state,
            precision="preview",
            output_grid_size=65,
            pupil_sample_count=17,
            layout_pupil_sample_count=17,
            high_precision_coupling_enabled=False,
        )
        state = shell.collect_simulation_state()
        planned = plan_analyses(
            state.calculation.analyses,
            FORMAL_RESULT_VIEWS,
            visible_only=state.calculation.only_visible_results,
        )
        state = replace(state, calculation=replace(state.calculation, analyses=tuple(planned)))
        payload = build_simulation_payload(
            shell.context.project.project, state, request_id="workbench-ui-smoke"
        )
        assert payload["options"]["wave"]["method"] == "fresnel"
        result = create_optical_simulation_engine().evaluate(
            SimulationRequest.model_validate(payload), None, None
        )
        assert result.status == "completed", result.errors
        body = result.model_dump()
        arrays = dict(body.get("arrays") or {})
        assert arrays, f"engine returned no arrays; warnings={body.get('warnings')}"

        for kind in ("coupling", "spot", "ray_layout", "wavefront", "layout_3d"):
            shell.open_document("simulation", kind)
        shell._formal_result_ready(body, payload.get("project"))
        for kind in ("coupling", "spot", "ray_layout", "wavefront", "layout_3d"):
            widget = shell._widgets[f"simulation:{kind}"]
            plot = dict(getattr(widget, "_last_plot") or {})
            source = widget.findChild(QLabel, "ResultSource")
            assert plot.get("kind") not in {None, "", "empty"}, (
                f"{kind} stayed empty for keys {RESULT_PLOT_KEYS.get(kind)}; "
                f"message={plot.get('message')!r}; "
                f"array_keys={sorted(arrays)[:40]}; "
                f"source={None if source is None else source.text()}"
            )
            assert source is not None
            assert source.text() == "正式计算"
    finally:
        shell.close()
        app.processEvents()
