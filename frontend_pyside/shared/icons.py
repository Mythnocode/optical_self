from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

try:  
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  
    QSvgRenderer = None


_ICON_ROOT = Path(__file__).resolve().parents[1] / "resources" / "icons"


@lru_cache(maxsize=128)
def _svg_text(name: str) -> str:
    path = _ICON_ROOT / f"{name}.svg"
    return path.read_text(encoding="utf-8") if path.exists() else ""


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#FFFFFF", size: int = 24) -> QIcon:

    path = _ICON_ROOT / f"{name}.svg"
    if not path.exists():
        return QIcon()
    if QSvgRenderer is None:
        return QIcon(str(path))
    try:
        svg = _svg_text(name).replace("#FFFFFF", color)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pixmap = QPixmap(QSize(int(size), int(size)))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon(str(path))


@lru_cache(maxsize=128)
def icon_path(name: str) -> str:
    return str(_ICON_ROOT / f"{name}.svg")


__all__ = ["icon", "icon_path"]
