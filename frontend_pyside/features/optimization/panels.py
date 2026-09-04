from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.unit_spinbox import UnitAwareDoubleSpinBox
from frontend_pyside.features.simulation.surface_registry import (
    ensure_surface_defaults,
    get_surface_type,
)
from frontend_pyside.features.optimization.variable_actions import OptimizationVariableActions
from frontend_pyside.shared.components.basic import (
    Card,
    CollapsiblePanel,
    PrimaryButton,
    SecondaryButton,
)
from frontend_pyside.shared.components.tables import DataTable


class OptimizationVariableSelector(QWidget):


    changed = Signal()

    def __init__(self, project_context, parent=None):
        super().__init__(parent)
        self.project_context = project_context
        self._row_metadata: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        table_card = Card("优化变量", compact=True)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索元件、表面或参数")
        self.object_filter = QComboBox()
        self.object_filter.addItem("全部对象", "")
        self.parameter_filter = QComboBox()
        self.parameter_filter.addItems(["全部参数", "光源", "曲率半径", "厚度/间隔", "半口径", "光纤与装调", "其他参数"])
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(self.object_filter)
        filter_row.addWidget(self.parameter_filter)
        table_card.body.addLayout(filter_row)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.select_curvature_button = SecondaryButton("选择全部曲率")
        self.select_thickness_button = SecondaryButton("选择全部厚度")
        self.enabled_only_button = SecondaryButton("只看已启用")
        self.batch_bounds_button = SecondaryButton("批量范围")
        for button in (
            self.select_curvature_button,
            self.select_thickness_button,
            self.enabled_only_button,
            self.batch_bounds_button,
        ):
            tools.addWidget(button)
        tools.addStretch(1)
        table_card.body.addLayout(tools)

        self.table = DataTable(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["启用", "参数", "所属对象", "当前值", "下限", "上限", "单位"]
        )
        self.table.content_columns(0, 3, 4, 5, 6)
        self.table.stretch_columns(1, 2)
        # This is a dedicated professional editor, so parameter/object names must
        # remain readable at the default dialog size instead of collapsing into
        # ``非球… / L1…`` ellipses.
        self.table.setColumnWidth(0, 68)
        self.table.setColumnWidth(3, 112)
        self.table.setColumnWidth(4, 112)
        self.table.setColumnWidth(5, 112)
        self.table.setColumnWidth(6, 78)
        self.table.setMinimumHeight(320)
        table_card.body.addWidget(self.table, 1)
        root.addWidget(table_card, 1)

        self.detail = CollapsiblePanel("当前变量范围", expanded=False)
        form = QFormLayout()
        form.setVerticalSpacing(6)
        self.current = QLabel("选择表格中的变量后设置范围")
        self.current.setWordWrap(True)
        self.current_value = QLabel("—")
        self.lower = UnitAwareDoubleSpinBox()
        self.lower.setRange(-1e12, 1e12)
        self.lower.setDecimals(9)
        self.upper = UnitAwareDoubleSpinBox()
        self.upper.setRange(-1e12, 1e12)
        self.upper.setDecimals(9)
        self.step = UnitAwareDoubleSpinBox()
        self.step.setRange(1e-12, 1e12)
        self.step.setDecimals(9)
        self.scale = QComboBox()
        self.scale.addItems(["线性", "对数", "相对百分比"])
        form.addRow("当前变量", self.current)
        form.addRow("当前值", self.current_value)
        form.addRow("下限", self.lower)
        form.addRow("上限", self.upper)
        form.addRow("初始步长", self.step)
        form.addRow("缩放方式", self.scale)
        apply_button = PrimaryButton("保存变量设置")
        form.addRow(apply_button)
        self.detail.content_layout.addLayout(form)
        root.addWidget(self.detail)

        self.actions = OptimizationVariableActions(self.table, self)
        self.actions.changed.connect(self.changed)
        self.actions.filterChanged.connect(
            lambda enabled: self.enabled_only_button.setText(
                "显示全部" if enabled else "只看已启用"
            )
        )
        self.select_curvature_button.clicked.connect(
            lambda: self.actions.enable_matching("曲率")
        )
        self.select_thickness_button.clicked.connect(
            lambda: self.actions.enable_matching("厚度/间隔")
        )
        self.enabled_only_button.clicked.connect(self.actions.toggle_enabled_only)
        self.batch_bounds_button.clicked.connect(
            lambda: self.actions.request_batch_bounds(self)
        )
        self.table.currentCellChanged.connect(self._selected)
        self.table.itemChanged.connect(self.actions.handle_item_changed)
        apply_button.clicked.connect(self._apply)
        self.search.textChanged.connect(self._apply_local_filters)
        self.object_filter.currentIndexChanged.connect(self._apply_local_filters)
        self.parameter_filter.currentTextChanged.connect(self._apply_local_filters)
        self.project_context.project_changed.connect(lambda _: self.reload())
        self.reload()

    @staticmethod
    def _bounds(value: float, *, floor: float | None = None) -> tuple[float, float]:
        if value == 0:
            low, high = -1.0, 1.0
        else:
            low, high = sorted((value * 0.7, value * 1.3))
        if floor is not None:
            low = max(floor, low)
            high = max(low + max(abs(value) * 0.01, 1e-6), high)
        return low, high

    def reload(self):
        project = self.project_context.project
        rows: list[tuple[list[object], dict]] = []
        group_ids: list[str] = ["光源", "光纤与装调"]

        def add_global_row(
            parameter: str,
            object_name: str,
            value: float,
            low: float,
            high: float,
            unit: str,
            path: str,
            category: str,
            *, enabled: bool = False,
        ) -> None:
            rows.append((
                ["☑" if enabled else "☐", parameter, object_name, value, low, high, unit],
                {
                    "group_id": object_name,
                    "surface_name": object_name,
                    "surface_index": -1,
                    "path": path,
                    "label": parameter,
                    "unit": unit,
                    "category": category,
                },
            ))

        wavelength = float(getattr(project, "wavelength_nm", 1550.0))
        wave_half = max(10.0, wavelength * 0.03)
        add_global_row(
            "波长", "光源", wavelength, wavelength - wave_half, wavelength + wave_half,
            "nm", "source.wavelength_nm", "光源",
        )
        mfd = float(getattr(project, "receiver_mfd_um", 10.4))
        mfd_low, mfd_high = self._bounds(mfd, floor=0.1)
        add_global_row(
            "光纤模场直径", "光纤与装调", mfd, mfd_low, mfd_high,
            "μm", "receiver.mode_field_diameter_x_um", "光纤与装调",
        )
        for parameter, path, unit, low, high in (
            ("光纤轴向位置", "receiver.axial_offset_z_mm", "mm", -0.5, 0.5),
            ("光纤 X 偏移", "receiver.offset_x_mm", "mm", -0.05, 0.05),
            ("光纤 Y 偏移", "receiver.offset_y_mm", "mm", -0.05, 0.05),
            ("光纤 X 倾角", "receiver.tilt_x_deg", "deg", -0.5, 0.5),
            ("光纤 Y 倾角", "receiver.tilt_y_deg", "deg", -0.5, 0.5),
        ):
            add_global_row(parameter, "光纤与装调", 0.0, low, high, unit, path, "光纤与装调")

        for index, surface in enumerate(project.surfaces):
            ensure_surface_defaults(surface, fallback_group=f"L{index // 2 + 1}")
            group_id = str(surface.group_id or f"L{index // 2 + 1}")
            if group_id not in group_ids:
                group_ids.append(group_id)
            spec = get_surface_type(surface.surface_type)
            common = {
                "group_id": group_id,
                "surface_name": surface.name,
                "surface_index": index,
                "material": str(surface.material),
            }
            if "radius" not in spec.disabled_common_fields:
                low, high = self._bounds(surface.radius_mm)
                rows.append((
                    ["☑", "曲率半径", surface.name, surface.radius_mm, low, high, "mm"],
                    {
                        **common,
                        "path": f"surfaces[{index}].radius_mm",
                        "label": f"{surface.name} / 曲率半径",
                        "unit": "mm",
                        "category": "曲率半径",
                    },
                ))
            low, high = self._bounds(surface.thickness_mm, floor=0.0)
            rows.append((
                ["☐", "厚度/间隔", surface.name, surface.thickness_mm, low, high, "mm"],
                {
                    **common,
                    "path": f"surfaces[{index}].distance_to_next_mm",
                    "label": f"{surface.name} / 厚度/间隔",
                    "unit": "mm",
                    "category": "厚度/间隔",
                },
            ))
            if "aperture" not in spec.disabled_common_fields:
                low, high = self._bounds(surface.semi_aperture_mm, floor=1e-6)
                rows.append((
                    ["☐", "半口径", surface.name, surface.semi_aperture_mm, low, high, "mm"],
                    {
                        **common,
                        "path": f"surfaces[{index}].semi_aperture_mm",
                        "label": f"{surface.name} / 半口径",
                        "unit": "mm",
                        "category": "半口径",
                    },
                ))
            for parameter in spec.parameters:
                if parameter.kind not in {"float", "int"}:
                    continue
                value = float(surface.type_parameters.get(parameter.key, parameter.default))
                low, high = self._bounds(value)
                low = max(float(parameter.minimum), low)
                high = min(float(parameter.maximum), high)
                if high <= low:
                    high = min(float(parameter.maximum), low + 1.0)
                rows.append((
                    ["☐", parameter.label, surface.name, value, low, high, parameter.unit or "—"],
                    {
                        **common,
                        "path": f"surfaces[{index}].{parameter.key}",
                        "label": f"{surface.name} / {parameter.label}",
                        "unit": parameter.unit or "",
                        "category": "其他参数",
                    },
                ))

        blocked = self.object_filter.blockSignals(True)
        self.object_filter.clear()
        self.object_filter.addItem("全部对象", "")
        for group_id in group_ids:
            self.object_filter.addItem(group_id, group_id)
        self.object_filter.blockSignals(blocked)

        self._row_metadata = [metadata for _, metadata in rows]
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row_index, (row_values, metadata) in enumerate(rows):
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(str(value))
                if column_index == 0:
                    item.setText("")
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if str(value) in {"☑", "✓", "1", "true", "True"}
                        else Qt.CheckState.Unchecked
                    )
                if column_index == 1:
                    item.setData(Qt.ItemDataRole.UserRole, metadata)
                self.table.setItem(row_index, column_index, item)
        self.table.blockSignals(False)
        if rows:
            self.table.setCurrentCell(0, 0)
        self.actions.refresh_filter()
        self._apply_local_filters()

    def _apply_local_filters(self, *_):
        search = self.search.text().strip().lower()
        group_id = str(self.object_filter.currentData() or "")
        category = self.parameter_filter.currentText()
        for row in range(self.table.rowCount()):
            metadata = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole) or {}
            haystack = " ".join(
                [
                    str(metadata.get("group_id", "")),
                    str(metadata.get("surface_name", "")),
                    str(metadata.get("label", "")),
                    str(self.table.item(row, 1).text() if self.table.item(row, 1) else ""),
                ]
            ).lower()
            visible = True
            if search and search not in haystack:
                visible = False
            if group_id and str(metadata.get("group_id", "")) != group_id:
                visible = False
            if category != "全部参数" and str(metadata.get("category", "")) != category:
                visible = False
            self.table.setRowHidden(row, not visible)

    def get_variables(self) -> list[dict]:

        variables: list[dict] = []
        for row in range(self.table.rowCount()):
            enabled_item = self.table.item(row, 0)
            parameter_item = self.table.item(row, 1)
            if enabled_item is None or parameter_item is None:
                continue
            if enabled_item.checkState() != Qt.CheckState.Checked:
                continue
            metadata = parameter_item.data(Qt.ItemDataRole.UserRole) or {}
            try:
                variables.append(
                    {
                        "path": str(metadata.get("path", "")),
                        "label": str(metadata.get("label", parameter_item.text())),
                        "unit": str(metadata.get("unit", self.table.item(row, 6).text())),
                        "lower_bound": float(self.table.item(row, 4).text()),
                        "upper_bound": float(self.table.item(row, 5).text()),
                        "initial_value": float(self.table.item(row, 3).text()),
                        "enabled": True,
                    }
                )
            except (AttributeError, TypeError, ValueError):
                continue
        return [item for item in variables if item["path"]]

    def get_parameter_snapshot(self) -> list[dict]:
        """Freeze every selectable numeric parameter at task submission time."""
        snapshot: list[dict] = []
        for row in range(self.table.rowCount()):
            enabled_item = self.table.item(row, 0)
            parameter_item = self.table.item(row, 1)
            value_item = self.table.item(row, 3)
            unit_item = self.table.item(row, 6)
            if enabled_item is None or parameter_item is None or value_item is None:
                continue
            metadata = parameter_item.data(Qt.ItemDataRole.UserRole) or {}
            path = str(metadata.get("path", "")).strip()
            if not path:
                continue
            try:
                value = float(value_item.text())
            except (TypeError, ValueError):
                continue
            snapshot.append({
                "path": path,
                "label": str(metadata.get("label", parameter_item.text())),
                "unit": str(metadata.get("unit", unit_item.text() if unit_item else "")),
                "value": value,
                "optimized": enabled_item.checkState() == Qt.CheckState.Checked,
            })
        return snapshot

    def _selected(self, row, *_):
        if row < 0 or self.table.item(row, 2) is None:
            return
        self.detail.set_expanded(True)
        self.current.setText(
            f"{self.table.item(row, 2).text()} / {self.table.item(row, 1).text()}"
        )
        self.current_value.setText(
            f"{self.table.item(row, 3).text()} {self.table.item(row, 6).text()}"
        )
        unit = self.table.item(row, 6).text() if self.table.item(row, 6) is not None else ""
        for spin in (self.lower, self.upper, self.step):
            spin.setTargetUnit(unit)
        self.lower.setValue(float(self.table.item(row, 4).text()))
        self.upper.setValue(float(self.table.item(row, 5).text()))
        self.step.setValue(max(abs(self.upper.value() - self.lower.value()) / 50, 1e-9))

    def _apply(self):
        row = self.table.currentRow()
        if row < 0:
            return
        low, high = sorted((self.lower.value(), self.upper.value()))
        self.table.item(row, 4).setText(str(low))
        self.table.item(row, 5).setText(str(high))
        self.changed.emit()
