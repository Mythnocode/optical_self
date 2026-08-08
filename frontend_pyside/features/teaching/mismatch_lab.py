from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget


from frontend_pyside.resources import theme_tokens as theme

@dataclass(frozen=True)
class MismatchLesson:
    key: str
    title: str
    short_title: str
    parameter_label: str
    unit: str
    minimum: float
    maximum: float
    default: float
    step: float
    question: str
    answer: str
    phenomenon: str
    reason: str
    adjustment: str
    formula: str
    visual_mode: str
    efficiency: Callable[[float, float], float]


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _lateral_efficiency(value: float, _wavelength_nm: float) -> float:
    mode_radius_um = 5.2
    return _clip01(math.exp(-((float(value) / mode_radius_um) ** 2)))


def _size_efficiency(value: float, _wavelength_nm: float) -> float:
    ratio = max(1e-6, float(value))
    return _clip01((2.0 * ratio / (1.0 + ratio * ratio)) ** 2)


def _defocus_efficiency(value: float, _wavelength_nm: float) -> float:
    rayleigh_range_um = 65.0
    normalized = float(value) / rayleigh_range_um
    return _clip01(1.0 / (1.0 + normalized * normalized))


def _angle_efficiency(value: float, wavelength_nm: float) -> float:
    wavelength_um = max(float(wavelength_nm) * 1e-3, 1e-6)
    effective_radius_um = 5.2
    angle_rad = abs(float(value)) * 1e-3
    exponent = math.pi * effective_radius_um * angle_rad / wavelength_um
    return _clip01(math.exp(-(exponent * exponent)))


def _curvature_efficiency(value: float, _wavelength_nm: float) -> float:
    
    
    
    phase_waves = abs(float(value))
    return _clip01(1.0 / (1.0 + (math.pi * phase_waves) ** 2))


LESSONS: tuple[MismatchLesson, ...] = (
    MismatchLesson(
        key="lateral",
        title="横向偏移",
        short_title="位置没有对准",
        parameter_label="横向偏移 Δx",
        unit="μm",
        minimum=0.0,
        maximum=8.0,
        default=0.0,
        step=0.1,
        question="入射光斑逐渐离开纤芯中心时，耦合效率会怎样变化？",
        answer="下降",
        phenomenon="两个光斑中心逐渐分离，重叠区域变小。",
        reason="入射场与光纤基模的空间重叠减少，因此可进入目标模式的能量下降。",
        adjustment="优先调节五轴架的 X/Y 方向，使两个中心重新重合。",
        formula="ηₓᵧ ≈ exp[-(Δx²+Δy²)/w²]",
        visual_mode="endpoint",
        efficiency=_lateral_efficiency,
    ),
    MismatchLesson(
        key="size",
        title="尺寸失配",
        short_title="光斑大小不同",
        parameter_label="光斑半径比 w/wf",
        unit="",
        minimum=0.50,
        maximum=1.50,
        default=1.00,
        step=0.01,
        question="中心保持重合，但光斑变得过大或过小时，耦合效率会怎样变化？",
        answer="下降",
        phenomenon="两个光斑中心重合，但边缘不能同时重合。",
        reason="光斑过大或过小都会使一部分场分布落在目标模式之外。",
        adjustment="调整聚焦焦距、入射束径或镜片位置，使端面光斑半径接近光纤模场半径。",
        formula="ηsize ≈ [2wwf/(w²+wf²)]²",
        visual_mode="endpoint",
        efficiency=_size_efficiency,
    ),
    MismatchLesson(
        key="defocus",
        title="轴向离焦",
        short_title="端面不在最佳焦面",
        parameter_label="轴向偏移 Δz",
        unit="μm",
        minimum=-150.0,
        maximum=150.0,
        default=0.0,
        step=2.0,
        question="光纤端面离开最佳束腰位置后，耦合效率会怎样变化？",
        answer="下降",
        phenomenon="端面位于束腰前或束腰后，端面光斑和波前曲率同时改变。",
        reason="离焦会同时引起尺寸失配和相位曲率失配，所以即使中心对准，复场重叠仍会下降。",
        adjustment="沿 Z 方向移动光纤端面，先找到效率峰值，再做 X/Y 微调。",
        formula="ηz ≈ 1/√[1+(Δz/zR)²]",
        visual_mode="defocus",
        efficiency=_defocus_efficiency,
    ),
    MismatchLesson(
        key="angle",
        title="角度失配",
        short_title="传播方向不同",
        parameter_label="倾角 θ",
        unit="mrad",
        minimum=0.0,
        maximum=60.0,
        default=0.0,
        step=0.5,
        question="光斑中心仍在纤芯中心，但传播方向发生倾斜时，耦合效率会怎样变化？",
        answer="下降",
        phenomenon="端面中心可以重合，但入射光轴与光纤轴线形成夹角。",
        reason="倾角引入线性相位坡度，不同位置的复振幅不能完全同相叠加。",
        adjustment="调节 Pitch/Yaw，使入射光轴与光纤轴线平行，再检查横向中心。",
        formula="ηθ ≈ exp[-(πwθ/λ)²]",
        visual_mode="angle",
        efficiency=_angle_efficiency,
    ),
    MismatchLesson(
        key="curvature",
        title="曲率失配",
        short_title="波前弯曲程度不同",
        parameter_label="端面边缘相位差",
        unit="waves",
        minimum=0.0,
        maximum=1.5,
        default=0.0,
        step=0.02,
        question="光斑中心和大小都相同，但波前曲率不同，耦合效率会怎样变化？",
        answer="下降",
        phenomenon="强度轮廓看起来一致，但入射波前和目标模式波前的弯曲程度不同。",
        reason="各位置的相位不能一致相加，复场积分会发生部分抵消。",
        adjustment="调整焦面位置或镜组间距，使端面处的波前曲率与光纤模式匹配。",
        formula="ηR ∝ |∬A²exp(iΔφR)dA|²",
        visual_mode="curvature",
        efficiency=_curvature_efficiency,
    ),
)

