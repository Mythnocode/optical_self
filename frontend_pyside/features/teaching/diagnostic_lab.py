
from __future__ import annotations

from dataclasses import replace
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.components.basic import Badge, Card, PrimaryButton, SecondaryButton
from .teaching_scene_model import (
    SEMI_FREE_PRESETS,
    TeachingOpticalMetrics,
    TeachingOpticalState,
    apply_preset,
    evaluate_teaching_state,
    random_free_fault,
)
from .teaching_scene_views import SceneInstrument, TeachingOpticalScene3D, TeachingOverview2D


INSTRUMENTS: tuple[tuple[str, str, str], ...] = (
    ("input_power", "输入功率计", "先判断光源和主路功率是否稳定。"),
    ("output_power", "输出功率计", "读取总耦合效率，寻找装调峰值。"),
    ("beam_analyzer", "光束分析仪", "观察光斑中心、半径与椭圆率。"),
    ("shack_hartmann", "波前传感器", "观察波前倾斜、离焦和曲率趋势。"),
    ("mach_zehnder", "离轴干涉仪", "通过干涉条纹理解相位与曲率。"),
)
INSTRUMENT_KEYS = {item[0] for item in INSTRUMENTS}


class MeasurementPreview(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.key = "output_power"
        self.state = TeachingOpticalState()
        self.metrics = evaluate_teaching_state(self.state)

    def set_data(self, key: str, state: TeachingOpticalState, metrics: TeachingOpticalMetrics) -> None:
        self.key = str(key)
        self.state = state
        self.metrics = metrics
        self.update()

    def paintEvent(self, event) -> None:  
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))
        area = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        painter.setPen(QPen(QColor("#d7e4ed"), 1))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(area, 8, 8)
        if self.key in {"input_power", "output_power"}:
            self._draw_power(painter, area)
        elif self.key == "beam_analyzer":
            self._draw_beam(painter, area)
        elif self.key == "shack_hartmann":
            self._draw_wavefront(painter, area)
        elif self.key == "mach_zehnder":
            self._draw_fringe(painter, area)
        elif self.key == "lens":
            self._draw_focus(painter, area)
        else:
            self._draw_fiber(painter, area)

    def _draw_power(self, painter: QPainter, area: QRectF) -> None:
        if self.key == "input_power":
            value = self.state.input_power_mw
            maximum = max(120.0, value * 1.15)
            title = "输入功率"
        else:
            value = self.metrics.output_power_mw
            maximum = max(100.0, self.state.input_power_mw)
            title = "输出功率"
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(12, 10, -12, -10), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, title)
        track = area.adjusted(28, 65, -28, -72)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e5edf3"))
        painter.drawRoundedRect(track, 8, 8)
        fraction = max(0.0, min(1.0, value / maximum))
        fill = QRectF(track.left(), track.top(), track.width() * fraction, track.height())
        painter.setBrush(QColor("#3b9fd8"))
        painter.drawRoundedRect(fill, 8, 8)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(12, 0, -12, -24), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, f"{value:.3f} mW")

    def _draw_beam(self, painter: QPainter, area: QRectF) -> None:
        center = area.center()
        target_r = min(area.width(), area.height()) * 0.25
        dx = self.state.offset_x_um * target_r / max(self.state.fiber_mode_radius_um * 1.8, 1e-9)
        dy = -self.state.offset_y_um * target_r / max(self.state.fiber_mode_radius_um * 1.8, 1e-9)
        beam_r = target_r * self.metrics.beam_radius_at_fiber_um / max(self.state.fiber_mode_radius_um, 1e-9)
        beam_r = max(target_r * 0.35, min(target_r * 1.9, beam_r))
        painter.setBrush(QColor(47, 128, 201, 40))
        painter.setPen(QPen(QColor(theme.PRIMARY), 2))
        painter.drawEllipse(center, target_r, target_r)
        incident = QPointF(center.x() + dx, center.y() + dy)
        gradient = QRadialGradient(incident, beam_r)
        gradient.setColorAt(0.0, QColor(255, 225, 61, 220))
        gradient.setColorAt(0.35, QColor(239, 91, 91, 150))
        gradient.setColorAt(1.0, QColor(239, 91, 91, 15))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(theme.ERROR), 2))
        painter.drawEllipse(incident, beam_r, beam_r)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "蓝：光纤模场　红：端面光斑")
        painter.drawText(area.adjusted(10, 0, -10, -14), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, f"中心偏移 {math.hypot(self.state.offset_x_um, self.state.offset_y_um):.2f} μm　端面半径 {self.metrics.beam_radius_at_fiber_um:.2f} μm")

    def _draw_wavefront(self, painter: QPainter, area: QRectF) -> None:
        rows, cols = 7, 9
        painter.setPen(QPen(QColor("#bdd0dd"), 1))
        painter.setBrush(QColor("#1f78b4"))
        tilt_x = self.state.yaw_mrad * 0.16
        tilt_y = self.state.pitch_mrad * 0.16
        curvature = self.state.curvature_waves * 14.0 + self.state.offset_z_um / max(self.metrics.rayleigh_range_um, 1e-9) * 5.0
        for row in range(rows):
            for col in range(cols):
                nx = (col - (cols - 1) / 2) / max((cols - 1) / 2, 1)
                ny = (row - (rows - 1) / 2) / max((rows - 1) / 2, 1)
                x = area.left() + 28 + col * (area.width() - 56) / max(cols - 1, 1)
                y = area.top() + 34 + row * (area.height() - 76) / max(rows - 1, 1)
                dx = tilt_x * nx + curvature * nx * (nx * nx + ny * ny)
                dy = -tilt_y * ny + curvature * ny * (nx * nx + ny * ny)
                painter.drawEllipse(QPointF(x + dx, y + dy), 3.2, 3.2)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "简化 Shack–Hartmann 焦点阵列")
        painter.drawText(area.adjusted(10, 0, -10, -12), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, f"Pitch {self.state.pitch_mrad:+.1f} mrad　Yaw {self.state.yaw_mrad:+.1f} mrad　曲率 {self.state.curvature_waves:+.2f} waves")

    def _draw_fringe(self, painter: QPainter, area: QRectF) -> None:
        clip = area.adjusted(16, 25, -16, -34)
        painter.save()
        painter.setClipRect(clip)
        phase = self.state.curvature_waves * 2.0 + self.state.offset_z_um / max(self.metrics.rayleigh_range_um, 1e-9)
        tilt = (self.state.pitch_mrad + self.state.yaw_mrad) * 0.02
        for index in range(22):
            x = clip.left() + index * clip.width() / 22
            offset = 13.0 * math.sin(index * 0.48 + phase) + tilt * index
            color = QColor("#1d4ed8") if index % 2 == 0 else QColor("#dbeafe")
            painter.setPen(QPen(color, max(3.0, clip.width() / 29)))
            painter.drawLine(QPointF(x, clip.top() - 25 + offset), QPointF(x + 38, clip.bottom() + 25 + offset))
        painter.restore()
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "离轴干涉条纹：观察倾斜与弯曲")
        painter.drawText(area.adjusted(10, 0, -10, -12), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "条纹倾斜对应角度误差，弯曲对应离焦或曲率失配")

    def _draw_focus(self, painter: QPainter, area: QRectF) -> None:
        axis_y = area.center().y()
        left = area.left() + 25
        right = area.right() - 25
        lens_x = area.left() + area.width() * 0.34
        waist_x = area.left() + area.width() * 0.68
        fiber_x = waist_x + self.state.offset_z_um / 120.0 * area.width() * 0.22
        painter.setPen(QPen(QColor("#8599aa"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))
        painter.setPen(QPen(QColor(theme.PRIMARY), 2))
        for offset in (-44, -22, 0, 22, 44):
            painter.drawLine(QPointF(left, axis_y + offset), QPointF(lens_x, axis_y + offset))
            painter.drawLine(QPointF(lens_x, axis_y + offset), QPointF(waist_x, axis_y))
        painter.setBrush(QColor(130, 205, 238, 120))
        painter.drawEllipse(QRectF(lens_x - 10, axis_y - 62, 20, 124))
        painter.setPen(QPen(QColor(theme.SUCCESS), 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(waist_x, axis_y - 46), QPointF(waist_x, axis_y + 46))
        painter.setPen(QPen(QColor(theme.ERROR), 3))
        painter.drawLine(QPointF(fiber_x, axis_y - 58), QPointF(fiber_x, axis_y + 58))
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "聚焦镜组、最佳束腰与光纤端面的相对位置")

    def _draw_fiber(self, painter: QPainter, area: QRectF) -> None:
        center = area.center()
        painter.setPen(QPen(QColor("#8599aa"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(area.left() + 30, center.y()), QPointF(area.right() - 30, center.y()))
        painter.setPen(QPen(QColor(theme.PRIMARY), 3))
        painter.drawLine(QPointF(center.x(), area.top() + 30), QPointF(center.x(), area.bottom() - 30))
        painter.setBrush(QColor(47, 128, 201, 45))
        painter.drawEllipse(center, 48, 48)
        incident = QPointF(center.x() + self.state.offset_x_um * 6, center.y() - self.state.offset_y_um * 6)
        painter.setPen(QPen(QColor(theme.ERROR), 2))
        painter.setBrush(QColor(239, 91, 91, 45))
        painter.drawEllipse(incident, 38, 38)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "光纤端面局部状态")


class TeachingDiagnosticPage(QWidget):
    sectionRequested = Signal(str)
    progressChanged = Signal(str, int)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.mode = "semi"
        self.category = "position"
        self.state = TeachingOpticalState(wavelength_nm=self._project_wavelength())
        self.initial_state = self.state
        self.metrics = evaluate_teaching_state(self.state)
        self.best_state = self.state
        self.best_efficiency = self.metrics.total_efficiency
        self.history: list[TeachingOpticalState] = []
        self.used_instruments: set[str] = set()
        self.task_counter = 0
        self._updating_controls = False
        self.selected_object = "output_power"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        task_card = Card("实验任务", compact=True)
        task_top = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.semi_button = SecondaryButton("半自由实验")
        self.free_button = SecondaryButton("自由实验")
        self.semi_button.setCheckable(True)
        self.free_button.setCheckable(True)
        self.semi_button.clicked.connect(self._activate_semi_mode)
        self.free_button.clicked.connect(self._activate_free_mode)
        self.mode_group.addButton(self.semi_button, 0)
        self.mode_group.addButton(self.free_button, 1)
        task_top.addWidget(self.semi_button)
        task_top.addWidget(self.free_button)
        self.category_combo = QComboBox()
        self.category_combo.addItem("位置类失配", "position")
        self.category_combo.addItem("方向类失配", "direction")
        self.category_combo.addItem("光束形状失配", "shape")
        self.category_combo.addItem("五轴综合入门", "five_axis")
        self.category_combo.currentIndexChanged.connect(self._category_changed)
        task_top.addWidget(self.category_combo)
        new_task = PrimaryButton("生成新任务")
        new_task.clicked.connect(self.new_task)
        task_top.addWidget(new_task)
        task_top.addStretch(1)
        self.mode_badge = Badge("半自由：故障范围已知", "info")
        task_top.addWidget(self.mode_badge)
        task_card.body.addLayout(task_top)
        self.task_label = QLabel()
        self.task_label.setWordWrap(True)
        task_card.body.addWidget(self.task_label)
        root.addWidget(task_card)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(7)

        self.instrument_card = Card("固定仪器与测量选择", compact=True)
        self.instrument_card.setMinimumWidth(215)
        self.instrument_card.setMaximumWidth(270)
        note = QLabel("元件和仪器位置已经摆好。自由度来自测量顺序、证据选择与装调策略。")
        note.setObjectName("helperText")
        note.setWordWrap(True)
        self.instrument_card.body.addWidget(note)
        self.instrument_group = QButtonGroup(self)
        self.instrument_group.setExclusive(True)
        self.instrument_buttons: dict[str, QPushButton] = {}
        for index, (key, name, hint) in enumerate(INSTRUMENTS):
            button = SecondaryButton(name)
            button.setCheckable(True)
            button.setToolTip(hint)
            button.clicked.connect(lambda checked=False, k=key: self.select_object(k))
            self.instrument_group.addButton(button, index)
            self.instrument_buttons[key] = button
            self.instrument_card.body.addWidget(button)
        self.instrument_card.body.addStretch(1)
        self.measurement_count = QLabel("已使用仪器：0/5")
        self.measurement_count.setObjectName("helperText")
        self.instrument_card.body.addWidget(self.measurement_count)
        self.main_splitter.addWidget(self.instrument_card)

        scene_card = Card("固定实验平台", compact=True)
        scene_top = QHBoxLayout()
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_2d_button = SecondaryButton("2D实验光路")
        self.view_3d_button = SecondaryButton("3D空间装调")
        self.view_2d_button.setCheckable(True)
        self.view_3d_button.setCheckable(True)
        self.view_2d_button.clicked.connect(lambda: self.set_scene_view(0))
        self.view_3d_button.clicked.connect(lambda: self.set_scene_view(1))
        self.view_group.addButton(self.view_2d_button, 0)
        self.view_group.addButton(self.view_3d_button, 1)
        scene_top.addWidget(self.view_2d_button)
        scene_top.addWidget(self.view_3d_button)
        scene_top.addStretch(1)
        self.camera_combo = QComboBox()
        self.camera_combo.addItem("等轴视图", "isometric")
        self.camera_combo.addItem("俯视图", "top")
        self.camera_combo.addItem("正视图", "front")
        self.camera_combo.addItem("沿光轴观察", "axis")
        self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        scene_top.addWidget(self.camera_combo)
        focus_button = SecondaryButton("聚焦选中元件")
        focus_button.clicked.connect(self._focus_selected)
        scene_top.addWidget(focus_button)
        scene_card.body.addLayout(scene_top)
        self.scene_stack = QStackedWidget()
        self.scene_2d = TeachingOverview2D()
        self.scene_3d = TeachingOpticalScene3D()
        instruments = [SceneInstrument(key, name.replace("仪", "").replace("计", "")) for key, name, _hint in INSTRUMENTS]
        self.scene_2d.set_instruments(instruments)
        self.scene_3d.set_instruments(instruments)
        self.scene_2d.objectActivated.connect(self.select_object)
        self.scene_3d.objectActivated.connect(self.select_object)
        self.scene_stack.addWidget(self.scene_2d)
        self.scene_stack.addWidget(self.scene_3d)
        scene_card.body.addWidget(self.scene_stack, 1)
        self.main_splitter.addWidget(scene_card)

        result_card = Card("测量结果与实验记录", compact=True)
        result_card.setMinimumWidth(315)
        result_card.setMaximumWidth(390)
        self.selected_label = QLabel("输出功率计")
        self.selected_label.setObjectName("cardTitle")
        result_card.body.addWidget(self.selected_label)
        self.preview = MeasurementPreview()
        result_card.body.addWidget(self.preview, 1)
        self.readout = QLabel()
        self.readout.setWordWrap(True)
        self.readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        result_card.body.addWidget(self.readout)
        self.efficiency_bar = QProgressBar()
        self.efficiency_bar.setRange(0, 1000)
        result_card.body.addWidget(self.efficiency_bar)
        self.best_label = QLabel()
        self.best_label.setObjectName("helperText")
        result_card.body.addWidget(self.best_label)
        self.main_splitter.addWidget(result_card)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([235, 780, 350])
        root.addWidget(self.main_splitter, 1)

        control_card = Card("装调自由度与实验决策", compact=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.controls: dict[str, QDoubleSpinBox] = {}
        specs = (
            ("offset_x_um", "X 横向", -8.0, 8.0, 0.1, " μm"),
            ("offset_y_um", "Y 横向", -8.0, 8.0, 0.1, " μm"),
            ("offset_z_um", "Z 轴离焦", -150.0, 150.0, 1.0, " μm"),
            ("pitch_mrad", "Pitch", -60.0, 60.0, 0.5, " mrad"),
            ("yaw_mrad", "Yaw", -60.0, 60.0, 0.5, " mrad"),
            ("input_beam_radius_mm", "入射束半径", 0.25, 1.35, 0.01, " mm"),
            ("curvature_waves", "边缘相位差", -0.75, 0.75, 0.01, " waves"),
        )
        for index, (key, label, minimum, maximum, step, suffix) in enumerate(specs):
            text = QLabel(label)
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(2 if step < 0.1 else 1)
            spin.setSuffix(suffix)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value, k=key: self._control_changed(k, value))
            self.controls[key] = spin
            row = index // 4
            col = (index % 4) * 2
            grid.addWidget(text, row, col)
            grid.addWidget(spin, row, col + 1)
        control_card.body.addLayout(grid)

        actions = QHBoxLayout()
        undo = SecondaryButton("撤销上一步")
        undo.clicked.connect(self.undo)
        restore = SecondaryButton("恢复初始故障")
        restore.clicked.connect(self.restore_initial)
        save_best = SecondaryButton("保存当前最好状态")
        save_best.clicked.connect(self.save_best)
        self.diagnosis_combo = QComboBox()
        self.diagnosis_combo.addItems(["位置失配", "轴向离焦", "角度失配", "尺寸失配", "曲率失配"])
        submit = PrimaryButton("提交诊断")
        submit.clicked.connect(self.submit_diagnosis)
        next_section = SecondaryButton("进入系统设计")
        next_section.clicked.connect(lambda: self.sectionRequested.emit("design"))
        actions.addWidget(undo)
        actions.addWidget(restore)
        actions.addWidget(save_best)
        actions.addStretch(1)
        actions.addWidget(QLabel("主导原因判断"))
        actions.addWidget(self.diagnosis_combo)
        actions.addWidget(submit)
        actions.addWidget(next_section)
        control_card.body.addLayout(actions)
        root.addWidget(control_card)

        self.semi_button.setChecked(True)
        self.view_2d_button.setChecked(True)
        self.new_task()
        self.select_object("output_power")

    def _project_wavelength(self) -> float:
        try:
            return float(getattr(self.context.project.project, "wavelength_nm", 808.0))
        except Exception:
            return 808.0

    def _activate_semi_mode(self, checked: bool = False) -> None:
        if checked or self.semi_button.isChecked():
            self.set_mode("semi")

    def _activate_free_mode(self, checked: bool = False) -> None:
        if checked or self.free_button.isChecked():
            self.set_mode("free")

    def set_mode(self, mode: str) -> None:
        self.mode = "free" if mode == "free" else "semi"
        self.semi_button.setChecked(self.mode == "semi")
        self.free_button.setChecked(self.mode == "free")
        self.category_combo.setVisible(self.mode == "semi")
        self.mode_badge.setText("自由：未知复合失配" if self.mode == "free" else "半自由：故障范围已知")
        self.mode_badge.setProperty("status", "warning" if self.mode == "free" else "info")
        self.new_task()

    def _category_changed(self) -> None:
        self.category = str(self.category_combo.currentData() or "position")
        if self.mode == "semi":
            self.new_task()

    def new_task(self) -> None:
        self.task_counter += 1
        self.category = str(self.category_combo.currentData() or "position")
        base = TeachingOpticalState(wavelength_nm=self._project_wavelength())
        if self.mode == "free":
            self.state = random_free_fault(base, seed=20260729 + self.task_counter)
            task = "当前系统含有 2—4 项未知复合失配。请自行选择测量证据、判断主导原因，并将总效率提升到 85% 以上。"
        else:
            self.state = apply_preset(base, self.category)
            task = str(SEMI_FREE_PRESETS[self.category]["task"])
        self.initial_state = self.state
        self.history.clear()
        self.used_instruments.clear()
        self.metrics = evaluate_teaching_state(self.state)
        self.best_state = self.state
        self.best_efficiency = self.metrics.total_efficiency
        self.task_label.setText(task)
        self._apply_enabled_controls()
        self._sync_controls()
        self._refresh()

    def _apply_enabled_controls(self) -> None:
        if self.mode == "free":
            enabled = set(self.controls)
        else:
            enabled_by_category = {
                "position": {"offset_x_um", "offset_y_um", "offset_z_um"},
                "direction": {"pitch_mrad", "yaw_mrad"},
                "shape": {"offset_z_um", "input_beam_radius_mm", "curvature_waves"},
                "five_axis": {"offset_x_um", "offset_y_um", "offset_z_um", "pitch_mrad", "yaw_mrad"},
            }
            enabled = enabled_by_category.get(self.category, set())
        for key, control in self.controls.items():
            control.setEnabled(key in enabled)

    def select_object(self, key: str) -> None:
        key = str(key)
        if key in INSTRUMENT_KEYS:
            self.selected_object = key
            self.used_instruments.add(key)
            self.instrument_buttons[key].setChecked(True)
        elif key in {"lens", "fiber"}:
            self.selected_object = key
        self.scene_2d.set_focus(key)
        self.scene_3d.set_focus(key)
        self._refresh_measurement()

    def set_scene_view(self, index: int) -> None:
        index = 1 if int(index) == 1 else 0
        self.scene_stack.setCurrentIndex(index)
        self.view_2d_button.setChecked(index == 0)
        self.view_3d_button.setChecked(index == 1)
        self.camera_combo.setEnabled(index == 1)

    def _camera_changed(self) -> None:
        self.scene_3d.set_view(str(self.camera_combo.currentData() or "isometric"))

    def _focus_selected(self) -> None:
        if self.scene_stack.currentIndex() == 1:
            self.scene_3d.focus_selected()

    def _control_changed(self, key: str, value: float) -> None:
        if self._updating_controls:
            return
        self.history.append(self.state)
        if len(self.history) > 60:
            self.history.pop(0)
        self.state = self.state.updated(**{key: float(value)})
        self.metrics = evaluate_teaching_state(self.state)
        if self.metrics.total_efficiency > self.best_efficiency:
            self.best_efficiency = self.metrics.total_efficiency
            self.best_state = self.state
        self._refresh()

    def _sync_controls(self) -> None:
        self._updating_controls = True
        for key, control in self.controls.items():
            control.setValue(float(getattr(self.state, key)))
        self._updating_controls = False

    def _refresh(self) -> None:
        self.scene_2d.set_state(self.state, self.metrics)
        self.scene_3d.set_state(self.state, self.metrics)
        self.efficiency_bar.setValue(round(self.metrics.total_efficiency * 1000))
        self.best_label.setText(f"当前总效率 {self.metrics.total_efficiency * 100:.1f}%　历史最好 {self.best_efficiency * 100:.1f}%")
        self.measurement_count.setText(f"已使用仪器：{len(self.used_instruments)}/5")
        self._refresh_measurement()

    def _refresh_measurement(self) -> None:
        labels = {key: name for key, name, _hint in INSTRUMENTS}
        labels.update({"lens": "聚焦镜组", "fiber": "五轴光纤架与光纤端面"})
        self.selected_label.setText(labels.get(self.selected_object, self.selected_object))
        self.preview.set_data(self.selected_object, self.state, self.metrics)
        m = self.metrics
        if self.selected_object == "input_power":
            text = f"输入功率：{self.state.input_power_mw:.3f} mW\n监测支路：{m.monitor_power_mw:.3f} mW\n判断用途：排除光源波动与输入基准问题。"
        elif self.selected_object == "output_power":
            text = f"输出功率：{m.output_power_mw:.3f} mW\n系统效率：{m.system_efficiency * 100:.1f}%\n接收效率：{m.receiver_efficiency * 100:.1f}%\n总效率：{m.total_efficiency * 100:.1f}%"
        elif self.selected_object == "beam_analyzer":
            text = f"光斑中心：X={self.state.offset_x_um:+.2f} μm，Y={self.state.offset_y_um:+.2f} μm\n端面光斑半径：{m.beam_radius_at_fiber_um:.2f} μm\n目标模场半径：{self.state.fiber_mode_radius_um:.2f} μm"
        elif self.selected_object == "shack_hartmann":
            text = f"波前倾斜：Pitch={self.state.pitch_mrad:+.2f} mrad，Yaw={self.state.yaw_mrad:+.2f} mrad\n轴向离焦：{self.state.offset_z_um:+.1f} μm\n纯曲率差：{self.state.curvature_waves:+.2f} waves"
        elif self.selected_object == "mach_zehnder":
            text = f"干涉证据：倾角会引起条纹倾斜；离焦和曲率会引起条纹弯曲。\n当前边缘相位差：{self.state.curvature_waves:+.2f} waves"
        elif self.selected_object == "lens":
            text = f"焦距：{self.state.focal_length_mm:.2f} mm\n理想束腰：{m.ideal_waist_radius_um:.2f} μm\n瑞利长度：{m.rayleigh_range_um:.1f} μm"
        else:
            text = f"X={self.state.offset_x_um:+.2f} μm　Y={self.state.offset_y_um:+.2f} μm　Z={self.state.offset_z_um:+.1f} μm\nPitch={self.state.pitch_mrad:+.2f} mrad　Yaw={self.state.yaw_mrad:+.2f} mrad\n当前判断：{m.status}"
        self.readout.setText(text)

    def undo(self) -> None:
        if not self.history:
            return
        self.state = self.history.pop()
        self.metrics = evaluate_teaching_state(self.state)
        self._sync_controls()
        self._refresh()

    def restore_initial(self) -> None:
        self.history.append(self.state)
        self.state = self.initial_state
        self.metrics = evaluate_teaching_state(self.state)
        self._sync_controls()
        self._refresh()

    def save_best(self) -> None:
        if self.metrics.total_efficiency >= self.best_efficiency:
            self.best_state = self.state
            self.best_efficiency = self.metrics.total_efficiency
        QMessageBox.information(self, "已保存", f"当前最好总效率：{self.best_efficiency * 100:.1f}%")

    def submit_diagnosis(self) -> None:
        selected = self.diagnosis_combo.currentText()
        expected = self.metrics.dominant_mismatch
        
        
        initial_expected = evaluate_teaching_state(self.initial_state).dominant_mismatch
        correct = selected == initial_expected
        efficiency_pass = self.metrics.total_efficiency >= (0.85 if self.mode == "free" else 0.80)
        evidence_pass = len(self.used_instruments) >= 2
        score = int(correct) * 35 + int(efficiency_pass) * 45 + int(evidence_pass) * 20
        self.progressChanged.emit("diagnostic", score)
        QMessageBox.information(
            self,
            "实验评价",
            f"主导原因判断：{'正确' if correct else '需复核'}（初始主因：{initial_expected}）\n"
            f"目标效率：{'达到' if efficiency_pass else '未达到'}\n"
            f"测量证据：{'较完整' if evidence_pass else '至少再查看一种仪器'}\n"
            f"本次评价：{score} 分",
        )

    def resizeEvent(self, event) -> None:  
        super().resizeEvent(event)
        width = max(1, self.width())
        compact = width < 1250
        if not hasattr(self, "instrument_card") or not hasattr(self, "main_splitter"):
            return
        self.instrument_card.setVisible(not compact)
        if compact:
            self.main_splitter.setSizes([0, max(560, width - 390), 340])
        else:
            self.main_splitter.setSizes([235, max(680, width - 620), 350])


__all__ = ["TeachingDiagnosticPage"]
