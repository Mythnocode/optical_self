"""Teaching entry shell and its modeless analysis tools."""

from __future__ import annotations

from frontend_pyside.modules import shared as _shared

globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

class KindDragButton(QPushButton):
    """Click to add, or drag onto the bench."""

    def __init__(self, kind: str, title: str, parent=None) -> None:
        super().__init__(title, parent)
        self._kind = str(kind)
        self._press = None

    def mousePressEvent(self, event) -> None:
        self._press = event.position().toPoint() if hasattr(event, "position") else event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._press is not None:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if (pos - self._press).manhattanLength() >= 8:
                drag = QDrag(self)
                mime = QMimeData()
                payload = QByteArray(self._kind.encode("utf-8"))
                mime.setData(TEACHING_KIND_MIME, payload)
                mime.setText(self._kind)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
                self._press = None
                return
        super().mouseMoveEvent(event)


TEACHING_ANALYSIS_INFO: dict[str, dict[str, Any]] = {
    "spot": {
        "key": "imaging",
        "title": "成像分析",
        "empty": "尚未进行成像计算。请先放置并启用 CCD 或光纤，再点击开始计算。",
        "metrics": (
            ("rms_spot_radius_um", "RMS 光斑半径", "μm"),
            ("centroid_x_mm", "光斑质心 X", "mm"),
            ("centroid_y_mm", "光斑质心 Y", "mm"),
            ("image_distance_mm", "像面位置", "mm"),
            ("valid_ray_count", "有效光线数", "条"),
        ),
    },
    "coupling": {
        "key": "coupling",
        "title": "耦合分析",
        "empty": "尚未进行耦合计算。请先放置并启用光纤，再点击开始计算。",
        "metrics": (
            ("coupling_efficiency", "模式耦合效率", "%"),
            ("mode_overlap_efficiency", "模式重叠效率", "%"),
            ("fiber_interface_efficiency", "端面接收效率", "%"),
            ("total_coupling_efficiency", "总耦合效率", "%"),
            ("coupling_loss_db", "耦合损耗", "dB"),
        ),
    },
}


def _format_teaching_metric(key: str, value: Any, unit: str = "") -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "无效"
    if unit == "%":
        return f"{number * 100:.4g}%"
    if unit == "条":
        return f"{int(number)} 条"
    if unit:
        return f"{number:.6g} {unit}"
    return f"{number:.6g}"