LESSON_BY_KEY = {lesson.key: lesson for lesson in LESSONS}


def lesson_efficiency(lesson: MismatchLesson, value: float, wavelength_nm: float) -> float:
    return lesson.efficiency(float(value), float(wavelength_nm))


def trend_samples(
    lesson: MismatchLesson,
    wavelength_nm: float,
    points: int = 121,
) -> tuple[list[float], list[float]]:
    points = max(5, int(points))
    span = lesson.maximum - lesson.minimum
    x = [lesson.minimum + span * i / (points - 1) for i in range(points)]
    y = [lesson_efficiency(lesson, value, wavelength_nm) for value in x]
    return x, y


class MismatchVisualWidget(QWidget):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.lesson = LESSONS[0]
        self.value = self.lesson.default
        self.efficiency = 1.0
        self.setMinimumSize(420, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setObjectName("mismatchVisual")

    def set_state(self, lesson: MismatchLesson, value: float, efficiency: float) -> None:
        self.lesson = lesson
        self.value = float(value)
        self.efficiency = _clip01(efficiency)
        self.update()

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#fbfdff"))
        rect = self.rect().adjusted(18, 16, -18, -18)
        painter.setPen(QPen(QColor(theme.SURFACE_SECONDARY), 1))
        painter.drawRoundedRect(QRectF(rect), 10, 10)
        self._draw_title(painter, rect)
        diagram = QRectF(rect.left() + 18, rect.top() + 56, rect.width() - 36, rect.height() - 88)
        if self.lesson.visual_mode == "endpoint":
            self._draw_endpoint(painter, diagram)
        elif self.lesson.visual_mode == "defocus":
            self._draw_defocus(painter, diagram)
        elif self.lesson.visual_mode == "angle":
            self._draw_angle(painter, diagram)
        else:
            self._draw_curvature(painter, diagram)
        self._draw_legend(painter, rect)

    def _draw_title(self, painter: QPainter, rect) -> None:
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSizeF(max(11.0, font.pointSizeF()))
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(
            QRectF(rect.left() + 18, rect.top() + 12, rect.width() - 36, 28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{self.lesson.title}：{self.lesson.short_title}",
        )

    def _draw_endpoint(self, painter: QPainter, rect: QRectF) -> None:
        side = min(rect.width(), rect.height()) * 0.72
        center = QPointF(rect.center().x(), rect.center().y() + 4)
        target_radius = side * 0.25
        shift = 0.0
        incident_radius = target_radius
        if self.lesson.key == "lateral":
            normalized = (self.value - self.lesson.minimum) / max(
                self.lesson.maximum - self.lesson.minimum, 1e-9
            )
            shift = normalized * target_radius * 1.65
        elif self.lesson.key == "size":
            incident_radius = target_radius * max(0.38, min(1.65, self.value))

        self._draw_mode_disc(
            painter,
            QPointF(center.x(), center.y()),
            target_radius,
            QColor(theme.PRIMARY),
            "光纤基模",
            label_offset=-target_radius - 28,
        )
        self._draw_mode_disc(
            painter,
            QPointF(center.x() + shift, center.y()),
            incident_radius,
            QColor(theme.ERROR),
            "入射光场",
            label_offset=target_radius + 14,
        )
        painter.setPen(QPen(QColor("#58738c"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(center.x(), center.y() - target_radius * 1.35), QPointF(center.x(), center.y() + target_radius * 1.35))
        painter.drawLine(QPointF(center.x() - target_radius * 1.35, center.y()), QPointF(center.x() + target_radius * 1.35, center.y()))

    def _draw_mode_disc(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        color: QColor,
        label: str,
        *,
        label_offset: float,
    ) -> None:
        gradient = QRadialGradient(center, radius)
        translucent = QColor(color)
        translucent.setAlpha(110)
        edge = QColor(color)
        edge.setAlpha(18)
        gradient.setColorAt(0.0, translucent)
        gradient.setColorAt(0.62, QColor(color.red(), color.green(), color.blue(), 58))
        gradient.setColorAt(1.0, edge)
        painter.setBrush(gradient)
        painter.setPen(QPen(color, 2))
        painter.drawEllipse(center, radius, radius)
        painter.setPen(color)
        label_rect = QRectF(center.x() - 90, center.y() + label_offset, 180, 24)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_defocus(self, painter: QPainter, rect: QRectF) -> None:
        axis_y = rect.center().y()
        left = rect.left() + 28
        right = rect.right() - 28
        waist_x = rect.center().x()
        span = right - left
        normalized = (self.value - self.lesson.minimum) / max(
            self.lesson.maximum - self.lesson.minimum, 1e-9
        )
        facet_x = left + normalized * span

        painter.setPen(QPen(QColor("#58738c"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))

        top = QPainterPath(QPointF(left, axis_y - 72))
        bottom = QPainterPath(QPointF(left, axis_y + 72))
        steps = 90
        for i in range(1, steps + 1):
            x = left + span * i / steps
            t = (x - waist_x) / max(span * 0.30, 1.0)
            radius = 17 + 56 * min(1.0, abs(t) ** 0.92)
            top.lineTo(x, axis_y - radius)
            bottom.lineTo(x, axis_y + radius)
        painter.setPen(QPen(QColor(theme.ERROR), 2))
        painter.drawPath(top)
        painter.drawPath(bottom)

        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(facet_x, axis_y - 92), QPointF(facet_x, axis_y + 92))
        painter.setPen(QPen(QColor(theme.PRIMARY), 1))
        painter.drawText(QRectF(facet_x - 75, axis_y + 100, 150, 24), Qt.AlignmentFlag.AlignCenter, "光纤端面")

        painter.setPen(QPen(QColor(theme.SUCCESS), 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(waist_x, axis_y - 48), QPointF(waist_x, axis_y + 48))
        painter.setPen(QColor(theme.SUCCESS))
        painter.drawText(QRectF(waist_x - 70, axis_y - 126, 140, 24), Qt.AlignmentFlag.AlignCenter, "最佳束腰")

    def _draw_angle(self, painter: QPainter, rect: QRectF) -> None:
        axis_y = rect.center().y()
        left = rect.left() + 34
        right = rect.right() - 34
        center_x = rect.center().x()
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))
        painter.setPen(QColor(theme.PRIMARY))
        painter.drawText(QRectF(right - 150, axis_y + 18, 150, 24), Qt.AlignmentFlag.AlignRight, "光纤轴线")

        normalized = abs(self.value) / max(abs(self.lesson.maximum), 1e-9)
        angle = normalized * math.radians(16.0)
        length = (right - left) * 0.86
        start = QPointF(left, axis_y + math.tan(angle) * length * 0.42)
        end = QPointF(left + length, start.y() - math.tan(angle) * length)
        painter.setPen(QPen(QColor(theme.ERROR), 4))
        painter.drawLine(start, end)
        painter.setPen(QColor(theme.ERROR))
        painter.drawText(QRectF(left, rect.top() + 18, 160, 26), Qt.AlignmentFlag.AlignLeft, "入射光轴")

        painter.setPen(QPen(QColor("#58738c"), 2))
        painter.drawLine(QPointF(center_x, axis_y - 90), QPointF(center_x, axis_y + 90))
        painter.setPen(QColor("#58738c"))
        painter.drawText(QRectF(center_x - 75, axis_y + 98, 150, 24), Qt.AlignmentFlag.AlignCenter, "光纤端面")

    def _draw_curvature(self, painter: QPainter, rect: QRectF) -> None:
        left = rect.left() + 54
        width = rect.width() - 108
        normalized = abs(self.value) / max(self.lesson.maximum, 1e-9)
        base_y = rect.bottom() - 30
        target_bow = max(34.0, min(72.0, rect.height() * 0.40))
        incident_bow = target_bow + normalized * max(24.0, min(58.0, rect.height() * 0.30))

        painter.setPen(QPen(QColor(theme.PRIMARY), 4))
        target = QPainterPath(QPointF(left, base_y))
        target.cubicTo(
            QPointF(left + width * 0.28, base_y - target_bow),
            QPointF(left + width * 0.72, base_y - target_bow),
            QPointF(left + width, base_y),
        )
        painter.drawPath(target)

        painter.setPen(QPen(QColor(theme.ERROR), 4))
        incident = QPainterPath(QPointF(left, base_y))
        incident.cubicTo(
            QPointF(left + width * 0.28, base_y - incident_bow),
            QPointF(left + width * 0.72, base_y - incident_bow),
            QPointF(left + width, base_y),
        )
        painter.drawPath(incident)

        painter.setPen(QColor(theme.PRIMARY))
        painter.drawText(QRectF(left, rect.top() + 16, 170, 24), Qt.AlignmentFlag.AlignLeft, "光纤目标波前")
        painter.setPen(QColor(theme.ERROR))
        painter.drawText(QRectF(rect.right() - 190, rect.top() + 16, 180, 24), Qt.AlignmentFlag.AlignRight, "入射波前")

    def _draw_legend(self, painter: QPainter, rect) -> None:
        painter.setFont(QFont(painter.font().family(), max(9, painter.font().pointSize() - 1)))
        painter.setPen(QColor("#58738c"))
        text = f"当前教学近似耦合效率：{self.efficiency * 100:.1f}%"
        painter.drawText(
            QRectF(rect.left() + 18, rect.bottom() - 32, rect.width() - 36, 24),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            text,
        )


class TrendWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lesson = LESSONS[0]
        self.wavelength_nm = 1550.0
        self.current_value = self.lesson.default
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setObjectName("mismatchTrend")

    def set_state(self, lesson: MismatchLesson, wavelength_nm: float, current_value: float) -> None:
        self.lesson = lesson
        self.wavelength_nm = float(wavelength_nm)
        self.current_value = float(current_value)
        self.update()

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        rect = self.rect().adjusted(54, 18, -22, -42)
        painter.setPen(QPen(QColor("#b8cad8"), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.topLeft())
        painter.setPen(QColor("#58738c"))
        painter.drawText(QRectF(4, rect.top() - 6, 46, 24), Qt.AlignmentFlag.AlignRight, "100%")
        painter.drawText(QRectF(4, rect.bottom() - 12, 46, 24), Qt.AlignmentFlag.AlignRight, "0%")
        painter.drawText(
            QRectF(rect.left(), rect.bottom() + 12, rect.width(), 24),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.lesson.parameter_label} / {self.lesson.unit or '比值'}",
        )

        x_values, y_values = trend_samples(self.lesson, self.wavelength_nm)
        span = max(self.lesson.maximum - self.lesson.minimum, 1e-9)
        path = QPainterPath()
        for index, (x_value, y_value) in enumerate(zip(x_values, y_values)):
            x = rect.left() + (x_value - self.lesson.minimum) / span * rect.width()
            y = rect.bottom() - y_value * rect.height()
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawPath(path)

        current_eta = lesson_efficiency(self.lesson, self.current_value, self.wavelength_nm)
        cx = rect.left() + (self.current_value - self.lesson.minimum) / span * rect.width()
        cy = rect.bottom() - current_eta * rect.height()
        painter.setBrush(QColor(theme.ERROR))
        painter.setPen(QPen(QColor(theme.SURFACE), 2))
        painter.drawEllipse(QPointF(cx, cy), 6, 6)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        label_left = min(rect.right() - 140, max(rect.left(), cx - 70))
        painter.drawText(
            QRectF(label_left, max(rect.top(), cy - 32), 140, 24),
            Qt.AlignmentFlag.AlignCenter,
            f"当前 {current_eta * 100:.1f}%",
        )
