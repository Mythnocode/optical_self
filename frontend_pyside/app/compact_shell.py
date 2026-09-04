from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QPushButton,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.icons import icon


@dataclass(frozen=True, slots=True)
class ShellAction:
    key: str
    title: str
    icon_name: str
    page_key: str
    target: str = ""
    payload: dict[str, Any] | None = None
    hint: str = ""


@dataclass(frozen=True, slots=True)
class ShellCategory:
    key: str
    title: str
    icon_name: str
    groups: tuple[tuple[str, tuple[ShellAction, ...]], ...]


CATEGORIES: tuple[ShellCategory, ...] = (
    ShellCategory(
        "system",
        "系统与建模",
        "application",
        ((
            "当前系统",
            (
                ShellAction("overview", "项目总览", "overview", "home", hint="平台总览与当前系统状态"),
                ShellAction("system", "系统建模", "list", "simulation", "simulation.parameters", hint="光源、光学元件与光纤参数"),
                ShellAction("lens_editor", "完整镜头编辑器", "list", "simulation", "simulation.lens_editor", hint="完整 Surface 表、曲率、材料与非球面参数"),
                ShellAction("compute_settings", "计算设置", "settings", "simulation", "simulation.parameters", {"section": "compute"}, hint="采样、传播算法与正式计算设置"),
            ),
        ),),
    ),
    ShellCategory(
        "analysis",
        "光学分析",
        "chart",
        ((
            "专业分析",
            (
                ShellAction("system_view", "系统视图", "rays", "simulation", "simulation.view", {"view": "光路"}),
                ShellAction("propagation", "光束传播", "rays", "simulation", "simulation.view", {"view": "光束包络"}),
                ShellAction("focal", "焦面分析", "intensity", "simulation", "simulation.view", {"view": "PSF"}),
                ShellAction("field", "复光场", "phase", "simulation", "simulation.view", {"view": "相位"}),
                ShellAction("mode", "模场匹配", "compare", "simulation", "simulation.view", {"view": "端面匹配"}),
                ShellAction("wave", "像质与波前", "result", "simulation", "simulation.view", {"view": "点列图"}),
                ShellAction("all_results", "完整结果目录", "result", "simulation", "simulation.result_catalogue", hint="点列图、PSF、MTF、波前、能量分解等全部结果"),
            )),
            ("研究分析", (
                ShellAction("scan", "参数研究", "chart", "simulation", "simulation.parameter_research", hint="改变当前系统参数并观察正式光学响应"),
                ShellAction("tolerance", "容差分析", "measure", "simulation", "simulation.tolerance", hint="围绕当前系统评估制造/装调误差的统计稳健性"),
            )),
        ),
    ),
    ShellCategory(
        "research",
        "优化",
        "optimization",
        (
            ("优化任务", (
                ShellAction("research_scan", "参数研究", "chart", "optimization", "optimization.scan", hint="研究参数响应、优化前后、收敛、候选与相关性"),
                ShellAction("optimize", "自动优化", "optimization", "optimization", "optimization.variables"),
                ShellAction("physical_inverse", "物理反向设计", "workflow", "optimization", "optimization.inverse_design", hint="目标 → 物理搜索 → 正式候选"),
            )),
        ),
    ),
    ShellCategory(
        "surrogate",
        "代理模型",
        "machine_learning",
        ((
            "模型任务",
            (
                ShellAction("model_build", "模型构建", "machine_learning", "machine_learning", "machine_learning.build", hint="数据准备 → 模型训练 → 模型比较"),
                ShellAction("forward", "正向预测", "next", "machine_learning", "machine_learning.prediction", hint="当前系统参数 → 性能预测"),
                ShellAction("ml_inverse", "反向预测", "workflow", "optimization", "optimization.ml_inverse_prediction", hint="目标性能 → 代理模型候选 → 正式验证"),
                ShellAction("model_explain", "模型解释", "inspect", "explainability", hint="SHAP 与特征贡献解释"),
                ShellAction("model_manage", "模型管理", "list", "machine_learning", "machine_learning.models", hint="模型比较、采用与版本信息"),
            ),
        ),),
    ),
    ShellCategory(
        "experiment",
        "实验与数据",
        "measure",
        ((
            "数据与任务",
            (
                ShellAction("data", "数据管理", "list", "machine_learning", "machine_learning.data", hint="数据集生成、导入、质量与注册"),
                ShellAction("tasks", "任务中心", "tasks", "tasks", hint="仿真、扫描、优化、训练与解释任务"),
            ),
        ),),
    ),
    ShellCategory(
        "teaching",
        "教学",
        "teaching",
        ((
            "实验",
            (
                ShellAction("mismatch5", "五大失配实验", "teaching", "teaching", "teaching.mismatch", {"mismatch": "lateral"}),
                ShellAction("free", "自由实验", "free_explore", "teaching", "teaching.workbench", hint="使用真实光学系统参数进行教学操作"),
                ShellAction("library", "实验库", "list", "teaching", "teaching.library", hint="扩束、曲率匹配、柱面整形等扩展实验"),
            ),
        ),),
    ),
)

