
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.components.basic import Badge, Card, InlineMetric, PrimaryButton, SecondaryButton


FOCAL_POOL = (4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 25.0)
STEP_TITLES = (
    "定义目标与约束",
    "分解效率瓶颈",
    "分配镜片功能",
    "建立焦距候选池",
    "完成近轴筛选",
    "检查镜片方向",
    "分轮开放优化变量",
    "正式验证与复盘",
)


@dataclass(frozen=True, slots=True)
class DesignState:
    mode: str = "semi"
    lens_count: int = 2
    wavelength_nm: float = 808.0
    source_na: float = 0.12
    receiver_na: float = 0.10
    receiver_mfd_um: float = 5.6
    max_length_mm: float = 50.0
    min_gap_mm: float = 0.5
    target_total: float = 0.90
    focal_lengths_mm: tuple[float, ...] = (8.0, 6.0, 10.0, 12.0)
    gaps_mm: tuple[float, ...] = (5.0, 8.0, 8.0, 5.0, 5.0)
    reversed_flags: tuple[bool, ...] = (False, False, False, False)

    def normalized(self) -> "DesignState":
        count = max(1, min(4, int(self.lens_count)))
        focals = tuple(float(x) for x in self.focal_lengths_mm[:4])
        focals += tuple(10.0 for _ in range(4 - len(focals)))
        gaps = tuple(float(x) for x in self.gaps_mm[:5])
        gaps += tuple(5.0 for _ in range(5 - len(gaps)))
        flags = tuple(bool(x) for x in self.reversed_flags[:4])
        flags += tuple(False for _ in range(4 - len(flags)))
        return replace(
            self,
            mode="free" if self.mode == "free" else "semi",
            lens_count=count,
            wavelength_nm=max(200.0, float(self.wavelength_nm)),
            source_na=max(0.001, min(0.95, float(self.source_na))),
            receiver_na=max(0.001, min(0.95, float(self.receiver_na))),
            receiver_mfd_um=max(0.5, float(self.receiver_mfd_um)),
            max_length_mm=max(5.0, float(self.max_length_mm)),
            min_gap_mm=max(0.0, float(self.min_gap_mm)),
            target_total=max(0.05, min(0.999, float(self.target_total))),
            focal_lengths_mm=focals,
            gaps_mm=gaps,
            reversed_flags=flags,
        )


@dataclass(frozen=True, slots=True)
class DesignMetrics:
    target_waist_um: float
    predicted_waist_um: float
    max_beam_radius_mm: float
    total_length_mm: float
    system_efficiency: float
    receiver_efficiency: float
    total_efficiency: float
    feasible: bool
    main_bottleneck: str
    evidence: tuple[str, ...]
    recommendation: str


