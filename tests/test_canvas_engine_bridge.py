from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from frontend_pyside.features.canvas.engine_bridge import EngineBridge
from frontend_pyside.features.canvas.refresh_controller import RefreshController


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_engine_bridge_stop_does_not_emit_result():
    _app()
    received: list[dict] = []
    bridge = EngineBridge()
    bridge.resultReady.connect(received.append)
    bridge.stop()
    bridge._emit_result({"version": 1, "status": "completed"})
    assert received == []
    assert bridge.run_async([]) == 0


def test_refresh_controller_shutdown_stops_new_requests():
    _app()
    received: list[dict] = []
    controller = RefreshController()
    controller.resultReady.connect(received.append)
    controller.shutdown()
    assert controller.request_refresh([]) == 0
    controller._bridge._emit_result({"version": 1, "status": "completed"})
    assert received == []
