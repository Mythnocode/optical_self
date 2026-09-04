from __future__ import annotations

import runpy
import sys


def test_run_backend_does_not_import_backend_app_when_reimported_as_spawn_child(monkeypatch):
    # multiprocessing(spawn) re-executes the parent's entry module under a
    # non-__main__ name. A worker must not construct FastAPI services or run job
    # recovery merely by importing run_backend.py.
    sys.modules.pop("backend.optical_ml_app.main", None)
    runpy.run_path("run_backend.py", run_name="__mp_main__")
    assert "backend.optical_ml_app.main" not in sys.modules


def test_optimization_submission_does_not_send_registry_lock_to_worker(tmp_path):
    import cloudpickle
    from machine_learning.registry.model_registry import FileModelRegistry
    from backend.optical_ml_app.application.optimization_service import OptimizationApplicationService
    from shared_contracts.optimization import OptimizationObjective, OptimizationRequest, OptimizationVariable
    from shared_contracts.project import ProjectSnapshot
    from shared_contracts.simulation import SimulationRequest

    class PickleCheckingTaskManager:
        def submit(self, job_type, function, *args, **kwargs):
            assert job_type == "optimization"
            # Mirror the persistent-worker queue boundary. This used to fail on
            # FileModelRegistry._cache_lock with TypeError: cannot pickle RLock.
            cloudpickle.dumps({"function": function, "args": args, "kwargs": kwargs})
            assert isinstance(args[-1], (str, type(None)))
            return "job-spawn-safe"

    project = ProjectSnapshot(
        project_id="spawn-safe", surfaces=[], object_distance_mm=0.0,
        image_distance_mm=0.0, pupil_radius_mm=1.0, source={}, receiver={},
        fingerprint="spawn-safe",
    )
    base = SimulationRequest(request_id="spawn-safe-base", project=project, analyses=["coupling"], precision="preview")
    opt = OptimizationRequest(
        request_id="spawn-safe-opt",
        variables=[OptimizationVariable(path="receiver.offset_x_mm", lower_bound=-0.01, upper_bound=0.01, initial_value=0.0)],
        objectives=[OptimizationObjective(metric="coupling_efficiency", goal="target", target_value=0.5)],
        max_iterations=2, max_evaluations=2, precision="preview",
    )
    service = OptimizationApplicationService(PickleCheckingTaskManager(), str(tmp_path / "datasets"), FileModelRegistry(tmp_path / "models"))
    assert service.submit(base, opt) == "job-spawn-safe"
