"""节点内容全屏覆盖层（⛶）。

- 只承载节点提供的全屏 widget（教学 3D 节点：独立 3D 视图 + 参数条）；
- Esc 或「退出全屏」按钮关闭；关闭时把 widget 交还节点回收；
- 画布主窗口保持不动，全屏层是独立顶层窗口。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget



class FullscreenOverlay(QWidget):
    """节点全屏层：一个内容 widget + 右上角退出按钮 + Esc。"""

    def __init__(self, node, widget: QWidget, parent=None):
        super().__init__(None)  # 独立顶层窗口，不随画布裁剪
        self._node = node
        self._widget = widget
        self.setObjectName("nodeFullscreenOverlay")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            "QWidget#nodeFullscreenOverlay { background: #F3F4F6; }"
            "QToolButton#nodeFullscreenExit { background: #FFFFFF; color: #0F172A;"
            " border: 1px solid #334155; border-radius: 6px; padding: 5px 12px; font-size: 12px; }"
            "QToolButton#nodeFullscreenExit:hover { background: #E5E7EB; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        widget.setParent(self)
        layout.addWidget(widget)

        self.exit_button = QToolButton(self)
        self.exit_button.setObjectName("nodeFullscreenExit")
        self.exit_button.setText("退出全屏 (Esc)")
        self.exit_button.clicked.connect(self.close)
        self.exit_button.adjustSize()

        # setWindowState 会同步触发 resizeEvent；退出按钮必须先建好
        self.setWindowState(Qt.WindowState.WindowFullScreen)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        button = getattr(self, "exit_button", None)
        if button is None:
            return
        margin = 14
        button.move(self.width() - button.width() - margin, margin)
        button.raise_()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        callback = getattr(self._node, "close_fullscreen_widget", None)
        if callable(callback):
            callback(self._widget)
        super().closeEvent(event)


def open_node_fullscreen(node) -> bool:
    """节点 ⛶ chrome 的统一入口：节点提供 create_fullscreen_widget() 即可全屏。"""
    existing = getattr(node, "_fullscreen_overlay", None)
    if existing is not None:
        existing.showFullScreen()
        existing.raise_()
        existing.activateWindow()
        return True
    factory = getattr(node, "create_fullscreen_widget", None)
    widget = factory() if callable(factory) else None
    if widget is None:
        return False
    overlay = FullscreenOverlay(node, widget)
    # 独立顶层 QWidget 没有 Qt parent；必须由节点持有 Python 引用，
    # 否则全屏函数返回后可能被回收，表现为全屏闪退/不出现。
    node._fullscreen_overlay = overlay
    overlay.destroyed.connect(lambda *_args: setattr(node, "_fullscreen_overlay", None))
    overlay.showFullScreen()
    return True


__all__ = ["FullscreenOverlay", "open_node_fullscreen"]
