
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QWidget


class SplitterWorkspace(QWidget):
    def __init__(
        self,
        widgets: Iterable[QWidget],
        sizes: Iterable[int],
        *,
        orientation=Qt.Orientation.Horizontal,
        parent=None,
    ):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.splitter = QSplitter(orientation)
        self.splitter.setChildrenCollapsible(False)
        for widget in widgets:
            self.splitter.addWidget(widget)
        self.splitter.setSizes([int(value) for value in sizes])
        root.addWidget(self.splitter)

    def sizes(self) -> list[int]:
        return list(self.splitter.sizes())

    def set_sizes(self, sizes: Iterable[int]) -> None:
        self.splitter.setSizes([int(value) for value in sizes])


class TwoPanelWorkspace(SplitterWorkspace):


    def __init__(
        self,
        left: QWidget,
        right: QWidget,
        sizes=(420, 820),
        orientation=Qt.Orientation.Horizontal,
        parent=None,
    ):
        super().__init__((left, right), sizes, orientation=orientation, parent=parent)


class ThreePanelWorkspace(SplitterWorkspace):


    def __init__(
        self,
        left: QWidget,
        center: QWidget,
        right: QWidget,
        sizes=(220, 620, 280),
        parent=None,
    ):
        super().__init__((left, center, right), sizes, parent=parent)


__all__ = ["SplitterWorkspace", "ThreePanelWorkspace", "TwoPanelWorkspace"]
