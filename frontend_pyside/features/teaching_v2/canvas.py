"""Canvas-first teaching viewport with lightweight 3D bench projection."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
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
        self.setToolTip(f"{component.label}\n点击右侧“属性”按钮编辑参数，或拖到台面位置")
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
        from shared_presentation.teaching_canvas import component_primitives
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for primitive in component_primitives(self.kind, self.label, self._length, self._aperture, self.scale, self.isSelected(), self._hovered):
            if primitive['shape'] == 'text':
                painter.setPen(QColor(*primitive['fill']))
                painter.setFont(QFont('Microsoft YaHei UI', primitive['font_size']))
                painter.drawText(QRectF(*primitive['bounds']), Qt.AlignmentFlag.AlignCenter, primitive['text'])
                continue
            stroke = primitive['stroke']
            painter.setPen(QPen(QColor(*stroke), primitive['width']) if stroke else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*primitive['fill']))
            rect = QRectF(*primitive['bounds'])
            if primitive['shape'] == 'ellipse': painter.drawEllipse(rect)
            elif primitive['radius']: painter.drawRoundedRect(rect, primitive['radius'], primitive['radius'])
            else: painter.drawRect(rect)

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

    # 缩放上下限：按 8 px/mm 的场景比例，0.02 能看整张台面，16 能看清单片透镜。
    MIN_SCALE = 0.02
    MAX_SCALE = 16.0
    ZOOM_STEP = 1.15

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
        self._fitted_viewport = QSize()
        self._user_scaled = False

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
        self._fitted_viewport = self.viewport().size()
        self._user_scaled = False
        # 滚动条要等下一次布局才出现/消失并改变视口尺寸，所以排一次复查，
        # 让"适配画面"落在最终视口上，而不是留一条滚动条。
        QTimer.singleShot(0, self._refit_after_layout)
        self.fitRequested.emit()

    def _refit_after_layout(self) -> None:
        if self._user_scaled or not self.isVisible():
            return
        if self._fitted_viewport != self.viewport().size():
            self.fit_scene()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 二维视图在堆栈里被隐藏时，视口只有最小尺寸，那时算出的"适配画面"
        # 比例没有意义；重新显示时按真实尺寸补一次。用户自己缩放过就不动他。
        if not self._user_scaled and self._fitted_viewport != self.viewport().size():
            QTimer.singleShot(0, self.fit_scene)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        current = max(float(self.transform().m11()), 1.0e-6)
        factor = self.ZOOM_STEP if delta > 0 else 1.0 / self.ZOOM_STEP
        # 先把目标比例夹到合法范围再比较：适配比例本来就可能落在范围之外
        # （例如在隐藏状态下拟合过），旧写法会把两个方向一起挡掉，表现为
        # "怎么滚都不动"。
        target = min(self.MAX_SCALE, max(self.MIN_SCALE, current * factor))
        if abs(target - current) > 1.0e-9:
            self.scale(target / current, target / current)
            self._user_scaled = True
        event.accept()


__all__ = ["BenchScene", "BenchView", "ComponentItem"]
