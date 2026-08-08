from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QTimer, Signal
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import Badge, SecondaryButton
from frontend_pyside.shared.components.ray_section_controls import RaySectionControls
from frontend_pyside.shared.components.result_status_widget import ResultStatusWidget
from frontend_pyside.shared.components.workbench import ThumbnailStrip
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace


class LivePreviewWorkspace(QWidget):


    resultChanged = Signal(str)
    comparisonChanged = Signal(bool)
    visibleResultsChanged = Signal(object)
    sectionOptionsChanged = Signal(dict)
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    recomputeRequested = Signal()
    diagnosticsRequested = Signal()
    renderCompleted = Signal(str, str)

    RESULT_ORDER = (
        "光路",
        "3D光路",
        "点列图",
        "PSF",
        "MTF",
        "端面匹配",
        "光束包络",
        "相位对比",
        "多平面演化",
        "能量分解",
        "束腰位置",
        "振幅",
        "相位",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._results: dict[str, dict] = {}
        self._busy = False
        self._windows: list[QWidget] = []
        self._render_quality = "平衡"
        self._disposed = False
        self._compact_navigation = False
        self._pending_thumbnail: tuple[str, str] | None = None
        self._displayed_render: tuple[str, str] | None = None
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._capture_pending_thumbnail)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        toolbar = QFrame()
        self.navigation_toolbar = toolbar
        toolbar.setObjectName("livePreviewToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(9, 5, 9, 5)
        tools.setSpacing(6)
        
        
        self.source_badge = Badge("待计算", "warning", self)
        self.source_badge.setVisible(False)
        self.result_selector = QComboBox()
        self.result_selector.setObjectName("previewResultCombo")
        self.result_selector.addItems(self.RESULT_ORDER)
        self.result_selector.setToolTip("选择结果后自动读取缓存；缺失时自动提交当前分析")
        tools.addWidget(self.result_selector, 1)
        self.details_button = SecondaryButton("诊断", self)
        self.details_button.clicked.connect(self.diagnosticsRequested.emit)
        self.details_button.setVisible(False)
        self.compare_button = SecondaryButton("对比", self)
        self.compare_button.clicked.connect(self.open_compare)
        self.compare_button.setVisible(False)
        self.viewer_button = SecondaryButton("放大", self)
        self.viewer_button.clicked.connect(self.open_current)
        self.viewer_button.setVisible(False)
        toolbar.setVisible(False)
        root.addWidget(toolbar, 0)

        self.section_controls = RaySectionControls()
        self.section_controls.setVisible(False)
        self.section_controls.optionsChanged.connect(self.sectionOptionsChanged.emit)

        self.result_status = ResultStatusWidget(self)
        self.result_status.recomputeRequested.connect(self.recomputeRequested.emit)
        self.result_status.setVisible(False)

        self.workspace = ResultWorkspace()
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_single_view_only(True)
        self.workspace.set_maximize_controls_visible(False)
        self.workspace.set_pane_header_visible(False)
        self.workspace.set_plot_tools_visible(False)
        self.workspace.set_footer_visible(False)
        self.workspace.surfaceSelected.connect(self.surfaceSelected.emit)
        self.workspace.renderCompleted.connect(self._on_workspace_rendered)
        self.workspace.surfaceActivated.connect(self.surfaceActivated.emit)
        root.addWidget(self.workspace, 1)

        self.thumbnails = ThumbnailStrip()
        self.thumbnails.set_expanded(True)
        self.thumbnails.selected.connect(self.set_current_result)
        self.thumbnails.openRequested.connect(self.open_result)
        root.addWidget(self.thumbnails, 0)

        self.status = QLabel("选择结果后自动加载；已有缓存直接显示，缺失分析自动提交。", self)
        self.status.setObjectName("previewStatus")
        self.status.setWordWrap(True)
        self.status.setVisible(False)

        self.result_selector.currentTextChanged.connect(self._selector_changed)
        self._refresh_result_navigation()
        self.set_current_result("光路")

    def set_compact_navigation(self, enabled: bool) -> None:

        enabled = bool(enabled)
        if enabled == self._compact_navigation:
            return
        self._compact_navigation = enabled
        self.navigation_toolbar.setVisible(enabled)
        self.thumbnails.setVisible(not enabled)
        if not enabled:
            self.thumbnails.set_expanded(True)

    def visible_result_keys(self) -> tuple[str, ...]:
        key = self.current_key()
        return (key,) if key else ()

    def current_key(self) -> str:
        index = self.result_selector.currentIndex()
        value = self.result_selector.itemData(index) if index >= 0 else None
        return str(value or self.result_selector.currentText()).split(" · ", 1)[0]

    def current_data(self) -> dict:
        return self._result_data(self.current_key())

    def results(self) -> dict[str, dict]:
        return {key: self._result_data(key) for key in self.RESULT_ORDER}

    def set_results(self, results: Mapping[str, dict], *, replace: bool = True) -> None:
        normalized = {str(key): dict(value or {}) for key, value in results.items()}
        if "端面匹配" not in normalized:
            legacy = normalized.get("模式重叠") or normalized.get("耦合场")
            if legacy:
                normalized["端面匹配"] = dict(legacy)
        if replace:
            self._results = normalized
        else:
            self._results.update(normalized)
        self._sync_section_controls()
        self._refresh_result_navigation()
        self._render()
        self._sync_source_badge()

    def merge_results(self, results: Mapping[str, dict]) -> None:
        self.set_results(results, replace=False)

    def section_options(self) -> dict:
        return self.section_controls.options()

    def set_render_quality(self, quality: str) -> None:
        self._render_quality = str(quality or "平衡")
        
        
        self.thumbnails.set_expanded(True)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.section_controls.setEnabled(not self._busy)
        self.result_selector.setEnabled(not self._busy)
        self.viewer_button.setEnabled(not self._busy)
        self.compare_button.setEnabled(not self._busy and self._available_result_count() > 1)
        if self._busy:
            self.result_status.set_running("后台正在补算；当前缓存结果仍保留在主图中。")
            self.source_badge.setText("后端计算中")
            self.source_badge.set_tone("warning")
            self.status.setText("后台正在补算；完成后只刷新当前主图。")
        else:
            self._sync_source_badge()

    def set_result_valid(
        self,
        *,
        version: str = "",
        generated_at: str | None = None,
        algorithm: str = "",
        sampling: str = "",
        converged: bool = True,
    ) -> None:
        self.result_status.set_valid(
            version=version,
            generated_at=generated_at,
            algorithm=algorithm,
            sampling=sampling,
            converged=converged,
        )

    def set_result_stale(self, reason: str, *, version: str = "") -> None:
        self.result_status.set_stale(reason, version=version)

    def set_result_error(self, message: str) -> None:
        self.result_status.set_error(message)

    def set_result_pending(self, message: str) -> None:
        self.result_status.set_pending(message)

    def set_selected_surface(self, index: int | None, group_id: str = "") -> None:
        self.section_controls.set_selected_surface(index, group_id)
        options = self.section_controls.options()
        if index is not None:
            options["selected_surface_index"] = int(index)
        if group_id:
            options["selected_group_id"] = str(group_id)
        self.sectionOptionsChanged.emit(options)

    def set_status(self, text: str, *, tone: str = "info") -> None:
        self.status.setText(text)
        if not self._busy:
            self.source_badge.set_tone(tone)

    def set_analysis_mode(self, enabled: bool) -> None:
        self.set_current_result("PSF" if enabled else "3D光路")

    def clear_pin(self) -> None:
        self.comparisonChanged.emit(False)

    def set_current_result(self, key: str, *, notify: bool = True) -> None:
        if key not in self.RESULT_ORDER:
            return
        blocked = self.result_selector.blockSignals(True)
        for index in range(self.result_selector.count()):
            if str(self.result_selector.itemData(index) or self.result_selector.itemText(index)).split(" · ", 1)[0] == key:
                self.result_selector.setCurrentIndex(index)
                break
        self.result_selector.blockSignals(blocked)
        self.thumbnails.set_current(key)
        self._render()
        self._sync_source_badge()
        if notify:
            self.resultChanged.emit(key)
            self.visibleResultsChanged.emit(self.visible_result_keys())

    def restore_cached_view(self) -> None:

        if self._disposed:
            return
        self._refresh_result_navigation()
        self._render()
        self._sync_source_badge()

    def _selector_changed(self, _label: str) -> None:
        key = self.current_key()
        self.thumbnails.set_current(key)
        self._render()
        self._sync_source_badge()
        self.resultChanged.emit(key)
        self.visibleResultsChanged.emit(self.visible_result_keys())

    def _sync_section_controls(self) -> None:
        ray2d = self._results.get("光路", {})
        ray3d = self._results.get("3D光路", {})
        has_formal_rays = ray2d.get("kind") == "raytrace_section" or ray3d.get("kind") in {
            "raytrace3d",
            "optical_scene_3d",
        }
        self.section_controls.setVisible(True)
        options = ray2d.get("section_options") or ray3d.get("section_options")
        if isinstance(options, dict):
            self.section_controls.set_options(options, emit=False)

    def _refresh_result_navigation(self) -> None:

        blocked = self.result_selector.blockSignals(True)
        records: list[tuple[str, str, str]] = []
        try:
            for index, key in enumerate(self.RESULT_ORDER):
                data = self._results.get(key)
                available = bool(data)
                source = str((data or {}).get("source", "待计算"))
                label = key if available else f"{key} · 待计算"
                self.result_selector.setItemData(index, key)
                self.result_selector.setItemText(index, label)
                records.append((key, source, "可用" if available else "未生成"))
        finally:
            self.result_selector.blockSignals(blocked)
        self.thumbnails.set_items(records)
        self.thumbnails.set_current(self.current_key() or "光路")
        self.compare_button.setEnabled(
            not self._busy and self._available_result_count() > 1
        )

    def _available_result_count(self) -> int:
        return sum(1 for key in self.RESULT_ORDER if self._results.get(key))

    def _result_data(self, key: str) -> dict:
        data = self._results.get(key)
        if data:
            return data
        messages = {
            "3D光路": "当前结果尚未包含正式三维光路；提交时只需补算 raytrace。",
            "点列图": "当前结果尚未计算点列图。",
            "PSF": "当前结果尚未计算 PSF。",
            "MTF": "当前结果尚未计算 MTF。",
            "端面匹配": "当前结果尚未计算端面复场与光纤模式。",
            "光束包络": "当前结果尚未计算光束包络。",
            "相位对比": "当前结果尚未计算接收面相位。",
            "多平面演化": "当前结果尚未计算或拟合多平面光斑。",
            "能量分解": "当前结果尚未返回能量分解指标。",
            "束腰位置": "当前结果尚未计算端面束径或焦面信息。",
            "振幅": "当前结果尚未计算接收面复场。",
            "相位": "当前结果尚未计算接收面复场。",
        }
        return {
            "kind": "empty",
            "message": messages.get(key, "当前结果尚未提供该视图。"),
            "description": "正在加载当前结果；已有缓存直接显示，缺失分析自动提交。",
            "source": "待计算",
            "render_key": f"empty:{key}",
        }

    def _render(self) -> None:
        key = self.current_key() or "光路"
        data = self._result_data(key)
        render_key = str(data.get("render_key", f"{key}:{data.get('source', '')}"))
        self.workspace.set_single_view_only(True)
        self._pending_thumbnail = None if self.thumbnails.has_render_key(key, render_key) else (key, render_key)
        current_render = (key, render_key)
        if current_render != self._displayed_render:
            self.workspace.set_result(0, key, data)
            self._displayed_render = current_render
        source = str(data.get("source", "待计算"))
        self.status.setText(
            f"当前主图：{key}｜来源：{source}。上方大图占满可用区域；单击下方缩略图切换，双击可独立查看。"
        )

    def _sync_source_badge(self) -> None:
        if self._busy:
            return
        source = str(self.current_data().get("source", "待计算"))
        if "正式" in source:
            self.source_badge.setText("正式结果")
            self.source_badge.set_tone("success")
        elif "待" in source:
            self.source_badge.setText("待计算")
            self.source_badge.set_tone("warning")
        else:
            self.source_badge.setText("快速预览")
            self.source_badge.set_tone("info")

    def open_current(self) -> None:
        self.open_result(self.current_key())

    def open_result(self, key: str) -> None:
        if not key:
            return
        from frontend_pyside.shared.dialogs.result_viewers import ImageViewerWindow

        window = ImageViewerWindow(key, self._result_data(key), self.window())
        self._windows.append(window)
        window.destroyed.connect(lambda *_: self._cleanup_windows())
        window.show()

    def open_compare(self) -> None:
        from frontend_pyside.shared.dialogs.result_viewers import ResultCompareWindow

        window = ResultCompareWindow(self.results(), self.current_key(), self.window())
        self._windows.append(window)
        window.destroyed.connect(lambda *_: self._cleanup_windows())
        window.show()
        self.comparisonChanged.emit(True)

    def _on_workspace_rendered(self, pane_index: int, render_key: str) -> None:
        if pane_index != 0 or self._disposed:
            return
        self.renderCompleted.emit(self.current_key(), str(render_key))
        if self._pending_thumbnail is None:
            return
        key, expected = self._pending_thumbnail
        if expected != str(render_key):
            return
        
        
        self._thumbnail_timer.start(0)

    def _capture_thumbnail(self, key: str, render_key: str) -> None:
        if self._disposed or key != self.current_key():
            return
        figure = getattr(self.workspace, "figure", None)
        if figure is not None:
            self.thumbnails.set_figure_thumbnail(key, render_key, figure)

    def _capture_pending_thumbnail(self) -> None:
        pending, self._pending_thumbnail = self._pending_thumbnail, None
        if (
            pending is not None
            and not self._disposed
            and isValid(self)
            and isValid(self.result_selector)
            and isValid(self.workspace)
        ):
            self._capture_thumbnail(*pending)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._thumbnail_timer.stop()
        self._pending_thumbnail = None
        self._displayed_render = None
        for window in list(self._windows):
            try:
                window.close()
                window.deleteLater()
            except Exception:
                pass
        self._windows.clear()
        self.thumbnails.clear_cache()
        try:
            self.workspace.dispose()
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self.dispose()
        super().closeEvent(event)

    def _cleanup_windows(self) -> None:
        self._windows = [window for window in self._windows if window is not None and not window.isHidden()]


__all__ = ["LivePreviewWorkspace"]
