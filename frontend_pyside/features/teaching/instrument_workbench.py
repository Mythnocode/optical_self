
from __future__ import annotations

from dataclasses import dataclass
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.components.basic import Card, InfoRow


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    key: str
    name: str
    short_name: str
    measures: str
    placement: str
    output: str
    note: str


INSTRUMENTS: tuple[InstrumentSpec, ...] = (
    InstrumentSpec(
        "input_power",
        "输入功率计",
        "输入功率",
        "输入功率、系统效率基准",
        "分束镜监测支路",
        "输入功率、功率稳定度",
        "用于建立系统效率和耦合效率的输入基准。",
    ),
    InstrumentSpec(
        "output_power",
        "输出功率计",
        "输出功率",
        "光纤输出功率、插入损耗",
        "光纤输出端",
        "输出功率、系统效率、耦合损耗",
        "与输入功率计配合计算系统效率和插入损耗。",
    ),
    InstrumentSpec(
        "beam_analyzer",
        "光束分析仪",
        "光束分析",
        "光强、位置、束宽、椭圆率",
        "观察支路或目标面",
        "二维光斑、X/Y 截面、1/e² 束宽",
        "定量分析光斑中心、尺寸、椭圆率和漂移。",
    ),
    InstrumentSpec(
        "mach_zehnder",
        "Mach–Zehnder 离轴干涉仪 + 相机",
        "离轴干涉",
        "二维相位、波前曲率、相位差",
        "待测光与参考光合束支路",
        "干涉条纹、包裹相位、解包裹相位",
        "通过离轴条纹的傅里叶重建获得二维复场相位。",
    ),
    InstrumentSpec(
        "shack_hartmann",
        "Shack–Hartmann 波前传感器",
        "波前传感",
        "波前斜率、倾斜、离焦和低阶像差",
        "目标面或准直输出面",
        "波前图、RMS/P-V、Zernike 系数",
        "适合实时诊断倾斜、离焦、曲率和低阶像差。",
    ),
)

INSTRUMENT_BY_KEY = {item.key: item for item in INSTRUMENTS}


