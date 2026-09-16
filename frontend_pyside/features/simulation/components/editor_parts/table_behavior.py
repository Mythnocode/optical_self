from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidgetItem

from frontend_pyside.features.simulation.surface_registry import (
    apply_type_defaults,
    ensure_surface_defaults,
    format_parameter_cell,
    parse_parameter_cell,
    surface_feature_summary,
    surface_uses_parameter,
)


class SurfaceTableMixin:
    def reload(self):
        try:
            from shiboken6 import isValid
            if not isValid(self.table):
                return
        except Exception:
            pass
        project = self.context.project
        current_row = max(0, self.table.currentRow())
        current_surface_id = ""
        if 0 <= current_row < len(project.surfaces):
            current_surface_id = str(getattr(project.surfaces[current_row], "surface_id", ""))
        self._loading_table = True
        try:
            self._sync_extra_columns()
            unused = str(getattr(self, "UNUSED_CELL", "未使用"))
            extra_specs = tuple(getattr(self, "_extra_specs", ()) or ())
            enabled_col = self._enabled_col()
            self.table.setRowCount(len(project.surfaces))
            for row, surface in enumerate(project.surfaces):
                ensure_surface_defaults(surface, fallback_group=f"L{row // 2 + 1}")
                values = [
                    row + 1,
                    surface.group_id,
                    surface.name,
                    surface.surface_type,
                    f"{surface.radius_mm:.2f}",
                    f"{surface.thickness_mm:.2f}",
                    surface.material,
                    f"{surface.semi_aperture_mm:.2f}",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column in (
                        self.COL_NUMBER,
                        self.COL_GROUP,
                        self.COL_TYPE,
                        self.COL_RADIUS,
                        self.COL_THICKNESS,
                        self.COL_APERTURE,
                    ):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if column == self.COL_NUMBER:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, column, item)
                for offset, spec in enumerate(extra_specs):
                    column = self.COL_COMMON_COUNT + offset
                    used = surface_uses_parameter(surface, spec.key)
                    if used:
                        value = surface.type_parameters.get(spec.key, spec.default)
                        item = QTableWidgetItem(format_parameter_cell(value, spec))
                        item.setToolTip(spec.helper or spec.label)
                    else:
                        item = QTableWidgetItem(unused)
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setForeground(QBrush(QColor("#98A2B3")))
                        item.setToolTip(f"{surface.surface_type}不使用此参数")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, column, item)
                enabled_item = QTableWidgetItem("是" if surface.enabled else "否")
                enabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, enabled_col, enabled_item)
            self.table.resizeRowsToContents()
            self._rebuild_component_filter()
            self._rebuild_summary()
            if project.surfaces:
                stable_row = next(
                    (index for index, item in enumerate(project.surfaces) if str(getattr(item, "surface_id", "")) == current_surface_id),
                    min(current_row, len(project.surfaces) - 1),
                )
                self.table.setCurrentCell(stable_row, self.COL_NAME)
        finally:
            self._loading_table = False
        self._filter_rows()

    def _rebuild_component_filter(self):
        selected = self.lens_filter.currentData()
        self.lens_filter.blockSignals(True)
        self.lens_filter.clear()
        self.lens_filter.addItem("全部表面", None)
        groups = []
        for surface in self.context.project.surfaces:
            ensure_surface_defaults(surface)
            if surface.group_id not in groups:
                groups.append(surface.group_id)
        for group in groups:
            self.lens_filter.addItem(group, group)
        target = self.lens_filter.findData(selected)
        self.lens_filter.setCurrentIndex(target if target >= 0 else 0)
        self.lens_filter.blockSignals(False)

    def _select(self, row, *_):
        if not 0 <= row < len(self.context.project.surfaces):
            return
        surface = self.context.project.surfaces[row]
        ensure_surface_defaults(surface, fallback_group=f"L{row // 2 + 1}")
        self._loading_properties = True
        try:
            self.selected_badge.setText(f"S{row + 1}｜{surface.group_id}｜{surface.name}")
            self.selected_badge.set_tone("info")
            feature = surface_feature_summary(surface)
            self.selection_context.setText(
                f"{surface.surface_type}｜材料 {surface.material}｜半口径 {surface.semi_aperture_mm:.2f} mm｜{feature}"
            )
            self.group_id.setText(surface.group_id)
            self.surface_name.setText(surface.name)
            self.surface_type.blockSignals(True)
            self.surface_type.setCurrentText(surface.surface_type)
            self.surface_type.blockSignals(False)
            self.radius.setValue(surface.radius_mm)
            self.thickness.setValue(surface.thickness_mm)
            self.aperture.setValue(surface.semi_aperture_mm)
            self.material.setCurrentText(surface.material)
            self.conic.setValue(surface.conic)
            self.aperture_type.setCurrentText(surface.type_parameters.get("_aperture_type", "圆形通光孔径"))
            self.clear_aperture.setValue(float(surface.type_parameters.get("_clear_aperture_mm", 2 * surface.semi_aperture_mm)))
            self.coating.setCurrentText(surface.coating)
            self.roughness.setValue(surface.roughness_nm)
            mechanical = surface.mechanical_diameter_mm or 2 * surface.semi_aperture_mm
            self.mechanical.setValue(max(0.0001, mechanical))
            self.enabled.setChecked(surface.enabled)
            self.note.setText(surface.note)
            self._rebuild_dynamic_editor(surface.surface_type, surface)
            self.previous_button.setEnabled(row > 0)
            self.next_button.setEnabled(row + 1 < len(self.context.project.surfaces))
        finally:
            self._loading_properties = False
        if hasattr(self.context, "select"):
            self.context.select(
                element_id=str(getattr(surface, "element_id", "")),
                surface_id=str(getattr(surface, "surface_id", "")),
            )
        self.surfaceSelected.emit(int(row))

    def _inline_edit_columns(self) -> tuple[int, ...]:
        extras = tuple(range(self.COL_COMMON_COUNT, self._enabled_col()))
        return (
            self.COL_GROUP, self.COL_NAME, self.COL_TYPE, self.COL_RADIUS,
            self.COL_THICKNESS, self.COL_MATERIAL, self.COL_APERTURE, *extras, self._enabled_col(),
        )

    def _table_double_clicked(self, row: int, column: int) -> None:
        """Double-click edits common fields; advanced properties remain explicit.

        The previous signal opened the Surface property window for *every*
        double-click, immediately stealing focus from the table editor.  That made
        cells advertise ItemIsEditable while no inline editor could stay open.
        """
        if not 0 <= row < len(self.context.project.surfaces):
            return
        if column in self._inline_edit_columns():
            item = self.table.item(row, column)
            if item is not None and bool(item.flags() & Qt.ItemFlag.ItemIsEditable):
                self.table.editItem(item)
            return
        self._activate_surface(row, column)

    def _activate_surface(self, row: int, _column: int = 0) -> None:
        if not 0 <= row < len(self.context.project.surfaces):
            return
        self.detail_toggle.setChecked(True)
        self.surfaceActivated.emit(int(row))

    def select_surface(self, row: int, *, open_properties: bool = False) -> None:
        if not 0 <= int(row) < len(self.context.project.surfaces):
            return
        self.table.setCurrentCell(int(row), self.COL_NAME)
        self.table.scrollToItem(self.table.item(int(row), self.COL_NAME))
        if open_properties:
            self.detail_toggle.setChecked(True)

    def selected_group_id(self) -> str:
        row = self.table.currentRow()
        if 0 <= row < len(self.context.project.surfaces):
            return str(self.context.project.surfaces[row].group_id or "")
        return ""

    def _table_item_changed(self, item: QTableWidgetItem):
        if self._loading_table:
            return
        row = item.row()
        column = item.column()
        if not 0 <= row < len(self.context.project.surfaces):
            return
        surface = self.context.project.surfaces[row]
        ensure_surface_defaults(surface, fallback_group=f"L{row // 2 + 1}")
        text = item.text().strip()
        extra_specs = tuple(getattr(self, "_extra_specs", ()) or ())
        enabled_col = self._enabled_col()
        try:
            if column == self.COL_GROUP:
                surface.group_id = text or f"S{row + 1}"
            elif column == self.COL_NAME:
                surface.name = text or f"S{row + 1}"
            elif column == self.COL_TYPE:
                apply_type_defaults(surface, text or "球面")
            elif column == self.COL_RADIUS:
                surface.radius_mm = float(text)
            elif column == self.COL_THICKNESS:
                value = float(text)
                if value < 0:
                    raise ValueError("thickness must be nonnegative")
                surface.thickness_mm = value
            elif column == self.COL_MATERIAL:
                surface.material = text or "AIR"
            elif column == self.COL_APERTURE:
                value = float(text)
                if value <= 0:
                    raise ValueError("aperture must be positive")
                surface.semi_aperture_mm = value
            elif column == enabled_col:
                surface.enabled = text.lower() not in {"否", "no", "false", "0", "禁用"}
            elif self.COL_COMMON_COUNT <= column < enabled_col:
                spec = extra_specs[column - self.COL_COMMON_COUNT]
                if not surface_uses_parameter(surface, spec.key):
                    return
                surface.type_parameters[spec.key] = parse_parameter_cell(text, spec)
            else:
                return
        except (ValueError, IndexError):
            self.reload()
            return
        self.operationCommitted.emit(f"修改 S{row + 1} {self.table.horizontalHeaderItem(column).text()}")
        self.context.touch_version()
        self.changed.emit()
