"""Material library and in-lens material inspector for the workbench."""

from __future__ import annotations

from math import sqrt
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

from optical_core.materials.catalog import default_material_database
from optical_core.materials.dispersion import wavelength_nm_to_um

_AIR_NAMES = {"", "AIR", "VACUUM", "NONE", "真空"}
_CATALOG_CACHE: dict[int, tuple[dict[str, Any], ...]] = {}


def is_air_material(name: str) -> bool:
    return str(name or "").strip().upper() in _AIR_NAMES


def display_material_name(name: str) -> str:
    text = str(name or "").strip()
    if text.startswith("glass_"):
        return text[len("glass_") :]
    return text or "—"


def _format_index(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):.6g}"


def _custom_index(record: dict[str, Any], wavelength_nm: float) -> float | None:
    model = str(record.get("model") or "constant")
    try:
        if model == "cauchy":
            wavelength_um = float(wavelength_nm) / 1000.0
            a = float(record.get("a", 1.5) or 1.5)
            b = float(record.get("b_um2", 0.0) or 0.0)
            c = float(record.get("c_um4", 0.0) or 0.0)
            return a + b / (wavelength_um ** 2) + c / (wavelength_um ** 4)
        if model == "sellmeier":
            lam2 = (float(wavelength_nm) / 1000.0) ** 2
            n2 = 1.0
            for index in (1, 2, 3):
                b = float(record.get(f"b{index}", 0.0) or 0.0)
                c = float(record.get(f"c{index}_um2", 0.0) or 0.0)
                n2 += b * lam2 / (lam2 - c) if abs(lam2 - c) > 1e-15 else 0.0
            return sqrt(max(n2, 0.0))
        return float(record.get("n", 1.5) or 1.5)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _catalog_entry(name: str, wavelength_nm: float) -> dict[str, Any] | None:
    database = default_material_database()
    try:
        canonical = database.normalize_material_name(name)
        entry = database.select_entry(
            canonical,
            wavelength_um=wavelength_nm_to_um(wavelength_nm),
            require_n=True,
        )
        index = database.get_n(canonical, wavelength_nm=wavelength_nm, source=entry.source)
        raw = dict(entry.raw or {})
        return {
            "name": display_material_name(canonical),
            "canonical": canonical,
            "n": float(index),
            "wavelength_nm": float(wavelength_nm),
            "custom": False,
            "source": entry.source,
            "type": entry.type,
            "wl_min_um": entry.wl_min,
            "wl_max_um": entry.wl_max,
            "coeffs": list(raw.get("coeffs") or []),
            "comments": entry.comments or "",
        }
    except Exception:
        return None


def _builtin_catalog(wavelength_nm: float) -> tuple[dict[str, Any], ...]:
    key = int(round(float(wavelength_nm) * 10.0))
    cached = _CATALOG_CACHE.get(key)
    if cached is not None:
        return cached
    database = default_material_database()
    rows: list[dict[str, Any]] = [
        {
            "name": "AIR",
            "canonical": "AIR",
            "n": 1.0,
            "wavelength_nm": float(wavelength_nm),
            "custom": False,
            "source": "constant",
            "type": "constant",
            "wl_min_um": 0.2,
            "wl_max_um": 20.0,
            "coeffs": [],
            "comments": "n = 1",
        },
        {
            "name": "MIRROR",
            "canonical": "MIRROR",
            "n": None,
            "wavelength_nm": float(wavelength_nm),
            "custom": False,
            "source": "ideal",
            "type": "mirror",
            "wl_min_um": None,
            "wl_max_um": None,
            "coeffs": [],
            "comments": "理想反射",
        },
    ]
    seen = {"air", "mirror"}
    for canonical in database.list_materials():
        record = _catalog_entry(canonical, wavelength_nm)
        if record is None:
            continue
        marker = str(record["name"]).strip().lower()
        if marker in seen:
            continue
        seen.add(marker)
        rows.append(record)
    rows.sort(key=lambda item: str(item.get("name") or "").lower())
    packed = tuple(rows)
    _CATALOG_CACHE[key] = packed
    return packed


