"""Material library and in-lens material inspector for the workbench."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


from shared_presentation import materials as _material_presentation

globals().update({name: value for name, value in vars(_material_presentation).items() if not name.startswith("__")})


class MaterialDetailDialog(QDialog):
    def __init__(self, record: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self.setWindowTitle(f"{record.get('name', '材料')} · 详细参数")
        self.resize(420, 420)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        pairs = material_detail_pairs(record)
        for label, value in pairs:
            field = QLabel(value)
            field.setWordWrap(True)
            form.addRow(label, field)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close is not None:
            close.clicked.connect(self.accept)
        root.addWidget(buttons)


class CustomMaterialDialog(QDialog):
    def __init__(self, record: dict[str, Any] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self.setWindowTitle("自定义材料")
        self.resize(420, 460)
        record = dict(record or {})
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self.name = QLineEdit(str(record.get("name") or ""))
        self.model = QComboBox()
        self.model.addItem("常数折射率", "constant")
        self.model.addItem("Cauchy", "cauchy")
        self.model.addItem("Sellmeier", "sellmeier")
        current = str(record.get("model") or "constant")
        index = self.model.findData(current)
        self.model.setCurrentIndex(max(0, index))
        self.n = QDoubleSpinBox()
        self.n.setDecimals(6)
        self.n.setRange(1.0, 8.0)
        self.n.setValue(float(record.get("n", 1.5) or 1.5))
        self.k = QDoubleSpinBox()
        self.k.setDecimals(6)
        self.k.setRange(0.0, 20.0)
        self.k.setValue(float(record.get("k", 0.0) or 0.0))
        self.a = QDoubleSpinBox()
        self.a.setDecimals(8)
        self.a.setRange(0.0, 20.0)
        self.a.setValue(float(record.get("a", 1.5) or 1.5))
        self.b_um2 = QDoubleSpinBox()
        self.b_um2.setDecimals(8)
        self.b_um2.setRange(-1e6, 1e6)
        self.b_um2.setValue(float(record.get("b_um2", 0.0) or 0.0))
        self.c_um4 = QDoubleSpinBox()
        self.c_um4.setDecimals(8)
        self.c_um4.setRange(-1e6, 1e6)
        self.c_um4.setValue(float(record.get("c_um4", 0.0) or 0.0))
        self.sellmeier: dict[str, QDoubleSpinBox] = {}
        form.addRow("材料名", self.name)
        form.addRow("模型", self.model)
        self.pages = QStackedWidget()
        constant = QWidget()
        constant_form = QFormLayout(constant)
        constant_form.addRow("折射率 n", self.n)
        constant_form.addRow("消光系数 k", self.k)
        cauchy = QWidget()
        cauchy_form = QFormLayout(cauchy)
        cauchy_form.addRow("A", self.a)
        cauchy_form.addRow("B / μm²", self.b_um2)
        cauchy_form.addRow("C / μm⁴", self.c_um4)
        sellmeier = QWidget()
        sellmeier_form = QFormLayout(sellmeier)
        for index in (1, 2, 3):
            b = QDoubleSpinBox()
            b.setDecimals(8)
            b.setRange(-1e6, 1e6)
            b.setValue(float(record.get(f"b{index}", 0.0) or 0.0))
            c = QDoubleSpinBox()
            c.setDecimals(8)
            c.setRange(-1e6, 1e6)
            c.setValue(float(record.get(f"c{index}_um2", 0.0) or 0.0))
            self.sellmeier[f"b{index}"] = b
            self.sellmeier[f"c{index}_um2"] = c
            sellmeier_form.addRow(f"B{index}", b)
            sellmeier_form.addRow(f"C{index} / μm²", c)
        self.pages.addWidget(constant)
        self.pages.addWidget(cauchy)
        self.pages.addWidget(sellmeier)
        form.addRow(self.pages)
        root.addLayout(form)
        self.model.currentIndexChanged.connect(self._show_model)
        self._show_model()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _show_model(self) -> None:
        key = str(self.model.currentData() or "constant")
        self.pages.setCurrentIndex({"constant": 0, "cauchy": 1, "sellmeier": 2}.get(key, 0))

    def payload(self) -> dict[str, Any] | None:
        name = self.name.text().strip()
        if not name or is_air_material(name):
            return None
        model = str(self.model.currentData() or "constant")
        data: dict[str, Any] = {"name": name, "model": model, "custom": True}
        if model == "cauchy":
            data.update({"a": float(self.a.value()), "b_um2": float(self.b_um2.value()), "c_um4": float(self.c_um4.value())})
        elif model == "sellmeier":
            for key, widget in self.sellmeier.items():
                data[key] = float(widget.value())
        else:
            data.update({"n": float(self.n.value()), "k": float(self.k.value())})
        return data


def more_column_width(table: QTableWidget) -> int:
    metrics = table.fontMetrics()
    text = metrics.horizontalAdvance("更多")
    scroll = max(table.verticalScrollBar().sizeHint().width(), 18)
    return int(text + 36 + scroll)


def _fill_material_table(
    table: QTableWidget,
    records: list[dict[str, Any]],
    on_more: Callable[[dict[str, Any]], None],
) -> None:
    table.setRowCount(0)
    for record in records:
        row = table.rowCount()
        table.insertRow(row)
        name = QTableWidgetItem(str(record.get("name") or "—"))
        name.setData(Qt.ItemDataRole.UserRole, dict(record))
        table.setItem(row, 0, name)
        table.setItem(row, 1, QTableWidgetItem(_format_index(record.get("n"))))
        table.setItem(row, 2, QTableWidgetItem(_wavelength_text(record)))
        more = QPushButton("更多")
        more.setAutoDefault(False)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.clicked.connect(lambda _checked=False, value=dict(record): on_more(value))
        table.setCellWidget(row, 3, more)
        name.setToolTip(str(record.get("name") or ""))
    table.setColumnWidth(3, more_column_width(table))


class UsedMaterialInspector(QFrame):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("ObjectInspector")
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 4)
        root.setSpacing(4)
        self.names = QListWidget()
        self.names.setObjectName("ObjectList")
        self.names.setMinimumHeight(72)
        self.names.itemDoubleClicked.connect(self._open_item)
        root.addWidget(self.names)
        self.refresh()

    def refresh(self) -> None:
        try:
            from shiboken6 import isValid
            if not isValid(self.table):
                return
        except Exception:
            pass
        project = self.context.project.project
        records = used_lens_materials(project, float(project.wavelength_nm))
        self.names.clear()
        for record in records:
            item = QListWidgetItem(str(record.get("name") or "—"))
            item.setData(Qt.ItemDataRole.UserRole, dict(record))
            item.setToolTip(str(record.get("name") or ""))
            self.names.addItem(item)

    def _open_item(self, item: QListWidgetItem) -> None:
        record = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(record, dict):
            dialog = MaterialDetailDialog(record, self)
            dialog.exec()


class MaterialLibraryDocument(QWidget):
    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.kind = "material_library"
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选材料…")
        self.search.setClearButtonEnabled(True)
        custom = QPushButton("自定义材料")
        custom.setProperty("kind", "primary")
        custom.setCursor(Qt.CursorShape.PointingHandCursor)
        custom.setMinimumHeight(34)
        custom.clicked.connect(self._new_custom)
        tools.addWidget(self.search, 1)
        tools.addWidget(custom)
        root.addLayout(tools)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["材料名", "折射率", "波长", "更多"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, more_column_width(self.table))
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        root.addWidget(self.table, 1)
        self.search.textChanged.connect(self._filter)
        self.table.cellDoubleClicked.connect(lambda row, _column: self._more_at(row))
        context.project.project_changed.connect(lambda _project: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        project = self.context.project.project
        self._records = all_material_records(project, float(project.wavelength_nm))
        _fill_material_table(self.table, self._records, self._open_record)
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        query = str(text or "").strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            label = item.text().lower() if item is not None else ""
            self.table.setRowHidden(row, bool(query) and query not in label)

    def _more_at(self, row: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(record, dict):
            self._open_record(record)

    def _open_record(self, record: dict[str, Any]) -> None:
        if record.get("custom"):
            self._edit_custom(record)
            return
        dialog = MaterialDetailDialog(record, self)
        dialog.exec()

    def _new_custom(self) -> None:
        self._edit_custom({})

    def _edit_custom(self, record: dict[str, Any]) -> None:
        dialog = CustomMaterialDialog(record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.payload()
        if payload is None:
            return
        self.context.project.upsert_custom_material(payload)


__all__ = [
    "CustomMaterialDialog",
    "MaterialLibraryDocument",
    "UsedMaterialInspector",
    "all_material_records",
    "display_material_name",
    "is_air_material",
    "more_column_width",
    "used_lens_materials",
]
