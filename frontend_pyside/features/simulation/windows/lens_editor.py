from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.components import OpticalSystemEditor
from frontend_pyside.shared.components.basic import Badge, SecondaryButton
from frontend_pyside.shared.lifecycle import SignalConnectionBag
from frontend_pyside.shared.settings import WorkspaceStateStore


@dataclass
class _HistoryEntry:
    description: str
    before: object
    after: object


class LensEditorWindow(QMainWindow):
    """Sequential Surface editor.

    The Surface sequence is the source of truth.  ``group_id``/``element_id`` are
    optional grouping metadata only; the UI never assumes one lens equals exactly
    two surfaces, so cemented doublets/triplets and special surfaces remain valid.
    """

    def __init__(self, project_context, parent=None) -> None:
        super().__init__(parent)
        self.project_context = project_context
        self.workspace_state = WorkspaceStateStore("lens_editor")
        self.connections = SignalConnectionBag()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("完整镜头编辑器")
        self.resize(1460, 860)
        self.setMinimumSize(900, 620)

        self._history: list[_HistoryEntry] = []
        self._history_checkpoint_count = 0
        self._history_limit = 200
        self._history_index = 0
        self._restoring = False
        self._last_snapshot = copy.deepcopy(project_context.project)
        self._pending_description = "修改镜头参数"

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        toolbar = QFrame()
        toolbar.setObjectName("lensWindowToolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(9, 5, 9, 5)
        tools.setSpacing(6)
        self.project_label = QLabel()
        self.project_label.setObjectName("cardTitle")
        tools.addWidget(self.project_label)
        self.dirty_badge = Badge("当前系统", "success")
        tools.addWidget(self.dirty_badge)
        tools.addStretch(1)

        self.undo_button = SecondaryButton("撤销 Ctrl+Z")
        self.redo_button = SecondaryButton("重做 Ctrl+Y")
        self.history_button = SecondaryButton("操作历史")
        self.reverse_button = SecondaryButton("反转所选元件")
        for button in (
            self.undo_button,
            self.redo_button,
            self.history_button,
            self.reverse_button,
        ):
            tools.addWidget(button)
        root.addWidget(toolbar)

        self.editor = OpticalSystemEditor(project_context)
        self.editor.detail_card.hide()
        self.editor.detail_toggle.setChecked(True)
        self.editor.apply_button.hide()
        self.editor.reset_button.hide()
        root.addWidget(self.editor, 1)

        # Advanced Surface fields live in a resizable on-demand window instead of
        # consuming a permanent right inspector and shrinking the central table.
        self.property_dialog = QDialog(self)
        self.property_dialog.setObjectName("surfacePropertyDialog")
        self.property_dialog.setWindowTitle("表面属性")
        self.property_dialog.setModal(False)
        self.property_dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.property_dialog.setSizeGripEnabled(True)
        self.property_dialog.resize(640, 720)
        self.property_dialog.setMinimumSize(520, 460)
        prop_root = QVBoxLayout(self.property_dialog)
        prop_root.setContentsMargins(8, 8, 8, 8)
        prop_root.addWidget(self.editor.detail_content, 1)
        self.editor.detail_content.show()

        footer = QFrame()
        footer.setObjectName("lensWindowFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(9, 5, 9, 5)
        self.history_label = QLabel("历史位置：0 / 0")
        self.history_label.setObjectName("helperText")
        footer_layout.addWidget(self.history_label)
        footer_layout.addStretch(1)
        self.status_label = QLabel("公共列可直接双击编辑；高级参数用“表面属性…”打开。修改实时写入当前系统，可用 Ctrl+Z / Ctrl+Y 撤销。")
        self.status_label.setObjectName("helperText")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label)
        root.addWidget(footer)

        self.setCentralWidget(central)
        self.editor.changed.connect(self._record_external_change)
        if hasattr(self.editor, "operationCommitted"):
            self.editor.operationCommitted.connect(self._set_pending_description)
        self.editor.surfaceActivated.connect(self._open_surface_properties)
        self.connections.connect(self.project_context.project_changed, self._project_changed)

        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.reverse_button.clicked.connect(self.reverse_selected_group)
        self.history_button.clicked.connect(self.show_history)

        self.workspace_state.restore_geometry("window", self)
        self.workspace_state.restore_geometry("surface_properties", self.property_dialog)
        self.workspace_state.restore_table("lens_data", self.editor.table)
        self.workspace_state.restore_tab("properties", self.editor.property_tabs, 0)
        self._refresh_status()

    def _project_changed(self, _project) -> None:
        if not self._restoring:
            self._refresh_status()

    def _open_surface_properties(self, row: int) -> None:
        row = int(row)
        if not 0 <= row < len(self.project_context.project.surfaces):
            return
        surface = self.project_context.project.surfaces[row]
        self.property_dialog.setWindowTitle(f"表面属性 · S{row + 1} · {surface.name}")
        self.property_dialog.show()
        if self.property_dialog.isMinimized():
            self.property_dialog.showNormal()
        self.property_dialog.raise_()
        self.property_dialog.activateWindow()

    def _set_pending_description(self, description: str) -> None:
        self._pending_description = str(description or "修改镜头参数")

    def _record_external_change(self) -> None:
        if self._restoring:
            return
        current = copy.deepcopy(self.project_context.project)
        if current == self._last_snapshot:
            return
        if self._history_index < len(self._history):
            self._history = self._history[: self._history_index]
        self._history.append(_HistoryEntry(self._pending_description, self._last_snapshot, current))
        if len(self._history) > self._history_limit:
            overflow = len(self._history) - self._history_limit
            del self._history[:overflow]
            self._history_checkpoint_count += overflow
        self._history_index = len(self._history)
        self._last_snapshot = copy.deepcopy(current)
        self._pending_description = "修改镜头参数"
        self._refresh_status()

    def undo(self) -> None:
        if self._history_index <= 0:
            return
        entry = self._history[self._history_index - 1]
        self._restore(entry.before)
        self._history_index -= 1
        self.status_label.setText(f"已撤销：{entry.description}")
        self._refresh_status()

    def redo(self) -> None:
        if self._history_index >= len(self._history):
            return
        entry = self._history[self._history_index]
        self._restore(entry.after)
        self._history_index += 1
        self.status_label.setText(f"已重做：{entry.description}")
        self._refresh_status()

    def _restore(self, project) -> None:
        self._restoring = True
        try:
            self.project_context.set_project(copy.deepcopy(project))
            self._last_snapshot = copy.deepcopy(project)
            self.editor.reload()
        finally:
            self._restoring = False

    def show_history(self) -> None:
        if not self._history:
            QMessageBox.information(self, "操作历史", "当前尚无可显示的镜头修改记录。")
            return
        lines = []
        if self._history_checkpoint_count:
            lines.append(f"更早的 {self._history_checkpoint_count} 步已归档。")
        for index, entry in enumerate(self._history, 1):
            marker = " ← 当前" if index == self._history_index else ""
            lines.append(f"{index:02d}. {entry.description}{marker}")
        QMessageBox.information(self, "操作历史", "\n".join(lines))

    def reverse_selected_group(self) -> None:
        row = self.editor.table.currentRow()
        surfaces = self.project_context.project.surfaces
        if not 0 <= row < len(surfaces):
            QMessageBox.information(self, "反转元件", "请先在 Surface 表中选择一个光学元件。")
            return
        selected_surface = surfaces[row]
        group_id = str(getattr(selected_surface, "group_id", "") or f"S{row + 1}")
        element_id = str(getattr(selected_surface, "element_id", ""))
        # group_id is the sequential editor's optical-element grouping marker.
        # Legacy/default projects may give each Surface a distinct element_id, so
        # using element_id here would incorrectly reject ordinary L1/L2 groups.
        indexes = [i for i, surface in enumerate(surfaces) if str(getattr(surface, "group_id", "")) == group_id]
        if len(indexes) < 2 or indexes != list(range(min(indexes), max(indexes) + 1)):
            QMessageBox.warning(self, "不能反转", "所选元件必须由两个以上连续 Surface 组成。")
            return
        supported = {"球面", "平面"}
        unsupported = [surfaces[i].surface_type for i in indexes if surfaces[i].surface_type not in supported]
        if unsupported:
            QMessageBox.warning(
                self,
                "不能自动反转",
                "当前元件包含尚未支持安全自动反转的表面类型：" + "、".join(sorted(set(unsupported))),
            )
            return

        originals = [copy.deepcopy(surfaces[i]) for i in indexes]
        count = len(originals)
        reversed_surfaces = []
        old_orientation = str(originals[0].type_parameters.get("_element_orientation", "forward"))
        new_orientation = "forward" if old_orientation == "reversed" else "reversed"
        for new_index, old_index in enumerate(range(count - 1, -1, -1)):
            source = copy.deepcopy(originals[old_index])
            source.radius_mm = -float(source.radius_mm)
            donor = originals[old_index - 1] if old_index > 0 else originals[-1]
            source.material = donor.material
            source.thickness_mm = donor.thickness_mm
            source.element_id = element_id
            source.group_id = group_id
            source.type_parameters["_element_orientation"] = new_orientation
            if count == 2:
                source.name = f"{group_id} {'前表面' if new_index == 0 else '后表面'}"
            elif new_index == 0:
                source.name = f"{group_id} 前表面"
            elif new_index == count - 1:
                source.name = f"{group_id} 后表面"
            else:
                source.name = f"{group_id} 内部面 {new_index}"
            reversed_surfaces.append(source)

        start = indexes[0]
        self._pending_description = f"反转元件 {group_id}（{old_orientation} → {new_orientation}）"
        surfaces[start : start + count] = reversed_surfaces
        self.project_context.touch_version()
        self.editor.reload()
        self.editor.table.setCurrentCell(start, self.editor.COL_NAME)
        self.editor.changed.emit()
        self.status_label.setText(f"{group_id} 已反转；可使用 Ctrl+Z 一步撤销。")

    def _refresh_status(self) -> None:
        project = self.project_context.project
        self.project_label.setText(f"当前系统 · {len(project.surfaces)} 表面")
        self.history_label.setText(f"历史位置：{self._history_index} / {len(self._history)}")
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(self._history_index < len(self._history))
        if self._history_index:
            self.dirty_badge.setText(f"本次编辑 {self._history_index} 步")
            self.dirty_badge.set_tone("warning")
            self.dirty_badge.show()
        else:
            self.dirty_badge.hide()

    def keyPressEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                return
            if event.key() == Qt.Key.Key_F:
                self.editor.search_toggle.setChecked(True)
                self.editor.search.setFocus()
                self.editor.search.selectAll()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.workspace_state.save_geometry("window", self)
        self.workspace_state.save_geometry("surface_properties", self.property_dialog)
        self.workspace_state.save_table("lens_data", self.editor.table)
        self.workspace_state.save_tab("properties", self.editor.property_tabs)
        self.connections.disconnect_all()
        debouncer = getattr(self.editor, "_search_debouncer", None)
        if debouncer is not None:
            debouncer.cancel()
        self.property_dialog.close()
        super().closeEvent(event)
