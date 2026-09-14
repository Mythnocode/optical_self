from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from backend.optical_ml_app.jobs.progress import (
    WORKER_PROGRESS_CEILING,
    ProgressReporter,
    ScaledProgressReporter,
    worker_progress_fraction,
)
from backend.optical_ml_app.jobs.task_manager import TaskManager
from backend.optical_ml_app.storage.filesystem_job_repository import FileJobRepository
from backend.optical_ml_app.storage.result_bundle import load_result_bundle, save_result_bundle
from frontend_pyside.core.types import LensSurface, ProjectSnapshot
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.features.simulation.payloads import build_simulation_payload
from frontend_pyside.shared.task_display import friendly_job_stage, terminal_progress
from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_WAVELENGTH_NM,
    FOUR_LENS_SURFACES,
    PROJECT_NAME,
)
from optical_runtime import create_optical_simulation_engine
from optical_runtime.request_compiler import compile_simulation_context
from optical_core.physics.geometric.solvers.compact_batch_raytrace import compact_trace_support
from optical_core.physics.geometric.solvers.trace_options import TraceOptions
from shared_contracts.simulation import SimulationRequest


def _project() -> ProjectSnapshot:
    # Fast-path tests exercise the uncoated geometric kernel explicitly.  The
    # shipped high-coupling demo carries a real multilayer coating and is
    # correctly routed through the full coating-aware tracer.
    surface_specs = []
    for item in FOUR_LENS_SURFACES:
        spec = dict(item)
        spec["coating"] = "无"
        spec["type_parameters"] = {}
        surface_specs.append(spec)
    return ProjectSnapshot(
        name=PROJECT_NAME,
        wavelength_nm=DEFAULT_WAVELENGTH_NM,
        receiver_mfd_um=DEFAULT_RECEIVER_MFD_UM,
        surfaces=[LensSurface(**item) for item in surface_specs],
    )


def _request(*, full_trace: bool = False, polarization: bool = False) -> SimulationRequest:
    payload = build_simulation_payload(
        _project(),
        SimulationFormState(),
        request_id=f"fastpath-test-{full_trace}-{polarization}",
        random_seed=42,
    )
    payload["precision"] = "preview"
    options = dict(payload.get("options", {}) or {})
    if full_trace:
        options["trace_output_level"] = "full"
    if polarization:
        options["polarization_sensitive"] = True
    payload["options"] = options
    return SimulationRequest.model_validate(payload)


