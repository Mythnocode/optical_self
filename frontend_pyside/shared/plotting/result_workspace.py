from __future__ import annotations

from collections.abc import Iterator, Sequence

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon
from frontend_pyside.shared.plotting.canvas import PlotCanvas
from frontend_pyside.shared.plotting.fast_heatmap import FastHeatmapWidget
from frontend_pyside.shared.plotting.plot_tools import PlotTools


class ResultPane(QFrame):
    maximizeRequested = Signal(object)
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    itemSelected = Signal(str)
    pointSelected = Signal(float, float)
    rendered = Signal(str)

    def __init__(self, title: str = "结果", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("resultPane")
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 8)
        layout.setSpacing(5)

        self.header_widget = QWidget()
        head = QHBoxLayout(self.header_widget)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName("resultTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.source = QLabel("预览")
        self.source.setProperty("tone", "info")
        head.addWidget(self.source)
        layout.addWidget(self.header_widget)

        self.canvas = PlotCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.surfaceSelected.connect(self.surfaceSelected.emit)
        self.canvas.surfaceActivated.connect(self.surfaceActivated.emit)
        self.canvas.itemSelected.connect(self.itemSelected.emit)
        self.canvas.pointSelected.connect(self.pointSelected.emit)
        self._draw_cid = self.canvas.mpl_connect("draw_event", self._on_draw_event)
        self.fast_heatmap = FastHeatmapWidget()
        self.fast_heatmap.rendered.connect(self.rendered.emit)
        self.plot_stack_widget = QWidget()
        self.plot_stack = QStackedLayout(self.plot_stack_widget)
        self.plot_stack.setContentsMargins(0, 0, 0, 0)
        self.plot_stack.addWidget(self.canvas)
        self.plot_stack.addWidget(self.fast_heatmap)
        # 图表工具固定在标题栏右侧。相同类型的结果页不再把
        # “恢复/保存/导出”放在图下方，避免每页形成不同的阅读顺序。
        self.plot_tools = PlotTools(
            self.canvas,
            prepare=self._prepare_matplotlib_export,
            pixmap_provider=self._active_pixmap,
        )
        head.addWidget(self.plot_tools)
        self.max_btn = QToolButton(self.header_widget)
        self.max_btn.setObjectName("plotIconTool")
        self.max_btn.setIcon(icon("popout", theme.TEXT_SECONDARY, 17))
        self.max_btn.setIconSize(QSize(17, 17))
        self.max_btn.setToolTip("弹出当前图")
        self.max_btn.clicked.connect(lambda: self.maximizeRequested.emit(self))
        head.addWidget(self.max_btn)
        # 兼容旧调用方：tools_widget 仍可被统一显隐，但不再额外占一行。
        self.tools_widget = self.plot_tools

        layout.addWidget(self.plot_stack_widget, 1)

        self.footer = QLabel("结果尚未加载")
        self.footer.setObjectName("helperText")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)
        self._render_key = None
        self._pending_render_key = None
        self._current_plot_data: dict = {}

    def _active_pixmap(self):
        if self.plot_stack.currentWidget() is self.fast_heatmap:
            return self.fast_heatmap.current_pixmap()
        return self.canvas.grab()

    def _prepare_matplotlib_export(self) -> None:
        if self.plot_stack.currentWidget() is self.fast_heatmap:
            self.canvas.set_plot(self._current_plot_data)

    def reset_view(self) -> None:
        if self.plot_stack.currentWidget() is self.fast_heatmap:
            self.fast_heatmap.reset_view()
        else:
            self.canvas.reset_view()

    def set_optical_3d_view(self, preset: str) -> bool:
        if self.plot_stack.currentWidget() is self.fast_heatmap:
            return False
        return bool(self.canvas.set_optical_3d_view(preset))

    def _on_draw_event(self, _event) -> None:
        key = self._pending_render_key
        if key is None:
            return
        self._pending_render_key = None
        self.rendered.emit(str(key))

    def set_result(self, title: str, data) -> None:
        self.title.setText(str(title))
        self.source.setText(data.get("source", "预览") if isinstance(data, dict) else "预览")
        render_key = data.get("render_key") if isinstance(data, dict) else None
        self._current_plot_data = dict(data or {}) if isinstance(data, dict) else {}
        if render_key is None or render_key != self._render_key:
            self._pending_render_key = str(render_key or f"{title}:{id(data)}")
            if isinstance(data, dict) and data.get("kind") in {"heatmap", "heatmap_pair", "beam_match"}:
                self.canvas._data = dict(data)
                self.plot_stack.setCurrentWidget(self.fast_heatmap)
                self.fast_heatmap.set_plot(dict(data))
                self._pending_render_key = None
            else:
                self.plot_stack.setCurrentWidget(self.canvas)
                self.canvas.set_plot(data)
            self._render_key = render_key
        elif render_key is not None:
            
            
            self.rendered.emit(str(render_key))
        summary = self._result_summary(data if isinstance(data, dict) else {})
        self.footer.setText(summary)
        self.footer.setVisible(bool(summary) and not bool(self.footer.property("forceHidden")))


    def set_header_visible(self, visible: bool) -> None:
        self.header_widget.setVisible(bool(visible))

    def set_tools_visible(self, visible: bool) -> None:
        self.tools_widget.setVisible(bool(visible))

    def set_footer_visible(self, visible: bool) -> None:
        self.footer.setVisible(bool(visible) and bool(self.footer.text()))
        self.footer.setProperty("forceHidden", not bool(visible))



    def dispose(self) -> None:

        try:
            if getattr(self, "_draw_cid", None) is not None:
                self.canvas.mpl_disconnect(self._draw_cid)
                self._draw_cid = None
        except Exception:
            pass
        try:
            self.canvas.dispose()
        except Exception:
            try:
                self.canvas.deleteLater()
            except Exception:
                pass

    @staticmethod
    def _result_summary(data: dict) -> str:
        description = str(data.get("description", "")).strip()
        kind = data.get("kind", "empty")
        if description:
            return description
        if kind in ("line", "scatter", "scatter_formula"):
            points = min(len(data.get("x", [])), len(data.get("y", [])))
            return (
                f"数据点：{points}　｜　横轴：{data.get('x_label', '—')}　｜　"
                f"纵轴：{data.get('y_label', '—')}"
            )
        if kind == "line_multi":
            return f"曲线：{len(data.get('series', []))} 条　｜　数据来源：{data.get('source', '预览')}"
        if kind in ("heatmap", "heatmap_pair"):
            z = data.get("z", data.get("z1", []))
            rows = len(z) if hasattr(z, "__len__") else 0
            cols = len(z[0]) if rows and hasattr(z[0], "__len__") else 0
            return f"网格：{rows} × {cols}　｜　数据来源：{data.get('source', '预览')}"
        if kind in {"raytrace", "raytrace_section", "raytrace3d", "optical_scene_3d"}:
            full_count = int(data.get("full_ray_count", len(data.get("rays", []))) or 0)
            display_count = int(data.get("display_ray_count", len(data.get("rays", []))) or 0)
            coordinate = (
                "三维正交工程视图"
                if kind in {"raytrace3d", "optical_scene_3d"}
                else data.get("y_label", "截面")
            )
            scale = str(data.get("scale_label", ""))
            suffix = f"　｜　{scale}" if scale else ""
            return (
                f"表面：{len(data.get('surfaces', []))}　｜　"
                f"显示光线：{display_count} / {full_count}　｜　坐标：{coordinate}{suffix}"
            )
        if kind in {"bar", "barh"}:
            return f"项目：{len(data.get('values', []))}　｜　数据来源：{data.get('source', '预览')}"
        if kind == "histogram":
            return f"样本：{len(data.get('values', []))}　｜　数据来源：{data.get('source', '正式容差分析')}"
        if kind == "target_achievement":
            return f"目标：{data.get('target', '—')}　｜　最佳候选：{data.get('best', '—')}　｜　数据来源：{data.get('source', '正式反向设计')}"
        if kind == "beeswarm":
            sample_count = data.get("sample_count")
            if not isinstance(sample_count, (int, float)):
                labels = max(1, len(data.get("labels", [])))
                sample_count = len(data.get("points", [])) // labels
            return (
                f"样本：{int(sample_count)}　｜　"
                f"特征：{len(data.get('labels', []))}　｜　数据来源：{data.get('source', '预览')}"
            )
        if kind == "beam_match":
            metrics = data.get("metrics", {}) or {}
            return (
                f"中心偏移：{metrics.get('center_offset_um', '—')} μm　｜　"
                f"X尺寸比：{metrics.get('size_ratio_x', '—')}　｜　"
                f"Y尺寸比：{metrics.get('size_ratio_y', '—')}　｜　"
                f"椭圆率：{metrics.get('ellipticity', '—')}"
            )
        if kind == "waist_position":
            return f"传播曲线：{len(data.get('series', []))} 条　｜　束腰点：{len(data.get('waist_points', []))} 个"
        if kind == "parameter_response":
            return f"采样点：{min(len(data.get('x', [])), len(data.get('y', [])))}　｜　已合并当前点、最佳点和完整仿真标记"
        if kind == "validation_scatter":
            count = min(len(data.get('actual', [])), len(data.get('predicted', [])))
            if data.get("simple"):
                return f"独立测试样本：{count}　｜　点越靠近 y=x，预测与完整仿真越一致"
            return f"独立测试样本：{count}　｜　参考线：y=x　｜　详细模式含诊断带"
        if kind == "residual":
            count = min(len(data.get('actual', data.get('predicted', []))), len(data.get('residual', [])))
            if data.get("simple"):
                return f"残差样本：{count}　｜　残差＝预测值－正式值；点应尽量围绕 0 随机分布"
            return f"残差样本：{count}　｜　残差定义：预测值－正式值　｜　详细模式含趋势与分布诊断"
        if kind == "waterfall":
            return f"解释特征：{min(len(data.get('labels', [])), len(data.get('values', [])))}　｜　从模型平均基准累加至当前预测值"
        if kind == "phase_comparison":
            return "入射相位、目标相位与相位差同图显示"
        if kind == "multi_plane_evolution":
            suffix = "（高斯拟合外推）" if data.get("derived") else ""
            return f"传播平面：{len(data.get('planes', []))} 个{suffix}"
        if kind == "energy_flow":
            values = list(data.get("cumulative", []) or [])
            return f"能量阶段：{len(values)}　｜　最终相对功率：{values[-1]:.3f}%" if values else ""
        if kind == "before_after":
            return "并列比较优化前后耦合效率、系统效率和关键参数"
        if kind == "candidate_compare":
            return f"候选结果：{len(data.get('candidates', []))} 个"
        if kind == "convergence_curve":
            return f"正式计算点：{len(data.get('x', []))} 个"
        if kind == "correlation_heatmap":
            return f"相关变量：{len(data.get('labels', []))} 个"
        if kind == "adjustment_trajectory":
            return f"调节记录：{len(data.get('x', []))} 步"
        if kind == "teaching_scan":
            return f"主动变量采样：{len(data.get('x', []))} 点　｜　同步变化量：{len(data.get('linked_series', []))} 项"
        return ""


