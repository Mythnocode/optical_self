from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import Card, InfoRow, SecondaryButton
from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_BEAM_QUALITY_M2,
    DEFAULT_CALCULATION_PRECISION_TEXT,
    DEFAULT_HIGH_PRECISION_COUPLING,
    DEFAULT_IMAGE_DISTANCE_MM,
    DEFAULT_OBJECT_DISTANCE_MM,
    DEFAULT_ONLY_VISIBLE_RESULTS,
    DEFAULT_OUTPUT_EXTENT_MM,
    DEFAULT_OUTPUT_GRID_SIZE,
    DEFAULT_PROPAGATION_TEXT,
    DEFAULT_PUPIL_RADIUS_MM,
    DEFAULT_RECEIVER_CORE_DIAMETER_UM,
    DEFAULT_RECEIVER_ENDFACE_TRANSMISSION,
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_RECEIVER_NA,
    DEFAULT_RECEIVER_N_CLAD,
    DEFAULT_RECEIVER_N_CORE,
    DEFAULT_SOURCE_NA,
    DEFAULT_SOURCE_POWER_MW,
    DEFAULT_WAIST_POSITION_MM,
    DEFAULT_WAIST_RADIUS_UM,
    DEFAULT_WAVELENGTH_NM,
)
from frontend_pyside.features.simulation.imported_field import ImportedFieldSelector


