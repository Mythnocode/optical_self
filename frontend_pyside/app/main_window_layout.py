
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.app.page_registry import PageSpec
from frontend_pyside.core.constants import APP_VERSION
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme


@dataclass(slots=True)
class MainWindowWidgets:
    central: QWidget
    sidebar: QWidget
    brand_layout: QHBoxLayout
    brand_icon: QLabel
    brand_text: QWidget
    sidebar_toggle: QToolButton
    nav_buttons: dict[str, QToolButton]
    group_labels: list[QLabel]
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
    stack: QStackedWidget
    status_bar: QStatusBar
    status_page: QLabel
    status_source: QLabel


def build_main_window_layout(window: QMainWindow, specs: tuple[PageSpec, ...]) -> MainWindowWidgets:
    central = QWidget()
    central.setObjectName("centralRoot")
    shell = QHBoxLayout(central)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    sidebar = QWidget()
    sidebar.setObjectName("navPanel")
    sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    nav_layout = QVBoxLayout(sidebar)
    nav_layout.setContentsMargins(0, 0, 0, 0)
    nav_layout.setSpacing(0)

    brand_row = QWidget()
    brand_row.setObjectName("brandRow")
    brand_layout = QHBoxLayout(brand_row)
    brand_layout.setContentsMargins(14, 10, 10, 10)
    brand_layout.setSpacing(10)

    
    
    brand_icon = QLabel()
    brand_icon.setVisible(False)

    brand_text = QWidget()
    brand_text_layout = QVBoxLayout(brand_text)
    brand_text_layout.setContentsMargins(0, 0, 0, 0)
    brand_text_layout.setSpacing(0)
    title = QLabel("激光耦合研究系统")
    title.setObjectName("brand")
    subtitle = QLabel("仿真与参数优化")
    subtitle.setObjectName("brandSubtitle")
    subtitle.setVisible(True)
    brand_text_layout.addWidget(title)
    brand_text_layout.addWidget(subtitle)
    brand_layout.addWidget(brand_text, 1)

    sidebar_toggle = QToolButton()
    sidebar_toggle.setObjectName("sidebarToggle")
    sidebar_toggle.setIconSize(QSize(18, 18))
    brand_layout.addWidget(sidebar_toggle)
    nav_layout.addWidget(brand_row)

    nav_buttons: dict[str, QToolButton] = {}
    group_labels: list[QLabel] = []
    for spec in specs:
        button = QToolButton()
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setIcon(icon(spec.icon_name, theme.NAV_ICON, 23))
        button.setIconSize(QSize(23, 23))
        button.setText(spec.title)
        button.setToolTip(spec.title)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        nav_layout.addWidget(button)
        nav_buttons[spec.key] = button

    nav_layout.addStretch(1)
    connection_status = QLabel("● 服务状态检查中")
    connection_status.setObjectName("connectionStatus")
    connection_status.setWordWrap(True)
    nav_layout.addWidget(connection_status)
    shell.addWidget(sidebar)

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(0)

    
    
    
    
    topbar = QWidget(content)
    topbar.setObjectName("topBar")
    top_layout = QHBoxLayout(topbar)
    top_layout.setContentsMargins(18, 9, 18, 9)
    top_layout.setSpacing(8)

    top_project = QLabel()
    top_project.setObjectName("topProject")
    top_layout.addWidget(top_project)
    top_layout.addStretch(1)

    top_version = QLabel()
    top_wave = QLabel()
    top_surfaces = QLabel()
    top_efficiency = QLabel()
    top_mode = QLabel("教学：近似模式")
    top_frontend = QLabel(f"前端 {APP_VERSION}")
    for widget in (top_version, top_wave, top_surfaces, top_mode, top_frontend):
        widget.setObjectName("topMeta")
    top_efficiency.setObjectName("topMetric")
    for widget in (top_version, top_wave, top_surfaces, top_efficiency):
        top_layout.addWidget(widget)

    display_mode = QComboBox()
    display_mode.setObjectName("topDisplayMode")
    display_mode.addItems(["标准", "紧凑", "大字体"])
    display_mode.setToolTip("界面显示密度")
    display_mode.setMaximumWidth(96)
    top_layout.addWidget(display_mode)

    render_quality = QComboBox()
    render_quality.setObjectName("topRenderQuality")
    render_quality.addItems(["性能优先", "平衡", "质量优先"])
    render_quality.setToolTip("绘图质量与交互性能")
    render_quality.setMaximumWidth(108)
    top_layout.addWidget(render_quality)

    top_mode.setVisible(False)
    top_frontend.setVisible(False)
    
    
    
    topbar.setVisible(False)

    stack = QStackedWidget()
    stack.setObjectName("featureStack")
    content_layout.addWidget(stack, 1)
    shell.addWidget(content, 1)

    status_bar = QStatusBar()
    status_page = QLabel("当前页面：首页")
    status_source = QLabel("结果来源会在各页面明确标注")
    status_bar.addWidget(status_page)
    status_bar.addPermanentWidget(status_source)

    window.setCentralWidget(central)
    status_bar.setVisible(False)
    window.setStatusBar(status_bar)

    return MainWindowWidgets(
        central=central,
        sidebar=sidebar,
        brand_layout=brand_layout,
        brand_icon=brand_icon,
        brand_text=brand_text,
        sidebar_toggle=sidebar_toggle,
        nav_buttons=nav_buttons,
        group_labels=group_labels,
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
        stack=stack,
        status_bar=status_bar,
        status_page=status_page,
        status_source=status_source,
    )


__all__ = ["MainWindowWidgets", "build_main_window_layout"]
