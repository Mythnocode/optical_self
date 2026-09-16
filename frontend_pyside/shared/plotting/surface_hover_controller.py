
"""光学表面悬停提示控制器。

本模块把鼠标位置映射到最近的光学表面并延迟更新提示，避免快速移动鼠标时
频繁触发昂贵的场景查询或 Qt 重绘。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QToolTip


class SurfaceHoverController:
    def __init__(self, canvas, *, delay_ms: int = 650):
        self.canvas = canvas
        self.delay_ms = max(100, int(delay_ms))
        self.pick_artists: dict[object, int] = {}
        self.surface_data: dict[int, dict] = {}
        self._candidate: int | None = None
        self.timer = QTimer(canvas)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._show)
        self._connection = canvas.mpl_connect("motion_notify_event", self._motion)

    def update(self, *, pick_artists: dict, surfaces: list[dict]) -> None:
        self.pick_artists = dict(pick_artists)
        self.surface_data = {
            int(item.get("surface_index", -1)): dict(item)
            for item in surfaces
            if int(item.get("surface_index", -1)) >= 0
        }
        self._candidate = None
        self.timer.stop()

    def clear(self) -> None:
        self.update(pick_artists={}, surfaces=[])

    def _motion(self, event) -> None:
        candidate = None
        for artist, index in self.pick_artists.items():
            try:
                contains, _ = artist.contains(event)
            except Exception:
                continue
            if contains:
                candidate = int(index)
                break
        if candidate == self._candidate:
            return
        self._candidate = candidate
        self.timer.stop()
        if candidate is None:
            QToolTip.hideText()
            return
        self.timer.start(self.delay_ms)

    def _show(self) -> None:
        item = self.surface_data.get(self._candidate or -1)
        if not item:
            return
        text = (
            f"S{int(item.get('surface_index', -1)) + 1} · {item.get('name', '')}\n"
            f"类型：{item.get('type', '—')}　材料：{item.get('material', '—')}\n"
            f"曲率半径：{float(item.get('radius', 0.0) or 0.0):.6g} mm\n"
            f"半口径：{float(item.get('aperture', 0.0) or 0.0):.6g} mm　"
            f"圆锥系数：{float(item.get('conic', 0.0) or 0.0):.6g}"
        )
        QToolTip.showText(QCursor.pos(), text, self.canvas)


__all__ = ["SurfaceHoverController"]
