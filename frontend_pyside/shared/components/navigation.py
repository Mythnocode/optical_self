from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme


@dataclass(frozen=True)
class SectionItem:
    text: str
    icon_name: str = "list"


class CollapsibleSectionNavigator(QFrame):


    currentRowChanged = Signal(int)

    def __init__(
        self,
        items: list[SectionItem] | list[tuple[str, str]] | list[str],
        *,
        expanded_width: int = 238,
        collapsed_width: int = 56,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("sectionNavigator")
        self.expanded_width = expanded_width
        self.collapsed_width = collapsed_width
        self._expanded = True
        normalized: list[SectionItem] = []
        for item in items:
            if isinstance(item, SectionItem):
                normalized.append(item)
            elif isinstance(item, tuple):
                normalized.append(SectionItem(item[0], item[1]))
            else:
                normalized.append(SectionItem(str(item)))
        self.items = normalized

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QWidget()
        header.setObjectName("sectionNavigatorHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 8, 8)
        self.title = QLabel("页面目录")
        self.title.setObjectName("sectionNavigatorTitle")
        hl.addWidget(self.title)
        hl.addStretch()
        self.toggle = QToolButton()
        self.toggle.setObjectName("sectionToggle")
        self.toggle.setIcon(icon("chevron_left", theme.TEXT_SECONDARY, 18))
        self.toggle.setIconSize(QSize(18, 18))
        self.toggle.setToolTip("收起目录")
        self.toggle.clicked.connect(self.toggle_collapsed)
        hl.addWidget(self.toggle)
        root.addWidget(header)

        self.list = QListWidget()
        self.list.setObjectName("sectionList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for spec in self.items:
            item = QListWidgetItem(icon(spec.icon_name, theme.PRIMARY_DARK, 22), spec.text)
            item.setSizeHint(QSize(0, 44))
            item.setToolTip(spec.text)
            self.list.addItem(item)
        self.list.currentRowChanged.connect(self.currentRowChanged)
        root.addWidget(self.list, 1)

        self.setMinimumWidth(collapsed_width)
        self.setMaximumWidth(expanded_width)
        self.animation = QPropertyAnimation(self, b"maximumWidth", self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def setCurrentRow(self, row: int) -> None:
        self.list.setCurrentRow(row)

    def currentRow(self) -> int:
        return self.list.currentRow()

    def toggle_collapsed(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        self._expanded = bool(expanded)
        target = self.expanded_width if self._expanded else self.collapsed_width
        if animate:
            self.animation.stop()
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self.setMaximumWidth(target)
        self.title.setVisible(self._expanded)
        self.toggle.setIcon(icon("chevron_left" if self._expanded else "chevron_right", theme.TEXT_SECONDARY, 18))
        self.toggle.setToolTip("收起目录" if self._expanded else "展开目录")
        for row, spec in enumerate(self.items):
            item = self.list.item(row)
            item.setText(spec.text if self._expanded else "")
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if self._expanded else Qt.AlignmentFlag.AlignHCenter))
        self.list.setIconSize(QSize(22, 22))

    @property
    def expanded(self) -> bool:
        return self._expanded
