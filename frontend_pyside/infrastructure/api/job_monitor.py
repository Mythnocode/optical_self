
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from frontend_pyside.core.constants import DEFAULT_WS_URL

try:  
    from PySide6.QtNetwork import QAbstractSocket
    from PySide6.QtWebSockets import QWebSocket
except ImportError:  
    QAbstractSocket = None
    QWebSocket = None


_TERMINAL = {"completed", "failed", "cancelled"}


class CentralJobMonitor(QObject):
    job_progress = Signal(str, float, str)
    job_partial = Signal(str, dict)
    job_completed = Signal(str, str, dict)
    job_failed = Signal(str, str)
    connection_changed = Signal(bool)

    centralized_polling = True

    def __init__(self, api, url: str = DEFAULT_WS_URL, parent=None) -> None:
        super().__init__(parent)
        self.api = api
        self.url = str(url)
        self._subscribed_jobs: set[str] = set()
        self._closed_by_user = False
        self._connected = False
        self._poll_inflight: set[str] = set()
        self._last_partial_versions: dict[str, int] = {}

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_subscriptions)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(5000)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

        self.socket = QWebSocket() if QWebSocket is not None else None
        if self.socket is not None:
            self.socket.setParent(self)
            self.socket.connected.connect(self._on_connected)
            self.socket.disconnected.connect(self._on_disconnected)
            self.socket.textMessageReceived.connect(self._on_message)

        self.api.completed.connect(self._on_api_completed)
        self.api.failed.connect(self._on_api_failed)

    @property
    def is_connected(self) -> bool:
        return bool(self._connected)

    @property
    def subscribed_jobs(self) -> tuple[str, ...]:
        return tuple(sorted(self._subscribed_jobs))

    def subscribe(self, job_id: str) -> None:
        job_id = str(job_id or "")
        if not job_id:
            return
        self._closed_by_user = False
        self._subscribed_jobs.add(job_id)
        if self.socket is not None:
            if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
                self.socket.open(QUrl(self.url))
            else:
                self._send_subscribe()

        # Always perform one immediate HTTP status reconciliation, even when the
        # WebSocket is already connected. Very fast jobs can finish between the
        # POST response and the subscribe message; the server does not replay an
        # already-emitted terminal event, so relying on WebSocket-only delivery
        # can leave the UI permanently in "等待后端". The in-flight guard and
        # unsubscribe-on-terminal logic make this one-shot request safe when a
        # WebSocket event arrives first.
        if job_id not in self._poll_inflight:
            self._poll_inflight.add(job_id)
            self.api.get(f"job_monitor.status.{job_id}", f"/jobs/{job_id}")
        self._sync_fallback_timer(immediate=False)

    def unsubscribe(self, job_id: str) -> None:
        job_id = str(job_id or "")
        self._subscribed_jobs.discard(job_id)
        self._poll_inflight.discard(job_id)
        self._last_partial_versions.pop(job_id, None)
        if self.socket is not None and self._connected:
            if self._subscribed_jobs:
                self._send_subscribe()
            else:
                self.socket.sendTextMessage(json.dumps({"action": "unsubscribe"}))
        self._sync_fallback_timer()

    def unsubscribe_all(self) -> None:
        self._subscribed_jobs.clear()
        self._poll_inflight.clear()
        self._last_partial_versions.clear()
        self._poll_timer.stop()
        if self.socket is not None and self._connected:
            self.socket.sendTextMessage(json.dumps({"action": "unsubscribe"}))

    def disconnect(self) -> None:
        self._closed_by_user = True
        self._poll_timer.stop()
        self._reconnect_timer.stop()
        self._connected = False
        if self.socket is not None:
            self.socket.close()

    def _sync_fallback_timer(self, *, immediate: bool = False) -> None:
        # Keep a low-frequency HTTP reconciliation active even while the
        # WebSocket is connected. WebSocket delivery is the low-latency path,
        # but terminal events can be emitted before a newly-created job's
        # subscription reaches the server. The HTTP poll closes that race and
        # also repairs transient dropped events. Terminal handling unsubscribes
        # the job immediately, so completed jobs do not keep polling.
        should_poll = bool(self._subscribed_jobs)
        if should_poll:
            if immediate:
                self._poll_subscriptions()
            if not self._poll_timer.isActive():
                self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def _poll_subscriptions(self) -> None:
        for job_id in tuple(self._subscribed_jobs):
            if job_id in self._poll_inflight:
                continue
            self._poll_inflight.add(job_id)
            self.api.get(f"job_monitor.status.{job_id}", f"/jobs/{job_id}")

    def _on_api_completed(self, key: str, data) -> None:
        prefix = "job_monitor.status."
        if not str(key).startswith(prefix):
            return
        job_id = str(key)[len(prefix):]
        self._poll_inflight.discard(job_id)
        if job_id not in self._subscribed_jobs or not isinstance(data, dict):
            return
        self._emit_status(job_id, data)

    def _on_api_failed(self, key: str, message: str) -> None:
        prefix = "job_monitor.status."
        if not str(key).startswith(prefix):
            return
        job_id = str(key)[len(prefix):]
        self._poll_inflight.discard(job_id)
        
        if "404" in str(message) or "not found" in str(message).lower():
            self.job_failed.emit(job_id, str(message))
            self.unsubscribe(job_id)

    def _emit_status(self, job_id: str, data: dict) -> None:
        status = str(data.get("status", "") or "").lower()
        progress = float(data.get("progress", 0.0) or 0.0)
        stage = str(data.get("stage", "") or "")
        if status in {"queued", "running"}:
            version = int(data.get("result_version", 0) or 0)
            if bool(data.get("partial_result_available")) and version > self._last_partial_versions.get(job_id, 0):
                self._last_partial_versions[job_id] = version
                self.job_partial.emit(
                    job_id,
                    {
                        "stage": stage,
                        "result_version": version,
                        "metrics": dict(data.get("metrics", {}) or {}),
                    },
                )
            self.job_progress.emit(job_id, progress, stage)
            return
        if status == "failed":
            error = data.get("error") or {}
            message = error.get("message", "任务失败") if isinstance(error, dict) else str(error)
            self.job_failed.emit(job_id, str(message))
            self.unsubscribe(job_id)
            return
        if status in {"completed", "cancelled"}:
            metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
            self.job_completed.emit(job_id, status, dict(metrics))
            self.unsubscribe(job_id)

    def _on_connected(self) -> None:
        self._connected = True
        self._reconnect_timer.stop()
        self.connection_changed.emit(True)
        if self._subscribed_jobs:
            self._send_subscribe()
        self._sync_fallback_timer()

    def _on_disconnected(self) -> None:
        self._connected = False
        self.connection_changed.emit(False)
        self._sync_fallback_timer(immediate=True)
        if self._subscribed_jobs and not self._closed_by_user and not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def _on_message(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        event_type = str(data.get("type", "") or "").lower()
        job_id = str(data.get("job_id", "") or "")
        if not job_id or job_id not in self._subscribed_jobs:
            
            
            return
        if event_type == "progress":
            self.job_progress.emit(job_id, float(data.get("progress", 0.0) or 0.0), str(data.get("stage", "") or ""))
        elif event_type == "partial":
            version = int(data.get("result_version", 0) or 0)
            if version > self._last_partial_versions.get(job_id, 0):
                self._last_partial_versions[job_id] = version
                payload = dict(data.get("partial", {}) or {})
                payload.setdefault("stage", str(data.get("stage", "") or ""))
                payload.setdefault("result_version", version)
                self.job_partial.emit(job_id, payload)
        elif event_type == "completed":
            self.job_completed.emit(job_id, "completed", dict(data.get("metrics", {}) or {}))
            self.unsubscribe(job_id)
        elif event_type == "failed":
            error = data.get("error", {})
            message = error.get("message", "unknown error") if isinstance(error, dict) else str(error)
            self.job_failed.emit(job_id, str(message))
            self.unsubscribe(job_id)
        elif event_type == "cancelled":
            self.job_completed.emit(job_id, "cancelled", {})
            self.unsubscribe(job_id)
        elif event_type in {"queued", "running"}:
            self.job_progress.emit(job_id, float(data.get("progress", 0.0) or 0.0), str(data.get("stage", "") or ""))

    def _send_subscribe(self) -> None:
        if self.socket is None or not self._connected:
            return
        self.socket.sendTextMessage(json.dumps({"action": "subscribe", "job_ids": sorted(self._subscribed_jobs)}))

    def _try_reconnect(self) -> None:
        if self.socket is None or self._closed_by_user or not self._subscribed_jobs:
            self._reconnect_timer.stop()
            return
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self.socket.open(QUrl(self.url))


__all__ = ["CentralJobMonitor"]
