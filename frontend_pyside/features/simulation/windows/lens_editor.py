from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.components import OpticalSystemEditor
from frontend_pyside.shared.components.basic import Badge, Card, PrimaryButton, SecondaryButton
from frontend_pyside.shared.lifecycle import SignalConnectionBag
from frontend_pyside.shared.settings import WorkspaceStateStore


@dataclass
class _HistoryEntry:
    description: str
    before: object
    after: object


class LensEditorWindow(QMainWindow):


    def __init__(self, project_context, parent=None) -> None:
        super().__init__(parent)
        self.project_context = project_context
        self.workspace_state = WorkspaceStateStore("lens_editor")
        self.connections = SignalConnectionBag()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("完整镜头编辑器")
        self.resize(1540, 900)
        self.setMinimumSize(1080, 680)

        self._history: list[_HistoryEntry] = []
        self._history_checkpoint_count = 0
        self._history_limit = 200
        self._history_index = 0
        self._saved_history_index = 0
        self._restoring = False
        self._syncing_tree = False
        self._last_snapshot = copy.deepcopy(project_context.project)
        self._baseline = copy.deepcopy(project_context.project)
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
        self.dirty_badge = Badge("无未保存修改", "success")
        tools.addWidget(self.dirty_badge)
        tools.addStretch(1)

        self.undo_button = SecondaryButton("撤销 Ctrl+Z")
        self.redo_button = SecondaryButton("重做 Ctrl+Y")
        self.history_button = SecondaryButton("操作历史")
        self.reverse_button = SecondaryButton("反转所选镜片")
        self.baseline_button = SecondaryButton("设为对比基准")
        self.save_button = PrimaryButton("设为保存点")
        for button in (
            self.undo_button,
            self.redo_button,
            self.history_button,
            self.reverse_button,
            self.baseline_button,
            self.save_button,
        ):
            tools.addWidget(button)
        root.addWidget(toolbar)

        self.editor = OpticalSystemEditor(project_context)
        
        
        self.editor.detail_card.setVisible(False)
        self.editor.detail_content.setParent(None)
        self.editor.detail_content.setVisible(True)
        self.editor.detail_toggle.setChecked(True)
        self.editor.apply_button.setVisible(False)
        self.editor.reset_button.setVisible(False)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter = self.main_splitter
        main_splitter.setObjectName("lensEditorMainSplitter")
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(7)

        tree_card = Card("元件树", compact=True)
        tree_card.setMinimumWidth(190)
        tree_card.setMaximumWidth(300)
        self.tree = QTreeWidget()
        self.tree.setObjectName("lensElementTree")
        self.tree.setHeaderLabels(["镜片与表面"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        tree_card.body.addWidget(self.tree, 1)
        main_splitter.addWidget(tree_card)

        self.editor.setMinimumWidth(610)
        main_splitter.addWidget(self.editor)

        property_card = Card("属性检查器", compact=True)
        property_card.setMinimumWidth(380)
        property_card.setMaximumWidth(560)
        property_card.body.addWidget(self.editor.detail_content, 1)
        main_splitter.addWidget(property_card)

        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        self.workspace_state.restore_splitter("main", main_splitter, [220, 860, 460])
        root.addWidget(main_splitter, 1)

        footer = QFrame()
        footer.setObjectName("lensWindowFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(9, 5, 9, 5)
        self.history_label = QLabel("历史位置：0 / 0")
        self.history_label.setObjectName("helperText")
        footer_layout.addWidget(self.history_label)
        self.baseline_label = QLabel("对比基准：打开编辑器时")
        self.baseline_label.setObjectName("helperText")
        footer_layout.addWidget(self.baseline_label)
        footer_layout.addStretch(1)
        self.status_label = QLabel("修改会立即更新当前项目；每次提交自动记录，可使用 Ctrl+Z / Ctrl+Y。")
        self.status_label.setObjectName("helperText")
        footer_layout.addWidget(self.status_label)
        root.addWidget(footer)

        self.setCentralWidget(central)
        self.editor.changed.connect(self._record_external_change)
        self.editor.surfaceSelected.connect(self._select_tree_row)
        if hasattr(self.editor, "operationCommitted"):
            self.editor.operationCommitted.connect(self._set_pending_description)
        self.tree.currentItemChanged.connect(self._tree_selection_changed)
        self.connections.connect(self.project_context.project_changed, self._project_changed)

        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.reverse_button.clicked.connect(self.reverse_selected_group)
        self.baseline_button.clicked.connect(self.set_baseline)
        self.history_button.clicked.connect(self.show_history)
        self.save_button.clicked.connect(self.save_version)

        self.workspace_state.restore_geometry("window", self)
        self.workspace_state.restore_table("lens_data", self.editor.table)
        self.workspace_state.restore_tab("properties", self.editor.property_tabs, 0)
        self._rebuild_tree()
        self._refresh_status()

    def _project_changed(self, _project) -> None:
        if not self._restoring:
            self._rebuild_tree()

    def _row_for_surface_id(self, surface_id: str) -> int:
        wanted = str(surface_id or "")
        for row, surface in enumerate(self.project_context.project.surfaces):
            if str(getattr(surface, "surface_id", "")) == wanted:
                return row
        return -1

    def _current_surface_id(self) -> str:
        row = self.editor.table.currentRow()
        surfaces = self.project_context.project.surfaces
        if 0 <= row < len(surfaces):
            return str(getattr(surfaces[row], "surface_id", ""))
        return ""

    def _rebuild_tree(self) -> None:
        current_surface_id = self._current_surface_id()
        self._syncing_tree = True
        try:
            self.tree.clear()
            group_items: dict[str, QTreeWidgetItem] = {}
            for row, surface in enumerate(self.project_context.project.surfaces):
                group_id = str(getattr(surface, "group_id", "") or f"S{row + 1}")
                group_item = group_items.get(group_id)
                if group_item is None:
                    direction = str(getattr(surface, "type_parameters", {}).get("_element_orientation", "forward"))
                    suffix = "  ← 已反转" if direction == "reversed" else "  →"
                    group_item = QTreeWidgetItem([f"{group_id}{suffix}"])
                    group_item.setData(0, Qt.ItemDataRole.UserRole, {"element_id": str(getattr(surface, "element_id", "")), "surface_id": str(getattr(surface, "surface_id", ""))})
                    self.tree.addTopLevelItem(group_item)
                    group_items[group_id] = group_item
                child = QTreeWidgetItem([f"S{row + 1}  {surface.name}"])
                child.setData(0, Qt.ItemDataRole.UserRole, {"element_id": str(getattr(surface, "element_id", "")), "surface_id": str(getattr(surface, "surface_id", ""))})
                child.setToolTip(0, f"{surface.surface_type}｜R={surface.radius_mm:.6g} mm｜{surface.material}")
                group_item.addChild(child)
            self.tree.collapseAll()
        finally:
            self._syncing_tree = False
        current_row = self._row_for_surface_id(current_surface_id)
        if current_row < 0 and self.project_context.project.surfaces:
            current_row = 0
        if current_row >= 0:
            self._select_tree_row(current_row)

    def _tree_selection_changed(self, current, _previous) -> None:
        if self._syncing_tree or current is None:
            return
        identity = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(identity, dict):
            row = self._row_for_surface_id(identity.get("surface_id", ""))
            if row >= 0:
                surface = self.project_context.project.surfaces[row]
                self.project_context.select(
                    element_id=str(getattr(surface, "element_id", "")),
                    surface_id=str(getattr(surface, "surface_id", "")),
                )
                self.editor.select_surface(row, open_properties=False)

    def _select_tree_row(self, row: int) -> None:
        if self._syncing_tree:
            return
        surfaces = self.project_context.project.surfaces
        if not 0 <= int(row) < len(surfaces):
            return
        surface = surfaces[int(row)]
        surface_id = str(getattr(surface, "surface_id", ""))
        element_id = str(getattr(surface, "element_id", ""))
        self.project_context.select(element_id=element_id, surface_id=surface_id)
        self._syncing_tree = True
        try:
            root = self.tree.invisibleRootItem()
            self.tree.collapseAll()
            for i in range(root.childCount()):
                group = root.child(i)
                group_identity = group.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(group_identity, dict) and group_identity.get("element_id") == element_id:
                    group.setExpanded(True)
                for j in range(group.childCount()):
                    child = group.child(j)
                    identity = child.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(identity, dict) and identity.get("surface_id") == surface_id:
                        group.setExpanded(True)
                        self.tree.setCurrentItem(child)
                        self.tree.scrollToItem(child)
                        return
        finally:
            self._syncing_tree = False

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
            if self._saved_history_index > self._history_index:
                self._saved_history_index = self._history_index
        self._history.append(
            _HistoryEntry(self._pending_description, self._last_snapshot, current)
        )
        if len(self._history) > self._history_limit:
            overflow = len(self._history) - self._history_limit
            del self._history[:overflow]
            self._history_checkpoint_count += overflow
            self._saved_history_index = max(0, self._saved_history_index - overflow)
        self._history_index = len(self._history)
        self._last_snapshot = copy.deepcopy(current)
        self._pending_description = "修改镜头参数"
        self._rebuild_tree()
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
            self._rebuild_tree()
        finally:
            self._restoring = False

    def set_baseline(self) -> None:
        self._baseline = copy.deepcopy(self.project_context.project)
        self.baseline_label.setText(f"对比基准：{self._baseline.version} / 当前镜头状态")
        self.status_label.setText("已将当前镜头状态设为对比基准。")

    def save_version(self) -> None:

        self._saved_history_index = self._history_index
        self.status_label.setText(
            "已将当前镜头状态设为保存点；项目文件仍由项目保存流程持久化。"
        )
        self._refresh_status()

    def show_history(self) -> None:
        if not self._history:
            QMessageBox.information(self, "操作历史", "当前尚无可显示的镜头修改记录。")
            return
        lines = []
        if self._history_checkpoint_count:
            lines.append(f"更早的 {self._history_checkpoint_count} 步已归档为检查点。")
        for index, entry in enumerate(self._history, 1):
            markers = []
            if index == self._history_index:
                markers.append("当前")
            if index == self._saved_history_index:
                markers.append("保存点")
            marker = f" ← {' / '.join(markers)}" if markers else ""
            lines.append(f"{index:02d}. {entry.description}{marker}")
        QMessageBox.information(self, "操作历史", "\n".join(lines))

    def reverse_selected_group(self) -> None:
        row = self.editor.table.currentRow()
        surfaces = self.project_context.project.surfaces
        if not 0 <= row < len(surfaces):
            QMessageBox.information(self, "反转镜片", "请先在镜头数据表中选择一个完整镜片。")
            return
        selected_surface = surfaces[row]
        group_id = getattr(selected_surface, "group_id", "")
        element_id = str(getattr(selected_surface, "element_id", ""))
        indexes = [i for i, surface in enumerate(surfaces) if str(getattr(surface, "element_id", "")) == element_id]
        if len(indexes) < 2 or indexes != list(range(min(indexes), max(indexes) + 1)):
            QMessageBox.warning(self, "不能反转", "所选元件必须由两个以上连续表面组成。")
            return
        supported = {"球面", "平面"}
        unsupported = [surfaces[i].surface_type for i in indexes if surfaces[i].surface_type not in supported]
        if unsupported:
            QMessageBox.warning(
                self,
                "不能自动反转",
                "当前镜片包含尚未支持安全自动反转的表面类型：" + "、".join(sorted(set(unsupported))),
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
        self._pending_description = f"反转镜片 {group_id}（{old_orientation} → {new_orientation}）"
        surfaces[start : start + count] = reversed_surfaces
        self.project_context.touch_version()
        self.editor.reload()
        self.editor.table.setCurrentCell(start, self.editor.COL_NAME)
        self.editor.changed.emit()
        self.status_label.setText(f"{group_id} 已反转；可使用 Ctrl+Z 一步撤销。")

    def _refresh_status(self) -> None:
        project = self.project_context.project
        self.project_label.setText(f"{project.name} · {project.version} · {len(project.surfaces)} 个表面")
        self.history_label.setText(f"历史位置：{self._history_index} / {len(self._history)}")
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(self._history_index < len(self._history))
        pending = abs(self._history_index - self._saved_history_index)
        changed = self._history_index != self._saved_history_index
        self.dirty_badge.setText(f"保存点后修改：{pending} 项" if changed else "当前状态已标记")
        self.dirty_badge.set_tone("warning" if changed else "success")

    def keyPressEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._history_index != self._saved_history_index:
            answer = QMessageBox.question(
                self,
                "关闭镜头编辑器",
                "当前镜头参数已实时更新到项目，并且存在保存点之后的修改。\n\n"
                "选择“是”保留当前状态并关闭；选择“否”返回编辑器。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.workspace_state.save_geometry("window", self)
        self.workspace_state.save_splitter("main", self.main_splitter)
        self.workspace_state.save_table("lens_data", self.editor.table)
        self.workspace_state.save_tab("properties", self.editor.property_tabs)
        self.connections.disconnect_all()
        debouncer = getattr(self.editor, "_search_debouncer", None)
        if debouncer is not None:
            debouncer.cancel()
        super().closeEvent(event)
