

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from frontend_pyside.core.constants import DEFAULT_WS_URL


class WebSocketJobWatcher(QObject):


    job_progress = Signal(str, float, str)
    job_partial = Signal(str, dict)
    job_completed = Signal(str, str, dict)
    job_failed = Signal(str, str)
    connection_changed = Signal(bool)

    def __init__(self, url: str = DEFAULT_WS_URL, parent=None):
        super().__init__(parent)
        self.url = url
        self.socket = QWebSocket()
        self.socket.setParent(self)
        self._subscribed_jobs: set[str] = set()
        self._closed_by_user = False
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(5000)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.textMessageReceived.connect(self._on_message)

    def subscribe(self, job_id: str) -> None:
        if not job_id:
            return
        self._closed_by_user = False
        self._subscribed_jobs.add(str(job_id))
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self.socket.open(QUrl(self.url))
        else:
            self._send_subscribe()

    def unsubscribe(self, job_id: str) -> None:
        self._subscribed_jobs.discard(str(job_id or ""))
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self._send_subscribe() if self._subscribed_jobs else self.socket.sendTextMessage(json.dumps({"action": "unsubscribe"}))

    def unsubscribe_all(self) -> None:
        self._subscribed_jobs.clear()
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.sendTextMessage(json.dumps({"action": "unsubscribe"}))

    def disconnect(self) -> None:
        self._closed_by_user = True
        self._reconnect_timer.stop()
        self.socket.close()

    def _on_connected(self) -> None:
        self._reconnect_timer.stop()
        self.connection_changed.emit(True)
        if self._subscribed_jobs:
            self._send_subscribe()

    def _on_disconnected(self) -> None:
        self.connection_changed.emit(False)
        if self._subscribed_jobs and not self._closed_by_user:
            self._reconnect_timer.start()

    def _on_message(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return

        event_type = str(data.get("type", ""))
        job_id = str(data.get("job_id", ""))
        if not job_id or job_id not in self._subscribed_jobs:
            return
        if event_type == "progress":
            self.job_progress.emit(job_id, float(data.get("progress", 0.0)), str(data.get("stage", "")))
        elif event_type == "partial":
            payload = dict(data.get("partial", {}) or {})
            payload.setdefault("stage", str(data.get("stage", "") or ""))
            payload.setdefault("result_version", int(data.get("result_version", 0) or 0))
            self.job_partial.emit(job_id, payload)
        elif event_type == "completed":
            self.job_completed.emit(job_id, "completed", dict(data.get("metrics", {})))
        elif event_type == "failed":
            error = data.get("error", {})
            message = error.get("message", "unknown error") if isinstance(error, dict) else str(error)
            self.job_failed.emit(job_id, str(message))
        elif event_type in {"queued", "running", "cancelled"}:
            self.job_completed.emit(job_id, event_type, {})

    def _send_subscribe(self) -> None:
        self.socket.sendTextMessage(
            json.dumps({"action": "subscribe", "job_ids": sorted(self._subscribed_jobs)})
        )

    def _try_reconnect(self) -> None:
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self.socket.open(QUrl(self.url))
