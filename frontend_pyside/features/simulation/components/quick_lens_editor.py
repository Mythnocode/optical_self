from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.surface_registry import ensure_surface_defaults
from frontend_pyside.shared.components.basic import Badge, SecondaryButton
from frontend_pyside.shared.components.tables import DataTable


class QuickLensEditor(QWidget):


    changed = Signal()
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    fullEditorRequested = Signal()

    COL_NUMBER = 0
    COL_GROUP = 1
    COL_RADIUS = 2
    COL_THICKNESS = 3
    COL_MATERIAL = 4

    def __init__(self, project_context, parent=None) -> None:
        super().__init__(parent)
        self.context = project_context
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(7)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.count_badge = Badge("0 个表面", "info")
        toolbar.addWidget(self.count_badge)
        toolbar.addStretch(1)
        self.full_editor_button = SecondaryButton("打开完整镜头编辑器")
        self.full_editor_button.clicked.connect(self.fullEditorRequested.emit)
        toolbar.addWidget(self.full_editor_button)
        root.addLayout(toolbar)

        self.table = DataTable(0, 5)
        self.table.setObjectName("quickLensTable")
        self.table.setHorizontalHeaderLabels(
            ["面号", "元件", "曲率 R", "厚度/间隔", "材料"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_NUMBER, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_GROUP, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_RADIUS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_THICKNESS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_MATERIAL, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_NUMBER, 48)
        self.table.setColumnWidth(self.COL_GROUP, 58)
        self.table.setMinimumHeight(340)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        root.addWidget(self.table, 1)

        self.table.currentCellChanged.connect(self._select)
        self.table.cellDoubleClicked.connect(self._activate)
        self.table.itemChanged.connect(self._table_item_changed)
        self.context.project_changed.connect(lambda _project: self.reload())
        self.reload()

    def reload(self) -> None:
        project = self.context.project
        current = max(0, self.table.currentRow())
        current_surface_id = ""
        if 0 <= current < len(project.surfaces):
            current_surface_id = str(getattr(project.surfaces[current], "surface_id", ""))
        self._loading = True
        try:
            self.table.setRowCount(len(project.surfaces))
            for row, surface in enumerate(project.surfaces):
                ensure_surface_defaults(surface, fallback_group=f"L{row // 2 + 1}")
                values = [
                    row + 1,
                    surface.group_id,
                    f"{surface.radius_mm:.8g}",
                    f"{surface.thickness_mm:.8g}",
                    surface.material,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == self.COL_NUMBER:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if column in {
                        self.COL_NUMBER,
                        self.COL_GROUP,
                        self.COL_RADIUS,
                        self.COL_THICKNESS,
                    }:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(
                        f"S{row + 1}｜{surface.name}｜{surface.surface_type}｜"
                        f"半口径 {surface.semi_aperture_mm:.4g} mm｜双击打开完整编辑器"
                    )
                    self.table.setItem(row, column, item)
            self.count_badge.setText(f"{len(project.surfaces)} 个表面")
            QTimer.singleShot(0, self._fit_table_height)
            if project.surfaces:
                stable_row = next(
                    (
                        index
                        for index, item in enumerate(project.surfaces)
                        if str(getattr(item, "surface_id", "")) == current_surface_id
                    ),
                    min(current, len(project.surfaces) - 1),
                )
                self.table.setCurrentCell(stable_row, self.COL_RADIUS)
        finally:
            self._loading = False

    def _fit_table_height(self) -> None:

        rows = max(1, min(self.table.rowCount(), 12))
        header_height = max(36, self.table.horizontalHeader().height())
        body_height = sum(
            max(34, self.table.rowHeight(row))
            for row in range(min(self.table.rowCount(), rows))
        )
        if self.table.rowCount() == 0:
            body_height = 34
        target = header_height + body_height + self.table.frameWidth() * 2 + 10
        self.table.setMinimumHeight(target)
        self.table.setMaximumHeight(target)

    def _select(self, row: int, *_args) -> None:
        if self._loading or not 0 <= row < len(self.context.project.surfaces):
            return
        surface = self.context.project.surfaces[row]
        if hasattr(self.context, "select"):
            self.context.select(
                element_id=str(getattr(surface, "element_id", "")),
                surface_id=str(getattr(surface, "surface_id", "")),
            )
        self.surfaceSelected.emit(row)

    def _activate(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.context.project.surfaces):
            self.surfaceActivated.emit(row)
            self.fullEditorRequested.emit()

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        row = item.row()
        if not 0 <= row < len(self.context.project.surfaces):
            return
        surface = self.context.project.surfaces[row]
        text = item.text().strip()
        try:
            if item.column() == self.COL_GROUP:
                surface.group_id = text or f"S{row + 1}"
            elif item.column() == self.COL_RADIUS:
                surface.radius_mm = float(text)
            elif item.column() == self.COL_THICKNESS:
                value = float(text)
                if value < 0:
                    raise ValueError
                surface.thickness_mm = value
            elif item.column() == self.COL_MATERIAL:
                surface.material = text or "AIR"
            else:
                return
        except ValueError:
            self.reload()
            return
        self.context.touch_version()
        self.changed.emit()

    def selected_group_id(self) -> str:
        row = self.table.currentRow()
        if 0 <= row < len(self.context.project.surfaces):
            return str(self.context.project.surfaces[row].group_id or "")
        return ""

    def select_surface(self, row: int, *, open_properties: bool = False) -> None:
        row = int(row)
        if not 0 <= row < len(self.context.project.surfaces):
            return
        self.table.setCurrentCell(row, self.COL_RADIUS)
        self.table.scrollToItem(self.table.item(row, self.COL_RADIUS))
        if open_properties:
            self.fullEditorRequested.emit()

    def set_properties_visible(self, _visible: bool) -> None:
        pass


__all__ = ["QuickLensEditor"]
