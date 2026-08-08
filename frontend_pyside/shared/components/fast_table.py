
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView


class RowsTableModel(QAbstractTableModel):


    def __init__(
        self,
        headers: Sequence[str] = (),
        parent=None,
        *,
        page_size: int = 200,
    ) -> None:
        super().__init__(parent)
        self._headers = [str(value) for value in headers]
        self._all_rows: list[list[Any]] = []
        self._rows: list[list[Any]] = []
        self._all_tooltips: list[list[str]] = []
        self._tooltips: list[list[str]] = []
        self._align_columns: set[int] = set()
        self._page_size = max(1, int(page_size))

    def rowCount(self, parent=QModelIndex()) -> int:  
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if not (0 <= index.column() < len(row)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = row[index.column()]
            return "" if value is None else str(value)
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.row() < len(self._tooltips):
                tips = self._tooltips[index.row()]
                if index.column() < len(tips):
                    return tips[index.column()] or None
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in self._align_columns:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def canFetchMore(self, parent=QModelIndex()) -> bool:  
        return not parent.isValid() and len(self._rows) < len(self._all_rows)

    def fetchMore(self, parent=QModelIndex()) -> None:  
        if parent.isValid() or not self.canFetchMore(parent):
            return
        start = len(self._rows)
        count = min(self._page_size, len(self._all_rows) - start)
        end = start + count - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._rows.extend(self._all_rows[start : start + count])
        self._tooltips.extend(self._all_tooltips[start : start + count])
        self.endInsertRows()

    def set_headers(self, headers: Sequence[str]) -> None:
        self.beginResetModel()
        self._headers = [str(value) for value in headers]
        self._all_rows = []
        self._rows = []
        self._all_tooltips = []
        self._tooltips = []
        self.endResetModel()

    def set_rows(
        self,
        rows: Iterable[Sequence[Any]],
        *,
        tooltips: Iterable[Sequence[str]] | None = None,
        align_columns: Iterable[int] = (),
        eager_rows: int | None = None,
    ) -> None:
        normalized = self._normalize_rows(rows)
        normalized_tips = [list(row) for row in tooltips] if tooltips is not None else []
        while len(normalized_tips) < len(normalized):
            normalized_tips.append([])
        visible = min(
            len(normalized),
            max(0, int(eager_rows if eager_rows is not None else self._page_size)),
        )
        self.beginResetModel()
        self._all_rows = normalized
        self._rows = normalized[:visible]
        self._all_tooltips = normalized_tips
        self._tooltips = normalized_tips[:visible]
        self._align_columns = {int(value) for value in align_columns}
        self.endResetModel()

    def append_rows(self, rows: Iterable[Sequence[Any]]) -> None:
        normalized = self._normalize_rows(rows)
        if not normalized:
            return
        self._all_rows.extend(normalized)
        self._all_tooltips.extend([[] for _ in normalized])
        if len(self._rows) == len(self._all_rows) - len(normalized):
            self.fetchMore()

    def update_row(self, row: int, values: Sequence[Any], *, source_index: bool = False) -> bool:
        row = int(row)
        if source_index:
            if not (0 <= row < len(self._all_rows)):
                return False
            normalized = self._normalize_rows([values])[0]
            self._all_rows[row] = normalized
            if row >= len(self._rows):
                return True
            self._rows[row] = normalized
        else:
            if not (0 <= row < len(self._rows)):
                return False
            normalized = self._normalize_rows([values])[0]
            self._rows[row] = normalized
            self._all_rows[row] = normalized
        left = self.index(row, 0)
        right = self.index(row, max(0, self.columnCount() - 1))
        self.dataChanged.emit(left, right, [Qt.ItemDataRole.DisplayRole])
        return True

    def update_cells(self, row: int, values: dict[int, Any]) -> bool:
        row = int(row)
        if not (0 <= row < len(self._rows)):
            return False
        columns = sorted(int(column) for column in values if 0 <= int(column) < self.columnCount())
        if not columns:
            return False
        for column in columns:
            value = values[column]
            self._rows[row][column] = value
            self._all_rows[row][column] = value
        self.dataChanged.emit(
            self.index(row, columns[0]),
            self.index(row, columns[-1]),
            [Qt.ItemDataRole.DisplayRole],
        )
        return True

    def row_values(self, row: int) -> list[Any]:
        return list(self._rows[row]) if 0 <= row < len(self._rows) else []

    def source_row_values(self, row: int) -> list[Any]:
        return list(self._all_rows[row]) if 0 <= row < len(self._all_rows) else []

    @property
    def total_row_count(self) -> int:
        return len(self._all_rows)

    def _normalize_rows(self, rows: Iterable[Sequence[Any]]) -> list[list[Any]]:
        normalized = [list(row) for row in rows]
        width = len(self._headers)
        if width:
            for row in normalized:
                if len(row) < width:
                    row.extend([""] * (width - len(row)))
                elif len(row) > width:
                    del row[width:]
        return normalized


class FastTableView(QTableView):


    currentCellChanged = Signal(int, int, int, int)

    def __init__(self, headers: Sequence[str] = (), parent=None, *, page_size: int = 200) -> None:
        super().__init__(parent)
        self._rows_model = RowsTableModel(headers, self, page_size=page_size)
        self.setModel(self._rows_model)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setMinimumSectionSize(64)
        self.horizontalHeader().setDefaultSectionSize(112)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setSortingEnabled(False)
        self.selectionModel().currentChanged.connect(self._current_changed)

    @property
    def rows_model(self) -> RowsTableModel:
        return self._rows_model

    def _current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        self.currentCellChanged.emit(
            current.row(), current.column(), previous.row(), previous.column()
        )

    def set_rows(
        self,
        rows: Iterable[Sequence[Any]],
        *,
        tooltips: Iterable[Sequence[str]] | None = None,
        align_columns: Iterable[int] = (),
        eager_rows: int | None = None,
    ) -> None:
        self.setUpdatesEnabled(False)
        try:
            self._rows_model.set_rows(
                rows,
                tooltips=tooltips,
                align_columns=align_columns,
                eager_rows=eager_rows,
            )
        finally:
            self.setUpdatesEnabled(True)
            self.viewport().update()

    def update_cells(self, row: int, values: dict[int, Any]) -> bool:
        return self._rows_model.update_cells(row, values)

    def currentRow(self) -> int:  
        index = self.currentIndex()
        return index.row() if index.isValid() else -1

    def setCurrentCell(self, row: int, column: int = 0) -> None:  
        index = self._rows_model.index(row, column)
        if index.isValid():
            self.setCurrentIndex(index)
            super().selectRow(row)

    def selectRow(self, row: int) -> None:  
        index = self._rows_model.index(row, 0)
        if index.isValid():
            self.setCurrentIndex(index)
            super().selectRow(row)

    def stretch_columns(self, *columns: int) -> None:
        header = self.horizontalHeader()
        for column in columns:
            if 0 <= column < self._rows_model.columnCount():
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def content_columns(self, *columns: int) -> None:
        header = self.horizontalHeader()
        for column in columns:
            if 0 <= column < self._rows_model.columnCount():
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)


__all__ = ["FastTableView", "RowsTableModel"]
