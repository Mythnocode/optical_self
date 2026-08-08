
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ShellController(QObject):
    connectionChanged = Signal(str, str)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        context.api_client.completed.connect(self._api_completed)
        context.api_client.failed.connect(self._api_failed)

    def check_backend_health(self) -> None:
        self.connectionChanged.emit("正在检查后端连接...", "warning")
        health = getattr(self.context.services, "health", None)
        if health is None:
            self.connectionChanged.emit("未配置后端健康检查\n教学计算：本地近似模式", "warning")
            return
        health.capabilities("main.capabilities")

    def record_page_view(self, key: str) -> None:
        try:
            self.context.services.usage.record_page_view(key)
        except Exception:
            
            return

    def _api_completed(self, key: str, data) -> None:
        if key != "main.capabilities" or not isinstance(data, dict):
            return
        nested = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        engine = data.get("default_engine", nested.get("default_engine", "未报告"))
        self.connectionChanged.emit(
            f"FastAPI 后端已连接\n引擎：{engine}\n教学计算：本地近似模式",
            "success",
        )

    def _api_failed(self, key: str, message: str) -> None:
        if key == "main.capabilities":
            self.connectionChanged.emit(
                f"后端未连接（{message}）\n教学计算：本地近似模式",
                "danger",
            )


__all__ = ["ShellController"]
