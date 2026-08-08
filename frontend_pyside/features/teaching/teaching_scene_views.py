
from __future__ import annotations

from dataclasses import dataclass
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .teaching_scene_model import TeachingOpticalMetrics, TeachingOpticalState


from frontend_pyside.resources import theme_tokens as theme

@dataclass(frozen=True, slots=True)
class SceneInstrument:
    key: str
    short_name: str


ELEMENT_LABELS = {
    "laser": "激光器",
    "isolator": "光隔离器",
    "splitter": "分束镜",
    "lens": "聚焦镜组",
    "fiber": "五轴光纤架 + 光纤",
    "output": "输出端",
}


class TeachingOverview2D(QWidget):


    objectActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._state = TeachingOpticalState()
        self._metrics: TeachingOpticalMetrics | None = None
        self._instruments: list[SceneInstrument] = []
        self._focus = "fiber"
        self._hit_boxes: dict[str, QRectF] = {}
        self._show_labels = True
        self._show_envelope = True

    def set_state(self, state: TeachingOpticalState, metrics: TeachingOpticalMetrics) -> None:
        self._state = state
        self._metrics = metrics
        self.update()

    def set_instruments(self, instruments: list[SceneInstrument]) -> None:
        self._instruments = list(instruments)
        self.update()

    def set_focus(self, key: str) -> None:
        self._focus = str(key)
        self.update()

    def set_layers(self, *, labels: bool | None = None, envelope: bool | None = None) -> None:
        if labels is not None:
            self._show_labels = bool(labels)
        if envelope is not None:
            self._show_envelope = bool(envelope)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        position = event.position()
        for key, box in self._hit_boxes.items():
            if box.contains(position):
                self.objectActivated.emit(key)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f6f9fc"))

        width = max(520.0, float(self.width()))
        height = max(330.0, float(self.height()))
        self._draw_grid(painter, width, height)

        left = 68.0
        right = width - 62.0
        axis_y = height * 0.50
        xs = {
            "laser": left,
            "isolator": left + (right - left) * 0.17,
            "splitter": left + (right - left) * 0.34,
            "lens": left + (right - left) * 0.55,
            "fiber": left + (right - left) * 0.78,
            "output": right,
        }

        if self._show_envelope:
            self._draw_beam_envelope(painter, xs, axis_y)
        painter.setPen(QPen(QColor("#e53935"), 2.7))
        painter.drawLine(QPointF(xs["laser"] + 24, axis_y), QPointF(xs["output"] - 20, axis_y))

        self._hit_boxes = {}
        self._draw_laser(painter, QPointF(xs["laser"], axis_y), self._focus == "laser")
        self._draw_isolator(painter, QPointF(xs["isolator"], axis_y), self._focus == "isolator")
        self._draw_splitter(painter, QPointF(xs["splitter"], axis_y), self._focus == "splitter")
        self._draw_lens(painter, QPointF(xs["lens"], axis_y), self._focus == "lens")
        self._draw_fiber(painter, QPointF(xs["fiber"], axis_y), self._focus == "fiber")
        self._draw_output(painter, QPointF(xs["output"], axis_y), self._focus == "output")

        node_boxes = {
            "laser": QRectF(xs["laser"] - 34, axis_y - 34, 68, 68),
            "isolator": QRectF(xs["isolator"] - 42, axis_y - 32, 84, 64),
            "splitter": QRectF(xs["splitter"] - 36, axis_y - 36, 72, 72),
            "lens": QRectF(xs["lens"] - 36, axis_y - 48, 72, 96),
            "fiber": QRectF(xs["fiber"] - 52, axis_y - 44, 104, 88),
            "output": QRectF(xs["output"] - 38, axis_y - 36, 76, 72),
        }
        self._hit_boxes.update(node_boxes)

        placements = {
            "input_power": (xs["splitter"] + 18, axis_y + 108, xs["splitter"]),
            "output_power": (xs["output"] - 16, axis_y + 106, xs["fiber"] + 22),
            "beam_analyzer": (xs["lens"] + 5, axis_y + 108, xs["lens"]),
            "mach_zehnder": (xs["splitter"] + 68, axis_y - 112, xs["splitter"]),
            "shack_hartmann": (xs["lens"] + 72, axis_y - 112, xs["lens"]),
            "polarimeter": (xs["fiber"] + 20, axis_y + 108, xs["fiber"]),
        }
        for instrument in self._instruments:
            placement = placements.get(instrument.key)
            if placement is None:
                continue
            x, y, origin_x = placement
            painter.setPen(QPen(QColor("#f59e0b"), 1.8, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(origin_x, axis_y), QPointF(x, y))
            rect = QRectF(x - 62, y - 25, 124, 50)
            focused = self._focus == instrument.key
            painter.setPen(QPen(QColor(theme.PRIMARY) if focused else QColor(theme.BORDER), 2.2 if focused else 1.2))
            painter.setBrush(QColor("#dff2ff") if focused else QColor(theme.SURFACE))
            painter.drawRoundedRect(rect, 7, 7)
            painter.setPen(QColor("#16364e"))
            font = QFont(painter.font())
            font.setBold(focused)
            painter.setFont(font)
            painter.drawText(rect.adjusted(6, 3, -6, -3), Qt.AlignmentFlag.AlignCenter, instrument.short_name)
            self._hit_boxes[instrument.key] = rect

        if self._show_labels:
            self._draw_labels(painter, xs, axis_y)

        painter.setPen(QColor("#52697c"))
        painter.drawText(
            QRectF(22, height - 30, width - 44, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "红色实线：主光路　橙色虚线：测量支路　半透明区域：高斯光束包络　单击元件查看教学解释",
        )

    @staticmethod
    def _draw_grid(painter: QPainter, width: float, height: float) -> None:
        painter.setPen(QPen(QColor("#e2ebf2"), 1))
        for x in range(24, int(width), 28):
            painter.drawLine(x, 18, x, int(height - 18))
        for y in range(22, int(height), 28):
            painter.drawLine(18, y, int(width - 18), y)

    def _draw_beam_envelope(self, painter: QPainter, xs: dict[str, float], axis_y: float) -> None:
        input_radius = 14.0 + min(18.0, self._state.input_beam_radius_mm * 13.0)
        waist = 3.5
        if self._metrics is not None:
            waist = max(2.5, min(13.0, self._metrics.waist_radius_um * 1.8))
        end_radius = max(waist, min(24.0, (self._metrics.beam_radius_at_fiber_um if self._metrics else 3.0) * 2.0))
        path = QPainterPath(QPointF(xs["laser"] + 22, axis_y - input_radius))
        path.lineTo(QPointF(xs["lens"], axis_y - input_radius))
        path.lineTo(QPointF(xs["fiber"], axis_y - end_radius))
        path.lineTo(QPointF(xs["output"] - 20, axis_y - end_radius * 0.9))
        path.lineTo(QPointF(xs["output"] - 20, axis_y + end_radius * 0.9))
        path.lineTo(QPointF(xs["fiber"], axis_y + end_radius))
        path.lineTo(QPointF(xs["lens"], axis_y + input_radius))
        path.lineTo(QPointF(xs["laser"] + 22, axis_y + input_radius))
        path.closeSubpath()
        gradient = QLinearGradient(QPointF(xs["laser"], axis_y), QPointF(xs["output"], axis_y))
        gradient.setColorAt(0.0, QColor(239, 68, 68, 42))
        gradient.setColorAt(0.62, QColor(239, 68, 68, 75))
        gradient.setColorAt(1.0, QColor(239, 68, 68, 32))
        painter.setPen(QPen(QColor(239, 68, 68, 90), 1.0))
        painter.setBrush(gradient)
        painter.drawPath(path)

    def _draw_laser(self, painter: QPainter, center: QPointF, focused: bool) -> None:
        rect = QRectF(center.x() - 31, center.y() - 22, 52, 44)
        painter.setPen(QPen(self._focus_color(focused), 2.2 if focused else 1.2))
        painter.setBrush(QColor("#d8eefe"))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setBrush(QColor("#ef4444"))
        painter.drawEllipse(QPointF(center.x() + 23, center.y()), 5, 5)

    def _draw_isolator(self, painter: QPainter, center: QPointF, focused: bool) -> None:
        rect = QRectF(center.x() - 35, center.y() - 19, 70, 38)
        painter.setPen(QPen(self._focus_color(focused), 2.2 if focused else 1.2))
        painter.setBrush(QColor(theme.PRIMARY_TINT))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QPen(QColor(theme.PRIMARY), 2))
        painter.drawLine(QPointF(center.x() - 15, center.y()), QPointF(center.x() + 16, center.y()))
        painter.drawLine(QPointF(center.x() + 10, center.y() - 6), QPointF(center.x() + 16, center.y()))
        painter.drawLine(QPointF(center.x() + 10, center.y() + 6), QPointF(center.x() + 16, center.y()))

    def _draw_splitter(self, painter: QPainter, center: QPointF, focused: bool) -> None:
        polygon = QPolygonF([
            QPointF(center.x(), center.y() - 31),
            QPointF(center.x() + 24, center.y()),
            QPointF(center.x(), center.y() + 31),
            QPointF(center.x() - 24, center.y()),
        ])
        painter.setPen(QPen(self._focus_color(focused), 2.2 if focused else 1.2))
        painter.setBrush(QColor(191, 225, 244, 165))
        painter.drawPolygon(polygon)
        painter.setPen(QPen(QColor("#6ba5c6"), 2))
        painter.drawLine(QPointF(center.x() - 16, center.y() + 21), QPointF(center.x() + 16, center.y() - 21))

    def _draw_lens(self, painter: QPainter, center: QPointF, focused: bool) -> None:
        painter.setPen(QPen(self._focus_color(focused), 2.4 if focused else 1.4))
        painter.setBrush(QColor(160, 218, 242, 135))
        painter.drawEllipse(QRectF(center.x() - 11, center.y() - 44, 22, 88))
        painter.setPen(QPen(QColor("#7897aa"), 2))
        painter.drawLine(QPointF(center.x(), center.y() + 45), QPointF(center.x(), center.y() + 58))
        painter.drawLine(QPointF(center.x() - 19, center.y() + 58), QPointF(center.x() + 19, center.y() + 58))

    def _draw_fiber(self, painter: QPainter, center: QPointF, focused: bool) -> None:
        painter.setPen(QPen(self._focus_color(focused), 2.4 if focused else 1.4))
        painter.setBrush(QColor("#e8eef3"))
        painter.drawRoundedRect(QRectF(center.x() - 42, center.y() - 33, 62, 66), 5, 5)
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(center.x() + 20, center.y()), QPointF(center.x() + 50, center.y()))
        painter.setBrush(QColor(80, 170, 225, 80))
        painter.drawEllipse(QPointF(center.x() + 20 + self._state.offset_x_um * 1.2, center.y() + self._state.offset_y_um * 1.2), 11, 11)
        painter.setPen(QPen(QColor("#475569"), 1.3))
        painter.drawLine(QPointF(center.x() - 30, center.y() + 34), QPointF(center.x() - 30, center.y() + 48))
        painter.drawLine(QPointF(center.x() - 48, center.y() + 48), QPointF(center.x() - 12, center.y() + 48))

    def _draw_output(self, painter: QPainter, center: QPointF, focused: bool) -> None:
        rect = QRectF(center.x() - 28, center.y() - 25, 56, 50)
        painter.setPen(QPen(self._focus_color(focused), 2.2 if focused else 1.2))
        painter.setBrush(QColor(theme.PRIMARY_TINT))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(theme.PRIMARY))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Pout")

    @staticmethod
    def _focus_color(focused: bool) -> QColor:
        return QColor(theme.PRIMARY) if focused else QColor("#7c9db2")

    def _draw_labels(self, painter: QPainter, xs: dict[str, float], axis_y: float) -> None:
        labels = {
            "laser": f"激光器\n{self._state.wavelength_nm:.0f} nm",
            "isolator": "光隔离器\n抑制回返光",
            "splitter": f"分束镜\n监测 {self._state.monitor_fraction * 100:.0f}%",
            "lens": f"聚焦镜组\nf = {self._state.focal_length_mm:.2f} mm",
            "fiber": f"光纤接收端\nNA = {self._state.fiber_na:.3f}",
            "output": f"输出端\nη = {(self._metrics.coupling_efficiency if self._metrics else 0.0) * 100:.1f}%",
        }
        painter.setPen(QColor("#173a55"))
        for key, text in labels.items():
            rect = QRectF(xs[key] - 62, axis_y + 56, 124, 46)
            if key in {"splitter", "lens", "fiber"}:
                rect.moveTop(axis_y - 102)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class TeachingOpticalScene3D(QWidget):


    objectActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._state = TeachingOpticalState()
        self._metrics: TeachingOpticalMetrics | None = None
        self._instruments: list[SceneInstrument] = []
        self._focus = "fiber"
        self._yaw = math.radians(-18.0)
        self._pitch = math.radians(27.0)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._last_mouse: QPointF | None = None
        self._dragging = False
        self._hit_boxes: dict[str, QRectF] = {}
        self._show_labels = True
        self._show_envelope = True
        self._show_branches = True
        self._show_axes = True

    def set_state(self, state: TeachingOpticalState, metrics: TeachingOpticalMetrics) -> None:
        self._state = state
        self._metrics = metrics
        self.update()

    def set_instruments(self, instruments: list[SceneInstrument]) -> None:
        self._instruments = list(instruments)
        self.update()

    def set_focus(self, key: str) -> None:
        self._focus = str(key)
        self.update()

    def set_layers(
        self,
        *,
        labels: bool | None = None,
        envelope: bool | None = None,
        branches: bool | None = None,
        axes: bool | None = None,
    ) -> None:
        if labels is not None:
            self._show_labels = bool(labels)
        if envelope is not None:
            self._show_envelope = bool(envelope)
        if branches is not None:
            self._show_branches = bool(branches)
        if axes is not None:
            self._show_axes = bool(axes)
        self.update()

    def set_view(self, name: str) -> None:
        views = {
            "isometric": (-18.0, 27.0, 1.0),
            "top": (0.0, 78.0, 0.92),
            "front": (0.0, 8.0, 1.0),
            "axis": (-88.0, 4.0, 1.18),
        }
        yaw, pitch, zoom = views.get(str(name), views["isometric"])
        self._yaw = math.radians(yaw)
        self._pitch = math.radians(pitch)
        self._zoom = zoom
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def focus_selected(self) -> None:
        positions = self._element_positions()
        point = positions.get(self._focus)
        if point is None:
            return
        projected = self._project(*point)
        center = QPointF(self.width() * 0.53, self.height() * 0.48)
        self._pan += center - projected
        self._zoom = min(1.65, max(1.05, self._zoom * 1.25))
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            for key, box in self._hit_boxes.items():
                if box.contains(event.position()):
                    self.objectActivated.emit(key)
                    return
            self._last_mouse = event.position()
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._last_mouse is not None:
            delta = event.position() - self._last_mouse
            self._last_mouse = event.position()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._pan += delta
            else:
                self._yaw += float(delta.x()) * 0.008
                self._pitch = min(math.radians(82.0), max(math.radians(-12.0), self._pitch + float(delta.y()) * 0.006))
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._last_mouse = None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        for key, box in self._hit_boxes.items():
            if box.contains(event.position()):
                self._focus = key
                self.objectActivated.emit(key)
                self.focus_selected()
                return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.12 if event.angleDelta().y() > 0 else 1.0 / 1.12
        self._zoom = min(2.2, max(0.55, self._zoom * factor))
        self.update()
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f4f7fa"))

        self._draw_platform(painter)
        if self._show_envelope:
            self._draw_beam(painter)
        self._draw_axis(painter)
        if self._show_branches:
            self._draw_measurement_branches(painter)
        self._draw_elements(painter)
        if self._show_axes and self._focus == "fiber":
            self._draw_five_axis_gizmo(painter)
        self._draw_overlay(painter)

    def _project(self, x: float, y: float, z: float) -> QPointF:
        cx = 510.0
        px = x - cx
        py = y
        pz = z - 35.0
        cos_yaw, sin_yaw = math.cos(self._yaw), math.sin(self._yaw)
        x1 = px * cos_yaw - py * sin_yaw
        depth = px * sin_yaw + py * cos_yaw
        cos_pitch, sin_pitch = math.cos(self._pitch), math.sin(self._pitch)
        y1 = depth * sin_pitch + pz * cos_pitch
        depth2 = depth * cos_pitch - pz * sin_pitch
        base_scale = min(max(self.width(), 1) / 1180.0, max(self.height(), 1) / 520.0)
        scale = base_scale * self._zoom
        return QPointF(
            self.width() * 0.51 + x1 * scale + self._pan.x(),
            self.height() * 0.53 - y1 * scale + depth2 * 0.10 * scale + self._pan.y(),
        )

    def _draw_platform(self, painter: QPainter) -> None:
        corners = [
            self._project(20, -205, 0),
            self._project(1030, -205, 0),
            self._project(1030, 205, 0),
            self._project(20, 205, 0),
        ]
        painter.setPen(QPen(QColor("#b8c6d0"), 1.2))
        painter.setBrush(QColor("#e5ebef"))
        painter.drawPolygon(QPolygonF(corners))

        painter.setPen(QPen(QColor(174, 190, 201, 100), 0.8))
        for x in range(60, 1010, 70):
            painter.drawLine(self._project(x, -195, 1), self._project(x, 195, 1))
        for y in range(-175, 190, 50):
            painter.drawLine(self._project(30, y, 1), self._project(1020, y, 1))

    def _draw_axis(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#e3342f"), 2.7))
        painter.drawLine(self._project(76, 0, 72), self._project(995, 0, 72))

    def _draw_beam(self, painter: QPainter) -> None:
        lens_x = 545.0
        fiber_x = 805.0 + self._state.offset_z_um * 1.3
        input_radius = 22.0 + min(24.0, self._state.input_beam_radius_mm * 20.0)
        end_radius = 7.0
        if self._metrics is not None:
            end_radius = max(4.0, min(30.0, self._metrics.beam_radius_at_fiber_um * 3.0))

        upper = [
            self._project(80, 0, 72 + input_radius),
            self._project(lens_x, 0, 72 + input_radius),
            self._project(fiber_x, 0, 72 + end_radius),
            self._project(982, 0, 72 + end_radius * 1.15),
        ]
        lower = [
            self._project(982, 0, 72 - end_radius * 1.15),
            self._project(fiber_x, 0, 72 - end_radius),
            self._project(lens_x, 0, 72 - input_radius),
            self._project(80, 0, 72 - input_radius),
        ]
        polygon = QPolygonF(upper + lower)
        gradient = QLinearGradient(self._project(80, 0, 72), self._project(982, 0, 72))
        gradient.setColorAt(0.0, QColor(239, 68, 68, 38))
        gradient.setColorAt(0.55, QColor(239, 68, 68, 78))
        gradient.setColorAt(1.0, QColor(239, 68, 68, 30))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(239, 68, 68, 100), 1.0))
        painter.drawPolygon(polygon)

    def _element_positions(self) -> dict[str, tuple[float, float, float]]:
        return {
            "laser": (80, 0, 72),
            "isolator": (235, 0, 72),
            "splitter": (390, 0, 72),
            "lens": (545, 0, 72),
            "fiber": (805 + self._state.offset_z_um * 1.3, self._state.offset_x_um * 5.0, 72 + self._state.offset_y_um * 5.0),
            "output": (980, 0, 72),
        }

    def _draw_elements(self, painter: QPainter) -> None:
        positions = self._element_positions()
        self._hit_boxes = {}
        for key in ("laser", "isolator", "splitter", "lens", "fiber", "output"):
            point = self._project(*positions[key])
            focused = self._focus == key
            if key == "laser":
                box = self._draw_3d_laser(painter, point, focused)
            elif key == "isolator":
                box = self._draw_3d_isolator(painter, point, focused)
            elif key == "splitter":
                box = self._draw_3d_splitter(painter, point, focused)
            elif key == "lens":
                box = self._draw_3d_lens(painter, point, focused)
            elif key == "fiber":
                box = self._draw_3d_fiber(painter, point, focused)
            else:
                box = self._draw_3d_output(painter, point, focused)
            self._hit_boxes[key] = box
            if self._show_labels:
                self._draw_scene_label(painter, key, point, focused)

        instrument_positions = self._instrument_positions()
        for instrument in self._instruments:
            pos = instrument_positions.get(instrument.key)
            if pos is None:
                continue
            point = self._project(*pos)
            focused = self._focus == instrument.key
            rect = QRectF(point.x() - 47, point.y() - 22, 94, 44)
            painter.setPen(QPen(QColor(theme.PRIMARY) if focused else QColor(theme.BORDER), 2.2 if focused else 1.1))
            painter.setBrush(QColor("#dff2ff") if focused else QColor(theme.SURFACE))
            painter.drawRoundedRect(rect, 7, 7)
            painter.setPen(QColor("#173a55"))
            painter.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignCenter, instrument.short_name)
            self._hit_boxes[instrument.key] = rect

    def _instrument_positions(self) -> dict[str, tuple[float, float, float]]:
        return {
            "input_power": (420, -145, 65),
            "output_power": (930, 130, 65),
            "beam_analyzer": (610, 140, 65),
            "mach_zehnder": (465, -155, 145),
            "shack_hartmann": (650, -145, 140),
            "polarimeter": (850, 145, 130),
        }

    def _draw_measurement_branches(self, painter: QPainter) -> None:
        origins = {
            "input_power": (390, 0, 72),
            "output_power": (850, 0, 72),
            "beam_analyzer": (545, 0, 72),
            "mach_zehnder": (390, 0, 72),
            "shack_hartmann": (545, 0, 72),
            "polarimeter": (805, 0, 72),
        }
        positions = self._instrument_positions()
        painter.setPen(QPen(QColor("#f59e0b"), 1.8, Qt.PenStyle.DashLine))
        for instrument in self._instruments:
            if instrument.key in origins and instrument.key in positions:
                painter.drawLine(self._project(*origins[instrument.key]), self._project(*positions[instrument.key]))

    @staticmethod
    def _focus_pen(focused: bool) -> QPen:
        return QPen(QColor("#0577ba") if focused else QColor("#738fa2"), 2.6 if focused else 1.3)

    def _draw_3d_laser(self, painter: QPainter, point: QPointF, focused: bool) -> QRectF:
        rect = QRectF(point.x() - 31, point.y() - 22, 62, 44)
        painter.setPen(self._focus_pen(focused))
        painter.setBrush(QColor("#dceffc"))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setBrush(QColor("#ef4444"))
        painter.drawEllipse(QPointF(point.x() + 31, point.y()), 5, 5)
        return rect.adjusted(-5, -5, 5, 5)

    def _draw_3d_isolator(self, painter: QPainter, point: QPointF, focused: bool) -> QRectF:
        rect = QRectF(point.x() - 34, point.y() - 18, 68, 36)
        painter.setPen(self._focus_pen(focused))
        painter.setBrush(QColor("#edf4f8"))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QPen(QColor(theme.PRIMARY), 2))
        painter.drawLine(QPointF(point.x() - 14, point.y()), QPointF(point.x() + 16, point.y()))
        painter.drawLine(QPointF(point.x() + 10, point.y() - 6), QPointF(point.x() + 16, point.y()))
        painter.drawLine(QPointF(point.x() + 10, point.y() + 6), QPointF(point.x() + 16, point.y()))
        return rect.adjusted(-5, -5, 5, 5)

    def _draw_3d_splitter(self, painter: QPainter, point: QPointF, focused: bool) -> QRectF:
        polygon = QPolygonF([
            QPointF(point.x() - 5, point.y() - 34),
            QPointF(point.x() + 24, point.y() - 4),
            QPointF(point.x() + 5, point.y() + 34),
            QPointF(point.x() - 24, point.y() + 4),
        ])
        painter.setPen(self._focus_pen(focused))
        painter.setBrush(QColor(173, 220, 242, 150))
        painter.drawPolygon(polygon)
        return polygon.boundingRect().adjusted(-6, -6, 6, 6)

    def _draw_3d_lens(self, painter: QPainter, point: QPointF, focused: bool) -> QRectF:
        rect = QRectF(point.x() - 13, point.y() - 48, 26, 96)
        painter.setPen(self._focus_pen(focused))
        painter.setBrush(QColor(126, 207, 238, 125))
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#7b91a0"), 2))
        painter.drawLine(QPointF(point.x(), point.y() + 48), QPointF(point.x(), point.y() + 62))
        painter.drawLine(QPointF(point.x() - 22, point.y() + 62), QPointF(point.x() + 22, point.y() + 62))
        return rect.adjusted(-8, -8, 8, 18)

    def _draw_3d_fiber(self, painter: QPainter, point: QPointF, focused: bool) -> QRectF:
        mount = QRectF(point.x() - 38, point.y() - 34, 65, 68)
        painter.setPen(self._focus_pen(focused))
        painter.setBrush(QColor("#e3e9ed"))
        painter.drawRoundedRect(mount, 5, 5)
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        tilt_x = self._state.yaw_mrad * 0.14
        tilt_y = self._state.pitch_mrad * 0.14
        painter.drawLine(
            QPointF(point.x() + 25, point.y()),
            QPointF(point.x() + 58 + tilt_x, point.y() - tilt_y),
        )
        mode_center = QPointF(point.x() + 25, point.y())
        radius = max(6.0, min(17.0, self._state.fiber_mode_radius_um * 3.0))
        painter.setPen(QPen(QColor("#178bd0"), 1.4))
        painter.setBrush(QColor(50, 160, 220, 55))
        painter.drawEllipse(mode_center, radius, radius)
        return QRectF(point.x() - 46, point.y() - 42, 110, 84)

    def _draw_3d_output(self, painter: QPainter, point: QPointF, focused: bool) -> QRectF:
        rect = QRectF(point.x() - 27, point.y() - 25, 54, 50)
        painter.setPen(self._focus_pen(focused))
        painter.setBrush(QColor("#eef5f9"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(theme.PRIMARY))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Pout")
        return rect.adjusted(-5, -5, 5, 5)

    def _draw_scene_label(self, painter: QPainter, key: str, point: QPointF, focused: bool) -> None:
        values = {
            "laser": f"{self._state.wavelength_nm:.0f} nm",
            "isolator": "单向保护",
            "splitter": f"{(1.0 - self._state.monitor_fraction) * 100:.0f}:{self._state.monitor_fraction * 100:.0f}",
            "lens": f"f={self._state.focal_length_mm:.2f} mm",
            "fiber": f"X={self._state.offset_x_um:+.1f} μm  Z={self._state.offset_z_um:+.1f} μm",
            "output": f"η={(self._metrics.coupling_efficiency if self._metrics else 0.0) * 100:.1f}%",
        }
        rect = QRectF(point.x() - 65, point.y() + 48, 130, 38)
        if key == "lens":
            rect.moveTop(point.y() - 86)
        painter.setPen(QColor(theme.PRIMARY) if focused else QColor(theme.TEXT_SECONDARY))
        font = QFont(painter.font())
        font.setBold(focused)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{ELEMENT_LABELS[key]}\n{values[key]}")

    def _draw_five_axis_gizmo(self, painter: QPainter) -> None:
        fiber = self._element_positions()["fiber"]
        origin = self._project(fiber[0], fiber[1], fiber[2] + 75)
        axes = [
            (QPointF(48, 0), QColor("#dc2626"), "Z"),
            (QPointF(-22, -35), QColor("#16a34a"), "X"),
            (QPointF(0, -48), QColor("#2563eb"), "Y"),
        ]
        for delta, color, label in axes:
            end = origin + delta
            painter.setPen(QPen(color, 2.2))
            painter.drawLine(origin, end)
            painter.drawText(QRectF(end.x() - 10, end.y() - 10, 20, 20), Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(QPen(QColor("#7c3aed"), 1.6, Qt.PenStyle.DashLine))
        painter.drawArc(QRectF(origin.x() - 28, origin.y() - 28, 56, 56), 25 * 16, 105 * 16)
        painter.drawText(QRectF(origin.x() - 48, origin.y() + 18, 96, 22), Qt.AlignmentFlag.AlignCenter, "Pitch / Yaw")

    def _draw_overlay(self, painter: QPainter) -> None:
        painter.setPen(QColor("#40566a"))
        painter.drawText(
            QRectF(18, 10, self.width() - 36, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "拖动旋转　Shift+拖动平移　滚轮缩放　双击元件聚焦",
        )
        if self._metrics is not None:
            text = (
                f"束腰 {self._metrics.waist_radius_um:.2f} μm　"
                f"端面光斑 {self._metrics.beam_radius_at_fiber_um:.2f} μm　"
                f"耦合效率 {self._metrics.coupling_efficiency * 100:.1f}%"
            )
            rect = QRectF(18, self.height() - 42, min(560, self.width() - 36), 28)
            painter.setPen(QPen(QColor("#a8bac7"), 1))
            painter.setBrush(QColor(255, 255, 255, 220))
            painter.drawRoundedRect(rect, 6, 6)
            painter.setPen(QColor("#173a55"))
            painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, text)


__all__ = ["SceneInstrument", "TeachingOpticalScene3D", "TeachingOverview2D"]
