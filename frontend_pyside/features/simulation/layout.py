
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    InlineMetric,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.workbench import SideDetailDrawer
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme


@dataclass(slots=True)
class SimulationWidgets:
    root: QVBoxLayout
    model_badge: Badge
    preview_button: SecondaryButton
    formal_button: PrimaryButton
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
    cards: dict[str, InlineMetric]
    apply_alignment_button: SecondaryButton
    diagnostic_text: QLabel
    detail_drawer: SideDetailDrawer
    result_splitter: QSplitter


def _build_diagnostics_panel() -> tuple[QWidget, QLabel]:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(8, 7, 8, 7)
    layout.setSpacing(5)
    diagnostic_text = QLabel("详细物理指标、收敛数据与数值质量将在正式结果返回后显示。")
    diagnostic_text.setObjectName("drawerText")
    diagnostic_text.setWordWrap(True)
    diagnostic_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(diagnostic_text)
    layout.addStretch(1)
    return panel, diagnostic_text


def _build_result_actions() -> tuple[QWidget, SecondaryButton, QCheckBox]:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(8, 7, 8, 7)
    layout.setSpacing(6)
    multipath_toggle = QCheckBox("使用多路径正式计算")
    multipath_toggle.setToolTip("高级选项：启用后下一次正式计算走多路径后端；默认关闭")
    layout.addWidget(multipath_toggle)

    
    
    apply_alignment_button = SecondaryButton("应用五轴最优值")
    apply_alignment_button.setVisible(False)
    layout.addStretch(1)
    return panel, apply_alignment_button, multipath_toggle


def build_simulation_layout(page: QWidget, context) -> SimulationWidgets:
    root = QVBoxLayout(page)
    root.setContentsMargins(14, 7, 14, 12)
    root.setSpacing(6)

    model_badge = Badge("正式仿真由后端执行", "info")
    model_badge.setVisible(False)
    lens_editor_button = SecondaryButton("完整镜头编辑器")
    lens_editor_button.setIcon(icon("list", theme.PRIMARY, 16))
    preview_button = SecondaryButton("快速预览")
    preview_button.setIcon(icon("reset", theme.PRIMARY, 16))
    formal_button = PrimaryButton("正式计算")
    formal_button.setIcon(icon("check", theme.TEXT_INVERSE, 16))
    formal_button.setVisible(False)

    mode_bar = QFrame()
    mode_bar.setObjectName("simulationModeToolbar")
    mode_layout = QHBoxLayout(mode_bar)
    mode_layout.setContentsMargins(8, 3, 8, 3)
    mode_layout.setSpacing(6)

    auto_preview = QCheckBox("自动预览")
    auto_preview.setChecked(False)
    auto_preview.setToolTip("参数停止变化后只运行一次本地快速预览，不会提交后端")
    mode_layout.addWidget(auto_preview)
    mode_layout.addStretch(1)
    save_parameters_button = SecondaryButton("保存参数")
    save_parameters_button.setToolTip("保存当前正式工作台参数，供教学中心复盘和继续编辑")
    mode_layout.addWidget(save_parameters_button)
    import_teaching_button = SecondaryButton("导入教学参数")
    import_teaching_button.setToolTip("将教学中心最近保存的镜片结构和光纤参数载入正式工作台")
    mode_layout.addWidget(import_teaching_button)
    teaching_button = SecondaryButton("教学中心查看")
    teaching_button.setToolTip("保存当前参数并在教学中心查看光束、仪器与原理解释")
    mode_layout.addWidget(teaching_button)
    mode_layout.addWidget(lens_editor_button)
    mode_layout.addWidget(preview_button)
    mode_layout.addWidget(formal_button)

    multipath_button = QToolButton()
    multipath_button.setVisible(False)
    preview_state = Badge("预览需手动刷新", "info")
    preview_state.setVisible(False)
    formal_state = Badge("尚未正式计算", "warning")
    formal_state.setVisible(False)
    root.addWidget(mode_bar)

    main_splitter = QSplitter(Qt.Orientation.Horizontal)
    main_splitter.setObjectName("simulationMainSplitter")
    main_splitter.setChildrenCollapsible(False)
    main_splitter.setHandleWidth(8)
    main_splitter.setOpaqueResize(False)

    editor = QuickLensEditor(context.project)
    params = SimpleParameterTabs(editor)
    
    
    
    params.setMinimumWidth(520)
    params.setMaximumWidth(720)
    main_splitter.addWidget(params)
    main_splitter.setCollapsible(0, False)

    right_panel = QWidget()
    right_panel.setMinimumWidth(390)
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(5)

    metric_frame = QFrame()
    metric_frame.setObjectName("simulationResultSummary")
    metric_layout = QHBoxLayout(metric_frame)
    metric_layout.setContentsMargins(6, 3, 6, 3)
    metric_layout.setSpacing(5)
    cards = {
        "system_eff": InlineMetric("系统效率", "—", "%", note="即时估计"),
        "receiver_eff": InlineMetric("接收效率", "—", "%", note="即时估计"),
        "coupling_eff": InlineMetric("耦合效率", "—", "%", note="即时估计"),
    }
    for key in ("system_eff", "receiver_eff", "coupling_eff"):
        cards[key].setMinimumWidth(150)
        cards[key].setMinimumHeight(58)
        cards[key].setMaximumHeight(68)
        metric_layout.addWidget(cards[key], 1)
    right_layout.addWidget(metric_frame)

    diagnostic_panel, diagnostic_text = _build_diagnostics_panel()
    action_panel, apply_alignment_button, multipath_toggle = _build_result_actions()

    result_splitter = QSplitter(Qt.Orientation.Horizontal)
    result_splitter.setObjectName("simulationResultSplitter")
    result_splitter.setChildrenCollapsible(True)
    result_splitter.setHandleWidth(0)

    results = LivePreviewWorkspace()
    results.setMinimumSize(410, 320)
    params.attach_result_controls(results.section_controls)
    result_splitter.addWidget(results)

    detail_drawer = SideDetailDrawer(
        "详情",
        [("诊断", diagnostic_panel), ("高级", action_panel)],
        expanded=False,
    )
    detail_drawer.setVisible(False)
    result_splitter.addWidget(detail_drawer)
    result_splitter.setStretchFactor(0, 1)
    result_splitter.setStretchFactor(1, 0)
    result_splitter.setSizes([1138, 0])
    right_layout.addWidget(result_splitter, 1)

    main_splitter.addWidget(right_panel)
    main_splitter.setStretchFactor(0, 0)
    main_splitter.setStretchFactor(1, 1)
    main_splitter.setSizes([620, 980])
    root.addWidget(main_splitter, 1)

    return SimulationWidgets(
        root=root,
        model_badge=model_badge,
        preview_button=preview_button,
        formal_button=formal_button,
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
        cards=cards,
        apply_alignment_button=apply_alignment_button,
        diagnostic_text=diagnostic_text,
        detail_drawer=detail_drawer,
        result_splitter=result_splitter,
    )


__all__ = ["SimulationWidgets", "build_simulation_layout"]