def evaluate_design(state: DesignState) -> DesignMetrics:
    s = state.normalized()
    count = s.lens_count
    wavelength_um = s.wavelength_nm / 1000.0
    target_waist = wavelength_um / max(math.pi * s.receiver_na, 1e-9)

    focals = s.focal_lengths_mm[:count]
    active_gaps = s.gaps_mm[: count + 1]
    total_length = sum(active_gaps) + count * 2.2

    
    
    source_radius_mm = wavelength_um / max(math.pi * s.source_na, 1e-9) / 1000.0
    source_radius_mm = max(0.28, min(1.6, source_radius_mm * 1150.0))
    transform = 1.0
    for index, focal in enumerate(focals[:-1]):
        role_weight = 0.18 + 0.06 * index
        transform *= max(0.58, min(1.55, 1.0 + role_weight * (10.0 / focal - 1.0)))
    beam_at_final = max(0.22, min(2.2, source_radius_mm * transform))
    final_focal = focals[-1]
    predicted_waist = (s.wavelength_nm * 1e-6 * final_focal / (math.pi * beam_at_final)) * 1000.0

    size_match = (2.0 * predicted_waist * target_waist / max(predicted_waist**2 + target_waist**2, 1e-12)) ** 2

    
    
    if count <= 1:
        progression = 0.82
    else:
        jumps = [abs(math.log(max(focals[i + 1], 1e-6) / max(focals[i], 1e-6))) for i in range(count - 1)]
        progression = math.exp(-0.20 * sum(jumps))
    role_capacity = {1: 0.78, 2: 0.90, 3: 0.96, 4: 0.985}[count]
    direction_penalty = 1.0
    for index, reversed_flag in enumerate(s.reversed_flags[:count]):
        if reversed_flag:
            
            
            direction_penalty *= 0.985 if index in {1, 2} else 0.965
    receiver = max(0.0, min(1.0, size_match * progression * role_capacity * direction_penalty))

    coating = 0.992 ** (2 * count)
    min_gap = min(active_gaps) if active_gaps else 999.0
    gap_penalty = 1.0 if min_gap >= s.min_gap_mm else math.exp(-3.0 * (s.min_gap_mm - min_gap))
    length_penalty = 1.0 if total_length <= s.max_length_mm else math.exp(-(total_length - s.max_length_mm) / max(s.max_length_mm * 0.15, 1.0))
    max_beam_radius = beam_at_final * (1.0 + 0.10 * max(0, count - 2))
    aperture_penalty = 1.0 if max_beam_radius <= 2.6 else math.exp(-((max_beam_radius - 2.6) / 0.5) ** 2)
    system = max(0.0, min(1.0, coating * gap_penalty * length_penalty * aperture_penalty))
    total = system * receiver

    evidence: list[str] = []
    feasible = True
    if min_gap < s.min_gap_mm:
        feasible = False
        evidence.append(f"最小空气间隔 {min_gap:.2f} mm，小于约束 {s.min_gap_mm:.2f} mm。")
    else:
        evidence.append(f"所有空气间隔均不小于 {s.min_gap_mm:.2f} mm。")
    if total_length > s.max_length_mm:
        feasible = False
        evidence.append(f"总长 {total_length:.1f} mm，超过 {s.max_length_mm:.1f} mm。")
    else:
        evidence.append(f"总长 {total_length:.1f} mm，满足结构限制。")
    if max_beam_radius > 2.6:
        feasible = False
        evidence.append(f"最大光束半径约 {max_beam_radius:.2f} mm，候选镜片有效口径余量不足。")
    else:
        evidence.append(f"最大光束半径约 {max_beam_radius:.2f} mm，孔径余量基本可用。")
    evidence.append(f"预测束腰 {predicted_waist:.2f} μm，目标束腰 {target_waist:.2f} μm。")

    if system < receiver:
        bottleneck = "系统通过能力"
        recommendation = "优先检查空气间隔、总长、有效口径和镜片方向；不要只移动接收光纤。"
    else:
        bottleneck = "接收模场匹配"
        recommendation = "优先调整末级焦距、末级间距和中间波前整形，使束腰与曲率接近目标模式。"
    if not feasible:
        recommendation = "当前方案数学上可能有较高效率，但机械或孔径约束不成立，应更换焦距组合或镜片。"

    return DesignMetrics(
        target_waist_um=target_waist,
        predicted_waist_um=predicted_waist,
        max_beam_radius_mm=max_beam_radius,
        total_length_mm=total_length,
        system_efficiency=system,
        receiver_efficiency=receiver,
        total_efficiency=total,
        feasible=feasible,
        main_bottleneck=bottleneck,
        evidence=tuple(evidence),
        recommendation=recommendation,
    )


class LensDesignCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(310)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.state = DesignState()
        self.metrics = evaluate_design(self.state)
        self.active_lens = -1

    def set_state(self, state: DesignState, metrics: DesignMetrics, active_lens: int = -1) -> None:
        self.state = state.normalized()
        self.metrics = metrics
        self.active_lens = int(active_lens)
        self.update()

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))
        area = QRectF(self.rect()).adjusted(14, 12, -14, -12)
        painter.setPen(QPen(QColor(theme.SURFACE_SECONDARY), 1))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(area, 9, 9)

        count = self.state.lens_count
        left = area.left() + 55
        right = area.right() - 65
        axis_y = area.top() + area.height() * 0.39
        painter.setPen(QPen(QColor("#8095a6"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))

        lens_xs = []
        span = right - left
        for i in range(count):
            lens_xs.append(left + span * (0.28 + 0.50 * (i + 1) / (count + 1)))
        source_x = left
        receiver_x = right
        final_x = lens_xs[-1]
        waist_x = receiver_x - 25

        
        input_r = 38.0
        final_r = max(4.0, min(36.0, self.metrics.predicted_waist_um / max(self.metrics.target_waist_um, 1e-9) * 10.0))
        path = QPainterPath(QPointF(source_x, axis_y - input_r))
        previous_x = source_x
        previous_r = input_r
        for i, x in enumerate(lens_xs):
            r = max(16.0, input_r * (0.95 - 0.08 * i)) if i < count - 1 else previous_r
            path.lineTo(x, axis_y - r)
            previous_x, previous_r = x, r
        path.lineTo(waist_x, axis_y - final_r)
        path.lineTo(receiver_x, axis_y - final_r * 1.05)
        path.lineTo(receiver_x, axis_y + final_r * 1.05)
        path.lineTo(waist_x, axis_y + final_r)
        for i, x in reversed(list(enumerate(lens_xs))):
            r = max(16.0, input_r * (0.95 - 0.08 * i)) if i < count - 1 else previous_r
            path.lineTo(x, axis_y + r)
        path.lineTo(source_x, axis_y + input_r)
        path.closeSubpath()
        gradient = QLinearGradient(QPointF(source_x, axis_y), QPointF(receiver_x, axis_y))
        gradient.setColorAt(0.0, QColor(248, 190, 52, 80))
        gradient.setColorAt(0.7, QColor(239, 91, 91, 58))
        gradient.setColorAt(1.0, QColor(239, 91, 91, 25))
        painter.setPen(QPen(QColor("#e85e55"), 1.4))
        painter.setBrush(gradient)
        painter.drawPath(path)

        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(QRectF(source_x - 44, axis_y - 92, 100, 26), Qt.AlignmentFlag.AlignCenter, "源光纤")
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(source_x + 18, axis_y - 42), QPointF(source_x + 18, axis_y + 42))

        for index, (x, focal) in enumerate(zip(lens_xs, self.state.focal_lengths_mm[:count])):
            active = index == self.active_lens
            painter.setPen(QPen(QColor(theme.PRIMARY) if active else QColor(theme.PRIMARY), 3 if active else 2))
            painter.setBrush(QColor(123, 203, 238, 145 if active else 95))
            painter.drawEllipse(QRectF(x - 10, axis_y - 58, 20, 116))
            painter.setPen(QColor(theme.TEXT_PRIMARY))
            orientation = "反向" if self.state.reversed_flags[index] else "正向"
            painter.drawText(QRectF(x - 38, axis_y + 62, 76, 38), Qt.AlignmentFlag.AlignCenter, f"L{index + 1}\n{focal:.0f}mm｜{'反' if self.state.reversed_flags[index] else '正'}")

        painter.setPen(QPen(QColor(theme.SUCCESS), 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(waist_x, axis_y - 48), QPointF(waist_x, axis_y + 48))
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(receiver_x, axis_y - 48), QPointF(receiver_x, axis_y + 48))
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(QRectF(receiver_x - 48, axis_y - 92, 96, 26), Qt.AlignmentFlag.AlignCenter, "接收光纤")
        painter.drawText(
            area.adjusted(16, area.height() - 42, -16, -10),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{count} 片结构　总长 {self.metrics.total_length_mm:.1f} mm　预测束腰 {self.metrics.predicted_waist_um:.2f} μm　目标 {self.metrics.target_waist_um:.2f} μm",
        )


