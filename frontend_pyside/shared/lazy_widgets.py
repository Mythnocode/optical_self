
from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

from frontend_pyside.shared.lifecycle import dispose_widget_tree


WidgetFactory = Callable[[], QWidget]


def _placeholder(text: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(16, 16, 16, 16)
    label = QLabel(text)
    label.setObjectName("lazyPlaceholder")
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addStretch(1)
    widget.setProperty("lazyPlaceholderText", text)
    return widget


class _LazyContainerSupport:
    def _init_lazy_support(self) -> None:
        self._factories: dict[int, WidgetFactory] = {}
        self._placeholder_texts: dict[int, str] = {}
        self._loaded: set[int] = set()
        self._loading: set[int] = set()
        self._last_used: dict[int, float] = {}

    def is_loaded(self, index: int) -> bool:
        return index in self._loaded

    def loaded_indices(self) -> tuple[int, ...]:
        return tuple(sorted(self._loaded))

    def touch(self, index: int) -> None:
        self._last_used[int(index)] = monotonic()

    def unload_idle(self, *, idle_s: float = 300.0, keep: set[int] | None = None) -> list[int]:
        now = monotonic()
        keep = set(keep or ())
        released: list[int] = []
        for index in tuple(self._loaded):
            if index in keep:
                continue
            if now - self._last_used.get(index, 0.0) >= max(0.0, float(idle_s)):
                if self.unload(index):
                    released.append(index)
        return released


class LazyStackedWidget(_LazyContainerSupport, QStackedWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_lazy_support()

    def add_lazy_widget(self, factory: WidgetFactory, text: str = "正在准备工作区…") -> int:
        index = self.addWidget(_placeholder(text))
        self._factories[index] = factory
        self._placeholder_texts[index] = text
        return index

    def ensure_loaded(self, index: int) -> QWidget | None:
        if index < 0:
            return None
        self.touch(index)
        if index in self._loaded or index in self._loading:
            return self.widget(index)
        factory = self._factories.get(index)
        if factory is None:
            return self.widget(index)
        self._loading.add(index)
        try:
            old = self.widget(index)
            current = self.currentIndex() == index
            widget = factory()
            self.removeWidget(old)
            dispose_widget_tree(old)
            self.insertWidget(index, widget)
            self._loaded.add(index)
            if current:
                super().setCurrentIndex(index)
            return widget
        finally:
            self._loading.discard(index)

    def unload(self, index: int) -> bool:
        if index not in self._loaded or index == self.currentIndex():
            return False
        old = self.widget(index)
        current = self.currentIndex()
        self.removeWidget(old)
        self.insertWidget(index, _placeholder(self._placeholder_texts.get(index, "按需加载")))
        self._loaded.discard(index)
        self._last_used.pop(index, None)
        dispose_widget_tree(old)
        super().setCurrentIndex(current)
        return True

    def setCurrentIndex(self, index: int) -> None:  
        self.ensure_loaded(index)
        super().setCurrentIndex(index)

    def ensure_current_deferred(self) -> None:
        QTimer.singleShot(0, lambda: self.ensure_loaded(self.currentIndex()))

    def dispose(self) -> None:
        for index in tuple(self._loaded):
            if index == self.currentIndex():
                continue
            self.unload(index)


class LazyTabWidget(_LazyContainerSupport, QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_lazy_support()
        self.currentChanged.connect(self._schedule_current_load)

    def add_lazy_tab(self, factory: WidgetFactory, title: str, text: str = "正在准备内容…") -> int:
        index = self.addTab(_placeholder(text), title)
        self._factories[index] = factory
        self._placeholder_texts[index] = text
        return index

    def _schedule_current_load(self, index: int) -> None:
        self.touch(index)
        if index >= 0 and index not in self._loaded and index not in self._loading:
            QTimer.singleShot(0, lambda selected=index: self.ensure_loaded(selected))

    def ensure_loaded(self, index: int) -> QWidget | None:
        if index < 0:
            return None
        self.touch(index)
        if index in self._loaded or index in self._loading:
            return self.widget(index)
        factory = self._factories.get(index)
        if factory is None:
            return self.widget(index)
        self._loading.add(index)
        try:
            old = self.widget(index)
            current = self.currentIndex() == index
            title = self.tabText(index)
            icon = self.tabIcon(index)
            enabled = self.isTabEnabled(index)
            tooltip = self.tabToolTip(index)
            widget = factory()
            self.removeTab(index)
            self.insertTab(index, widget, icon, title)
            self.setTabEnabled(index, enabled)
            self.setTabToolTip(index, tooltip)
            dispose_widget_tree(old)
            self._loaded.add(index)
            if current:
                super().setCurrentIndex(index)
            return widget
        finally:
            self._loading.discard(index)

    def unload(self, index: int) -> bool:
        if index not in self._loaded or index == self.currentIndex():
            return False
        old = self.widget(index)
        title = self.tabText(index)
        icon = self.tabIcon(index)
        enabled = self.isTabEnabled(index)
        tooltip = self.tabToolTip(index)
        current = self.currentIndex()
        self.removeTab(index)
        placeholder = _placeholder(self._placeholder_texts.get(index, "按需加载"))
        self.insertTab(index, placeholder, icon, title)
        self.setTabEnabled(index, enabled)
        self.setTabToolTip(index, tooltip)
        self._loaded.discard(index)
        self._last_used.pop(index, None)
        dispose_widget_tree(old)
        super().setCurrentIndex(current)
        return True

    def ensure_current_deferred(self) -> None:
        self._schedule_current_load(self.currentIndex())

    def dispose(self) -> None:
        for index in tuple(self._loaded):
            if index == self.currentIndex():
                continue
            self.unload(index)


__all__ = ["LazyStackedWidget", "LazyTabWidget"]
