"""数据流连线：按目标上下顺序摊开端口，避免全部挤在节点中点交叉。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from frontend_pyside.features.canvas.theme import C

_PORT_INSET = 12.0
_PORT_RADIUS = 3.2


def _mid_y(node) -> float:
    return float(node.pos().y()) + float(node.height) * 0.5


def _port_point(node, side: str, index: int, count: int) -> QPointF:
    """沿节点竖边按序摊开端口；只有一条线时仍走中点。"""
    height = max(float(node.height), 1.0)
    inset = min(_PORT_INSET, height * 0.28)
    if count <= 1:
        y = _mid_y(node)
    else:
        usable = max(height - 2.0 * inset, 1.0)
        y = float(node.pos().y()) + inset + usable * (index / (count - 1))
    x = float(node.pos().x()) + float(node._w) if side == "out" else float(node.pos().x())
    return QPointF(x, y)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, source, target, edge_kind: str = "data", parent=None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self.edge_kind = str(edge_kind)
        self._src = QPointF()
        self._dst = QPointF()
        self.setZValue(-1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, False)
        for node in (source, target):
            node.moved.connect(self._on_endpoint_changed)
            node.staleChanged.connect(self.refresh)
        self.refresh()

    def _on_endpoint_changed(self) -> None:
        scene = self.scene()
        refresh_all = getattr(scene, "refresh_attached_edges", None)
        if callable(refresh_all):
            refresh_all(self.source, self.target)
            return
        self.refresh()

    def _peer_edges(self, role: str) -> list[EdgeItem]:
        scene = self.scene()
        items = getattr(scene, "_edges", None)
        pool = list(items) if items is not None else [self]
        if role == "out":
            peers = [edge for edge in pool if edge.source is self.source]
            peers.sort(key=lambda edge: (_mid_y(edge.target), edge.target.node_id))
        else:
            peers = [edge for edge in pool if edge.target is self.target]
            peers.sort(key=lambda edge: (_mid_y(edge.source), edge.source.node_id))
        return peers or [self]

    def refresh(self) -> None:
        outgoing = self._peer_edges("out")
        incoming = self._peer_edges("in")
        src_index = outgoing.index(self) if self in outgoing else 0
        dst_index = incoming.index(self) if self in incoming else 0
        src = _port_point(self.source, "out", src_index, len(outgoing))
        dst = _port_point(self.target, "in", dst_index, len(incoming))
        self._src, self._dst = src, dst
        dx = max(48.0, min(140.0, abs(dst.x() - src.x()) * 0.38))
        path = QPainterPath(src)
        path.cubicTo(QPointF(src.x() + dx, src.y()), QPointF(dst.x() - dx, dst.y()), dst)
        self.setPath(path)
        stale = bool(getattr(self.target, "_stale", False)) or bool(
            getattr(self.target, "_refreshing", False)
        )
        highlight = ""
        scene = self.scene()
        lookup = getattr(scene, "edge_highlight_for", None)
        if callable(lookup):
            highlight = str(lookup(self) or "")
        if highlight == "selected":
            color = C["node_border_focus"]
            width = 3.0
        elif highlight == "hover":
            color = C["edge_hover"]
            width = 2.2
        elif stale:
            color = C["edge_stale"]
            width = 1.6
        elif self.edge_kind == "workflow":
            # 正式流程线用石板灰实线，和参数胶囊的深色虚线分开，避免演示时看起来像纯黑线。
            color = C["text_muted"]
            width = 1.8
        else:
            color = C["edge"]
            width = 1.4
        pen = QPen(QColor(color))
        pen.setWidthF(width)
        if stale and highlight != "selected":
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([5, 4])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.pen().color())
        painter.drawEllipse(self._src, _PORT_RADIUS, _PORT_RADIUS)
        painter.drawEllipse(self._dst, _PORT_RADIUS, _PORT_RADIUS)

    def dispose(self) -> None:
        for node in (self.source, self.target):
            for signal in (node.moved, node.staleChanged):
                try:
                    signal.disconnect(self._on_endpoint_changed)
                except (RuntimeError, TypeError):
                    pass
                try:
                    signal.disconnect(self.refresh)
                except (RuntimeError, TypeError):
                    pass


__all__ = ["EdgeItem"]