class TeachingAnalysisVisual(QWidget):
    """Compact visual reading of the formal teaching result.

    This intentionally supplements the exact metric table: a beginner can see
    whether a spot is centred and concentrated, or where power is lost, before
    reading micrometre-level values.
    """

    def __init__(self, analysis: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.analysis = str(analysis)
        self.metrics: dict[str, Any] = {}
        self.available = False
        self.setObjectName("TeachingAnalysisVisual")
        self.setMinimumHeight(270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_metrics(self, metrics: dict[str, Any], *, available: bool) -> None:
        self.metrics = dict(metrics or {})
        self.available = bool(available)
        self.update()

    @staticmethod
    def _number(metrics: dict[str, Any], *keys: str, default: float = 0.0) -> float:
        for key in keys:
            try:
                value = float(metrics.get(key))
                if math.isfinite(value):
                    return value
            except (TypeError, ValueError):
                continue
        return default

    @staticmethod
    def _fraction(value: float) -> float:
        return max(0.0, min(1.0, value / 100.0 if value > 1.000001 else value))

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#101828"))
        painter.setPen(QPen(QColor("#344054"), 1))
        painter.drawRoundedRect(rect, 8, 8)
        if not self.available:
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(0, -30, 0, 0), Qt.AlignmentFlag.AlignCenter, "尚无正式计算结果")
            painter.setPen(QColor("#98A2B3"))
            painter.drawText(rect.adjusted(0, 28, 0, 0), Qt.AlignmentFlag.AlignCenter,
                             "点击上方“开始计算”获取当前指标")
            return
        if self.analysis == "spot":
            rms = self._number(self.metrics, "rms_spot_radius_um", "rms_um", default=0.0)
            center = rect.center()
            radius = max(20, min(68, 22 + rms * 1.4))
            for factor, colour in ((2.0, "#7F1D1D"), (1.45, "#DC2626"), (0.9, "#F97316"), (0.42, "#FEF3C7")):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colour))
                painter.drawEllipse(center, int(radius * factor), int(radius * factor))
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(0, 10, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             f"接收面光斑 · RMS 半径 {rms:.3g} μm")
        else:
            eta = self._fraction(self._number(self.metrics, "total_coupling_efficiency", "coupling_efficiency", default=0.0))
            center = rect.center()
            radius = min(rect.height(), rect.width()) // 4
            painter.setPen(QPen(QColor("#34D399"), 10))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)
            painter.setPen(QColor("#FFFFFF"))
            font = painter.font()
            font.setPointSize(max(15, font.pointSize() + 7))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                f"η  {_format_teaching_metric('total_coupling_efficiency', eta, '%')}",
            )
            painter.setPen(QColor("#A7F3D0"))
            painter.drawText(rect.adjusted(0, 70, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                             "总耦合效率（正式波动光学计算）")

    def _paint_spot(self, painter: QPainter, rect) -> None:
        title_rect = rect.adjusted(14, 8, -14, 0)
        painter.setPen(QColor("#0A327A"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "接收面光斑与像心")
        plot = rect.adjusted(18, 30, -18, -14)
        side = min(plot.height(), max(72, plot.width() // 2))
        target = plot
        target.setWidth(side)
        target.setHeight(side)
        painter.fillRect(target, QColor("#172554"))
        center = target.center()
        rms = self._number(self.metrics, "rms_spot_radius_um", "rms_um", default=12.0)
        radius = max(13.0, min(float(side) * 0.32, 12.0 + rms * 0.65))
        x = self._number(self.metrics, "centroid_x_mm", "centroid_x", default=0.0)
        y = self._number(self.metrics, "centroid_y_mm", "centroid_y", default=0.0)
        # Centroid is deliberately clipped: the plot signals off-axis imaging
        # without pretending that a different scale is a physical calculation.
        offset_x = max(-side * 0.28, min(side * 0.28, x * 12.0))
        offset_y = max(-side * 0.28, min(side * 0.28, -y * 12.0))
        spot = center + QPoint(int(offset_x), int(offset_y))
        for factor, colour in ((2.2, "#1D4ED8"), (1.55, "#2563EB"), (1.0, "#60A5FA"), (0.55, "#FDE68A")):
            painter.setBrush(QColor(colour))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(spot, int(radius * factor), int(radius * factor))
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(center.x() - 12, center.y(), center.x() + 12, center.y())
        painter.drawLine(center.x(), center.y() - 12, center.x(), center.y() + 12)
        painter.setPen(QPen(QColor("#F97316"), 2))
        painter.drawLine(spot.x() - 6, spot.y(), spot.x() + 6, spot.y())
        painter.drawLine(spot.x(), spot.y() - 6, spot.x(), spot.y() + 6)
        info = rect.adjusted(side + 34, 35, -12, -12)
        painter.setPen(QColor("#344054"))
        painter.drawText(info, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         f"RMS 半径  {rms:.3g} μm\n\n"
                         f"光斑质心  ({x:.3g}, {y:.3g}) mm\n\n"
                         "白色十字：理想像心\n橙色十字：实际质心")

    def _paint_coupling(self, painter: QPainter, rect) -> None:
        painter.setPen(QColor("#0A327A"))
        painter.drawText(rect.adjusted(14, 8, -14, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         "功率如何到达光纤基模")
        system = self._fraction(self._number(self.metrics, "system_efficiency", "transmission_efficiency", default=0.0))
        facet = self._fraction(self._number(self.metrics, "fiber_interface_efficiency", "receiver_efficiency", default=1.0))
        total = self._fraction(self._number(self.metrics, "total_coupling_efficiency", "coupling_efficiency", default=0.0))
        overlap = self._fraction(self._number(self.metrics, "mode_overlap_efficiency", default=total))
        stages = (("系统透过", system), ("模场重叠", overlap), ("端面接收", facet), ("总耦合", total))
        left = rect.left() + 18
        top = rect.top() + 40
        width = max(90, rect.width() - 158)
        bar_h = 18
        for index, (label, value) in enumerate(stages):
            y = top + index * 25
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#DCE9FF"))
            painter.drawRoundedRect(left, y, width, bar_h, 5, 5)
            painter.setBrush(QColor("#155EEF") if index < 3 else QColor("#0E7490"))
            painter.drawRoundedRect(left, y, int(width * value), bar_h, 5, 5)
            painter.setPen(QColor("#344054"))
            painter.drawText(left + width + 10, y, 100, bar_h, Qt.AlignmentFlag.AlignVCenter,
                             f"{label}  {value * 100:.1f}%")
        painter.setPen(QColor("#667085"))
        painter.drawText(rect.adjusted(18, -4, -18, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                         "每一行表示相对于该环节输入的保留比例；总耦合效率以正式引擎结果为准。")


class TeachingImagingCouplingPopup(QFrame):
    """成像与耦合：一个窗口里放成像预览和耦合数据。

    这两项本来各有一个窗口，但它们读的是同一次正式计算处方，放在一起才能
    对照着看：上面是接收面光斑预览，下面是效率数据（按钮式显示，与仿真页
    的耦合效率一致）。
    """

    calculateRequested = Signal()

    START_BUTTON_TEXT = "开始计算"
    BUSY_BUTTON_TEXT = "正在计算"
    UPDATE_BUTTON_TEXT = "更新"

    # 效率口径取自教学引擎实际返回的量：仿真页那三项里的"系统效率/端面接收
    # 效率"在教学台上没有对应输出，硬摆上去只会永远是"—"。
    EFFICIENCY_PILLS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("total", "总耦合效率", ("total_coupling_efficiency", "coupling_efficiency")),
    )
    # 其余耦合指标直接列成一行，避免为每个值再开一个控件。
    DETAIL_METRICS: tuple[tuple[str, str, str], ...] = (
        ("coupling_loss_db", "耦合损耗", "dB"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("TeachingImagingCouplingPopup")
        self.setWindowTitle("成像与耦合")
        self.setMinimumSize(460, 520)
        self.resize(500, 640)
        self._result_scene_revision: int | None = None
        self._scene_revision: int | None = None
        self._has_completed_result = False
        self._coupling_metrics: dict[str, Any] = {}
        self._imaging_metrics: dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(8)

        action_row = QHBoxLayout()
        self.run_button = QPushButton(self.START_BUTTON_TEXT)
        self.run_button.setObjectName("teachingV2PrimaryButton")
        self.run_button.setMinimumHeight(38)
        self.run_button.setMinimumWidth(156)
        self.run_button.clicked.connect(self.calculateRequested.emit)
        action_row.addWidget(self.run_button)
        # 状态只在需要人注意时出现（正在算 / 算不出来）；成功不写提示词，
        # 结果本身就是反馈。文案仍写入 text()，供验收脚本和读屏软件读取。
        self.status = QLabel("")
        self.status.setObjectName("TeachingPopupStatus")
        self.status.setWordWrap(True)
        self.status.hide()
        action_row.addWidget(self.status, 1)
        root.addLayout(action_row)

        # 波动光学没有可信的完成百分比，用不确定进度条表示正在算。
        self.progress = QProgressBar(self)
        self.progress.setObjectName("TeachingAnalysisProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        root.addWidget(self.progress)

        # 没有结果就没有"成像预览"这一块：窗口里只留图和结果，不摆空态文案。
        self.imaging_block = QWidget()
        imaging_layout = QVBoxLayout(self.imaging_block)
        imaging_layout.setContentsMargins(0, 0, 0, 0)
        imaging_layout.setSpacing(6)
        imaging_title = QLabel("成像预览")
        imaging_title.setObjectName("PopupGroupTitle")
        imaging_layout.addWidget(imaging_title)
        self.imaging_summary = QLabel("")
        self.imaging_summary.setObjectName("TeachingAnalysisSummary")
        self.imaging_summary.setWordWrap(True)
        imaging_layout.addWidget(self.imaging_summary)
        self.imaging_visual = TeachingAnalysisVisual("spot", self)
        # 预览只是示意图，窗口要保持"小窗"尺寸，别让预览把耦合数据挤出去。
        self.imaging_visual.setMinimumHeight(168)
        self.imaging_visual.setMaximumHeight(186)
        imaging_layout.addWidget(self.imaging_visual)
        self.imaging_block.hide()
        root.addWidget(self.imaging_block)

        coupling_title = QLabel("耦合数据")
        coupling_title.setObjectName("PopupGroupTitle")
        root.addWidget(coupling_title)
        # 竖排而不是仿真页那种一行三块：这是个窄窗口，横排会把标签挤到被裁掉。
        pills = QVBoxLayout()
        pills.setSpacing(4)
        self.coupling_pills: dict[str, QLabel] = {}
        for key, title, _keys in self.EFFICIENCY_PILLS:
            label = QLabel(f"{title}：—")
            label.setObjectName("coup")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # 与仿真页一致：效率用按钮式标签显示，扫一眼就能比较。
            pills.addWidget(label)
            self.coupling_pills[key] = label
        root.addLayout(pills)
        self.coupling_detail = QLabel("")
        self.coupling_detail.setObjectName("HelperText")
        self.coupling_detail.setWordWrap(True)
        self.coupling_detail.hide()
        root.addWidget(self.coupling_detail)
        root.addStretch(1)

    def _idle_button_text(self) -> str:
        return self.UPDATE_BUTTON_TEXT if self._has_completed_result else self.START_BUTTON_TEXT

    def _set_run_button(self, text: str, *, enabled: bool) -> None:
        self.run_button.setText(str(text))
        self.run_button.setEnabled(bool(enabled))

    def _set_status(self, text: str, *, attention: bool = True) -> None:
        """写状态文字；只有需要人注意的状态才真的显示出来。"""
        self.status.setText(str(text or ""))
        self.status.setVisible(bool(text) and bool(attention))

    @staticmethod
    def _first_metric(metrics: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if metrics.get(key) is not None:
                return metrics[key]
        return None

    def _refresh_pills(self) -> None:
        for key, title, keys in self.EFFICIENCY_PILLS:
            value = self._first_metric(self._coupling_metrics, keys)
            text = _format_teaching_metric(key, value, "%") if value is not None else "—"
            self.coupling_pills[key].setText(f"{title}：{text}")

    def set_scene_revision(self, revision: int) -> None:
        self._scene_revision = int(revision)
        if self._result_scene_revision is None or self._result_scene_revision == int(revision):
            return
        # 场景改了就不再摆着旧数字：清空结果并提示需要重算，避免把过期值当现状。
        self._set_run_button(self._idle_button_text(), enabled=True)
        self._result_scene_revision = None
        self._imaging_metrics = {}
        self._coupling_metrics = {}
        self.imaging_block.hide()
        self.imaging_visual.set_metrics({}, available=False)
        self.coupling_detail.clear()
        self.coupling_detail.hide()
        self._refresh_pills()
        action = "更新" if self._has_completed_result else "开始计算"
        self._set_status(f"场景已修改，请点击{action}")

    def set_busy(self, busy: bool, message: str = "") -> None:
        if busy:
            self._set_run_button(self.BUSY_BUTTON_TEXT, enabled=False)
            # 正在算：进度条 + 一句状态，除此之外没有别的提示文字。
            self._set_status(str(message or "正在计算，界面仍可操作"))
            self.progress.setRange(0, 0)
            self.progress.show()
        elif message:
            self._set_run_button(self._idle_button_text(), enabled=True)
            self._set_status(str(message))
            self.progress.hide()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        else:
            self._set_run_button(self._idle_button_text(), enabled=True)
            self._set_status("", attention=False)
            self.progress.hide()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)

    def set_running(self, analysis: str, *, done: bool = False) -> None:
        """显示正在算哪一项：合并后是两个分析，进度要说清楚。"""
        if done:
            # 两项都算完：结果本身就是反馈，不再留一句提示词。
            self.set_busy(False)
            self._set_status("正式计算完成", attention=False)
            return
        title = str(TEACHING_ANALYSIS_INFO.get(str(analysis), {}).get("title") or analysis)
        self.set_busy(True, f"正在计算{title}…")

    def set_result(self, analysis: str, result: object) -> None:
        analysis = str(analysis)
        info = TEACHING_ANALYSIS_INFO.get(analysis, {})
        title = str(info.get("title") or analysis)
        artifacts = getattr(result, "artifacts", {}) or {}
        artifact = artifacts.get(analysis) if isinstance(artifacts, dict) else None
        artifact = dict(artifact or {})
        metrics = dict(artifact.get("metrics") or getattr(result, "metrics", {}) or {})
        status = str(artifact.get("status") or getattr(result, "status", "failed") or "failed")
        success = bool(getattr(result, "success", status == "completed"))
        completed = bool(success and status == "completed")
        scene_revision = getattr(result, "scene_revision", None)
        self._result_scene_revision = (
            int(scene_revision) if scene_revision is not None else self._scene_revision
        )
        self._set_run_button(self._idle_button_text(), enabled=True)
        self.progress.hide()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)

        if analysis == "coupling":
            self._coupling_metrics = metrics if completed else {}
            self._refresh_pills()
            detail = [
                f"{label} {_format_teaching_metric(key, metrics.get(key), unit)}"
                for key, label, unit in self.DETAIL_METRICS
                if metrics.get(key) is not None
            ]
            # 没有明细量就不留空行；算不出来时把原因交给状态栏。
            self.coupling_detail.setText(" · ".join(detail) if completed else "")
            self.coupling_detail.setVisible(bool(completed and detail))
        else:
            self._imaging_metrics = metrics if completed else {}
            self.imaging_visual.set_metrics(metrics, available=completed)
            value = metrics.get("rms_spot_radius_um", metrics.get("rms_um"))
            self.imaging_summary.setText(
                f"RMS 光斑半径  {_format_teaching_metric('rms_spot_radius_um', value, 'μm')}"
                if completed
                else ""
            )
            # 有结果才有"成像预览"这一块，没结果就整块收起。
            self.imaging_block.setVisible(completed)

        errors = [str(item).strip() for item in (artifact.get("errors") or getattr(result, "errors", ()) or ())]
        errors = [item for item in errors if item]
        if completed:
            self._has_completed_result = True
            self._set_run_button(self.UPDATE_BUTTON_TEXT, enabled=True)
            elapsed = float(getattr(result, "elapsed_ms", 0.0) or 0.0)
            suffix = f" · {elapsed:.0f} ms" if elapsed > 0 else ""
            # 成功不显示提示词：填好的图和数据本身就是反馈。
            self._set_status(f"{title}完成{suffix}", attention=False)
        elif status == "missed":
            self._set_status(f"{title}：光束未命中接收端")
        elif errors:
            self._set_status(f"{title}：{errors[0]}")
        else:
            self._set_status(f"{title}计算未完成")


class TeachingEquipmentPopup(QFrame):
    addRequested = Signal(str)
    presetRequested = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setObjectName("TeachingEquipmentPopup")
        self.setWindowTitle("器材库")
        self.setMinimumSize(420, 560)
        self.resize(440, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("器材库"))
        close = QToolButton()
        close.setText("×")
        close.clicked.connect(self.close)
        title_row.addStretch(1)
        title_row.addWidget(close)
        root.addLayout(title_row)
        search = QLineEdit()
        search.setPlaceholderText("搜索器材…")
        root.addWidget(search)
        hint = QLabel("拖到台上放置，或点击添加")
        hint.setObjectName("TeachingHint")
        root.addWidget(hint)
        self._preset_kind = ""
        self._preset_label = QLabel("")
        self._preset_label.setObjectName("PopupGroupTitle")
        self._preset_label.setWordWrap(True)
        self._preset_label.hide()
        root.addWidget(self._preset_label)
        self.preset_box = QComboBox()
        self.preset_box.setVisible(False)
        root.addWidget(self.preset_box)
        self.custom_value = QDoubleSpinBox()
        self.custom_value.setRange(0.01, 30000.0)
        self.custom_value.setDecimals(3)
        self.custom_value.setSuffix(" nm")
        self.custom_value.setVisible(False)
        root.addWidget(self.custom_value)
        self.apply_preset = QPushButton("应用当前规格")
        self.apply_preset.setVisible(False)
        self.apply_preset.clicked.connect(self._apply_preset)
        root.addWidget(self.apply_preset)
        catalog = QWidget()
        catalog_layout = QVBoxLayout(catalog)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.setSpacing(4)
        self._kind_buttons: list[QPushButton] = []
        for group, values in (
            ("光源", [item for item in PLACEABLE_KINDS if item[0] == "laser"]),
            ("光学元件", [item for item in PLACEABLE_KINDS if item[0] in {
                "isolator", "waveplate", "lens", "cylindrical_lens", "beam_expander",
                "aperture", "pbs", "splitter", "beam_sampler", "grating", "mirror",
            }]),
            ("接收与测量", [item for item in PLACEABLE_KINDS if item[0] in {
                "fiber", "ccd", "power_meter", "wavefront_sensor",
            }]),
            ("台面", [item for item in PLACEABLE_KINDS if item[0] == "oscilloscope"]),
        ):
            if not values:
                continue
            label = QLabel(group)
            label.setObjectName("PopupGroupTitle")
            catalog_layout.addWidget(label)
            for key, title in values:
                button = KindDragButton(key, title)
                button.setProperty("kindKey", key)
                button.clicked.connect(lambda _checked=False, value=key: self._select_equipment(value))
                catalog_layout.addWidget(button)
                self._kind_buttons.append(button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(catalog)
        scroll.setMinimumHeight(280)
        scroll.setMaximumHeight(420)
        root.addWidget(scroll)
        search.textChanged.connect(self._filter_equipment)
        self.adjustSize()

    def _filter_equipment(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        for button in self._kind_buttons:
            title = button.text().lower()
            key = str(button.property("kindKey") or "").lower()
            button.setVisible(not needle or needle in title or needle in key)

    def _select_equipment(self, kind: str) -> None:
        kind = str(kind)
        self.addRequested.emit(kind)
        presets: dict[str, tuple[str, list[tuple[str, object]]]] = {
            "laser": (
                "工业常用激光器规格",
                [("780 nm 外腔二极管 · 50 mW · 0.70 mm", {"wavelength_nm": 780.0, "power_mw": 50.0, "beam_radius_mm": 0.70}),
                 ("850 nm VCSEL · 10 mW · 0.35 mm", {"wavelength_nm": 850.0, "power_mw": 10.0, "beam_radius_mm": 0.35}),
                 ("1064 nm DPSS · 100 mW · 0.80 mm", {"wavelength_nm": 1064.0, "power_mw": 100.0, "beam_radius_mm": 0.80}),
                 ("1310 nm DFB · 10 mW · 0.45 mm", {"wavelength_nm": 1310.0, "power_mw": 10.0, "beam_radius_mm": 0.45}),
                 ("1550 nm DFB · 10 mW · 0.50 mm", {"wavelength_nm": 1550.0, "power_mw": 10.0, "beam_radius_mm": 0.50}),
                 ("自定义波长", None)],
            ),
            "lens": (
                "工程常用透镜规格",
                [("焦距 25 mm · 直径 12.7 mm", {"focal_length_mm": 25.0, "diameter_mm": 12.7}),
                 ("焦距 50 mm · 直径 25.4 mm", {"focal_length_mm": 50.0, "diameter_mm": 25.4}),
                 ("焦距 100 mm · 直径 25.4 mm", {"focal_length_mm": 100.0, "diameter_mm": 25.4})],
            ),
            "mirror": (
                "工程常用反射镜规格",
                [("圆形 12.7 mm", {"diameter_mm": 12.7}), ("圆形 25.4 mm", {"diameter_mm": 25.4})],
            ),
            "aperture": (
                "工程常用光阑规格",
                [("通光直径 4 mm", {"diameter_mm": 4.0}), ("通光直径 8 mm", {"diameter_mm": 8.0}),
                 ("通光直径 12 mm", {"diameter_mm": 12.0})],
            ),
            "fiber": (
                "工程常用光纤规格",
                [("单模 · 模场 5.6 μm · NA 0.12", {"mfd_um": 5.6, "na": 0.12}),
                 ("单模 · 模场 10.4 μm · NA 0.14", {"mfd_um": 10.4, "na": 0.14}),
                 ("多模 · 芯径 50 μm · NA 0.22", {"core_diameter_um": 50.0, "na": 0.22})],
            ),
            "detector": (
                "工程常用探测器规格",
                [("小面阵 6.4 × 4.8 mm", {"sensor_width_mm": 6.4, "sensor_height_mm": 4.8}),
                 ("大面阵 13.2 × 8.8 mm", {"sensor_width_mm": 13.2, "sensor_height_mm": 8.8})],
            ),
        }
        self._preset_kind = kind
        title, values = presets.get(kind, ("", []))
        self._preset_label.setText(title)
        self._preset_label.setVisible(bool(title))
        self.preset_box.clear()
        for label, payload in values:
            self.preset_box.addItem(label, payload)
        enabled = bool(values)
        self.preset_box.setVisible(enabled)
        self.apply_preset.setVisible(enabled)
        custom = kind == "laser"
        self.custom_value.setVisible(custom)
        if custom:
            self.custom_value.setValue(780.0)
        self.adjustSize()

    def _apply_preset(self) -> None:
        if not self._preset_kind or self.preset_box.currentIndex() < 0:
            return
        payload = self.preset_box.currentData()
        if self._preset_kind == "laser" and payload is None:
            payload = {"wavelength_nm": float(self.custom_value.value())}
        if isinstance(payload, dict):
            self.presetRequested.emit(self._preset_kind, payload)


class TeachingShell(QWidget):
    """Large teaching canvas shell.  It deliberately has no document tabs."""

    statusMessage = Signal(str)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("TeachingShell")
        self.store = SceneStore(self, start_empty=True)
        self.equipment_popup: TeachingEquipmentPopup | None = None
        self.analysis_popup: TeachingImagingCouplingPopup | None = None
        self._last_equipment_id: str | None = None
        self._teaching_result_origin = "教学示意"
        self._active_analysis = ""
        # 成像与耦合在同一个窗口里，按顺序算：光斑 → 耦合。
        self._analysis_queue: list[str] = []
        self._tool_buttons: dict[str, QToolButton] = {}
        self._engineering_contract: dict[str, Any] | None = None
        self._engineering_sync_scene_revision: int | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("TeachingToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(10, 5, 10, 5)
        row.setSpacing(5)
        # 属性和成像与耦合的快捷入口固定在画布右侧；结果直接在成像与耦合窗口呈现。
        for key, title in (("scheme", "方案"), ("equipment", "器材库"), ("display", "视角"), ("analysis", "成像与耦合"), ("calculate", "计算"), ("sync_to_simulation", "同步到仿真"), ("sync_from_simulation", "从仿真更新")):
            button = QToolButton()
            button.setText(title)
            button.setObjectName("TeachingToolButton")
            button.setCheckable(key in {"equipment", "analysis"})
            if key == "scheme":
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                scheme_menu = QMenu(button)
                for count, label in ((1, "单透镜"), (2, "双透镜"), (3, "三透镜"), (4, "四非球面 · 780 nm 高效耦合")):
                    action = scheme_menu.addAction(label)
                    action.triggered.connect(lambda _checked=False, value=count: self._apply_scheme(value))
                button.setMenu(scheme_menu)
            button.clicked.connect(lambda _checked=False, value=key: self._toolbar_action(value))
            row.addWidget(button)
            self._tool_buttons[key] = button
        row.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("TeachingStatus")
        row.addWidget(self.status)
        row.addWidget(QLabel("画布"))
        self.canvas_mode = QComboBox()
        self.canvas_mode.setObjectName("TeachingCanvasMode")
        self.canvas_mode.addItems(["二维", "三维"])
        self.canvas_mode.setToolTip("切换中央画布视图，不把二维和三维压缩成上下两栏")
        self.canvas_mode.currentTextChanged.connect(self._canvas_mode_changed)
        row.addWidget(self.canvas_mode)
        root.addWidget(toolbar)
        self.scene = BenchScene(self.store, self)
        self.scene.moved.connect(self._scene_item_moved)
        self.view = BenchView(self.scene, self)
        try:
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is not None and QApplication.instance().platformName() == "offscreen":
                raise RuntimeError("当前运行平台为 offscreen，跳过 3D 视口")
            self.view3d = BenchView3D(self.store, self)
        except Exception as exc:
            self.view3d = QLabel(f"3D 视口不可用：{exc}", self)
            self.view3d.setObjectName("Teaching3DFallback")
        self.view_stack = QStackedWidget(self)
        self.view_stack.addWidget(self.view)
        self.view_stack.addWidget(self.view3d)
        self.inspector = Inspector(self.store, self)
        self.inspector.setWindowFlags(Qt.WindowType.Tool)
        self.inspector.setWindowTitle("当前对象")
        self.inspector.hide()
        self.inspector.publishRequested.connect(lambda: self._toolbar_action("sync_to_simulation"))
        self.controller = ComputationController(
            self.store,
            gateway=FormalTeachingGateway(
                engineering_request_provider=self._engineering_request_for_current_scene,
            ),
            parent=self,
        )
        self.controller.stateChanged.connect(self._on_compute_state)
        self.controller.previewReady.connect(self._apply_preview_rays)
        self.controller.resultReady.connect(self._on_formal_result)
        root.addWidget(self.view_stack, 1)
        self._create_canvas_actions()
        self._create_quick_actions()
        self._install_teaching_shortcuts()
        self.store.sceneChanged.connect(self._scene_changed)
        # 选中器件只更新选择态、坐标轴和已打开的属性内容；窗口由画布右侧按钮打开。
        project_context = getattr(self.context, "project", None)
        project_changed = getattr(project_context, "project_changed", None)
        if project_changed is not None:
            project_changed.connect(self._invalidate_engineering_contract)
        payload_changed = getattr(project_context, "simulation_project_payload_changed", None)
        if payload_changed is not None:
            payload_changed.connect(self._invalidate_engineering_contract)
        self.view.fit_scene()
        reset_camera = getattr(self.view3d, "reset_camera", None)
        if callable(reset_camera):
            reset_camera()
        if not isinstance(self.view3d, QLabel):
            self.canvas_mode.setCurrentText("三维")
        self.controller.request_preview()
        bridge = getattr(self.view3d, "bridge", None)
        if bridge is not None and hasattr(bridge, "kindDropped"):
            bridge.kindDropped.connect(self._drop_component)

    def _create_canvas_actions(self) -> None:
        """Keep the two context windows reachable without crowding the toolbar."""
        self.canvas_actions = QFrame(self)
        self.canvas_actions.setObjectName("TeachingCanvasActions")
        column = QVBoxLayout(self.canvas_actions)
        column.setContentsMargins(5, 5, 5, 5)
        column.setSpacing(6)
        self._canvas_action_buttons: dict[str, QToolButton] = {}
        for key, glyph, label, tip, callback in (
            ("analysis", "intensity", "成像与耦合", "打开成像与耦合", self._show_analysis_popup),
            ("inspector", "properties", "属性", "打开当前对象属性", self._open_current_inspector),
        ):
            button = QToolButton(self.canvas_actions)
            button.setObjectName("TeachingCanvasAction")
            button.setIcon(icon(glyph, "#155EEF", 22))
            button.setIconSize(QSize(22, 22))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setToolTip(tip)
            button.setAccessibleName(label)
            button.setStatusTip(tip)
            button.clicked.connect(callback)
            column.addWidget(button)
            self._canvas_action_buttons[key] = button
        self.canvas_actions.adjustSize()
        self.canvas_actions.show()

    def _create_quick_actions(self) -> None:
        """Visible, recoverable edit controls kept at the canvas lower-right."""
        self.quick_actions = QFrame(self)
        self.quick_actions.setObjectName("TeachingQuickActions")
        row = QHBoxLayout(self.quick_actions)
        row.setContentsMargins(7, 5, 7, 5)
        row.setSpacing(6)
        self._quick_action_buttons: dict[str, QToolButton] = {}
        for key, glyph, label, tip, color, callback in (
            ("undo", "undo", "撤销", "撤销上一步", "#155EEF", self._undo_scene),
            ("redo", "redo", "下一步", "重做下一步", "#155EEF", self._redo_scene),
            ("delete", "delete", "删除", "删除当前选中器件", "#B42318", self._delete_selected),
            ("clear", "reset", "清空", "清空教学台（可撤销）", "#B42318", self._clear_scene),
        ):
            button = QToolButton(self.quick_actions)
            button.setObjectName("TeachingQuickAction")
            button.setIcon(icon(glyph, color, 22))
            button.setIconSize(QSize(22, 22))
            button.setText(label)
            button.setToolTip(tip)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(callback)
            row.addWidget(button)
            self._quick_action_buttons[key] = button
        self.quick_actions.adjustSize()
        self.quick_actions.show()
        self._position_overlay_controls()
        self._refresh_quick_actions()

    def _install_teaching_shortcuts(self) -> None:
        bindings = (
            (QKeySequence.StandardKey.Delete, self._delete_selected),
            (QKeySequence.StandardKey.Undo, self._undo_scene),
            (QKeySequence.StandardKey.Redo, self._redo_scene),
            (QKeySequence("Ctrl+Shift+Z"), self._redo_scene),
        )
        self._teaching_shortcuts: list[QShortcut] = []
        for sequence, callback in bindings:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._teaching_shortcuts.append(shortcut)

    def _position_overlay_controls(self) -> None:
        if not hasattr(self, "view_stack"):
            return
        view_origin = self.view_stack.mapTo(self, QPoint(0, 0))
        right = view_origin.x() + self.view_stack.width() - 18
        if hasattr(self, "canvas_actions"):
            self.canvas_actions.adjustSize()
            self.canvas_actions.move(
                max(10, right - self.canvas_actions.width()),
                max(view_origin.y() + 10, view_origin.y() + 18),
            )
            self.canvas_actions.raise_()
        if hasattr(self, "quick_actions"):
            self.quick_actions.adjustSize()
            bottom = view_origin.y() + self.view_stack.height() - 18
            self.quick_actions.move(
                max(10, right - self.quick_actions.width()),
                max(view_origin.y() + 10, bottom - self.quick_actions.height()),
            )
            self.quick_actions.raise_()

    def _refresh_quick_actions(self) -> None:
        if not hasattr(self, "_quick_action_buttons"):
            return
        selected = self.store.selected_component_id in self.store.components
        self._quick_action_buttons["delete"].setEnabled(selected)
        self._quick_action_buttons["undo"].setEnabled(self.store.can_undo())
        self._quick_action_buttons["redo"].setEnabled(self.store.can_redo())
        self._quick_action_buttons["clear"].setEnabled(bool(self.store.components))

    def _delete_selected(self) -> None:
        component_id = self.store.selected_component_id
        if component_id and self.store.remove_component(component_id):
            self.status.setText("已删除当前器件；可点撤销恢复")

    def _scene_item_moved(self, component_id: str, x_mm: float, y_mm: float) -> None:
        component = self.store.components.get(component_id)
        if component is not None:
            self.status.setText(f"{component.label}：沿导轨 {x_mm:.1f} mm · 横向 {y_mm:.1f} mm")

    def _open_current_inspector(self) -> None:
        """Open the inspector explicitly from the canvas-side property button."""
        if not self.inspector.isVisible():
            self._place_tool_window(self.inspector, "", corner="right")
            self.inspector.show()
        self.inspector.raise_()

    def _undo_scene(self) -> None:
        if self.store.undo():
            self.status.setText("已撤销")

    def _redo_scene(self) -> None:
        if self.store.redo():
            self.status.setText("已重做")

    def _clear_scene(self) -> None:
        self.store.clear_scene()
        self.status.setText("教学台已清空；可点撤销恢复")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_overlay_controls)

    def _invalidate_engineering_contract(self, *_args) -> None:
        """Do not retain a comparison claim after either source has changed."""
        self._engineering_contract = None
        self._engineering_sync_scene_revision = None

    def _engineering_request_for_current_scene(self) -> dict[str, Any] | None:
        if (
            not self._engineering_contract
            or self._engineering_sync_scene_revision != int(self.store.revision)
        ):
            return None
        return {
            "project": dict(self._engineering_contract.get("project") or {}),
            "options": dict(self._engineering_contract.get("options") or {}),
            "precision": str(self._engineering_contract.get("precision") or "standard"),
        }

    @staticmethod
    def _engineering_lens_groups(project: object) -> list[list[object]]:
        """Return consecutive lens-surface groups, preserving prescription order."""
        surfaces = list(getattr(project, "surfaces", ()) or ())
        groups: list[list[object]] = []
        current: list[object] = []
        current_key = ""
        for index, surface in enumerate(surfaces):
            kind = str(getattr(surface, "surface_type", "") or "").strip().lower()
            if kind in {"detector", "探测器/像面", "coordinate_break", "坐标断点"}:
                continue
            key = str(getattr(surface, "group_id", "") or "").strip() or f"pair-{index // 2 + 1}"
            if current and key != current_key:
                groups.append(current)
                current = []
            current.append(surface)
            current_key = key
        if current:
            groups.append(current)
        return groups

    def _sync_scene_from_engineering_project(self) -> None:
        from frontend_pyside.features.teaching_v2.model import BENCH_ORIGIN_X_MM

        project_context = getattr(self.context, "project", None)
        project = getattr(project_context, "project", None)
        if project is None:
            self.status.setText("当前没有仿真工程")
            return
        serialized = serialize_project(project)
        stored_payload = getattr(project_context, "simulation_project_payload", {}) or {}
        if isinstance(stored_payload, dict) and stored_payload.get("surfaces"):
            serialized = dict(stored_payload)
        source = dict(serialized.get("source") or {})
        receiver = dict(serialized.get("receiver") or {})
        system = dict(serialized)
        axis_height = float(self.store.reference.axis_height_mm)
        wavelength = float(source.get("wavelength_nm") or getattr(project, "wavelength_nm", 0.0) or 780.0)
        waist = max(0.01, float(source.get("waist_x_mm") or 0.5))
        mfd = float(receiver.get("mode_field_diameter_x_um") or getattr(project, "receiver_mfd_um", 0.0) or 5.0)
        na = float(receiver.get("na_x") or 0.12)
        # 整条光路一起右移一段台面留白（见 BENCH_ORIGIN_X_MM）：光源 x 是出光面，
        # 摆在台面左端时管身会悬空，而相对间距不变，所以光学问题不变。
        components: list[dict[str, Any]] = [
            {
                "component_id": "laser-001",
                "kind": "laser",
                "label": "工程光源",
                "pose": {"x_mm": BENCH_ORIGIN_X_MM, "y_mm": 0.0, "z_mm": axis_height},
                "params": {"wavelength_nm": wavelength, "beam_radius_mm": waist},
            }
        ]
        axial = 0.0
        for ordinal, group in enumerate(self._engineering_lens_groups(project), start=1):
            front = group[0]
            rear = group[-1] if len(group) > 1 else None
            thickness = max(0.1, float(getattr(front, "thickness_mm", 0.0) or 0.0))
            axial += thickness * 0.5
            first_radius = float(getattr(front, "radius_mm", 0.0) or 0.0)
            second_radius = float(getattr(rear, "radius_mm", 0.0) or 0.0) if rear is not None else 0.0
            aperture = float(getattr(front, "semi_aperture_mm", 0.0) or 0.0)
            label = str(getattr(front, "group_id", "") or f"L{ordinal}")
            components.append(
                {
                    "component_id": f"lens-{ordinal + 1:03d}",
                    "kind": "lens",
                    "label": f"{label} 透镜",
                    "pose": {"x_mm": BENCH_ORIGIN_X_MM + max(8.0, axial), "y_mm": 0.0, "z_mm": axis_height},
                    "params": {
                        "radius1_mm": first_radius,
                        "radius2_mm": second_radius,
                        "center_thickness_mm": thickness,
                        "material": str(getattr(front, "material", "N-BK7") or "N-BK7"),
                        "clear_aperture_mm": aperture,
                        "diameter_mm": max(2.0 * aperture, 1.0),
                        "conic": float(getattr(front, "conic", 0.0) or 0.0),
                    },
                }
            )
            axial += max(0.0, sum(float(getattr(item, "thickness_mm", 0.0) or 0.0) for item in group) - thickness * 0.5)
        image_distance = max(4.0, float(system.get("image_distance_mm") or 8.0))
        components.append(
            {
                "component_id": f"fiber-{len(components) + 1:03d}",
                "kind": "fiber",
                "label": "工程光纤接收端",
                "pose": {"x_mm": BENCH_ORIGIN_X_MM + max(24.0, axial + image_distance), "y_mm": 0.0, "z_mm": axis_height},
                "params": {"mfd_um": mfd, "na": na},
            }
        )
        snapshot = self.store.to_dict()
        snapshot.update(
            {
                "revision": int(self.store.revision) + 1,
                "components": components,
                # 基准线画在光源出光面上，和默认方案保持一致。
                "baseline_x_mm": BENCH_ORIGIN_X_MM,
                "selected_component_id": components[1]["component_id"] if len(components) > 2 else components[0]["component_id"],
                "results": {},
                "active_result_revision": None,
            }
        )
        self.store.restore_dict(snapshot, reason="从仿真更新教学台")
        contract = serialized.get("calculation_contract") if isinstance(serialized, dict) else None
        if isinstance(contract, dict) and isinstance(contract.get("options"), dict):
            self._engineering_contract = {
                "project": serialized,
                "options": dict(contract["options"]),
                "precision": str(contract.get("precision") or "standard"),
            }
            self._engineering_sync_scene_revision = int(self.store.revision)
            comparison = "后续不修改教学台时，成像和耦合将与仿真工程同处方、同数值配置。"
        else:
            self._engineering_contract = None
            self._engineering_sync_scene_revision = None
            comparison = "已载入工程处方；请先在仿真页完成一次正式计算，再更新教学台以继承数值配置。"
        self._last_equipment_id = None
        self.set_result_origin("教学示意")
        self.view.fit_scene()
        reset_camera = getattr(self.view3d, "reset_camera", None)
        if callable(reset_camera):
            reset_camera()
        self.controller.request_preview()
        self.status.setText(f"已从仿真更新 {len(components) - 2} 片透镜、波长和光纤模场；{comparison}")

    def _flash_tool_button(self, key: str) -> None:
        """动作型按钮（计算/测量/显示等）点下去要看得出来。

        这类按钮没有选中态，只有按下瞬间有反馈；补一次短亮，让"点到了"在
        松开鼠标之后仍然可见，而不是只靠右上角的状态文字。
        """
        button = self._tool_buttons.get(key)
        if button is None:
            return
        button.setProperty("flash", True)
        button.style().unpolish(button)
        button.style().polish(button)

        def clear() -> None:
            button.setProperty("flash", False)
            button.style().unpolish(button)
            button.style().polish(button)

        QTimer.singleShot(220, clear)

    def _toolbar_action(self, key: str) -> None:
        # Tool windows stay modeless, but their pressed state makes it obvious
        # which analysis or panel the user just opened.
        if key in {"equipment", "analysis"}:
            for name in {"equipment", "analysis"}:
                button = self._tool_buttons.get(name)
                if button is not None:
                    button.setChecked(name == key)
        else:
            self._flash_tool_button(key)
        if key == "equipment":
            if self.equipment_popup is None:
                self.equipment_popup = TeachingEquipmentPopup(self)
                self.equipment_popup.addRequested.connect(self._add_component)
                self.equipment_popup.presetRequested.connect(self._apply_equipment_preset)
            self._place_tool_window(self.equipment_popup, "equipment")
            self.equipment_popup.show()
            self.equipment_popup.raise_()
        elif key == "analysis":
            self._show_analysis_popup()
        elif key == "calculate":
            self.set_result_origin("近似计算")
            self.controller.request_preview()
            self.status.setText("光路示意已更新")
        elif key == "sync_to_simulation":
            payload = self.store.to_publish_dict()
            changes: dict[str, float] = {}
            for item in self.store.components.values():
                if not item.enabled:
                    continue
                if item.kind == "laser":
                    try:
                        wavelength = float(item.params.get("wavelength_nm", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        wavelength = 0.0
                    if wavelength > 0.0:
                        changes["source.wavelength_nm"] = wavelength
                elif item.kind == "fiber":
                    try:
                        mfd = float(item.params.get("mfd_um", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        mfd = 0.0
                    if mfd > 0.0:
                        changes["receiver.mode_field_diameter_x_um"] = mfd
            project_context = getattr(self.context, "project", None)
            apply_changes = getattr(project_context, "apply_parameter_changes", None)
            applied = bool(callable(apply_changes) and apply_changes(changes, reason="教学方案同步到仿真"))
            updater = getattr(self.context.project, "update_research_profile", None)
            if callable(updater):
                updater({"active_snapshot_source": "teaching", "teaching_snapshot": payload})
            if applied:
                self._invalidate_engineering_contract()
                self.status.setText(f"已同步 {len(changes)} 项可映射参数并保存教学快照；请从仿真更新后再比较指标")
            elif changes:
                self.status.setText("参数与当前仿真相同；已保存教学快照")
            else:
                self.status.setText("未发现可同步的波长或模场参数；已保存教学快照")
        elif key == "sync_from_simulation":
            self._sync_scene_from_engineering_project()
        elif key == "display":
            self._show_display_menu()
        elif key == "measure":
            self._measure_selected()

    def _apply_scheme(self, lens_count: int) -> None:
        if int(lens_count) == 4:
            # The four-lens teaching preset is the same engineering project
            # used by simulation, including receiver and numerical settings.
            # This prevents the menu from loading the old independent 808 nm
            # scene whose efficiency could not be compared with simulation.
            from frontend_pyside.state.project_context import default_project

            project_context = getattr(self.context, "project", None)
            project = default_project()
            state = SimulationFormState()
            payload = serialize_project(project, state)
            payload["calculation_contract"] = {
                "precision": str(state.calculation.precision),
                "options": state.request_options(),
            }
            project_context.set_project(project, dirty=False)
            project_context.set_simulation_project_payload(payload)
            self._sync_scene_from_engineering_project()
            self.status.setText("已载入四非球面 · 780 nm 高效耦合演示；教学与仿真共用同一计算处方")
            return
        self.store.apply_optical_scheme(int(lens_count))
        self._invalidate_engineering_contract()
        self._last_equipment_id = None
        self.set_result_origin("教学示意")
        self.view.fit_scene()
        reset_camera = getattr(self.view3d, "reset_camera", None)
        if callable(reset_camera):
            reset_camera()
        self.controller.request_preview()
        self.status.setText(f"已载入{int(lens_count)}透镜方案：808 nm 激光器 → 透镜组 → 单模光纤")

    def _show_display_menu(self) -> None:
        menu = QMenu(self)
        reset_camera = getattr(self.view3d, "reset_camera", None)
        look_top = getattr(self.view3d, "look_top", None)
        if callable(reset_camera):
            menu.addAction("重置三维视角", reset_camera)
        if callable(look_top):
            menu.addAction("俯视", look_top)
        menu.addAction("二维适配画面", self.view.fit_scene)
        button = self._tool_buttons.get("display")
        origin = button.mapToGlobal(button.rect().bottomLeft()) if button is not None else self.mapToGlobal(self.rect().topLeft())
        menu.exec(origin)

    def _measure_selected(self) -> None:
        cid = self.store.selected_component_id
        item = self.store.components.get(str(cid or ""))
        if item is None:
            self.status.setText("未选择对象")
            return
        pose = item.pose
        self.status.setText(
            f"{item.label}  沿导轨 {pose.x_mm:.1f} mm  横向 {pose.y_mm:.1f} mm  离台 {pose.z_mm:.1f} mm"
        )

    def _show_analysis_popup(self) -> None:
        popup = self.analysis_popup
        if popup is None:
            popup = TeachingImagingCouplingPopup(self)
            popup.calculateRequested.connect(self._request_formal_analysis)
            self.analysis_popup = popup
        popup.set_scene_revision(self.store.revision)
        self._place_tool_window(popup, "analysis", corner="right")
        popup.show()
        popup.raise_()

    def _request_formal_analysis(self) -> None:
        """依次算光斑和耦合：合并窗口里两块数据要来自同一轮计算处方。"""
        popup = self.analysis_popup
        if popup is None:
            return
        self._analysis_queue = ["spot", "coupling"]
        self._request_next_analysis()

    def _request_next_analysis(self) -> None:
        popup = self.analysis_popup
        if popup is None:
            self._analysis_queue = []
            return
        if not self._analysis_queue:
            self._active_analysis = ""
            popup.set_running("", done=True)
            return
        analysis = self._analysis_queue.pop(0)
        self._active_analysis = analysis
        popup.set_running(analysis)
        self.set_result_origin("正式计算")
        self.controller.request_formal(analysis)

    def _on_formal_result(self, analysis: str, result: object) -> None:
        analysis = str(analysis or "")
        popup = self.analysis_popup
        if popup is not None and analysis == self._active_analysis:
            popup.set_result(analysis, result)
        self.set_result_origin("正式计算")
        if analysis == self._active_analysis:
            # 第一项算完接着算第二项，中途失败也要把窗口状态收回可用。
            self._request_next_analysis()

    def _on_compute_state(self, _state: str, message: str) -> None:
        if message:
            self.status.setText(message)
        popup = self.analysis_popup
        if popup is None or not self._active_analysis:
            return
        state = str(_state or "")
        if state == "running":
            popup.set_busy(True, message)
        elif state in {"blocked", "failed", "cancelled", "stale", "missed"}:
            popup.set_busy(False, message)
            self._analysis_queue = []
            self._active_analysis = ""
        elif state == "completed":
            popup.set_busy(False)

    def _apply_preview_rays(self, result) -> None:
        from frontend_pyside.features.teaching_v2.physics import ray_segment_to_dict

        rays = [ray_segment_to_dict(ray) for ray in getattr(result, "rays", ()) or ()]
        self.scene.set_rays(rays)
        set_rays = getattr(self.view3d, "set_rays", None)
        if callable(set_rays):
            set_rays(rays, self.store.snapshot())

    def _canvas_mode_changed(self, text: str) -> None:
        is_3d = str(text) == "三维"
        self.view_stack.setCurrentWidget(self.view3d if is_3d else self.view)
        QTimer.singleShot(0, self._position_overlay_controls)
        self.status.setText("")

    def set_result_origin(self, origin: str) -> None:
        allowed = {"教学示意", "近似计算", "正式计算"}
        value = str(origin or "教学示意")
        self._teaching_result_origin = value if value in allowed else "教学示意"

    def _place_tool_window(self, widget, button_key: str, *, corner: str = "left") -> None:
        button = self._tool_buttons.get(button_key)
        if corner == "right":
            origin = self.view_stack.mapToGlobal(self.view_stack.rect().topRight())
            widget.move(origin.x() - max(widget.width(), 320) - 8, origin.y() + 8)
            return
        if button is None:
            return
        widget.move(button.mapToGlobal(button.rect().bottomLeft()))

    def _drop_component(self, kind: str, x_mm: float, y_mm: float, z_mm: float) -> None:
        self._add_component(kind, Pose(float(x_mm), float(y_mm), float(z_mm)))

    def _add_component(self, kind: str, pose: Pose | None = None) -> None:
        mapping = {"detector": "ccd", "power": "power_meter", "camera": "ccd"}
        resolved = mapping.get(str(kind), str(kind))
        kwargs = {"pose": pose} if pose is not None else {}
        self._last_equipment_id = self.store.add_component(resolved, **kwargs)
        self.status.setText(f"已添加 {dict(PLACEABLE_KINDS).get(resolved, resolved)}")

    def _apply_equipment_preset(self, kind: str, payload: object) -> None:
        component_id = self._last_equipment_id or self.store.selected_component_id
        if not component_id or not isinstance(payload, dict):
            return
        if self.store.update_params(component_id, payload, reason=f"应用{kind}工程常用规格"):
            self.status.setText("已应用工程规格")

    def _scene_changed(self, snapshot, _reason: str = "") -> None:
        if (
            self._engineering_sync_scene_revision is not None
            and int(snapshot.revision) != int(self._engineering_sync_scene_revision)
        ):
            self._invalidate_engineering_contract()
        rays = (snapshot.results.get("geometry") or {}).get("rays") or []
        self.scene.set_rays(rays)
        set_rays = getattr(self.view3d, "set_rays", None)
        if callable(set_rays):
            set_rays(rays, snapshot)
        if self.analysis_popup is not None:
            self.analysis_popup.set_scene_revision(snapshot.revision)
        self._refresh_quick_actions()
        self._position_overlay_controls()

    def assistant_context(self) -> dict:
        snapshot = self.store.snapshot()
        return {
            "page": "教学中心",
            "current_view": "教学实验台",
            "node_count": len(getattr(snapshot, "components", ()) or ()),
            "selected_component_id": getattr(snapshot, "selected_component_id", ""),
        }
__all__ = ["KindDragButton", "TeachingImagingCouplingPopup", "TeachingAnalysisVisual", "TeachingEquipmentPopup", "TeachingShell"]
