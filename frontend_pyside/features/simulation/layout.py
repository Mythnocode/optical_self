
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.components.quick_lens_editor import QuickLensEditor
from frontend_pyside.features.simulation.live_preview import LivePreviewWorkspace
from frontend_pyside.features.simulation.panels import SimpleParameterTabs
from frontend_pyside.shared.components.basic import (
    Badge,
    CollapsiblePanel,
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.workbench import SideDetailDrawer
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared import layout_tokens as ui_layout


@dataclass(slots=True)
class SimulationWidgets:
    root: QVBoxLayout
    model_badge: Badge
    preview_button: SecondaryButton
    formal_button: PrimaryButton
    parameter_research_button: SecondaryButton
    tolerance_analysis_button: SecondaryButton
    parameter_toggle_button: SecondaryButton
    lens_editor_button: SecondaryButton
    save_parameters_button: SecondaryButton
    import_teaching_button: SecondaryButton
    teaching_button: SecondaryButton
    mode_bar: QFrame
    multipath_button: QToolButton
    multipath_toggle: QCheckBox
    auto_preview: QCheckBox
    preview_state: Badge
    formal_state: Badge
    main_splitter: QSplitter
    editor: QuickLensEditor
    params: SimpleParameterTabs
    results: LivePreviewWorkspace
    display_settings: CollapsiblePanel
    metric_frame: QFrame
    cards: dict[str, InlineMetric]
    preview_banner: QFrame
    preview_banner_title: QLabel
    preview_banner_text: QLabel
    preview_apply_button: PrimaryButton
    preview_clear_button: SecondaryButton
    formal_progress_panel: QFrame
    formal_progress_label: QLabel
    formal_progress_bar: QProgressBar
    apply_alignment_button: SecondaryButton
    diagnostic_text: QLabel
    detail_drawer: SideDetailDrawer
    result_splitter: QSplitter


def _build_diagnostics_panel() -> tuple[QWidget, QLabel]:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(ui_layout.CARD_PADDING, ui_layout.CARD_PADDING, ui_layout.CARD_PADDING, ui_layout.CARD_PADDING)
    layout.setSpacing(ui_layout.CONTROL_GAP)
    diagnostic_text = QLabel("详细物理指标、收敛数据与数值质量将在正式结果返回后显示。")
    diagnostic_text.setObjectName("drawerText")
    diagnostic_text.setWordWrap(True)
    diagnostic_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(diagnostic_text)
    layout.addStretch(1)
    return panel, diagnostic_text


def _build_result_actions(
    save_parameters_button: SecondaryButton,
    teaching_button: SecondaryButton,
) -> tuple[QWidget, SecondaryButton, QCheckBox]:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(ui_layout.CARD_PADDING, ui_layout.CARD_PADDING, ui_layout.CARD_PADDING, ui_layout.CARD_PADDING)
    layout.setSpacing(ui_layout.CONTROL_GAP)

    tool_title = QLabel("其他操作")
    tool_title.setObjectName("mutedText")
    layout.addWidget(tool_title)
    layout.addWidget(save_parameters_button)
    layout.addWidget(teaching_button)

    multipath_toggle = QCheckBox("多路径计算")
    multipath_toggle.setToolTip("高级选项：启用后下一次完整计算使用多路径后端。")
    layout.addWidget(multipath_toggle)

    apply_alignment_button = SecondaryButton("应用五轴最优值")
    apply_alignment_button.setVisible(False)
    layout.addWidget(apply_alignment_button)
    layout.addStretch(1)
    return panel, apply_alignment_button, multipath_toggle


def build_simulation_layout(page: QWidget, context) -> SimulationWidgets:
    root = QVBoxLayout(page)
    # Simulation is the one ordinary workspace that intentionally gives more
    # area to the canvas than to page chrome.
    root.setContentsMargins(16, ui_layout.CONTROL_GAP, 16, 16)
    root.setSpacing(ui_layout.CONTROL_GAP)

    model_badge = Badge("正式仿真由后端执行", "info")
    model_badge.setVisible(False)
    lens_editor_button = SecondaryButton("编辑光路")
    lens_editor_button.setIcon(icon("list", theme.PRIMARY, 16))
    preview_button = SecondaryButton("预览")
    preview_button.setIcon(icon("reset", theme.PRIMARY, 16))
    formal_button = PrimaryButton("开始计算")
    formal_button.setIcon(icon("check", theme.TEXT_INVERSE, 16))
    formal_button.setVisible(True)

    mode_bar = QFrame()
    mode_bar.setObjectName("simulationModeToolbar")
    mode_layout = QHBoxLayout(mode_bar)
    mode_layout.setContentsMargins(ui_layout.CONTROL_GAP, 4, ui_layout.CONTROL_GAP, 4)
    mode_layout.setSpacing(ui_layout.CONTROL_GAP)

    auto_preview = QCheckBox("自动预览")
    auto_preview.setChecked(False)
    auto_preview.setToolTip("参数停止变化后只运行一次本地快速预览，不会提交后端")
    mode_layout.addWidget(auto_preview)
    mode_layout.addStretch(1)
    save_parameters_button = SecondaryButton("保存参数")
    save_parameters_button.setToolTip("保存当前参数，供后续继续编辑或教学复盘。")
    import_teaching_button = SecondaryButton("教学导入")
    import_teaching_button.setToolTip("载入教学中心最近保存的镜片结构、波长与光纤装调参数。")
    teaching_button = SecondaryButton("教学中心")
    teaching_button.setToolTip("保存当前参数并打开教学中心。")
    # 主工具栏只保留高频操作，低频操作移动到“详情 → 高级”。
    parameter_toggle_button = SecondaryButton("收起参数")
    parameter_toggle_button.setToolTip("暂时收起左侧参数，让结果图有更多空间；再次点击可恢复。")
    mode_layout.addWidget(import_teaching_button)
    mode_layout.addWidget(parameter_toggle_button)
    mode_layout.addWidget(preview_button)
    mode_layout.addWidget(formal_button)
    lens_editor_button.hide()

    multipath_button = QToolButton()
    multipath_button.setVisible(False)
    preview_state = Badge("预览需手动刷新", "info")
    preview_state.setVisible(False)
    formal_state = Badge("尚未正式计算", "warning")
    formal_state.setVisible(True)
    root.addWidget(mode_bar)

    main_splitter = QSplitter(Qt.Orientation.Horizontal)
    main_splitter.setObjectName("simulationMainSplitter")
    # The parameter forms have fixed-width engineering inputs.  Letting the
    # splitter squeeze this child below its minimum clips the right edge under
    # the result canvas; narrow windows use the explicit show/hide control.
    main_splitter.setChildrenCollapsible(False)
    main_splitter.setHandleWidth(8)
    main_splitter.setOpaqueResize(False)

    editor = QuickLensEditor(context.project)
    params = SimpleParameterTabs(editor)
    
    
    
    params.setMinimumWidth(ui_layout.SIM_PARAMETER_MIN_WIDTH)
    params.setMaximumWidth(ui_layout.SIM_PARAMETER_MAX_WIDTH)
    main_splitter.addWidget(params)
    main_splitter.setCollapsible(0, False)

    right_panel = QWidget()
    right_panel.setMinimumWidth(390)
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(ui_layout.CONTROL_GAP)

    metric_frame = QFrame()
    metric_frame.setObjectName("simulationResultSummary")
    metric_layout = QHBoxLayout(metric_frame)
    metric_layout.setContentsMargins(ui_layout.CONTROL_GAP, 4, ui_layout.CONTROL_GAP, 4)
    metric_layout.setSpacing(ui_layout.CONTROL_GAP)
    # 三类效率都是当前系统的结果状态，必须归在主页面，不使用独立/孤立小窗。
    cards = {
        "coupling_eff": InlineMetric("耦合效率", "—", "%", metric_frame),
        "system_eff": InlineMetric("系统效率", "—", "%", metric_frame),
        "receiver_eff": InlineMetric("端面效率", "—", "%", metric_frame),
    }
    for card in cards.values():
        card.setObjectName("simulationCompactMetric")
        card.setMinimumWidth(100)
        card.setMinimumHeight(36)
        card.setMaximumHeight(42)
        card.note_label.hide()
        metric_layout.addWidget(card, 1)
    metric_layout.addSpacing(4)
    metric_layout.addWidget(formal_state, 0, Qt.AlignmentFlag.AlignVCenter)
    right_layout.addWidget(metric_frame)

    # Research belongs to the current formal optical system, not to the
    # Optimization workspace.  Keep two compact first-level entries next to the
    # result system: parameter response and robustness.  The actual task content
    # is still reusable in a modeless/full task container, so no capability is
    # duplicated here.
    research_bar = QFrame()
    research_bar.setObjectName("simulationResearchToolbar")
    research_layout = QHBoxLayout(research_bar)
    research_layout.setContentsMargins(ui_layout.CONTROL_GAP, 2, ui_layout.CONTROL_GAP, 2)
    research_layout.setSpacing(ui_layout.CONTROL_GAP)
    research_label = QLabel("研究")
    research_label.setObjectName("mutedText")
    research_layout.addWidget(research_label)
    parameter_research_button = SecondaryButton("参数研究")
    parameter_research_button.setToolTip("改变当前系统参数并用正式光学计算观察响应；不会自动写回系统")
    tolerance_analysis_button = SecondaryButton("容差分析")
    tolerance_analysis_button.setToolTip("围绕当前系统或已验证候选评估制造/装调误差的统计稳健性")
    research_layout.addWidget(parameter_research_button)
    research_layout.addWidget(tolerance_analysis_button)
    research_layout.addStretch(1)
    research_context = QLabel("基于当前系统与正式仿真数值设置")
    research_context.setObjectName("mutedText")
    research_layout.addWidget(research_context)
    right_layout.addWidget(research_bar)

    preview_banner = QFrame()
    preview_banner.setObjectName("taskPreviewBanner")
    preview_banner_layout = QHBoxLayout(preview_banner)
    preview_banner_layout.setContentsMargins(10, 6, 8, 6)
    preview_banner_layout.setSpacing(8)
    preview_copy = QWidget(preview_banner)
    preview_copy_layout = QVBoxLayout(preview_copy)
    preview_copy_layout.setContentsMargins(0, 0, 0, 0)
    preview_copy_layout.setSpacing(0)
    preview_banner_title = QLabel("候选临时预览")
    preview_banner_title.setObjectName("taskPreviewTitle")
    preview_banner_text = QLabel("尚未写入当前系统")
    preview_banner_text.setObjectName("taskPreviewText")
    preview_banner_text.setWordWrap(True)
    preview_copy_layout.addWidget(preview_banner_title)
    preview_copy_layout.addWidget(preview_banner_text)
    preview_banner_layout.addWidget(preview_copy, 1)
    preview_clear_button = SecondaryButton("退出预览")
    preview_apply_button = PrimaryButton("应用到当前系统")
    preview_banner_layout.addWidget(preview_clear_button)
    preview_banner_layout.addWidget(preview_apply_button)
    preview_banner.hide()
    right_layout.addWidget(preview_banner)

    formal_progress_panel = QFrame()
    formal_progress_panel.setObjectName("taskProgressPanel")
    formal_progress_layout = QVBoxLayout(formal_progress_panel)
    formal_progress_layout.setContentsMargins(10, 6, 10, 7)
    formal_progress_layout.setSpacing(4)
    formal_progress_label = QLabel("正在准备正式仿真")
    formal_progress_label.setObjectName("taskProgressTitle")
    formal_progress_bar = QProgressBar()
    formal_progress_bar.setObjectName("taskProgressBar")
    formal_progress_bar.setRange(0, 0)
    formal_progress_bar.setTextVisible(True)
    formal_progress_layout.addWidget(formal_progress_label)
    formal_progress_layout.addWidget(formal_progress_bar)
    formal_progress_panel.hide()
    right_layout.addWidget(formal_progress_panel)

    diagnostic_panel, diagnostic_text = _build_diagnostics_panel()
    action_panel, apply_alignment_button, multipath_toggle = _build_result_actions(
        save_parameters_button, teaching_button
    )

    result_splitter = QSplitter(Qt.Orientation.Horizontal)
    result_splitter.setObjectName("simulationResultSplitter")
    result_splitter.setChildrenCollapsible(True)
    result_splitter.setHandleWidth(0)

    results = LivePreviewWorkspace()
    results.setMinimumSize(410, 320)
    # 显示设置已移动到结果画布工具栏的统一设置图标弹出层；保留隐藏对象仅兼容旧引用。
    display_settings = CollapsiblePanel("显示设置", expanded=False)
    display_settings.setObjectName("simulationDisplaySettings")
    display_settings.hide()
    result_splitter.addWidget(results)

    detail_drawer = SideDetailDrawer(
        "详细结果",
        [("结果", diagnostic_panel), ("高级", action_panel)],
        expanded=False,
    )
    detail_drawer.setVisible(True)
    result_splitter.addWidget(detail_drawer)
    result_splitter.setStretchFactor(0, 1)
    result_splitter.setStretchFactor(1, 0)
    result_splitter.setSizes([1138, 0])
    right_layout.addWidget(result_splitter, 1)

    main_splitter.addWidget(right_panel)
    main_splitter.setStretchFactor(0, 0)
    main_splitter.setStretchFactor(1, 1)
    main_splitter.setSizes([ui_layout.SIM_PARAMETER_PREFERRED_WIDTH, 1300])
    root.addWidget(main_splitter, 1)

    return SimulationWidgets(
        root=root,
        model_badge=model_badge,
        preview_button=preview_button,
        formal_button=formal_button,
        parameter_research_button=parameter_research_button,
        tolerance_analysis_button=tolerance_analysis_button,
        parameter_toggle_button=parameter_toggle_button,
        lens_editor_button=lens_editor_button,
        save_parameters_button=save_parameters_button,
        import_teaching_button=import_teaching_button,
        teaching_button=teaching_button,
        mode_bar=mode_bar,
        multipath_button=multipath_button,
        multipath_toggle=multipath_toggle,
        auto_preview=auto_preview,
        preview_state=preview_state,
        formal_state=formal_state,
        main_splitter=main_splitter,
        editor=editor,
        params=params,
        results=results,
        display_settings=display_settings,
        metric_frame=metric_frame,
        cards=cards,
        preview_banner=preview_banner,
        preview_banner_title=preview_banner_title,
        preview_banner_text=preview_banner_text,
        preview_apply_button=preview_apply_button,
        preview_clear_button=preview_clear_button,
        formal_progress_panel=formal_progress_panel,
        formal_progress_label=formal_progress_label,
        formal_progress_bar=formal_progress_bar,
        apply_alignment_button=apply_alignment_button,
        diagnostic_text=diagnostic_text,
        detail_drawer=detail_drawer,
        result_splitter=result_splitter,
    )


__all__ = ["SimulationWidgets", "build_simulation_layout"]