class InstrumentBenchCanvas(QWidget):


    instrumentActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._keys: list[str] = ["input_power", "output_power", "beam_analyzer"]
        self._focus = "beam_analyzer"
        self._hit_boxes: dict[str, QRectF] = {}

    def set_instruments(self, keys: list[str]) -> None:
        self._keys = [key for key in keys if key in INSTRUMENT_BY_KEY]
        if self._focus not in self._keys and self._keys:
            self._focus = self._keys[0]
        self.update()

    def set_focus(self, key: str) -> None:
        if key in INSTRUMENT_BY_KEY:
            self._focus = key
            self.update()

    def mousePressEvent(self, event) -> None:
        position = event.position()
        for key, box in self._hit_boxes.items():
            if box.contains(position):
                self.instrumentActivated.emit(key)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))

        width = max(600.0, float(self.width()))
        height = max(220.0, float(self.height()))
        axis_y = height * 0.48
        left = 54.0
        right = width - 54.0

        painter.setPen(QPen(QColor(theme.DIVIDER), 1))
        for x in range(30, int(width), 32):
            painter.drawLine(x, 18, x, int(height - 18))
        for y in range(24, int(height), 32):
            painter.drawLine(18, y, int(width - 18), y)

        painter.setPen(QPen(QColor(theme.ERROR), 3))
        painter.drawLine(QPointF(left, axis_y), QPointF(right, axis_y))

        base_nodes = [
            ("laser", "808/1550 nm\n激光器", left + 30),
            ("isolator", "光隔离器", left + (right - left) * 0.18),
            ("splitter", "分束镜", left + (right - left) * 0.36),
            ("lens", "聚焦镜组", left + (right - left) * 0.58),
            ("fiber", "五轴光纤架\n+ 光纤", left + (right - left) * 0.80),
        ]
        for key, label, x in base_nodes:
            self._draw_node(painter, QRectF(x - 48, axis_y - 30, 96, 60), label, key == "fiber")

        self._hit_boxes = {}
        selected = [key for key in self._keys if key in INSTRUMENT_BY_KEY]
        if not selected:
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                QRectF(0, axis_y + 60, width, 80),
                Qt.AlignmentFlag.AlignCenter,
                "选择分析仪器后，平台会在二维实验台中显示测量位置和结果类型。",
            )
            return

        branch_y_top = axis_y - 105
        branch_y_bottom = axis_y + 110
        positions = {
            "input_power": (left + (right - left) * 0.38, branch_y_bottom),
            "output_power": (right - 35, axis_y),
            "beam_analyzer": (left + (right - left) * 0.58, branch_y_bottom),
            "mach_zehnder": (left + (right - left) * 0.47, branch_y_top),
            "shack_hartmann": (left + (right - left) * 0.70, branch_y_top),
            "polarimeter": (left + (right - left) * 0.90, branch_y_bottom),
        }
        branch_origins = {
            "input_power": left + (right - left) * 0.36,
            "output_power": left + (right - left) * 0.84,
            "beam_analyzer": left + (right - left) * 0.58,
            "mach_zehnder": left + (right - left) * 0.36,
            "shack_hartmann": left + (right - left) * 0.58,
            "polarimeter": left + (right - left) * 0.82,
        }

        for key in selected:
            x, y = positions[key]
            origin_x = branch_origins[key]
            if key != "output_power":
                painter.setPen(QPen(QColor(theme.ERROR), 2, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(origin_x, axis_y), QPointF(x, y))
            box = QRectF(x - 62, y - 27, 124, 54)
            self._hit_boxes[key] = box
            self._draw_instrument(painter, box, INSTRUMENT_BY_KEY[key], key == self._focus)

        painter.setPen(QColor("#516579"))
        painter.drawText(
            QRectF(24, height - 30, width - 48, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "红线：主光路　红色虚线：测量支路　点击仪器可查看输出预览",
        )

    @staticmethod
    def _draw_node(painter: QPainter, rect: QRectF, text: str, emphasized: bool = False) -> None:
        painter.setPen(QPen(QColor("#7ea6c4"), 1.4))
        painter.setBrush(QColor("#eaf4fb") if not emphasized else QColor("#dceffc"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _draw_instrument(painter: QPainter, rect: QRectF, spec: InstrumentSpec, focused: bool) -> None:
        painter.setPen(QPen(QColor("#146fb3") if focused else QColor("#7ea6c4"), 2.2 if focused else 1.2))
        painter.setBrush(QColor("#dceffc") if focused else QColor(theme.SURFACE))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        font = QFont(painter.font())
        font.setBold(focused)
        painter.setFont(font)
        painter.drawText(rect.adjusted(5, 3, -5, -3), Qt.AlignmentFlag.AlignCenter, spec.short_name)


class InstrumentPreviewCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(190)
        self._key = "beam_analyzer"

    def set_instrument(self, key: str) -> None:
        if key in INSTRUMENT_BY_KEY:
            self._key = key
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.SURFACE_MUTED))
        area = QRectF(18, 18, max(40, self.width() - 36), max(40, self.height() - 36))
        painter.setPen(QPen(QColor(theme.DIVIDER), 1))
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(area, 7, 7)

        if self._key in {"input_power", "output_power"}:
            self._draw_power(painter, area, 0.82 if self._key == "input_power" else 0.68)
        elif self._key == "beam_analyzer":
            self._draw_beam(painter, area)
        elif self._key == "mach_zehnder":
            self._draw_interferogram(painter, area)
        elif self._key == "shack_hartmann":
            self._draw_shack(painter, area)
        else:
            self._draw_wavefront_placeholder(painter, area)

    @staticmethod
    def _draw_power(painter: QPainter, area: QRectF, fraction: float) -> None:
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(12, 8, -12, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter, "实时功率")
        bar = area.adjusted(26, 55, -26, -75)
        painter.setBrush(QColor(theme.SURFACE_SECONDARY))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawRoundedRect(bar, 8, 8)
        value = QRectF(bar.left(), bar.top(), bar.width() * fraction, bar.height())
        gradient = QLinearGradient(value.topLeft(), value.topRight())
        gradient.setColorAt(0.0, QColor("#2d82c7"))
        gradient.setColorAt(1.0, QColor("#56b5e8"))
        painter.setBrush(gradient)
        painter.drawRoundedRect(value, 8, 8)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(10, 0, -10, -20), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, f"{fraction * 100:.1f}% 量程")

    @staticmethod
    def _draw_beam(painter: QPainter, area: QRectF) -> None:
        center = area.center()
        radius = min(area.width(), area.height()) * 0.34
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, QColor("#fff44f"))
        gradient.setColorAt(0.25, QColor("#ff8c2a"))
        gradient.setColorAt(0.55, QColor("#2cc4c9"))
        gradient.setColorAt(1.0, QColor("#172a74"))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius * 1.18, radius * 0.88)
        painter.setPen(QPen(QColor("white"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - radius), QPointF(center.x(), center.y() + radius))

    @staticmethod
    def _draw_interferogram(painter: QPainter, area: QRectF) -> None:
        clip = area.adjusted(12, 12, -12, -12)
        painter.save()
        painter.setClipRect(clip)
        stripe_count = 18
        for index in range(stripe_count):
            x = clip.left() + index * clip.width() / stripe_count
            offset = 10.0 * math.sin(index * 0.55)
            color = QColor("#1d4ed8") if index % 2 == 0 else QColor("#dbeafe")
            painter.setPen(QPen(color, clip.width() / stripe_count * 0.78))
            painter.drawLine(QPointF(x, clip.top() - 20 + offset), QPointF(x + 28, clip.bottom() + 20 + offset))
        painter.restore()
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "离轴干涉条纹 → 相位重建")

    @staticmethod
    def _draw_shack(painter: QPainter, area: QRectF) -> None:
        painter.setPen(QPen(QColor(theme.DIVIDER), 1))
        painter.setBrush(QColor("#1f78b4"))
        rows, cols = 7, 9
        for row in range(rows):
            for column in range(cols):
                x = area.left() + 24 + column * (area.width() - 48) / max(cols - 1, 1)
                y = area.top() + 24 + row * (area.height() - 48) / max(rows - 1, 1)
                dx = 4.0 * math.sin(row * 0.7 + column * 0.35)
                dy = 3.0 * math.cos(row * 0.45 - column * 0.25)
                painter.drawEllipse(QPointF(x + dx, y + dy), 3.2, 3.2)
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "微透镜焦点阵列")

    @staticmethod
    def _draw_wavefront_placeholder(painter: QPainter, area: QRectF) -> None:
        center = area.center()
        radius_x = area.width() * 0.28
        radius_y = area.height() * 0.18
        painter.setPen(QPen(QColor("#2563eb"), 3))
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawEllipse(center, radius_x, radius_y)
        painter.setPen(QPen(QColor(theme.ERROR), 2))
        painter.drawLine(center, QPointF(center.x() + radius_x * 0.82, center.y() - radius_y * 0.62))
        painter.setPen(QColor(theme.TEXT_PRIMARY))
        painter.drawText(area.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "波前曲率与倾斜示意")


