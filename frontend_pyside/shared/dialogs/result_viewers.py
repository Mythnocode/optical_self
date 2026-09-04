from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import Badge, PrimaryButton, SecondaryButton
from frontend_pyside.shared.plotting.canvas import PlotCanvas
from frontend_pyside.shared.plotting.plot_tools import PlotTools


_EQUAL_ASPECT_KINDS = {
    "scatter", "heatmap", "beam_match", "phase_comparison", "heatmap_pair",
}


class ScientificPlotWindow(QMainWindow):
    """统一科研图窗：显示与物理计算解耦，可独立缩放、平移和锁定快照。"""

    followChanged = Signal(bool)

    def __init__(self, title: str, data: dict, parent=None, *, follow: bool = True, allow_follow: bool = True) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._result_title = str(title)
        self._data = dict(data or {})
        self._follow = bool(follow)
        self.setWindowTitle(self._window_title())
        self.resize(1180, 760)
        self.setMinimumSize(680, 460)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        toolbar = QFrame()
        toolbar.setObjectName("viewerToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(8, 5, 8, 5)
        tools.setSpacing(5)
        self.heading = QLabel(self._result_title)
        self.heading.setObjectName("cardTitle")
        tools.addWidget(self.heading)
        self.source_badge = Badge("结果", "info")
        tools.addWidget(self.source_badge)
        tools.addStretch(1)

        self.follow_check = QCheckBox("跟随当前系统")
        self.follow_check.setChecked(self._follow)
        self.follow_check.setToolTip("开启时，主工作区得到同类新结果后更新此图；关闭后保留当前快照。")
        self.follow_check.toggled.connect(self._follow_toggled)
        self.follow_check.setVisible(bool(allow_follow))
        if not allow_follow:
            self._follow = False
        tools.addWidget(self.follow_check)
        self.pin_check = QCheckBox("置顶")
        self.pin_check.toggled.connect(self._set_always_on_top)
        tools.addWidget(self.pin_check)
        root.addWidget(toolbar)

        self.canvas = PlotCanvas()
        self.canvas.setProperty("freeWheelZoom", True)
        self.canvas.setMinimumSize(520, 340)
        root.addWidget(self.canvas, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        zoom_in = SecondaryButton("放大")
        zoom_in.clicked.connect(lambda: self.canvas.zoom_by(0.82))
        zoom_out = SecondaryButton("缩小")
        zoom_out.clicked.connect(lambda: self.canvas.zoom_by(1.22))
        reset = SecondaryButton("恢复")
        reset.clicked.connect(self.canvas.reset_view)
        self.aspect = QCheckBox("1:1")
        self.aspect.setToolTip("对点列图、光斑、场幅度/相位等二维物理图锁定 x:y=1:1；光路图默认保持工程显示比例。")
        self.aspect.toggled.connect(self.canvas.set_physical_aspect)
        bottom.addWidget(zoom_in)
        bottom.addWidget(zoom_out)
        bottom.addWidget(reset)
        bottom.addWidget(self.aspect)
        bottom.addWidget(QLabel("滚轮缩放 · 中键拖动平移"))
        bottom.addStretch(1)
        self.plot_tools = PlotTools(self.canvas)
        bottom.addWidget(self.plot_tools)
        root.addLayout(bottom)

        self.setCentralWidget(central)
        self.set_data(self._result_title, self._data, preserve_view=False)

    @property
    def follow_current(self) -> bool:
        return bool(self._follow)

    @property
    def result_title(self) -> str:
        return self._result_title

    def _window_title(self) -> str:
        state = "跟随当前系统" if self._follow else "已锁定快照"
        return f"{self._result_title} · {state}"

    def _follow_toggled(self, enabled: bool) -> None:
        self._follow = bool(enabled)
        self.setWindowTitle(self._window_title())
        self.followChanged.emit(self._follow)

    def lock_snapshot(self) -> None:
        self.follow_check.setChecked(False)

    def _set_always_on_top(self, enabled: bool) -> None:
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
        self.show()
        self.setGeometry(geometry)

    def _capture_limits(self):
        ax = getattr(self.canvas, "_axis", None)
        if ax is None:
            return None
        try:
            state = {"kind": self.canvas.data.get("kind"), "x": ax.get_xlim(), "y": ax.get_ylim()}
            if hasattr(ax, "get_zlim"):
                state.update({"z": ax.get_zlim(), "elev": ax.elev, "azim": ax.azim})
            return state
        except Exception:
            return None

    def _restore_limits(self, state) -> None:
        ax = getattr(self.canvas, "_axis", None)
        if not state or ax is None or state.get("kind") != self.canvas.data.get("kind"):
            return
        try:
            ax.set_xlim(*state["x"]); ax.set_ylim(*state["y"])
            if "z" in state and hasattr(ax, "set_zlim"):
                ax.set_zlim(*state["z"]); ax.view_init(elev=state.get("elev", ax.elev), azim=state.get("azim", ax.azim))
            self.canvas.draw_idle()
        except Exception:
            return

    def set_data(self, title: str, data: dict, *, preserve_view: bool = True) -> None:
        if not self._follow and preserve_view:
            return
        state = self._capture_limits() if preserve_view else None
        self._result_title = str(title)
        self._data = dict(data or {})
        self.heading.setText(self._result_title)
        source = str(self._data.get("source", "结果"))
        self.source_badge.setText(source)
        self.source_badge.set_tone("success" if "正式" in source else "warning" if "待" in source else "info")
        self.canvas.set_plot(self._data)
        default_equal = bool(self._data.get("equal_aspect", False)) or str(self._data.get("kind", "")) in _EQUAL_ASPECT_KINDS
        blocked = self.aspect.blockSignals(True)
        self.aspect.setChecked(default_equal)
        self.aspect.blockSignals(blocked)
        self.canvas.set_physical_aspect(default_equal)
        self._restore_limits(state)
        self.setWindowTitle(self._window_title())


# 旧名称保留，避免其他模块失效。
ImageViewerWindow = ScientificPlotWindow


class ResultCompareWindow(QMainWindow):
    def __init__(self, results: dict[str, dict], current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.results = {str(k): dict(v or {}) for k, v in results.items()}
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("结果对比")
        self.resize(1360, 780)
        self.setMinimumSize(900, 560)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        toolbar = QFrame()
        toolbar.setObjectName("viewerToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(8, 5, 8, 5)
        tools.addWidget(QLabel("左图"))
        self.left_selector = QComboBox(); self.left_selector.addItems(self.results); tools.addWidget(self.left_selector)
        tools.addWidget(QLabel("右图"))
        self.right_selector = QComboBox(); self.right_selector.addItems(self.results); tools.addWidget(self.right_selector)
        tools.addStretch(1)
        reset = SecondaryButton("恢复两图")
        reset.clicked.connect(self._reset)
        tools.addWidget(reset)
        root.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.left_canvas = PlotCanvas(); self.left_canvas.setProperty("freeWheelZoom", True); self.left_canvas.setMinimumSize(420, 340)
        self.right_canvas = PlotCanvas(); self.right_canvas.setProperty("freeWheelZoom", True); self.right_canvas.setMinimumSize(420, 340)
        splitter.addWidget(self.left_canvas); splitter.addWidget(self.right_canvas)
        splitter.setSizes([650, 650])
        root.addWidget(splitter, 1)

        footer = QLabel("滚轮缩放；中键拖动平移。窗口不足时保持图窗最小尺寸，不强行把物理图压缩变形。")
        footer.setObjectName("helperText")
        root.addWidget(footer)

        keys = list(self.results)
        if current in keys:
            self.left_selector.setCurrentText(current)
        if len(keys) > 1:
            right = keys[1] if keys[0] == self.left_selector.currentText() else keys[0]
            self.right_selector.setCurrentText(right)
        self.left_selector.currentTextChanged.connect(self._render)
        self.right_selector.currentTextChanged.connect(self._render)
        self._render()
        self.setCentralWidget(central)

    def _render(self) -> None:
        left = self.left_selector.currentText(); right = self.right_selector.currentText()
        self.left_canvas.set_plot(self.results.get(left, {"kind": "empty", "message": "无结果"}))
        self.right_canvas.set_plot(self.results.get(right, {"kind": "empty", "message": "无结果"}))

    def _reset(self) -> None:
        self.left_canvas.reset_view(); self.right_canvas.reset_view()


class ComprehensiveResultsWindow(QMainWindow):
    """通用比较集：2～4 项平铺，更多结果使用“焦点 + 参考”布局。"""

    MAX_SLOTS = 6

    def __init__(self, results: dict[str, dict], current: str = "", parent=None, *, initial_mode: str = "") -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.results = {str(k): dict(v or {}) for k, v in results.items()}
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("比较集")
        self.resize(1540, 920)
        self.setMinimumSize(1040, 700)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        toolbar = QFrame()
        toolbar.setObjectName("viewerToolbar")
        top = QHBoxLayout(toolbar)
        top.setContentsMargins(8, 5, 8, 5)
        top.addWidget(QLabel("比较布局"))
        self.layout_selector = QComboBox()
        self.layout_selector.addItems(["两项对比", "三项对比", "四项对比", "焦点 + 参考"])
        self.layout_selector.setToolTip("2～4 项直接平铺；五项以上使用一个主图和参考带，避免所有图被压得过小。")
        top.addWidget(self.layout_selector)
        self.count_label = QLabel("")
        self.count_label.setObjectName("helperText")
        top.addWidget(self.count_label)
        top.addStretch(1)
        reset = SecondaryButton("恢复全部")
        reset.clicked.connect(self._reset)
        top.addWidget(reset)
        root.addWidget(toolbar)

        self.grid_host = QWidget()
        from PySide6.QtWidgets import QGridLayout
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        root.addWidget(self.grid_host, 1)

        self.panels: list[QFrame] = []
        self.selectors: list[QComboBox] = []
        self.canvases: list[PlotCanvas] = []
        keys = list(self.results)
        defaults: list[str] = []
        for name in (current, "端面匹配", "相位", "光束包络", "PSF", "点列图", "3D光路", "光路"):
            if name in keys and name not in defaults:
                defaults.append(name)
        defaults += [key for key in keys if key not in defaults]

        for index in range(self.MAX_SLOTS):
            panel = QFrame()
            panel.setObjectName("resultPane")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(4)
            selector = QComboBox()
            selector.addItems(keys)
            selector.setMinimumHeight(34)
            layout.addWidget(selector)
            canvas = PlotCanvas()
            canvas.setProperty("freeWheelZoom", True)
            layout.addWidget(canvas, 1)
            selector.currentTextChanged.connect(lambda _text, i=index: self._render_one(i))
            self.panels.append(panel)
            self.selectors.append(selector)
            self.canvases.append(canvas)
            if defaults:
                selector.setCurrentText(defaults[index % len(defaults)])

        self.layout_selector.currentTextChanged.connect(self._apply_layout)
        if initial_mode and self.layout_selector.findText(initial_mode) >= 0:
            self.layout_selector.setCurrentText(initial_mode)
        elif len(keys) >= 5:
            self.layout_selector.setCurrentText("焦点 + 参考")
        elif len(keys) >= 4:
            self.layout_selector.setCurrentText("四项对比")
        elif len(keys) >= 3:
            self.layout_selector.setCurrentText("三项对比")
        else:
            self.layout_selector.setCurrentText("两项对比")

        self.setCentralWidget(central)
        self._apply_layout(self.layout_selector.currentText())
        for index in range(self.MAX_SLOTS):
            self._render_one(index)

    def _clear_layout(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
        for row in range(3):
            self.grid.setRowStretch(row, 0)
        for column in range(self.MAX_SLOTS):
            self.grid.setColumnStretch(column, 0)

    def _apply_layout(self, mode: str) -> None:
        self._clear_layout()
        result_count = len(self.results)
        if mode == "两项对比":
            slots = min(2, max(1, result_count))
            positions = [(0, 0, 1, 1), (0, 1, 1, 1)][:slots]
            self.grid.setRowStretch(0, 1)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 1)
            sizes = [(430, 330)] * slots
        elif mode == "三项对比":
            slots = min(3, max(1, result_count))
            positions = [(0, 0, 2, 1), (0, 1, 1, 1), (1, 1, 1, 1)][:slots]
            self.grid.setRowStretch(0, 1); self.grid.setRowStretch(1, 1)
            self.grid.setColumnStretch(0, 2); self.grid.setColumnStretch(1, 1)
            sizes = [(560, 500), (340, 240), (340, 240)][:slots]
        elif mode == "四项对比":
            slots = min(4, max(1, result_count))
            positions = [
                (0, 0, 1, 1), (0, 1, 1, 1),
                (1, 0, 1, 1), (1, 1, 1, 1),
            ][:slots]
            self.grid.setRowStretch(0, 1); self.grid.setRowStretch(1, 1)
            self.grid.setColumnStretch(0, 1); self.grid.setColumnStretch(1, 1)
            sizes = [(390, 280)] * slots
        else:
            slots = min(self.MAX_SLOTS, max(1, result_count))
            positions = [(0, 0, 1, 5)]
            positions.extend((1, index, 1, 1) for index in range(max(0, slots - 1)))
            self.grid.setRowStretch(0, 4); self.grid.setRowStretch(1, 1)
            for column in range(5):
                self.grid.setColumnStretch(column, 1)
            sizes = [(700, 480)] + [(190, 145)] * max(0, slots - 1)

        for index, (row, column, row_span, column_span) in enumerate(positions):
            panel = self.panels[index]
            canvas = self.canvases[index]
            minimum = sizes[index]
            canvas.setMinimumSize(*minimum)
            self.grid.addWidget(panel, row, column, row_span, column_span)
            panel.show()
        self.count_label.setText(f"当前显示 {slots} 项 · 共 {result_count} 项可选")

    def _render_one(self, index: int) -> None:
        if not 0 <= index < len(self.selectors):
            return
        key = self.selectors[index].currentText()
        self.canvases[index].set_plot(self.results.get(key, {"kind": "empty", "message": "暂无结果"}))

    def _reset(self) -> None:
        for canvas in self.canvases:
            canvas.reset_view()


__all__ = ["ScientificPlotWindow", "ImageViewerWindow", "ResultCompareWindow", "ComprehensiveResultsWindow"]
