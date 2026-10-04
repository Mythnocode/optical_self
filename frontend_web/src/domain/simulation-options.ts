import { clone, type SimulationRequest, type SimulationUiState } from "./simulation-project.js";

/** Transport mapping from the original form_state/request_options and execution_policy.
 * Optical propagation, mode generation and alignment remain in Python. */
export function uiState(request: SimulationRequest): SimulationUiState {
  const { source: s, receiver: r } = request.project;
  const ui = request.frontend_state ?? (request.frontend_state = {
    source_split: Math.abs(s.waist_x_mm - s.waist_y_mm) > 1e-9 || Math.abs(s.beam_quality_m2_x - s.beam_quality_m2_y) > 1e-9,
    source_na_split: Math.abs(s.object_na_x - s.object_na_y) > 1e-9,
    fiber_split: Math.abs(r.mode_field_diameter_x_um - r.mode_field_diameter_y_um) > 1e-9,
    fiber_na_split: Math.abs(r.na_x - r.na_y) > 1e-9,
    source_waist_um: s.waist_x_mm * 1000, source_position_mm: s.waist_position_x_mm, source_m2: s.beam_quality_m2_x,
    fiber_tilt_x_urad: r.tilt_x_deg * (Math.PI / 180) * 1e6, fiber_tilt_y_urad: r.tilt_y_deg * (Math.PI / 180) * 1e6,
    image_distance_mm: request.project.image_distance_mm,
  });
  ui.source_axes ??= Object.fromEntries(['waist_x_mm', 'waist_y_mm', 'waist_position_x_mm', 'waist_position_y_mm', 'beam_quality_m2_x', 'beam_quality_m2_y'].map(key => [key, Number((s as unknown as Record<string, unknown>)[key])]));
  ui.fiber_mfd_y_um ??= r.mode_field_diameter_y_um;
  ui.fiber_kind ??= r.receiver_type; ui.fiber_model ??= r.mode_model;
  ui.fiber_core_sm_um ??= r.core_diameter_um;
  ui.fiber_core_mm_um ??= r.core_diameter_um >= 10 ? r.core_diameter_um : 50;
  return ui;
}

export function auxiliaryWavelengths(text: string, primary: number): number[] {
  const values: number[] = [];
  for (const token of text.replace(/[，；;]/g, ",").split(",")) {
    const value = Number(token.trim());
    if (!token.trim() || !Number.isFinite(value) || value < 100 || value > 30000 || Math.abs(value - primary) < 1e-9
      || values.some(previous => Math.abs(previous - value) < 1e-9)) continue;
    values.push(value);
  }
  return values;
}

export function synchronizeRequest(request: SimulationRequest): void {
  const p = request.project, s = p.source, a = p.analysis_settings;
  s.beam_quality_m2 = .5 * (s.beam_quality_m2_x + s.beam_quality_m2_y);
  s.axis_tilt_x_rad = s.field_x_deg * (Math.PI / 180);
  s.axis_tilt_y_rad = s.field_y_deg * (Math.PI / 180);
  s.spectral_wavelengths_nm = [...new Set([s.wavelength_nm, ...s.spectral_wavelengths_nm].filter(value => value > 0))];
  s.spectral_power_weights = s.spectral_wavelengths_nm.map(() => 1 / s.spectral_wavelengths_nm.length);
  a.system_field_x_deg = s.field_x_deg; a.system_field_y_deg = s.field_y_deg;
  p.aperture.radius_mm = p.pupil_radius_mm;
  const analyses = [...a.requested_analyses];
  if (a.alignment_enabled && !analyses.includes("fiber_alignment")) analyses.push("fiber_alignment");
  if (a.auto_best_focus && !analyses.includes("focus_search")) analyses.push("focus_search");
  request.analyses = analyses.length ? analyses : ["raytrace"];
  request.precision = a.calc_precision;
  request.options = requestOptions(request);
}

