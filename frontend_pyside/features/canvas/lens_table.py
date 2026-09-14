"""镜头组节点使用的纯表格编辑器。

这里故意只保留顺序表面表格，不复用包含导航、属性抽屉和页面级布局的
OpticalSystemEditor，避免把完整页面嵌入中心节点。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from frontend_pyside.features.simulation.components.surface_delegate import SurfaceTypeDelegate
from frontend_pyside.features.simulation.surface_registry import apply_type_defaults


class LensSurfaceTable(QWidget):
    changed = Signal()

    HEADERS = (
        "面号", "元件组", "表面名称", "表面类型", "曲率半径 R / mm",
        "厚度 / mm", "材料", "柱轴角 / deg",
    )

    def __init__(self, project_context, parent=None):
        super().__init__(parent)
        self.context = project_context
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(list(self.HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(3, SurfaceTypeDelegate(self.table))
        self.table.setMinimumSize(560, 260)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        # 首列紧跟可用宽度伸缩，其余列按比例伸缩，最后一列 stretch 吸收余量，
        # 字号随节点尺寸缩放，避免"字太小"。
        self.table.horizontalHeader().setStretchLastSection(True)
        self._col_ratios = (0.060, 0.090, 0.165, 0.130, 0.165, 0.145, 0.120, 0.125)
        self.table.itemChanged.connect(self._item_changed)
        self._apply_responsive_size()
        root.addWidget(self.table)
        self.context.project_changed.connect(lambda *_: self.reload())
        self.reload()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_size()

    def _apply_responsive_size(self) -> None:
        """让字号、行高、列宽随可用空间自适应：表越大字越大，但不超过 18px。"""
        vp_width = self.table.viewport().width()
        vp_height = self.table.viewport().height()
        rows = max(1, self.table.rowCount())
        width_score = max(vp_width, 120) / 46.0
        height_score = max(vp_height, 100) / float(rows + 3.0) * 0.9
        px = int(min(18.0, max(10.0, width_score, height_score)))
        font = QFont(self.table.font())
        font.setPixelSize(px)
        self.table.setFont(font)
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, px + 13)
        self.table.horizontalHeader().setFixedHeight(px + 14)
        usable = self.table.viewport().width()
        if usable <= 0:
            return
        ratio_sum = sum(self._col_ratios[:-1])
        for col, ratio in enumerate(self._col_ratios[:-1]):
            # 防止列宽缩小导致不可用
            col_w = max(46, int(usable * ratio / ratio_sum))
            self.table.setColumnWidth(col, col_w)

    def reload(self) -> None:
        surfaces = list(self.context.project.surfaces)
        self._loading = True
        try:
            self.table.setRowCount(len(surfaces))
            for row, surface in enumerate(surfaces):
                values = (
                    row + 1,
                    str(surface.group_id or ""),
                    str(surface.name or ""),
                    str(surface.surface_type or ""),
                    f"{float(surface.radius_mm):.8g}",
                    f"{float(surface.thickness_mm):.8g}",
                    str(surface.material or "AIR"),
                    f"{float((surface.type_parameters or {}).get('cylinder_axis_deg', 0.0)):.8g}"
                    if str(surface.surface_type) in {"柱面", "柱面镜", "cylindrical"}
                    else "—",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter if column in (0, 1) else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    if column in (0, 1):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, column, item)
        finally:
            self._loading = False

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() in (0, 1):
            return
        row = item.row()
        surfaces = list(self.context.project.surfaces)
        if not 0 <= row < len(surfaces):
            return
        surface = surfaces[row]
        text = item.text().strip()
        changes = {}
        try:
            if item.column() == 2:
                changes["name"] = text or f"S{row + 1}"
            elif item.column() == 3:
                new_type = text or "球面"
                apply_type_defaults(surface, new_type)
                changes["surface_type"] = surface.surface_type
                changes["type_parameters"] = dict(surface.type_parameters or {})
            elif item.column() == 4:
                changes["radius_mm"] = float(text)
            elif item.column() == 5:
                value = float(text)
                if value < 0:
                    raise ValueError
                changes["thickness_mm"] = value
            elif item.column() == 6:
                changes["material"] = text or "AIR"
            elif item.column() == 7:
                if str(surface.surface_type) not in {"柱面", "柱面镜", "cylindrical"}:
                    self.reload()
                    return
                axis = float(text) % 180.0
                params = dict(surface.type_parameters or {})
                params["cylinder_axis_deg"] = axis
                changes["type_parameters"] = params
            if changes:
                self.context.update_surface(str(surface.surface_id), **changes)
                self.changed.emit()
        except (TypeError, ValueError):
            self.reload()


__all__ = ["LensSurfaceTable"]
