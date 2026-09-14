"""布局持久化：CanvasSnapshot（节点/边/相机）⇄ QSettings（JSON），700ms 防抖写入。

快照结构::

    {
        "version": 1,
        "canvas": {"version": 1, "nodes": [...], "edges": [...]},
        "zoom": 1.0,
    }

- scene.layoutDirty → schedule_save（防抖合并拖拽/调大小高频事件）；
- 启动时 load() 一次；恢复失败（结构损坏/版本不识别）返回 None，壳层走默认种子。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, QTimer

SNAPSHOT_VERSION = 1
_DEBOUNCE_MS = 700


class LayoutStore(QObject):
    """画布快照的防抖持久化（QSettings）。"""

    def __init__(
        self,
        settings_key: str = "canvas_centric/layout_v1",
        *,
        debounce_ms: int = _DEBOUNCE_MS,
        parent=None,
    ):
        super().__init__(parent)
        self._key = str(settings_key)
        self._provider: Callable[[], dict[str, Any]] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(debounce_ms))
        self._timer.timeout.connect(self._flush)

    # ---- 读取 -----------------------------------------------------------

    def load(self) -> dict[str, Any] | None:
        raw = QSettings().value(self._key)
        if not raw:
            return None
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return None
        if not isinstance(raw, dict):
            return None
        if int(raw.get("version", 0)) != SNAPSHOT_VERSION:
            return None
        canvas = raw.get("canvas")
        if not isinstance(canvas, dict) or not isinstance(canvas.get("nodes"), list):
            return None
        return raw

    # ---- 写入 -----------------------------------------------------------

    def schedule_save(self, provider: Callable[[], dict[str, Any]]) -> None:
        """注册快照提供者并启动防抖计时（重复调用仅刷新计时）。"""
        self._provider = provider
        self._timer.start()

    def flush(self) -> None:
        """立即落盘（窗口关闭时调用；无挂起写入则跳过）。"""
        if self._provider is not None and self._timer.isActive():
            self._flush()

    def clear(self) -> None:
        self._timer.stop()
        self._provider = None
        QSettings().remove(self._key)

    def _flush(self) -> None:
        provider, self._provider = self._provider, None
        if provider is None:
            return
        try:
            data = provider()
        except Exception:
            return  # 序列化失败不落盘，避免覆盖最后一份可用布局
        try:
            QSettings().setValue(self._key, json.dumps(data, ensure_ascii=False))
        except (TypeError, ValueError):
            pass


__all__ = ["LayoutStore", "SNAPSHOT_VERSION"]
