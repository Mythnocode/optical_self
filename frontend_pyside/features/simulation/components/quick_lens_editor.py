from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.surface_registry import ensure_surface_defaults
from frontend_pyside.shared.components.basic import SecondaryButton


_SURFACE_TYPE_NAMES = {
    "sphere": "球面镜",
    "spherical": "球面镜",
    "asphere": "非球面镜",
    "aspheric": "非球面镜",
    "plane": "平面镜",
    "mirror": "反射镜",
    "grating": "衍射元件",
    "binary": "二元衍射",
    "stop": "光阑",
    "coordinate_break": "坐标断点",
    "detector": "探测/像面",
}


class _LensGroupButton(SecondaryButton):
    doubleActivated = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self.doubleActivated.emit()
        super().mouseDoubleClickEvent(event)


class QuickLensEditor(QWidget):
    """Compact lens-object navigator used in the narrow simulation sidebar.

    The former implementation embedded the complete Surface table here.  That
    produced both horizontal and vertical scrollbars in a ~300 px sidebar and
    duplicated the real lens editor.  This widget now has one responsibility:
    choose a lens object.  Full Surface data remains available from the complete
    lens editor and therefore no optical capability is removed.
    """

    changed = Signal()
    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    fullEditorRequested = Signal()

    def __init__(self, project_context, parent=None) -> None:
        super().__init__(parent)
        self.context = project_context
        self._selected_surface_row = -1
        self._group_rows: dict[str, list[int]] = {}
        self._buttons: dict[str, _LensGroupButton] = {}

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(2, 0, 2, 0)
        toolbar.setSpacing(6)
        self.count_label = QLabel("0 镜头 · 0 表面")
        self.count_label.setObjectName("compactContext")
        toolbar.addWidget(self.count_label, 1)
        self.full_editor_button = QToolButton(self)
        self.full_editor_button.setText("完整编辑器 ›")
        self.full_editor_button.setObjectName("compactTextTool")
        self.full_editor_button.setToolTip("打开完整 Surface / 材料 / 非球面参数编辑器")
        self.full_editor_button.clicked.connect(self.fullEditorRequested.emit)
        toolbar.addWidget(self.full_editor_button)
        root.addLayout(toolbar)

        self.list_host = QWidget(self)
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        root.addWidget(self.list_host)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.context.project_changed.connect(lambda _project: self.reload())
        self.reload()

    @staticmethod
    def _surface_type_name(surfaces: list[object]) -> str:
        kinds = [str(getattr(item, "surface_type", "") or "").strip().lower() for item in surfaces]
        non_plane = next((kind for kind in kinds if kind not in {"", "plane"}), kinds[0] if kinds else "")
        return _SURFACE_TYPE_NAMES.get(non_plane, "镜头")

    @staticmethod
    def _material_name(surfaces: list[object]) -> str:
        materials = []
        for item in surfaces:
            material = str(getattr(item, "material", "") or "").strip()
            if material and material.upper() not in {"AIR", "VACUUM"} and material not in materials:
                materials.append(material)
        return "/".join(materials[:2]) if materials else "空气/未指定"

    def _clear_buttons(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.button_group.removeButton(widget)
                widget.deleteLater()
        self._buttons.clear()
        self._group_rows.clear()

    def reload(self) -> None:
        project = self.context.project
        previous_group = self.selected_group_id()
        self._clear_buttons()

        grouped: "OrderedDict[str, list[tuple[int, object]]]" = OrderedDict()
        for row, surface in enumerate(project.surfaces):
            ensure_surface_defaults(surface, fallback_group=f"L{row // 2 + 1}")
            group_id = str(getattr(surface, "group_id", "") or f"L{row // 2 + 1}")
            grouped.setdefault(group_id, []).append((row, surface))

        for group_index, (group_id, entries) in enumerate(grouped.items()):
            rows = [row for row, _surface in entries]
            surfaces = [surface for _row, surface in entries]
            self._group_rows[group_id] = rows
            kind = self._surface_type_name(surfaces)
            material = self._material_name(surfaces)
            button = _LensGroupButton(f"{group_id}   {kind}   {material} · {len(rows)} 面", self.list_host)
            button.setObjectName("lensObjectButton")
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setToolTip(f"{group_id}｜{len(rows)} 个表面｜单击选择，双击打开完整镜头编辑器")
            button.clicked.connect(lambda _checked=False, gid=group_id: self._select_group(gid))
            button.doubleActivated.connect(lambda gid=group_id: self._activate_group(gid))
            self.button_group.addButton(button, group_index)
            self.list_layout.addWidget(button)
            self._buttons[group_id] = button

        self.count_label.setText(f"{len(grouped)} 镜头 · {len(project.surfaces)} 表面")

        if grouped:
            group_to_select = previous_group if previous_group in grouped else next(iter(grouped))
            self._select_group(group_to_select, emit_signal=False)

    def _select_group(self, group_id: str, *, emit_signal: bool = True) -> None:
        rows = self._group_rows.get(str(group_id), [])
        if not rows:
            return
        row = rows[0]
        self._selected_surface_row = row
        button = self._buttons.get(str(group_id))
        if button is not None:
            button.setChecked(True)
        surface = self.context.project.surfaces[row]
        if hasattr(self.context, "select"):
            self.context.select(
                element_id=str(getattr(surface, "element_id", "")),
                surface_id=str(getattr(surface, "surface_id", "")),
            )
        if emit_signal:
            self.surfaceSelected.emit(row)

    def _activate_group(self, group_id: str) -> None:
        rows = self._group_rows.get(str(group_id), [])
        if not rows:
            return
        self._select_group(group_id, emit_signal=True)
        self.surfaceActivated.emit(rows[0])
        self.fullEditorRequested.emit()

    def selected_group_id(self) -> str:
        for group_id, button in self._buttons.items():
            if button.isChecked():
                return group_id
        if 0 <= self._selected_surface_row < len(self.context.project.surfaces):
            return str(getattr(self.context.project.surfaces[self._selected_surface_row], "group_id", "") or "")
        return ""

    def select_surface(self, row: int, *, open_properties: bool = False) -> None:
        row = int(row)
        if not 0 <= row < len(self.context.project.surfaces):
            return
        self._selected_surface_row = row
        surface = self.context.project.surfaces[row]
        group_id = str(getattr(surface, "group_id", "") or "")
        if group_id in self._buttons:
            self._buttons[group_id].setChecked(True)
        if open_properties:
            self.fullEditorRequested.emit()

    def set_properties_visible(self, _visible: bool) -> None:
        pass


__all__ = ["QuickLensEditor"]
