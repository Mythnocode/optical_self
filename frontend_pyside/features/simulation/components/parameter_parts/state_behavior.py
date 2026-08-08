from __future__ import annotations

import re


class ParameterStateMixin:
    @staticmethod
    def _parse_auxiliary_wavelengths(text: str, primary: float) -> tuple[float, ...]:
        values: list[float] = []
        for token in re.split(r"[,，;；\s]+", str(text or "").strip()):
            if not token:
                continue
            try:
                value = float(token)
            except (TypeError, ValueError):
                continue
            if not 100.0 <= value <= 30000.0:
                continue
            if abs(value - float(primary)) < 1e-9:
                continue
            if any(abs(value - existing) < 1e-9 for existing in values):
                continue
            values.append(value)
        return tuple(values)

    def collect_state(self):

        from ...form_state import (
            AlignmentFormState,
            CalculationFormState,
            PRECISION_MAP,
            PROPAGATION_MAP,
            RECEIVER_TYPE_MAP,
            ReceiverFormState,
            SOURCE_TYPE_MAP,
            SimulationFormState,
            SourceFormState,
            SystemFormState,
            parse_grid_size,
        )

        analyses = [name for name, box in self.analysis_boxes.items() if box.isChecked()]
        if self.system_auto_focus.isChecked() and "focus_search" not in analyses:
            analyses.append("focus_search")
        if not analyses:
            analyses = ["raytrace"]
        high_precision_coupling = bool(
            getattr(self, "calc_high_precision_coupling", None)
            and self.calc_high_precision_coupling.isChecked()
        )
        if high_precision_coupling and "coupling" not in analyses:
            analyses.append("coupling")
        mode_model = {"Gaussian": "gaussian", "高斯近似": "gaussian", "LP01": "lp01", "HE11": "he11", "导入复场": "imported"}.get(
            self.receiver_mode_model.currentText(), "gaussian"
        )
        primary_wavelength = float(self.system_wavelength.value())
        auxiliary_wavelengths = self._parse_auxiliary_wavelengths(
            self.system_auxiliary_wavelengths.text(), primary_wavelength
        )
        imported_field = None
        if mode_model == "imported":
            selector = getattr(self, "receiver_field_selector", None)
            imported_field = getattr(selector, "data", None)
            if imported_field is None:
                raise ValueError("选择‘导入复场’后，必须先选择并通过校验的复场文件。")
        source = SourceFormState(
            source_type=SOURCE_TYPE_MAP.get(self.source_type.currentText(), "gaussian"),
            wavelength_nm=primary_wavelength,
            waist_x_um=float(self.source_waist_x.value()),
            waist_y_um=float(self.source_waist_y.value()),
            waist_position_mm=float(self.source_waist_position.value()),
            beam_quality_m2_x=float(self.source_m2_x.value()),
            beam_quality_m2_y=float(self.source_m2_y.value()),
            object_na_x=float(self.source_na_x.value()),
            object_na_y=float(self.source_na_y.value()),
            field_x_deg=float(self.source_field_x.value()),
            field_y_deg=float(self.source_field_y.value()),
            power_value=float(self.source_power.value()),
            power_unit=self.source_power_unit.currentText(),
            auxiliary_wavelengths_nm=auxiliary_wavelengths,
        )
        receiver = ReceiverFormState(
            receiver_type=RECEIVER_TYPE_MAP.get(
                self.receiver_type.currentText(), "single_mode_fiber"
            ),
            mode_model=mode_model,
            mode_field_diameter_x_um=float(self.receiver_mfd_x.value()),
            mode_field_diameter_y_um=float(self.receiver_mfd_y.value()),
            core_diameter_um=float(self.receiver_core_diameter.value()),
            na_x=float(self.receiver_na_x.value()),
            na_y=float(self.receiver_na_y.value()),
            core_refractive_index=float(self.receiver_n_core.value()),
            cladding_refractive_index=float(self.receiver_n_clad.value()),
            outside_refractive_index=float(self.receiver_outside_index.value()),
            offset_x_um=float(self.receiver_offset_x.value()),
            offset_y_um=float(self.receiver_offset_y.value()),
            axial_offset_z_um=float(self.receiver_offset_z.value()),
            tilt_x_urad=float(self.receiver_tilt_x.value()),
            tilt_y_urad=float(self.receiver_tilt_y.value()),
            endface_transmission=float(self.receiver_endface.value()),
            fiber_length_m=float(self.receiver_length.value()),
            attenuation_db_per_km=float(self.receiver_attenuation.value()),
            connector_loss_db=float(self.receiver_connector_loss.value()),
            imported_mode_real=(imported_field.real if imported_field is not None else None),
            imported_mode_imag=(imported_field.imag if imported_field is not None else None),
            imported_mode_source=(imported_field.path if imported_field is not None else ""),
        )
        system = SystemFormState(
            object_distance_mm=float(self.system_object_distance.value()),
            pupil_radius_mm=float(self.system_pupil_radius.value()),
            image_distance_mm=float(self.system_image_distance.value()),
            field_x_deg=float(self.source_field_x.value()),
            field_y_deg=float(self.source_field_y.value()),
            auto_best_focus=bool(self.system_auto_focus.isChecked()),
            environment_temperature_c=float(self.system_temperature.value()),
            environment_pressure_kpa=float(self.system_pressure.value()),
            thermal_compensation=bool(self.system_thermal.isChecked()),
        )
        
        
        alignment = AlignmentFormState(enabled=False)
        calculation = CalculationFormState(
            precision=PRECISION_MAP.get(self.calc_precision.currentText(), "standard"),
            output_grid_size=parse_grid_size(self.calc_grid.currentText(), 257),
            pupil_sample_count=parse_grid_size(self.calc_pupil.currentText(), 49),
            layout_pupil_sample_count=parse_grid_size(
                self.calc_layout_pupil.currentText(), 9
            ),
            propagation_model=PROPAGATION_MAP.get(
                self.calc_propagation.currentText(),
                "band_limited_angular_spectrum",
            ),
            zero_padding_factor=float(self.calc_padding.value()),
            output_extent_mm=float(self.calc_extent.value()),
            analyses=tuple(analyses),
            only_visible_results=bool(
                self.output_boxes["only_visible_results"].isChecked()
            ),
            include_energy_audit=bool(self.analysis_boxes["power_audit"].isChecked()),
            sampling_convergence_enabled=bool(
                self.output_boxes["sampling_convergence"].isChecked()
            ),
            save_large_arrays=bool(self.output_boxes["save_large_arrays"].isChecked()),
            high_precision_coupling_enabled=high_precision_coupling,
        )
        return SimulationFormState(
            source=source,
            receiver=receiver,
            system=system,
            calculation=calculation,
            alignment=alignment,
        )

    def apply_alignment_solution(self, solution) -> None:

        widgets_and_values = (
            (self.receiver_offset_x, solution.offset_x_um),
            (self.receiver_offset_y, solution.offset_y_um),
            (self.receiver_offset_z, solution.axial_offset_z_um),
            (self.receiver_tilt_x, solution.tilt_x_urad),
            (self.receiver_tilt_y, solution.tilt_y_urad),
        )
        for widget, value in widgets_and_values:
            previous = widget.blockSignals(True)
            try:
                widget.setValue(float(value))
            finally:
                widget.blockSignals(previous)
        self.expand_section("fiber")
        self.changed.emit()
