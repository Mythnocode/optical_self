from __future__ import annotations

import copy

from PySide6.QtCore import Qt

from frontend_pyside.core.types import LensSurface
from frontend_pyside.features.simulation.surface_registry import (
    apply_type_defaults,
    ensure_surface_defaults,
    get_surface_type,
    next_group_id,
    surface_feature_summary,
)


class SurfaceCommandMixin:
    def _reset_current(self):
        self._select(self.table.currentRow())

    def _step_selection(self, step: int):
        if not self.context.project.surfaces:
            return
        row = self.table.currentRow()
        row = max(0, min(len(self.context.project.surfaces) - 1, row + step))
        self.table.setCurrentCell(row, self.COL_NAME)
        self.table.scrollToItem(self.table.item(row, self.COL_NAME))

    def _apply(self):
        if getattr(self, "_loading_properties", False):
            return
        row = self.table.currentRow()
        if not 0 <= row < len(self.context.project.surfaces):
            return
        surface = self.context.project.surfaces[row]
        surface.group_id = self.group_id.text().strip() or f"S{row + 1}"
        surface.name = self.surface_name.text().strip() or f"S{row + 1}"
        apply_type_defaults(surface, self.surface_type.currentText())
        surface.radius_mm = self.radius.value() if self.radius.isEnabled() else 0.0
        surface.thickness_mm = self.thickness.value()
        surface.semi_aperture_mm = self.aperture.value() if self.aperture.isEnabled() else max(surface.semi_aperture_mm, 0.001)
        surface.material = self.material.currentText().strip() if self.material.isEnabled() else "AIR"
        surface.material = surface.material or "AIR"
        surface.conic = self.conic.value()
        surface.type_parameters["_aperture_type"] = self.aperture_type.currentText()
        surface.type_parameters["_clear_aperture_mm"] = self.clear_aperture.value()
        for key, control in self._dynamic_controls.items():
            surface.type_parameters[key] = self._control_value(control, self._dynamic_specs[key])
        surface.coating = self.coating.currentText().strip() or "无"
        surface.roughness_nm = self.roughness.value()
        surface.mechanical_diameter_mm = self.mechanical.value()
        surface.enabled = self.enabled.isChecked()
        surface.note = self.note.text().strip()
        self.operationCommitted.emit(f"修改 S{row + 1} 表面属性")
        self.context.touch_version()
        self.reload()
        self.selected_badge.setText(f"S{row + 1} 已自动应用")
        self.selected_badge.set_tone("success")
        self.changed.emit()

    def _existing_groups(self):
        return [getattr(surface, "group_id", "") for surface in self.context.project.surfaces]

    def _insert_after_current(self, surfaces):
        row = self.table.currentRow()
        index = row + 1 if 0 <= row < len(self.context.project.surfaces) else len(self.context.project.surfaces)
        self.context.project.surfaces[index:index] = surfaces
        self.operationCommitted.emit(f"新增 {len(surfaces)} 个光学表面")
        self.context.touch_version()
        self.changed.emit()
        self.table.setCurrentCell(index, self.COL_NAME)

    def _add_lens(self):
        group = next_group_id(self._existing_groups(), "L")
        first = LensSurface(f"{group} 前表面", 20.0, 2.0, "N-BK7", 3.0, group_id=group)
        surfaces = [
            first,
            LensSurface(
                f"{group} 后表面", -20.0, 3.0, "AIR", 3.0,
                group_id=group, element_id=first.element_id,
            ),
        ]
        self._insert_after_current(surfaces)

    def _add_surface_type(self, type_name: str):
        spec = get_surface_type(type_name)
        group = next_group_id(self._existing_groups(), spec.group_prefix)
        material = "AIR" if "material" in spec.disabled_common_fields else ("MIRROR" if type_name == "反射镜" else "N-BK7")
        surface = LensSurface(
            f"{group} {type_name}",
            0.0 if "radius" in spec.disabled_common_fields else 50.0,
            1.0,
            material,
            5.0,
            surface_type=type_name,
            group_id=group,
        )
        apply_type_defaults(surface, type_name)
        self._insert_after_current([surface])
        self.detail_toggle.setChecked(True)
        self.property_tabs.setCurrentIndex(self.dynamic_tab_index)

    def _duplicate_surface(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.context.project.surfaces):
            return
        source = copy.deepcopy(self.context.project.surfaces[row])
        spec = get_surface_type(source.surface_type)
        source.group_id = next_group_id(self._existing_groups(), spec.group_prefix)
        source.element_id = ""
        source.surface_id = ""
        source.__post_init__()
        source.name = f"{source.group_id} {source.surface_type} 副本"
        self._insert_after_current([source])

    def _duplicate_group(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.context.project.surfaces):
            return
        selected = self.context.project.surfaces[row]
        ensure_surface_defaults(selected)
        group_surfaces = [surface for surface in self.context.project.surfaces if getattr(surface, "group_id", "") == selected.group_id]
        if not group_surfaces:
            return
        prefix = "".join(character for character in selected.group_id if character.isalpha()) or "G"
        new_group = next_group_id(self._existing_groups(), prefix)
        copies = []
        new_element_id = ""
        for surface in group_surfaces:
            clone = copy.deepcopy(surface)
            clone.group_id = new_group
            clone.element_id = new_element_id
            clone.surface_id = ""
            clone.__post_init__()
            if not new_element_id:
                new_element_id = clone.element_id
            else:
                clone.element_id = new_element_id
            clone.name = surface.name.replace(selected.group_id, new_group, 1)
            copies.append(clone)
        self._insert_after_current(copies)

    def _toggle_detail(self, expanded: bool):
        self.detail_content.setVisible(expanded)
        self.detail_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.detail_toggle.setText("收起表面属性" if expanded else "展开表面属性")

    def _set_column_visible(self, column: int, visible: bool):
        self.table.setColumnHidden(column, not visible)

    def _remove(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.context.project.surfaces):
            removed = self.context.project.surfaces.pop(row)
            self.operationCommitted.emit(f"删除 S{row + 1} {removed.name}")
            self.context.touch_version()
            self.changed.emit()

    def _filter_rows(self, *_):
        needle = self.search.text().strip().lower()
        selected_group = self.lens_filter.currentData()
        visible = 0
        for row, surface in enumerate(self.context.project.surfaces):
            ensure_surface_defaults(surface, fallback_group=f"L{row // 2 + 1}")
            haystack = (
                f"{row + 1} {surface.group_id} {surface.name} {surface.material} "
                f"{surface.surface_type} {surface_feature_summary(surface, max_items=99)}"
            ).lower()
            hidden = bool(needle and needle not in haystack)
            hidden = hidden or (selected_group is not None and surface.group_id != selected_group)
            self.table.setRowHidden(row, hidden)
            if not hidden:
                visible += 1
        self.visible_count.setText(f"{visible} / {len(self.context.project.surfaces)} 面")
