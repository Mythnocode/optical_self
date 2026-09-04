from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import frontend_pyside.infrastructure.api.job_monitor as job_monitor_module


class FakeApi(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.gets: list[tuple[str, str]] = []

    def get(self, key: str, path: str) -> None:
        self.gets.append((key, path))


def _app():
    return QApplication.instance() or QApplication([])


def test_connected_monitor_keeps_http_reconciliation_until_terminal(monkeypatch):
    _app()
    monkeypatch.setattr(job_monitor_module, "QWebSocket", None)
    api = FakeApi()
    monitor = job_monitor_module.CentralJobMonitor(api)
    monitor._connected = True  # simulate a healthy WebSocket transport
    completed: list[tuple] = []
    monitor.job_completed.connect(lambda *args: completed.append(args))

    monitor.subscribe("fast-job")
    assert api.gets == [("job_monitor.status.fast-job", "/jobs/fast-job")]
    assert monitor._poll_timer.isActive()

    # First reconciliation can legitimately race and still see the task running.
    api.completed.emit(
        "job_monitor.status.fast-job",
        {"job_id": "fast-job", "status": "running", "progress": 0.3, "stage": "compute"},
    )
    assert "fast-job" in monitor.subscribed_jobs

    # Even though the WebSocket is connected, the next reconciliation is allowed.
    monitor._poll_subscriptions()
    assert api.gets[-1] == ("job_monitor.status.fast-job", "/jobs/fast-job")
    api.completed.emit(
        "job_monitor.status.fast-job",
        {"job_id": "fast-job", "status": "completed", "progress": 1.0, "metrics": {"ok": 1}},
    )
    assert completed and completed[-1][0] == "fast-job" and completed[-1][1] == "completed"
    assert "fast-job" not in monitor.subscribed_jobs
    assert not monitor._poll_timer.isActive()
