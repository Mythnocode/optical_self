"""Canvas-first teaching viewport with lightweight 3D bench projection."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from .model import MIRROR_RUNTIME_FOLD_DEG, OpticalComponent, Pose, SceneSnapshot, SceneStore, TEACHING_KIND_MIME
from .assets import BREADBOARD_HOLE_PITCH_MM, BREADBOARD_LENGTH_MM, BREADBOARD_WIDTH_MM, visual_housing
from .coordinates import AXIS_HEIGHT_MM


KIND_COLORS = {
    "laser": QColor("#dc2626"),
    "isolator": QColor("#4b5563"),
    "waveplate": QColor("#7c3aed"),
    "lens": QColor("#2563eb"),
    "cylindrical_lens": QColor("#1d4ed8"),
    "beam_expander": QColor("#0284c7"),
    "aperture": QColor("#334155"),
    "pbs": QColor("#0f766e"),
    "splitter": QColor("#0891b2"),
    "beam_sampler": QColor("#64748b"),
    "grating": QColor("#ca8a04"),
    "mirror": QColor("#d97706"),
    "fiber": QColor("#0f766e"),
    "ccd": QColor("#7c3aed"),
    "power_meter": QColor("#475569"),
    "wavefront_sensor": QColor("#6366f1"),
    "oscilloscope": QColor("#1e293b"),
}

MAX_DRAW_RAYS = 80


class ComponentItem(QGraphicsObject):
    selected = Signal(str)
    moved = Signal(str, float, float)
    activated = Signal(str)

    def __init__(self, component: OpticalComponent, scale: float, parent=None) -> None:
        super().__init__(parent)
        self.component_id = component.component_id
        self.kind = component.kind
        self.label = component.label
        self.scale = float(scale)
        self._aperture = 12.7
        self._length = 8.0
        self._dragging = False
        self._hovered = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{component.label}\n在右侧面板编辑参数，或拖到台面位置")
        self.update_component(component)

    def _to_point(self, pose: Pose) -> QPointF:
        return QPointF(float(pose.x_mm) * self.scale, -float(pose.y_mm) * self.scale)

    def update_component(self, component: OpticalComponent) -> None:
        self.label = component.label
        self.kind = component.kind
        housing = visual_housing(component.kind, component.params)
        self._aperture = max(float(housing.aperture_mm), 6.0)
        self._length = max(float(housing.length_mm), 4.0)
        yaw = float(component.pose.yaw_deg)
        if component.kind == "mirror":
            yaw += MIRROR_RUNTIME_FOLD_DEG
        self.setRotation(-yaw)
        if not self._dragging:
            self.setPos(self._to_point(component.pose))
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QRectF:
        half = max(self._aperture, self._length) * self.scale * 0.8 + 22.0
        return QRectF(-half, -half, half * 2.0, half * 2.0)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        selected = self.isSelected()
        color = QColor(KIND_COLORS.get(self.kind, "#64748b"))
        px_len = max(self._length * self.scale * 0.5, 11.0)
        px_ap = max(self._aperture * self.scale * 0.42, 10.0)
        mount = QColor("#2A3038")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if selected or self._hovered:
            accent = QColor("#d97706") if selected else QColor("#2563eb")
            painter.setPen(QPen(accent, 1.8))
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 28))
            painter.drawEllipse(QRectF(-px_ap - 7, -px_ap - 7, (px_ap + 7) * 2, (px_ap + 7) * 2))
        if self.kind != "oscilloscope":
            painter.setPen(QPen(QColor("#64748b"), 0.8))
            painter.setBrush(QColor("#8B95A0"))
            painter.drawEllipse(QRectF(-4.2, -4.2, 8.4, 8.4))
        painter.setPen(QPen(QColor("#111827"), 0.9))
        painter.setBrush(mount)
        if self.kind in {"lens", "cylindrical_lens", "aperture", "waveplate", "isolator", "beam_expander"}:
            painter.drawEllipse(QRectF(-px_ap - 3.2, -px_ap - 3.2, (px_ap + 3.2) * 2, (px_ap + 3.2) * 2))
            painter.setPen(QPen(color.darker(150), 1.2))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 220))
            painter.drawEllipse(QRectF(-px_ap, -px_ap, px_ap * 2, px_ap * 2))
            painter.setPen(Qt.PenStyle.NoPen)
            if self.kind == "aperture":
                painter.setBrush(QColor("#e8edf2"))
                painter.drawEllipse(QRectF(-px_ap * 0.34, -px_ap * 0.34, px_ap * 0.68, px_ap * 0.68))
            else:
                painter.setBrush(QColor(255, 255, 255, 45))
                painter.drawEllipse(QRectF(-px_ap * 0.45, -px_ap * 0.55, px_ap * 0.7, px_ap * 0.5))
        elif self.kind in {"mirror", "splitter", "beam_sampler", "grating", "pbs"}:
            painter.drawRoundedRect(QRectF(-px_len * 0.22, -px_ap - 3, px_len * 0.95, (px_ap + 3) * 2), 2.0, 2.0)
            painter.setPen(QPen(color.darker(140), 1.1))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 230))
            painter.drawRoundedRect(QRectF(-px_len * 0.18, -px_ap, px_len * 0.48, px_ap * 2), 1.5, 1.5)
        elif self.kind == "laser":
            painter.drawRoundedRect(QRectF(-px_len * 0.12, -px_ap * 0.85, px_len * 0.95, px_ap * 1.7), 2.0, 2.0)
            painter.setPen(QPen(color.darker(140), 1.0))
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(-px_len, -px_ap * 0.5, px_len * 1.55, px_ap), 3.0, 3.0)
        elif self.kind == "fiber":
            painter.drawRoundedRect(QRectF(-px_ap - 2, -px_ap - 2, (px_ap + 2) * 2, (px_ap + 2) * 2), 3.0, 3.0)
            painter.setPen(QPen(color.darker(140), 1.0))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 220))
            painter.drawRoundedRect(QRectF(-px_ap, -px_ap * 0.7, px_ap * 2, px_ap * 1.4), 3.0, 3.0)
        elif self.kind == "ccd":
            painter.drawRoundedRect(QRectF(-px_ap - 2, -px_ap * 0.85, px_ap * 2 + 4, px_ap * 1.7), 2.0, 2.0)
            painter.setPen(QPen(color.darker(140), 1.0))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 220))
            painter.drawRect(QRectF(-px_ap, -px_ap * 0.7, px_ap * 2, px_ap * 1.4))
        else:
            painter.drawRoundedRect(QRectF(-px_len - 2, -px_ap * 0.85, px_len * 2 + 4, px_ap * 1.7), 2.0, 2.0)
            painter.setPen(QPen(color.darker(140), 1.0))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 210))
            painter.drawRoundedRect(QRectF(-px_len, -px_ap * 0.7, px_len * 2, px_ap * 1.4), 3.0, 3.0)
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.drawText(QRectF(-48, px_ap + 4, 96, 14), Qt.AlignmentFlag.AlignCenter, self.label)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.component_id)
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._dragging:
            self._dragging = False
            x_mm, y_mm = self.pos().x() / self.scale, -self.pos().y() / self.scale
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                x_mm, y_mm = round(x_mm / 2.5) * 2.5, round(y_mm / 2.5) * 2.5
                self.setPos(x_mm * self.scale, -y_mm * self.scale)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.moved.emit(self.component_id, x_mm, y_mm)

    def mouseDoubleClickEvent(self, event) -> None:
        self.selected.emit(self.component_id)
        self.activated.emit(self.component_id)
        event.accept()

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.unsetCursor()
        self.update()
        super().hoverLeaveEvent(event)


class BenchScene(QGraphicsScene):
    selected = Signal(str)
    moved = Signal(str, float, float)
    activated = Signal(str)

    def __init__(self, store: SceneStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.scale = 8.0
        self.setSceneRect(-40.0, -BREADBOARD_WIDTH_MM * 8.0 * 0.55, BREADBOARD_LENGTH_MM * 8.0 + 80.0, BREADBOARD_WIDTH_MM * 8.0 * 1.1)
        self._items: dict[str, ComponentItem] = {}
        self._snapshot: SceneSnapshot | None = None
        self._rays: list[dict[str, Any]] = []
        self.store.sceneChanged.connect(self.set_snapshot)
        self.store.selectionChanged.connect(self._select_from_store)
        self.set_snapshot(store.snapshot(), "initial")

    def set_snapshot(self, snapshot: SceneSnapshot, _reason: str = "") -> None:
        self._snapshot = snapshot
        self._rebuild_items(snapshot)
        self.update()

    def set_rays(self, rays: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
        self._rays = list(rays or [])[:MAX_DRAW_RAYS]
        self.update()

    def _rebuild_items(self, snapshot: SceneSnapshot) -> None:
        present = {item.component_id for item in snapshot.components}
        for cid in list(self._items):
            if cid not in present:
                self.removeItem(self._items.pop(cid))
        for component in snapshot.components:
            item = self._items.get(component.component_id)
            if item is None:
                item = ComponentItem(component, self.scale)
                item.selected.connect(self._on_item_selected)
                item.moved.connect(self._on_item_moved)
                item.activated.connect(self.activated)
                self._items[component.component_id] = item
                self.addItem(item)
            else:
                item.update_component(component)
        self._select_from_store(snapshot.selected_component_id)

    def _on_item_selected(self, component_id: str) -> None:
        self.store.select(component_id)
        self.selected.emit(component_id)

    def _on_item_moved(self, component_id: str, x_mm: float, y_mm: float) -> None:
        snapshot = self.store.snapshot()
        component = next((item for item in snapshot.components if item.component_id == component_id), None)
        if component is None:
            return
        self.store.update_pose(
            component_id,
            Pose.from_degrees(
                x_mm,
                y_mm,
                component.pose.z_mm,
                component.pose.yaw_deg,
                component.pose.pitch_deg,
                component.pose.roll_deg,
            ),
            reason=f"拖动{component.label}",
        )
        self.moved.emit(component_id, x_mm, y_mm)

    def _select_from_store(self, component_id: str | None) -> None:
        for cid, item in self._items.items():
            item.setSelected(cid == component_id)
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#e8edf2"))
        s = self.scale
        board = QRectF(0.0, -0.5 * BREADBOARD_WIDTH_MM * s, BREADBOARD_LENGTH_MM * s, BREADBOARD_WIDTH_MM * s)
        painter.setPen(QPen(QColor("#98A2B3"), 1.2))
        painter.setBrush(QColor("#D7DCE2"))
        painter.drawRect(board)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#7B8794"))
        pitch = BREADBOARD_HOLE_PITCH_MM * s
        r = 2.2
        x0 = 12.5 * s
        y0 = -0.5 * BREADBOARD_WIDTH_MM * s + 12.5 * s
        nx = int(BREADBOARD_LENGTH_MM / BREADBOARD_HOLE_PITCH_MM)
        ny = int(BREADBOARD_WIDTH_MM / BREADBOARD_HOLE_PITCH_MM)
        for ix in range(nx):
            for iy in range(ny):
                cx = x0 + ix * pitch
                cy = y0 + iy * pitch
                if rect.intersects(QRectF(cx - r, cy - r, r * 2, r * 2)):
                    painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(QPen(QColor("#64748b"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(0, 0), QPointF(BREADBOARD_LENGTH_MM * s, 0))
        if self._snapshot and self._snapshot.baseline_enabled:
            bx = self._snapshot.baseline_x_mm * s
            painter.setPen(QPen(QColor("#2563eb"), 1.4, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(bx, board.top()), QPointF(bx, board.bottom()))
        painter.setPen(QColor("#475569"))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.drawText(QPointF(8, board.bottom() + 16), "俯视 · 沿导轨（mm）  台面 450 × 300")
        self._draw_rays(painter)

    def _draw_rays(self, painter: QPainter) -> None:
        for ray in self._rays:
            start = ray.get("start") or ()
            end = ray.get("end") or ()
            if len(start) < 2 or len(end) < 2:
                continue
            a = QPointF(float(start[0]) * self.scale, -float(start[1]) * self.scale)
            b = QPointF(float(end[0]) * self.scale, -float(end[1]) * self.scale)
            power = float(ray.get("power_fraction", 1.0))
            alpha = max(50, min(230, int(70 + 150 * power)))
            width = 4.2 if power > 0.9 else 2.6
            painter.setPen(QPen(QColor(239, 68, 68, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(a, b)


class BenchView(QGraphicsView):
    fitRequested = Signal()

    def __init__(self, scene: BenchScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setObjectName("teachingV2BenchView")
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(280, 120)
        self.setStyleSheet("QGraphicsView { border: 1px solid #d8e1eb; border-radius: 8px; background: #f8fafc; }")
        self.setAcceptDrops(True)

    def _drop_kind(self, event) -> str:
        mime = event.mimeData()
        if mime.hasFormat(TEACHING_KIND_MIME):
            return bytes(mime.data(TEACHING_KIND_MIME)).decode("utf-8")
        return str(mime.text() or "")

    def dragEnterEvent(self, event) -> None:
        if self._drop_kind(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        kind = self._drop_kind(event)
        if not kind:
            event.ignore()
            return
        scene_pos = self.mapToScene(event.position().toPoint() if hasattr(event, "position") else event.pos())
        scene = self.scene()
        store = getattr(scene, "store", None)
        if store is None:
            event.ignore()
            return
        scale = max(float(getattr(scene, "scale", 8.0)), 0.01)
        store.add_component(kind, pose=Pose(scene_pos.x() / scale, -scene_pos.y() / scale, AXIS_HEIGHT_MM))
        event.acceptProposedAction()

    def fit_scene(self) -> None:
        items = [item for item in self.scene().items() if item.isVisible()]
        if items:
            rect = self.scene().itemsBoundingRect().adjusted(-48, -36, 48, 36)
        else:
            rect = self.scene().sceneRect().adjusted(20, 20, -20, -20)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.fitRequested.emit()

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current = float(self.transform().m11())
        proposed = current * factor
        if 0.22 <= proposed <= 6.0:
            self.scale(factor, factor)


__all__ = ["BenchScene", "BenchView", "ComponentItem"]
