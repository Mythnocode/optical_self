
from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from frontend_pyside.shared.performance import record_perf


class LazyResultWorkspace(QWidget):
    layoutModeChanged = Signal(str)
    presetChanged = Signal(str)
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    itemSelected = Signal(str)
    pointSelected = Signal(float, float)
    renderCompleted = Signal(int, str)

    def __init__(self, parent=None) -> None:
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
        return not data or str(data.get("kind", "empty")) == "empty"

    def ensure_loaded(self):
        if self._real is not None:
            return self._real
        started = perf_counter()
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
        return self.ensure_loaded().panes

    def set_toolbar_visible(self, visible: bool) -> None:
        self._toolbar_visible = bool(visible)
        if self._real is not None:
            self._real.set_toolbar_visible(visible)

    def set_maximize_controls_visible(self, visible: bool) -> None:
        self._maximize_visible = bool(visible)
        if self._real is not None:
            self._real.set_maximize_controls_visible(visible)

    def set_pane_header_visible(self, visible: bool) -> None:

        self._pane_header_visible = bool(visible)
        if self._real is not None:
            self._real.set_pane_header_visible(visible)

    def set_pane_title_visible(self, visible: bool) -> None:
        self._pane_title_visible = bool(visible)
        if self._real is not None:
            self._real.set_pane_title_visible(visible)

    def set_pane_source_visible(self, visible: bool) -> None:
        self._pane_source_visible = bool(visible)
        if self._real is not None:
            self._real.set_pane_source_visible(visible)

    def set_plot_tools_visible(self, visible: bool) -> None:

        self._plot_tools_visible = bool(visible)
        if self._real is not None:
            self._real.set_plot_tools_visible(visible)

    def set_footer_visible(self, visible: bool) -> None:

        self._footer_visible = bool(visible)
        if self._real is not None:
            self._real.set_footer_visible(visible)

    def set_single_view_only(self, enabled: bool = True) -> None:
        self._single_view_only = bool(enabled)
        if self._real is not None:
            self._real.set_single_view_only(enabled)

    def set_result(self, index: int, title: str, data) -> None:
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
        real = self.ensure_loaded()
        real.select_result(self._selected_result)
        return bool(real.set_optical_3d_view(preset, index=self._selected_result))

    def current_result(self) -> tuple[str, dict] | None:
        current = self._pending_results.get(int(self._selected_result))
        if current is None:
            return None
        title, data = current
        return str(title), dict(data or {})

    def current_data(self) -> dict:
        """Return selected structured plot data without forcing the heavy canvas to load."""
        current = self.current_result()
        return dict(current[1]) if current is not None else {}

    def set_layout_mode(self, text: str) -> None:
        self._layout_mode = str(text)
        if self._real is not None:
            self._real.set_layout_mode(text)

    def set_preset(self, text: str) -> None:
        self._preset = str(text)
        if self._real is not None:
            self._real.set_preset(text)

    def grab(self, *args, **kwargs):
        return self.ensure_loaded().grab(*args, **kwargs)

    @property
    def figure(self):
        if self._real is None:
            return None
        self._real.select_result(self._selected_result)
        return self._real.selected_figure

    def dispose(self) -> None:
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
        self.dispose()
        super().closeEvent(event)



ResultWorkspace = LazyResultWorkspace

__all__ = ["LazyResultWorkspace", "ResultWorkspace"]