class ParameterPageBuilderMixin:
    def _source_page(self):
        page, _, grid = self._page_shell([])

        primary = Card("光源", compact=True)
        form = self._compact_form()
        self.source_type = QComboBox()
        self.source_type.addItems(["高斯模式", "均匀光瞳", "点光源"])
        self.source_axis_button = SecondaryButton("分轴设置")
        self.source_axis_button.setCheckable(True)
        self.source_axis_button.toggled.connect(self._sync_source_axis_mode)
        self.source_waist_x = self._spin(DEFAULT_WAIST_RADIUS_UM, 0.1, 10000, "μm")
        self.source_waist_y = self._spin(DEFAULT_WAIST_RADIUS_UM, 0.1, 10000, "μm")
        self.source_waist_position = self._spin(DEFAULT_WAIST_POSITION_MM, -10000, 10000, "mm")
        self.source_m2_x = self._spin(DEFAULT_BEAM_QUALITY_M2, 1.0, 100, decimals=3)
        self.source_m2_y = self._spin(DEFAULT_BEAM_QUALITY_M2, 1.0, 100, decimals=3)
        self.source_na_x = self._spin(DEFAULT_SOURCE_NA, 0, 1, decimals=5)
        self.source_na_y = self._spin(DEFAULT_SOURCE_NA, 0, 1, decimals=5)
        self.source_field_x = self._spin(0, -90, 90, "°")
        self.source_field_y = self._spin(0, -90, 90, "°")
        self.system_field_x = self.source_field_x
        self.system_field_y = self.source_field_y
        for label, widget in [
            ("光源模式", self.source_type),
            ("对称方式", self.source_axis_button),
            ("束腰半径", self.source_waist_x),
            ("Y方向束腰", self.source_waist_y),
            ("束腰位置", self.source_waist_position),
            ("M²", self.source_m2_x),
            ("M²-Y", self.source_m2_y),
            ("数值孔径", self.source_na_x),
            ("NA-Y", self.source_na_y),
            ("视场角", self.source_field_x),
            ("视场角Y", self.source_field_y),
        ]:
            form.addRow(label, widget)
        self.source_form = form
        primary.body.addLayout(form)
        grid.addWidget(primary, 0, 0)

        spectrum = Card("波长与功率", compact=True)
        spectrum_form = self._compact_form()
        self.system_wavelength = self._spin(DEFAULT_WAVELENGTH_NM, 100, 30000, "nm")
        self.system_auxiliary_wavelengths = QLineEdit("")
        self.system_auxiliary_wavelengths.setPlaceholderText("1064, 1310, 1590")
        self.system_temperature = self._spin(20, -273, 1000, "℃")
        self.system_pressure = self._spin(101.325, 0, 10000, "kPa")
        self.system_thermal = QCheckBox("温度补偿")
        self.source_power = self._spin(DEFAULT_SOURCE_POWER_MW, 0, 1e9, "mW")
        self.source_power_unit = QComboBox()
        self.source_power_unit.addItems(["mW", "W", "μW"])
        for label, widget in [
            ("主波长", self.system_wavelength),
            ("辅助波长", self.system_auxiliary_wavelengths),
            ("总功率", self.source_power),
            ("功率单位", self.source_power_unit),
            ("环境温度", self.system_temperature),
            ("环境压力", self.system_pressure),
            ("材料补偿", self.system_thermal),
        ]:
            spectrum_form.addRow(label, widget)
        spectrum.body.addLayout(spectrum_form)
        grid.addWidget(spectrum, 0, 1)

        geometry = Card("系统几何", compact=True)
        form2 = self._compact_form()
        self.system_object_distance = self._spin(DEFAULT_OBJECT_DISTANCE_MM, 0.1, 1e9, "mm")
        self.system_pupil_radius = self._spin(DEFAULT_PUPIL_RADIUS_MM, 0.01, 10000, "mm")
        self.system_image_distance = self._spin(DEFAULT_IMAGE_DISTANCE_MM, -10000, 10000, "mm")
        self.system_auto_focus = QCheckBox("最佳焦面搜索")
        for label, widget in [
            ("物距", self.system_object_distance),
            ("入瞳半径", self.system_pupil_radius),
            ("像面位置", self.system_image_distance),
            ("焦面策略", self.system_auto_focus),
        ]:
            form2.addRow(label, widget)
        geometry.body.addLayout(form2)
        grid.addWidget(geometry, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.source_type.currentIndexChanged.connect(self._update_source_mode_fields)
        self.source_waist_x.valueChanged.connect(self._sync_source_common_values)
        self.source_m2_x.valueChanged.connect(self._sync_source_common_values)
        self.source_na_x.valueChanged.connect(self._sync_source_common_values)
        self.source_field_x.valueChanged.connect(self._sync_source_common_values)
        self._sync_source_axis_mode(False)
        self._update_source_mode_fields()
        return page

    def _set_form_row_visible(self, form: QFormLayout, widget, visible: bool) -> None:
        try:
            form.setRowVisible(widget, bool(visible))
        except AttributeError:
            widget.setVisible(bool(visible))
            label = form.labelForField(widget)
            if label is not None:
                label.setVisible(bool(visible))

    def _sync_source_common_values(self, *_args) -> None:
        if not hasattr(self, "source_axis_button") or self.source_axis_button.isChecked():
            return
        for source, target in (
            (self.source_waist_x, self.source_waist_y),
            (self.source_m2_x, self.source_m2_y),
            (self.source_na_x, self.source_na_y),
            (self.source_field_x, self.source_field_y),
        ):
            blocked = target.blockSignals(True)
            target.setValue(source.value())
            target.blockSignals(blocked)

    def _sync_source_axis_mode(self, split: bool) -> None:
        if not hasattr(self, "source_form"):
            return
        split = bool(split)
        self.source_axis_button.setText("圆对称" if split else "分轴设置")
        for widget in (self.source_waist_y, self.source_m2_y, self.source_na_y, self.source_field_y):
            self._set_form_row_visible(self.source_form, widget, split)
        labels = {
            self.source_waist_x: "X方向束腰" if split else "束腰半径",
            self.source_m2_x: "M²-X" if split else "M²",
            self.source_na_x: "NA-X" if split else "数值孔径",
            self.source_field_x: "视场角X" if split else "视场角",
        }
        for widget, text in labels.items():
            label = self.source_form.labelForField(widget)
            if label is not None:
                label.setText(text)
        if not split:
            self._sync_source_common_values()

    def _update_source_mode_fields(self, *_args) -> None:
        if not hasattr(self, "source_form"):
            return
        mode = self.source_type.currentText()
        gaussian = mode == "高斯模式"
        for widget in (self.source_axis_button, self.source_waist_x, self.source_waist_y, self.source_waist_position, self.source_m2_x, self.source_m2_y):
            self._set_form_row_visible(self.source_form, widget, gaussian)
        for widget in (self.source_na_x, self.source_na_y, self.source_field_x, self.source_field_y):
            self._set_form_row_visible(self.source_form, widget, True)
        if gaussian:
            self._sync_source_axis_mode(self.source_axis_button.isChecked())

    def _current_output_grid_size(self) -> int | None:
        combo = getattr(self, "calc_grid", None)
        if combo is None:
            return 257
        try:
            return int(str(combo.currentText()).split("×", 1)[0].strip())
        except (TypeError, ValueError):
            return 257

    def _revalidate_imported_receiver_field(self, *_args) -> None:
        selector = getattr(self, "receiver_field_selector", None)
        if selector is None or selector.data is None:
            return
        selector.load_path(selector.data.path, show_error=False)

    def _receiver_page(self):
        page, _, grid = self._page_shell([])
        fiber = Card("光纤模式", compact=True)
        form = self._compact_form()
        self.receiver_type = QComboBox()
        self.receiver_type.addItems(["单模光纤", "多模光纤", "用户模式"])
        self.receiver_mode_model = QComboBox()
        self.receiver_mode_model.addItems(["高斯近似", "LP01", "HE11", "导入复场"])
        self.receiver_axis_button = SecondaryButton("分轴设置")
        self.receiver_axis_button.setCheckable(True)
        self.receiver_axis_button.toggled.connect(self._sync_receiver_axis_mode)
        self.receiver_mfd_x = self._spin(DEFAULT_RECEIVER_MFD_UM, 0.1, 1000, "μm")
        self.receiver_mfd_y = self._spin(DEFAULT_RECEIVER_MFD_UM, 0.1, 1000, "μm")
        self.receiver_core_diameter = self._spin(DEFAULT_RECEIVER_CORE_DIAMETER_UM, 0.1, 1000, "μm")
        self.receiver_na_x = self._spin(DEFAULT_RECEIVER_NA, 0.001, 1, decimals=5)
        self.receiver_na_y = self._spin(DEFAULT_RECEIVER_NA, 0.001, 1, decimals=5)
        self.receiver_n_core = self._spin(DEFAULT_RECEIVER_N_CORE, 1, 5, decimals=6)
        self.receiver_n_clad = self._spin(DEFAULT_RECEIVER_N_CLAD, 1, 5, decimals=6)
        self.receiver_field_selector = ImportedFieldSelector(self._current_output_grid_size)
        self.receiver_field_selector.fieldChanged.connect(self.changed.emit)
        
        self.receiver_field_file = self.receiver_field_selector.path_edit
        for label, widget in [
            ("光纤类型", self.receiver_type),
            ("模式", self.receiver_mode_model),
            ("对称方式", self.receiver_axis_button),
            ("模场直径", self.receiver_mfd_x),
            ("MFD-Y", self.receiver_mfd_y),
            ("数值孔径", self.receiver_na_x),
            ("NA-Y", self.receiver_na_y),
            ("芯径", self.receiver_core_diameter),
            ("纤芯折射率", self.receiver_n_core),
            ("包层折射率", self.receiver_n_clad),
            ("复场文件", self.receiver_field_selector),
        ]:
            form.addRow(label, widget)
        self.receiver_form = form
        fiber.body.addLayout(form)
        grid.addWidget(fiber, 0, 0)

        alignment = Card("位置与损耗", compact=True)
        form2 = self._compact_form()
        self.receiver_offset_x = self._spin(0, -10000, 10000, "μm")
        self.receiver_offset_y = self._spin(0, -10000, 10000, "μm")
        self.receiver_offset_z = self._spin(0, -10000, 10000, "μm")
        self.receiver_tilt_x = self._spin(0, -1e6, 1e6, "μrad")
        self.receiver_tilt_y = self._spin(0, -1e6, 1e6, "μrad")
        self.receiver_outside_index = self._spin(1.0, 0.1, 5, decimals=6)
        self.receiver_endface = self._spin(DEFAULT_RECEIVER_ENDFACE_TRANSMISSION, 0, 1, decimals=5)
        self.receiver_length = self._spin(0.0, 0, 1e6, "m")
        self.receiver_attenuation = self._spin(0.0, 0, 1e6, "dB/km")
        self.receiver_connector_loss = self._spin(0.0, 0, 1e6, "dB")
        for label, widget in [
            ("X方向偏移", self.receiver_offset_x),
            ("Y方向偏移", self.receiver_offset_y),
            ("轴向偏移", self.receiver_offset_z),
            ("X方向倾角", self.receiver_tilt_x),
            ("Y方向倾角", self.receiver_tilt_y),
            ("外部折射率", self.receiver_outside_index),
            ("端面透射率", self.receiver_endface),
            ("光纤长度", self.receiver_length),
            ("衰减", self.receiver_attenuation),
            ("连接器损耗", self.receiver_connector_loss),
        ]:
            form2.addRow(label, widget)
        alignment.body.addLayout(form2)
        grid.addWidget(alignment, 1, 0)
        grid.setColumnStretch(0, 1)
        self.receiver_mode_model.currentIndexChanged.connect(self._update_receiver_mode_fields)
        self.receiver_mfd_x.valueChanged.connect(self._sync_receiver_common_values)
        self.receiver_na_x.valueChanged.connect(self._sync_receiver_common_values)
        self._sync_receiver_axis_mode(False)
        self._update_receiver_mode_fields()
        return page

    def _sync_receiver_common_values(self, *_args) -> None:
        if not hasattr(self, "receiver_axis_button") or self.receiver_axis_button.isChecked():
            return
        for source, target in ((self.receiver_mfd_x, self.receiver_mfd_y), (self.receiver_na_x, self.receiver_na_y)):
            blocked = target.blockSignals(True)
            target.setValue(source.value())
            target.blockSignals(blocked)

    def _sync_receiver_axis_mode(self, split: bool) -> None:
        if not hasattr(self, "receiver_form"):
            return
        split = bool(split)
        self.receiver_axis_button.setText("圆对称" if split else "分轴设置")
        for widget in (self.receiver_mfd_y, self.receiver_na_y):
            self._set_form_row_visible(self.receiver_form, widget, split)
        labels = {
            self.receiver_mfd_x: "MFD-X" if split else "模场直径",
            self.receiver_na_x: "NA-X" if split else "数值孔径",
        }
        for widget, text in labels.items():
            label = self.receiver_form.labelForField(widget)
            if label is not None:
                label.setText(text)
        if not split:
            self._sync_receiver_common_values()

    def _update_receiver_mode_fields(self, *_args) -> None:
        if not hasattr(self, "receiver_form"):
            return
        mode = self.receiver_mode_model.currentText()
        gaussian = mode == "高斯近似"
        imported = mode == "导入复场"
        for widget in (self.receiver_axis_button, self.receiver_mfd_x, self.receiver_mfd_y, self.receiver_na_x, self.receiver_na_y):
            self._set_form_row_visible(self.receiver_form, widget, gaussian)
        for widget in (self.receiver_core_diameter, self.receiver_n_core, self.receiver_n_clad):
            self._set_form_row_visible(self.receiver_form, widget, mode in {"LP01", "HE11"})
        self._set_form_row_visible(self.receiver_form, self.receiver_field_selector, imported)
        if imported and self.receiver_type.currentText() != "用户模式":
            self.receiver_type.setCurrentText("用户模式")
        if gaussian:
            self._sync_receiver_axis_mode(self.receiver_axis_button.isChecked())

    def _calculation_page(self):
        page, _, grid = self._page_shell([])
        display = Card("光路与截面显示", compact=True)
        self.result_controls_host = QWidget()
        self.result_controls_host_layout = QVBoxLayout(self.result_controls_host)
        self.result_controls_host_layout.setContentsMargins(0, 0, 0, 0)
        self.result_controls_host_layout.setSpacing(5)
        display.body.addWidget(self.result_controls_host)
        grid.addWidget(display, 0, 0)

        sampling = Card("采样与传播", compact=True)
        form = self._compact_form()
        self.calc_precision = QComboBox()
        self.calc_precision.addItems(["预览", "标准", "高精度", "研究级"])
        self.calc_precision.setCurrentText(DEFAULT_CALCULATION_PRECISION_TEXT)
        self.calc_grid = QComboBox()
        self.calc_grid.addItems(["65 × 65", "129 × 129", "257 × 257", "513 × 513", "1025 × 1025"])
        self.calc_grid.setCurrentText(f"{DEFAULT_OUTPUT_GRID_SIZE} × {DEFAULT_OUTPUT_GRID_SIZE}")
        self.calc_grid.currentTextChanged.connect(self._revalidate_imported_receiver_field)
        self.calc_layout_pupil = QComboBox()
        self.calc_layout_pupil.addItems(["7 × 7", "9 × 9", "13 × 13", "17 × 17"])
        self.calc_layout_pupil.setCurrentText("9 × 9")
        self.calc_layout_pupil.setToolTip("仅用于正式二维/三维布局光路，不影响波动或耦合精度")
        self.calc_pupil = QComboBox()
        self.calc_pupil.addItems(["17 × 17", "33 × 33", "49 × 49", "65 × 65"])
        self.calc_pupil.setCurrentText("49 × 49")
        self.calc_pupil.setToolTip("用于点列、复场和耦合等定量分析")
        self.calc_propagation = QComboBox()
        self.calc_propagation.addItems(["普通角谱", "带限角谱", "缩放角谱", "缩放 Fresnel", "ISSC", "Fresnel"])
        self.calc_propagation.setCurrentText(DEFAULT_PROPAGATION_TEXT)
        self.calc_padding = self._spin(2, 1, 16, "×", decimals=0)
        self.calc_extent = self._spin(DEFAULT_OUTPUT_EXTENT_MM, 0.001, 1000, "mm")
        for label, widget in [
            ("精度预设", self.calc_precision),
            ("接收面网格", self.calc_grid),
            ("光路布局采样", self.calc_layout_pupil),
            ("分析光瞳采样", self.calc_pupil),
            ("传播方法", self.calc_propagation),
            ("零填充倍率", self.calc_padding),
            ("输出窗口", self.calc_extent),
        ]:
            form.addRow(label, widget)
        sampling.body.addLayout(form)
        grid.addWidget(sampling, 1, 0)

        outputs = Card("正式分析与输出", compact=True)
        form2 = self._compact_form()
        analyses = [
            ("raytrace", "几何光路与三维光线", True),
            ("spot", "点列图", False),
            ("focus_search", "最佳焦面", False),
            ("psf", "PSF", False),
            ("mtf", "MTF", False),
            ("coupling", "光纤模场耦合", True),
            ("power_audit", "能量闭合审计", False),
        ]
        for name, label, checked in analyses:
            box = QCheckBox(label)
            box.setChecked(checked)
            self.analysis_boxes[name] = box
            form2.addRow(box)
        self.output_boxes["only_visible_results"] = QCheckBox("仅计算当前可见结果")
        self.output_boxes["only_visible_results"].setChecked(DEFAULT_ONLY_VISIBLE_RESULTS)
        self.output_boxes["only_visible_results"].setToolTip(
            "严格只运行右侧当前可见视图；取消勾选后才执行全部已选分析"
        )
        self.output_boxes["sampling_convergence"] = QCheckBox("采样收敛测试")
        self.output_boxes["save_large_arrays"] = QCheckBox("保存完整大型数组")
        self.calc_high_precision_coupling = QCheckBox("采用高精度耦合效率计算")
        self.calc_high_precision_coupling.setChecked(DEFAULT_HIGH_PRECISION_COUPLING)
        self.calc_high_precision_coupling.setToolTip(
            "关闭时顶部效率使用即时 Gaussian 估计；开启后正式计算会请求高精度复场耦合。"
        )
        form2.addRow(self.calc_high_precision_coupling)
        form2.addRow(self.output_boxes["only_visible_results"])
        form2.addRow(self.output_boxes["sampling_convergence"])
        form2.addRow(self.output_boxes["save_large_arrays"])
        outputs.body.addLayout(form2)
        grid.addWidget(outputs, 2, 0)
        grid.setColumnStretch(0, 1)
        return page
