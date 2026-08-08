from __future__ import annotations

import json
from time import perf_counter

from PySide6.QtCore import QObject, QThreadPool, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from frontend_pyside.core.constants import DEFAULT_API_BASE
from frontend_pyside.infrastructure.workers.worker import FunctionWorker
from frontend_pyside.shared.performance import record_perf


class ApiClient(QObject):


    completed = Signal(str, object)
    failed = Signal(str, str)
    binary_completed = Signal(str, bytes)

    def __init__(self, base_url: str = DEFAULT_API_BASE, parent=None):
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")
        self.manager = QNetworkAccessManager(self)
        self._workers: set[FunctionWorker] = set()
        self._inflight_gets: dict[str, list[str]] = {}
        self._inflight_binary_gets: dict[str, list[str]] = {}

    def get(self, key: str, path: str) -> None:
        path = str(path)
        pending = self._inflight_gets.get(path)
        if pending is not None:
            pending.append(str(key))
            return
        keys = [str(key)]
        self._inflight_gets[path] = keys
        reply = self.manager.get(QNetworkRequest(QUrl(self.base_url + path)))
        reply.setProperty("perf_started", perf_counter())
        reply.setProperty("perf_path", path)
        reply.finished.connect(lambda: self._finish_json_get(path, reply))

    def post(self, key: str, path: str, payload: dict) -> None:
        request = QNetworkRequest(QUrl(self.base_url + path))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reply = self.manager.post(request, body)
        reply.setProperty("perf_started", perf_counter())
        reply.setProperty("perf_path", path)
        reply.finished.connect(lambda: self._finish_json((str(key),), reply))

    def get_binary(self, key: str, path: str) -> None:
        path = str(path)
        pending = self._inflight_binary_gets.get(path)
        if pending is not None:
            pending.append(str(key))
            return
        keys = [str(key)]
        self._inflight_binary_gets[path] = keys
        reply = self.manager.get(QNetworkRequest(QUrl(self.base_url + path)))
        reply.setProperty("perf_started", perf_counter())
        reply.setProperty("perf_path", path)
        reply.finished.connect(lambda: self._finish_binary_get(path, reply))

    def _finish_json_get(self, path: str, reply: QNetworkReply) -> None:
        keys = tuple(self._inflight_gets.pop(str(path), []) or [str(path)])
        self._finish_json(keys, reply)

    def _finish_json(self, keys: tuple[str, ...], reply: QNetworkReply) -> None:
        started = reply.property("perf_started")
        path = str(reply.property("perf_path") or "")
        raw = bytes(reply.readAll())
        if isinstance(started, (int, float)):
            record_perf(
                "api_request",
                (perf_counter() - float(started)) * 1000.0,
                key=keys[0] if keys else "",
                path=path,
                coalesced=len(keys),
                bytes=len(raw),
            )
        network_error = reply.error() != QNetworkReply.NetworkError.NoError
        error_string = reply.errorString()
        reply.deleteLater()

        worker = FunctionWorker(
            self._decode_json_response,
            keys,
            raw,
            network_error,
            error_string,
        )
        self._workers.add(worker)
        worker.signals.result.connect(self._json_decoded)
        worker.signals.error.connect(lambda message, request_keys=keys: self._emit_failed_many(request_keys, message))
        worker.signals.finished.connect(lambda w=worker: self._workers.discard(w))
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _decode_json_response(
        keys: tuple[str, ...],
        raw: bytes,
        network_error: bool,
        error_string: str,
    ) -> tuple[tuple[str, ...], object, bool, str, str, float]:
        started = perf_counter()
        text = raw.decode("utf-8", errors="replace")
        try:
            body = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            if network_error:
                raise RuntimeError(text or error_string or "后端请求失败") from exc
            raise RuntimeError(text or "服务器返回了无效 JSON 响应") from exc
        elapsed_ms = (perf_counter() - started) * 1000.0
        return keys, body, network_error, error_string, text, elapsed_ms

    def _json_decoded(self, result: tuple) -> None:
        keys, body, network_error, error_string, raw_text, elapsed_ms = result
        first_key = keys[0] if keys else ""
        record_perf(
            "api_json_decode", float(elapsed_ms), key=first_key,
            bytes=len(raw_text.encode("utf-8")), coalesced=len(keys),
        )
        if network_error:
            message = body.get("message") if isinstance(body, dict) else None
            self._emit_failed_many(keys, str(message or raw_text or error_string))
            return
        data = body.get("data", body) if isinstance(body, dict) else body
        for key in keys:
            self.completed.emit(str(key), data)

    def _emit_failed_many(self, keys, message: str) -> None:
        for key in tuple(keys):
            self.failed.emit(str(key), str(message))

    def _finish_binary_get(self, path: str, reply: QNetworkReply) -> None:
        keys = tuple(self._inflight_binary_gets.pop(str(path), []) or [str(path)])
        self._finish_binary(keys, reply)

    def _finish_binary(self, keys: tuple[str, ...], reply: QNetworkReply) -> None:
        started = reply.property("perf_started")
        path = str(reply.property("perf_path") or "")
        if isinstance(started, (int, float)):
            record_perf(
                "api_request",
                (perf_counter() - float(started)) * 1000.0,
                key=keys[0] if keys else "",
                path=path,
                binary=True,
                coalesced=len(keys),
            )
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._emit_failed_many(keys, reply.errorString())
        else:
            payload = bytes(reply.readAll())
            for key in keys:
                self.binary_completed.emit(str(key), payload)
        reply.deleteLater()