CATEGORY_BY_KEY = {item.key: item for item in CATEGORIES}


class CompactNavigationRail(QFrame):
    categoryRequested = Signal(str)
    homeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compactNavRail")
        self.setFixedWidth(58)
        root = QVBoxLayout(self)
        root.setContentsMargins(5, 7, 5, 7)
        root.setSpacing(6)

        home = QToolButton(self)
        home.setObjectName("railHomeButton")
        home.setIcon(icon("logo", theme.NAV_ICON, 28))
        home.setIconSize(QSize(28, 28))
        home.setToolTip("项目总览")
        home.clicked.connect(self.homeRequested.emit)
        root.addWidget(home)

        separator = QFrame(self)
        separator.setObjectName("railSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(separator)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for category in CATEGORIES:
            button = QToolButton(self)
            button.setObjectName("railCategoryButton")
            button.setCheckable(True)
            button.setIcon(icon(category.icon_name, theme.NAV_ICON, 24))
            button.setIconSize(QSize(24, 24))
            button.setToolTip(category.title)
            button.setAccessibleName(category.title)
            button.clicked.connect(lambda checked=False, key=category.key: self.categoryRequested.emit(key))
            self.group.addButton(button)
            self.buttons[category.key] = button
            root.addWidget(button)

        root.addStretch(1)

    def set_current_category(self, key: str) -> None:
        button = self.buttons.get(str(key))
        if button is not None:
            button.setChecked(True)

    def clear_current_category(self) -> None:
        self.group.setExclusive(False)
        for button in self.buttons.values():
            button.setChecked(False)
        self.group.setExclusive(True)


class CompactToolDrawer(QFrame):
    actionTriggered = Signal(object)
    closeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compactToolDrawer")
        self.setFixedWidth(344)
        self._category_key = ""
        self._all_mode = False
        self._search_text = ""

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(12, 10, 12, 10)
        self.root.setSpacing(8)

        header = QHBoxLayout()
        self.title = QLabel("工具")
        self.title.setObjectName("drawerTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        close = QToolButton(self)
        close.setObjectName("drawerCloseButton")
        close.setIcon(icon("close", theme.TEXT_SECONDARY, 18))
        close.setIconSize(QSize(18, 18))
        close.setToolTip("收起")
        close.clicked.connect(self.closeRequested.emit)
        header.addWidget(close)
        self.root.addLayout(header)

        self.search = QLineEdit(self)
        self.search.setObjectName("toolboxSearch")
        self.search.setPlaceholderText("搜索工具、分析或任务…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_changed)
        self.root.addWidget(self.search)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("toolboxScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget(self.scroll)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(3)
        self.scroll.setWidget(self.body)
        self.root.addWidget(self.scroll, 1)
        self.hide()

    @property
    def category_key(self) -> str:
        return self._category_key

    def show_all(self) -> None:
        self._category_key = "all"
        self._all_mode = True
        self.title.setText("工具箱")
        self.search.setVisible(True)
        self.search.clear()
        self._render_categories(CATEGORIES)
        self.show()
        self.raise_()
        self.search.setFocus()

    def show_category(self, key: str) -> None:
        category = CATEGORY_BY_KEY.get(str(key))
        if category is None:
            return
        self._category_key = category.key
        self._all_mode = False
        self.title.setText(category.title)
        self.search.setVisible(True)
        self.search.clear()
        self._render_categories((category,))
        self.show()
        self.raise_()

    def _filter_changed(self, text: str) -> None:
        self._search_text = str(text or "").strip().lower()
        categories = CATEGORIES if self._all_mode else tuple(
            item for item in CATEGORIES if item.key == self._category_key
        )
        self._render_categories(categories)

    def _render_categories(self, categories: tuple[ShellCategory, ...]) -> None:
        self._clear_body()
        query = self._search_text
        any_action = False
        for category in categories:
            visible_groups: list[tuple[str, list[ShellAction]]] = []
            for group_title, actions in category.groups:
                filtered: list[ShellAction] = []
                for action in actions:
                    haystack = " ".join((category.title, group_title, action.title, action.hint, action.key)).lower()
                    if not query or query in haystack:
                        filtered.append(action)
                if filtered:
                    visible_groups.append((group_title, filtered))
            if not visible_groups:
                continue
            any_action = True
            category_label = QLabel(category.title)
            category_label.setObjectName("drawerCategoryTitle")
            self.body_layout.addWidget(category_label)
            for group_title, actions in visible_groups:
                if len(visible_groups) > 1:
                    group_label = QLabel(group_title)
                    group_label.setObjectName("drawerGroupTitle")
                    self.body_layout.addWidget(group_label)
                for action in actions:
                    button = QPushButton(action.title, self.body)
                    button.setObjectName("drawerActionButton")
                    button.setIcon(icon(action.icon_name, theme.PRIMARY_DARK, 18))
                    button.setIconSize(QSize(18, 18))
                    button.setMinimumHeight(30)
                    tip_parts = [action.title]
                    if action.hint:
                        tip_parts.append(action.hint)
                    button.setToolTip("\n".join(tip_parts))
                    button.clicked.connect(lambda checked=False, item=action: self.actionTriggered.emit(item))
                    self.body_layout.addWidget(button)
        if not any_action:
            empty = QLabel("没有匹配的工具")
            empty.setObjectName("drawerEmptyText")
            self.body_layout.addWidget(empty)
        self.body_layout.addStretch(1)

    def _clear_body(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class DocumentTabBar(QTabBar):
    pageRequested = Signal(str)
    pageCloseRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("documentTabBar")
        self.setDocumentMode(True)
        self.setMovable(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setTabsClosable(True)
        self.currentChanged.connect(self._current_changed)
        self.tabCloseRequested.connect(self._close_requested)

    def open_page(self, key: str, title: str, icon_name: str = "") -> None:
        index = self.index_for_key(key)
        if index < 0:
            if icon_name:
                index = self.addTab(icon(icon_name, theme.TEXT_SECONDARY, 17), title)
            else:
                index = self.addTab(title)
            self.setTabData(index, key)
            self.setTabToolTip(index, title)
            if key == "home":
                close_button = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
                if close_button is not None:
                    close_button.hide()
        blocked = self.blockSignals(True)
        self.setCurrentIndex(index)
        self.blockSignals(blocked)

    def index_for_key(self, key: str) -> int:
        for index in range(self.count()):
            if str(self.tabData(index) or "") == str(key):
                return index
        return -1

    def close_key(self, key: str) -> None:
        index = self.index_for_key(key)
        if index >= 0 and str(key) != "home":
            self.removeTab(index)

    def _current_changed(self, index: int) -> None:
        if index < 0:
            return
        key = str(self.tabData(index) or "")
        if key:
            self.pageRequested.emit(key)

    def _close_requested(self, index: int) -> None:
        key = str(self.tabData(index) or "")
        if key and key != "home":
            self.pageCloseRequested.emit(key)


__all__ = [
    "CATEGORY_BY_KEY",
    "CATEGORIES",
    "CompactNavigationRail",
    "CompactToolDrawer",
    "DocumentTabBar",
    "ShellAction",
    "ShellCategory",
]