class TeachingDesignPage(QWidget):
    workbenchRequested = Signal(dict)
    progressChanged = Signal(str, int)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.state = DesignState(wavelength_nm=self._project_wavelength()).normalized()
        self.metrics = evaluate_design(self.state)
        self.current_step = 0
        self.saved_candidates: list[tuple[DesignState, DesignMetrics]] = []
        self._updating = False
        self.optimization_round = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.semi_button = SecondaryButton("半自由设计")
        self.free_button = SecondaryButton("自由设计")
        self.semi_button.setCheckable(True)
        self.free_button.setCheckable(True)
        self.semi_button.clicked.connect(self._activate_semi_mode)
        self.free_button.clicked.connect(self._activate_free_mode)
        self.mode_group.addButton(self.semi_button, 0)
        self.mode_group.addButton(self.free_button, 1)
        mode_row.addWidget(self.semi_button)
        mode_row.addWidget(self.free_button)
        mode_row.addSpacing(12)
        mode_row.addWidget(QLabel("透镜数量"))
        self.count_group = QButtonGroup(self)
        self.count_group.setExclusive(True)
        self.count_buttons: list[QPushButton] = []
        for count in range(1, 5):
            button = SecondaryButton(f"{count} 片")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, n=count: self.set_lens_count(n))
            self.count_group.addButton(button, count)
            self.count_buttons.append(button)
            mode_row.addWidget(button)
        mode_row.addStretch(1)
        self.mode_badge = Badge("半自由：有限候选池与阶段提示", "info")
        mode_row.addWidget(self.mode_badge)
        root.addLayout(mode_row)

        metrics_row = QHBoxLayout()
        self.system_metric = InlineMetric("系统效率", "—", "%")
        self.receiver_metric = InlineMetric("接收效率", "—", "%")
        self.total_metric = InlineMetric("总效率", "—", "%")
        self.feasible_metric = InlineMetric("工程可实现性", "—")
        metrics_row.addWidget(self.system_metric)
        metrics_row.addWidget(self.receiver_metric)
        metrics_row.addWidget(self.total_metric)
        metrics_row.addWidget(self.feasible_metric)
        root.addLayout(metrics_row)

        self.design_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.design_splitter.setChildrenCollapsible(False)
        self.design_splitter.setHandleWidth(7)

        self.steps_card = Card("设计决策链", compact=True)
        self.steps_card.setMinimumWidth(230)
        self.steps_card.setMaximumWidth(285)
        self.step_group = QButtonGroup(self)
        self.step_group.setExclusive(True)
        self.step_buttons: list[QPushButton] = []
        for index, title in enumerate(STEP_TITLES):
            button = SecondaryButton(f"{index + 1}. {title}")
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda checked=False, row=index: self.set_step(row))
            self.step_group.addButton(button, index)
            self.step_buttons.append(button)
            self.steps_card.body.addWidget(button)
        self.steps_card.body.addStretch(1)
        self.saved_label = QLabel("已保存候选：0")
        self.saved_label.setObjectName("helperText")
        self.steps_card.body.addWidget(self.saved_label)
        self.design_splitter.addWidget(self.steps_card)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(7)
        canvas_card = Card("当前结构与光束状态", compact=True)
        self.canvas = LensDesignCanvas()
        canvas_card.body.addWidget(self.canvas, 1)
        center_layout.addWidget(canvas_card, 1)
        self.stage_stack = QStackedWidget()
        self.stage_stack.addWidget(self._build_target_panel())
        self.stage_stack.addWidget(self._build_efficiency_panel())
        self.stage_stack.addWidget(self._build_roles_panel())
        self.stage_stack.addWidget(self._build_candidates_panel())
        self.stage_stack.addWidget(self._build_paraxial_panel())
        self.stage_stack.addWidget(self._build_direction_panel())
        self.stage_stack.addWidget(self._build_optimization_panel())
        self.stage_stack.addWidget(self._build_verification_panel())
        center_layout.addWidget(self.stage_stack)
        self.design_splitter.addWidget(center)

        self.evidence_card = Card("设计判断与证据", compact=True)
        self.evidence_card.setMinimumWidth(290)
        self.evidence_card.setMaximumWidth(370)
        self.bottleneck_badge = Badge("", "info")
        self.evidence_card.body.addWidget(self.bottleneck_badge)
        self.evidence_label = QLabel()
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.evidence_card.body.addWidget(self.evidence_label)
        self.recommendation_label = QLabel()
        self.recommendation_label.setWordWrap(True)
        self.recommendation_label.setObjectName("helperText")
        self.evidence_card.body.addWidget(self.recommendation_label)
        self.evidence_card.body.addStretch(1)
        warning = QLabel("高效率不是唯一目标：负空气厚度、镜片重叠、极长传播和孔径不足都必须淘汰。")
        warning.setWordWrap(True)
        warning.setObjectName("helperText")
        self.evidence_card.body.addWidget(warning)
        self.design_splitter.addWidget(self.evidence_card)

        self.design_splitter.setStretchFactor(0, 0)
        self.design_splitter.setStretchFactor(1, 1)
        self.design_splitter.setStretchFactor(2, 0)
        self.design_splitter.setSizes([255, 820, 340])
        root.addWidget(self.design_splitter, 1)

        actions = QHBoxLayout()
        reset = SecondaryButton("恢复课程初始方案")
        reset.clicked.connect(self.reset_design)
        previous = SecondaryButton("上一步")
        previous.clicked.connect(lambda: self.set_step(self.current_step - 1))
        next_button = PrimaryButton("下一步")
        next_button.clicked.connect(lambda: self.set_step(self.current_step + 1))
        save = SecondaryButton("保存候选方案")
        save.clicked.connect(self.save_candidate)
        workbench = PrimaryButton("进入工作台正式验证")
        workbench.clicked.connect(self._request_workbench)
        actions.addWidget(reset)
        actions.addWidget(previous)
        actions.addWidget(next_button)
        actions.addStretch(1)
        actions.addWidget(save)
        actions.addWidget(workbench)
        root.addLayout(actions)

        self.semi_button.setChecked(True)
        self.count_buttons[1].setChecked(True)
        self._sync_all_controls()
        self.set_step(0)
        self.refresh()

    def _project_wavelength(self) -> float:
        try:
            return float(getattr(self.context.project.project, "wavelength_nm", 808.0))
        except Exception:
            return 808.0

    
    def _scroll_card(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(230)
        card = Card(title, compact=True)
        scroll.setWidget(card)
        return scroll, card.body

    def _build_target_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段1：定义目标模式与工程约束")
        form = QFormLayout()
        self.wavelength = self._spin(200, 2200, 1, " nm", 0)
        self.source_na = self._spin(0.01, 0.60, 0.01, "", 3)
        self.receiver_na = self._spin(0.01, 0.60, 0.01, "", 3)
        self.receiver_mfd = self._spin(1.0, 30.0, 0.1, " μm", 2)
        self.max_length = self._spin(10.0, 200.0, 1.0, " mm", 1)
        self.min_gap = self._spin(0.0, 10.0, 0.1, " mm", 2)
        self.target_efficiency = self._spin(10.0, 99.9, 1.0, " %", 1)
        for control in (self.wavelength, self.source_na, self.receiver_na, self.receiver_mfd, self.max_length, self.min_gap, self.target_efficiency):
            control.valueChanged.connect(self._target_changed)
        form.addRow("波长", self.wavelength)
        form.addRow("源光纤 NA", self.source_na)
        form.addRow("接收光纤 NA", self.receiver_na)
        form.addRow("接收光纤 MFD", self.receiver_mfd)
        form.addRow("最大系统长度", self.max_length)
        form.addRow("最小空气间隔", self.min_gap)
        form.addRow("目标总效率", self.target_efficiency)
        body.addLayout(form)
        return widget

    def _build_efficiency_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段2：判断系统效率还是接收效率限制结果")
        self.efficiency_explanation = QLabel()
        self.efficiency_explanation.setWordWrap(True)
        body.addWidget(self.efficiency_explanation)
        self.bottleneck_choice = QComboBox()
        self.bottleneck_choice.addItems(["系统通过能力", "接收模场匹配", "两者共同限制"])
        body.addWidget(self.bottleneck_choice)
        check = PrimaryButton("提交瓶颈判断")
        check.clicked.connect(self._check_bottleneck)
        body.addWidget(check, 0, Qt.AlignmentFlag.AlignRight)
        return widget

    def _build_roles_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段3：先分配功能，再选择型号")
        self.roles_label = QLabel()
        self.roles_label.setWordWrap(True)
        body.addWidget(self.roles_label)
        return widget

    def _build_candidates_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段4：建立短焦、中焦和长焦候选")
        self.lens_control_grid = QGridLayout()
        self.focal_combos: list[QComboBox] = []
        self.gap_spins: list[QDoubleSpinBox] = []
        for index in range(4):
            combo = QComboBox()
            for focal in FOCAL_POOL:
                combo.addItem(f"{focal:.0f} mm", focal)
            combo.currentIndexChanged.connect(lambda _idx, row=index: self._focal_changed(row))
            self.focal_combos.append(combo)
            self.lens_control_grid.addWidget(QLabel(f"L{index + 1} 焦距"), index, 0)
            self.lens_control_grid.addWidget(combo, index, 1)
        for index in range(5):
            spin = self._spin(-10.0, 60.0, 0.5, " mm", 2)
            spin.valueChanged.connect(lambda value, row=index: self._gap_changed(row, value))
            self.gap_spins.append(spin)
            self.lens_control_grid.addWidget(QLabel(f"d{index}" if index == 0 else f"间隔 {index}"), index, 2)
            self.lens_control_grid.addWidget(spin, index, 3)
        body.addLayout(self.lens_control_grid)
        return widget

    def _build_paraxial_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段5：近轴模型只负责筛掉明显不成立的组合")
        self.paraxial_result = QLabel("尚未筛选。")
        self.paraxial_result.setWordWrap(True)
        body.addWidget(self.paraxial_result)
        run = PrimaryButton("执行近轴筛选")
        run.clicked.connect(self.run_paraxial_screen)
        body.addWidget(run, 0, Qt.AlignmentFlag.AlignRight)
        return widget

    def _build_direction_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段6：逐片比较镜片正反方向")
        self.direction_grid = QGridLayout()
        self.direction_checks: list[QCheckBox] = []
        for index in range(4):
            box = QCheckBox(f"L{index + 1} 使用 Reverse Elements / 反向")
            box.toggled.connect(lambda checked, row=index: self._direction_changed(row, checked))
            self.direction_checks.append(box)
            self.direction_grid.addWidget(box, index // 2, index % 2)
        body.addLayout(self.direction_grid)
        note = QLabel("方向比较应同时检查 RMS 波前、焦点位置、效率和机械边界，而不是只看一个数值。")
        note.setWordWrap(True)
        note.setObjectName("helperText")
        body.addWidget(note)
        return widget

    def _build_optimization_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段7：按物理功能分轮开放变量")
        self.optimization_list = QListWidget()
        self.optimization_list.setMaximumHeight(105)
        body.addWidget(self.optimization_list)
        self.round_result = QLabel("尚未运行分轮优化。")
        self.round_result.setWordWrap(True)
        body.addWidget(self.round_result)
        run = PrimaryButton("执行下一轮教学优化")
        run.clicked.connect(self.run_optimization_round)
        body.addWidget(run, 0, Qt.AlignmentFlag.AlignRight)
        return widget

    def _build_verification_panel(self) -> QWidget:
        widget, body = self._scroll_card("阶段8：正式验证前的工程复核")
        self.verification_checks: list[QCheckBox] = []
        for text in ("所有空气间隔为正且满足最小值", "系统总长满足限制", "光束未超过候选镜片有效口径", "焦点未跑到搜索边界", "系统效率与接收效率均已检查", "已评估装调敏感性"):
            box = QCheckBox(text)
            self.verification_checks.append(box)
            body.addWidget(box)
        verify = PrimaryButton("完成教学复核")
        verify.clicked.connect(self.complete_verification)
        body.addWidget(verify, 0, Qt.AlignmentFlag.AlignRight)
        return widget

    @staticmethod
    def _spin(minimum: float, maximum: float, step: float, suffix: str, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setDecimals(decimals)
        spin.setKeyboardTracking(False)
        return spin

    
    def _activate_semi_mode(self, checked: bool = False) -> None:
        if checked or self.semi_button.isChecked():
            self.set_mode("semi")

    def _activate_free_mode(self, checked: bool = False) -> None:
        if checked or self.free_button.isChecked():
            self.set_mode("free")

    def set_mode(self, mode: str) -> None:
        self.state = replace(self.state, mode="free" if mode == "free" else "semi").normalized()
        self.semi_button.setChecked(self.state.mode == "semi")
        self.free_button.setChecked(self.state.mode == "free")
        self.mode_badge.setText("自由：自行选择镜片数量、焦距与优化顺序" if self.state.mode == "free" else "半自由：有限候选池与阶段提示")
        
        
        for combo in self.focal_combos:
            for index in range(combo.count()):
                focal = float(combo.itemData(index))
                combo.model().item(index).setEnabled(self.state.mode == "free" or focal <= 16.0)
        self.refresh()

    def set_lens_count(self, count: int) -> None:
        count = max(1, min(4, int(count)))
        self.state = replace(self.state, lens_count=count).normalized()
        self.count_buttons[count - 1].setChecked(True)
        self.optimization_round = 0
        self._update_visibility()
        self._update_roles()
        self._update_rounds()
        self.refresh()

    def set_step(self, index: int) -> None:
        index = max(0, min(int(index), len(STEP_TITLES) - 1))
        self.current_step = index
        self.step_buttons[index].setChecked(True)
        self.stage_stack.setCurrentIndex(index)
        self.canvas.active_lens = -1
        self.canvas.update()
        self.progressChanged.emit("design", round(index / (len(STEP_TITLES) - 1) * 70))

    def _target_changed(self) -> None:
        if self._updating:
            return
        self.state = replace(
            self.state,
            wavelength_nm=self.wavelength.value(),
            source_na=self.source_na.value(),
            receiver_na=self.receiver_na.value(),
            receiver_mfd_um=self.receiver_mfd.value(),
            max_length_mm=self.max_length.value(),
            min_gap_mm=self.min_gap.value(),
            target_total=self.target_efficiency.value() / 100.0,
        ).normalized()
        self.refresh()

    def _focal_changed(self, row: int) -> None:
        if self._updating:
            return
        values = list(self.state.focal_lengths_mm)
        values[row] = float(self.focal_combos[row].currentData())
        self.state = replace(self.state, focal_lengths_mm=tuple(values)).normalized()
        self.canvas.active_lens = row
        self.refresh()

    def _gap_changed(self, row: int, value: float) -> None:
        if self._updating:
            return
        values = list(self.state.gaps_mm)
        values[row] = float(value)
        self.state = replace(self.state, gaps_mm=tuple(values)).normalized()
        self.refresh()

    def _direction_changed(self, row: int, checked: bool) -> None:
        if self._updating:
            return
        values = list(self.state.reversed_flags)
        values[row] = bool(checked)
        self.state = replace(self.state, reversed_flags=tuple(values)).normalized()
        self.canvas.active_lens = row
        self.refresh()

    def refresh(self) -> None:
        self.metrics = evaluate_design(self.state)
        m = self.metrics
        self.system_metric.set_value(f"{m.system_efficiency * 100:.1f}")
        self.receiver_metric.set_value(f"{m.receiver_efficiency * 100:.1f}")
        self.total_metric.set_value(f"{m.total_efficiency * 100:.1f}")
        self.feasible_metric.set_value("通过" if m.feasible else "不通过")
        self.bottleneck_badge.setText(f"当前瓶颈：{m.main_bottleneck}")
        self.evidence_label.setText("\n".join(f"• {item}" for item in m.evidence))
        self.recommendation_label.setText("建议：" + m.recommendation)
        self.efficiency_explanation.setText(
            f"系统效率 ηsystem = {m.system_efficiency:.4f}\n"
            f"接收效率 ηreceiver = {m.receiver_efficiency:.4f}\n"
            f"总效率 ηtotal = ηsystem × ηreceiver = {m.total_efficiency:.4f}\n\n"
            "系统效率低时优先检查孔径、间隔、总长和透过；接收效率低时优先检查束腰、位置、角度和波前。"
        )
        self.canvas.set_state(self.state, m, self.canvas.active_lens)
        self._update_visibility()
        if hasattr(self, "paraxial_result") and self.current_step == 4:
            pass

    def _sync_all_controls(self) -> None:
        self._updating = True
        s = self.state
        self.wavelength.setValue(s.wavelength_nm)
        self.source_na.setValue(s.source_na)
        self.receiver_na.setValue(s.receiver_na)
        self.receiver_mfd.setValue(s.receiver_mfd_um)
        self.max_length.setValue(s.max_length_mm)
        self.min_gap.setValue(s.min_gap_mm)
        self.target_efficiency.setValue(s.target_total * 100.0)
        for index, combo in enumerate(self.focal_combos):
            wanted = min(range(combo.count()), key=lambda row: abs(float(combo.itemData(row)) - s.focal_lengths_mm[index]))
            combo.setCurrentIndex(wanted)
        for index, spin in enumerate(self.gap_spins):
            spin.setValue(s.gaps_mm[index])
        for index, box in enumerate(self.direction_checks):
            box.setChecked(s.reversed_flags[index])
        self._updating = False
        self._update_visibility()
        self._update_roles()
        self._update_rounds()

    def _update_visibility(self) -> None:
        count = self.state.lens_count
        for index, combo in enumerate(self.focal_combos):
            visible = index < count
            combo.setVisible(visible)
            label = self.lens_control_grid.itemAtPosition(index, 0).widget()
            label.setVisible(visible)
        for index, spin in enumerate(self.gap_spins):
            visible = index <= count
            spin.setVisible(visible)
            label = self.lens_control_grid.itemAtPosition(index, 2).widget()
            label.setVisible(visible)
        for index, box in enumerate(self.direction_checks):
            box.setVisible(index < count)

    def _update_roles(self) -> None:
        roles_by_count = {
            1: ["L1：直接聚焦，理解焦距、工作距离和单片结构上限。"],
            2: ["L1：接收源端发散光并初步准直。", "L2：聚焦并决定接收端束腰和 NA。"],
            3: ["L1：源端接收与准直。", "L2：控制中间束径和波前曲率。", "L3：完成末级聚焦与模场匹配。"],
            4: ["L1：源端接收、初步准直和入口孔径控制。", "L2：控制中间光束尺寸和波前。", "L3：调整模式倍率并补偿高阶误差。", "L4：决定最终束腰、工作距离和接收 NA。"],
        }
        self.roles_label.setText("\n\n".join(roles_by_count[self.state.lens_count]))

    def _update_rounds(self) -> None:
        count = self.state.lens_count
        rounds = {
            1: ["第1轮：只优化最终焦面 d1", "第2轮：比较焦距与工作距离"],
            2: ["第1轮：只优化最终焦面 d2", "第2轮：开放 d12、d2", "第3轮：最后微调源端距离 d0"],
            3: ["第1轮：最终焦面 d3", "第2轮：末级整形 d23、d3", "第3轮：前端间距 d12", "第4轮：源端距离 d0"],
            4: ["第1轮：最终焦面 d4", "第2轮：末级整形 d34、d4", "第3轮：中间波前 d23、d34、d4", "第4轮：前端间距 d12", "第5轮：源端距离 d0"],
        }[count]
        self.optimization_list.clear()
        self.optimization_list.addItems(rounds)
        self.optimization_round = min(self.optimization_round, len(rounds))

    def _check_bottleneck(self) -> None:
        choice = self.bottleneck_choice.currentText()
        expected = self.metrics.main_bottleneck
        correct = choice == expected or (choice == "两者共同限制" and abs(self.metrics.system_efficiency - self.metrics.receiver_efficiency) < 0.05)
        QMessageBox.information(self, "瓶颈判断", "判断正确。" if correct else f"当前更主要的限制来自：{expected}。")

    def run_paraxial_screen(self) -> None:
        m = self.metrics
        reasons = []
        if m.total_length_mm > self.state.max_length_mm:
            reasons.append("系统总长超限")
        if min(self.state.gaps_mm[: self.state.lens_count + 1]) < self.state.min_gap_mm:
            reasons.append("存在负值或过小空气间隔")
        if m.max_beam_radius_mm > 2.6:
            reasons.append("光束超过预设候选镜片口径余量")
        if m.predicted_waist_um / max(m.target_waist_um, 1e-9) > 2.5 or m.predicted_waist_um / max(m.target_waist_um, 1e-9) < 0.4:
            reasons.append("预测束腰偏离目标过大")
        if reasons:
            self.paraxial_result.setText("近轴筛选：淘汰当前组合。\n• " + "\n• ".join(reasons) + "\n近轴筛选只判断结构是否基本成立，不能代表最终高耦合效率。")
        else:
            self.paraxial_result.setText("近轴筛选：当前组合基本成立，可继续导入镜片处方并进行复场验证。\n注意：通过筛选不等于已经获得最高耦合效率。")

    def run_optimization_round(self) -> None:
        rounds = self.optimization_list.count()
        if self.optimization_round >= rounds:
            self.round_result.setText("所有教学优化轮次已完成。请进入正式验证并检查结果稳定性。")
            return
        before = self.metrics.total_efficiency
        count = self.state.lens_count
        gaps = list(self.state.gaps_mm)
        focals = list(self.state.focal_lengths_mm)
        round_index = self.optimization_round
        if round_index == 0:
            
            
            gaps[count] = max(self.state.min_gap_mm, min(gaps[count], 5.0 + 0.8 * count))
        elif round_index == 1 and count >= 2:
            gaps[count - 1] = max(self.state.min_gap_mm, gaps[count - 1] * 0.82)
            gaps[count] = max(self.state.min_gap_mm, gaps[count] * 0.90)
        elif round_index == 2 and count >= 3:
            gaps[count - 2] = max(self.state.min_gap_mm, gaps[count - 2] * 0.88)
            target = self.metrics.target_waist_um
            best = min(FOCAL_POOL, key=lambda f: abs((self.state.wavelength_nm * 1e-6 * f / (math.pi * 0.72)) * 1000.0 - target))
            focals[count - 1] = best
        elif round_index == 3:
            gaps[1] = max(self.state.min_gap_mm, gaps[1] * 0.92)
        else:
            gaps[0] = max(self.state.min_gap_mm, gaps[0] * 0.94)
        self.state = replace(self.state, gaps_mm=tuple(gaps), focal_lengths_mm=tuple(focals)).normalized()
        self.optimization_round += 1
        self._sync_all_controls()
        self.refresh()
        after = self.metrics.total_efficiency
        self.optimization_list.setCurrentRow(self.optimization_round - 1)
        self.round_result.setText(
            f"第 {self.optimization_round} 轮完成：总效率 {before * 100:.1f}% → {after * 100:.1f}%。\n"
            "每轮只开放一组有明确物理功能的变量，便于判断改善来自哪里。"
        )

    def complete_verification(self) -> None:
        checked = sum(box.isChecked() for box in self.verification_checks)
        score = round(checked / len(self.verification_checks) * 40 + min(40, self.metrics.total_efficiency * 40) + (20 if self.metrics.feasible else 0))
        self.progressChanged.emit("design", max(70, score))
        QMessageBox.information(
            self,
            "设计复核",
            f"复核项目：{checked}/{len(self.verification_checks)}\n"
            f"当前总效率：{self.metrics.total_efficiency * 100:.1f}%\n"
            f"工程可实现性：{'通过' if self.metrics.feasible else '不通过'}\n"
            f"教学评价：{score} 分",
        )

    def save_candidate(self) -> None:
        self.saved_candidates.append((self.state, self.metrics))
        self.saved_label.setText(f"已保存候选：{len(self.saved_candidates)}")
        QMessageBox.information(self, "候选方案", f"已保存当前 {self.state.lens_count} 片方案，总效率 {self.metrics.total_efficiency * 100:.1f}%。")

    def reset_design(self) -> None:
        mode = self.state.mode
        self.state = DesignState(mode=mode, wavelength_nm=self._project_wavelength()).normalized()
        self.optimization_round = 0
        self._sync_all_controls()
        self.set_lens_count(2)
        self.set_step(0)
        self.refresh()

    def current_profile(self) -> dict:
        s = self.state.normalized()
        return {
            "source": "teaching_design",
            "mode": s.mode,
            "lens_count": s.lens_count,
            "wavelength_nm": s.wavelength_nm,
            "source_na": s.source_na,
            "receiver_na": s.receiver_na,
            "receiver_mfd_um": s.receiver_mfd_um,
            "max_length_mm": s.max_length_mm,
            "min_gap_mm": s.min_gap_mm,
            "target_total_efficiency": s.target_total,
            "focal_lengths_mm": list(s.focal_lengths_mm[: s.lens_count]),
            "air_gaps_mm": list(s.gaps_mm[: s.lens_count + 1]),
            "reversed_flags": list(s.reversed_flags[: s.lens_count]),
            "teaching_metrics": {
                "system_efficiency": self.metrics.system_efficiency,
                "receiver_efficiency": self.metrics.receiver_efficiency,
                "total_efficiency": self.metrics.total_efficiency,
                "feasible": self.metrics.feasible,
            },
        }

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        if not hasattr(self, "design_splitter") or not hasattr(self, "steps_card"):
            return
        width = max(1, self.width())
        compact = width < 1250
        self.steps_card.setVisible(not compact)
        if compact:
            self.design_splitter.setSizes([0, max(650, width - 330), 300])
        else:
            self.design_splitter.setSizes([255, max(720, width - 650), 340])

    def _request_workbench(self) -> None:
        self.workbenchRequested.emit(self.current_profile())


__all__ = ["DesignMetrics", "DesignState", "TeachingDesignPage", "evaluate_design"]