def _wait_status(manager: TaskManager, job_id: str, wanted: set[str], timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = manager.get_status(job_id)
        if latest.status in wanted:
            return latest
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {wanted}; latest={latest}")


def _worker_claims_done_then_waits(context, seconds: float):
    context.progress.update(1.0, "test.worker_claimed_done", 1, 1)
    time.sleep(float(seconds))
    return {"status": "completed", "value": 7}


def test_worker_progress_never_owns_terminal_100_percent():
    assert worker_progress_fraction(1.0) == pytest.approx(WORKER_PROGRESS_CEILING)
    seen: list[float] = []
    ProgressReporter(lambda progress, *_: seen.append(progress)).update(1.0, "done")
    assert seen == [pytest.approx(WORKER_PROGRESS_CEILING)]


def test_scaled_progress_can_finish_child_interval_before_parent_ceiling():
    seen: list[float] = []

    class Parent:
        def update(self, progress, *_args, **_kwargs):
            seen.append(float(progress))

    ScaledProgressReporter(Parent(), 0.2, 0.8).update(1.0, "child.done")
    assert seen == [pytest.approx(0.8)]


def test_task_manager_reserves_100_percent_for_persisted_completed_state(tmp_path: Path):
    repo = FileJobRepository(tmp_path / "jobs")
    manager = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        job_id = manager.submit("test", _worker_claims_done_then_waits, 0.35)
        deadline = time.monotonic() + 5.0
        observed_worker_stage = None
        while time.monotonic() < deadline:
            status = manager.get_status(job_id)
            if status.status == "running" and status.stage == "test.worker_claimed_done":
                observed_worker_stage = status
                break
            time.sleep(0.01)
        assert observed_worker_stage is not None
        assert observed_worker_stage.progress == pytest.approx(WORKER_PROGRESS_CEILING)
        assert observed_worker_stage.result_available is False

        completed = _wait_status(manager, job_id, {"completed"})
        assert completed.progress == pytest.approx(1.0)
        assert completed.result_available is True
        assert manager.get_result(job_id)["value"] == 7
    finally:
        manager.shutdown(wait=True)


def test_default_aspheric_plane_system_is_compact_trace_eligible_but_pose_falls_back():
    request = _request()
    context = compile_simulation_context(request)
    options = context.canonical_trace_options(context.scene.options.get("hybrid", {}))
    trace_options = TraceOptions(
        wavelength_nm=float(options["wavelength_nm"]),
        pupil_sample_count=int(options["pupil_sample_count"]),
        record_surfaces=bool(options["record_surfaces"]),
        propagate_to_image=bool(options.get("propagate_to_image", True)),
        evaluate_apertures=bool(options.get("evaluate_apertures", True)),
        max_intersection_iterations=int(options["max_intersection_iterations"]),
        output_level=str(options.get("trace_output_level", "planes")),
        polarization_sensitive=bool(options.get("polarization_sensitive", False)),
    )
    assert compact_trace_support(context.scene.system, trace_options).supported is True

    project = _project()
    project.surfaces[0].type_parameters["decenter_x_mm"] = 0.05
    payload = build_simulation_payload(project, SimulationFormState(), request_id="posed-fallback")
    posed = compile_simulation_context(SimulationRequest.model_validate(payload))
    posed_options = posed.canonical_trace_options(posed.scene.options.get("hybrid", {}))
    posed_trace_options = replace(
        trace_options,
        wavelength_nm=float(posed_options["wavelength_nm"]),
        pupil_sample_count=int(posed_options["pupil_sample_count"]),
    )
    support = compact_trace_support(posed.scene.system, posed_trace_options)
    assert support.supported is False
    assert "posed-surface" in support.reason


@pytest.mark.parametrize("polarization", [False, True])
def test_compact_trace_matches_full_trace_for_preview_formal_result(polarization: bool):
    fast = create_optical_simulation_engine().evaluate(_request(polarization=polarization), None, None)
    full = create_optical_simulation_engine().evaluate(
        _request(full_trace=True, polarization=polarization), None, None
    )
    assert fast.status == full.status == "completed"
    assert fast.converged == full.converged
    assert set(fast.metrics) == set(full.metrics)
    assert set(fast.arrays) == set(full.arrays)
    assert float(fast.metrics["coupling_efficiency"]) == pytest.approx(
        float(full.metrics["coupling_efficiency"]), abs=1.0e-10, rel=1.0e-10
    )
    for key in fast.arrays:
        left = np.asarray(fast.arrays[key])
        right = np.asarray(full.arrays[key])
        assert left.shape == right.shape, key
        if left.dtype.kind in "fci" and right.dtype.kind in "fci":
            np.testing.assert_allclose(left, right, atol=1.0e-9, rtol=1.0e-9, equal_nan=True, err_msg=key)
        else:
            assert np.array_equal(left, right), key



def test_frontend_progress_contract_uses_100_only_for_completed_and_names_tail_stages():
    assert terminal_progress("running", 1.0) == 99
    assert terminal_progress("failed", 1.0) == 99
    assert terminal_progress("completed", 0.12) == 100
    assert friendly_job_stage("result.materializing") == "正在整理结果"
    assert friendly_job_stage("result.local_ready") == "正式结果已生成，正在完成存档"
    assert friendly_job_stage("result.persisting") == "正在保存结果"


def test_full_fallback_trace_reports_intermediate_real_progress():
    class Capture:
        def __init__(self):
            self.items = []
        def update(self, progress, stage, completed_items=0, total_items=1):
            self.items.append((float(progress), str(stage)))
        def partial(self, *_args, **_kwargs):
            return None

    capture = Capture()
    result = create_optical_simulation_engine().evaluate(
        _request(full_trace=True), None, capture
    )
    assert result.status == "completed"
    values = [
        value for value, stage in capture.items
        if stage == "optical_engine.trace.running" and 0.14 < value < 0.42
    ]
    assert len(set(round(value, 4) for value in values)) >= 4
    assert max(value for value, _stage in capture.items) <= WORKER_PROGRESS_CEILING

def test_stored_npz_result_bundle_round_trips_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPTICAL_RESULT_NPZ_COMPRESSION", raising=False)
    values = np.linspace(-1.0, 1.0, 4096, dtype=np.float64).reshape(64, 64)
    payload = {
        "status": "completed",
        "metrics": {"coupling_efficiency": 0.9739467967},
        "arrays": {"field": values},
    }
    manifest = save_result_bundle(tmp_path, payload)
    assert manifest["array_compression"] == "stored"
    loaded = load_result_bundle(tmp_path)
    restored = np.asarray(loaded["arrays"]["field"], dtype=np.float64)
    assert np.array_equal(restored, values)
    on_disk = json.loads((tmp_path / "result_manifest.json").read_text(encoding="utf-8"))
    assert on_disk["array_compression"] == "stored"


def test_task_context_translates_backend_progress_stage_for_users():
    from frontend_pyside.state.task_context import TaskContext

    context = TaskContext()
    row = context.upsert_backend_job(
        {
            "job_id": "job-stage-friendly",
            "job_type": "simulation",
            "status": "running",
            "progress": 0.25,
            "stage": "optical_engine.trace.running",
            "result_available": False,
        }
    )
    assert row is not None
    assert row["note"] == "正在进行光线追迹"
    assert row["progress"] == 25



def test_task_manager_get_status_returns_atomic_copy(tmp_path):
    from backend.optical_ml_app.jobs.task_manager import TaskManager

    repo = FileJobRepository(tmp_path / "jobs")
    manager = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        job_id = manager.submit("test", _worker_claims_done_then_waits, 0.2)
        # The exact lifecycle stage is irrelevant here: a caller must receive an
        # independent snapshot rather than the mutable object stored by manager.
        snapshot = manager.get_status(job_id)
        with manager._lock:
            live = manager.records[job_id].status
            original = bool(live.result_available)
            live.result_available = not original
        assert snapshot.result_available == original
        with manager._lock:
            manager.records[job_id].status.result_available = original
    finally:
        manager.shutdown(wait=True)



def test_result_bundle_size_does_not_publish_result_before_completed(tmp_path: Path):
    from shared_contracts.jobs import JobStatus

    repo = FileJobRepository(tmp_path / "jobs")
    running = JobStatus(
        job_id="job-result-index-atomic",
        job_type="simulation",
        status="running",
        progress=0.98,
        stage="result.persisting",
        created_at="2026-08-16T00:00:00+00:00",
        started_at="2026-08-16T00:00:01+00:00",
        result_available=False,
    )
    repo.save_status(running)

    # The bundle can already exist while the authoritative task state is still
    # ``running``. Recording its byte size must not make /jobs advertise a
    # formal result early.
    repo.index.update_result_size(running.job_id, 12345, updated_mtime=time.time())
    item = next(row for row in repo.list_jobs(limit=10) if row["job_id"] == running.job_id)
    assert item["status"] == "running"
    assert item["result_available"] is False

    completed = running.model_copy(deep=True)
    completed.status = "completed"
    completed.progress = 1.0
    completed.stage = "completed"
    completed.finished_at = "2026-08-16T00:00:02+00:00"
    completed.result_available = True
    repo.save_status(completed)
    item = next(row for row in repo.list_jobs(limit=10) if row["job_id"] == running.job_id)
    assert item["status"] == "completed"
    assert item["result_available"] is True


def test_task_context_rejects_out_of_order_progress_and_result_availability_regressions():
    from frontend_pyside.state.task_context import TaskContext

    context = TaskContext()
    first = context.upsert_backend_job({
        "job_id": "job-out-of-order",
        "job_type": "training",
        "status": "running",
        "progress": 1.0,
        "stage": "result.persisting",
        "result_available": False,
    })
    assert first is not None
    # Running 100% is contradictory; the display contract reserves 100 for a
    # confirmed terminal success state.
    assert first["status"] == "运行中"
    assert first["progress"] == 99
    assert first["result_available"] is False

    stale = context.upsert_backend_job({
        "job_id": "job-out-of-order",
        "job_type": "training",
        "status": "running",
        "progress": 0.35,
        "stage": "worker.ready",
        "result_available": False,
    })
    assert stale is not None
    assert stale["progress"] == 99

    completed = context.upsert_backend_job({
        "job_id": "job-out-of-order",
        "job_type": "training",
        "status": "completed",
        "progress": 1.0,
        "stage": "completed",
        "result_available": True,
    })
    assert completed is not None
    assert completed["status"] == "已完成"
    assert completed["progress"] == 100
    assert completed["result_available"] is True

    delayed_running = context.upsert_backend_job({
        "job_id": "job-out-of-order",
        "job_type": "training",
        "status": "running",
        "progress": 0.35,
        "stage": "worker.ready",
        "result_available": False,
    })
    assert delayed_running is not None
    assert delayed_running["status"] == "已完成"
    assert delayed_running["progress"] == 100
    assert delayed_running["result_available"] is True


def test_monotonic_progress_reducer_prevents_ws_http_progress_disagreement():
    from frontend_pyside.shared.task_display import MonotonicProgress, stable_progress_text

    tracker = MonotonicProgress()
    job_id = "job-progress-race"
    assert tracker.value(job_id, "running", 0.35) == 35
    # A newer WebSocket event advances to the worker ceiling.
    assert tracker.value(job_id, "running", 1.0) == 99
    # A delayed HTTP poll must not make either the bar or text go back to 35%.
    merged = tracker.value(job_id, "running", 0.35)
    assert merged == 99
    assert stable_progress_text("running", merged / 100.0) == "进度 99%"
    assert tracker.value(job_id, "completed", 1.0) == 100


def test_persisted_simulation_result_emits_terminal_frontend_state():
    from PySide6.QtTest import QSignalSpy
    from frontend_pyside.app.bootstrap import create_app_context
    from frontend_pyside.features.simulation.controller import SimulationController

    controller = SimulationController(create_app_context(), object())
    controller._multipath = True  # keep this unit test independent of result-cache merging
    controller.current_job_id = "job-terminal-state"
    controller.current_task_id = ""
    controller.last_project_payload = {}
    spy = QSignalSpy(controller.stateChanged)

    controller._accept_result({"status": "completed", "converged": True})

    states = [str(spy.at(index)[0]) for index in range(spy.count())]
    assert "completed" in states
    assert controller.current_job_id == ""
