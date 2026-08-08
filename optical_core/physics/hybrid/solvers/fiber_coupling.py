from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import OrderedDict
from threading import RLock
import math
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.models.representations.vector_field import VectorField2D, lift_scalar_field_to_jones
from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.operators.field_overlap import normalized_field_overlap
from optical_core.physics.hybrid.operators.overlap_decomposition import decompose_scalar_overlap
from optical_core.physics.hybrid.operators.vector_overlap import normalized_vector_overlap
from optical_core.physics.fiber_modes.solver import solve_finite_difference_mode, solve_he11_vector_mode
from optical_core.physics.wave.solvers.vector_debye import vectorial_debye_focus
from optical_core.physics.hybrid.operators.fiber_mode import (
    StepIndexFiberSpec,
    gaussian_fiber_mode,
    solve_step_index_fiber_mode,
    step_index_lp01_mode,
)
from optical_core.physics.hybrid.solvers.cartesian_pupil_propagation import (
    CartesianPupilPropagationResult,
    PreparedCartesianPupil,
    prepare_cartesian_pupil_propagation,
    propagate_prepared_cartesian_pupil,
)
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions


@dataclass(slots=True)
class FiberCouplingSolverResult:
    efficiency: float
    overlap: complex
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_efficiency(self) -> float:

        return float(self.metrics.get("total_coupling_efficiency", self.efficiency))

    @property
    def field_overlap_efficiency(self) -> float:
        return float(self.metrics.get("complex_field_overlap_efficiency", self.efficiency))


class CouplingNumericalGateError(RuntimeError):


    code = "COUPLING_NUMERICAL_GATE_FAILED"
    stage = "optical_core.physics.hybrid.coupling"
    retryable = False

    def __init__(self, failures: list[str], metrics: dict[str, Any]) -> None:
        self.context = {
            "failed_gates": list(failures),
            "edge_power_fraction": metrics.get("propagation_edge_power_fraction"),
            "energy_closure_error": metrics.get("propagation_energy_closure_error"),
            "nyquist_margin_min": metrics.get("propagation_nyquist_margin_min"),
            "sampling_pass": metrics.get("coupling_propagation_sampling_pass"),
            "aliasing_risk": metrics.get("coupling_propagation_aliasing_risk"),
            "preflight_sampling_pass": metrics.get("coupling_propagation_preflight_sampling_pass"),
            "preflight_aliasing_risk": metrics.get("coupling_propagation_preflight_aliasing_risk"),
            "required_grid_size": metrics.get("coupling_propagation_required_grid_size"),
            "required_window_mm": metrics.get("coupling_propagation_required_window_mm"),
            "required_padding_factor": metrics.get("coupling_propagation_required_padding_factor"),
            "sampling_convergence_pass": metrics.get("sampling_convergence_pass"),
            "output_grid_size": metrics.get("coupling_output_final_grid_size"),
            "auto_expand_steps": metrics.get("coupling_output_auto_expand_steps"),
        }
        joined = ", ".join(failures)
        super().__init__(
            "Coupling propagation numerical gate failed before overlap/tolerance evaluation: "
            f"{joined}. Expand the receiver window or increase sampling before using this result."
        )


def _enforce_propagation_gates(
    result: CartesianPupilPropagationResult,
    options: CouplingOptions,
) -> None:
    if not bool(options.enforce_numerical_gates):
        return
    metrics = result.metrics
    failures: list[str] = []
    if not bool(metrics.get("coupling_propagation_edge_pass", False)):
        failures.append("receiver_window_edge_power")
    if not bool(metrics.get("coupling_propagation_energy_pass", False)):
        failures.append("propagation_energy_closure")
    if not bool(metrics.get("coupling_propagation_nyquist_pass", False)):
        failures.append("propagation_nyquist_margin")
    
    
    
    
    if bool(options.sampling_convergence_enabled) and not bool(
        metrics.get("sampling_convergence_pass", False)
    ):
        failures.append("sampling_convergence")
    if failures:
        raise CouplingNumericalGateError(failures, metrics)


@dataclass(frozen=True, slots=True)
class PreparedCouplingEvaluation:
    efficiency: float
    overlap: complex
    receiver_field: ScalarField2D
    receiving_mode: ScalarField2D
    field_result: CartesianPupilPropagationResult


