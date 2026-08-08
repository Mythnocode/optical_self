from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from frontend_pyside.core.constants import DEFAULT_WS_URL


class WebSocketClient(QObject):


    progress_received = Signal(str, float, str)
    status_changed = Signal(str, str)
    completed_received = Signal(str, dict)
    failed_received = Signal(str, str)
    error = Signal(str)

    def __init__(self, url: str = DEFAULT_WS_URL, parent=None):
        super().__init__(parent)
        self.url = url
        self.socket = QWebSocket()
        self.socket.textMessageReceived.connect(self._message)
        self.socket.errorOccurred.connect(lambda _: self.error.emit(self.socket.errorString()))

    def connect_server(self) -> None:
        self.socket.open(QUrl(self.url))

    def disconnect_server(self) -> None:
        self.socket.close()

    def subscribe(self, job_ids) -> None:
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.sendTextMessage(json.dumps({"action": "subscribe", "job_ids": list(job_ids)}))

    def _message(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return

        event_type = str(data.get("type", ""))
        job_id = str(data.get("job_id", ""))
        if event_type == "progress":
            self.progress_received.emit(job_id, float(data.get("progress", 0.0)), str(data.get("stage", "")))
        elif event_type in {"queued", "running", "cancelled"}:
            self.status_changed.emit(job_id, event_type)
        elif event_type == "completed":
            self.completed_received.emit(job_id, dict(data.get("metrics", {})))
        elif event_type == "failed":
            error = data.get("error", {})
            message = error.get("message", "unknown error") if isinstance(error, dict) else str(error)
            self.failed_received.emit(job_id, str(message))