class TeachingInstrumentWorkbench(QWidget):


    instrumentsChanged = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stage = "模场失配"
        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(7)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)

        selector = Card("分析仪器", compact=True)
        selector.setMinimumWidth(230)
        selector.setMaximumWidth(300)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(5)
        self.instrument_boxes: dict[str, QCheckBox] = {}
        default_keys = {"input_power", "output_power", "beam_analyzer"}
        for index, spec in enumerate(INSTRUMENTS):
            box = QCheckBox(spec.name)
            box.setChecked(spec.key in default_keys)
            box.toggled.connect(self._selection_changed)
            self.instrument_boxes[spec.key] = box
            grid.addWidget(box, index, 0)
        selector.body.addLayout(grid)
        selector.body.addWidget(
            InfoRow("覆盖能力", "功率、强度、位置、尺寸、相位与波前")
        )
        splitter.addWidget(selector)

        bench_card = Card("二维虚拟实验台", compact=True)
        self.bench = InstrumentBenchCanvas()
        self.bench.instrumentActivated.connect(self._activate_instrument)
        bench_card.body.addWidget(self.bench, 1)
        splitter.addWidget(bench_card)

        result_card = Card("仪器结果预览", compact=True)
        result_card.setMinimumWidth(300)
        result_card.setMaximumWidth(390)
        self.instrument_selector = QComboBox()
        self.instrument_selector.currentIndexChanged.connect(self._current_changed)
        result_card.body.addWidget(self.instrument_selector)
        self.preview = InstrumentPreviewCanvas()
        result_card.body.addWidget(self.preview, 1)
        self.instrument_measurement = InfoRow("测量内容", "—")
        self.instrument_output = InfoRow("输出图形", "—")
        self.instrument_location = InfoRow("建议位置", "—")
        result_card.body.addWidget(self.instrument_measurement)
        result_card.body.addWidget(self.instrument_output)
        result_card.body.addWidget(self.instrument_location)
        self.instrument_note = QLabel()
        self.instrument_note.setWordWrap(True)
        self.instrument_note.setObjectName("helperText")
        result_card.body.addWidget(self.instrument_note)
        splitter.addWidget(result_card)

        splitter.setSizes([260, 850, 340])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter, 1)
        self._selection_changed()

    def selected_instruments(self) -> list[str]:
        return [key for key, box in self.instrument_boxes.items() if box.isChecked()]

    def set_stage(self, stage: str) -> None:
        self._stage = str(stage or "")
        recommendations = {
            "光源建模": {"input_power", "beam_analyzer"},
            "几何传播": {"beam_analyzer", "shack_hartmann"},
            "OPL / OPD": {"mach_zehnder"},
            "出瞳复场": {"beam_analyzer", "mach_zehnder", "shack_hartmann"},
            "衍射传播": {"beam_analyzer", "mach_zehnder", "shack_hartmann"},
            "光纤模式": {"output_power", "beam_analyzer"},
            "复场耦合": {"input_power", "output_power", "beam_analyzer", "mach_zehnder"},
            "模场失配": {item.key for item in INSTRUMENTS},
            "优化与解释": {"input_power", "output_power", "beam_analyzer", "shack_hartmann"},
        }
        wanted = recommendations.get(self._stage)
        if not wanted:
            return
        for key, box in self.instrument_boxes.items():
            blocked = box.blockSignals(True)
            box.setChecked(key in wanted)
            box.blockSignals(blocked)
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        keys = self.selected_instruments()
        self.bench.set_instruments(keys)
        current_key = str(self.instrument_selector.currentData() or "")
        blocked = self.instrument_selector.blockSignals(True)
        self.instrument_selector.clear()
        for key in keys:
            spec = INSTRUMENT_BY_KEY[key]
            self.instrument_selector.addItem(spec.name, key)
        self.instrument_selector.blockSignals(blocked)
        if keys:
            index = self.instrument_selector.findData(current_key)
            self.instrument_selector.setCurrentIndex(index if index >= 0 else 0)
            self._current_changed(self.instrument_selector.currentIndex())
        else:
            self.instrument_measurement.layout().itemAt(1).widget().setText("—")
            self.instrument_output.layout().itemAt(1).widget().setText("—")
            self.instrument_location.layout().itemAt(1).widget().setText("—")
            self.instrument_note.setText("请选择至少一种分析仪器。")
        self.instrumentsChanged.emit(keys)

    def _activate_instrument(self, key: str) -> None:
        index = self.instrument_selector.findData(key)
        if index >= 0:
            self.instrument_selector.setCurrentIndex(index)

    def _current_changed(self, index: int) -> None:
        key = str(self.instrument_selector.itemData(index) or "")
        spec = INSTRUMENT_BY_KEY.get(key)
        if spec is None:
            return
        self.bench.set_focus(key)
        self.preview.set_instrument(key)
        self._set_info(self.instrument_measurement, "测量内容", spec.measures)
        self._set_info(self.instrument_output, "输出图形", spec.output)
        self._set_info(self.instrument_location, "建议位置", spec.placement)
        self.instrument_note.setText(spec.note)

    @staticmethod
    def _set_info(row: InfoRow, label: str, value: str) -> None:
        layout = row.layout()
        if layout and layout.count() >= 2:
            layout.itemAt(0).widget().setText(label)
            layout.itemAt(1).widget().setText(value)


__all__ = ["INSTRUMENTS", "TeachingInstrumentWorkbench"]