def custom_material_records(project, wavelength_nm: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in list(getattr(project, "custom_materials", ()) or ()):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                **dict(item),
                "name": name,
                "canonical": name,
                "n": _custom_index(item, wavelength_nm),
                "wavelength_nm": float(wavelength_nm),
                "custom": True,
            }
        )
    return rows


def all_material_records(project, wavelength_nm: float) -> list[dict[str, Any]]:
    custom = custom_material_records(project, wavelength_nm)
    custom_names = {str(item["name"]).strip().lower() for item in custom}
    catalog = [
        dict(item)
        for item in _builtin_catalog(wavelength_nm)
        if str(item.get("name") or "").strip().lower() not in custom_names
    ]
    return custom + catalog


def used_lens_materials(project, wavelength_nm: float) -> list[dict[str, Any]]:
    used: list[str] = []
    for surface in list(getattr(project, "surfaces", ()) or ()):
        name = str(getattr(surface, "material", "") or "").strip()
        if not name or is_air_material(name) or name in used:
            continue
        used.append(name)
    custom = {
        str(item.get("name") or "").strip().lower(): item
        for item in custom_material_records(project, wavelength_nm)
    }
    rows: list[dict[str, Any]] = []
    for name in used:
        record = custom.get(name.lower()) or _catalog_entry(name, wavelength_nm)
        if record is None:
            record = {
                "name": name,
                "canonical": name,
                "n": None,
                "wavelength_nm": float(wavelength_nm),
                "custom": False,
                "comments": "当前波长下没有折射率数据",
            }
        rows.append(record)
    return rows


def _wavelength_text(record: dict[str, Any]) -> str:
    value = record.get("wavelength_nm")
    try:
        return f"{float(value):g} nm"
    except (TypeError, ValueError):
        return "—"


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
        pairs = [
            ("材料名", str(record.get("name") or "—")),
            ("折射率", _format_index(record.get("n"))),
            ("波长", _wavelength_text(record)),
            ("来源", str(record.get("source") or ("自定义" if record.get("custom") else "—"))),
            ("模型", str(record.get("type") or record.get("model") or "—")),
        ]
        wl_min = record.get("wl_min_um")
        wl_max = record.get("wl_max_um")
        if wl_min is not None or wl_max is not None:
            low = f"{float(wl_min):g}" if isinstance(wl_min, (int, float)) else "—"
            high = f"{float(wl_max):g}" if isinstance(wl_max, (int, float)) else "—"
            pairs.append(("有效波段", f"{low}–{high} μm"))
        if record.get("custom"):
            model = str(record.get("model") or "constant")
            if model == "constant":
                pairs.append(("消光系数 k", f"{float(record.get('k', 0.0) or 0.0):g}"))
            elif model == "cauchy":
                pairs.extend(
                    (
                        ("A", f"{float(record.get('a', 0.0) or 0.0):g}"),
                        ("B / μm²", f"{float(record.get('b_um2', 0.0) or 0.0):g}"),
                        ("C / μm⁴", f"{float(record.get('c_um4', 0.0) or 0.0):g}"),
                    )
                )
            elif model == "sellmeier":
                for index in (1, 2, 3):
                    pairs.append((f"B{index}", f"{float(record.get(f'b{index}', 0.0) or 0.0):g}"))
                    pairs.append((f"C{index} / μm²", f"{float(record.get(f'c{index}_um2', 0.0) or 0.0):g}"))
        coeffs = record.get("coeffs") or []
        if coeffs:
            pairs.append(("色散系数", ", ".join(f"{float(value):.6g}" for value in coeffs[:8])))
        comment = str(record.get("comments") or "").strip()
        if comment:
            pairs.append(("说明", comment))
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
