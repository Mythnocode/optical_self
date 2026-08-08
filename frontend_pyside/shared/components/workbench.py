from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.plotting.thumbnail_cache import ThumbnailPixmapCache



class ExpandableSection(QFrame):


    expandedChanged = Signal(object, bool)

    def __init__(
        self,
        title: str,
        content: QWidget | Callable[[], QWidget],
        *,
        subtitle: str = "",
        expanded: bool = False,
        header_variant: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("expandableSection")
        self._content_factory = content if callable(content) else None
        self._content: QWidget | None = None if callable(content) else content

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root = root

        self.header = QToolButton()
        self.header.setObjectName("expandableSectionHeader")
        if header_variant:
            self.header.setProperty("variant", str(header_variant))
        self.header.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        text = title if not subtitle else f"{title}　{subtitle}"
        self.header.setText(text)
        self.header.toggled.connect(self.set_expanded)
        root.addWidget(self.header)

        if self._content is not None:
            self._install_content(self._content)
        if expanded:
            self._ensure_content()

    def _install_content(self, content: QWidget) -> None:
        if self._content is not None and self._content is not content:
            self._root.removeWidget(self._content)
            self._content.deleteLater()
        self._content = content
        content.setObjectName("expandableSectionContent")
        self._root.addWidget(content)
        content.setVisible(self.header.isChecked())

    def _ensure_content(self) -> QWidget | None:
        if self._content is None and self._content_factory is not None:
            factory, self._content_factory = self._content_factory, None
            self._install_content(factory())
        return self._content

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        blocked = self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(blocked)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        if expanded:
            self._ensure_content()
        if self._content is not None:
            self._content.setVisible(expanded)
        self.expandedChanged.emit(self, expanded)


class Accordion(QWidget):


    def __init__(
        self,
        sections: Iterable[ExpandableSection],
        *,
        exclusive: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sections = list(sections)
        self.exclusive = bool(exclusive)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        for section in self.sections:
            root.addWidget(section)
            section.expandedChanged.connect(self._section_changed)
        root.addStretch(1)

    def _section_changed(self, current: ExpandableSection, expanded: bool) -> None:
        if not expanded or not self.exclusive:
            return
        for section in self.sections:
            if section is not current and section.is_expanded():
                section.set_expanded(False)


class MetricSummaryBar(QFrame):


    def __init__(self, items: Iterable[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricSummaryBar")
        self._labels: dict[str, QLabel] = {}
        records = list(items)
        root = QHBoxLayout(self)
        root.setContentsMargins(11, 5, 11, 5)
        root.setSpacing(9)
        for index, (key, value) in enumerate(records):
            label = QLabel(f"{key} {value}")
            label.setObjectName("metricSummaryItem")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._labels[key] = label
            root.addWidget(label)
            if index < len(records) - 1:
                divider = QFrame()
                divider.setFrameShape(QFrame.Shape.VLine)
                divider.setObjectName("summaryDivider")
                root.addWidget(divider)
        root.addStretch(1)

    def set_value(self, key: str, value: object) -> None:
        label = self._labels.get(key)
        if label is not None:
            label.setText(f"{key} {value}")

    def set_items(self, items: Iterable[tuple[str, object]]) -> None:

        for key, value in items:
            self.set_value(str(key), value)

    def set_values(self, values: Iterable[object]) -> None:
        for label, value in zip(self._labels.values(), values):
            key = label.text().split(" ", 1)[0]
            label.setText(f"{key} {value}")


class CollapsibleDetailTabs(QFrame):


    visibilityChanged = Signal(bool)

    def __init__(
        self,
        title: str,
        tabs: Iterable[tuple[str, QWidget]],
        *,
        expanded: bool = False,
        orientation: Qt.Orientation = Qt.Orientation.Vertical,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailDrawer")
        self._orientation = orientation
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("detailDrawerHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(6)
        self.toggle = QToolButton()
        self.toggle.setObjectName("detailDrawerToggle")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        header_layout.addWidget(self.toggle)
        header_layout.addStretch(1)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for label, widget in tabs:
            self.tabs.addTab(widget, label)
        self.tabs.setVisible(expanded)
        root.addWidget(self.tabs, 1)
        self.toggle.toggled.connect(self.set_expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self.tabs.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.visibilityChanged.emit(expanded)

    def set_current_tab(self, label: str, *, expand: bool = True) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == label:
                self.tabs.setCurrentIndex(index)
                break
        if expand:
            self.toggle.setChecked(True)


class SideDetailDrawer(QFrame):


    visibilityChanged = Signal(bool)

    def __init__(
        self,
        title: str,
        tabs: Iterable[tuple[str, QWidget]],
        *,
        expanded: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sideDetailDrawer")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toggle = QToolButton()
        self.toggle.setObjectName("sideDetailDrawerToggle")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.toggle.setArrowType(
            Qt.ArrowType.RightArrow if expanded else Qt.ArrowType.LeftArrow
        )
        self.toggle.setFixedWidth(38)
        root.addWidget(self.toggle)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("sideDetailTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMinimumWidth(300)
        self.tabs.setMaximumWidth(420)
        for label, widget in tabs:
            self.tabs.addTab(widget, label)
        root.addWidget(self.tabs, 1)

        self.toggle.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        blocked = self.toggle.blockSignals(True)
        self.toggle.setChecked(expanded)
        self.toggle.blockSignals(blocked)
        self.tabs.setVisible(expanded)
        self.toggle.setArrowType(
            Qt.ArrowType.RightArrow if expanded else Qt.ArrowType.LeftArrow
        )
        self.setMinimumWidth(338 if expanded else 38)
        self.setMaximumWidth(458 if expanded else 38)
        self.visibilityChanged.emit(expanded)

    def set_current_tab(self, label: str, *, expand: bool = True) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == label:
                self.tabs.setCurrentIndex(index)
                break
        if expand:
            self.set_expanded(True)


class ThumbnailStrip(QFrame):


    selected = Signal(str)
    openRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("thumbnailStrip")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._buttons: dict[str, QPushButton] = {}
        self._cache = ThumbnailPixmapCache(max_items=64)
        self._render_keys: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("thumbnailHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 3, 8, 3)
        self.toggle = QToolButton(text="结果预览")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header_layout.addWidget(self.toggle)
        self.count_label = QLabel("（0）")
        self.count_label.setObjectName("helperText")
        header_layout.addWidget(self.count_label)
        header_layout.addStretch(1)
        root.addWidget(header)

        self.scroller = QScrollArea()
        self.scroller.setObjectName("thumbnailScroll")
        self.scroller.setWidgetResizable(True)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroller.setFixedHeight(104)
        self.container = QWidget()
        self.row = QHBoxLayout(self.container)
        self.row.setContentsMargins(7, 5, 7, 5)
        self.row.setSpacing(6)
        self.row.addStretch(1)
        self.scroller.setWidget(self.container)
        root.addWidget(self.scroller)
        self.toggle.toggled.connect(self._toggle)

    def _toggle(self, expanded: bool) -> None:
        self.scroller.setVisible(expanded)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def set_items(self, items: Iterable[tuple[str, str, str]]) -> None:
        records = list(items)
        keys = [str(key) for key, _, _ in records]

        
        
        
        if keys == list(self._buttons):
            for key, source, status in records:
                key = str(key)
                button = self._buttons[key]
                button.setText(f"{key}\n{source}")
                button.setToolTip(
                    f"{key}｜{source}｜{status}\n单击切换上方大图，双击在独立窗口查看。"
                )
                cached = self._cache.get(self._render_keys.get(key, ""))
                if cached is not None:
                    button.setIcon(QIcon(cached))
            self.count_label.setText(f"（{len(records)}）")
            return

        while self.row.count():
            item = self.row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()

        for key, source, status in records:
            key = str(key)
            button = QPushButton(f"{key}\n{source}")
            button.setObjectName("thumbnailButton")
            button.setCheckable(True)
            button.setIconSize(QSize(96, 56))
            cached = self._cache.get(self._render_keys.get(key, ""))
            if cached is not None:
                button.setIcon(QIcon(cached))
            button.setToolTip(
                f"{key}｜{source}｜{status}\n单击切换上方大图，双击在独立窗口查看。"
            )
            button.clicked.connect(
                lambda checked=False, name=key: self.selected.emit(name)
            )
            button.installEventFilter(self)
            button.setProperty("resultKey", key)
            self.row.addWidget(button)
            self._buttons[key] = button
        self.row.addStretch(1)
        self.count_label.setText(f"（{len(records)}）")

    def has_render_key(self, key: str, render_key: str) -> bool:
        key = str(key)
        render_key = str(render_key or key)
        return self._render_keys.get(key) == render_key and self._cache.get(render_key) is not None

    def set_pixmap(self, key: str, render_key: str, pixmap: QPixmap) -> None:
        key = str(key)
        render_key = str(render_key or key)
        cached = self._cache.put_pixmap(render_key, pixmap)
        self._render_keys[key] = render_key
        button = self._buttons.get(key)
        if button is not None:
            button.setIcon(QIcon(cached))

    def set_figure_thumbnail(self, key: str, render_key: str, figure) -> None:
        render_key = str(render_key or key)
        pixmap = self._cache.put_figure(render_key, figure)
        if pixmap is not None:
            self._render_keys[str(key)] = render_key
            button = self._buttons.get(str(key))
            if button is not None:
                button.setIcon(QIcon(pixmap))

    def set_expanded(self, expanded: bool) -> None:
        blocked = self.toggle.blockSignals(True)
        self.toggle.setChecked(bool(expanded))
        self.toggle.blockSignals(blocked)
        self._toggle(bool(expanded))

    def clear_cache(self) -> None:
        self._cache.clear()
        self._render_keys.clear()

    def set_current(self, key: str) -> None:
        for name, button in self._buttons.items():
            blocked = button.blockSignals(True)
            button.setChecked(name == key)
            button.blockSignals(blocked)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            key = watched.property("resultKey")
            
            
            if key and self._buttons.get(str(key)) is watched:
                self.openRequested.emit(str(key))
                return True
        return super().eventFilter(watched, event)


class EmptyState(QWidget):
    def __init__(self, title: str, description: str = "", action: QPushButton | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addStretch(1)
        heading = QLabel(title)
        heading.setObjectName("emptyStateTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(heading)
        if description:
            note = QLabel(description)
            note.setObjectName("emptyStateText")
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(note)
        if action is not None:
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(action)
            row.addStretch(1)
            root.addLayout(row)
        root.addStretch(1)
