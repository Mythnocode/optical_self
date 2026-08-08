
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
)


class RaySectionControls(QWidget):


    optionsChanged = Signal(dict)

    _PLANE_VALUES = {
        "YZ 截面": "yz",
        "XZ 截面": "xz",
        "自定义截面": "custom",
    }
    _SCALE_VALUES = {
        "布局视图": "layout",
        "物理比例": "physical",
        "镜组细节": "group_detail",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(8)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.scale_mode = QComboBox()
        self.scale_mode.setObjectName("rayDisplayScaleCombo")
        self.scale_mode.addItems(self._SCALE_VALUES)
        layout.addRow("轴向显示", self.scale_mode)

        self.plane = QComboBox()
        self.plane.setObjectName("raySectionPlaneCombo")
        self.plane.addItems(self._PLANE_VALUES)
        layout.addRow("截面", self.plane)

        self.position = QDoubleSpinBox()
        self.position.setObjectName("raySectionPosition")
        self.position.setRange(-10000.0, 10000.0)
        self.position.setDecimals(3)
        self.position.setSingleStep(0.05)
        self.position.setSuffix(" mm")
        layout.addRow("位置", self.position)

        self.half_thickness = QDoubleSpinBox()
        self.half_thickness.setObjectName("raySectionThickness")
        self.half_thickness.setRange(0.001, 1000.0)
        self.half_thickness.setDecimals(3)
        self.half_thickness.setSingleStep(0.01)
        self.half_thickness.setValue(0.05)
        self.half_thickness.setSuffix(" mm")
        layout.addRow("半厚度", self.half_thickness)

        self.azimuth_label = QLabel("方位角")
        self.azimuth = QDoubleSpinBox()
        self.azimuth.setObjectName("raySectionAzimuth")
        self.azimuth.setRange(-180.0, 180.0)
        self.azimuth.setDecimals(1)
        self.azimuth.setSingleStep(5.0)
        self.azimuth.setValue(45.0)
        self.azimuth.setSuffix("°")
        layout.addRow(self.azimuth_label, self.azimuth)

        self.section_count = QSpinBox()
        self.section_count.setRange(5, 120)
        self.section_count.setValue(21)
        layout.addRow("2D光线", self.section_count)

        self.three_d_count = QSpinBox()
        self.three_d_count.setRange(5, 80)
        self.three_d_count.setValue(15)
        layout.addRow("3D光线", self.three_d_count)

        self.scale_mode.currentTextChanged.connect(self._emit_options)
        self.plane.currentTextChanged.connect(self._plane_changed)
        self.position.valueChanged.connect(self._emit_options)
        self.half_thickness.valueChanged.connect(self._emit_options)
        self.azimuth.valueChanged.connect(self._emit_options)
        self.section_count.valueChanged.connect(self._emit_options)
        self.three_d_count.valueChanged.connect(self._emit_options)
        self._plane_changed(self.plane.currentText())

    def options(self) -> dict:
        return {
            "plane": self._PLANE_VALUES.get(self.plane.currentText(), "yz"),
            "position_mm": float(self.position.value()),
            "half_thickness_mm": float(self.half_thickness.value()),
            "custom_azimuth_deg": float(self.azimuth.value()),
            "max_section_rays": int(self.section_count.value()),
            "max_3d_rays": int(self.three_d_count.value()),
            "scale_mode": self._SCALE_VALUES.get(self.scale_mode.currentText(), "layout"),
        }

    def set_options(self, options: dict | None, *, emit: bool = False) -> None:
        options = dict(options or {})
        plane_value = str(options.get("plane", "yz"))
        plane_text = next(
            (label for label, value in self._PLANE_VALUES.items() if value == plane_value),
            "YZ 截面",
        )
        scale_value = str(options.get("scale_mode", "layout"))
        scale_text = next(
            (label for label, value in self._SCALE_VALUES.items() if value == scale_value),
            "布局视图",
        )
        controls = (
            self.scale_mode,
            self.plane,
            self.position,
            self.half_thickness,
            self.azimuth,
            self.section_count,
            self.three_d_count,
        )
        previous = [control.blockSignals(True) for control in controls]
        try:
            self.scale_mode.setCurrentText(scale_text)
            self.plane.setCurrentText(plane_text)
            self.position.setValue(float(options.get("position_mm", 0.0) or 0.0))
            self.half_thickness.setValue(float(options.get("half_thickness_mm", 0.05) or 0.05))
            self.azimuth.setValue(float(options.get("custom_azimuth_deg", 45.0) or 45.0))
            self.section_count.setValue(int(options.get("max_section_rays", 21) or 21))
            self.three_d_count.setValue(int(options.get("max_3d_rays", 15) or 15))
        finally:
            for control, was_blocked in zip(controls, previous):
                control.blockSignals(was_blocked)
        self._update_azimuth_visibility()
        if emit:
            self._emit_options()

    def set_selected_surface(self, index: int | None, group_id: str = "") -> None:
        self.setProperty("selectedSurfaceIndex", index)
        self.setProperty("selectedGroupId", group_id)

    def _plane_changed(self, _text: str) -> None:
        self._update_azimuth_visibility()
        self._emit_options()

    def _update_azimuth_visibility(self) -> None:
        visible = self._PLANE_VALUES.get(self.plane.currentText()) == "custom"
        self.azimuth_label.setVisible(visible)
        self.azimuth.setVisible(visible)

    def _emit_options(self, *_args) -> None:
        options = self.options()
        selected = self.property("selectedSurfaceIndex")
        group_id = self.property("selectedGroupId")
        if selected is not None:
            options["selected_surface_index"] = int(selected)
        if group_id:
            options["selected_group_id"] = str(group_id)
        self.optionsChanged.emit(options)


__all__ = ["RaySectionControls"]
