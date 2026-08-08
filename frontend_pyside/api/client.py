import json
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply


class ApiClient(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, base_url="http://127.0.0.1:8000/api/v1", parent=None):
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")
        self.manager = QNetworkAccessManager(self)

    def get(self, key, path):
        reply = self.manager.get(QNetworkRequest(QUrl(self.base_url + path)))
        reply.finished.connect(lambda: self._finish(key, reply))

    def post(self, key, path, payload):
        request = QNetworkRequest(QUrl(self.base_url + path))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        reply = self.manager.post(request, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        reply.finished.connect(lambda: self._finish(key, reply))

    def _finish(self, key, reply):
        data = bytes(reply.readAll()).decode("utf-8", errors="replace")
        if reply.error() == QNetworkReply.NoError:
            self.completed.emit(key, json.loads(data or "{}"))
        else:
            self.failed.emit(key, data)
        reply.deleteLater()
