from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSize, QTimer, Signal, Qt
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QWidgetAction,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import Badge, SecondaryButton
from frontend_pyside.shared.components.ray_section_controls import RaySectionControls
from frontend_pyside.shared.components.result_status_widget import ResultStatusWidget
from frontend_pyside.shared.components.workbench import ThumbnailStrip
from frontend_pyside.shared.icons import icon
from frontend_pyside.shared.plotting.lazy_workspace import ResultWorkspace
from frontend_pyside.shared.plotting.engineering_views import rebuild_multi_plane_evolution_range
from frontend_pyside.shared.plotting.analysis_metrics import detail_text, key_metrics
from frontend_pyside.features.simulation.analysis_detail_report import AnalysisDetailReport
from frontend_pyside.features.simulation.analysis_planner import VIEW_ANALYSES
from frontend_pyside.resources import theme_tokens as theme


class _AnalysisMetricStrip(QFrame):
    """Two-layer metrics: concise overview or dense detail, owned by the current plot."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisMetricStrip")
        self._detail_mode = False
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(6)

        self.overview_host = QWidget(self)
        row = QHBoxLayout(self.overview_host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.metric_labels: list[QLabel] = []
        for _ in range(6):
            label = QLabel(self.overview_host)
            label.setObjectName("analysisMetricItem")
            label.setVisible(False)
            row.addWidget(label)
            self.metric_labels.append(label)
        row.addStretch(1)
        root.addWidget(self.overview_host)

        self.detail_label = QLabel(self)
        self.detail_label.setObjectName("analysisMetricDetails")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_label.hide()
        root.addWidget(self.detail_label)
        self.hide()

    def set_detail_mode(self, enabled: bool) -> None:
        self._detail_mode = bool(enabled)
        self.overview_host.setVisible(not self._detail_mode)
        self.detail_label.setVisible(self._detail_mode and bool(self.detail_label.text().strip()))

    def set_data(self, data: Mapping[str, object] | None) -> None:
        items = key_metrics(data)
        details = detail_text(data)
        for index, label in enumerate(self.metric_labels):
            if index < len(items):
                name, value = items[index]
                label.setText(f"{name}  {value}")
                label.show()
            else:
                label.hide()
        self.detail_label.setText(details)
        self.setVisible(bool(items or details))
        self.set_detail_mode(self._detail_mode)



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
    focusRequested = Signal()

    RESULT_ORDER = (
        # 光路
        "光路", "3D光路", "光束包络",
        # 几何/成像
        "点列图", "MTF", "波前",
        # 焦面
        "PSF", "焦面截面", "光斑尺寸",
        # 复场
        "振幅", "相位", "相位对比", "多平面演化",
        # 光纤耦合
        "光纤基模", "端面匹配", "XY模场比较", "重叠贡献", "能量分解", "束腰位置",
    )
    PRIMARY_RESULTS = ("光路", "3D光路", "点列图", "PSF", "端面匹配")
    DISPLAY_LABELS = {
        "光路": "光路",
        "点列图": "点列图",
        "PSF": "焦面光斑",
        "端面匹配": "模场匹配",
        "3D光路": "三维光路",
        "MTF": "MTF",
        "波前": "波前",
        "光束包络": "光束包络",
        "相位对比": "相位对比",
        "多平面演化": "多平面演化",
        "能量分解": "能量分解",
        "束腰位置": "束腰位置",
        "振幅": "复场振幅",
        "相位": "复场相位",
        "焦面截面": "X/Y 强度截面",
        "光斑尺寸": "光斑尺寸 / 椭圆率",
        "光纤基模": "光纤基模",
        "XY模场比较": "X/Y 模场比较",
        "重叠贡献": "重叠贡献",
    }

    RESULT_GROUPS = (
        ("光路", ("光路", "3D光路", "光束包络")),
        ("几何", ("点列图", "MTF", "波前")),
        ("焦面", ("PSF", "焦面截面", "光斑尺寸")),
        ("复场", ("振幅", "相位", "相位对比", "多平面演化")),
        ("光纤", ("光纤基模", "端面匹配", "XY模场比较", "重叠贡献", "能量分解", "束腰位置")),
    )

    # 用户先选择“分析对象”，再在分析器内部切换同一类数据的观察方式。
    # 这与成熟光学软件的结果组织一致：能力不减少，但不把每一个派生量
    # 都做成平级菜单。底层结果键保持不变，避免破坏正式计算与缓存契约。
    ANALYSIS_GROUPS = (
        ("系统视图", ("光路", "3D光路")),
        ("光束传播", ("光束包络", "多平面演化", "束腰位置")),
        ("焦面分析", ("PSF", "焦面截面", "光斑尺寸")),
        ("复光场", ("振幅", "相位", "相位对比")),
        ("模场匹配", ("端面匹配", "光纤基模", "XY模场比较", "重叠贡献", "能量分解")),
        ("像质与波前", ("点列图", "PSF", "MTF", "波前")),
    )
    VIEW_TO_ANALYSIS = {view: title for title, views in ANALYSIS_GROUPS for view in views}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._results: dict[str, dict] = {}
        self._available_analyses: set[str] = set()
        self._busy = False
        self._external_preview_label = ""
        self._windows: list[QWidget] = []
        self._render_quality = "平衡"
        self._disposed = False
        self._compact_navigation = False
        self._pending_thumbnail: tuple[str, str] | None = None
        self._displayed_render: tuple[str, str] | None = None
        self._research_context: dict = {}
        self._multi_plane_range_mode = "auto"
        self._multi_plane_custom_range = (-2.0, 2.0)
        self._multi_plane_plane_count = 7
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._capture_pending_thumbnail)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.section_controls = RaySectionControls()
        self.section_controls.setVisible(True)
        self.section_controls.optionsChanged.connect(self.sectionOptionsChanged.emit)

        toolbar = QFrame()
        self.navigation_toolbar = toolbar
        toolbar.setObjectName("livePreviewToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(9, 5, 9, 5)
        tools.setSpacing(6)
        
        
        self.source_badge = Badge("待计算", "warning", self)
        self.source_badge.setVisible(True)
        tools.addWidget(self.source_badge)
        self.analysis_selector = QComboBox()
        self.analysis_selector.setObjectName("previewAnalysisCombo")
        self.analysis_selector.setToolTip("选择要回答的分析问题；每个分析器内部再切换相关视图。")
        for title, _views in self.ANALYSIS_GROUPS:
            self.analysis_selector.addItem(title, title)
        self.analysis_selector.setMinimumWidth(132)
        self.analysis_selector.setMaximumWidth(190)
        tools.addWidget(self.analysis_selector)

        self.result_selector = QComboBox()
        self.result_selector.setObjectName("previewResultCombo")
        self.result_selector.setToolTip("同一分析对象的不同观察方式；尚未计算的视图也始终保留入口。")
        self.result_selector.setMinimumWidth(150)
        tools.addWidget(self.result_selector, 1)

        self.multi_plane_range_button = QToolButton(self)
        self.multi_plane_range_button.setObjectName("compactTextTool")
        self.multi_plane_range_button.setText("范围：自动 ▾")
        self.multi_plane_range_button.setToolTip("多平面演化的轴向显示范围；参数研究仅在扫描轴向位置时可直接同步范围")
        self.multi_plane_range_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        range_menu = QMenu(self.multi_plane_range_button)
        self.multi_plane_auto_action = range_menu.addAction("自动 · 耦合焦区")
        self.multi_plane_research_action = range_menu.addAction("参数研究联动")
        self.multi_plane_custom_action = range_menu.addAction("自定义范围…")
        self.multi_plane_auto_action.triggered.connect(lambda: self._set_multi_plane_range_mode("auto"))
        self.multi_plane_research_action.triggered.connect(lambda: self._set_multi_plane_range_mode("research"))
        self.multi_plane_custom_action.triggered.connect(self._open_multi_plane_range_dialog)
        self.multi_plane_range_button.setMenu(range_menu)
        self.multi_plane_range_button.hide()
        tools.addWidget(self.multi_plane_range_button)

        self.metric_mode_group = QButtonGroup(self)
        self.metric_mode_group.setExclusive(True)
        self.overview_mode_button = SecondaryButton("概览", self)
        self.detail_mode_button = SecondaryButton("详细", self)
        for idx, button in enumerate((self.overview_mode_button, self.detail_mode_button)):
            button.setCheckable(True)
            self.metric_mode_group.addButton(button, idx)
            tools.addWidget(button)
        self.overview_mode_button.setChecked(True)

        self.details_button = SecondaryButton("诊断", self)
        self.details_button.clicked.connect(self.diagnosticsRequested.emit)
        self.details_button.setVisible(False)

        self.display_button = QToolButton(self)
        self.display_button.setObjectName("plotIconTool")
        self.display_button.setIcon(icon("settings", theme.TEXT_SECONDARY, 17))
        self.display_button.setIconSize(QSize(17, 17))
        self.display_button.setToolTip("显示设置")
        self.display_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        display_menu = QMenu(self.display_button)
        display_action = QWidgetAction(display_menu)
        display_host = QWidget()
        display_layout = QVBoxLayout(display_host)
        display_layout.setContentsMargins(10, 8, 10, 8)
        display_layout.addWidget(self.section_controls if hasattr(self, "section_controls") else QWidget())
        display_action.setDefaultWidget(display_host)
        display_menu.addAction(display_action)
        self._display_menu = display_menu
        self._display_action = display_action
        self._display_host = display_host
        self.display_button.setMenu(display_menu)

        self.view_button = QToolButton(self)
        self.view_button.setText("视图 ▾")
        self.view_button.setToolTip("三维光路快速视图")
        self.view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        view_menu = QMenu(self.view_button)
        for label, preset in (("适应全部", "all"), ("L1–L2", "l1-l2"), ("L3–L4", "l3-l4"), ("光纤端面", "fiber")):
            action = view_menu.addAction(label)
            action.triggered.connect(lambda checked=False, value=preset: self.set_optical_3d_view(value))
        self.view_button.setMenu(view_menu)
        self.view_button.setVisible(False)

        self.viewer_button = QToolButton(self)
        self.viewer_button.setObjectName("plotIconTool")
        self.viewer_button.setIcon(icon("popout", theme.TEXT_SECONDARY, 17))
        self.viewer_button.setIconSize(QSize(17, 17))
        self.viewer_button.setToolTip("在独立窗口查看当前结果")
        self.viewer_button.clicked.connect(self.open_current)
        self.reset_button = QToolButton(self)
        self.reset_button.setObjectName("plotIconTool")
        self.reset_button.setIcon(icon("reset", theme.TEXT_SECONDARY, 17))
        self.reset_button.setIconSize(QSize(17, 17))
        self.reset_button.setToolTip("恢复当前图视图")
        self.reset_button.clicked.connect(self._reset_current_view)
        self.compare_button = SecondaryButton("对比", self)
        self.compare_button.clicked.connect(self.open_compare)
        self.comprehensive_button = QToolButton(self)
        self.comprehensive_button.setObjectName("plotMoreTool")
        self.comprehensive_button.setText("更多 ▾")
        self.comprehensive_button.setToolTip("综合查看、复制、保存、导出等低频工具")
        self.comprehensive_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self.comprehensive_button)
        more_menu.addAction("综合查看", self.open_comprehensive)
        more_menu.addAction("结果对比", self.open_compare)
        more_menu.addAction("恢复当前图视图", self._reset_current_view)
        more_menu.addAction("专注当前结果", self.focusRequested.emit)
        more_menu.addSeparator()
        more_menu.addAction(icon("copy", theme.TEXT_SECONDARY, 16), "复制图片", self._copy_current_plot)
        more_menu.addAction(icon("download", theme.TEXT_SECONDARY, 16), "保存图片", self._save_current_plot)
        more_menu.addAction(icon("download", theme.TEXT_SECONDARY, 16), "导出数据", self._export_current_plot)
        more_menu.addSeparator()
        more_menu.addAction(icon("info", theme.TEXT_SECONDARY, 16), "图表信息", self._show_current_plot_info)
        self.comprehensive_button.setMenu(more_menu)
        self.focus_button = SecondaryButton("专注", self)
        self.focus_button.setToolTip("收起全局导航，扩大当前结果画布")
        self.focus_button.clicked.connect(self.focusRequested.emit)
        # 高频观察动作留在工具栏；恢复、对比和专注仍可在“更多”中直接找到，
        # 避免同一行同时出现七八个等权按钮。
        tools.addWidget(self.display_button)
        tools.addWidget(self.view_button)
        tools.addWidget(self.viewer_button)
        tools.addWidget(self.comprehensive_button)
        self.reset_button.hide()
        self.compare_button.hide()
        self.focus_button.hide()
        toolbar.setVisible(True)
        root.addWidget(toolbar, 0)

        self.result_status = ResultStatusWidget(self)
        self.result_status.recomputeRequested.connect(self.recomputeRequested.emit)
        self.result_status.setVisible(False)

        self.metric_strip = _AnalysisMetricStrip(self)
        self.overview_mode_button.clicked.connect(lambda: self._set_detail_view(False))
        self.detail_mode_button.clicked.connect(lambda: self._set_detail_view(True))
        root.addWidget(self.metric_strip, 0)

        self.detail_report = AnalysisDetailReport(self)
        self.detail_report.setVisible(False)
        self.detail_report.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.detail_report, 1)

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

        # 主图选择器是唯一的结果切换入口。缩略结果条保留为兼容对象但不再
        # 出现在页面，避免“主图下拉 + 结果预览”两套导航互相矛盾。
        self.thumbnails = ThumbnailStrip()
        self.thumbnails.hide()

        self.status = QLabel("选择结果后自动加载；已有缓存直接显示，缺失分析自动提交。", self)
        self.status.setObjectName("previewStatus")
        self.status.setWordWrap(True)
        self.status.setVisible(False)

        self.analysis_selector.currentTextChanged.connect(self._analysis_selector_changed)
        self.result_selector.currentTextChanged.connect(self._selector_changed)
        self._refresh_result_navigation()
        self.set_current_result("光路")

    def _set_detail_view(self, enabled: bool) -> None:
        """Switch between plot-first overview and data-only detailed report."""
        detail = bool(enabled)
        self.overview_mode_button.setChecked(not detail)
        self.detail_mode_button.setChecked(detail)
        # The detail page intentionally does not repeat the main plot.  This is a
        # hard UI rule modelled after professional optical analysis software.
        self.workspace.setVisible(not detail)
        self.metric_strip.setVisible((not detail) and bool(key_metrics(self.current_data())))
        self.metric_strip.set_detail_mode(False)
        self.detail_report.setVisible(detail)
        if detail:
            current = dict(self.current_data() or {})
            key = self.current_key() or "光路"
            label = self.DISPLAY_LABELS.get(key, key)
            current.setdefault("title", f"{label} · 详细数据")
            self.detail_report.set_data(current)

    def set_compact_navigation(self, enabled: bool) -> None:

        enabled = bool(enabled)
        if enabled == self._compact_navigation:
            return
        self._compact_navigation = enabled
        # 仿真工作区始终只保留一套主图结果选择器。
        self.navigation_toolbar.setVisible(True)
        self.thumbnails.hide()

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
        # 对比/综合查看与主图选择器共享同一套“真实可用结果”来源。
        return {key: dict(self._results[key]) for key in self.RESULT_ORDER if self._results.get(key)}

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
        # A materialised plot is definitive evidence that its backing analysis is
        # present.  Record that capability so sibling views sharing the same
        # analysis (PSF/profile/size, coupling-derived views, etc.) immediately
        # become “✓ 已有” without another backend request.
        for key, data in normalized.items():
            if data and str(data.get("kind", "empty")) != "empty":
                self._available_analyses.update(VIEW_ANALYSES.get(str(key), ()))
        self._sync_section_controls()
        self._refresh_result_navigation()
        self._render()
        self._sync_source_badge()
        self._refresh_following_windows()

    def merge_results(self, results: Mapping[str, dict]) -> None:
        self.set_results(results, replace=False)

    def set_available_analyses(self, analyses) -> None:
        self._available_analyses = {str(item) for item in (analyses or ()) if str(item)}
        self._refresh_result_navigation()

    def section_options(self) -> dict:
        return self.section_controls.options()

    def set_render_quality(self, quality: str) -> None:
        self._render_quality = str(quality or "平衡")

    def set_external_preview_state(self, active: bool, label: str = "") -> None:
        """Mark the displayed data as a temporary task candidate, never formal truth."""
        self._external_preview_label = str(label or "候选") if active else ""
        self._sync_source_badge()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.section_controls.setEnabled(not self._busy)
        # 计算期间锁定结果切换，避免用户在一个 analysis 尚未完成时连续触发
        # 多个补算请求；但导航项始终保留，并把当前缺失视图标成“计算中”。
        self.analysis_selector.setEnabled(not self._busy)
        self.result_selector.setEnabled(not self._busy)
        self.viewer_button.setEnabled(not self._busy)
        self.compare_button.setEnabled(not self._busy and self._available_result_count() > 1)
        self.comprehensive_button.setEnabled(not self._busy and self._available_result_count() > 0)
        if self._busy:
            self.result_status.set_running("后台正在补算；当前缓存结果仍保留在主图中。")
            self.source_badge.setText("后端计算中")
            self.source_badge.set_tone("warning")
            self.status.setText("后台正在补算；完成后只刷新当前主图。")
        else:
            self._sync_source_badge()
        self._refresh_result_navigation()

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
        if not self._busy:
            self._sync_source_badge()

    def set_result_stale(self, reason: str, *, version: str = "") -> None:
        self.result_status.set_stale(reason, version=version)
        if not self._busy:
            self.source_badge.setText("需更新")
            self.source_badge.set_tone("warning")

    def set_result_error(self, message: str) -> None:
        self.result_status.set_error(message)
        if not self._busy:
            self.source_badge.setText("计算异常")
            self.source_badge.set_tone("danger")

    def set_result_pending(self, message: str) -> None:
        self.result_status.set_pending(message)
        if not self._busy:
            self.source_badge.setText("待计算")
            self.source_badge.set_tone("warning")

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
        if hasattr(self, "view_button"):
            self.view_button.setVisible(key == "3D光路")
        if hasattr(self, "multi_plane_range_button"):
            self.multi_plane_range_button.setVisible(key == "多平面演化")
            if key == "多平面演化":
                self._sync_multi_plane_range_button()
        analyzer = self.VIEW_TO_ANALYSIS.get(key, "系统视图")
        blocked_analysis = self.analysis_selector.blockSignals(True)
        index = self.analysis_selector.findData(analyzer)
        if index < 0:
            index = self.analysis_selector.findText(analyzer)
        if index >= 0:
            self.analysis_selector.setCurrentIndex(index)
        self.analysis_selector.blockSignals(blocked_analysis)
        self._populate_view_selector(analyzer, preferred=key)
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

    def _analysis_selector_changed(self, label: str) -> None:
        analyzer = str(self.analysis_selector.currentData() or label or "系统视图")
        self._populate_view_selector(analyzer)
        self._selector_changed(self.result_selector.currentText())

    def _populate_view_selector(self, analyzer: str, *, preferred: str = "") -> None:
        analyzer = str(analyzer or "系统视图")
        views = next((items for title, items in self.ANALYSIS_GROUPS if title == analyzer), ("光路",))
        blocked = self.result_selector.blockSignals(True)
        try:
            self.result_selector.clear()
            for key in views:
                state, state_label = self._view_state(key)
                base = self.DISPLAY_LABELS.get(key, key)
                label = base if state == "available" else f"{base}  ·  {state_label}"
                self.result_selector.addItem(label, key)
                index = self.result_selector.count() - 1
                self.result_selector.setItemData(
                    index,
                    {
                        "available": "结果已在当前缓存中；选择后只进行懒渲染。",
                        "computable": "选择后只补算该视图所需分析；入口不会因尚未计算而消失。",
                        "busy": "正在补算当前视图所需分析。",
                        "unavailable": "当前物理条件或后端能力不支持该视图。",
                    }[state],
                    role=Qt.ItemDataRole.ToolTipRole,
                )
            target = preferred if preferred in views else views[0]
            for index in range(self.result_selector.count()):
                if str(self.result_selector.itemData(index) or "") == target:
                    self.result_selector.setCurrentIndex(index)
                    break
            self.result_selector.setEnabled(not self._busy)
        finally:
            self.result_selector.blockSignals(blocked)

    def _selector_changed(self, _label: str) -> None:
        key = self.current_key()
        if hasattr(self, "view_button"):
            self.view_button.setVisible(key == "3D光路")
        if hasattr(self, "multi_plane_range_button"):
            self.multi_plane_range_button.setVisible(key == "多平面演化")
            if key == "多平面演化":
                self._sync_multi_plane_range_button()
        self.thumbnails.set_current(key)
        self._render()
        self._sync_source_badge()
        self.resultChanged.emit(key)
        self.visibleResultsChanged.emit(self.visible_result_keys())

    def set_research_context(self, context: Mapping[str, object] | None) -> None:
        self._research_context = dict(context or {})
        self._sync_multi_plane_range_button()
        if self.current_key() == "多平面演化" and self._multi_plane_range_mode == "research":
            self._render()

    def _research_axial_range(self) -> tuple[float, float] | None:
        scan = self._research_context.get("active_parameter_scan")
        if not isinstance(scan, Mapping):
            return None
        path = str(scan.get("path", "") or "")
        unit = str(scan.get("unit", "") or "")
        if path != "receiver.axial_offset_z_mm" or unit not in {"", "mm"}:
            return None
        try:
            start = float(scan.get("start"))
            stop = float(scan.get("stop"))
        except (TypeError, ValueError):
            return None
        if not (start < stop or stop < start):
            return None
        return tuple(sorted((start, stop)))

    def _set_multi_plane_range_mode(self, mode: str) -> None:
        mode = str(mode or "auto")
        if mode == "research" and self._research_axial_range() is None:
            mode = "auto"
        self._multi_plane_range_mode = mode
        self._sync_multi_plane_range_button()
        if self.current_key() == "多平面演化":
            self._render()

    def _sync_multi_plane_range_button(self) -> None:
        button = getattr(self, "multi_plane_range_button", None)
        if button is None:
            return
        research_range = self._research_axial_range()
        self.multi_plane_research_action.setEnabled(research_range is not None)
        self.multi_plane_research_action.setToolTip(
            "同步当前‘接收面位置’参数研究范围" if research_range is not None
            else "当前参数研究不是轴向位置扫描；仍会联动采样点预览，但不会把设计参数范围误当作传播 z 范围"
        )
        if self._multi_plane_range_mode == "research" and research_range is not None:
            button.setText(f"范围：研究 {research_range[0]:.3g}～{research_range[1]:.3g} mm ▾")
        elif self._multi_plane_range_mode == "custom":
            start, stop = self._multi_plane_custom_range
            button.setText(f"范围：{start:.3g}～{stop:.3g} mm ▾")
        else:
            button.setText("范围：自动焦区 ▾")

    def _open_multi_plane_range_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("多平面演化范围")
        dialog.setModal(True)
        dialog.setSizeGripEnabled(True)
        dialog.resize(420, 250)
        dialog.setMinimumSize(360, 220)
        root = QVBoxLayout(dialog)
        hint = QLabel("自定义的是传播坐标 z 范围。普通焦距、曲率、空气间隔等参数扫描只联动采样状态，不会直接映射成 z 范围。")
        hint.setWordWrap(True)
        hint.setObjectName("mutedText")
        root.addWidget(hint)
        form = QFormLayout()
        start = QDoubleSpinBox(dialog); stop = QDoubleSpinBox(dialog)
        for widget in (start, stop):
            widget.setRange(-1.0e6, 1.0e6); widget.setDecimals(4); widget.setSuffix(" mm")
        start.setValue(float(self._multi_plane_custom_range[0])); stop.setValue(float(self._multi_plane_custom_range[1]))
        count = QSpinBox(dialog); count.setRange(3, 15); count.setValue(int(self._multi_plane_plane_count))
        form.addRow("起点", start); form.addRow("终点", stop); form.addRow("平面数", count)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        a, b = sorted((float(start.value()), float(stop.value())))
        if abs(b - a) < 1.0e-9:
            b = a + 1.0e-3
        self._multi_plane_custom_range = (a, b)
        self._multi_plane_plane_count = int(count.value())
        self._multi_plane_range_mode = "custom"
        self._sync_multi_plane_range_button()
        self._render()

    def _multi_plane_display_data(self, data: Mapping[str, object]) -> dict:
        mode = self._multi_plane_range_mode
        if mode == "research":
            requested = self._research_axial_range()
            if requested is not None:
                result = rebuild_multi_plane_evolution_range(data, requested[0], requested[1], self._multi_plane_plane_count)
                result["range_source"] = "参数研究联动"
                return result
        if mode == "custom":
            start, stop = self._multi_plane_custom_range
            result = rebuild_multi_plane_evolution_range(data, start, stop, self._multi_plane_plane_count)
            result["range_source"] = "自定义"
            return result
        result = dict(data)
        result["range_source"] = "自动焦区"
        return result

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

    def _view_state(self, key: str) -> tuple[str, str]:
        """Return a stable, user-facing lazy-result state for ``key``.

        Result navigation is a capability catalogue, not a list of already
        materialised plots.  Missing plots therefore remain selectable.
        """
        data = self._results.get(key)
        if data and str(data.get("kind", "empty")) != "empty":
            return "available", "已有"
        required = set(VIEW_ANALYSES.get(key, ()))
        if not required and key not in VIEW_ANALYSES:
            return "unavailable", "当前不可用"
        # analysis 数据已经存在时，即使这张图的 Plot dict 还没有物化，
        # 也属于“已有”：选中后只在前端派生/绘图，不再提交物理任务。
        if required and required.issubset(self._available_analyses):
            return "available", "已有"
        if self._busy and key == (self.current_key() or "光路"):
            return "busy", "计算中"
        return "computable", "点此计算"

    def _refresh_result_navigation(self) -> None:
        current = self.current_key() or "光路"
        analyzer = self.VIEW_TO_ANALYSIS.get(current, "系统视图")
        blocked = self.analysis_selector.blockSignals(True)
        try:
            index = self.analysis_selector.findData(analyzer)
            if index < 0:
                index = self.analysis_selector.findText(analyzer)
            if index >= 0:
                self.analysis_selector.setCurrentIndex(index)
        finally:
            self.analysis_selector.blockSignals(blocked)
        self._populate_view_selector(analyzer, preferred=current)

        primary_records: list[tuple[str, str, str, str]] = []
        for key in self.PRIMARY_RESULTS:
            data = self._results.get(key) or {}
            _state, state_label = self._view_state(key)
            base = self.DISPLAY_LABELS.get(key, key)
            source = str(data.get("source", "待计算"))
            primary_records.append((key, source, state_label, base))
        self.thumbnails.set_items(primary_records)
        self.thumbnails.set_current(current if current in self.PRIMARY_RESULTS else "光路")
        available = self._available_result_count()
        self.compare_button.setEnabled(not self._busy and available > 1)
        self.comprehensive_button.setEnabled(not self._busy and available > 0)

    def _current_plot_tools(self):
        try:
            return self.workspace.panes[0].plot_tools
        except Exception:
            return None

    def _copy_current_plot(self) -> None:
        tools = self._current_plot_tools()
        if tools is not None:
            tools.copy_image()

    def _save_current_plot(self) -> None:
        tools = self._current_plot_tools()
        if tools is not None:
            tools.save_image()

    def _export_current_plot(self) -> None:
        tools = self._current_plot_tools()
        if tools is not None:
            tools.export_data()

    def _show_current_plot_info(self) -> None:
        tools = self._current_plot_tools()
        if tools is not None:
            tools.show_info()

    def _reset_current_view(self) -> None:
        try:
            self.workspace.panes[0].reset_view()
        except Exception:
            pass

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
            "焦面截面": "当前结果尚未计算焦面二维强度。",
            "光斑尺寸": "当前结果尚未计算焦面二维强度。",
            "光纤基模": "当前结果尚未计算光纤目标模式。",
            "XY模场比较": "当前结果尚未计算端面复场与光纤模式。",
            "重叠贡献": "当前结果尚未计算带相位的复场重叠。",
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
        if key == "多平面演化" and str(data.get("kind", "")) == "multi_plane_evolution":
            data = self._multi_plane_display_data(data)
        render_key = str(data.get("render_key", f"{key}:{data.get('source', '')}:{data.get('range_mm', '')}"))
        self.workspace.set_single_view_only(True)
        self._pending_thumbnail = None if self.thumbnails.has_render_key(key, render_key) else (key, render_key)
        current_render = (key, render_key)
        if current_render != self._displayed_render:
            self.workspace.set_result(0, key, data)
            self._displayed_render = current_render
        self.metric_strip.set_data(data)
        label = self.DISPLAY_LABELS.get(key, key)
        report_data = dict(data)
        report_data.setdefault("title", f"{label} · 详细数据")
        self.detail_report.set_data(report_data)
        self._set_detail_view(self.detail_mode_button.isChecked())
        source = str(data.get("source", "待计算"))
        self.status.setText(f"当前结果：{label}｜来源：{source}")

    def _sync_source_badge(self) -> None:
        if self._busy:
            return
        if self._external_preview_label:
            self.source_badge.setText("候选预览")
            self.source_badge.set_tone("warning")
            self.source_badge.setToolTip(f"临时预览：{self._external_preview_label}；尚未写入当前系统，也不是正式结果。")
            return
        self.source_badge.setToolTip("")
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


    def set_optical_3d_view(self, preset: str = "all") -> None:
        """Switch to formal 3D optical layout and apply a non-destructive view preset."""
        if self.current_key() != "3D光路":
            self.set_current_result("3D光路")
        def apply_view():
            try:
                if not self.workspace.set_optical_3d_view(preset):
                    self.set_status("当前三维光路尚未加载，生成正式三维结果后可使用快速视图。", tone="warning")
            except Exception as exc:
                self.set_status(f"三维视图调整失败：{exc}", tone="warning")
        QTimer.singleShot(0, apply_view)

    def open_current(self) -> None:
        self.open_result(self.current_key())

    def open_result(self, key: str) -> None:
        if not key:
            return
        from frontend_pyside.shared.dialogs.result_viewers import ScientificPlotWindow
        title = self.DISPLAY_LABELS.get(key, key)
        window = ScientificPlotWindow(title, self._result_data(key), self.window(), follow=True)
        window._result_key = key
        self._windows.append(window)
        window.destroyed.connect(lambda *_: self._cleanup_windows())
        window.show()

    def _refresh_following_windows(self) -> None:
        self._cleanup_windows()
        for window in list(self._windows):
            key = str(getattr(window, "_result_key", ""))
            if not key or not hasattr(window, "set_data") or not bool(getattr(window, "follow_current", False)):
                continue
            window.set_data(self.DISPLAY_LABELS.get(key, key), self._result_data(key), preserve_view=True)

    def open_compare(self) -> None:
        from frontend_pyside.shared.dialogs.result_viewers import ComprehensiveResultsWindow
        available = self._available_result_count()
        initial = "三项对比" if available >= 3 else "两项对比"
        window = ComprehensiveResultsWindow(self.results(), self.current_key(), self.window(), initial_mode=initial)
        self._windows.append(window)
        window.destroyed.connect(lambda *_: self._cleanup_windows())
        window.show()
        self.comparisonChanged.emit(True)

    def open_comprehensive(self) -> None:
        from frontend_pyside.shared.dialogs.result_viewers import ComprehensiveResultsWindow
        initial = "焦点 + 参考" if self._available_result_count() >= 5 else "四项对比"
        window = ComprehensiveResultsWindow(self.results(), self.current_key(), self.window(), initial_mode=initial)
        self._windows.append(window)
        window.destroyed.connect(lambda *_: self._cleanup_windows())
        window.showMaximized()

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
        self._windows = [window for window in self._windows if window is not None and isValid(window)]


__all__ = ["LivePreviewWorkspace"]
