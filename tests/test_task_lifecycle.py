from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from backend.optical_ml_app.domain.errors import BackendApplicationError
from backend.optical_ml_app.jobs.task_manager import TaskManager
from backend.optical_ml_app.storage.filesystem_job_repository import FileJobRepository
from frontend_pyside.state.task_context import TaskContext
from frontend_pyside.shared.task_display import terminal_progress
from frontend_pyside.features.tasks.page import TasksPage
from shared_contracts.jobs import JobStatus


def _wait_status(manager: TaskManager, job_id: str, wanted: set[str], timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = manager.get_status(job_id)
        if latest.status in wanted:
            return latest
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach {wanted}; latest={latest}")


def _gate_task(context, marker_path: str):
    context.progress.update(0.15, "gate.check", 0, 1)
    if Path(marker_path).read_text(encoding="utf-8").strip() != "ok":
        raise BackendApplicationError(
            code="TEST_RETRYABLE",
            stage="gate.check",
            message="temporary gate failure",
            retryable=True,
        )
    context.progress.update(0.75, "gate.compute", 1, 1)
    return {"status": "completed", "value": 42}


def _sleep_task(context, seconds: float):
    time.sleep(float(seconds))
    return {"status": "completed", "slept": float(seconds)}


def test_retry_creates_new_real_job_id_and_replays_payload(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    marker.write_text("fail", encoding="utf-8")
    repo = FileJobRepository(tmp_path / "jobs")
    manager = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        original_id = manager.submit(
            "scan", _gate_task, str(marker), queue_timeout_seconds=5, stall_timeout_seconds=5
        )
        original = _wait_status(manager, original_id, {"failed"})
        assert original.error is not None
        assert original.error.retryable is True
        assert original.retry_available is True

        marker.write_text("ok", encoding="utf-8")
        retried = manager.retry(original_id)
        assert retried.job_id != original_id
        assert retried.retry_of == original_id
        assert retried.status in {"queued", "running"}

        completed = _wait_status(manager, retried.job_id, {"completed"})
        assert completed.result_available is True
        assert manager.get_result(retried.job_id)["value"] == 42
    finally:
        manager.shutdown(wait=True)


def test_backend_restart_recovery_preserves_retry_and_can_replay(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    marker.write_text("fail", encoding="utf-8")
    repo = FileJobRepository(tmp_path / "jobs")
    manager = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        source_id = manager.submit("scan", _gate_task, str(marker), queue_timeout_seconds=5, stall_timeout_seconds=5)
        source = _wait_status(manager, source_id, {"failed"})
        assert source.retry_available
    finally:
        manager.shutdown(wait=True)

    interrupted_id = "job-interrupted-test"
    interrupted_dir = tmp_path / "jobs" / interrupted_id
    interrupted_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tmp_path / "jobs" / source_id / "retry_payload.bin", interrupted_dir / "retry_payload.bin")
    interrupted = JobStatus(
        job_id=interrupted_id,
        job_type="scan",
        status="running",
        progress=0.43,
        stage="scan.evaluate",
        created_at=source.created_at,
        started_at=source.created_at,
        retry_available=True,
    )
    repo.save_status(interrupted)

    recovered = repo.recover_interrupted_jobs()
    assert interrupted_id in recovered
    recovered_status = repo.load_status(interrupted_id)
    assert recovered_status.status == "failed"
    assert recovered_status.progress == pytest.approx(0.43)
    assert recovered_status.error is not None
    assert recovered_status.error.code == "BACKEND_RESTARTED"
    assert recovered_status.error.retryable is True
    assert recovered_status.retry_available is True

    marker.write_text("ok", encoding="utf-8")
    manager2 = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        retried = manager2.retry(interrupted_id)
        assert retried.retry_of == interrupted_id
        done = _wait_status(manager2, retried.job_id, {"completed"})
        assert done.result_available is True
        assert manager2.get_result(retried.job_id)["value"] == 42
    finally:
        manager2.shutdown(wait=True)


def test_queue_watchdog_fails_job_instead_of_waiting_forever(tmp_path: Path):
    repo = FileJobRepository(tmp_path / "jobs")
    manager = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        first = manager.submit("test", _sleep_task, 1.5, queue_timeout_seconds=5, stall_timeout_seconds=5)
        _wait_status(manager, first, {"running"})
        queued = manager.submit("test", _sleep_task, 0.1, queue_timeout_seconds=0.25, stall_timeout_seconds=5)
        failed = _wait_status(manager, queued, {"failed"}, timeout=3)
        assert failed.error is not None
        assert failed.error.code == "QUEUE_TIMEOUT"
        assert failed.error.retryable is True
        assert failed.progress == pytest.approx(0.0)
    finally:
        manager.shutdown(wait=False)


def test_stall_watchdog_stops_silent_worker(tmp_path: Path):
    repo = FileJobRepository(tmp_path / "jobs")
    manager = TaskManager(repo, max_workers=1, persistent_workers={})
    try:
        job_id = manager.submit(
            "test", _sleep_task, 2.0, queue_timeout_seconds=5, stall_timeout_seconds=0.35
        )
        failed = _wait_status(manager, job_id, {"failed"}, timeout=3)
        assert failed.error is not None
        assert failed.error.code == "WORKER_STALLED"
        assert failed.error.retryable is True
        assert failed.progress < 1.0
    finally:
        manager.shutdown(wait=False)


def test_task_context_preserves_result_retry_error_flags_and_dedupes_logs():
    app = QApplication.instance() or QApplication([])
    del app
    context = TaskContext()
    task = context.upsert_backend_job(
        {
            "job_id": "job-abc",
            "job_type": "scan",
            "status": "failed",
            "progress": 0.43,
            "result_available": False,
            "retry_available": True,
            "error": {
                "code": "BACKEND_RESTARTED",
                "stage": "backend.restarted",
                "message": "backend restarted before the job reached a terminal state",
                "retryable": True,
                "context": {},
            },
        }
    )
    assert task is not None
    assert task["progress"] == 43
    assert task["result_available"] is False
    assert task["retry_available"] is True
    assert task["error_retryable"] is True
    assert task["error_code"] == "BACKEND_RESTARTED"
    assert "后端" in task["note"]

    context.append_log("job-abc", "same terminal failure", level="ERROR")
    context.append_log("job-abc", "same terminal failure", level="ERROR")
    assert len(context.logs("job-abc")) == 1


def test_tasks_page_failed_job_disables_result_keeps_real_progress_and_allows_retry():
    app = QApplication.instance() or QApplication([])
    del app

    class _Context:
        def __init__(self):
            self.tasks = TaskContext()
            self.api_client = None

    context = _Context()
    page = TasksPage(context)
    try:
        failed = context.tasks.upsert_backend_job(
            {
                "job_id": "job-failed-ui",
                "job_type": "scan",
                "status": "failed",
                "progress": 0.43,
                "result_available": False,
                "retry_available": True,
                "error": {
                    "code": "BACKEND_RESTARTED",
                    "stage": "backend.restarted",
                    "message": "backend restarted before the job reached a terminal state",
                    "retryable": True,
                    "context": {},
                },
            }
        )
        assert failed is not None
        page._show_task_detail(failed)
        assert page.progress.value() == 43
        assert page.detail_view_result.isEnabled() is False
        assert page.retry_button.isEnabled() is True

        completed = context.tasks.upsert_backend_job(
            {
                "job_id": "job-completed-ui",
                "job_type": "scan",
                "status": "completed",
                "progress": 1.0,
                "result_available": True,
                "retry_available": True,
            }
        )
        assert completed is not None
        page._show_task_detail(completed)
        assert page.progress.value() == 100
        assert page.detail_view_result.isEnabled() is True
        assert page.retry_button.isEnabled() is False
    finally:
        page.close()


def test_retry_button_does_not_create_ghost_task_before_backend_returns_job_id():
    app = QApplication.instance() or QApplication([])
    del app

    class _Context:
        def __init__(self):
            self.tasks = TaskContext()
            self.api_client = None

    class _FakeJobClient:
        def __init__(self):
            self.calls = []

        def retry(self, key: str, job_id: str) -> None:
            self.calls.append((key, job_id))

        def list_jobs(self, key: str, *, limit: int = 20, offset: int = 0, status=None, job_type=None) -> None:
            del key, limit, offset, status, job_type

    context = _Context()
    page = TasksPage(context)
    fake = _FakeJobClient()
    page.job_client = fake
    try:
        failed = context.tasks.upsert_backend_job(
            {
                "job_id": "job-old",
                "job_type": "scan",
                "status": "failed",
                "progress": 0.43,
                "result_available": False,
                "retry_available": True,
                "error": {
                    "code": "BACKEND_RESTARTED",
                    "stage": "backend.restarted",
                    "message": "backend restarted before the job reached a terminal state",
                    "retryable": True,
                    "context": {},
                },
            }
        )
        assert failed is not None
        page._selected_task_override = failed
        before_ids = {str(row.get("id")) for row in context.tasks.tasks}

        page._retry_selected()

        after_submit_ids = {str(row.get("id")) for row in context.tasks.tasks}
        assert fake.calls == [("tasks.retry.job-old", "job-old")]
        assert after_submit_ids == before_ids, "frontend must not fabricate a waiting task without a backend job_id"

        page._api_completed(
            "tasks.retry.job-old",
            {
                "job_id": "job-new",
                "job_type": "scan",
                "status": "queued",
                "progress": 0.0,
                "result_available": False,
                "retry_available": True,
                "retry_of": "job-old",
            },
        )
        new_task = next((row for row in context.tasks.tasks if row.get("job_id") == "job-new"), None)
        assert new_task is not None
        assert new_task.get("retry_of") == "job-old"
        assert str(new_task.get("status")) in {"等待后端", "排队中", "等待中"}
    finally:
        page.close()


def test_failed_task_result_action_never_requests_backend_when_result_unavailable():
    app = QApplication.instance() or QApplication([])
    del app

    class _Context:
        def __init__(self):
            self.tasks = TaskContext()
            self.api_client = None

    class _FakeJobClient:
        def __init__(self):
            self.result_calls = []

        def get_result(self, key: str, job_id: str) -> None:
            self.result_calls.append((key, job_id))

    context = _Context()
    page = TasksPage(context)
    fake = _FakeJobClient()
    page.job_client = fake
    try:
        failed = context.tasks.upsert_backend_job(
            {
                "job_id": "job-no-result",
                "job_type": "scan",
                "status": "failed",
                "progress": 0.17,
                "result_available": False,
                "retry_available": True,
                "error": {
                    "code": "BACKEND_RESTARTED",
                    "stage": "backend.restarted",
                    "message": "backend restarted before the job reached a terminal state",
                    "retryable": True,
                },
            }
        )
        assert failed is not None
        page._selected_task_override = failed
        page._show_task_detail(failed)
        assert page.detail_view_result.isEnabled() is False

        page._view_selected_result()

        assert fake.result_calls == []
        assert "没有可用的正式结果" in page.artifact_text.text()
    finally:
        page.close()


def test_nonterminal_progress_never_claims_100_percent():
    assert terminal_progress("queued", 1.0) == 99
    assert terminal_progress("running", 1.0) == 99
    assert terminal_progress("failed", 1.0) == 99
    assert terminal_progress("cancelled", 1.0) == 99
    assert terminal_progress("completed", 1.0) == 100


def test_task_context_terminal_truth_survives_stale_running_response():
    context = TaskContext()
    running = context.upsert_backend_job({
        "job_id": "job-terminal-truth",
        "job_type": "scan",
        "status": "running",
        "progress": 1.0,
        "result_available": False,
    })
    assert running is not None
    assert running["status"] == "运行中"
    assert running["progress"] == 99

    completed = context.upsert_backend_job({
        "job_id": "job-terminal-truth",
        "job_type": "scan",
        "status": "completed",
        "progress": 1.0,
        "result_available": True,
    })
    assert completed is not None
    assert completed["status"] == "已完成"
    assert completed["progress"] == 100
    assert completed["result_available"] is True

    stale = context.upsert_backend_job({
        "job_id": "job-terminal-truth",
        "job_type": "scan",
        "status": "running",
        "progress": 0.35,
        "result_available": False,
        "stage": "worker.running",
    })
    assert stale is not None
    assert stale["status"] == "已完成"
    assert stale["progress"] == 100
    assert stale["result_available"] is True
    assert stale["stage"] == "completed"
