from __future__ import annotations

from typing import Any

import numpy as np

from .analysis_mapper import AnalysisSpec
from .analysis_registry import AnalysisCategory, DEFAULT_ANALYSIS_REGISTRY
from .result_merger import EnginePartialResult
from .sampling_roles import infer_sampling_role


_TRACE_ANALYSES = {
    "raytrace",
    "spot",
    "throughput",
    "power_audit",
    "focus_search",
}

_TRACE_OPTION_KEYS = {
    "wavelength_nm",
    "pupil_sample_count",
    "pupil_radius_mm",
    "record_surfaces",
    "propagate_to_image",
    "evaluate_apertures",
    "max_intersection_iterations",
    "explicit_pupil_samples",
    "source_model",
    "object_distance_mm",
    "object_space_na",
    "field_x_deg",
    "field_y_deg",
    "start_z_mm",
    "apodization_type",
    "apodization_factor",
    "apodization_factor_x",
    "apodization_factor_y",
    "sampling_role",
    "apply_surface_physics",
    "environment_temperature_c",
    "include_group_delay",
}



class GeometricPipeline:


    def evaluate(
        self,
        *,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
        context: Any | None = None,
    ) -> EnginePartialResult:


        result = EnginePartialResult.empty()
        for spec in analyses:
            definition = DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name)
            if definition.category is not AnalysisCategory.GEOMETRIC:
                raise ValueError(f"analysis {spec.name!r} is not geometric")

            trace = None
            if definition.requires_trace:
                trace_options = self._trace_options_for(
                    analyses=[spec], global_options=global_options
                )
                trace = self._trace(system, trace_options, context=context)
                result.merge(self._trace_summary(trace, include_arrays=definition.executor == "geometric_raytrace"))

            executor = definition.executor
            if executor == "geometric_raytrace":
                continue
            if executor == "geometric_spot":
                result.merge(self._evaluate_spot(trace=trace, analyses=[spec], global_options=global_options))
            elif executor == "geometric_throughput":
                result.merge(self._evaluate_throughput(trace))
            elif executor == "geometric_power_audit":
                result.merge(self._evaluate_power_audit(trace=trace, system=system, analyses=[spec], global_options=global_options))
            elif executor == "geometric_focus_search":
                result.merge(self._evaluate_focus_search(trace=trace, analyses=[spec], global_options=global_options))
            elif executor == "geometric_ghost_stray_light":
                result.merge(self._evaluate_ghost_stray_light(system=system, analyses=[spec], global_options=global_options))
            elif executor == "geometric_native":
                result.merge(self._run_native_geometric_analysis(name=spec.name, system=system, analyses=[spec], global_options=global_options))
            else:
                raise RuntimeError(f"unbound geometric executor: {executor!r}")
        return result

    def _trace_summary(self, trace: Any, *, include_arrays: bool) -> EnginePartialResult:
        partial = EnginePartialResult.empty()
        valid_mask = np.asarray(getattr(trace, "valid_mask", []), dtype=bool)
        total_ray_count = int(valid_mask.size)
        valid_ray_count = int(np.count_nonzero(valid_mask))
        partial.metrics.update({
            "ray_count": total_ray_count,
            "valid_ray_count": float(valid_ray_count),
            "valid_ray_ratio": valid_ray_count / total_ray_count if total_ray_count else 0.0,
        })
        partial.metadata["geometric_trace_done"] = True
        if not include_arrays:
            return partial
        partial.arrays.update({
            "raytrace_final_positions_mm": np.asarray(trace.final_positions_mm).tolist(),
            "raytrace_final_directions": np.asarray(trace.final_directions).tolist(),
            "raytrace_valid_mask": valid_mask.tolist(),
            "raytrace_optical_paths_mm": np.asarray(trace.optical_paths_mm, dtype=float).tolist(),
            "raytrace_integration_weights": np.asarray(trace.integration_weights, dtype=float).tolist(),
            "raytrace_field_amplitudes": np.asarray(trace.field_amplitudes, dtype=float).tolist(),
            "raytrace_power_weights": np.asarray(trace.power_weights, dtype=float).tolist(),
            "raytrace_quadrature_weights": np.asarray(trace.quadrature_weights, dtype=float).tolist(),
        })
        for key, attr in (
            ("raytrace_ray_ids", "ray_ids"),
            ("raytrace_pupil_coordinates_normalized", "pupil_coordinates_normalized"),
            ("raytrace_status_codes", "status_codes"),
            ("raytrace_path_points_mm", "path_points_mm"),
            ("raytrace_path_offsets", "path_offsets"),
            ("raytrace_path_surface_indices", "path_surface_indices"),
            ("raytrace_segment_lengths_mm", "segment_lengths_mm"),
            ("raytrace_segment_refractive_indices", "segment_refractive_indices"),
            ("raytrace_segment_opl_mm", "segment_opl_mm"),
            ("raytrace_cumulative_opl_mm", "cumulative_opl_mm"),
        ):
            value = getattr(trace, attr, None)
            if value is not None:
                partial.arrays[key] = np.asarray(value).tolist()
        partial.arrays["raytrace_termination_reasons"] = list(getattr(trace, "termination_reasons", []) or [])
        return partial

    def _options_for(
        self,
        *,
        name: str,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> dict[str, Any]:
        options = dict(global_options.get("geometric", {}) or {})
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


        options = dict(global_options.get("geometric", {}) or {})

        for analysis in analyses:
            if analysis.name not in _TRACE_ANALYSES:
                continue
            for key, value in dict(analysis.options or {}).items():
                if key in _TRACE_OPTION_KEYS:
                    options[key] = value

        options["sampling_role"] = infer_sampling_role(
            (analysis.name for analysis in analyses), options
        )
        return options

    def _trace(self, system: Any, options: dict[str, Any], *, context: Any | None = None) -> Any:
        if context is not None:
            return context.get_or_create_trace(options)

        from optical_core.physics.geometric.operators.pupil_sampling import (
            sample_explicit_pupil_rays,
            sample_pupil_grid,
        )
        from optical_core.physics.geometric.solvers.batch_raytrace import (
            trace_ray_batch,
        )
        from optical_core.physics.geometric.solvers.trace_options import TraceOptions

        wavelength_nm = float(
            options.get("wavelength_nm", getattr(system, "wavelength_nm", 550.0))
        )
        pupil_sample_count = int(options.get("pupil_sample_count", 25))
        pupil_radius_mm = float(
            options.get("pupil_radius_mm", getattr(system, "pupil_radius_mm", 1.0))
        )

        explicit_samples = options.get("explicit_pupil_samples")
        common_kwargs = {
            "pupil_radius_mm": pupil_radius_mm,
            "wavelength_nm": wavelength_nm,
            "source_model": str(options.get("source_model", "parallel_pupil")),
            "object_distance_mm": options.get("object_distance_mm", None),
            "object_space_na": options.get("object_space_na", None),
            "apodization_type": options.get("apodization_type", None),
            "apodization_factor": options.get("apodization_factor", None),
            "apodization_factor_x": options.get("apodization_factor_x", None),
            "apodization_factor_y": options.get("apodization_factor_y", None),
            "include_source_to_pupil_opl": bool(options.get("include_source_to_pupil_opl", False)),
            "start_z_mm": float(options.get("start_z_mm", -1.0e-6)),
            "field_x_deg": float(options.get("field_x_deg", 0.0)),
            "field_y_deg": float(options.get("field_y_deg", 0.0)),
        }
        if explicit_samples is not None:
            rays = sample_explicit_pupil_rays(
                samples=explicit_samples,
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
            record_surfaces=bool(options.get("record_surfaces", False)),
            propagate_to_image=bool(options.get("propagate_to_image", True)),
            evaluate_apertures=bool(options.get("evaluate_apertures", True)),
            max_intersection_iterations=int(
                options.get("max_intersection_iterations", 12)
            ),
            apply_surface_physics=bool(options.get("apply_surface_physics", True)),
            environment_temperature_c=float(options.get("environment_temperature_c", 20.0)),
            include_group_delay=bool(options.get("include_group_delay", False)),
        )

        return trace_ray_batch(system, rays, trace_options)


    def _evaluate_ghost_stray_light(
        self,
        *,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:

        from optical_core.models.representations.ray import Ray
        from optical_core.physics.geometric.operators.pupil_sampling import sample_pupil_grid
        from optical_core.physics.nonsequential import RayTreeOptions, trace_ray_tree

        opts = self._options_for(name="ghost_stray_light", analyses=analyses, global_options=global_options)
        wavelength_nm = float(opts.get("wavelength_nm", getattr(system, "wavelength_nm", 550.0)))
        sample_count = int(opts.get("pupil_sample_count", 9))
        sampled = sample_pupil_grid(
            pupil_radius_mm=float(opts.get("pupil_radius_mm", getattr(system, "pupil_radius_mm", 1.0))),
            sample_count=sample_count,
            wavelength_nm=wavelength_nm,
            start_z_mm=float(opts.get("start_z_mm", -1.0e-6)),
        )
        options = RayTreeOptions(
            max_interactions=int(opts.get("max_interactions", 12)),
            max_reflections=int(opts.get("max_reflections", 4)),
            max_nodes=int(opts.get("max_nodes", 4096)),
            min_power_fraction=float(opts.get("min_power_fraction", 1.0e-8)),
            russian_roulette=bool(opts.get("use_russian_roulette", opts.get("russian_roulette", False))),
            roulette_threshold_fraction=float(opts.get("roulette_threshold_fraction", 1.0e-5)),
            random_seed=int(opts.get("random_seed", 0)),
            detector_z_mm=opts.get("detector_z_mm", None),
            environment_temperature_c=float(opts.get("environment_temperature_c", 20.0)),
            include_diffraction_orders=bool(opts.get("include_diffraction_orders", True)),
        )
        trees = []
        for position, direction, valid, amplitude, power in zip(
            sampled.positions_mm, sampled.directions, sampled.valid_mask, sampled.field_amplitudes, sampled.power_weights, strict=True
        ):
            if not bool(valid):
                continue
            trees.append(trace_ray_tree(system, Ray(
                position_mm=tuple(position), direction=tuple(direction), wavelength_nm=wavelength_nm,
                field_amplitude=float(amplitude), power_weight=float(power),
            ), options))
        partial = EnginePartialResult.empty()
        root_power = float(sum(tree.root_power for tree in trees))
        primary = float(sum(tree.metrics["ray_tree_primary_power"] for tree in trees))
        ghost = float(sum(tree.metrics["ray_tree_total_ghost_power"] for tree in trees))
        detector = float(sum(tree.metrics["ray_tree_detector_power"] for tree in trees))
        partial.metrics.update({
            "ghost_input_ray_count": len(trees),
            "ghost_root_power": root_power,
            "ghost_primary_power": primary,
            "ghost_total_stray_power": ghost,
            "ghost_detector_power": detector,
            "ghost_to_primary_ratio": ghost / max(primary, 1e-30),
            "ghost_detector_throughput": detector / max(root_power, 1e-30),
        })
        ranked = []
        for ray_index, tree in enumerate(trees):
            for signature, sequence, power_value, opl, x, y in zip(
                tree.arrays["ray_tree_path_signature"], tree.arrays["ray_tree_surface_sequence"],
                tree.arrays["ray_tree_path_power"], tree.arrays["ray_tree_optical_path_mm"],
                tree.arrays["ray_tree_detector_x_mm"], tree.arrays["ray_tree_detector_y_mm"], strict=True
            ):
                ranked.append((float(power_value), ray_index, signature, sequence, float(opl), float(x), float(y)))
        ranked.sort(reverse=True, key=lambda row: row[0])
        limit = int(opts.get("return_top_paths", 50))
        selected = ranked[:limit]
        partial.arrays.update({
            "ghost_path_power": [row[0] for row in selected],
            "ghost_path_input_ray_index": [row[1] for row in selected],
            "ghost_path_signature": [row[2] for row in selected],
            "ghost_path_surface_sequence": [row[3] for row in selected],
            "ghost_path_optical_path_mm": [row[4] for row in selected],
            "ghost_path_detector_x_mm": [row[5] for row in selected],
            "ghost_path_detector_y_mm": [row[6] for row in selected],
        })
        partial.metadata.update({
            "ghost_solver": "native_bidirectional_ray_tree",
            "ghost_geometry": "ordered_surface_stack_with_bidirectional_reflections",
            "zemax_data_used_as_input": False,
            "reference_data_used_as_input": False,
        })
        for tree in trees:
            partial.warnings.extend(tree.warnings)
        return partial

    def _evaluate_spot(
        self,
        *,
        trace: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        from optical_core.physics.geometric.analyses.spot import evaluate_spot
        from optical_core.physics.geometric.analyses.spot.options import SpotAnalysisOptions

        opts = self._options_for(name="spot", analyses=analyses, global_options=global_options)
        options = SpotAnalysisOptions(
            output_unit=str(opts.get("output_unit", "um")),
            wavelength_nm=opts.get("wavelength_nm", None),
            numerical_aperture=opts.get("numerical_aperture", opts.get("na", None)),
            f_number=opts.get("f_number", opts.get("fno", None)),
            focal_length_mm=opts.get("focal_length_mm", None),
            aperture_diameter_mm=opts.get("aperture_diameter_mm", None),
            refractive_index=float(opts.get("refractive_index", 1.0)),
            include_real_ray_airy=bool(opts.get("include_real_ray_airy", True)),
        )
        partial = _to_partial_result(evaluate_spot(trace, options))
        partial.metadata["spot_done"] = True
        return partial

    def _evaluate_throughput(self, trace: Any) -> EnginePartialResult:
        from optical_core.physics.geometric.analyses.throughput import (
            evaluate_throughput,
        )

        return _to_partial_result(evaluate_throughput(trace))

    def _evaluate_power_audit(
        self,
        *,
        trace: Any,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        from optical_core.physics.geometric.analyses.power_audit import (
            evaluate_power_audit,
        )

        options = self._options_for(
            name="power_audit",
            analyses=analyses,
            global_options=global_options,
        )
        partial = _to_partial_result(evaluate_power_audit(trace, system, options))
        partial.metadata["power_audit_done"] = True
        return partial

    def _evaluate_focus_search(
        self,
        *,
        trace: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        from optical_core.physics.geometric.analyses.focus_search import (
            evaluate_focus_search,
        )

        options = self._options_for(
            name="focus_search",
            analyses=analyses,
            global_options=global_options,
        )
        partial = _to_partial_result(evaluate_focus_search(trace, options))
        partial.metadata["focus_search_done"] = True
        return partial

    def _run_native_geometric_analysis(
        self,
        *,
        name: str,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        options = self._options_for(
            name=name,
            analyses=analyses,
            global_options=global_options,
        )

        if name == "first_order":
            from optical_core.physics.geometric.analyses.first_order import (
                evaluate_first_order,
            )

            raw = evaluate_first_order(system, options)

        elif name == "chromatic":
            from optical_core.physics.geometric.analyses.chromatic import (
                evaluate_chromatic,
            )

            raw = evaluate_chromatic(system, options)

        elif name == "ray_fan":
            from optical_core.physics.geometric.analyses.ray_fan import (
                evaluate_ray_fan,
            )

            raw = evaluate_ray_fan(system, options)

        elif name == "field_curvature":
            from optical_core.physics.geometric.analyses.field_curvature import (
                evaluate_field_curvature,
            )

            raw = evaluate_field_curvature(system, options)

        elif name == "distortion":
            from optical_core.physics.geometric.analyses.distortion import (
                evaluate_distortion,
            )

            raw = evaluate_distortion(system, options)

        elif name == "seidel":
            from optical_core.physics.geometric.analyses.seidel import evaluate_seidel

            raw = evaluate_seidel(system, options)

        elif name == "material_transmission":
            from optical_core.physics.geometric.analyses.material_transmission import (
                evaluate_material_transmission,
            )

            raw = evaluate_material_transmission(system, options)

        else:
            partial = EnginePartialResult.empty()
            partial.warnings.append(f"Unsupported native geometric analysis: {name}")
            return partial

        partial = _to_partial_result(raw)
        partial.metadata[f"{name}_done"] = True
        return partial


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
            result.metrics.update(raw)
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
