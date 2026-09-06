from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.app.compact_shell import CompactNavigationRail, CompactToolDrawer, DocumentTabBar
from frontend_pyside.core.constants import APP_VERSION
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon


@dataclass(slots=True)
class MainWindowWidgets:
    central: QWidget
    rail: CompactNavigationRail
    drawer: CompactToolDrawer
    document_tabs: DocumentTabBar
    stack: QStackedWidget
    connection_status: QLabel
    top_project: QLabel
    top_version: QLabel
    top_wave: QLabel
    top_surfaces: QLabel
    top_efficiency: QLabel
    top_mode: QLabel
    top_frontend: QLabel
    display_mode: QComboBox
    render_quality: QComboBox
    status_page: QLabel
    status_source: QLabel
    footer_efficiency: QLabel
    footer_notice: QLabel
    footer_result_button: QToolButton
    footer_tasks_button: QToolButton
    command_buttons: dict[str, QToolButton]


def _small_tool(icon_name: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setObjectName("shellIconButton")
    button.setIcon(icon(icon_name, theme.TEXT_SECONDARY, 18))
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    return button


def _command(text: str, *, icon_name: str = "") -> QToolButton:
    button = QToolButton()
    button.setObjectName("shellCommandButton")
    button.setText(text)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    if icon_name:
        button.setIcon(icon(icon_name, theme.TEXT_SECONDARY, 17))
        button.setIconSize(QSize(17, 17))
    button.setMinimumHeight(34)
    button.setAccessibleName(text)
    return button


def build_main_window_layout(window: QMainWindow, _specs) -> MainWindowWidgets:
    central = QWidget(window)
    central.setObjectName("centralRoot")
    root = QVBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # One stable command strip.  It chooses tasks; it does not pretend each
    # analysis sub-view is a separate document/workspace.
    top = QFrame(central)
    top.setObjectName("compactTopBar")
    top_layout = QHBoxLayout(top)
    top_layout.setContentsMargins(8, 4, 10, 4)
    top_layout.setSpacing(5)

    home_button = _small_tool("logo", "项目总览")
    home_button.setObjectName("shellHomeButton")
    save_button = _small_tool("save", "保存当前系统")
    save_button.setProperty("shellAction", "save")
    undo_button = _small_tool("undo", "撤销")
    undo_button.setProperty("shellAction", "undo")
    redo_button = _small_tool("redo", "重做")
    redo_button.setProperty("shellAction", "redo")
    for button in (home_button, save_button, undo_button, redo_button):
        top_layout.addWidget(button)

    divider = QFrame(top)
    divider.setObjectName("shellCommandDivider")
    divider.setFrameShape(QFrame.Shape.VLine)
    top_layout.addWidget(divider)

    command_buttons = {
        "simulation": _command("仿真", icon_name="simulation"),
        "teaching": _command("教学", icon_name="teaching"),
        "optimization": _command("优化", icon_name="optimization"),
        "surrogate": _command("代理模型", icon_name="machine_learning"),
        "explainability": _command("模型解释", icon_name="explainability"),
    }
    for button in command_buttons.values():
        button.setCheckable(True)
        button.setAutoExclusive(True)
        top_layout.addWidget(button)
    top_layout.addStretch(1)

    connection_status = QLabel("服务检查中")
    connection_status.setObjectName("compactConnectionStatus")
    connection_status.setToolTip("后端服务状态")
    top_layout.addWidget(connection_status)
    root.addWidget(top)

    body = QWidget(central)
    body_layout = QHBoxLayout(body)
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setSpacing(0)

    # Compatibility objects stay alive for old controller calls, but navigation
    # is no longer a permanent left feature rail/drawer.
    rail = CompactNavigationRail(body)
    rail.hide()
    drawer = CompactToolDrawer(body)
    drawer.hide()
    document_tabs = DocumentTabBar(body)
    document_tabs.hide()

    stack = QStackedWidget(body)
    stack.setObjectName("featureStack")
    body_layout.addWidget(stack, 1)
    root.addWidget(body, 1)

    footer = QFrame(central)
    footer.setObjectName("compactFooter")
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(10, 2, 10, 2)
    footer_layout.setSpacing(8)

    footer_efficiency = QLabel("耦合效率 待计算")
    footer_efficiency.setObjectName("footerMetric")
    footer_layout.addWidget(footer_efficiency)
    footer_notice = QLabel("就绪")
    footer_notice.setObjectName("footerNotice")
    footer_layout.addWidget(footer_notice, 1)

    footer_result_button = _small_tool("result", "当前仿真结果")
    footer_result_button.setObjectName("footerActionButton")
    footer_layout.addWidget(footer_result_button)
    footer_tasks_button = _small_tool("tasks", "任务状态")
    footer_tasks_button.setObjectName("footerActionButton")
    footer_layout.addWidget(footer_tasks_button)
    root.addWidget(footer)

    # Hidden compatibility state for pre-refactor logic.
    compat = QWidget(central)
    compat.hide()
    top_project = QLabel(compat)
    top_version = QLabel(compat)
    top_wave = QLabel(compat)
    top_surfaces = QLabel(compat)
    top_efficiency = QLabel(compat)
    top_mode = QLabel("教学：近似模式", compat)
    top_frontend = QLabel(f"前端 {APP_VERSION}", compat)
    display_mode = QComboBox(compat)
    display_mode.addItems(["标准", "紧凑", "大字体"])
    render_quality = QComboBox(compat)
    render_quality.addItems(["性能优先", "平衡", "质量优先"])
    status_page = QLabel("当前页面：首页", compat)
    status_source = QLabel("结果来源会在各页面明确标注", compat)

    window.setCentralWidget(central)
    window.statusBar().hide()

    return MainWindowWidgets(
        central=central,
        rail=rail,
        drawer=drawer,
        document_tabs=document_tabs,
        stack=stack,
        connection_status=connection_status,
        top_project=top_project,
        top_version=top_version,
        top_wave=top_wave,
        top_surfaces=top_surfaces,
        top_efficiency=top_efficiency,
        top_mode=top_mode,
        top_frontend=top_frontend,
        display_mode=display_mode,
        render_quality=render_quality,
        status_page=status_page,
        status_source=status_source,
        footer_efficiency=footer_efficiency,
        footer_notice=footer_notice,
        footer_result_button=footer_result_button,
        footer_tasks_button=footer_tasks_button,
        command_buttons=command_buttons,
    )


__all__ = ["MainWindowWidgets", "build_main_window_layout"]
