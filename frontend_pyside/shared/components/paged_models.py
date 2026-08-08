
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class IncrementalRowsModel(QAbstractTableModel):


    def __init__(
        self,
        headers: Sequence[str] = (),
        rows: Iterable[Sequence[object]] = (),
        *,
        page_size: int = 250,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.headers = [str(item) for item in headers]
        self.page_size = max(1, int(page_size))
        self._all_rows = [tuple(item) for item in rows]
        self._visible_count = min(self.page_size, len(self._all_rows))

    def rowCount(self, parent=QModelIndex()) -> int:  
        return 0 if parent.isValid() else self._visible_count

    def columnCount(self, parent=QModelIndex()) -> int:  
        if parent.isValid():
            return 0
        if self.headers:
            return len(self.headers)
        return max((len(row) for row in self._all_rows), default=0)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < self._visible_count:
            return None
        row = self._all_rows[index.row()]
        value = row[index.column()] if index.column() < len(row) else ""
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return str(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return section + 1 if orientation == Qt.Orientation.Vertical else None

    def canFetchMore(self, parent=QModelIndex()) -> bool:  
        return not parent.isValid() and self._visible_count < len(self._all_rows)

    def fetchMore(self, parent=QModelIndex()) -> None:  
        if parent.isValid() or not self.canFetchMore(parent):
            return
        start = self._visible_count
        end = min(len(self._all_rows), start + self.page_size)
        self.beginInsertRows(QModelIndex(), start, end - 1)
        self._visible_count = end
        self.endInsertRows()

    def replace_rows(self, rows: Iterable[Sequence[object]]) -> None:
        self.beginResetModel()
        self._all_rows = [tuple(item) for item in rows]
        self._visible_count = min(self.page_size, len(self._all_rows))
        self.endResetModel()


class PagedCsvTableModel(IncrementalRowsModel):


    def __init__(
        self,
        path: str | Path,
        *,
        page_size: int = 250,
        max_preview_rows: int = 5000,
        encoding: str = "utf-8-sig",
        parent=None,
    ) -> None:
        source = Path(path)
        headers: list[str] = []
        rows: list[tuple[str, ...]] = []
        if source.exists():
            with source.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                headers = next(reader, [])
                for index, row in enumerate(reader):
                    if index >= max(1, int(max_preview_rows)):
                        break
                    rows.append(tuple(row))
        super().__init__(headers, rows, page_size=page_size, parent=parent)
        self.path = source


class PagedLogModel(IncrementalRowsModel):
    def __init__(self, entries=(), *, page_size: int = 500, parent=None) -> None:
        rows = [
            (
                item.get("time", ""),
                item.get("level", "INFO"),
                item.get("message", ""),
            )
            if isinstance(item, dict)
            else ("", "INFO", str(item))
            for item in entries
        ]
        super().__init__(("时间", "级别", "消息"), rows, page_size=page_size, parent=parent)


__all__ = ["IncrementalRowsModel", "PagedCsvTableModel", "PagedLogModel"]
