
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.components.basic import Badge, Card, PrimaryButton, SecondaryButton
from .mismatch_lab import LESSONS, MismatchLesson, MismatchVisualWidget, TrendWidget, lesson_efficiency


class MismatchOverviewCanvas(QWidget):


    lessonActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(520, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._active_key = "lateral"
        self._hit_boxes: dict[str, QRectF] = {}

    def set_active_lesson(self, key: str) -> None:
        self._active_key = str(key)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        for key, rect in self._hit_boxes.items():
            if rect.contains(event.position()):
                self.lessonActivated.emit(key)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))
        outer = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        painter.setPen(QPen(QColor(theme.SURFACE_SECONDARY), 1))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(outer, 10, 10)

        title_font = QFont(painter.font())
        title_font.setBold(True)
        title_font.setPointSizeF(max(11.0, title_font.pointSizeF()))
        painter.setFont(title_font)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(
            outer.adjusted(18, 10, -18, -outer.height() + 42),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "完整耦合主图：先定位失配发生在哪里",
        )

        left = outer.left() + 48
        right = outer.right() - 52
        axis_y = outer.center().y() + 2
        lens_x = left + (right - left) * 0.42
        waist_x = left + (right - left) * 0.67
        fiber_x = left + (right - left) * 0.80

        painter.setPen(QPen(QColor("#8498a8"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))

        
        top = QPainterPath(QPointF(left, axis_y - 47))
        top.lineTo(lens_x, axis_y - 47)
        top.cubicTo(lens_x + 55, axis_y - 44, waist_x - 32, axis_y - 7, waist_x, axis_y - 5)
        top.cubicTo(waist_x + 34, axis_y - 7, fiber_x - 22, axis_y - 18, right, axis_y - 24)
        bottom = QPainterPath(QPointF(left, axis_y + 47))
        bottom.lineTo(lens_x, axis_y + 47)
        bottom.cubicTo(lens_x + 55, axis_y + 44, waist_x - 32, axis_y + 7, waist_x, axis_y + 5)
        bottom.cubicTo(waist_x + 34, axis_y + 7, fiber_x - 22, axis_y + 18, right, axis_y + 24)
        envelope = QPainterPath(top)
        reverse = QPainterPath(QPointF(right, axis_y + 24))
        reverse.cubicTo(waist_x + 34, axis_y + 7, waist_x + 34, axis_y + 7, waist_x, axis_y + 5)
        reverse.cubicTo(waist_x - 32, axis_y + 7, lens_x + 55, axis_y + 44, lens_x, axis_y + 47)
        reverse.lineTo(left, axis_y + 47)
        reverse.lineTo(left, axis_y - 47)
        reverse.lineTo(lens_x, axis_y - 47)
        reverse.cubicTo(lens_x + 55, axis_y - 44, waist_x - 32, axis_y - 7, waist_x, axis_y - 5)
        reverse.cubicTo(waist_x + 34, axis_y - 7, fiber_x - 22, axis_y - 18, right, axis_y - 24)
        reverse.closeSubpath()
        gradient = QLinearGradient(QPointF(left, axis_y), QPointF(right, axis_y))
        gradient.setColorAt(0.0, QColor(248, 190, 52, 75))
        gradient.setColorAt(0.65, QColor(239, 68, 68, 55))
        gradient.setColorAt(1.0, QColor(239, 68, 68, 24))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#e95b54"), 1.5))
        painter.drawPath(reverse)

        painter.setPen(QPen(QColor("#276aa8"), 1.8))
        for offset in (-31, -15, 0, 15, 31):
            painter.drawLine(QPointF(left, axis_y + offset), QPointF(lens_x, axis_y + offset))
            painter.drawLine(QPointF(lens_x, axis_y + offset), QPointF(waist_x, axis_y))

        
        painter.setPen(QPen(QColor("#1c6ea4"), 2))
        painter.setBrush(QColor(134, 202, 236, 120))
        painter.drawEllipse(QRectF(lens_x - 12, axis_y - 68, 24, 136))
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(QRectF(lens_x - 58, axis_y - 104, 116, 26), Qt.AlignmentFlag.AlignCenter, "聚焦镜组")

        
        painter.setPen(QPen(QColor(theme.SUCCESS), 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(waist_x, axis_y - 48), QPointF(waist_x, axis_y + 48))
        painter.setPen(QColor(theme.SUCCESS))
        painter.drawText(QRectF(waist_x - 64, axis_y + 58, 128, 24), Qt.AlignmentFlag.AlignCenter, "最佳束腰")

        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(fiber_x, axis_y - 72), QPointF(fiber_x, axis_y + 72))
        painter.setBrush(QColor("#e9f0f5"))
        painter.setPen(QPen(QColor("#7893a6"), 1.5))
        painter.drawRoundedRect(QRectF(fiber_x + 6, axis_y - 42, 74, 84), 6, 6)
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(fiber_x + 80, axis_y), QPointF(right, axis_y))
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(QRectF(fiber_x - 38, axis_y - 106, 148, 26), Qt.AlignmentFlag.AlignCenter, "光纤端面与单模光纤")

        painter.drawText(QRectF(left - 20, axis_y - 104, 120, 26), Qt.AlignmentFlag.AlignLeft, "输入光束")

        anchors = {
            "defocus": (QPointF((waist_x + fiber_x) / 2, axis_y + 38), "③", "轴向离焦", QPointF((waist_x + fiber_x) / 2 - 56, axis_y + 58)),
            "angle": (QPointF(fiber_x - 80, axis_y + 16), "④", "角度失配", QPointF(fiber_x - 160, axis_y + 34)),
            "lateral": (QPointF(fiber_x + 6, axis_y - 32), "①", "横向偏移", QPointF(fiber_x + 22, axis_y - 68)),
            "size": (QPointF(fiber_x + 6, axis_y + 32), "②", "尺寸失配", QPointF(fiber_x + 22, axis_y + 48)),
            "curvature": (QPointF(fiber_x - 42, axis_y - 54), "⑤", "曲率失配", QPointF(fiber_x - 130, axis_y - 92)),
        }
        self._hit_boxes.clear()
        compact = outer.width() < 650
        normal_font = QFont(painter.font())
        normal_font.setBold(True)
        painter.setFont(normal_font)
        for key, (point, number, label, label_pos) in anchors.items():
            active = key == self._active_key
            radius = 14 if active else 12
            color = QColor(theme.PRIMARY) if active else QColor("#8aa4b8")
            painter.setPen(QPen(QColor(theme.SURFACE), 2))
            painter.setBrush(color)
            painter.drawEllipse(point, radius, radius)
            painter.setPen(QColor(theme.SURFACE))
            painter.drawText(QRectF(point.x() - radius, point.y() - radius, 2 * radius, 2 * radius), Qt.AlignmentFlag.AlignCenter, number)
            if not compact or active:
                label_rect = QRectF(label_pos.x(), label_pos.y(), 112, 25)
                painter.setPen(color)
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
            self._hit_boxes[key] = QRectF(point.x() - 28, point.y() - 28, 56, 70)

        painter.setFont(QFont(painter.font().family(), max(9, painter.font().pointSize() - 1)))
        painter.setPen(QColor("#5a7082"))
        painter.drawText(
            outer.adjusted(18, outer.height() - 44, -18, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "①横向　②尺寸　③离焦　④角度　⑤曲率；点击编号切换。" if compact else "点击编号定位失配；左图保留完整光路，右图只放大当前物理原因。",
        )


class PrincipleLearningPage(QWidget):
    sectionRequested = Signal(str)
    progressChanged = Signal(str, int)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.lessons = LESSONS
        self.lesson_index = 0
        self.lesson = self.lessons[0]
        self.wavelength_nm = self._project_wavelength_nm()
        self._syncing = False
        self._answered: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        lesson_bar = QHBoxLayout()
        lesson_bar.setSpacing(5)
        self.lesson_group = QButtonGroup(self)
        self.lesson_group.setExclusive(True)
        self.lesson_buttons: list[QPushButton] = []
        for index, lesson in enumerate(self.lessons):
            button = SecondaryButton(f"{index + 1}. {lesson.title}")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, row=index: self.load_lesson(row))
            self.lesson_group.addButton(button, index)
            self.lesson_buttons.append(button)
            lesson_bar.addWidget(button, 1)
        root.addLayout(lesson_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        overview_card = Card("完整光路与失配位置", compact=True)
        self.overview = MismatchOverviewCanvas()
        self.overview.lessonActivated.connect(self._load_by_key)
        overview_card.body.addWidget(self.overview, 1)
        splitter.addWidget(overview_card)

        detail_card = Card("局部放大：理想状态与当前状态", compact=True)
        heading = QHBoxLayout()
        self.lesson_title = QLabel()
        self.lesson_title.setObjectName("cardTitle")
        self.parameter_badge = Badge("", "info")
        heading.addWidget(self.lesson_title)
        heading.addStretch(1)
        heading.addWidget(self.parameter_badge)
        detail_card.body.addLayout(heading)
        self.visual = MismatchVisualWidget()
        self.visual.setMinimumWidth(430)
        detail_card.body.addWidget(self.visual, 1)

        result_row = QHBoxLayout()
        self.efficiency_label = QLabel("100.0%")
        self.efficiency_label.setStyleSheet("font-size: 26px; font-weight: 700;")
        self.efficiency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.efficiency_bar = QProgressBar()
        self.efficiency_bar.setRange(0, 1000)
        self.efficiency_bar.setTextVisible(False)
        result_row.addWidget(QLabel("单因素匹配效率"))
        result_row.addWidget(self.efficiency_label)
        result_row.addWidget(self.efficiency_bar, 1)
        detail_card.body.addLayout(result_row)

        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_card.body.addWidget(self.explanation)
        splitter.addWidget(detail_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 560])
        root.addWidget(splitter, 1)

        self.trend = TrendWidget()
        self.trend.setVisible(False)
        root.addWidget(self.trend)

        controls = Card("预测—调节—解释", compact=True)
        question_row = QHBoxLayout()
        self.question = QLabel()
        self.question.setWordWrap(True)
        question_row.addWidget(self.question, 1)
        self.prediction_group = QButtonGroup(self)
        self.prediction_group.setExclusive(True)
        self.prediction_buttons: list[SecondaryButton] = []
        for choice in ("升高", "下降", "保持不变"):
            button = SecondaryButton(choice)
            button.setCheckable(True)
            button.clicked.connect(self._check_prediction)
            self.prediction_group.addButton(button)
            self.prediction_buttons.append(button)
            question_row.addWidget(button)
        controls.body.addLayout(question_row)

        parameter_row = QHBoxLayout()
        self.parameter_label = QLabel()
        self.parameter_label.setMinimumWidth(150)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.valueChanged.connect(self._slider_changed)
        self.spin = QDoubleSpinBox()
        self.spin.setKeyboardTracking(False)
        self.spin.valueChanged.connect(self._spin_changed)
        self.spin.setMinimumWidth(130)
        self.feedback = QLabel("先预测，再拖动参数观察变化。")
        self.feedback.setObjectName("helperText")
        self.feedback.setWordWrap(True)
        parameter_row.addWidget(self.parameter_label)
        parameter_row.addWidget(self.slider, 1)
        parameter_row.addWidget(self.spin)
        parameter_row.addWidget(self.feedback, 1)
        controls.body.addLayout(parameter_row)

        action_row = QHBoxLayout()
        self.trend_button = SecondaryButton("查看变化趋势")
        self.trend_button.setCheckable(True)
        self.trend_button.toggled.connect(self._toggle_trend)
        formula_button = SecondaryButton("查看原理与公式")
        formula_button.clicked.connect(self._show_formula)
        reset_button = SecondaryButton("恢复匹配状态")
        reset_button.clicked.connect(self._reset)
        diagnostic_button = PrimaryButton("进入实验诊断")
        diagnostic_button.clicked.connect(lambda: self.sectionRequested.emit("diagnostic"))
        action_row.addWidget(self.trend_button)
        action_row.addWidget(formula_button)
        action_row.addWidget(reset_button)
        action_row.addStretch(1)
        action_row.addWidget(diagnostic_button)
        controls.body.addLayout(action_row)
        root.addWidget(controls)

        self.load_lesson(0)

    def _project_wavelength_nm(self) -> float:
        try:
            project = self.context.project.project
            return float(getattr(project, "wavelength_nm", 808.0))
        except Exception:
            return 808.0

    def _load_by_key(self, key: str) -> None:
        for index, lesson in enumerate(self.lessons):
            if lesson.key == key:
                self.load_lesson(index)
                return

    def load_lesson(self, index: int) -> None:
        index = max(0, min(int(index), len(self.lessons) - 1))
        self.lesson_index = index
        self.lesson = self.lessons[index]
        self.lesson_buttons[index].setChecked(True)
        self.overview.set_active_lesson(self.lesson.key)
        self.lesson_title.setText(f"{self.lesson.title}：{self.lesson.short_title}")
        self.question.setText(self.lesson.question)
        self.parameter_label.setText(self.lesson.parameter_label)
        self.spin.blockSignals(True)
        self.spin.setRange(self.lesson.minimum, self.lesson.maximum)
        self.spin.setSingleStep(self.lesson.step)
        decimals = 0 if self.lesson.step >= 1 else min(3, max(1, len(str(self.lesson.step).split(".")[-1])))
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(f" {self.lesson.unit}" if self.lesson.unit else "")
        self.spin.setValue(self.lesson.default)
        self.spin.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setValue(self._value_to_slider(self.lesson.default))
        self.slider.blockSignals(False)
        for button in self.prediction_buttons:
            button.setChecked(False)
        self.feedback.setText("先预测，再拖动参数观察变化。")
        self._update(self.lesson.default)

    def _update(self, value: float) -> None:
        efficiency = lesson_efficiency(self.lesson, value, self.wavelength_nm)
        unit = f" {self.lesson.unit}" if self.lesson.unit else ""
        self.parameter_badge.setText(f"{value:.{self.spin.decimals()}f}{unit}")
        self.efficiency_label.setText(f"{efficiency * 100:.1f}%")
        self.efficiency_bar.setValue(round(efficiency * 1000))
        self.visual.set_state(self.lesson, value, efficiency)
        self.trend.set_state(self.lesson, self.wavelength_nm, value)
        self.explanation.setText(
            f"现象：{self.lesson.phenomenon}\n\n"
            f"为什么：{self.lesson.reason}\n\n"
            f"实验调整：{self.lesson.adjustment}"
        )

    def _value_to_slider(self, value: float) -> int:
        span = max(self.lesson.maximum - self.lesson.minimum, 1e-12)
        return round(max(0.0, min(1.0, (value - self.lesson.minimum) / span)) * 1000)

    def _slider_to_value(self, value: int) -> float:
        ratio = max(0.0, min(1.0, value / 1000.0))
        raw = self.lesson.minimum + ratio * (self.lesson.maximum - self.lesson.minimum)
        step = max(self.lesson.step, 1e-12)
        snapped = round((raw - self.lesson.minimum) / step) * step + self.lesson.minimum
        return max(self.lesson.minimum, min(self.lesson.maximum, snapped))

    def _slider_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.spin.setValue(self._slider_to_value(value))
        self._syncing = False
        self._update(self.spin.value())

    def _spin_changed(self, value: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.slider.setValue(self._value_to_slider(value))
        self._syncing = False
        self._update(value)

    def _check_prediction(self) -> None:
        button = self.prediction_group.checkedButton()
        if button is None:
            return
        correct = button.text().strip() == self.lesson.answer
        if correct:
            self._answered.add(self.lesson.key)
        self.feedback.setText(("✓ 判断正确。" if correct else "✗ 再观察主图和局部图。") + " " + self.lesson.reason)
        self.progressChanged.emit("principle", round(len(self._answered) / len(self.lessons) * 100))

    def _toggle_trend(self, visible: bool) -> None:
        self.trend.setVisible(bool(visible))
        self.trend_button.setText("收起变化趋势" if visible else "查看变化趋势")

    def _reset(self) -> None:
        self.spin.setValue(self.lesson.default)
        for button in self.prediction_buttons:
            button.setChecked(False)
        self.feedback.setText("已恢复匹配状态。")

    def _show_formula(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{self.lesson.title}：原理与公式")
        dialog.resize(560, 260)
        layout = QVBoxLayout(dialog)
        title = QLabel(self.lesson.formula)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note = QLabel(
            self.lesson.reason
            + "\n\n教学页展示单因素趋势；多个误差共同存在时，应回到正式复场重叠计算。"
        )
        note.setWordWrap(True)
        close = PrimaryButton("知道了")
        close.clicked.connect(dialog.accept)
        layout.addWidget(title)
        layout.addWidget(note)
        layout.addStretch(1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()


__all__ = ["MismatchOverviewCanvas", "PrincipleLearningPage"]
