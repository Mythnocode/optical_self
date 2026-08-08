from __future__ import annotations

from dataclasses import fields
from typing import Any, Callable

from .analysis_mapper import AnalysisSpec
from .analysis_registry import AnalysisCategory, DEFAULT_ANALYSIS_REGISTRY
from .result_merger import EnginePartialResult

from optical_core.physics.wave.solvers.propagation_options import PropagationOptions




class WavePipeline:


    def evaluate(
        self,
        *,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:


        result = EnginePartialResult.empty()
        for spec in analyses:
            definition = DEFAULT_ANALYSIS_REGISTRY.resolve(spec.name)
            if definition.category is not AnalysisCategory.WAVE:
                raise ValueError(f"analysis {spec.name!r} is not wave")
            if definition.executor == "wave_propagation":
                partial = self._run_propagation_analysis(spec.name, system, [spec], global_options)
            elif definition.executor == "wave_option_dataclass":
                partial = self._run_option_dataclass_analysis(spec.name, system, [spec], global_options)
            elif definition.executor == "wave_formula":
                partial = self._run_formula_analysis(spec.name, system, [spec], global_options)
            else:
                raise RuntimeError(f"unbound wave executor: {definition.executor!r}")
            result.merge(partial)
        return result

    def _options_for(
        self,
        *,
        group: str,
        name: str,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> dict[str, Any]:
        options = dict(global_options.get(group, {}) or {})

        for analysis in analyses:
            if analysis.name == name:
                options.update(dict(analysis.options or {}))

        return options

    def _propagation_options(
        self,
        *,
        name: str,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> PropagationOptions:
        opts = self._options_for(
            group="wave",
            name=name,
            analyses=analyses,
            global_options=global_options,
        )

        return PropagationOptions(
            wavelength_nm=float(opts.get("wavelength_nm", getattr(system, "wavelength_nm", 550.0))),
            refractive_index=float(opts.get("refractive_index", 1.0)),
            grid_size=int(opts.get("grid_size", 65)),
            extent_mm=float(opts.get("extent_mm", 1.0)),
            propagation_distance_mm=float(opts.get("propagation_distance_mm", opts.get("distance_mm", 50.0))),
            method=str(opts.get("method", "fraunhofer")),
            aperture_type=str(opts.get("aperture_type", "circular")),
            aperture_diameter_mm=float(opts.get("aperture_diameter_mm", 0.5)),
            aperture_width_mm=float(opts.get("aperture_width_mm", 0.5)),
            aperture_height_mm=float(opts.get("aperture_height_mm", 0.5)),
            slit_width_mm=float(opts.get("slit_width_mm", 0.1)),
            gaussian_waist_mm=float(opts.get("gaussian_waist_mm", 0.25)),
            normalize=bool(opts.get("normalize", True)),
            zero_padding_factor=float(opts.get("zero_padding_factor", 2.0)),
            edge_power_threshold=float(opts.get("edge_power_threshold", 1.0e-4)),
            energy_closure_threshold=float(
                opts.get("energy_closure_threshold", 5.0e-3)
            ),
            nyquist_margin_min=float(opts.get("nyquist_margin_min", 1.0)),
        )

    def _run_propagation_analysis(
        self,
        name: str,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        options = self._propagation_options(
            name=name,
            system=system,
            analyses=analyses,
            global_options=global_options,
        )

        if name in {"diffraction", "scalar_diffraction"}:
            from optical_core.physics.wave.analyses.diffraction import evaluate_diffraction

            raw = evaluate_diffraction(options)
            partial = _to_partial_result(raw)
            partial.metadata["diffraction_done"] = True
            return partial

        if name == "psf":
            from optical_core.physics.wave.analyses.psf import evaluate_psf

            raw = evaluate_psf(options)
            partial = _to_partial_result(raw)
            partial.metadata["psf_done"] = True
            return partial

        if name == "mtf":
            from optical_core.physics.wave.analyses.mtf import evaluate_mtf

            raw = evaluate_mtf(options)
            partial = _to_partial_result(raw)
            partial.metadata["mtf_done"] = True
            return partial

        if name == "wavefront":
            from optical_core.physics.wave.analyses.diffraction import evaluate_diffraction
            from optical_core.physics.wave.analyses.wavefront import evaluate_wavefront

            diffraction = evaluate_diffraction(options)
            raw = evaluate_wavefront(diffraction.phase_rad, diffraction.field.wavelength_nm)
            partial = _to_partial_result(raw)
            partial.metadata["wavefront_done"] = True
            return partial

        partial = EnginePartialResult.empty()
        partial.warnings.append(f"Unsupported propagation wave analysis: {name}")
        return partial

    def _run_option_dataclass_analysis(
        self,
        name: str,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        opts = self._options_for(
            group="wave",
            name=name,
            analyses=analyses,
            global_options=global_options,
        )

        if name == "interference":
            from optical_core.physics.wave.analyses.interference import (
                InterferenceAnalysisOptions,
                evaluate_interference,
            )

            opts.setdefault("wavelength_nm", getattr(system, "wavelength_nm", 550.0))
            raw = evaluate_interference(InterferenceAnalysisOptions(**_dataclass_kwargs(opts, InterferenceAnalysisOptions)))

        elif name == "coherence":
            from optical_core.physics.wave.analyses.coherence import (
                CoherenceAnalysisOptions,
                evaluate_coherence,
            )

            opts.setdefault("center_wavelength_nm", getattr(system, "wavelength_nm", 550.0))
            raw = evaluate_coherence(CoherenceAnalysisOptions(**_dataclass_kwargs(opts, CoherenceAnalysisOptions)))

        elif name == "polarization":
            from optical_core.physics.wave.analyses.polarization import (
                PolarizationAnalysisOptions,
                evaluate_polarization,
            )

            raw = evaluate_polarization(PolarizationAnalysisOptions(**_dataclass_kwargs(opts, PolarizationAnalysisOptions)))

        else:
            partial = EnginePartialResult.empty()
            partial.warnings.append(f"Unsupported option-dataclass wave analysis: {name}")
            return partial

        partial = _to_partial_result(raw)
        partial.metadata[f"{name}_done"] = True
        return partial

    def _run_formula_analysis(
        self,
        name: str,
        system: Any,
        analyses: list[AnalysisSpec],
        global_options: dict[str, Any],
    ) -> EnginePartialResult:
        from optical_core.physics.wave.analyses import formula_suite

        opts = self._options_for(
            group="wave",
            name=name,
            analyses=analyses,
            global_options=global_options,
        )
        opts.setdefault("wavelength_nm", getattr(system, "wavelength_nm", 550.0))

        evaluator = _formula_evaluator(name, formula_suite)
        raw = evaluator(opts)
        partial = _to_partial_result(raw)
        partial.metadata[f"{name}_done"] = True
        partial.metadata["wave_formula_suite"] = True
        return partial


def _formula_evaluator(name: str, formula_suite: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    if name == "grating":
        return formula_suite.evaluate_grating

    if name == "material_index":
        return formula_suite.evaluate_material_index

    if name in {
        "fresnel_interface",
        "polarized_interface",
        "polarized_interfaces",
        "polarized_fresnel",
        "fresnel_jones",
    }:
        return formula_suite.evaluate_fresnel_interface

    if name == "thin_film":
        return formula_suite.evaluate_thin_film

    if name == "fabry_perot":
        return formula_suite.evaluate_fabry_perot

    if name in {
        "fourier_optics",
        "fourier_transform",
        "fraunhofer_diffraction",
        "fresnel_propagation",
        "angular_spectrum",
        "coherent_imaging",
        "spatial_filtering",
        "fourier_psf_mtf",
    }:
        return formula_suite.evaluate_fourier_transform

    if name in {
        "birefringence",
        "uniaxial_crystal",
        "crystal_retardance",
        "waveplate_from_crystal",
        "effective_extraordinary_index",
        "ordinary_extraordinary_split",
        "crystal_summary",
    }:
        return formula_suite.evaluate_birefringence

    if name in {
        "polarization_diagnostics",
        "analyzer_scan_diagnostics",
        "malus_fit",
        "stokes_from_scan",
        "polarization_state_compare",
        "stokes_error",
        "polarization_ellipse_diagnostics",
    }:
        return formula_suite.evaluate_polarization_diagnostics

    if name in {
        "polarization_interference",
        "two_beam_polarization_interference",
        "polarization_phase_scan",
        "young_polarization_interference",
        "analyzer_restored_interference",
        "polarization_complementarity",
    }:
        return formula_suite.evaluate_polarization_interference

    raise NotImplementedError(f"未绑定波动公式分析: {name}")


def _dataclass_kwargs(options: dict[str, Any], cls: type) -> dict[str, Any]:
    valid = {item.name for item in fields(cls)}
    return {key: value for key, value in options.items() if key in valid}


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