@dataclass(slots=True)
class PreparedCouplingProblem:


    trace: TraceBundle
    options: CouplingOptions
    prepared_pupil: PreparedCartesianPupil
    fiber_metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    field_cache: OrderedDict[float, CartesianPupilPropagationResult] = field(default_factory=OrderedDict)
    mode_cache: OrderedDict[tuple[Any, ...], ScalarField2D] = field(default_factory=OrderedDict)
    evaluation_cache: OrderedDict[tuple[Any, ...], PreparedCouplingEvaluation] = field(default_factory=OrderedDict)
    field_cache_max_entries: int = 32
    mode_cache_max_entries: int = 256
    evaluation_cache_max_entries: int = 1024
    evaluation_count: int = 0
    evaluation_cache_hits: int = 0
    field_propagation_count: int = 0
    field_cache_hits: int = 0
    mode_build_count: int = 0
    mode_cache_hits: int = 0
    field_cache_evictions: int = 0
    mode_cache_evictions: int = 0
    evaluation_cache_evictions: int = 0

    @classmethod
    def prepare(cls, trace: TraceBundle, options: CouplingOptions) -> "PreparedCouplingProblem":
        resolved, fiber_metrics, fiber_warnings = resolve_fiber_mode_options(options)
        prepared = prepare_cartesian_pupil_propagation(trace, resolved)
        problem = cls(
            trace=trace,
            options=resolved,
            prepared_pupil=prepared,
            fiber_metrics=fiber_metrics,
            warnings=[*fiber_warnings, *prepared.warnings],
        )
        problem.receiver_field(resolved.receiver_axial_offset_z_mm)
        return problem

    @staticmethod
    def _q(value: float, quantum: float) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("prepared coupling coordinates must be finite")
        return float(round(value / quantum) * quantum)

    @staticmethod
    def _lru_get(cache: OrderedDict[Any, Any], key: Any) -> Any | None:
        try:
            value = cache.pop(key)
        except KeyError:
            return None
        cache[key] = value
        return value

    @staticmethod
    def _lru_put(cache: OrderedDict[Any, Any], key: Any, value: Any, max_entries: int) -> int:
        cache.pop(key, None)
        cache[key] = value
        evicted = 0
        while len(cache) > max(int(max_entries), 1):
            cache.popitem(last=False)
            evicted += 1
        return evicted

    def receiver_field(self, axial_offset_z_mm: float) -> CartesianPupilPropagationResult:
        axial = float(axial_offset_z_mm)
        if not math.isfinite(axial):
            raise ValueError("receiver_axial_offset_z_mm must be finite")
        key = self._q(axial, 1.0e-6)
        cached = self._lru_get(self.field_cache, key)
        if cached is not None:
            self.field_cache_hits += 1
            return cached
        result = propagate_prepared_cartesian_pupil(
            self.prepared_pupil,
            replace(self.options, receiver_axial_offset_z_mm=axial),
        )
        _enforce_propagation_gates(result, self.options)
        self.field_cache_evictions += self._lru_put(
            self.field_cache, key, result, self.field_cache_max_entries
        )
        self.field_propagation_count += 1
        return result

    def receiving_mode(
        self,
        field_obj: ScalarField2D,
        *,
        offset_x_mm: float,
        offset_y_mm: float,
        tilt_x_rad: float,
        tilt_y_rad: float,
        mode_field_diameter_x_um: float | None = None,
        mode_field_diameter_y_um: float | None = None,
    ) -> ScalarField2D:
        values = np.asarray(
            [offset_x_mm, offset_y_mm, tilt_x_rad, tilt_y_rad], dtype=float
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("receiver mode offset and tilt values must be finite")
        mfd_x = float(
            self.options.mode_field_diameter_x_um
            if mode_field_diameter_x_um is None
            else mode_field_diameter_x_um
        )
        mfd_y = float(
            self.options.mode_field_diameter_y_um
            if mode_field_diameter_y_um is None
            else mode_field_diameter_y_um
        )
        if not (math.isfinite(mfd_x) and math.isfinite(mfd_y) and mfd_x > 0.0 and mfd_y > 0.0):
            raise ValueError("mode field diameters must be positive and finite")
        key = (
            id(field_obj.grid),
            str(self.options.mode_model),
            self._q(offset_x_mm, 1.0e-6),
            self._q(offset_y_mm, 1.0e-6),
            self._q(tilt_x_rad, 1.0e-9),
            self._q(tilt_y_rad, 1.0e-9),
            self._q(mfd_x, 1.0e-6),
            self._q(mfd_y, 1.0e-6),
        )
        cached = self._lru_get(self.mode_cache, key)
        if cached is not None:
            self.mode_cache_hits += 1
            return cached
        mode = build_receiving_mode(
            field_obj,
            replace(
                self.options,
                offset_x_mm=float(offset_x_mm),
                offset_y_mm=float(offset_y_mm),
                tilt_x_rad=float(tilt_x_rad),
                tilt_y_rad=float(tilt_y_rad),
                mode_field_diameter_x_um=mfd_x,
                mode_field_diameter_y_um=mfd_y,
            ),
        )
        mode_power = float(mode.integrated_power)
        if not math.isfinite(mode_power):
            raise ValueError("receiving mode has non-finite power")
        self.mode_cache_evictions += self._lru_put(
            self.mode_cache, key, mode, self.mode_cache_max_entries
        )
        self.mode_build_count += 1
        return mode

    def evaluate(
        self,
        *,
        offset_x_mm: float | None = None,
        offset_y_mm: float | None = None,
        receiver_axial_offset_z_mm: float | None = None,
        tilt_x_rad: float | None = None,
        tilt_y_rad: float | None = None,
        mode_field_diameter_x_um: float | None = None,
        mode_field_diameter_y_um: float | None = None,
    ) -> PreparedCouplingEvaluation:
        values = (
            float(self.options.offset_x_mm if offset_x_mm is None else offset_x_mm),
            float(self.options.offset_y_mm if offset_y_mm is None else offset_y_mm),
            float(self.options.receiver_axial_offset_z_mm if receiver_axial_offset_z_mm is None else receiver_axial_offset_z_mm),
            float(self.options.tilt_x_rad if tilt_x_rad is None else tilt_x_rad),
            float(self.options.tilt_y_rad if tilt_y_rad is None else tilt_y_rad),
            float(self.options.mode_field_diameter_x_um if mode_field_diameter_x_um is None else mode_field_diameter_x_um),
            float(self.options.mode_field_diameter_y_um if mode_field_diameter_y_um is None else mode_field_diameter_y_um),
        )
        if not np.all(np.isfinite(np.asarray(values, dtype=float))):
            raise ValueError("prepared coupling evaluation parameters must be finite")
        if values[5] <= 0.0 or values[6] <= 0.0:
            raise ValueError("mode field diameters must be positive")
        quanta = (1.0e-6, 1.0e-6, 1.0e-6, 1.0e-9, 1.0e-9, 1.0e-6, 1.0e-6)
        key = tuple(self._q(value, quantum) for value, quantum in zip(values, quanta, strict=True))
        cached = self._lru_get(self.evaluation_cache, key)
        if cached is not None:
            self.evaluation_cache_hits += 1
            return cached

        field_result = self.receiver_field(values[2])
        field_power = float(field_result.field.integrated_power)
        if not math.isfinite(field_power):
            raise ValueError("receiver field has non-finite power")
        mode = self.receiving_mode(
            field_result.field,
            offset_x_mm=values[0],
            offset_y_mm=values[1],
            tilt_x_rad=values[3],
            tilt_y_rad=values[4],
            mode_field_diameter_x_um=values[5],
            mode_field_diameter_y_um=values[6],
        )
        mode_power = float(mode.integrated_power)
        if field_power <= 1.0e-30 or mode_power <= 1.0e-30:
            overlap = 0.0 + 0.0j
            efficiency = 0.0
        else:
            overlap = normalized_field_overlap(field_result.field, mode)
            efficiency = float(abs(overlap) ** 2)
        if not math.isfinite(efficiency):
            raise FloatingPointError("coupling overlap produced non-finite efficiency")
        if efficiency < -1.0e-12 or efficiency > 1.0 + 1.0e-8:
            raise FloatingPointError(f"coupling efficiency outside [0, 1]: {efficiency}")
        efficiency = min(max(efficiency, 0.0), 1.0)
        evaluation = PreparedCouplingEvaluation(
            efficiency=efficiency,
            overlap=overlap,
            receiver_field=field_result.field,
            receiving_mode=mode,
            field_result=field_result,
        )
        self.evaluation_cache_evictions += self._lru_put(
            self.evaluation_cache, key, evaluation, self.evaluation_cache_max_entries
        )
        self.evaluation_count += 1
        return evaluation

    def efficiency(self, **kwargs: float) -> float:
        return float(self.evaluate(**kwargs).efficiency)

    def clear_transient_caches(self, *, keep_axial_offsets: tuple[float, ...] = ()) -> None:
        keep: OrderedDict[float, CartesianPupilPropagationResult] = OrderedDict()
        for axial in keep_axial_offsets:
            key = self._q(float(axial), 1.0e-6)
            cached = self.field_cache.get(key)
            if cached is not None:
                keep[key] = cached
        self.field_cache.clear()
        self.field_cache.update(keep)
        self.mode_cache.clear()
        self.evaluation_cache.clear()

    def cache_metrics(self) -> dict[str, Any]:
        from optical_core.physics.wave.solvers.advanced_propagation import propagation_spectrum_cache_info
        spectrum = propagation_spectrum_cache_info()
        return {
            "prepared_coupling_evaluation_count": int(self.evaluation_count),
            "prepared_coupling_evaluation_cache_hits": int(self.evaluation_cache_hits),
            "prepared_coupling_field_propagation_count": int(self.field_propagation_count),
            "prepared_coupling_field_cache_hits": int(self.field_cache_hits),
            "prepared_coupling_mode_build_count": int(self.mode_build_count),
            "prepared_coupling_mode_cache_hits": int(self.mode_cache_hits),
            "prepared_coupling_field_cache_size": len(self.field_cache),
            "prepared_coupling_mode_cache_size": len(self.mode_cache),
            "prepared_coupling_evaluation_cache_size": len(self.evaluation_cache),
            "prepared_coupling_field_cache_max_entries": int(self.field_cache_max_entries),
            "prepared_coupling_mode_cache_max_entries": int(self.mode_cache_max_entries),
            "prepared_coupling_evaluation_cache_max_entries": int(self.evaluation_cache_max_entries),
            "prepared_coupling_field_cache_evictions": int(self.field_cache_evictions),
            "prepared_coupling_mode_cache_evictions": int(self.mode_cache_evictions),
            "prepared_coupling_evaluation_cache_evictions": int(self.evaluation_cache_evictions),
            "prepared_coupling_prepared_pupil_fingerprint": self.prepared_pupil.fingerprint,
            "RayTraceCache_reused_trace": True,
            "PupilFieldCache_size": 1,
            "PropagationSpectrumCache_hits": spectrum["hits"],
            "PropagationSpectrumCache_misses": spectrum["misses"],
            "PropagationSpectrumCache_size": spectrum["currsize"],
            "FiberModeCache_size": len(self.mode_cache),
            "GlobalFiberModeCache_hits": global_fiber_mode_cache_info()["hits"],
            "GlobalFiberModeCache_misses": global_fiber_mode_cache_info()["misses"],
            "GlobalFiberModeCache_size": global_fiber_mode_cache_info()["currsize"],
            "ToleranceOperatorCache_size": len(self.evaluation_cache),
        }


def resolve_fiber_mode_options(
    options: CouplingOptions,
) -> tuple[CouplingOptions, dict[str, Any], list[str]]:


    metrics: dict[str, Any] = {}
    warnings: list[str] = []
    if str(options.mode_model) == "finite_difference":
        return options, metrics, warnings
    if str(options.mode_model) == "imported":
        return options, metrics, warnings
    if (
        options.fiber_core_radius_um is None
        or options.fiber_n_core is None
        or options.fiber_n_clad is None
    ):
        if str(options.mode_model) in {"lp01", "he11"}:
            warnings.append(
                "LP01/HE11 mode requested without core radius/n_core/n_clad; Gaussian mode was used."
            )
            options = replace(options, mode_model="gaussian")
        return options, metrics, warnings

    solution = solve_step_index_fiber_mode(
        StepIndexFiberSpec(
            core_radius_um=float(options.fiber_core_radius_um),
            n_core=float(options.fiber_n_core),
            n_clad=float(options.fiber_n_clad),
            wavelength_nm=float(options.wavelength_nm),
            length_m=float(options.fiber_length_m),
            attenuation_db_per_km=float(options.fiber_attenuation_db_per_km),
            connector_loss_db=float(options.fiber_connector_loss_db),
            outside_index=float(options.receiver_medium_refractive_index),
        )
    )
    metrics.update(solution.metrics)
    warnings.extend(solution.warnings)
    
    
    
    
    
    if str(options.mode_model) == "gaussian":
        metrics.update(
            {
                "fiber_gaussian_mfd_source": "explicit_solver_options",
                "fiber_material_mfd_x_um": float(solution.mfd_x_um),
                "fiber_material_mfd_y_um": float(solution.mfd_y_um),
            }
        )
        return options, metrics, warnings
    options = replace(
        options,
        mode_field_diameter_x_um=solution.mfd_x_um,
        mode_field_diameter_y_um=solution.mfd_y_um,
    )
    return options, metrics, warnings


def _transform_sampled_mode(field_obj: ScalarField2D, base_values: np.ndarray, options: CouplingOptions) -> ScalarField2D:
    from scipy.interpolate import RegularGridInterpolator

    values = np.asarray(base_values, dtype=np.complex128)
    if values.shape != field_obj.grid.shape:
        raise ValueError("sampled fiber mode/index-map result must match receiver grid")
    x, y = np.meshgrid(field_obj.grid.x_mm, field_obj.grid.y_mm, indexing="xy")
    axes = (np.asarray(field_obj.grid.y_mm), np.asarray(field_obj.grid.x_mm))
    points = np.column_stack([(y - float(options.offset_y_mm)).ravel(), (x - float(options.offset_x_mm)).ravel()])
    real = RegularGridInterpolator(axes, np.real(values), bounds_error=False, fill_value=0.0)
    imag = RegularGridInterpolator(axes, np.imag(values), bounds_error=False, fill_value=0.0)
    shifted = (real(points) + 1j * imag(points)).reshape(values.shape)
    wavelength_mm = float(options.wavelength_nm) * 1.0e-6
    k = 2.0 * np.pi * float(options.receiver_medium_refractive_index) / wavelength_mm
    shifted *= np.exp(1j * k * (float(options.tilt_x_rad) * (x - options.offset_x_mm) + float(options.tilt_y_rad) * (y - options.offset_y_mm)))
    return ScalarField2D(
        values=shifted, grid=field_obj.grid, wavelength_nm=options.wavelength_nm,
        refractive_index=options.receiver_medium_refractive_index, z_mm=field_obj.z_mm,
    ).normalized()


_GLOBAL_FIBER_MODE_CACHE_MAXSIZE = 64
_GLOBAL_FIBER_MODE_CACHE_MAX_BYTES = 192 * 1024**2
_global_fiber_mode_cache: OrderedDict[tuple[Any, ...], tuple[ScalarField2D, int]] = OrderedDict()
_global_fiber_mode_cache_bytes = 0
_global_fiber_mode_lock = RLock()
_global_fiber_mode_hits = 0
_global_fiber_mode_misses = 0


def _global_mode_key(field_obj: ScalarField2D, options: CouplingOptions) -> tuple[Any, ...] | None:
    model = str(options.mode_model)
    if model not in {"gaussian", "lp01", "he11"}:
        return None
    return (
        id(field_obj.grid), model, float(options.wavelength_nm),
        float(options.receiver_medium_refractive_index),
        float(options.mode_field_diameter_x_um), float(options.mode_field_diameter_y_um),
        float(options.offset_x_mm), float(options.offset_y_mm),
        float(options.tilt_x_rad), float(options.tilt_y_rad),
        None if options.fiber_core_radius_um is None else float(options.fiber_core_radius_um),
        None if options.fiber_n_core is None else float(options.fiber_n_core),
        None if options.fiber_n_clad is None else float(options.fiber_n_clad),
    )


def clear_global_fiber_mode_cache() -> None:
    global _global_fiber_mode_hits, _global_fiber_mode_misses, _global_fiber_mode_cache_bytes
    with _global_fiber_mode_lock:
        _global_fiber_mode_cache.clear()
        _global_fiber_mode_cache_bytes = 0
        _global_fiber_mode_hits = _global_fiber_mode_misses = 0


def global_fiber_mode_cache_info() -> dict[str, int]:
    with _global_fiber_mode_lock:
        return {
            "hits": int(_global_fiber_mode_hits),
            "misses": int(_global_fiber_mode_misses),
            "currsize": len(_global_fiber_mode_cache),
            "maxsize": _GLOBAL_FIBER_MODE_CACHE_MAXSIZE,
            "bytes": int(_global_fiber_mode_cache_bytes),
            "max_bytes": int(_GLOBAL_FIBER_MODE_CACHE_MAX_BYTES),
        }


def _build_receiving_mode_uncached(field_obj: ScalarField2D, options: CouplingOptions) -> ScalarField2D:
    if str(options.mode_model) == "imported":
        return _transform_sampled_mode(field_obj, np.asarray(options.imported_mode_values), options)
    if str(options.mode_model) == "finite_difference":
        solved = solve_finite_difference_mode(
            field_obj.grid, wavelength_nm=options.wavelength_nm,
            refractive_index_map=np.asarray(options.finite_difference_refractive_index_map, dtype=float),
            mode_count=int(options.fiber_mode_index) + 1, mode_index=int(options.fiber_mode_index),
            jones_vector=options.fiber_mode_jones_vector,
        )
        return _transform_sampled_mode(field_obj, solved.scalar_field.values, options)
    if (
        str(options.mode_model) in {"lp01", "he11"}
        and options.fiber_core_radius_um is not None
        and options.fiber_n_core is not None
        and options.fiber_n_clad is not None
    ):
        return step_index_lp01_mode(
            field_obj.grid,
            wavelength_nm=options.wavelength_nm,
            core_radius_um=float(options.fiber_core_radius_um),
            n_core=float(options.fiber_n_core),
            n_clad=float(options.fiber_n_clad),
            offset_x_mm=options.offset_x_mm,
            offset_y_mm=options.offset_y_mm,
            tilt_x_rad=options.tilt_x_rad,
            tilt_y_rad=options.tilt_y_rad,
        )
    return gaussian_fiber_mode(
        field_obj.grid,
        wavelength_nm=options.wavelength_nm,
        mode_field_diameter_x_um=options.mode_field_diameter_x_um,
        mode_field_diameter_y_um=options.mode_field_diameter_y_um,
        offset_x_mm=options.offset_x_mm,
        offset_y_mm=options.offset_y_mm,
        tilt_x_rad=options.tilt_x_rad,
        tilt_y_rad=options.tilt_y_rad,
        refractive_index=options.receiver_medium_refractive_index,
    )


def build_receiving_mode(field_obj: ScalarField2D, options: CouplingOptions) -> ScalarField2D:
    global _global_fiber_mode_hits, _global_fiber_mode_misses
    key = _global_mode_key(field_obj, options)
    if key is not None:
        with _global_fiber_mode_lock:
            cached = _global_fiber_mode_cache.pop(key, None)
            if cached is not None:
                _global_fiber_mode_cache[key] = cached
                _global_fiber_mode_hits += 1
                return cached[0]
            _global_fiber_mode_misses += 1
    mode = _build_receiving_mode_uncached(field_obj, options)
    if key is not None:
        global _global_fiber_mode_cache_bytes
        mode_bytes = int(np.asarray(mode.values).nbytes)
        if mode_bytes <= _GLOBAL_FIBER_MODE_CACHE_MAX_BYTES:
            with _global_fiber_mode_lock:
                old = _global_fiber_mode_cache.pop(key, None)
                if old is not None:
                    _global_fiber_mode_cache_bytes -= old[1]
                _global_fiber_mode_cache[key] = (mode, mode_bytes)
                _global_fiber_mode_cache_bytes += mode_bytes
                while _global_fiber_mode_cache and (
                    len(_global_fiber_mode_cache) > _GLOBAL_FIBER_MODE_CACHE_MAXSIZE
                    or _global_fiber_mode_cache_bytes > _GLOBAL_FIBER_MODE_CACHE_MAX_BYTES
                ):
                    _, (_, removed_bytes) = _global_fiber_mode_cache.popitem(last=False)
                    _global_fiber_mode_cache_bytes -= removed_bytes
    return mode


def prepare_fiber_coupling(
    trace: TraceBundle,
    options: CouplingOptions,
) -> PreparedCouplingProblem:
    return PreparedCouplingProblem.prepare(trace, options)


def _trace_transmission_efficiency(trace: TraceBundle) -> float:
    input_record = dict(getattr(trace, "plane_records", {}) or {}).get("input_pupil")
    if input_record is None:
        return 1.0
    input_valid = np.asarray(input_record.valid_mask, dtype=bool)
    input_power = float(np.sum(input_record.integration_weights[input_valid]))
    output_valid = np.asarray(trace.valid_mask, dtype=bool)
    output_power = float(np.sum(trace.integration_weights[output_valid]))
    if input_power <= 0.0:
        return 1.0
    return float(max(output_power / input_power, 0.0))


def _mean_trace_polarization(trace: TraceBundle) -> tuple[complex, complex, float]:
    vectors = np.asarray(getattr(trace, "polarization_vectors_xyz", None), dtype=np.complex128)
    if vectors.ndim != 2 or vectors.shape[1] != 3 or vectors.shape[0] == 0:
        return 1.0 + 0.0j, 0.0 + 0.0j, 0.0
    valid = np.asarray(trace.valid_mask, dtype=bool)
    weights = np.asarray(trace.integration_weights, dtype=float)
    valid &= np.all(np.isfinite(vectors), axis=1) & np.isfinite(weights) & (weights > 0.0)
    if not np.any(valid):
        return 1.0 + 0.0j, 0.0 + 0.0j, 0.0
    root_weight = np.sqrt(weights[valid])
    mean = np.sum(vectors[valid] * root_weight[:, None], axis=0)
    transverse = mean[:2]
    norm = float(np.linalg.norm(transverse))
    longitudinal = float(
        np.sum(weights[valid] * np.abs(vectors[valid, 2]) ** 2) / np.sum(weights[valid])
    )
    if norm <= 1.0e-30:
        return 1.0 + 0.0j, 0.0 + 0.0j, longitudinal
    transverse = transverse / norm
    return complex(transverse[0]), complex(transverse[1]), longitudinal


def _resample_vector_field(field: VectorField2D, target: ScalarField2D) -> VectorField2D:
    if np.array_equal(field.grid.x_mm, target.grid.x_mm) and np.array_equal(
        field.grid.y_mm, target.grid.y_mm
    ):
        return field
    from scipy.interpolate import RegularGridInterpolator

    yy, xx = np.meshgrid(target.grid.y_mm, target.grid.x_mm, indexing="ij")
    points = np.column_stack([yy.ravel(), xx.ravel()])

    def component(values: np.ndarray) -> np.ndarray:
        axes = (np.asarray(field.grid.y_mm), np.asarray(field.grid.x_mm))
        real = RegularGridInterpolator(axes, np.real(values), bounds_error=False, fill_value=0.0)
        imag = RegularGridInterpolator(axes, np.imag(values), bounds_error=False, fill_value=0.0)
        return (real(points) + 1j * imag(points)).reshape(target.values.shape)

    return VectorField2D(
        ex=component(field.ex),
        ey=component(field.ey),
        ez=component(field.ez),
        grid=target.grid,
        wavelength_nm=target.wavelength_nm,
        refractive_index=target.refractive_index,
        z_mm=target.z_mm,
    ).normalized()


def _vector_fields_for_coupling(
    problem: PreparedCouplingProblem,
    evaluation: PreparedCouplingEvaluation,
) -> tuple[VectorField2D, VectorField2D, dict[str, Any], list[str]]:
    options = problem.options
    warnings: list[str] = []
    mean_x, mean_y, longitudinal_fraction = _mean_trace_polarization(problem.trace)
    incident_jones = np.asarray([mean_x, mean_y], dtype=np.complex128)
    if np.linalg.norm(incident_jones) <= 0.0:
        incident_jones = np.asarray(options.incident_jones_vector, dtype=np.complex128)
    incident_jones /= np.linalg.norm(incident_jones)

    if str(options.vector_coupling_model) == "vector_debye":
        focal_length = max(
            float(problem.prepared_pupil.nominal_propagation_distance_mm)
            + float(options.receiver_axial_offset_z_mm),
            1.0e-9,
        )
        candidate_na = options.receiver_na_x or options.receiver_na_y
        if candidate_na is None:
            pupil_radius = max(
                abs(float(problem.prepared_pupil.field.grid.x_mm[0])),
                abs(float(problem.prepared_pupil.field.grid.x_mm[-1])),
                abs(float(problem.prepared_pupil.field.grid.y_mm[0])),
                abs(float(problem.prepared_pupil.field.grid.y_mm[-1])),
            )
            candidate_na = min(
                float(problem.prepared_pupil.field.refractive_index),
                pupil_radius / np.sqrt(pupil_radius * pupil_radius + focal_length * focal_length),
            )
        incident = vectorial_debye_focus(
            problem.prepared_pupil.field,
            focal_length_mm=focal_length,
            numerical_aperture=max(float(candidate_na), 1.0e-9),
            jones_vector=(complex(incident_jones[0]), complex(incident_jones[1])),
        )
        incident = _resample_vector_field(incident, evaluation.receiver_field)
        vector_model = "vector_debye"
    else:
        incident = lift_scalar_field_to_jones(
            evaluation.receiver_field,
            (complex(incident_jones[0]), complex(incident_jones[1])),
        ).normalized()
        vector_model = "paraxial_trace_jones"

    if str(options.mode_model) == "he11":
        if (
            options.fiber_core_radius_um is None
            or options.fiber_n_core is None
            or options.fiber_n_clad is None
        ):
            mode = lift_scalar_field_to_jones(
                evaluation.receiving_mode, options.fiber_mode_jones_vector
            ).normalized()
            warnings.append("HE11 vector mode fell back to lifted Gaussian mode.")
            mode_metrics: dict[str, Any] = {"fiber_vector_mode": "fallback_gaussian"}
        else:
            solved = solve_he11_vector_mode(
                evaluation.receiving_mode.grid,
                wavelength_nm=options.wavelength_nm,
                core_radius_um=float(options.fiber_core_radius_um),
                n_core=float(options.fiber_n_core),
                n_clad=float(options.fiber_n_clad),
                jones_vector=options.fiber_mode_jones_vector,
                offset_x_mm=options.offset_x_mm,
                offset_y_mm=options.offset_y_mm,
                tilt_x_rad=options.tilt_x_rad,
                tilt_y_rad=options.tilt_y_rad,
            )
            mode = solved.vector_field
            assert mode is not None
            mode_metrics = {
                "fiber_vector_mode": solved.metrics.mode_name,
                "fiber_vector_mode_effective_index": solved.metrics.effective_index,
                "fiber_vector_mode_effective_area_um2": solved.metrics.effective_area_um2,
                "fiber_vector_mode_longitudinal_fraction": solved.metrics.vector_fraction_longitudinal,
            }
            warnings.extend(solved.warnings)
    else:
        mode = lift_scalar_field_to_jones(
            evaluation.receiving_mode, options.fiber_mode_jones_vector
        ).normalized()
        mode_metrics = {"fiber_vector_mode": f"lifted_{options.mode_model}"}

    return incident, mode, {
        "coupling_vector_model": vector_model,
        "coupling_trace_longitudinal_polarization_fraction": longitudinal_fraction,
        **mode_metrics,
    }, warnings


def solve_fiber_coupling(
    trace: TraceBundle,
    options: CouplingOptions,
    prepared_problem: PreparedCouplingProblem | None = None,
) -> FiberCouplingSolverResult:
    problem = prepared_problem or prepare_fiber_coupling(trace, options)
    options = problem.options
    evaluation = problem.evaluate(
        offset_x_mm=options.offset_x_mm,
        offset_y_mm=options.offset_y_mm,
        receiver_axial_offset_z_mm=options.receiver_axial_offset_z_mm,
        tilt_x_rad=options.tilt_x_rad,
        tilt_y_rad=options.tilt_y_rad,
        mode_field_diameter_x_um=options.mode_field_diameter_x_um,
        mode_field_diameter_y_um=options.mode_field_diameter_y_um,
    )
    field_obj = evaluation.receiver_field
    mode = evaluation.receiving_mode
    field_result = evaluation.field_result

    actual = decompose_scalar_overlap(field_obj, mode)
    centered_eval = problem.evaluate(
        offset_x_mm=0.0,
        offset_y_mm=0.0,
        tilt_x_rad=0.0,
        tilt_y_rad=0.0,
    )
    centered = decompose_scalar_overlap(
        centered_eval.receiver_field, centered_eval.receiving_mode
    )
    scalar_eta = actual.complex_efficiency
    alignment_efficiency = (
        scalar_eta / centered.complex_efficiency
        if centered.complex_efficiency > 1.0e-30
        else 0.0
    )

    vector_metrics: dict[str, Any] = {}
    vector_arrays: dict[str, Any] = {}
    vector_warnings: list[str] = []
    vector_eta = scalar_eta
    vector_overlap = actual.complex_overlap
    polarization_efficiency = 1.0
    if options.vector_coupling_enabled or options.polarization_sensitive:
        incident_vector, mode_vector, vector_metrics, vector_warnings = _vector_fields_for_coupling(
            problem, evaluation
        )
        vector_overlap = normalized_vector_overlap(incident_vector, mode_vector)
        vector_eta = float(abs(vector_overlap) ** 2)
        polarization_efficiency = (
            vector_eta / scalar_eta if scalar_eta > 1.0e-30 else 0.0
        )
        vector_arrays = {
            "coupling_vector_field_intensity": incident_vector.intensity,
            "coupling_vector_mode_intensity": mode_vector.intensity,
            "coupling_vector_field_ez_intensity": np.abs(incident_vector.ez) ** 2,
            "coupling_vector_mode_ez_intensity": np.abs(mode_vector.ez) ** 2,
        }

    eta = vector_eta if options.vector_coupling_enabled else scalar_eta
    overlap = vector_overlap if options.vector_coupling_enabled else actual.complex_overlap
    transmission_efficiency = _trace_transmission_efficiency(trace)
    facet = (
        float(options.fiber_facet_transmission_override)
        if options.fiber_facet_transmission_override is not None
        else float(problem.fiber_metrics.get("fiber_facet_transmission", 1.0))
    )
    if options.fiber_facet_transmission_override is not None:
        problem.fiber_metrics["fiber_facet_transmission"] = facet
        problem.fiber_metrics["fiber_facet_transmission_source"] = "explicit_override"
    propagation = float(problem.fiber_metrics.get("fiber_propagation_transmission", 1.0))
    connector = float(problem.fiber_metrics.get("fiber_connector_transmission", 1.0))
    fiber_interface_efficiency = facet * propagation * connector
    selected_polarization_efficiency = (
        polarization_efficiency if options.polarization_sensitive or options.vector_coupling_enabled else 1.0
    )
    
    total_overlap = eta if options.vector_coupling_enabled else scalar_eta * selected_polarization_efficiency
    total_efficiency = float(
        max(transmission_efficiency, 0.0)
        * max(total_overlap, 0.0)
        * max(fiber_interface_efficiency, 0.0)
    )
    
    
    
    
    
    explanatory_product = float(
        max(transmission_efficiency, 0.0)
        * max(centered.intensity_only_efficiency, 0.0)
        * max(centered.phase_matching_efficiency, 0.0)
        * max(alignment_efficiency, 0.0)
        * max(selected_polarization_efficiency, 0.0)
        * max(fiber_interface_efficiency, 0.0)
    )
    interaction_residual = float(total_efficiency - explanatory_product)
    interaction_residual_relative = float(
        interaction_residual / max(abs(total_efficiency), 1.0e-30)
    )

    input_power = float(field_obj.integrated_power)
    mode_power = float(mode.integrated_power)
    field_diag = _field_diagnostics(field_obj)
    mode_diag = _field_diagnostics(mode)
    valid = np.asarray(trace.valid_mask, dtype=bool)
    geometric_fraction = float(np.count_nonzero(valid) / valid.size) if valid.size else 0.0

    metrics: dict[str, Any] = {
        "coupling_efficiency": eta,
        "total_coupling_efficiency": total_efficiency,
        "mode_overlap_efficiency": eta,
        "complex_field_overlap_efficiency": scalar_eta,
        "intensity_only_overlap": actual.intensity_only_efficiency,
        "phase_only_penalty": actual.phase_matching_efficiency,
        "wavefront_aberration_penalty": actual.phase_matching_efficiency,
        "centered_intensity_overlap": centered.intensity_only_efficiency,
        "centered_phase_matching_efficiency": centered.phase_matching_efficiency,
        "alignment_efficiency": float(alignment_efficiency),
        "polarization_overlap_efficiency": float(selected_polarization_efficiency),
        "transmission_efficiency": float(transmission_efficiency),
        "fiber_interface_efficiency": float(fiber_interface_efficiency),
        "coupling_explanatory_factor_product": explanatory_product,
        "coupling_interaction_residual": interaction_residual,
        "coupling_interaction_residual_relative": interaction_residual_relative,
        "coupling_overlap_abs": abs(overlap),
        "coupling_overlap_phase_rad": float(np.angle(overlap)),
        "coupling_scalar_overlap_abs": abs(actual.complex_overlap),
        "coupling_scalar_overlap_phase_rad": float(np.angle(actual.complex_overlap)),
        "coupling_vector_efficiency": float(vector_eta),
        "coupling_input_power_a.u.": input_power,
        "coupling_mode_power_a.u.": mode_power,
        "coupling_valid_ray_fraction": geometric_fraction,
        "coupling_coherent_efficiency": eta,
        "coupling_grid_size": int(options.grid_size),
        "coupling_mode_offset_x_mm": float(options.offset_x_mm),
        "coupling_mode_offset_y_mm": float(options.offset_y_mm),
        "coupling_mode_tilt_x_rad": float(options.tilt_x_rad),
        "coupling_mode_tilt_y_rad": float(options.tilt_y_rad),
        "coupling_field_centroid_x_mm": field_diag["centroid_x_mm"],
        "coupling_field_centroid_y_mm": field_diag["centroid_y_mm"],
        "coupling_field_rms_x_um": field_diag["rms_x_um"],
        "coupling_field_rms_y_um": field_diag["rms_y_um"],
        "coupling_field_rms_radius_um": field_diag["rms_radius_um"],
        "coupling_mode_centroid_x_mm": mode_diag["centroid_x_mm"],
        "coupling_mode_centroid_y_mm": mode_diag["centroid_y_mm"],
        "coupling_mode_rms_x_um": mode_diag["rms_x_um"],
        "coupling_mode_rms_y_um": mode_diag["rms_y_um"],
        "coupling_mode_rms_radius_um": mode_diag["rms_radius_um"],
        **vector_metrics,
        **field_result.metrics,
        **problem.fiber_metrics,
        **problem.cache_metrics(),
    }

    wavelength_mm = float(options.wavelength_nm) * 1.0e-6
    waist_x_mm = max(float(options.mode_field_diameter_x_um) * 0.5e-3, 1.0e-15)
    waist_y_mm = max(float(options.mode_field_diameter_y_um) * 0.5e-3, 1.0e-15)
    gaussian_mode_na_x = wavelength_mm / (np.pi * waist_x_mm)
    gaussian_mode_na_y = wavelength_mm / (np.pi * waist_y_mm)
    metrics["coupling_gaussian_mode_na_x"] = float(gaussian_mode_na_x)
    metrics["coupling_gaussian_mode_na_y"] = float(gaussian_mode_na_y)
    if options.receiver_na_x is not None:
        metrics["coupling_receiver_na_x"] = float(options.receiver_na_x)
    if options.receiver_na_y is not None:
        metrics["coupling_receiver_na_y"] = float(options.receiver_na_y)

    metadata = {
        "solver": "fiber_coupling",
        "field_model": "cartesian_exit_pupil",
        "mode_model": str(options.mode_model),
        "precision_level": str(options.precision_mode),
        "wavelength_nm": float(options.wavelength_nm),
        "receiver_plane_z_mm": float(getattr(field_obj, "z_mm", 0.0) or 0.0),
        "grid_x_count": int(len(field_obj.grid.x_mm)),
        "grid_y_count": int(len(field_obj.grid.y_mm)),
        "prepared_coupling_problem": True,
        "loss_breakdown_model": (
            "transmission_x_centered_amplitude_x_centered_phase_x_alignment_"
            "x_polarization_x_fiber_interface"
        ),
        "surface_physics_in_main_chain": bool(
            any(bool(records) for records in getattr(trace, "surface_interaction_records", []))
        ),
        **field_result.metadata,
    }

    warnings = [*problem.warnings, *field_result.warnings, *vector_warnings]
    if options.receiver_na_x is not None and gaussian_mode_na_x > float(options.receiver_na_x) * 1.001:
        warnings.append(
            f"Gaussian-equivalent mode NA_x={gaussian_mode_na_x:.6g} exceeds receiver NA_x={float(options.receiver_na_x):.6g}."
        )
    if options.receiver_na_y is not None and gaussian_mode_na_y > float(options.receiver_na_y) * 1.001:
        warnings.append(
            f"Gaussian-equivalent mode NA_y={gaussian_mode_na_y:.6g} exceeds receiver NA_y={float(options.receiver_na_y):.6g}."
        )
    if alignment_efficiency > 1.001:
        warnings.append(
            "The requested alignment improves overlap relative to the nominal centered mode; "
            "alignment_efficiency is therefore greater than one."
        )
    if polarization_efficiency > 1.001:
        warnings.append(
            "Vector/scalar overlap ratio exceeds one because the vector mode changes the field model; "
            "interpret polarization_overlap_efficiency as a model ratio, not a passive loss factor."
        )

    if options.include_breakdown:
        metrics.update(
            {
                "coupling_breakdown_geometric_fraction": geometric_fraction,
                "coupling_breakdown_transmission": transmission_efficiency,
                "coupling_breakdown_mode_shape": centered.intensity_only_efficiency,
                "coupling_breakdown_phase": centered.phase_matching_efficiency,
                "coupling_breakdown_alignment": alignment_efficiency,
                "coupling_breakdown_polarization": selected_polarization_efficiency,
                "coupling_breakdown_mode_overlap": eta,
                "coupling_breakdown_facet_transmission": facet,
                "coupling_breakdown_propagation_transmission": propagation,
                "coupling_breakdown_connector_transmission": connector,
                "coupling_breakdown_fiber_interface": fiber_interface_efficiency,
                "coupling_breakdown_total_estimate": total_efficiency,
            }
        )
        metadata["breakdown_model"] = metadata["loss_breakdown_model"]

    array_policy = str(options.result_array_policy)
    if array_policy == "full":
        arrays = {
            "coupling_field_intensity": np.abs(field_obj.values) ** 2,
            "coupling_field_phase_rad": np.angle(field_obj.values),
            "coupling_mode_intensity": np.abs(mode.values) ** 2,
            "coupling_mode_phase_rad": np.angle(mode.values),
            "coupling_grid_x_mm": np.asarray(field_obj.grid.x_mm),
            "coupling_grid_y_mm": np.asarray(field_obj.grid.y_mm),
            **vector_arrays,
            **field_result.arrays,
        }
    elif array_policy == "field_only":
        arrays = {
            "coupling_field_real": np.asarray(field_obj.values.real),
            "coupling_field_imag": np.asarray(field_obj.values.imag),
            "coupling_grid_x_mm": np.asarray(field_obj.grid.x_mm),
            "coupling_grid_y_mm": np.asarray(field_obj.grid.y_mm),
        }
    else:
        arrays = {}
    metadata["result_array_policy"] = array_policy
    return FiberCouplingSolverResult(
        efficiency=eta,
        overlap=overlap,
        metrics=metrics,
        arrays=arrays,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
    )

def _field_diagnostics(field_obj: Any) -> dict[str, float]:
    values = np.asarray(field_obj.values)
    intensity = np.abs(values) ** 2
    intensity = np.where(np.isfinite(intensity) & (intensity > 0), intensity, 0.0)
    x_axis = np.asarray(field_obj.grid.x_mm, dtype=float)
    y_axis = np.asarray(field_obj.grid.y_mm, dtype=float)

    
    
    
    x_weight = np.sum(intensity, axis=0, dtype=float)
    y_weight = np.sum(intensity, axis=1, dtype=float)
    total = float(np.sum(x_weight, dtype=float))
    if total <= 0.0:
        return {
            "centroid_x_mm": 0.0,
            "centroid_y_mm": 0.0,
            "rms_x_um": 0.0,
            "rms_y_um": 0.0,
            "rms_radius_um": 0.0,
        }
    cx = float(np.dot(x_weight, x_axis) / total)
    cy = float(np.dot(y_weight, y_axis) / total)
    vx = float(np.dot(x_weight, (x_axis - cx) ** 2) / total)
    vy = float(np.dot(y_weight, (y_axis - cy) ** 2) / total)
    return {
        "centroid_x_mm": cx,
        "centroid_y_mm": cy,
        "rms_x_um": float(np.sqrt(max(vx, 0.0)) * 1.0e3),
        "rms_y_um": float(np.sqrt(max(vy, 0.0)) * 1.0e3),
        "rms_radius_um": float(np.sqrt(max(vx + vy, 0.0)) * 1.0e3),
    }


def solve_coupling_convergence(trace: TraceBundle, options: CouplingOptions) -> dict[str, Any]:
    sizes = tuple(int(v) for v in options.convergence_grid_sizes if int(v) >= 5)
    if not sizes:
        sizes = (int(max(options.grid_size, 5)),)

    efficiencies: list[float] = []
    overlaps: list[float] = []
    energy_errors: list[float] = []
    edge_fractions: list[float] = []
    for size in sizes:
        one = solve_fiber_coupling(
            trace,
            replace(
                options,
                grid_size=size,
                output_grid_size=size,
                include_convergence=False,
            ),
        )
        efficiencies.append(float(one.efficiency))
        overlaps.append(float(abs(one.overlap)))
        energy_errors.append(float(one.metrics.get("propagation_energy_closure_error", 0.0) or 0.0))
        edge_fractions.append(float(one.metrics.get("propagation_edge_power_fraction", 0.0) or 0.0))

    delta = abs(efficiencies[-1] - efficiencies[-2]) if len(efficiencies) >= 2 else 0.0
    relative_delta = delta / max(abs(efficiencies[-1]), 1.0e-12) if efficiencies else 0.0
    tolerance = float(options.sampling_convergence_tolerance)
    return {
        "metrics": {
            "coupling_convergence_final_efficiency": efficiencies[-1] if efficiencies else 0.0,
            "coupling_convergence_last_delta": float(delta),
            "coupling_convergence_last_relative_delta": float(relative_delta),
            "coupling_convergence_grid_count": len(sizes),
            "coupling_convergence_pass": bool(relative_delta < tolerance) if len(efficiencies) >= 2 else True,
        },
        "arrays": {
            "coupling_convergence_grid_sizes": list(sizes),
            "coupling_convergence_efficiency": efficiencies,
            "coupling_convergence_overlap_abs": overlaps,
            "coupling_convergence_energy_closure_error": energy_errors,
            "coupling_convergence_edge_power_fraction": edge_fractions,
        },
        "metadata": {
            "convergence_model": f"rerun_{str(options.field_model)}_at_grid_sizes",
            "convergence_tolerance": tolerance,
        },
    }


__all__ = [
    "FiberCouplingSolverResult",
    "CouplingNumericalGateError",
    "PreparedCouplingEvaluation",
    "PreparedCouplingProblem",
    "resolve_fiber_mode_options",
    "build_receiving_mode",
    "clear_global_fiber_mode_cache",
    "global_fiber_mode_cache_info",
    "prepare_fiber_coupling",
    "solve_fiber_coupling",
    "solve_coupling_convergence",
]
