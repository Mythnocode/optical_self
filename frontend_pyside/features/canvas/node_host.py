"""节点内容宿主：面板级 QWidget 经 QGraphicsProxyWidget 懒加载嵌入。

内置加载占位 / 工厂调用 / 错误重试 / dispose 骨架；
面板级 widget 直接嵌入，整页 page.py 禁止注册（方案 §10 尺寸爆炸红线）。
"""

from __future__ import annotations

import importlib
import traceback

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsProxyWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.app.startup import append_startup_log
from frontend_pyside.shared.lifecycle import dispose_widget_tree


class NodeHost(QGraphicsProxyWidget):
    """在 CanvasNode 展开态承载懒加载面板。"""

    contentReady = Signal(object)
    contentFailed = Signal(str)

    def __init__(self, parent_node, factory_path: str, parent=None):
        # 关键：作为 parent_node 的子项挂载 —— sync_geometry 的坐标全是节点局部坐标；
        # 若不挂载，proxy 会落在场景 (12,38) 处，节点体一片空白
        super().__init__(parent_node)
        self.parent_node = parent_node
        self.factory_path = str(factory_path)
        self._container: QWidget | None = None
        self._content: QWidget | None = None
        self._loading = False
        self._disposed = False
        # 嵌入 widget 的 sizeHint 经常宽过卡片；裁剪 + 锁定最大尺寸，避免画出圆角框。
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsToShape, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)

        self.setWidget(self._build_placeholder("展开后加载面板…"))

    # ---- 加载 -----------------------------------------------------------

    def ensure_loaded(self, factory_args: tuple = (), factory_kwargs: dict | None = None) -> None:
        if self._disposed or self._loading or self._content is not None:
            return
        self._loading = True
        try:
            module_name, attr = self.factory_path.rsplit(":", 1)
            factory = getattr(importlib.import_module(module_name), attr)
            content = factory(*factory_args, **(factory_kwargs or {}))
            if not isinstance(content, QWidget):
                raise TypeError(f"{self.factory_path} 返回的不是 QWidget")
            self._install(content)
            self.contentReady.emit(content)
        except Exception as exc:
            details = traceback.format_exc()
            append_startup_log(f"CANVAS NODE LOAD FAILED: {self.parent_node.node_id}", details)
            self.setWidget(self._build_error(str(exc)))
            self.contentFailed.emit(str(exc))
        finally:
            self._loading = False

    def retry(self) -> None:
        if self._disposed or self._content is not None:
            return
        self.setWidget(self._build_placeholder("正在重新加载…"))
        QTimer.singleShot(0, lambda: self.ensure_loaded())

    # ---- 布局跟随节点尺寸 ---------------------------------------------------

    def set_panel(self, widget: QWidget) -> None:
        """直接挂载已构建的面板（TaskNode/ConfigNode 等自建内容）。"""
        self._install(widget)

    def shape(self):
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def sync_geometry(self, x: float, y: float, w: float, h: float) -> None:
        self.setPos(x, y)
        self._lock_size(max(40.0, w), max(40.0, h))

    def set_content_visible(self, visible: bool) -> None:
        self.setVisible(bool(visible))
        if self._content is not None:
            self._content.setEnabled(bool(visible))

    # ---- 生命周期 -----------------------------------------------------------

    @property
    def content(self) -> QWidget | None:
        return self._content

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        if self._content is not None:
            dispose_widget_tree(self._content)
            self._content = None

    # ---- 内部 -----------------------------------------------------------

    def _install(self, content: QWidget) -> None:
        if self._container is None:
            self._container = QWidget()
            layout = QVBoxLayout(self._container)
            layout.setContentsMargins(0, 0, 0, 0)
            self.setWidget(self._container)
        else:
            old = self._content
            if old is not None:
                self._container.layout().removeWidget(old)
                dispose_widget_tree(old)
        self._container.layout().addWidget(content)
        self._content = content
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._apply_size()

    def _lock_size(self, w: float, h: float) -> None:
        """Keep the proxy at the node content rect even if the widget sizeHint is wider."""
        width, height = max(40.0, w), max(40.0, h)
        self.setMinimumSize(0.0, 0.0)
        self.setMaximumSize(width, height)
        self.resize(width, height)
        if self._container is not None:
            iw, ih = int(width), int(height)
            self._container.setMinimumSize(0, 0)
            self._container.setMaximumSize(iw, ih)
            self._container.setFixedSize(iw, ih)
        if self._content is not None:
            self._content.setMaximumWidth(int(width))

    def _apply_size(self) -> None:
        if self._container is None:
            return
        w, h = self.parent_node._full_w - 24.0, self.parent_node._full_h - self.parent_node.HEADER_H - 16.0
        self.setPos(12.0, self.parent_node.HEADER_H + 8.0)
        self._lock_size(w, h)

    def _build_placeholder(self, text: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        from PySide6.QtWidgets import QLabel

        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #71767E; background: transparent;")
        layout.addWidget(label)
        return box

    def _build_error(self, message: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        from PySide6.QtWidgets import QLabel

        label = QLabel(f"面板加载失败：{message}")
        label.setWordWrap(True)
        label.setStyleSheet("color: #B00020; background: transparent;")
        layout.addWidget(label)
        retry = QPushButton("重试")
        retry.clicked.connect(self.retry)
        layout.addWidget(retry, 0, Qt.AlignmentFlag.AlignHCenter)
        return box


__all__ = ["NodeHost"]