class _PaneAccessor(Sequence):


    def __init__(self, workspace: "ResultWorkspace") -> None:
        self._workspace = workspace

    def __len__(self) -> int:
        return self._workspace.PANE_COUNT

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._workspace._ensure_pane(i) for i in range(*index.indices(len(self)))]
        normalized = int(index)
        if normalized < 0:
            normalized += len(self)
        if not 0 <= normalized < len(self):
            raise IndexError(index)
        return self._workspace._ensure_pane(normalized)

    def __iter__(self) -> Iterator[ResultPane]:
        return iter(self._workspace._created_panes())


class ResultWorkspace(QWidget):


    layoutModeChanged = Signal(str)
    presetChanged = Signal(str)
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    itemSelected = Signal(str)
    pointSelected = Signal(float, float)
    renderCompleted = Signal(int, str)

    PANE_COUNT = 4
    PRESET_LAYOUTS = {
        "几何检查": "左右双图",
        "成像质量": "左右双图",
        "耦合分析": "上下双图",
        "质量诊断": "四宫格",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._single_view_only = False
        self._maximized: ResultPane | None = None
        self._pane_slots: list[ResultPane | None] = [None] * self.PANE_COUNT
        self._pane_accessor = _PaneAccessor(self)
        self._pending_results: dict[int, tuple[str, dict]] = {}
        self._pane_header_visible = True
        self._pane_title_visible = True
        self._pane_source_visible = True
        self._plot_tools_visible = True
        self._footer_visible = True
        self._maximize_controls_visible = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.toolbar = QFrame()
        self.toolbar.setObjectName("resultToolbar")
        tools = QHBoxLayout(self.toolbar)
        tools.setContentsMargins(10, 5, 10, 5)
        tools.setSpacing(7)

        self.result_label = QLabel("结果")
        tools.addWidget(self.result_label)
        self.preset = QComboBox()
        self.preset.addItems(["自定义", *self.PRESET_LAYOUTS])
        self.preset.setToolTip("切换常用结果组合；只改变显示，不重新提交计算")
        tools.addWidget(self.preset)
        self.single_view = QComboBox()
        self.single_view.addItems([f"图 {index + 1}" for index in range(self.PANE_COUNT)])
        self.single_view.setToolTip("选择当前主图")
        tools.addWidget(self.single_view)
        self.layout_label = QLabel("布局")
        tools.addWidget(self.layout_label)
        self.mode = QComboBox()
        self.mode.addItems(["单图", "左右双图", "上下双图", "四宫格"])
        tools.addWidget(self.mode)
        self.visible_label = QLabel(f"显示 1 / {self.PANE_COUNT}")
        self.visible_label.setObjectName("helperText")
        tools.addWidget(self.visible_label)
        tools.addStretch(1)
        self.reset_btn = QToolButton(self.toolbar)
        self.reset_btn.setObjectName("plotIconTool")
        self.reset_btn.setIcon(icon("reset", theme.TEXT_SECONDARY, 17))
        self.reset_btn.setIconSize(QSize(17, 17))
        self.reset_btn.setToolTip("恢复当前图视图")
        tools.addWidget(self.reset_btn)
        root.addWidget(self.toolbar)

        self.container = QWidget()
        self.container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout = QStackedLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)

        self.grid_widget = QWidget()
        self.grid_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)

        self.max_widget = QWidget()
        self.max_layout = QVBoxLayout(self.max_widget)
        self.max_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.addWidget(self.grid_widget)
        self.container_layout.addWidget(self.max_widget)
        root.addWidget(self.container, 1)

        self.mode.currentTextChanged.connect(self._apply)
        self.single_view.currentIndexChanged.connect(self._single_view_changed)
        self.preset.currentTextChanged.connect(self._apply_preset)
        self.reset_btn.clicked.connect(self._reset_all)
        self._apply("单图")

    @property
    def panes(self) -> _PaneAccessor:
        return self._pane_accessor

    def _created_panes(self) -> list[ResultPane]:
        return [pane for pane in self._pane_slots if pane is not None]

    def _ensure_pane(self, index: int) -> ResultPane:
        pane = self._pane_slots[index]
        if pane is not None:
            return pane
        pane = ResultPane(f"结果 {index + 1}", self.grid_widget)
        pane.maximizeRequested.connect(self._toggle_maximize)
        pane.surfaceSelected.connect(self.surfaceSelected.emit)
        pane.surfaceActivated.connect(self.surfaceActivated.emit)
        pane.itemSelected.connect(self.itemSelected.emit)
        pane.pointSelected.connect(self.pointSelected.emit)
        pane.rendered.connect(lambda key, pane_index=index: self.renderCompleted.emit(pane_index, key))
        pane.set_header_visible(self._pane_header_visible)
        pane.title.setVisible(self._pane_title_visible)
        pane.source.setVisible(self._pane_source_visible)
        pane.set_tools_visible(self._plot_tools_visible)
        pane.set_footer_visible(self._footer_visible)
        pane.max_btn.setVisible(self._maximize_controls_visible)
        self._pane_slots[index] = pane
        pending = self._pending_results.get(index)
        if pending is not None:
            pane.set_result(*pending)
        return pane

    def _apply_preset(self, text: str) -> None:
        if self._single_view_only or text == "自定义":
            return
        mode = self.PRESET_LAYOUTS.get(text)
        if mode:
            self.set_layout_mode(mode)
        self.presetChanged.emit(text)

    def _single_view_changed(self, _index: int) -> None:
        if self.mode.currentText() == "单图":
            self._apply("单图")

    def _positions(self, text: str) -> list[tuple[int, int, int]]:
        if self._single_view_only or text == "单图":
            return [(self.single_view.currentIndex(), 0, 0)]
        positions = {
            "左右双图": [(0, 0), (0, 1)],
            "上下双图": [(0, 0), (1, 0)],
            "四宫格": [(0, 0), (0, 1), (1, 0), (1, 1)],
        }.get(text, [(0, 0)])
        return [(index, row, column) for index, (row, column) in enumerate(positions)]

    def _apply(self, text: str) -> None:
        if self._single_view_only and text != "单图":
            text = "单图"
        self._restore_grid(clear_only=True)
        positions = self._positions(text)
        single = text == "单图" or self._single_view_only
        for column in range(2):
            self.grid.setColumnStretch(column, 0)
        for row in range(2):
            self.grid.setRowStretch(row, 0)
        used_rows = {row for _, row, _ in positions}
        used_columns = {column for _, _, column in positions}
        for column in used_columns:
            self.grid.setColumnStretch(column, 1)
        for row in used_rows:
            self.grid.setRowStretch(row, 1)
        for pane_index, row, column in positions:
            pane = self._ensure_pane(pane_index)
            if single:
                self.grid.addWidget(pane, 0, 0, 2, 2)
            else:
                self.grid.addWidget(pane, row, column)
            pane.show()
        self.single_view.setVisible(not self._single_view_only)
        self.visible_label.setVisible(not self._single_view_only)
        self.layoutModeChanged.emit(text)

    def _toggle_maximize(self, pane: ResultPane) -> None:
        if self.container_layout.currentWidget() is self.max_widget:
            self._restore_grid()
            return
        self._maximized = pane
        self.grid.removeWidget(pane)
        self.max_layout.addWidget(pane)
        pane.show()
        pane.max_btn.setToolTip("还原图形布局")
        self.container_layout.setCurrentWidget(self.max_widget)

    def _restore_grid(self, *, clear_only: bool = False) -> None:
        pane = self._maximized
        if pane is not None:
            self.max_layout.removeWidget(pane)
            pane.max_btn.setToolTip("放大当前图")
            self._maximized = None
        self.container_layout.setCurrentWidget(self.grid_widget)
        for item_pane in self._created_panes():
            self.grid.removeWidget(item_pane)
            item_pane.hide()
        if not clear_only:
            self._apply("单图" if self._single_view_only else self.mode.currentText())

    def _reset_all(self) -> None:
        if self._maximized is not None:
            self._restore_grid()
        for pane in self._created_panes():
            pane.reset_view()

    def set_optical_3d_view(self, preset: str, *, index: int | None = None) -> bool:
        pane_index = self.single_view.currentIndex() if index is None else int(index)
        if not 0 <= pane_index < self.PANE_COUNT:
            return False
        return self._ensure_pane(pane_index).set_optical_3d_view(preset)

    def set_toolbar_visible(self, visible: bool) -> None:
        self.toolbar.setVisible(bool(visible))

    def set_maximize_controls_visible(self, visible: bool) -> None:
        self._maximize_controls_visible = bool(visible)
        if not visible and self._maximized is not None:
            self._restore_grid()
        for pane in self._created_panes():
            pane.max_btn.setVisible(bool(visible))

    def set_pane_header_visible(self, visible: bool) -> None:
        self._pane_header_visible = bool(visible)
        for pane in self._created_panes():
            pane.set_header_visible(visible)

    def set_pane_title_visible(self, visible: bool) -> None:
        self._pane_title_visible = bool(visible)
        for pane in self._created_panes():
            pane.title.setVisible(bool(visible))

    def set_pane_source_visible(self, visible: bool) -> None:
        self._pane_source_visible = bool(visible)
        for pane in self._created_panes():
            pane.source.setVisible(bool(visible))

    def set_plot_tools_visible(self, visible: bool) -> None:
        self._plot_tools_visible = bool(visible)
        for pane in self._created_panes():
            pane.set_tools_visible(visible)

    def set_footer_visible(self, visible: bool) -> None:
        self._footer_visible = bool(visible)
        for pane in self._created_panes():
            pane.set_footer_visible(visible)

    def set_single_view_only(self, enabled: bool = True) -> None:
        enabled = bool(enabled)
        if enabled == self._single_view_only:
            return
        self._single_view_only = enabled
        self.preset.setVisible(not enabled)
        self.layout_label.setVisible(not enabled)
        self.mode.setVisible(not enabled)
        self.visible_label.setVisible(not enabled)
        self.result_label.setText("主图" if enabled else "结果")
        if enabled:
            blocked = self.mode.blockSignals(True)
            self.mode.setCurrentText("单图")
            self.mode.blockSignals(blocked)
        self._apply("单图" if enabled else self.mode.currentText())

    def set_result(self, index: int, title: str, data) -> None:
        index = int(index)
        if not 0 <= index < self.PANE_COUNT:
            return
        normalized = dict(data or {}) if isinstance(data, dict) else data or {}
        self._pending_results[index] = (str(title), normalized)
        self.single_view.setItemText(index, str(title))
        pane = self._pane_slots[index]
        visible_indices = {position[0] for position in self._positions(self.mode.currentText())}
        if pane is not None or index in visible_indices:
            self._ensure_pane(index).set_result(str(title), normalized)

    def select_result(self, index: int) -> None:
        index = int(index)
        if 0 <= index < self.PANE_COUNT:
            self.single_view.setCurrentIndex(index)

    def set_layout_mode(self, text: str) -> None:
        if self._single_view_only:
            text = "单图"
        index = self.mode.findText(text)
        if index >= 0:
            self.mode.setCurrentIndex(index)
        elif text == "单图":
            self._apply("单图")

    def set_preset(self, text: str) -> None:
        if self._single_view_only:
            return
        index = self.preset.findText(text)
        if index >= 0:
            self.preset.setCurrentIndex(index)

    @property
    def selected_figure(self):
        index = max(0, min(self.single_view.currentIndex(), self.PANE_COUNT - 1))
        pane = self._ensure_pane(index)
        pane._prepare_matplotlib_export()
        return pane.canvas.figure

    def dispose(self) -> None:
        self._restore_grid(clear_only=True)
        self._pending_results.clear()
        for index, pane in enumerate(list(self._pane_slots)):
            if pane is None:
                continue
            try:
                pane.dispose()
            except Exception:
                pass
            pane.setParent(None)
            pane.deleteLater()
            self._pane_slots[index] = None

    def closeEvent(self, event) -> None:
        self.dispose()
        super().closeEvent(event)


__all__ = ["ResultPane", "ResultWorkspace"]
