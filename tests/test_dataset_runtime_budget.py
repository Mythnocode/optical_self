from __future__ import annotations

from backend.optical_ml_app.application.dataset_service import dataset_timeout_seconds
from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from machine_learning.datasets.generator import dataset_simulation_options
from shared_contracts.project import ProjectSnapshot


def test_formal_dataset_timeout_matches_observed_wave_optics_cost() -> None:
    assert dataset_timeout_seconds(1) == 300.0
    assert dataset_timeout_seconds(50) == 780.0
    assert dataset_timeout_seconds(100) == 1530.0


def test_dataset_keeps_formal_coupling_but_omits_result_viewer_arrays() -> None:
    project = ProjectSnapshot.model_validate(
        serialize_project(default_project(), SimulationFormState())
    )
    options = dataset_simulation_options(project)["hybrid"]

    assert options["high_precision_coupling_enabled"] is True
    assert options["sampling_convergence_enabled"] is True
    assert options["include_diagnostic_arrays"] is False
    assert options["result_array_policy"] == "none"
