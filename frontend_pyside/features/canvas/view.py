"""画布相机：QGraphicsView（拖拽平移 / 滚轮缩放 / fit_all / 聚焦节点）。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from frontend_pyside.features.canvas.theme import C


class CanvasView(QGraphicsView):
    """滚轮缩放（光标锚定）；拖空白区平移；Delete 删除选中节点。

    缩放区间 [ZOOM_MIN, ZOOM_MAX]；展开节点时由 scene 调 ``snap_zoom_to_one``
    吸附 1.0，避免 proxy 非整数缩放导致文字发虚。
    """

    zoomChanged = Signal(float)
    deleteRequested = Signal()

    ZOOM_MIN, ZOOM_MAX = 0.25, 4.0

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

    # ---- 相机 -----------------------------------------------------------

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float, *, emit: bool = True) -> None:
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, float(zoom)))
        if abs(zoom - self._zoom) < 1e-9:
            return
        factor = zoom / self._zoom
        self.scale(factor, factor)
        self._zoom = zoom
        if emit:
            self.zoomChanged.emit(zoom)

    def snap_zoom_to_one(self) -> None:
        """展开 proxy 面板时吸附整数缩放，保证嵌入 widget 文字清晰。"""
        self.set_zoom(1.0)

    def focus_node(self, node, *, expand: bool = False) -> None:
        if node is None:
            return
        if expand and node.is_collapsed():
            node.expand()
        target = node.pos() + QPointF(node._w / 2.0, node.height / 2.0)
        self.centerOn(target)

    def fit_all(self, rect: QRectF | None = None) -> None:
        bounds = rect if rect is not None else self.scene().itemsBoundingRect()
        if bounds.isEmpty():
            return
        bounds = bounds.adjusted(-48.0, -48.0, 48.0, 48.0)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        transform = self.transform()
        zoom = math.sqrt(abs(transform.determinant()))
        self._zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        # fitInView 会把缩放改掉，重置为计算出的 zoom 并发射信号
        self.zoomChanged.emit(self._zoom)

    def reset_camera(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self.zoomChanged.emit(1.0)

    # ---- 交互 -----------------------------------------------------------

    def wheelEvent(self, event) -> None:
        # 滚轮上推（angleDelta 正）→ 放大，与 Office/WPS/Zemax 习惯一致
        factor = math.exp(event.angleDelta().y() * 0.0016)
        self.set_zoom(self._zoom * factor)
        event.accept()

    def mousePressEvent(self, event) -> None:
        # 空白处按下 → 临时切手型拖拽平移
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.deleteRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.fit_all()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---- 背景：点阵网格（世界坐标，随缩放自然稀疏） --------------------------

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(C["canvas_bg"]))
        pen = QPen(QColor(C["grid_dot"]))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        step = 32.0
        x = math.floor(rect.left() / step) * step
        while x <= rect.right():
            y = math.floor(rect.top() / step) * step
            while y <= rect.bottom():
                painter.drawPoint(QPointF(x, y))
                y += step
            x += step


__all__ = ["CanvasView"]
