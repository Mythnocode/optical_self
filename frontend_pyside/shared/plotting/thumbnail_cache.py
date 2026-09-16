
"""绘图缩略图缓存。

它保存小尺寸预览的最近使用结果，用于页面导航或结果列表快速展示；正式图表
仍由结果工作区和对应渲染器生成。
"""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap


class ThumbnailPixmapCache:
    def __init__(self, max_items: int = 64, size: QSize | None = None) -> None:
        self.max_items = max(1, int(max_items))
        self.size = size or QSize(240, 140)
        self._items: OrderedDict[str, QPixmap] = OrderedDict()

    def get(self, key: str) -> QPixmap | None:
        key = str(key)
        pixmap = self._items.get(key)
        if pixmap is not None:
            self._items.move_to_end(key)
        return pixmap

    def put_pixmap(self, key: str, pixmap: QPixmap) -> QPixmap:
        scaled = pixmap.scaled(
            self.size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._items[str(key)] = scaled
        self._items.move_to_end(str(key))
        self._trim()
        return scaled

    def put_png_bytes(self, key: str, data: bytes) -> QPixmap | None:
        image = QImage.fromData(bytes(data), "PNG")
        if image.isNull():
            return None
        return self.put_pixmap(key, QPixmap.fromImage(image))

    def put_figure(self, key: str, figure) -> QPixmap | None:
        
        
        buffer = BytesIO()
        try:
            figure.savefig(buffer, format="png", dpi=72, bbox_inches="tight")
        except Exception:
            return None
        return self.put_png_bytes(key, buffer.getvalue())

    def clear(self) -> None:
        self._items.clear()

    def _trim(self) -> None:
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)


__all__ = ["ThumbnailPixmapCache"]
