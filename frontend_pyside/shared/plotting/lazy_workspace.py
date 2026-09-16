
"""结果工作区的懒加载外壳。

页面打开时先显示轻量占位控件，只有收到非空绘图数据或真正访问绘图对象
时才创建重量较大的 Matplotlib 结果工作区。这样可以降低主窗口启动时间，
同时保留与旧 ``ResultWorkspace`` 相同的调用接口。
"""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from frontend_pyside.shared.performance import record_perf


class LazyResultWorkspace(QWidget):
    """延迟创建 :class:`ResultWorkspace` 的兼容包装器。"""
    layoutModeChanged = Signal(str)
    presetChanged = Signal(str)
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    itemSelected = Signal(str)
    pointSelected = Signal(float, float)
    renderCompleted = Signal(int, str)

    def __init__(self, parent=None) -> None:
        """初始化占位页、待处理结果缓存和工作区显示选项。"""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._real = None
        self._pending_results: dict[int, tuple[str, dict]] = {}
        self._single_view_only = False
        self._toolbar_visible = True
        self._maximize_visible = True
        self._pane_header_visible = True
        self._pane_title_visible = True
        self._pane_source_visible = True
        self._plot_tools_visible = True
        self._footer_visible = True
        self._layout_mode = "单图"
        self._preset = "自定义"
        self._selected_result = 0

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.setContentsMargins(18, 18, 18, 18)
        self._message = QLabel("结果尚未生成。需要显示图形时才会加载绘图引擎。")
        self._message.setObjectName("plotLazyPlaceholder")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(self._message)
        self._load_button = QPushButton("")
        self._load_button.clicked.connect(self.ensure_loaded)
        self._load_button.hide()
        placeholder_layout.addStretch(1)
        self._layout.addWidget(self._placeholder, 1)

    @staticmethod
    def _is_empty(data: Mapping | None) -> bool:
        """判断绘图载荷是否为空结果。"""
        return not data or str(data.get("kind", "empty")) == "empty"

    def ensure_loaded(self):
        """首次需要真实绘图时创建 ResultWorkspace 并回放缓存数据。"""
        if self._real is not None:
            return self._real
        started = perf_counter()
        # 延迟导入 Matplotlib 工作区，避免应用启动时立即加载绘图库。
        from frontend_pyside.shared.plotting.result_workspace import ResultWorkspace

        real = ResultWorkspace(self)
        real.layoutModeChanged.connect(self.layoutModeChanged.emit)
        real.presetChanged.connect(self.presetChanged.emit)
        real.surfaceSelected.connect(self.surfaceSelected.emit)
        real.surfaceActivated.connect(self.surfaceActivated.emit)
        real.itemSelected.connect(self.itemSelected.emit)
        real.pointSelected.connect(self.pointSelected.emit)
        real.renderCompleted.connect(self.renderCompleted.emit)
        self._layout.replaceWidget(self._placeholder, real)
        self._placeholder.hide()
        self._placeholder.deleteLater()
        self._real = real
        real.set_single_view_only(self._single_view_only)
        real.set_toolbar_visible(self._toolbar_visible)
        real.set_maximize_controls_visible(self._maximize_visible)
        real.set_pane_header_visible(self._pane_header_visible)
        real.set_pane_title_visible(self._pane_title_visible)
        real.set_pane_source_visible(self._pane_source_visible)
        real.set_plot_tools_visible(self._plot_tools_visible)
        real.set_footer_visible(self._footer_visible)
        real.set_layout_mode(self._layout_mode)
        real.set_preset(self._preset)
        for index, (title, data) in sorted(self._pending_results.items()):
            real.set_result(index, title, data)
        real.select_result(self._selected_result)
        record_perf(
            "plot_workspace_build",
            (perf_counter() - started) * 1000.0,
            pending=len(self._pending_results),
        )
        return real

    @property
    def panes(self):
        """访问真实工作区的结果面板集合；访问本身会触发加载。"""
        return self.ensure_loaded().panes

    def set_toolbar_visible(self, visible: bool) -> None:
        """保存并同步顶部工具栏可见性。"""
        self._toolbar_visible = bool(visible)
        if self._real is not None:
            self._real.set_toolbar_visible(visible)

    def set_maximize_controls_visible(self, visible: bool) -> None:
        """保存并同步最大化按钮可见性。"""
        self._maximize_visible = bool(visible)
        if self._real is not None:
            self._real.set_maximize_controls_visible(visible)

    def set_pane_header_visible(self, visible: bool) -> None:
        """保存并同步面板标题栏可见性。"""

        self._pane_header_visible = bool(visible)
        if self._real is not None:
            self._real.set_pane_header_visible(visible)

    def set_pane_title_visible(self, visible: bool) -> None:
        """保存并同步面板标题文本可见性。"""
        self._pane_title_visible = bool(visible)
        if self._real is not None:
            self._real.set_pane_title_visible(visible)

    def set_pane_source_visible(self, visible: bool) -> None:
        """保存并同步结果来源标签可见性。"""
        self._pane_source_visible = bool(visible)
        if self._real is not None:
            self._real.set_pane_source_visible(visible)

    def set_plot_tools_visible(self, visible: bool) -> None:
        """保存并同步图表工具按钮可见性。"""

        self._plot_tools_visible = bool(visible)
        if self._real is not None:
            self._real.set_plot_tools_visible(visible)

    def set_footer_visible(self, visible: bool) -> None:
        """保存并同步底部摘要可见性。"""

        self._footer_visible = bool(visible)
        if self._real is not None:
            self._real.set_footer_visible(visible)

    def set_single_view_only(self, enabled: bool = True) -> None:
        """限制真实工作区为单图模式。"""
        self._single_view_only = bool(enabled)
        if self._real is not None:
            self._real.set_single_view_only(enabled)

    def set_result(self, index: int, title: str, data) -> None:
        """缓存或转发绘图结果；非空结果会立即加载真实工作区。"""
        index = int(index)
        normalized = dict(data or {}) if isinstance(data, Mapping) else {}
        self._pending_results[index] = (str(title), normalized)
        if self._real is not None:
            self._real.set_result(index, title, normalized)
            return
        if self._is_empty(normalized):
            # 一个懒加载工作区可能预先登记多个视图。隐藏视图的空结果不能
            # 覆盖当前视图的提示，否则用户会看到与当前页面无关的通用占位。
            if index == int(self._selected_result):
                self._message.setText(
                    str(normalized.get("message") or "当前还没有可显示的结果。")
                )
            return
        self.ensure_loaded()

    def select_result(self, index: int) -> None:
        """选择结果索引，并在真实工作区加载后同步选择状态。"""
        self._selected_result = int(index)
        if self._real is not None:
            self._real.select_result(index)
            return
        current = self._pending_results.get(self._selected_result)
        if current is not None:
            _title, data = current
            if self._is_empty(data):
                self._message.setText(str(data.get("message") or "当前还没有可显示的结果。"))

    def set_optical_3d_view(self, preset: str) -> bool:
        """确保真实工作区已加载后切换当前结果的 3D 预设。"""
        real = self.ensure_loaded()
        real.select_result(self._selected_result)
        return bool(real.set_optical_3d_view(preset, index=self._selected_result))

    def current_result(self) -> tuple[str, dict] | None:
        """读取当前结果缓存，不强制创建重量级绘图控件。"""
        current = self._pending_results.get(int(self._selected_result))
        if current is None:
            return None
        title, data = current
        return str(title), dict(data or {})

    def current_data(self) -> dict:
        """读取当前结构化绘图数据，不强制加载重量级画布。"""
        current = self.current_result()
        return dict(current[1]) if current is not None else {}

    def set_layout_mode(self, text: str) -> None:
        """保存并同步工作区布局模式。"""
        self._layout_mode = str(text)
        if self._real is not None:
            self._real.set_layout_mode(text)

    def set_preset(self, text: str) -> None:
        """保存并同步工作区布局预设。"""
        self._preset = str(text)
        if self._real is not None:
            self._real.set_preset(text)

    def grab(self, *args, **kwargs):
        """抓取当前工作区画面，必要时先加载真实控件。"""
        return self.ensure_loaded().grab(*args, **kwargs)

    @property
    def figure(self):
        """返回当前 Matplotlib Figure；快速占位状态下返回 None。"""
        if self._real is None:
            return None
        self._real.select_result(self._selected_result)
        return self._real.selected_figure

    def dispose(self) -> None:
        """清空待处理结果并释放真实工作区。"""
        self._pending_results.clear()
        real = self._real
        self._real = None
        if real is not None:
            try:
                real.dispose()
            except Exception:
                pass
            real.setParent(None)
            real.deleteLater()

    def closeEvent(self, event) -> None:
        """关闭控件前释放绘图资源。"""
        self.dispose()
        super().closeEvent(event)



ResultWorkspace = LazyResultWorkspace

__all__ = ["LazyResultWorkspace", "ResultWorkspace"]
