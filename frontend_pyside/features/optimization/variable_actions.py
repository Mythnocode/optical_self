
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QInputDialog, QTableWidget


class OptimizationVariableActions(QObject):
    changed = Signal()
    filterChanged = Signal(bool)

    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent)
        self.table = table
        self.enabled_only = False

    @staticmethod
    def row_enabled(table: QTableWidget, row: int) -> bool:
        item = table.item(row, 0)
        if item is None:
            return False
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return item.checkState() == Qt.CheckState.Checked
        return item.text() in {"☑", "✓", "1", "true", "True"}

    @staticmethod
    def set_row_enabled(table: QTableWidget, row: int, enabled: bool) -> None:
        item = table.item(row, 0)
        if item is None:
            return
        item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        item.setText("")

    def enable_matching(self, keyword: str) -> None:
        changed = False
        for row in range(self.table.rowCount()):
            parameter = self.table.item(row, 1)
            matched = bool(parameter and keyword in parameter.text())
            if self.row_enabled(self.table, row) != matched:
                self.set_row_enabled(self.table, row, matched)
                changed = True
        self._apply_filter()
        if changed:
            self.changed.emit()

    def toggle_enabled_only(self) -> None:
        self.enabled_only = not self.enabled_only
        self._apply_filter()
        self.filterChanged.emit(self.enabled_only)

    def refresh_filter(self) -> None:
        self._apply_filter()

    def handle_item_changed(self, item) -> None:
        if item is None or item.column() != 0:
            return
        self._apply_filter()
        self.changed.emit()

    def request_batch_bounds(self, parent=None) -> None:
        percent, accepted = QInputDialog.getDouble(
            parent,
            "批量设置变量范围",
            "以当前值为中心的上下浮动百分比：",
            30.0,
            0.01,
            1000.0,
            2,
        )
        if not accepted:
            return
        self.apply_batch_bounds(percent / 100.0)

    def apply_batch_bounds(self, relative_half_width: float) -> None:
        relative_half_width = max(float(relative_half_width), 1e-9)
        rows = [
            row
            for row in range(self.table.rowCount())
            if self.row_enabled(self.table, row)
        ]
        if not rows:
            rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            current = self.table.currentRow()
            rows = [current] if current >= 0 else []
        for row in rows:
            current_item = self.table.item(row, 3)
            if current_item is None:
                continue
            try:
                value = float(current_item.text())
            except (TypeError, ValueError):
                continue
            half_width = max(abs(value) * relative_half_width, relative_half_width)
            low = value - half_width
            high = value + half_width
            
            label = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
            if any(token in label for token in ("厚度", "间隔", "口径")):
                low = max(0.0, low)
            self.table.item(row, 4).setText(f"{low:.12g}")
            self.table.item(row, 5).setText(f"{high:.12g}")
        if rows:
            self.changed.emit()

    def _apply_filter(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.setRowHidden(
                row,
                self.enabled_only and not self.row_enabled(self.table, row),
            )


__all__ = ["OptimizationVariableActions"]
