from __future__ import annotations

from collections import OrderedDict
import inspect
from typing import Any

import numpy as np

from .analysis_mapper import AnalysisSpec
from .analysis_registry import AnalysisCategory, DEFAULT_ANALYSIS_REGISTRY
from .result_merger import EnginePartialResult
from .sampling_roles import infer_sampling_role


class HybridPipeline:


    TRACE_OPTION_KEYS = {
        "wavelength_nm",
        "pupil_sample_count",
        "pupil_radius_mm",
        "record_surfaces",
        "explicit_pupil_samples",
        "propagate_to_image",
        "evaluate_apertures",
        "max_intersection_iterations",
        
        "source_model",
        "object_distance_mm",
        "object_space_na",
        "apodization_type",
        "apodization_factor",
        "apodization_factor_x",
        "apodization_factor_y",
        "include_source_to_pupil_opl",
        "start_z_mm",
        "field_x_deg",
        "field_y_deg",
        "sampling_role",
        "polarization_sensitive",
        "vector_coupling_enabled",
    }

    def __init__(self, *, prepared_coupling_cache_entries: int = 8) -> None:
        self._prepared_coupling_cache: OrderedDict[str, Any] = OrderedDict()
        self._prepared_coupling_cache_entries = max(1, int(prepared_coupling_cache_entries))
        self._prepared_coupling_cache_hits = 0
        self._prepared_coupling_cache_misses = 0

    def clear_caches(self) -> None:
        self._prepared_coupling_cache.clear()

    def cache_info(self) -> dict[str, Any]:
        return {
            "size": len(self._prepared_coupling_cache),
            "max_entries": self._prepared_coupling_cache_entries,
            "hits": self._prepared_coupling_cache_hits,
            "misses": self._prepared_coupling_cache_misses,
        }

    def _prepared_coupling_problem(self, trace: Any, options: Any) -> tuple[Any, str, bool]:
        from optical_core.physics.hybrid.solvers.fiber_coupling import prepare_fiber_coupling
        from .dependency_graph import prepared_coupling_key

        key = prepared_coupling_key(trace, options)
        try:
            problem = self._prepared_coupling_cache.pop(key)
        except KeyError:
            self._prepared_coupling_cache_misses += 1
            problem = prepare_fiber_coupling(trace, options)
            self._prepared_coupling_cache[key] = problem
            while len(self._prepared_coupling_cache) > self._prepared_coupling_cache_entries:
                self._prepared_coupling_cache.popitem(last=False)
            return problem, key, False
        self._prepared_coupling_cache_hits += 1
        self._prepared_coupling_cache[key] = problem
        return problem, key, True

    def evaluate(
        self,
        *,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
        context: Any | None = None,
        cancellation: Any | None = None,
    ) -> EnginePartialResult:


        result = EnginePartialResult.empty()
        trace_handlers = {
            "hybrid_coupling": self._run_coupling,
            "hybrid_detector": self._run_detector,
            "hybrid_exit_pupil": self._run_exit_pupil,
            "hybrid_wavefront_quality": self._run_wavefront_quality,
            "hybrid_psf_mtf": self._run_psf_mtf,
            "hybrid_fiber_tolerance": self._run_fiber_tolerance,
            "hybrid_fiber_alignment": self._run_fiber_alignment,
            "hybrid_coupling_research": self._run_coupling_research,
        }
        no_trace_handlers = {
            "hybrid_na_stop_fiber": self._run_na_stop_fiber,
            "hybrid_wavefront_tools": self._run_wavefront_tools,
            "hybrid_quality_audit": self._run_quality_audit,
        }
        for spec in analyses:
            definition = DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name)
            if definition.category is not AnalysisCategory.HYBRID:
                raise ValueError(f"analysis {spec.name!r} is not hybrid")
            executor = definition.executor
            if definition.requires_trace:
                trace = self._trace(system, [spec], global_options, context=context)
                try:
                    if executor in {"hybrid_fiber_tolerance", "hybrid_fiber_alignment"}:
                        partial = trace_handlers[executor](
                            trace,
                            [spec],
                            global_options,
                            cancellation=cancellation,
                        )
                    else:
                        partial = trace_handlers[executor](trace, [spec], global_options)
                except KeyError as exc:
                    raise RuntimeError(f"unbound hybrid executor: {executor!r}") from exc
            else:
                try:
                    handler = no_trace_handlers[executor]
                except KeyError as exc:
                    raise RuntimeError(f"unbound hybrid executor: {executor!r}") from exc
                if executor == "hybrid_na_stop_fiber":
                    partial = handler(system, [spec], global_options)
                else:
                    partial = handler(None, [spec], global_options)
            result.merge(partial)
        _add_hybrid_psf_mtf_aliases(result)
        return result

    def _options_for(
        self,
        *,
        name: str,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> dict[str, Any]:
        options = dict(global_options.get("hybrid", {}) or {})

        for analysis in analyses:
            if analysis.name == name:
                options.update(dict(analysis.options or {}))

        return options

    def _trace_options_for(
        self,
        *,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> dict[str, Any]:


        options = {
            key: value
            for key, value in dict(global_options.get("hybrid", {}) or {}).items()
            if key in self.TRACE_OPTION_KEYS
        }
        conflicts: list[str] = []

        for analysis in analyses:
            if not DEFAULT_ANALYSIS_REGISTRY.resolve(analysis.name).requires_trace:
                continue
            for key, value in dict(analysis.options or {}).items():
                if key not in self.TRACE_OPTION_KEYS:
                    continue
                if key in options and options[key] != value:
                    conflicts.append(
                        f"hybrid trace option {key!r} overridden by analysis "
                        f"{analysis.name!r}: {options[key]!r} -> {value!r}"
                    )
                options[key] = value

        if any(
            DEFAULT_ANALYSIS_REGISTRY.resolve(analysis.name).requires_complex_field
            for analysis in analyses
        ):
            options["record_surfaces"] = True
        options["sampling_role"] = infer_sampling_role(
            (analysis.name for analysis in analyses), options
        )
        if conflicts:
            options["_trace_option_conflict_warnings"] = conflicts
        return options

    def _trace(
        self,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
        *,
        context: Any | None = None,
    ) -> Any:
        opts = self._trace_options_for(analyses=analyses, global_options=global_options)
        if context is not None:
            return context.get_or_create_trace(opts)

        from optical_core.physics.geometric.operators.pupil_sampling import (
            sample_explicit_pupil_rays,
            sample_pupil_grid,
        )
        from optical_core.physics.geometric.solvers.batch_raytrace import trace_ray_batch
        from optical_core.physics.geometric.solvers.trace_options import TraceOptions

        wavelength_nm = float(opts.get("wavelength_nm", getattr(system, "wavelength_nm", 550.0)))
        pupil_sample_count = int(opts.get("pupil_sample_count", 25))
        pupil_radius_mm = float(opts.get("pupil_radius_mm", getattr(system, "pupil_radius_mm", 1.0)))

        common_kwargs = {
            "pupil_radius_mm": pupil_radius_mm,
            "wavelength_nm": wavelength_nm,
            "start_z_mm": float(opts.get("start_z_mm", -1.0e-6)),
            "field_x_deg": float(opts.get("field_x_deg", 0.0)),
            "field_y_deg": float(opts.get("field_y_deg", 0.0)),
            "source_model": str(opts.get("source_model", "parallel_pupil")),
            "object_distance_mm": float(opts.get("object_distance_mm", getattr(system, "object_distance_mm", 0.0)) or 0.0),
            "object_space_na": (
                None if opts.get("object_space_na", None) is None else float(opts.get("object_space_na"))
            ),
            "apodization_type": opts.get("apodization_type", None),
            "apodization_factor": (
                None if opts.get("apodization_factor", None) is None else float(opts.get("apodization_factor"))
            ),
            "apodization_factor_x": (
                None if opts.get("apodization_factor_x", None) is None else float(opts.get("apodization_factor_x"))
            ),
            "apodization_factor_y": (
                None if opts.get("apodization_factor_y", None) is None else float(opts.get("apodization_factor_y"))
            ),
            "include_source_to_pupil_opl": bool(opts.get("include_source_to_pupil_opl", False)),
        }
        if opts.get("explicit_pupil_samples") is not None:
            rays = sample_explicit_pupil_rays(
                samples=opts.get("explicit_pupil_samples"),
                **common_kwargs,
            )
            pupil_sample_count = int(rays.valid_mask.size)
        else:
            rays = sample_pupil_grid(
                sample_count=pupil_sample_count,
                **common_kwargs,
            )

        trace_options = TraceOptions(
            wavelength_nm=wavelength_nm,
            pupil_sample_count=pupil_sample_count,
            record_surfaces=bool(
                opts.get("record_surfaces", any(a.name == "wavefront_quality" for a in analyses))
            ),
            propagate_to_image=bool(opts.get("propagate_to_image", True)),
            evaluate_apertures=bool(opts.get("evaluate_apertures", True)),
            max_intersection_iterations=int(opts.get("max_intersection_iterations", 12)),
            apply_surface_physics=bool(opts.get("apply_surface_physics", True)),
            environment_temperature_c=float(opts.get("environment_temperature_c", 20.0)),
            include_group_delay=bool(opts.get("include_group_delay", False)),
            polarization_sensitive=bool(opts.get("polarization_sensitive", False) or opts.get("vector_coupling_enabled", False)),
        )

        trace = trace_ray_batch(system, rays, trace_options)
        conflict_warnings = list(opts.get("_trace_option_conflict_warnings", []) or [])
        if conflict_warnings:
            trace.warnings.extend(conflict_warnings)
        return trace

    def _run_coupling(
        self,
        trace: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.coupling.service import evaluate_coupling
        from optical_core.physics.hybrid.solvers.coupling_options import (
            CouplingOptions,
            apply_coupling_precision_defaults,
            parse_jones_pair,
        )

        opts = apply_coupling_precision_defaults(
            self._options_for(name="coupling", analyses=analyses, global_options=global_options)
        )
        convergence_grid_sizes = _as_int_tuple(opts.get("convergence_grid_sizes", (65, 129, 257, 513)))

        coupling_options = CouplingOptions(
            wavelength_nm=float(opts.get("wavelength_nm", getattr(trace, "wavelength_nm", 550.0))),
            grid_size=int(opts.get("grid_size", 65)),
            field_extent_mm=opts.get("field_extent_mm", None),
            mode_field_diameter_x_um=float(opts.get("mode_field_diameter_x_um", 1000.0)),
            mode_field_diameter_y_um=float(opts.get("mode_field_diameter_y_um", opts.get("mode_field_diameter_x_um", 1000.0))),
            mode_model=str(opts.get("mode_model", "gaussian")),
            vector_coupling_enabled=bool(opts.get("vector_coupling_enabled", False)),
            vector_coupling_model=str(opts.get("vector_coupling_model", "paraxial_trace")),
            polarization_sensitive=bool(opts.get("polarization_sensitive", False)),
            incident_jones_vector=parse_jones_pair(opts.get("incident_jones_vector", "linear_x")),
            fiber_mode_jones_vector=parse_jones_pair(opts.get("fiber_mode_jones_vector", "linear_x")),
            receiver_na_x=_optional_float(opts.get("receiver_na_x", None)),
            receiver_na_y=_optional_float(opts.get("receiver_na_y", None)),
            receiver_medium_refractive_index=float(opts.get("receiver_medium_refractive_index", 1.0)),
            offset_x_mm=float(opts.get("offset_x_mm", 0.0)),
            offset_y_mm=float(opts.get("offset_y_mm", 0.0)),
            tilt_x_rad=_tilt_rad_from_options(opts, "tilt_x"),
            tilt_y_rad=_tilt_rad_from_options(opts, "tilt_y"),
            field_model="cartesian_pupil_propagation",
            propagation_model=str(opts.get("propagation_model", "angular_spectrum")),
            propagation_distance_mm=_optional_float(opts.get("propagation_distance_mm", None)),
            receiver_axial_offset_z_mm=float(
                opts.get("receiver_axial_offset_z_mm", opts.get("axial_offset_z_mm", 0.0)) or 0.0
            ),
            sampling_model=str(opts.get("sampling_model", "equal_area_pupil")),
            convergence_enabled=bool(opts.get("convergence_enabled", True)),
            precision_mode=str(opts.get("precision_mode", "balanced")),
            wavefront_fit_order=int(opts.get("wavefront_fit_order", 2)),
            pupil_amplitude_weighting=str(opts.get("pupil_amplitude_weighting", "quadrature")),
            pupil_grid_size=int(opts.get("pupil_grid_size", 257)),
            pupil_extent_scale=float(opts.get("pupil_extent_scale", 1.04)),
            zero_padding_factor=float(opts.get("zero_padding_factor", 2.0)),
            scaled_angular_spectrum_transfer_model=str(opts.get("scaled_angular_spectrum_transfer_model", "fresnel")),
            edge_power_threshold=float(opts.get("edge_power_threshold", 1.0e-4)),
            energy_closure_threshold=float(opts.get("energy_closure_threshold", 5.0e-3)),
            nyquist_margin_min=float(opts.get("nyquist_margin_min", 1.0)),
            auto_expand_output=bool(opts.get("auto_expand_output", True)),
            auto_expand_factor=float(opts.get("auto_expand_factor", 1.5)),
            auto_expand_max_steps=int(opts.get("auto_expand_max_steps", 3)),
        auto_expand_max_grid_size=int(opts.get("auto_expand_max_grid_size", 1025)),
            enforce_numerical_gates=bool(opts.get("enforce_numerical_gates", False)),
            include_diagnostic_arrays=bool(opts.get("include_diagnostic_arrays", True)),
            result_array_policy=str(opts.get("result_array_policy", "full")),
            output_grid_size=(None if opts.get("output_grid_size", None) is None else int(opts.get("output_grid_size"))),
            output_extent_x_mm=_optional_float(opts.get("output_extent_x_mm", None)),
            output_extent_y_mm=_optional_float(opts.get("output_extent_y_mm", None)),
            sampling_convergence_enabled=bool(opts.get("sampling_convergence_enabled", False)),
            sampling_convergence_grid_sizes=_as_int_tuple(opts.get("sampling_convergence_grid_sizes", (257, 513))),
            sampling_convergence_tolerance=float(opts.get("sampling_convergence_tolerance", 5.0e-3)),
            issc_oversampling_factor=float(opts.get("issc_oversampling_factor", 1.2)),
            issc_padding_factor=float(opts.get("issc_padding_factor", 0.1)),
            issc_max_virtual_grid=int(opts.get("issc_max_virtual_grid", 2048)),
            include_breakdown=bool(opts.get("include_breakdown", True)),
            include_convergence=bool(opts.get("include_convergence", False)),
            convergence_grid_sizes=convergence_grid_sizes,
            coherent=bool(opts.get("coherent", True)),
            fiber_core_radius_um=opts.get("fiber_core_radius_um", None),
            fiber_n_core=opts.get("fiber_n_core", None),
            fiber_n_clad=opts.get("fiber_n_clad", None),
            fiber_length_m=float(opts.get("fiber_length_m", 0.0)),
            fiber_attenuation_db_per_km=float(opts.get("fiber_attenuation_db_per_km", 0.0)),
            fiber_connector_loss_db=float(opts.get("fiber_connector_loss_db", 0.0)),
            fiber_facet_transmission_override=_optional_float(opts.get("fiber_facet_transmission_override", None)),
            finite_difference_refractive_index_map=opts.get("finite_difference_refractive_index_map", None),
            imported_mode_values=opts.get("imported_mode_values", None),
            fiber_mode_index=int(opts.get("fiber_mode_index", 0)),
        )

        
        
        
        
        
        parameters = inspect.signature(evaluate_coupling).parameters
        if "prepared_problem" in parameters:
            prepared, prepared_key, prepared_hit = self._prepared_coupling_problem(
                trace, coupling_options
            )
            raw = evaluate_coupling(
                trace, coupling_options, prepared_problem=prepared
            )
        else:  
            prepared_key = ""
            prepared_hit = False
            raw = evaluate_coupling(trace, coupling_options)
        partial = _to_partial_result(raw)
        partial.metadata["coupling_done"] = True
        partial.metadata["prepared_coupling_cache_hit"] = prepared_hit
        partial.metadata["prepared_coupling_dependency_key"] = prepared_key
        partial.metadata["prepared_coupling_cache"] = self.cache_info()
        self._append_trace_audit(trace, partial)
        return partial

    def _run_detector(self, trace: Any, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.detector import evaluate_detector

        opts = self._options_for(name="detector", analyses=analyses, global_options=global_options)
        raw = evaluate_detector(trace, opts)
        partial = _to_partial_result(raw)
        partial.metadata["detector_done"] = True
        return partial

    def _run_exit_pupil(self, trace: Any, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.exit_pupil import evaluate_exit_pupil

        opts = self._options_for(name="exit_pupil", analyses=analyses, global_options=global_options)
        raw = evaluate_exit_pupil(trace, opts)
        partial = _to_partial_result(raw)
        partial.metadata["exit_pupil_done"] = True
        return partial

    def _run_wavefront_quality(self, trace: Any, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.wavefront_quality import evaluate_wavefront_quality

        opts = self._options_for(name="wavefront_quality", analyses=analyses, global_options=global_options)
        raw = evaluate_wavefront_quality(trace, opts)
        partial = _to_partial_result(raw)
        partial.metadata["wavefront_quality_done"] = True
        return partial

    def _run_psf_mtf(self, trace: Any, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.psf_mtf import evaluate_psf_mtf_from_trace

        opts = self._options_for(name="psf_mtf", analyses=analyses, global_options=global_options)
        raw = evaluate_psf_mtf_from_trace(trace, opts)
        partial = _to_partial_result(raw)
        partial.metadata["hybrid_psf_mtf_done"] = True
        return partial


    def _run_fiber_tolerance(
        self,
        trace: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
        *,
        cancellation: Any | None = None,
    ) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.fiber_tolerance import evaluate_fiber_tolerance

        opts = self._options_for(name="fiber_tolerance", analyses=analyses, global_options=global_options)
        raw = evaluate_fiber_tolerance(trace, opts, cancellation=cancellation)
        partial = _to_partial_result(raw)
        partial.metadata.setdefault("fiber_tolerance_done", True)
        self._append_trace_audit(trace, partial)
        return partial

    def _run_fiber_alignment(
        self,
        trace: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
        *,
        cancellation: Any | None = None,
    ) -> EnginePartialResult:
        from optical_core.physics.hybrid.analyses.fiber_alignment import evaluate_fiber_alignment

        opts = self._options_for(name="fiber_alignment", analyses=analyses, global_options=global_options)
        raw = evaluate_fiber_alignment(trace, opts, cancellation=cancellation)
        partial = _to_partial_result(raw)
        partial.metadata.setdefault("fiber_alignment_done", True)
        self._append_trace_audit(trace, partial)
        return partial

    def _run_coupling_research(
        self,
        trace: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:


        from optical_core.physics.coupling_research import (
            compare_alignment_methods,
            dimensionless_coupling_coordinates,
            evaluate_dynamic_coupling,
            evaluate_joint_tolerance_map,
            gaussian_mode_coupling_reference,
            generate_gaussian_jitter,
            scan_pupil_zernike_coupling_sensitivity,
        )
        from optical_core.physics.hybrid.operators.zernike import STANDARD_TERMS
        from optical_core.physics.hybrid.solvers.fiber_coupling import prepare_fiber_coupling
        from optical_core.physics.hybrid.tolerance import coupling_options_from_mapping

        opts = self._options_for(name="coupling_research", analyses=analyses, global_options=global_options)
        opts.setdefault("wavelength_nm", float(getattr(trace, "wavelength_nm", 550.0)))
        options = coupling_options_from_mapping(opts)
        prepared = prepare_fiber_coupling(trace, options)
        nominal = prepared.evaluate()
        field = nominal.receiver_field
        mode = nominal.receiving_mode
        base_eta = float(nominal.efficiency)

        metrics: dict[str, Any] = {
            "coupling_research_baseline_efficiency": base_eta,
            "coupling_research_mode_model": str(options.mode_model),
            "coupling_research_reference_data_used_as_input": False,
            "coupling_research_zemax_data_used_as_input": False,
        }
        arrays: dict[str, Any] = {}
        warnings: list[str] = list(prepared.warnings)

        intensity = np.abs(np.asarray(field.values)) ** 2
        total = float(np.sum(intensity))
        if total > 0.0:
            xx, yy = np.meshgrid(field.grid.x_mm, field.grid.y_mm, indexing="xy")
            cx = float(np.sum(intensity * xx) / total)
            cy = float(np.sum(intensity * yy) / total)
            sigma_x_um = float(np.sqrt(np.sum(intensity * (xx - cx) ** 2) / total) * 1.0e3)
            sigma_y_um = float(np.sqrt(np.sum(intensity * (yy - cy) ** 2) / total) * 1.0e3)
            incident_radius_x_um = max(2.0 * sigma_x_um, 1.0e-12)
            incident_radius_y_um = max(2.0 * sigma_y_um, 1.0e-12)
            theory = gaussian_mode_coupling_reference(
                wavelength_nm=options.wavelength_nm,
                incident_radius_x_um=incident_radius_x_um,
                incident_radius_y_um=incident_radius_y_um,
                mode_radius_x_um=0.5 * options.mode_field_diameter_x_um,
                mode_radius_y_um=0.5 * options.mode_field_diameter_y_um,
                offset_x_um=options.offset_x_mm * 1.0e3,
                offset_y_um=options.offset_y_mm * 1.0e3,
                tilt_x_rad=options.tilt_x_rad,
                tilt_y_rad=options.tilt_y_rad,
                refractive_index=options.receiver_medium_refractive_index,
            )
            metrics.update({
                "coupling_research_incident_radius_x_um": incident_radius_x_um,
                "coupling_research_incident_radius_y_um": incident_radius_y_um,
                "coupling_research_gaussian_reference_efficiency": theory.efficiency,
                "coupling_research_gaussian_mode_size_efficiency": theory.mode_size_efficiency,
                "coupling_research_gaussian_lateral_efficiency": theory.lateral_efficiency,
                "coupling_research_gaussian_angular_efficiency": theory.angular_efficiency,
            })
            rayleigh_um = np.pi * (0.5 * options.mode_field_diameter_x_um) ** 2 * options.receiver_medium_refractive_index / (options.wavelength_nm * 1.0e-3)
            metrics.update({
                f"coupling_research_{key}": value
                for key, value in dimensionless_coupling_coordinates(
                    offset_um=options.offset_x_mm * 1.0e3,
                    axial_offset_um=options.receiver_axial_offset_z_mm * 1.0e3,
                    tilt_rad=options.tilt_x_rad,
                    mode_radius_um=0.5 * options.mode_field_diameter_x_um,
                    rayleigh_range_um=rayleigh_um,
                    wavelength_nm=options.wavelength_nm,
                    refractive_index=options.receiver_medium_refractive_index,
                ).items()
            })

        def efficiency_for(parameters: dict[str, float]) -> float:
            return prepared.efficiency(
                offset_x_mm=float(parameters.get("dx_um", options.offset_x_mm * 1.0e3)) * 1.0e-3,
                offset_y_mm=float(parameters.get("dy_um", options.offset_y_mm * 1.0e3)) * 1.0e-3,
                receiver_axial_offset_z_mm=float(parameters.get("dz_um", options.receiver_axial_offset_z_mm * 1.0e3)) * 1.0e-3,
                tilt_x_rad=float(parameters.get("tilt_x_urad", options.tilt_x_rad * 1.0e6)) * 1.0e-6,
                tilt_y_rad=float(parameters.get("tilt_y_urad", options.tilt_y_rad * 1.0e6)) * 1.0e-6,
            )

        if bool(opts.get("include_joint_offset_tilt", False)):
            dx = np.asarray(opts.get("joint_dx_um", np.linspace(-5.0, 5.0, 7)), dtype=float)
            tilt = np.asarray(opts.get("joint_tilt_x_urad", np.linspace(-50000.0, 50000.0, 7)), dtype=float)
            joint = evaluate_joint_tolerance_map(
                efficiency_for, axis_x_name="dx_um", axis_x=dx,
                axis_y_name="tilt_x_urad", axis_y=tilt,
                threshold=opts.get("joint_threshold_efficiency", None),
            )
            arrays.update({
                "coupling_research_joint_dx_um": joint.axis_x.tolist(),
                "coupling_research_joint_tilt_x_urad": joint.axis_y.tolist(),
                "coupling_research_joint_dx_tilt_efficiency": joint.efficiency.tolist(),
            })
            metrics.update({f"coupling_research_joint_{key}": value for key, value in joint.metrics.items()})

        if bool(opts.get("include_joint_offset_defocus", False)):
            dx = np.asarray(opts.get("joint_dx_um", np.linspace(-5.0, 5.0, 7)), dtype=float)
            dz = np.asarray(opts.get("joint_dz_um", np.linspace(-100.0, 100.0, 7)), dtype=float)
            joint = evaluate_joint_tolerance_map(
                efficiency_for, axis_x_name="dx_um", axis_x=dx,
                axis_y_name="dz_um", axis_y=dz,
                threshold=opts.get("joint_threshold_efficiency", None),
            )
            arrays.update({
                "coupling_research_joint_dz_um": joint.axis_y.tolist(),
                "coupling_research_joint_dx_dz_efficiency": joint.efficiency.tolist(),
            })
            metrics.update({f"coupling_research_joint_defocus_{key}": value for key, value in joint.metrics.items()})

        if bool(opts.get("include_aberration_scan", False)):
            coefficients = np.asarray(opts.get("aberration_coefficients_waves_rms", (-0.1, 0.0, 0.1)), dtype=float)
            requested_indices = {int(value) for value in opts.get("aberration_term_indices", (4, 5, 6, 7, 8, 11))}
            terms = tuple(term for term in STANDARD_TERMS if term.index in requested_indices)
            scans = scan_pupil_zernike_coupling_sensitivity(
                prepared,
                coefficients_waves_rms=coefficients,
                terms=terms,
                pupil_radius_mm=opts.get("aberration_radius_mm", None),
            )
            metrics["coupling_research_aberration_application_plane"] = "exit_pupil"
            metrics["coupling_research_aberration_requires_new_propagation"] = True
            arrays["coupling_research_aberration_coefficients_waves_rms"] = coefficients.tolist()
            arrays["coupling_research_aberration_term_names"] = [item.term_name for item in scans]
            arrays["coupling_research_aberration_efficiency"] = [item.efficiency.tolist() for item in scans]
            arrays["coupling_research_aberration_loss_db"] = [item.loss_db.tolist() for item in scans]
            arrays["coupling_research_aberration_ranking"] = [
                {
                    "term_index": item.term_index,
                    "term_name": item.term_name,
                    "loss_db_per_wave2": item.local_loss_db_per_wave2,
                    "zero_is_local_maximum": item.zero_is_local_maximum,
                    "maximum_coefficient_waves_rms": item.maximum_coefficient_waves_rms,
                    "maximum_efficiency": item.maximum_efficiency,
                }
                for item in scans
            ]
            improving_terms = [item.term_name for item in scans if not item.zero_is_local_maximum]
            metrics["coupling_research_aberration_baseline_stationary"] = not improving_terms
            arrays["coupling_research_aberration_improving_terms"] = improving_terms
            if improving_terms:
                warnings.append(
                    "The nominal field is not a local coupling maximum for Zernike terms: "
                    + ", ".join(improving_terms)
                    + ". Interpret the scan as residual-aberration compensation, not isolated sensitivity."
                )
            if scans:
                metrics["coupling_research_most_sensitive_aberration"] = scans[0].term_name
                metrics["coupling_research_most_sensitive_loss_db_per_wave2"] = scans[0].local_loss_db_per_wave2

        if bool(opts.get("include_dynamic_jitter", False)):
            jitter = generate_gaussian_jitter(
                sample_count=int(opts.get("jitter_sample_count", 128)),
                sample_rate_hz=float(opts.get("jitter_sample_rate_hz", 1000.0)),
                standard_deviation_by_parameter=dict(opts.get("jitter_sigma", {"dx_um": 0.5, "dy_um": 0.5})),
                mean_by_parameter=dict(opts.get("jitter_mean", {})),
                correlation_matrix=(None if opts.get("jitter_correlation_matrix") is None else np.asarray(opts.get("jitter_correlation_matrix"), dtype=float)),
                random_seed=int(opts.get("random_seed", 0)),
            )
            dynamic = evaluate_dynamic_coupling(
                jitter, efficiency_for, threshold=opts.get("jitter_threshold_efficiency", None)
            )
            metrics.update({f"coupling_research_dynamic_{key}": value for key, value in dynamic.metrics.items()})
            arrays["coupling_research_dynamic_time_s"] = dynamic.time_s.tolist()
            arrays["coupling_research_dynamic_efficiency"] = dynamic.efficiency.tolist()
            arrays["coupling_research_dynamic_parameters"] = {
                key: np.asarray(value).tolist() for key, value in dynamic.parameters.items()
            }

        if bool(opts.get("include_alignment_benchmark", False)):
            methods = tuple(str(value) for value in opts.get("alignment_methods", ("Powell",)))
            unsupported = [method for method in methods if method.strip().lower() != "powell"]
            if unsupported:
                raise ValueError(
                    "stable alignment benchmark currently supports Powell only; "
                    f"unsupported methods: {', '.join(unsupported)}"
                )
            initial = np.asarray(opts.get("alignment_initial", (options.offset_x_mm * 1.0e3, options.offset_y_mm * 1.0e3)), dtype=float)
            bounds = tuple(tuple(float(v) for v in pair) for pair in opts.get("alignment_bounds", ((-10.0, 10.0), (-10.0, 10.0))))
            benchmark = compare_alignment_methods(
                lambda vector: prepared.efficiency(offset_x_mm=float(vector[0]) * 1.0e-3, offset_y_mm=float(vector[1]) * 1.0e-3),
                initial, methods=methods, bounds=bounds, max_iterations=int(opts.get("alignment_max_iterations", 100)),
            )
            arrays["coupling_research_alignment_benchmark"] = [
                {
                    "method": item.method,
                    "best_parameters_um": item.best_parameters.tolist(),
                    "initial_efficiency": item.initial_efficiency,
                    "best_efficiency": item.best_efficiency,
                    "function_evaluations": item.function_evaluations,
                    "iterations": item.iterations,
                    "converged": item.converged,
                    "message": item.message,
                }
                for item in benchmark
            ]
            if benchmark:
                metrics["coupling_research_best_alignment_method"] = benchmark[0].method
                metrics["coupling_research_best_aligned_efficiency"] = benchmark[0].best_efficiency

        metrics.update({
            "coupling_research_field_propagation_count": prepared.field_propagation_count,
            "coupling_research_field_cache_hits": prepared.field_cache_hits,
            "coupling_research_mode_build_count": prepared.mode_build_count,
            "coupling_research_evaluation_count": prepared.evaluation_count,
            "coupling_research_evaluation_cache_hits": prepared.evaluation_cache_hits,
        })
        partial = EnginePartialResult(
            metrics=metrics, arrays=arrays, warnings=list(dict.fromkeys(warnings)),
            metadata={
                "coupling_research_done": True,
                "coupling_research_algorithm_version": "1.0",
                "formal_complex_field_chain": "cartesian_exit_pupil",
                "reference_data_used_as_input": False,
                "zemax_data_used_as_input": False,
            },
        )
        self._append_trace_audit(trace, partial)
        return partial

    def _run_na_stop_fiber(self, system: Any, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.physics.hybrid.operators.na_stop_fiber import evaluate_na_stop_fibre

        opts = self._options_for(name="na_stop_fiber", analyses=analyses, global_options=global_options)
        opts.setdefault("wavelength_nm", getattr(system, "wavelength_nm", 550.0))
        opts.setdefault("object_distance_mm", getattr(system, "object_distance_mm", 100.0))
        raw = {"metrics": evaluate_na_stop_fibre(opts), "metadata": {"na_stop_fiber_done": True}}
        return _to_partial_result(raw)

    def _run_wavefront_tools(self, trace: Any | None, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.physics.hybrid.operators.wavefront_tools import (
            compute_standard_wavefront_map,
            fit_gaussian_array,
            fit_zernike_map,
            image_space_numerical_aperture,
            remove_zernike_modes,
        )

        opts = self._options_for(name="wavefront_tools", analyses=analyses, global_options=global_options)
        grid_size = int(opts.get("grid_size", 65))
        coefficients = opts.get("coefficients_nm", opts.get("zernike_coefficients_nm", [0.0, 0.0, 0.0, 50.0, 10.0]))
        remove_indices = tuple(int(x) for x in opts.get("remove_indices", (0, 1, 2, 3)))
        max_terms = int(opts.get("max_terms", 15))

        wavefront = compute_standard_wavefront_map(coefficients, grid_size=grid_size)
        fitted_coeff, fitted_map = fit_zernike_map(wavefront, max_terms=max_terms)
        removal = remove_zernike_modes(wavefront, remove_indices=remove_indices, max_terms=max_terms)
        residual = np.asarray(removal["residual_map_nm"], dtype=float)
        gaussian_fit = fit_gaussian_array(np.exp(-np.square(wavefront / max(float(np.std(wavefront)), 1e-12))))

        rms = float(np.sqrt(np.mean(np.square(wavefront)))) if wavefront.size else 0.0
        residual_rms = float(np.sqrt(np.mean(np.square(residual)))) if residual.size else 0.0
        image_na = image_space_numerical_aperture(
            float(opts.get("rms_spot_radius_mm", 0.01)),
            float(opts.get("focal_shift_mm", 1.0)),
            refractive_index=float(opts.get("refractive_index", 1.0)),
        )

        spot_points: list[list[float]] = []
        if trace is not None:
            positions = np.asarray(getattr(trace, "final_positions_mm", []), dtype=float)
            valid = np.asarray(getattr(trace, "valid_mask", np.ones(len(positions), dtype=bool)), dtype=bool)
            if positions.ndim == 2 and positions.shape[1] >= 3 and positions.shape[0] == valid.size:
                spot_points = np.column_stack(
                    (positions[valid, 0] * 1000.0, positions[valid, 1] * 1000.0)
                ).tolist()

        metrics = {
            "wavefront_tools_rms_nm": rms,
            "wavefront_tools_residual_rms_nm": residual_rms,
            "wavefront_tools_image_space_na": float(image_na),
            "wavefront_tools_fit_term_count": float(len(fitted_coeff)),
            **{f"wavefront_tools_{key}": float(value) for key, value in gaussian_fit.items()},
        }
        arrays = {
            "wavefront_tools_map_nm": wavefront.tolist(),
            "wavefront_tools_fitted_map_nm": np.asarray(fitted_map, dtype=float).tolist(),
            "wavefront_tools_residual_map_nm": residual.tolist(),
            "wavefront_tools_coefficients_nm": np.asarray(fitted_coeff, dtype=float).tolist(),
            "wavefront_tools_spot_points_um": spot_points,
        }
        return _to_partial_result({"metrics": metrics, "arrays": arrays, "metadata": {"wavefront_tools_done": True}})

    def _run_quality_audit(self, trace: Any | None, analyses: list[AnalysisSpec], global_options: dict[str, Any]) -> EnginePartialResult:
        from optical_core.quality.audit_suite import run_quality_audit_suite

        opts = self._options_for(name="quality_audit", analyses=analyses, global_options=global_options)
        if trace is not None:
            valid_mask = np.asarray(getattr(trace, "valid_mask", []), dtype=bool)
            opts.setdefault("ray_count", int(valid_mask.size))
        raw = run_quality_audit_suite(opts)
        partial = _to_partial_result(raw)
        partial.metadata["quality_audit_done"] = True
        benchmarks = raw.get("benchmarks") if isinstance(raw, dict) else None
        if benchmarks is not None:
            partial.metadata["standard_benchmarks"] = benchmarks
        return partial

    def _append_trace_audit(self, trace: Any, partial: EnginePartialResult) -> None:
        try:
            from optical_core.quality.invariant_check import audit_trace_invariants

            audit = audit_trace_invariants(trace)

            if isinstance(audit, dict):
                partial.metrics.update(dict(audit.get("metrics", {}) or {}))
                partial.warnings.extend(list(audit.get("warnings", []) or []))
            else:
                partial.metrics.update(dict(getattr(audit, "metrics", {}) or {}))
                partial.warnings.extend(list(getattr(audit, "warnings", []) or []))

            partial.metadata["hybrid_quality_audits"] = ["trace_invariants"]

        except Exception as exc:
            partial.warnings.append(f"trace invariant audit skipped: {exc}")


def _to_partial_result(raw: Any) -> EnginePartialResult:
    result = EnginePartialResult.empty()

    if isinstance(raw, dict):
        if "metrics" in raw or "arrays" in raw or "metadata" in raw:
            result.metrics.update(dict(raw.get("metrics", {}) or {}))
            result.arrays.update(dict(raw.get("arrays", {}) or {}))
            result.warnings.extend(list(raw.get("warnings", []) or []))
            result.errors.extend(list(raw.get("errors", []) or []))
            result.metadata.update(dict(raw.get("metadata", {}) or {}))
            success = raw.get("success", None)
            if success is not None:
                result.converged = bool(success)
        else:
            result.metrics.update(dict(raw))
        return result

    result.metrics.update(dict(getattr(raw, "metrics", {}) or {}))
    result.arrays.update(dict(getattr(raw, "arrays", {}) or {}))
    result.warnings.extend(list(getattr(raw, "warnings", []) or []))
    result.errors.extend(list(getattr(raw, "errors", []) or []))
    result.metadata.update(dict(getattr(raw, "metadata", {}) or {}))

    success = getattr(raw, "success", None)
    if success is not None:
        result.converged = bool(success)

    return result


def _add_hybrid_psf_mtf_aliases(result: EnginePartialResult) -> None:
    metric_aliases = {
        "psf_peak_normalized": "hybrid_psf_peak_normalized",
        "psf_rms_radius_mm": "hybrid_psf_rms_radius_mm",
        "mtf_dc": "hybrid_mtf_dc",
        "mtf_grid_size": "hybrid_mtf_grid_size",
    }

    for source_key, alias_key in metric_aliases.items():
        if source_key in result.metrics and alias_key not in result.metrics:
            result.metrics[alias_key] = result.metrics[source_key]

    array_aliases = {
        "psf_intensity": "hybrid_psf_intensity",
        "mtf_values": "hybrid_mtf_values",
        "mtf_frequency_cycles_per_mm": "hybrid_mtf_frequency_cycles_per_mm",
    }

    for source_key, alias_key in array_aliases.items():
        if source_key in result.arrays and alias_key not in result.arrays:
            result.arrays[alias_key] = result.arrays[source_key]


def _as_int_tuple(value: Any) -> tuple[int, ...]:
    if isinstance(value, str):
        return tuple(int(item.strip()) for item in value.split(",") if item.strip())
    try:
        return tuple(int(item) for item in value)
    except TypeError:
        return (int(value),)


def _tilt_rad_from_options(opts: dict[str, Any], axis: str) -> float:
    """Return receiver tilt in radians from any supported UI/runtime unit.

    The GUI serializes receiver tilt through ``receiver.tilt_*_deg`` while
    research/legacy callers may supply rad, urad, or mrad directly.  Keep a
    deterministic precedence so an explicit low-level runtime override wins
    over the project-level degree value compiled from the GUI.
    """
    for suffix, scale in (("rad", 1.0), ("urad", 1.0e-6), ("mrad", 1.0e-3)):
        key = f"{axis}_{suffix}"
        if key in opts:
            return float(opts[key]) * scale
    deg_key = f"{axis}_deg"
    if deg_key in opts:
        return float(np.deg2rad(float(opts[deg_key])))
    return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
