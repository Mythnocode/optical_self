"""画布节点基类：双态（折叠小卡片 / 展开全尺寸）+ 「!」脏徽标 + 拖拽调大小。

- 折叠态纯自绘（不经过 widget 层，缩放流畅）；
- 展开态由子类决定内容：面板节点经 NodeHost(proxy) 嵌入 QWidget；图表节点自绘；
- 万物可拖拽；展开态右下角 grip 拖拽调大小。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from frontend_pyside.features.canvas.theme import C


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def find_view(node) -> QGraphicsView | None:
    scene: QGraphicsScene | None = node.scene()
    return scene.views()[0] if scene is not None and scene.views() else None


class CanvasNode(QGraphicsObject):
    """所有画布节点的公共骨架。子类实现 _paint_content / summary_text / _on_resize。

    头部右侧统一 chrome（Office/WPS 式）：设置 · 运行 · ✓ 确认 · ⛶ 全屏 · × 关闭。
    参数设置和运行由具体节点声明；数据源节点没有 ×（依赖图根不可删）。
    """

    moved = Signal()
    staleChanged = Signal()
    refreshRequested = Signal(str)  # node_id（请求引擎刷新）
    expandChanged = Signal(bool)  # 展开/折叠
    confirmRequested = Signal()  # ✓：确认参数设置（节点保持打开）
    settingsRequested = Signal()  # ⚙：展开/收起节点附属参数胶囊
    runRequested = Signal()  # ▶：启动节点任务
    closeRequested = Signal()  # ×：关闭（移除）节点
    fullscreenRequested = Signal()  # ⛶：进入全屏（仅声明 fullscreen 的节点）

    HEADER_H = 30.0
    COLLAPSED_W = 176.0
    COLLAPSED_H = 54.0
    MIN_W, MIN_H = 190.0, 130.0
    CHROME_SIZE = 18.0
    CHROME_GAP = 4.0
    CHROME_MARGIN = 6.0

    def __init__(self, node_id: str, spec, parent=None):
        super().__init__(parent)
        self.node_id = str(node_id)
        self.spec = spec
        self.title = spec.title
        self.node_kind = spec.node_kind
        self.is_source = spec.node_kind == "source"
        self._full_w = float(spec.default_w)
        self._full_h = self.HEADER_H + float(spec.default_h)
        self._collapsed = True  # 默认折叠：不占画布
        self._resizing = None  # (start_pos, (start_w, start_h))
        self._stale = False
        self._ignored = False
        self._refreshing = False
        self._flash_until_ms = 0
        self._realtime = False
        # chrome 配置：× 默认给非 source 节点；其他按钮由子类声明
        self._chrome_close = not self.is_source
        self._chrome_settings = False
        self._chrome_run = False
        self._chrome_confirm = False
        self._chrome_fullscreen = False
        self._confirm_flash_until_ms = 0
        self._hover_chrome = ""  # settings / run / confirm / fullscreen / close

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        # 视口裁剪 + 设备级缓存：性能红线 §2.1
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    # ---- 几何 -----------------------------------------------------------

    @property
    def _w(self) -> float:
        return self.COLLAPSED_W if self._collapsed else self._full_w

    @property
    def height(self) -> float:
        return self.COLLAPSED_H if self._collapsed else self._full_h

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self._w, self.height)

    def _body_path(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self.boundingRect(), 10.0, 10.0)
        return path

    def _badge_rect(self) -> QRectF:
        # 徽标排在 chrome 按钮左侧，避免与 ✓/⛶/× 重叠
        return QRectF(self._chrome_left_x() - 28.0, 4.0, 22.0, 22.0)

    def _grip_rect(self) -> QRectF:
        return QRectF(self._w - 18.0, self.height - 18.0, 14.0, 14.0)

    # ---- chrome（✓ / ⛶ / ×）------------------------------------------------

    def _chrome_buttons(self) -> list[str]:
        """从左到右的 chrome 按钮序列；设置和运行在折叠态也保留。"""
        buttons: list[str] = []
        if self._chrome_settings:
            buttons.append("settings")
        if self._chrome_run:
            buttons.append("run")
        if not self._collapsed:
            if self._chrome_confirm:
                buttons.append("confirm")
            if self._chrome_fullscreen:
                buttons.append("fullscreen")
        if self._chrome_close:
            buttons.append("close")
        return buttons

    def _chrome_left_x(self) -> float:
        count = len(self._chrome_buttons())
        if count == 0:
            return self._w - 6.0
        total = count * self.CHROME_SIZE + (count - 1) * self.CHROME_GAP
        return self._w - self.CHROME_MARGIN - total

    def _chrome_rect(self, kind: str) -> QRectF:
        x = self._chrome_left_x()
        for button in self._chrome_buttons():
            rect = QRectF(x, (self.HEADER_H - self.CHROME_SIZE) / 2.0, self.CHROME_SIZE, self.CHROME_SIZE)
            if button == kind:
                return rect
            x += self.CHROME_SIZE + self.CHROME_GAP
        return QRectF()

    def _chrome_rect_at_pos(self, pos) -> str:
        for button in self._chrome_buttons():
            if self._chrome_rect(button).contains(pos):
                return button
        return ""

    def _paint_chrome(self, painter: QPainter) -> None:
        """头部右侧统一按钮：设置 / 运行 / 确认 / 全屏 / 关闭。"""
        confirmed = self._confirm_flash_until_ms > 0
        for kind in self._chrome_buttons():
            rect = self._chrome_rect(kind)
            hovered = self._hover_chrome == kind
            painter.setPen(Qt.PenStyle.NoPen)
            if kind == "close":
                fill = QColor("#C5221F") if hovered else QColor(C["badge_dim"])
                painter.setBrush(fill)
            else:
                fill = QColor(C["badge"]) if (hovered or (kind == "confirm" and confirmed)) else QColor(C["badge_dim"])
                painter.setBrush(fill)
            painter.drawEllipse(rect)
            # 字形
            glyph = QColor(C["text_inverse"])
            cx, cy = rect.center().x(), rect.center().y()
            pen = QPen(glyph, 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = rect.width() / 2.0
            if kind == "close":
                painter.drawLine(QPointF(cx - r * 0.42, cy - r * 0.42), QPointF(cx + r * 0.42, cy + r * 0.42))
                painter.drawLine(QPointF(cx - r * 0.42, cy + r * 0.42), QPointF(cx + r * 0.42, cy - r * 0.42))
            elif kind == "settings":
                # 齿轮以文本字形绘制，颜色必须走画笔（pen），不能用 NoPen，
                # 否则 drawText 画出来是空的 → 图标不可见。
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "⚙")
            elif kind == "run":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glyph)
                painter.drawPolygon(QPolygonF([
                    QPointF(cx - r * 0.25, cy - r * 0.48),
                    QPointF(cx + r * 0.46, cy),
                    QPointF(cx - r * 0.25, cy + r * 0.48),
                ]))
            elif kind == "confirm":
                painter.drawPolyline([
                    QPointF(cx - r * 0.45, cy + r * 0.02),
                    QPointF(cx - r * 0.1, cy + r * 0.38),
                    QPointF(cx + r * 0.48, cy - r * 0.34),
                ])
            else:  # fullscreen：四角括号
                inset = r * 0.34
                arm = r * 0.3
                for sx, sy in ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0)):
                    corner_x = cx + sx * (r - inset)
                    corner_y = cy + sy * (r - inset)
                    painter.drawLine(QPointF(corner_x, corner_y), QPointF(corner_x - sx * arm, corner_y))
                    painter.drawLine(QPointF(corner_x, corner_y), QPointF(corner_x, corner_y - sy * arm))

    def expanded_size(self) -> tuple[float, float]:
        return (self._full_w, self._full_h)

    # ---- 交互 -----------------------------------------------------------

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.moved.emit()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        # chrome 按钮（✓/⛶/×）优先于移动
        if event.button() == Qt.MouseButton.LeftButton:
            kind = self._chrome_rect_at_pos(event.pos())
            if kind:
                self._activate_chrome(kind)
                event.accept()
                return
        # 展开态右下角 grip → 进入拖拽调大小，不进入移动
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._collapsed
            and self._grip_rect().contains(event.pos())
        ):
            self._resizing = (event.pos(), (self._full_w, self._full_h))
            event.accept()
            return
        # 徽标区域点击 → 打开菜单
        if event.button() == Qt.MouseButton.LeftButton and self._badge_rect().contains(event.pos()):
            if self._open_badge_menu(event.pos().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def _activate_chrome(self, kind: str) -> None:
        import time as _time

        from PySide6.QtCore import QTimer

        if kind == "close":
            self.closeRequested.emit()
        elif kind == "settings":
            self.settingsRequested.emit()
        elif kind == "run":
            self.runRequested.emit()
        elif kind == "confirm":
            # ✓ 只确认参数，不关闭节点（打勾后短暂高亮反馈）
            self._confirm_flash_until_ms = int(_time.monotonic() * 1000) + 600
            QTimer.singleShot(620, self.update)
            self.update()
            self.confirmRequested.emit()
        elif kind == "fullscreen":
            self.fullscreenRequested.emit()

    def mouseMoveEvent(self, event):
        if self._resizing is not None:
            start_pos, (start_w, start_h) = self._resizing
            new_w = max(self.MIN_W, start_w + event.pos().x() - start_pos.x())
            new_h = max(self.MIN_H, start_h + event.pos().y() - start_pos.y())
            if new_w != self._full_w or new_h != self._full_h:
                self.resize(new_w, new_h)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing is not None:
            self._resizing = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resize(self, new_w: float, new_h: float) -> None:
        self.prepareGeometryChange()
        self._full_w = float(new_w)
        self._full_h = float(new_h)
        self._on_resize()
        self.moved.emit()
        self.update()

    def _on_resize(self) -> None:
        """子类覆写：嵌入 widget / 内容跟随新尺寸。"""

    def hoverMoveEvent(self, event):
        scene = self.scene()
        setter = getattr(scene, "set_hovered_node", None) if scene is not None else None
        if callable(setter):
            setter(self)
        if not self._collapsed and self._grip_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._chrome_rect_at_pos(event.pos()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            hovered = self._chrome_rect_at_pos(event.pos())
            if hovered != self._hover_chrome:
                self._hover_chrome = hovered
                self.update()
            return
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._hover_chrome:
            self._hover_chrome = ""
            self.update()
        super().hoverMoveEvent(event)

    def hoverEnterEvent(self, event):
        scene = self.scene()
        setter = getattr(scene, "set_hovered_node", None) if scene is not None else None
        if callable(setter):
            setter(self)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._hover_chrome:
            self._hover_chrome = ""
            self.update()
        scene = self.scene()
        setter = getattr(scene, "set_hovered_node", None)
        if callable(setter) and getattr(scene, "_hovered_node", None) is self:
            setter(None)
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.toggle_expand()
        event.accept()

    # ---- 折叠 / 展开 ------------------------------------------------------

    def toggle_expand(self) -> None:
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def expand(self) -> None:
        if not self._collapsed:
            return
        self.prepareGeometryChange()
        self._collapsed = False
        self._on_expand_state()
        self.moved.emit()
        self.update()
        self.expandChanged.emit(True)

    def collapse(self) -> None:
        if self._collapsed:
            return
        self.prepareGeometryChange()
        self._collapsed = True
        self._on_expand_state()
        self.moved.emit()
        self.update()
        self.expandChanged.emit(False)

    def _on_expand_state(self) -> None:
        """子类覆写：展开/折叠时同步嵌入 widget 可见性。"""

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _open_badge_menu(self, pos) -> bool:
        return False

    # ---- 状态 -----------------------------------------------------------

    def set_stale(self, stale: bool, reason: str = ""):
        self._stale = bool(stale)
        if stale:
            self._ignored = False
        if reason:
            self.setToolTip(reason)
        self.update()
        self.staleChanged.emit()

    def set_ignored(self) -> None:
        self._ignored = True
        self.update()
        self.staleChanged.emit()

    def set_refreshing(self, refreshing: bool) -> None:
        if self._refreshing == bool(refreshing):
            return
        self._refreshing = bool(refreshing)
        self.update()

    def do_refresh(self) -> None:
        self.refreshRequested.emit(self.node_id)

    def flash(self) -> None:
        import time as _time

        self._flash_until_ms = int(_time.monotonic() * 1000) + 500
        QTimer.singleShot(520, self.update)

    # ---- 绘制 -----------------------------------------------------------

    def paint(self, painter: QPainter, option, widget=None):
        import time as _time

        now_ms = int(_time.monotonic() * 1000)
        if self._confirm_flash_until_ms and now_ms >= self._confirm_flash_until_ms:
            self._confirm_flash_until_ms = 0
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body = self._body_path()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C["node_fill"]))
        painter.drawPath(body)

        # 标题头（黑 = 数据源 / 灰 = 分析）
        header_color = QColor(C["source_header"] if self.is_source else C["view_header"])
        band = QPainterPath()
        band.addRoundedRect(QRectF(0.0, 0.0, self._w, self.HEADER_H), 10.0, 10.0)
        painter.setBrush(header_color)
        painter.drawPath(band)
        painter.drawRect(QRectF(0.0, self.HEADER_H / 2.0, self._w, self.HEADER_H / 2.0))

        content = QRectF(12.0, self.HEADER_H + 4.0, self._w - 24.0, self.height - self.HEADER_H - 8.0)
        if self._collapsed:
            self._paint_summary(painter, content)
        else:
            self._paint_content(painter, content)

        focused = self.isSelected() or self._flash_until_ms > int(_time.monotonic() * 1000)
        pen = QPen(QColor(C["node_border_focus"] if focused else C["node_border"]))
        pen.setWidthF(2.0 if focused else 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(body)

        painter.setPen(QColor(C["source_header_text"] if self.is_source else C["view_header_text"]))
        painter.setFont(_font(12, True))
        title_width = max(60.0, self._chrome_left_x() - 40.0 if self._chrome_buttons() else self._w - 76.0)
        painter.drawText(QRectF(12.0, 0.0, title_width, self.HEADER_H), Qt.AlignmentFlag.AlignVCenter, self.title)
        self._paint_subtitle(painter)
        self._paint_badge(painter)
        self._paint_chrome(painter)

        if not self._collapsed:
            grip = self._grip_rect()
            pen = QPen(QColor(C["text_muted"]))
            pen.setWidthF(1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for i in (1, 2, 3):
                offset = i * 3.6
                painter.drawLine(
                    QPointF(grip.left() + 1.0, grip.bottom() - offset),
                    QPointF(grip.left() + offset, grip.bottom() - 1.0),
                )

    def _paint_subtitle(self, painter: QPainter) -> None:
        if self._chrome_buttons():
            return  # 有 chrome 的节点：标题右侧是按钮组，不再画「↩ 镜头组」副标题
        text = "数据源" if self.is_source else "↩ 镜头组"
        painter.setPen(QColor(C["text_muted"]))
        painter.setFont(_font(11))
        painter.drawText(
            QRectF(self._w - 96.0, 0.0, 64.0, self.HEADER_H),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            text,
        )

    def _paint_badge(self, painter: QPainter) -> None:
        if not (self._stale or self._ignored or self._refreshing):
            return
        rect = self._badge_rect()
        if self._ignored:
            color = QColor(C["badge_dim"])
        elif self._refreshing:
            color = QColor(C["accent"])
        else:
            color = QColor(C["warn"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(rect)
        painter.setPen(QColor(C["text_inverse"]))
        painter.setFont(_font(12, True))
        mark = "…" if self._refreshing else "!"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, mark)

    def _paint_summary(self, painter: QPainter, rect: QRectF) -> None:
        state = ""
        if self._refreshing:
            state = "计算中…"
        elif self._stale:
            state = "待更新"
        elif self._ignored:
            state = "已忽略"
        painter.setPen(QColor(C["text"]))
        painter.setFont(_font(11))
        text_rect = QRectF(rect.left(), rect.top(), rect.width() - 44.0, rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.summary_text())
        if state:
            painter.setPen(QColor(C["warn"] if self._stale and not self._ignored else C["text_muted"]))
            state_rect = QRectF(rect.right() - 92.0, rect.top(), 60.0, rect.height())
            painter.drawText(state_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, state)

    def _paint_content(self, painter: QPainter, rect: QRectF) -> None:
        pass

    def _paint_refreshing_overlay(self, painter: QPainter, rect: QRectF) -> None:
        overlay = QColor(C["overlay"])
        overlay.setAlpha(C["overlay_alpha"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(overlay)
        painter.drawRect(rect)
        painter.setPen(QColor(C["text_muted"]))
        painter.setFont(_font(12))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "重新计算中…")

    def summary_text(self) -> str:
        return self.title


__all__ = ["CanvasNode", "find_view"]
