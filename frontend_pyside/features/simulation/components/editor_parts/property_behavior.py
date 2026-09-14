from __future__ import annotations


from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.simulation.surface_registry import (
    get_surface_type,
    surface_type_names,
)


class SurfacePropertyMixin:
    @staticmethod
    def _field(label: str, control: QWidget, helper: str = "") -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel(label)
        title.setObjectName("propertyFieldLabel")
        layout.addWidget(title)
        control.setMinimumWidth(140)
        layout.addWidget(control)
        if helper:
            note = QLabel(helper)
            note.setObjectName("helperText")
            note.setWordWrap(True)
            layout.addWidget(note)
        return container

    @staticmethod
    def _scroll_page(content: QWidget) -> QScrollArea:

        scroll = QScrollArea()
        scroll.setObjectName("propertyInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    @staticmethod
    def _vertical_fields(fields: list[QWidget]) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(9)
        for field in fields:
            layout.addWidget(field)
        layout.addStretch(1)
        return SurfacePropertyMixin._scroll_page(content)

    def _build_basic_properties(self):
        self.group_id = QLineEdit()
        self.group_id.setPlaceholderText("例如 L1、G1、CB1")
        self.surface_name = QLineEdit()
        self.surface_type = QComboBox()
        self.surface_type.addItems(surface_type_names())
        self.radius = QDoubleSpinBox()
        self.radius.setRange(-1e9, 1e9)
        self.radius.setDecimals(6)
        self.radius.setSuffix(" mm")
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0, 1e9)
        self.thickness.setDecimals(6)
        self.thickness.setSuffix(" mm")
        self.aperture = QDoubleSpinBox()
        self.aperture.setRange(0.000001, 1e9)
        self.aperture.setDecimals(6)
        self.aperture.setSuffix(" mm")
        self.material = QComboBox()
        self.material.setEditable(True)
        self.material.addItems(["AIR", "N-BK7", "N-SF11", "F_SILICA", "MIRROR", "自定义"])

        fields = [
            self._field("元件组", self.group_id, "同一透镜的多个表面使用相同组号"),
            self._field("表面名称", self.surface_name),
            self._field("表面类型", self.surface_type, "切换后下方专用参数页自动变化"),
            self._field("曲率半径 R", self.radius, "正负号遵循光传播方向"),
            self._field("厚度", self.thickness, "该面到下一面的轴向距离"),
            self._field("材料 / 后介质", self.material, "空气间隔使用 AIR"),
            self._field("半口径", self.aperture, "有效通光半径"),
        ]
        return self._vertical_fields(fields)

    def _build_profile_properties(self):
        self.conic = QDoubleSpinBox()
        self.conic.setRange(-1e9, 1e9)
        self.conic.setDecimals(9)
        self.aperture_type = QComboBox()
        self.aperture_type.addItems(["圆形通光孔径", "矩形孔径", "椭圆孔径", "用户孔径"])
        self.clear_aperture = QDoubleSpinBox()
        self.clear_aperture.setRange(0.000001, 2e9)
        self.clear_aperture.setDecimals(6)
        self.clear_aperture.setSuffix(" mm")

        fields = [
            self._field("圆锥系数 k", self.conic),
            self._field("孔径类型", self.aperture_type),
            self._field("有效通光直径", self.clear_aperture),
        ]
        return self._vertical_fields(fields)

    def _build_engineering_properties(self):
        self.coating = QComboBox()
        self.coating.setEditable(True)
        self.coating.addItems(["无", "增透膜", "高反膜", "金属膜", "自定义镀膜"])
        self.roughness = QDoubleSpinBox()
        self.roughness.setRange(0, 1e9)
        self.roughness.setDecimals(6)
        self.roughness.setSuffix(" nm RMS")
        self.mechanical = QDoubleSpinBox()
        self.mechanical.setRange(0.0001, 1e9)
        self.mechanical.setDecimals(6)
        self.mechanical.setSuffix(" mm")
        self.enabled = QCheckBox("参与追迹和正式计算")
        self.enabled.setChecked(True)
        self.note = QLineEdit()
        self.note.setPlaceholderText("元件型号、装配位置或制造备注")

        fields = [
            self._field("镀膜", self.coating),
            self._field("表面粗糙度", self.roughness),
            self._field("机械直径", self.mechanical),
            self._field("启用状态", self.enabled),
            self._field("备注", self.note),
        ]
        return self._vertical_fields(fields)

    def _clear_dynamic_layout(self):
        while self.dynamic_layout.count():
            item = self.dynamic_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._dynamic_controls.clear()
        self._dynamic_specs.clear()

    def _create_parameter_control(self, parameter):
        if parameter.kind == "float":
            control = QDoubleSpinBox()
            control.setRange(float(parameter.minimum), float(parameter.maximum))
            control.setDecimals(parameter.decimals)
            if parameter.unit:
                control.setSuffix(f" {parameter.unit}")
            control.setValue(float(parameter.default))
        elif parameter.kind == "int":
            control = QSpinBox()
            control.setRange(int(parameter.minimum), int(parameter.maximum))
            control.setValue(int(parameter.default))
        elif parameter.kind == "choice":
            control = QComboBox()
            control.addItems(list(parameter.choices))
            control.setCurrentText(str(parameter.default))
        elif parameter.kind == "bool":
            control = QCheckBox("启用")
            control.setChecked(bool(parameter.default))
        else:
            control = QLineEdit(str(parameter.default or ""))
        return control

    def _set_control_value(self, control, parameter, value):
        if parameter.kind == "float":
            control.setValue(float(value))
        elif parameter.kind == "int":
            control.setValue(int(value))
        elif parameter.kind == "choice":
            target = control.findText(str(value))
            control.setCurrentIndex(target if target >= 0 else 0)
        elif parameter.kind == "bool":
            control.setChecked(bool(value))
        else:
            control.setText(str(value or ""))

    def _control_value(self, control, parameter):
        if parameter.kind == "float":
            return float(control.value())
        if parameter.kind == "int":
            return int(control.value())
        if parameter.kind == "choice":
            return control.currentText()
        if parameter.kind == "bool":
            return bool(control.isChecked())
        return control.text().strip()

    def _rebuild_dynamic_editor(self, type_name: str, surface=None):
        self._clear_dynamic_layout()
        spec = get_surface_type(type_name)
        description = QLabel(spec.description)
        description.setObjectName("helperText")
        description.setWordWrap(True)
        self.dynamic_layout.addWidget(description, 0, 0)
        if not spec.parameters:
            empty = QLabel("该表面类型没有额外专用参数；使用公共参数与面形参数即可。")
            empty.setObjectName("emptyStateText")
            empty.setWordWrap(True)
            self.dynamic_layout.addWidget(empty, 1, 0)
        else:
            values = getattr(surface, "type_parameters", {}) if surface is not None else {}
            for index, parameter in enumerate(spec.parameters):
                control = self._create_parameter_control(parameter)
                self._set_control_value(control, parameter, values.get(parameter.key, parameter.default))
                self._dynamic_controls[parameter.key] = control
                self._dynamic_specs[parameter.key] = parameter
                signal = getattr(control, "editingFinished", None)
                if signal is not None:
                    signal.connect(self._auto_apply_properties)
                else:
                    signal = getattr(control, "currentIndexChanged", None)
                    if signal is None:
                        signal = getattr(control, "toggled", None)
                    if signal is not None:
                        signal.connect(self._auto_apply_properties)
                self.dynamic_layout.addWidget(
                    self._field(parameter.label, control, parameter.helper), index + 1, 0
                )
                self.dynamic_layout.setColumnStretch(0, 1)
        self.property_tabs.setTabText(self.dynamic_tab_index, f"{spec.name}参数")
        self._set_common_field_state(type_name)

    def _set_common_field_state(self, type_name: str):
        spec = get_surface_type(type_name)
        mapping = {
            "radius": self.radius,
            "material": self.material,
            "aperture": self.aperture,
        }
        for key, control in mapping.items():
            disabled = key in spec.disabled_common_fields
            control.setEnabled(not disabled)
            control.setToolTip("该表面类型不使用此公共参数" if disabled else "")

    def _surface_type_changed(self, type_name: str):
        row = self.table.currentRow()
        surface = self.context.project.surfaces[row] if 0 <= row < len(self.context.project.surfaces) else None
        self._rebuild_dynamic_editor(type_name, surface if surface and surface.surface_type == type_name else None)

    def _rebuild_summary(self):
        project = self.context.project
        self.stats_badge.setText(f"{len(project.surfaces)} 面")
