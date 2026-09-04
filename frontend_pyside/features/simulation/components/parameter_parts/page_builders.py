from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.shared.components.basic import Card, CollapsiblePanel, InfoRow, SecondaryButton
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
from frontend_pyside.shared.settings import SimulationNumericsProfileStore


class ParameterPageBuilderMixin:
    def _source_page(self):
        page, _, grid = self._page_shell([])

        # 常用光源参数保持在第一层；环境、视场和系统几何按需展开。
        primary = Card("光源", compact=True)
        form = self._compact_form()
        self.source_type = QComboBox()
        self.source_type.addItems(["高斯模式", "均匀光瞳", "点光源"])
        self.system_wavelength = self._spin(DEFAULT_WAVELENGTH_NM, 100, 30000, "nm")
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
            ("主波长", self.system_wavelength),
            ("束腰半径", self.source_waist_x),
            ("Y方向束腰", self.source_waist_y),
            ("束腰位置", self.source_waist_position),
            ("M²", self.source_m2_x),
            ("M²-Y", self.source_m2_y),
            ("对称方式", self.source_axis_button),
        ]:
            form.addRow(label, widget)
        self.source_form = form
        primary.body.addLayout(form)
        grid.addWidget(primary, 0, 0)

        # 这些字段保留完整控制能力，但不再占用日常操作的首屏空间。
        more = CollapsiblePanel("更多设置", expanded=False)
        more_form = self._compact_form()
        self.system_auxiliary_wavelengths = QLineEdit("")
        self.system_auxiliary_wavelengths.setPlaceholderText("1064, 1310, 1590")
        self.system_temperature = self._spin(20, -273, 1000, "℃")
        self.system_pressure = self._spin(101.325, 0, 10000, "kPa")
        self.system_thermal = QCheckBox("温度补偿")
        self.source_power = self._spin(DEFAULT_SOURCE_POWER_MW, 0, 1e9, "mW")
        self.source_power_unit = QComboBox()
        self.source_power_unit.addItems(["mW", "W", "μW"])
        self.system_object_distance = self._spin(DEFAULT_OBJECT_DISTANCE_MM, 0.1, 1e9, "mm")
        self.system_pupil_radius = self._spin(DEFAULT_PUPIL_RADIUS_MM, 0.01, 10000, "mm")
        self.system_image_distance = self._spin(DEFAULT_IMAGE_DISTANCE_MM, -10000, 10000, "mm")
        self.system_auto_focus = QCheckBox("最佳焦面搜索")
        self.system_auto_focus.setChecked(False)
        self.system_auto_focus.hide()
        for label, widget in [
            ("数值孔径", self.source_na_x),
            ("NA-Y", self.source_na_y),
            ("视场角", self.source_field_x),
            ("视场角Y", self.source_field_y),
            ("辅助波长", self.system_auxiliary_wavelengths),
            ("总功率", self.source_power),
            ("功率单位", self.source_power_unit),
            ("环境温度", self.system_temperature),
            ("环境压力", self.system_pressure),
            ("材料补偿", self.system_thermal),
            ("物距", self.system_object_distance),
            ("入瞳半径", self.system_pupil_radius),
            ("像面位置", self.system_image_distance),
        ]:
            more_form.addRow(label, widget)
        self.source_more_form = more_form
        more.content_layout.addLayout(more_form)
        grid.addWidget(more, 1, 0)
        grid.setColumnStretch(0, 1)

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
        for widget in (self.source_waist_y, self.source_m2_y):
            self._set_form_row_visible(self.source_form, widget, split)
        more_form = getattr(self, "source_more_form", None)
        if more_form is not None:
            for widget in (self.source_na_y, self.source_field_y):
                self._set_form_row_visible(more_form, widget, split)
        labels = {
            self.source_waist_x: "X方向束腰" if split else "束腰半径",
            self.source_m2_x: "M²-X" if split else "M²",
            self.source_na_x: "NA-X" if split else "数值孔径",
            self.source_field_x: "视场角X" if split else "视场角",
        }
        for widget, text in labels.items():
            target_form = self.source_form if widget in (self.source_waist_x, self.source_m2_x) else getattr(self, "source_more_form", self.source_form)
            label = target_form.labelForField(widget)
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
        # NA 与视场位于“更多设置”，只根据分轴状态控制 Y 行。
        more_form = getattr(self, "source_more_form", None)
        if more_form is not None:
            self._set_form_row_visible(more_form, self.source_na_y, self.source_axis_button.isChecked())
            self._set_form_row_visible(more_form, self.source_field_y, self.source_axis_button.isChecked())
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

        alignment = Card("位置与角度", compact=True)
        form2 = self._compact_form()
        self.receiver_offset_x = self._spin(0, -10000, 10000, "μm")
        self.receiver_offset_y = self._spin(0, -10000, 10000, "μm")
        self.receiver_offset_z = self._spin(0, -10000, 10000, "μm")
        self.receiver_tilt_x = self._spin(0, -1e6, 1e6, "μrad")
        self.receiver_tilt_y = self._spin(0, -1e6, 1e6, "μrad")
        for label, widget in [
            ("X方向偏移", self.receiver_offset_x),
            ("Y方向偏移", self.receiver_offset_y),
            ("轴向偏移", self.receiver_offset_z),
            ("X方向倾角", self.receiver_tilt_x),
            ("Y方向倾角", self.receiver_tilt_y),
        ]:
            form2.addRow(label, widget)
        alignment.body.addLayout(form2)
        grid.addWidget(alignment, 1, 0)

        losses = CollapsiblePanel("传输设置", expanded=False)
        losses_form = self._compact_form()
        self.receiver_outside_index = self._spin(1.0, 0.1, 5, decimals=6)
        self.receiver_endface = self._spin(DEFAULT_RECEIVER_ENDFACE_TRANSMISSION, 0, 1, decimals=5)
        self.receiver_length = self._spin(0.0, 0, 1e6, "m")
        self.receiver_attenuation = self._spin(0.0, 0, 1e6, "dB/km")
        self.receiver_connector_loss = self._spin(0.0, 0, 1e6, "dB")
        for label, widget in [
            ("外部折射率", self.receiver_outside_index),
            ("端面透射率", self.receiver_endface),
            ("光纤长度", self.receiver_length),
            ("衰减", self.receiver_attenuation),
            ("连接器损耗", self.receiver_connector_loss),
        ]:
            losses_form.addRow(label, widget)
        losses.content_layout.addLayout(losses_form)
        grid.addWidget(losses, 2, 0)
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
        profile_store = SimulationNumericsProfileStore()
        profile = profile_store.load()
        self._numerics_profile_store = profile_store

        sampling = Card("计算设置", compact=True)
        strategy_form = self._compact_form()
        self.calc_precision = QComboBox()
        self.calc_precision.addItems(["129×129", "257×257", "513×513", "1025×1025"])
        preferred_precision = str(profile.get("precision", DEFAULT_CALCULATION_PRECISION_TEXT))
        self.calc_precision.setCurrentText(
            preferred_precision if self.calc_precision.findText(preferred_precision) >= 0
            else DEFAULT_CALCULATION_PRECISION_TEXT
        )
        self.calc_auto_numerics = QCheckBox("自动设置采样")
        self.calc_auto_numerics.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.calc_auto_numerics.setChecked(bool(profile.get("automatic", True)))
        strategy_form.addRow("网格", self.calc_precision)
        strategy_form.addRow(self.calc_auto_numerics)
        sampling.body.addLayout(strategy_form)
        recommended = SimulationNumericsProfileStore.recommended_sampling(self.calc_precision.currentText())
        self.calc_sampling_summary = QLabel(
            f"接收面 {recommended['grid_size']}×{recommended['grid_size']} · 光瞳 {recommended['pupil_sample_count']}×{recommended['pupil_sample_count']} · {recommended['propagation']}"
        )
        self.calc_sampling_summary.setObjectName("helperText")
        def refresh_sampling_summary(*_args):
            preset = SimulationNumericsProfileStore.recommended_sampling(self.calc_precision.currentText())
            self.calc_sampling_summary.setText(
                f"接收面 {preset['grid_size']}×{preset['grid_size']} · 光瞳 {preset['pupil_sample_count']}×{preset['pupil_sample_count']} · {preset['propagation']}"
            )
        self.calc_precision.currentTextChanged.connect(refresh_sampling_summary)
        sampling.body.addWidget(self.calc_sampling_summary)
        grid.addWidget(sampling, 0, 0)

        self.calc_advanced_sampling_panel = CollapsiblePanel(
            "高级设置", expanded=not self.calc_auto_numerics.isChecked()
        )
        form = self._compact_form()
        self.calc_grid = QComboBox()
        self.calc_grid.addItems(["65 × 65", "129 × 129", "257 × 257", "513 × 513", "1025 × 1025"])
        self.calc_grid.setCurrentText(f"{int(profile.get('grid_size', DEFAULT_OUTPUT_GRID_SIZE))} × {int(profile.get('grid_size', DEFAULT_OUTPUT_GRID_SIZE))}")
        self.calc_grid.currentTextChanged.connect(self._revalidate_imported_receiver_field)
        self.calc_layout_pupil = QComboBox()
        self.calc_layout_pupil.addItems(["7 × 7", "9 × 9", "13 × 13", "17 × 17"])
        layout_count = int(profile.get("layout_pupil_sample_count", 9))
        self.calc_layout_pupil.setCurrentText(f"{layout_count} × {layout_count}")
        self.calc_pupil = QComboBox()
        self.calc_pupil.addItems(["17 × 17", "33 × 33", "49 × 49", "65 × 65"])
        pupil_count = int(profile.get("pupil_sample_count", 49))
        self.calc_pupil.setCurrentText(f"{pupil_count} × {pupil_count}")
        self.calc_propagation = QComboBox()
        self.calc_propagation.addItems(["普通角谱", "带限角谱", "缩放角谱", "缩放 Fresnel", "ISSC", "Fresnel"])
        preferred_method = str(profile.get("propagation", DEFAULT_PROPAGATION_TEXT))
        self.calc_propagation.setCurrentText(
            preferred_method if self.calc_propagation.findText(preferred_method) >= 0 else DEFAULT_PROPAGATION_TEXT
        )
        self.calc_padding = self._spin(float(profile.get("padding", 2.0)), 1, 16, "×", decimals=0)
        self.calc_extent = self._spin(float(profile.get("extent_mm", DEFAULT_OUTPUT_EXTENT_MM)), 0.001, 1000, "mm")
        self._advanced_sampling_widgets = (
            self.calc_grid, self.calc_layout_pupil, self.calc_pupil,
            self.calc_propagation, self.calc_padding, self.calc_extent,
        )
        for label, widget in [
            ("接收面网格", self.calc_grid),
            ("光路采样", self.calc_layout_pupil),
            ("分析光瞳", self.calc_pupil),
            ("传播方法", self.calc_propagation),
            ("零填充", self.calc_padding),
            ("计算窗口", self.calc_extent),
        ]:
            form.addRow(label, widget)
        self.calc_advanced_sampling_panel.content_layout.addLayout(form)

        advanced_results = CollapsiblePanel("计算内容", expanded=False)
        result_form = self._compact_form()
        primary_analyses = [
            ("raytrace", "光路 / 3D 光路", True),
            ("spot", "点列图", True),
            ("psf", "焦面光斑", True),
            ("coupling", "模场匹配与耦合效率", True),
            ("mtf", "MTF", False),
            ("power_audit", "能量检查", False),
        ]
        for name, label, checked in primary_analyses:
            box = QCheckBox(label)
            box.setChecked(checked)
            self.analysis_boxes[name] = box
            result_form.addRow(box)
        self.analysis_boxes["focus_search"] = QCheckBox("焦面搜索")
        self.analysis_boxes["focus_search"].setChecked(False)
        self.analysis_boxes["focus_search"].hide()
        self.output_boxes["only_visible_results"] = QCheckBox("只计算当前结果")
        self.output_boxes["only_visible_results"].setChecked(DEFAULT_ONLY_VISIBLE_RESULTS)
        self.output_boxes["sampling_convergence"] = QCheckBox("检查采样收敛")
        self.output_boxes["sampling_convergence"].setChecked(bool(profile.get("sampling_convergence", True)))
        self.output_boxes["save_large_arrays"] = QCheckBox("保存完整数组")
        self.calc_high_precision_coupling = QCheckBox("完整复场耦合")
        self.calc_high_precision_coupling.setChecked(DEFAULT_HIGH_PRECISION_COUPLING)
        for widget in (
            self.calc_high_precision_coupling,
            self.output_boxes["only_visible_results"],
            self.output_boxes["sampling_convergence"],
            self.output_boxes["save_large_arrays"],
        ):
            result_form.addRow(widget)
        advanced_results.content_layout.addLayout(result_form)
        self.calc_advanced_sampling_panel.content_layout.addWidget(advanced_results)
        grid.addWidget(self.calc_advanced_sampling_panel, 1, 0)

        # 兼容旧的结果控制挂载点；结果显示控件现在放在主结果区域。
        self.result_controls_host = QWidget(page)
        self.result_controls_host.hide()
        self.result_controls_host_layout = QVBoxLayout(self.result_controls_host)
        self.result_controls_host_layout.setContentsMargins(0, 0, 0, 0)

        self.calc_auto_numerics.toggled.connect(self._sync_automatic_numerics)
        self.calc_precision.currentTextChanged.connect(self._sync_automatic_numerics)
        for widget in self._advanced_sampling_widgets:
            signal = getattr(widget, "currentTextChanged", None) or getattr(widget, "valueChanged", None)
            if signal is not None:
                signal.connect(self._persist_numerics_profile)
        self.output_boxes["sampling_convergence"].toggled.connect(self._persist_numerics_profile)
        self._sync_automatic_numerics()
        grid.setColumnStretch(0, 1)
        return page

    def apply_numerics_profile(self) -> None:
        if not hasattr(self, "calc_auto_numerics"):
            return
        profile = SimulationNumericsProfileStore().load()
        widgets = [
            self.calc_auto_numerics, self.calc_precision, self.calc_grid, self.calc_pupil,
            self.calc_layout_pupil, self.calc_propagation, self.calc_padding, self.calc_extent,
            self.output_boxes.get("sampling_convergence"),
        ]
        previous = [widget.blockSignals(True) if widget is not None else False for widget in widgets]
        try:
            self.calc_auto_numerics.setChecked(bool(profile.get("automatic", True)))
            if self.calc_precision.findText(str(profile.get("precision", "257×257"))) >= 0:
                self.calc_precision.setCurrentText(str(profile.get("precision", "257×257")))
            for widget, value in (
                (self.calc_grid, int(profile.get("grid_size", 257))),
                (self.calc_pupil, int(profile.get("pupil_sample_count", 49))),
                (self.calc_layout_pupil, int(profile.get("layout_pupil_sample_count", 9))),
            ):
                text = f"{value} × {value}"
                if widget.findText(text) >= 0:
                    widget.setCurrentText(text)
            method = str(profile.get("propagation", DEFAULT_PROPAGATION_TEXT))
            if self.calc_propagation.findText(method) >= 0:
                self.calc_propagation.setCurrentText(method)
            self.calc_padding.setValue(float(profile.get("padding", 2.0)))
            self.calc_extent.setValue(float(profile.get("extent_mm", DEFAULT_OUTPUT_EXTENT_MM)))
            convergence = self.output_boxes.get("sampling_convergence")
            if convergence is not None:
                convergence.setChecked(bool(profile.get("sampling_convergence", True)))
        finally:
            for widget, blocked in zip(widgets, previous):
                if widget is not None:
                    widget.blockSignals(blocked)
        self._sync_automatic_numerics()
        try:
            self.changed.emit()
        except AttributeError:
            pass

    def _sync_automatic_numerics(self, *_):
        automatic = bool(getattr(self, "calc_auto_numerics", None) and self.calc_auto_numerics.isChecked())
        if automatic:
            recommended = SimulationNumericsProfileStore.recommended_sampling(self.calc_precision.currentText())
            mapping = (
                (self.calc_grid, f"{recommended['grid_size']} × {recommended['grid_size']}"),
                (self.calc_pupil, f"{recommended['pupil_sample_count']} × {recommended['pupil_sample_count']}"),
                (self.calc_layout_pupil, f"{recommended['layout_pupil_sample_count']} × {recommended['layout_pupil_sample_count']}"),
            )
            for widget, value in mapping:
                previous = widget.blockSignals(True)
                try:
                    if widget.findText(value) >= 0:
                        widget.setCurrentText(value)
                finally:
                    widget.blockSignals(previous)
            previous = self.calc_padding.blockSignals(True)
            try:
                self.calc_padding.setValue(float(recommended['padding']))
            finally:
                self.calc_padding.blockSignals(previous)
            previous = self.calc_propagation.blockSignals(True)
            try:
                method = str(recommended.get('propagation', '缩放 Fresnel'))
                if self.calc_propagation.findText(method) >= 0:
                    self.calc_propagation.setCurrentText(method)
            finally:
                self.calc_propagation.blockSignals(previous)
            previous = self.calc_extent.blockSignals(True)
            try:
                self.calc_extent.setValue(float(recommended.get('extent_mm', 0.024)))
            finally:
                self.calc_extent.blockSignals(previous)
        for widget in getattr(self, "_advanced_sampling_widgets", ()):
            widget.setEnabled(not automatic)
        panel = getattr(self, "calc_advanced_sampling_panel", None)
        if panel is not None and automatic:
            try:
                panel.set_expanded(False)
            except AttributeError:
                pass
        self._persist_numerics_profile()

    def _persist_numerics_profile(self, *_):
        store = getattr(self, "_numerics_profile_store", None)
        if store is None or not hasattr(self, "calc_grid"):
            return
        def count(text, fallback):
            try:
                return int(str(text).split("×", 1)[0].strip())
            except (TypeError, ValueError):
                return int(fallback)
        store.save({
            "automatic": bool(self.calc_auto_numerics.isChecked()),
            "precision": self.calc_precision.currentText(),
            "grid_size": count(self.calc_grid.currentText(), DEFAULT_OUTPUT_GRID_SIZE),
            "pupil_sample_count": count(self.calc_pupil.currentText(), 49),
            "layout_pupil_sample_count": count(self.calc_layout_pupil.currentText(), 9),
            "propagation": self.calc_propagation.currentText(),
            "padding": float(self.calc_padding.value()),
            "extent_mm": float(self.calc_extent.value()),
            "sampling_convergence": bool(self.output_boxes.get("sampling_convergence") and self.output_boxes["sampling_convergence"].isChecked()),
        })