export function requestOptions(request: SimulationRequest): Record<string, unknown> {
  const p = request.project, a = p.analysis_settings, r = p.receiver;
  const analyses = new Set(request.analyses), ui = uiState(request);
  const previous = request.options;
  const options: Record<string, unknown> = {
    environment_temperature_c: previous.environment_temperature_c ?? 20,
    environment_pressure_kpa: previous.environment_pressure_kpa ?? 101.325,
    geometric: { pupil_sample_count: a.calc_pupil, field_x_deg: p.source.field_x_deg, field_y_deg: p.source.field_y_deg, record_surfaces: analyses.has("raytrace") },
  };
  if (["psf", "mtf", "diffraction"].some(key => analyses.has(key))) options.wave = {
    grid_size: a.calc_grid_size, method: ({ scaled_fresnel: "fresnel", scaled_angular_spectrum: "angular_spectrum", issc: "angular_spectrum", matrix_fresnel: "fresnel" } as Record<string, string>)[a.calc_propagation] ?? a.calc_propagation,
    extent_mm: a.calc_output_extent_mm, zero_padding_factor: a.calc_zero_padding,
  };
  if (["coupling", "wavefront_quality", "fiber_alignment", "power_audit"].some(key => analyses.has(key))) {
    const hybrid: Record<string, unknown> = {
      pupil_sample_count: a.calc_pupil, grid_size: a.calc_grid_size, output_grid_size: a.calc_grid_size,
      output_extent_x_mm: a.calc_output_extent_mm, output_extent_y_mm: a.calc_output_extent_mm,
      propagation_model: a.calc_propagation, zero_padding_factor: a.calc_zero_padding,
      precision_mode: ({ preview: "preview", standard: "balanced", high: "reference" } as Record<string, string>)[a.calc_precision] ?? "balanced",
      convergence_enabled: a.calc_sampling_convergence, sampling_convergence_enabled: a.calc_sampling_convergence,
      auto_expand_output: a.calc_auto_expand_output, wavefront_fit_order: 4,
      include_diagnostic_arrays: a.calc_save_large_arrays || analyses.has("coupling"), result_array_policy: a.calc_save_large_arrays ? "full" : "field_only",
      mode_model: r.mode_model, tilt_x_urad: ui.fiber_tilt_x_urad, tilt_y_urad: ui.fiber_tilt_y_urad,
      high_precision_coupling_enabled: a.calc_high_precision_coupling, fiber_core_radius_um: r.core_diameter_um / 2,
      fiber_n_core: r.core_refractive_index, fiber_n_clad: r.cladding_refractive_index, receiver_medium_refractive_index: r.outside_refractive_index,
      fiber_length_m: r.fiber_length_m, fiber_attenuation_db_per_km: r.attenuation_db_per_km,
      fiber_connector_loss_db: r.connector_loss_db, fiber_facet_transmission_override: r.endface_transmission,
    };
    const imported = (previous.hybrid as Record<string, unknown> | undefined);
    if (r.mode_model === "imported" && ui.imported_field) {
      hybrid.imported_mode_values = { real: ui.imported_field.real, imag: ui.imported_field.imag }; hybrid.imported_mode_source = ui.imported_field.path;
    } else if (r.mode_model === "imported" && imported?.imported_mode_values) {
      hybrid.imported_mode_values = imported.imported_mode_values; hybrid.imported_mode_source = imported.imported_mode_source;
    }
    if (analyses.has("power_audit")) hybrid.include_breakdown = true;
    if (a.alignment_enabled && analyses.has("fiber_alignment")) Object.assign(hybrid, {
      method: "powell", include_dz: a.alignment_include_dz,
      initial_offset_x_um: r.offset_x_mm * 1000, initial_offset_y_um: r.offset_y_mm * 1000, initial_axial_offset_z_um: r.axial_offset_z_mm * 1000,
      initial_tilt_x_urad: ui.fiber_tilt_x_urad, initial_tilt_y_urad: ui.fiber_tilt_y_urad,
      max_offset_um: a.alignment_max_offset_um, max_axial_offset_um: a.alignment_max_axial_offset_um, max_tilt_urad: a.alignment_max_tilt_urad,
      max_iterations: a.alignment_max_iterations, max_function_evaluations: a.alignment_max_function_evaluations, timeout_seconds: a.alignment_timeout_seconds, return_history: false,
    });
    options.hybrid = hybrid;
  }
  return options;
}

/** Original global compute opens all formal result views; visible-only planning uses their analyses. */
export function computationRequest(request: SimulationRequest): SimulationRequest {
  const payload = clone(request);
  synchronizeRequest(payload);
  const a = payload.project.analysis_settings;
  if (a.calc_only_visible_results) payload.analyses = ["coupling", "psf", "raytrace", "spot", "wavefront_quality"];
  else payload.analyses = [...new Set(payload.analyses)].sort();
  if (payload.analyses.length === 1 && payload.analyses[0] === "raytrace") {
    a.calc_pupil = a.calc_layout_pupil; a.calc_sampling_convergence = false; a.calc_save_large_arrays = false;
  }
  a.requested_analyses = [...payload.analyses];
  payload.options = requestOptions(payload);
  const importedValues = payload.frontend_state?.imported_field ?? (payload.options.hybrid as Record<string, unknown> | undefined)?.imported_mode_values as { real: number[][]; imag: number[][] } | undefined;
  if (payload.project.receiver.mode_model === "imported" && !importedValues)
    throw new Error("导入复场模式缺少已校验的复场数据。");
  if (payload.project.receiver.mode_model === "imported") {
    const values = importedValues!;
    if (values.real.length !== a.calc_grid_size || values.imag.length !== a.calc_grid_size
      || values.real.some(row => row.length !== a.calc_grid_size) || values.imag.some(row => row.length !== a.calc_grid_size))
      throw new Error("复场尺寸与当前接收面网格不一致，请重新选择复场文件。");
  }
  delete payload.frontend_state;
  return payload;
}
