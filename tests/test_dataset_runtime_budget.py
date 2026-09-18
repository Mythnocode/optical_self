from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.optical_ml_app.application.dataset_service import DatasetApplicationService
from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from machine_learning.datasets.generator import dataset_simulation_options
from shared_contracts.project import ProjectSnapshot


def test_dataset_has_no_total_timeout_but_keeps_stall_guard() -> None:
    class TaskManager:
        def __init__(self) -> None:
            self.kwargs = {}

        def submit(self, *_args, **kwargs):
            self.kwargs = kwargs
            return "job-dataset"

    manager = TaskManager()
    service = DatasetApplicationService(
        manager,
        SimpleNamespace(root=Path("datasets")),
        SimpleNamespace(),
    )

    assert service.submit(SimpleNamespace(sample_count=50)) == "job-dataset"
    assert manager.kwargs["timeout_seconds"] is None
    assert manager.kwargs["stall_timeout_seconds"] == 300.0


def test_dataset_uses_bounded_standard_coupling_and_omits_result_viewer_arrays() -> None:
    project = ProjectSnapshot.model_validate(
        serialize_project(default_project(), SimulationFormState())
    )
    options = dataset_simulation_options(project)["hybrid"]

    assert options["high_precision_coupling_enabled"] is True
    assert options["precision_mode"] == "balanced"
    assert options["grid_size"] == 257
    assert options["output_grid_size"] == 513
    assert options["sampling_convergence_enabled"] is False
    assert options["include_diagnostic_arrays"] is False
    assert options["result_array_policy"] == "none"


def test_dataset_precision_changes_the_actual_hybrid_profile() -> None:
    project = ProjectSnapshot.model_validate(
        serialize_project(default_project(), SimulationFormState())
    )

    preview = dataset_simulation_options(project, "preview")["hybrid"]
    high = dataset_simulation_options(project, "high")["hybrid"]

    assert (preview["grid_size"], preview["output_grid_size"]) == (65, 129)
    assert preview["sampling_convergence_enabled"] is False
    assert (high["grid_size"], high["output_grid_size"]) == (257, 513)
    assert high["sampling_convergence_enabled"] is True
