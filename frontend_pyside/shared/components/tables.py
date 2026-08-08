from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget


class DataTable(QTableWidget):


    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setMinimumSectionSize(72)
        self.horizontalHeader().setDefaultSectionSize(120)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    @contextmanager
    def bulk_update(self, *, disable_sorting: bool = True) -> Iterator[None]:

        sorting = self.isSortingEnabled()
        blocked = self.signalsBlocked()
        self.setUpdatesEnabled(False)
        self.blockSignals(True)
        if disable_sorting and sorting:
            self.setSortingEnabled(False)
        try:
            yield
        finally:
            if disable_sorting and sorting:
                self.setSortingEnabled(True)
            self.blockSignals(blocked)
            self.setUpdatesEnabled(True)
            self.viewport().update()

    def stretch_columns(self, *columns: int) -> None:
        header = self.horizontalHeader()
        for column in columns:
            if 0 <= column < self.columnCount():
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def content_columns(self, *columns: int) -> None:
        header = self.horizontalHeader()
        for column in columns:
            if 0 <= column < self.columnCount():
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
