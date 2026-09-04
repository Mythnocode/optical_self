from __future__ import annotations

from PySide6.QtWidgets import QApplication

from frontend_pyside.app.bootstrap import create_app_context
from frontend_pyside.features.simulation.instant_metrics import estimate_efficiency
from frontend_pyside.features.teaching.preview_metrics import (
    PREVIEW_EFFICIENCY_LABEL,
    estimate_teaching_preview_efficiency,
    receiver_beam_radius_um,
    teaching_to_preview_form_state,
)
from frontend_pyside.features.teaching.spatial_routing_upgrade import FlexibleSpatialExperimentModel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _model() -> tuple[FlexibleSpatialExperimentModel, object]:
    context = create_app_context()
    model = FlexibleSpatialExperimentModel()
    model.set_project_context(context.project)
    model.wavelength_nm = float(context.project.project.wavelength_nm)
    return model, context.project


def test_teaching_preview_matches_simulation_instant_metrics():
    model, project_context = _model()
    from frontend_pyside.features.simulation.page import SimulationPage

    app = _app()
    page = SimulationPage(create_app_context())
    page.show()
    app.processEvents()
    project_context = page.context.project
    model.set_project_context(project_context)
    project_context.set_simulation_project_payload(page.context.project.simulation_project_payload)

    preview = estimate_teaching_preview_efficiency(model, project_context)
    assert preview is not None
    form_state = teaching_to_preview_form_state(model, project_context)
    beam_radius = receiver_beam_radius_um(model, project_context)
    expected = estimate_efficiency(
        project_context.project,
        form_state,
        beam_radius_at_receiver_um=beam_radius,
    )
    assert abs(preview.total - expected.total) < 1.0e-12
    assert abs(preview.system - expected.system) < 1.0e-12
    assert abs(preview.receiver - expected.receiver) < 1.0e-12
    page.close()


def test_teaching_scene_snapshot_uses_preview_efficiency_label():
    _app()
    from frontend_pyside.features.simulation.page import SimulationPage

    page = SimulationPage(create_app_context())
    project_context = page.context.project
    model = FlexibleSpatialExperimentModel()
    model.set_project_context(project_context)
    project_context.set_simulation_project_payload(page.context.project.simulation_project_payload)
    snapshot = model.scene_snapshot()
    assert PREVIEW_EFFICIENCY_LABEL in snapshot.efficiency_source
    assert snapshot.efficiency_status == "preview"
    assert snapshot.metrics.total_efficiency >= 0.0
    page.close()


def test_teaching_preview_updates_when_fiber_offset_changes():
    model, project_context = _model()
    from frontend_pyside.features.simulation.page import SimulationPage

    app = _app()
    page = SimulationPage(create_app_context())
    project_context = page.context.project
    model.set_project_context(project_context)
    project_context.set_simulation_project_payload(page.context.project.simulation_project_payload)
    before = estimate_teaching_preview_efficiency(model, project_context)
    assert before is not None
    fiber = next(node for node in model.nodes.values() if node.kind == "fiber")
    fiber.params["offset_x_um"] = 8.0
    model.mark_changed()
    after = estimate_teaching_preview_efficiency(model, project_context)
    assert after is not None
    assert after.total < before.total
    page.close()


def test_payload_mfd_overrides_teaching_default_radius():
    from frontend_pyside.features.simulation.page import SimulationPage

    app = _app()
    page = SimulationPage(create_app_context())
    page.show()
    app.processEvents()
    page._publish_active_simulation_project()
    project_context = page.context.project
    model = FlexibleSpatialExperimentModel()
    model.set_project_context(project_context)
    model.receiver_mode_radius_um = 2.8  # teaching default would imply MFD 5.6
    form = teaching_to_preview_form_state(model, project_context)
    assert abs(form.receiver.mode_field_diameter_x_um - 5.0) < 1.0e-9
    page.close()
