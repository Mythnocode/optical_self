
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import OrderedDict
from threading import RLock
from contextlib import contextmanager
import hashlib
import json
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import (
    FieldNormalization,
    PowerUnit,
    ScalarField2D,
)
from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.reconstruction import (
    ComplexFieldReconstructionRequest,
    formal_complex_field_reconstructor,
)
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions
from optical_core.physics.wave.propagation import PropagationPlan, default_propagation_registry
from optical_core.physics.wave.solvers.advanced_propagation import (
    PropagationResult,
    SamplingDiagnostics,
)
from optical_core.physics.wave.solvers.sampling_advisor import advise_propagation_sampling
from optical_core.runtime.protected_merge import merge_unique_mappings


@dataclass(frozen=True, slots=True)
class PreparedCartesianPupil:


    field: ScalarField2D
    nominal_propagation_distance_mm: float
    image_plane_z_mm: float
    metrics: dict[str, Any]
    arrays: dict[str, Any]
    warnings: tuple[str, ...]
    metadata: dict[str, Any]
    fingerprint: str


@dataclass(slots=True)
class CartesianPupilPropagationResult:
    field: ScalarField2D
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)






class _KeyLockPool:


    def __init__(self) -> None:
        self._guard = RLock()
        self._locks: dict[tuple[Any, ...], tuple[RLock, int]] = {}

    @contextmanager
    def lock(self, key: tuple[Any, ...]):
        with self._guard:
            lock, users = self._locks.get(key, (RLock(), 0))
            self._locks[key] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                current = self._locks.get(key)
                if current is not None and current[0] is lock:
                    remaining = current[1] - 1
                    if remaining <= 0:
                        self._locks.pop(key, None)
                    else:
                        self._locks[key] = (lock, remaining)

    def clear(self) -> None:
        with self._guard:
            self._locks.clear()


_prepared_singleflight = _KeyLockPool()
_propagated_singleflight = _KeyLockPool()

_PREPARED_PUPIL_CACHE_MAXSIZE = 16
_prepared_pupil_cache: OrderedDict[tuple[Any, ...], tuple[TraceBundle, PreparedCartesianPupil]] = OrderedDict()
_prepared_pupil_lock = RLock()
_prepared_pupil_hits = 0
_prepared_pupil_misses = 0

_PROPAGATED_FIELD_CACHE_MAX_BYTES = 256 * 1024**2
_propagated_field_cache: OrderedDict[tuple[Any, ...], tuple[CartesianPupilPropagationResult, int]] = OrderedDict()
_propagated_field_cache_bytes = 0
_propagated_field_lock = RLock()
_propagated_field_hits = 0
_propagated_field_misses = 0


def _prepared_pupil_key(trace: TraceBundle, options: CouplingOptions) -> tuple[Any, ...]:
    return (
        id(trace), float(options.wavelength_nm), int(options.pupil_grid_size),
        float(options.pupil_extent_scale), int(options.wavefront_fit_order),
        str(options.pupil_amplitude_weighting),
        float(options.receiver_medium_refractive_index),
        None if options.propagation_distance_mm is None else round(float(options.propagation_distance_mm), 12),
        bool(options.include_diagnostic_arrays),
    )


def _get_prepared_pupil(
    trace: TraceBundle, key: tuple[Any, ...]
) -> PreparedCartesianPupil | None:
    global _prepared_pupil_hits, _prepared_pupil_misses
    with _prepared_pupil_lock:
        item = _prepared_pupil_cache.pop(key, None)
        if item is None or item[0] is not trace:
            _prepared_pupil_misses += 1
            return None
        _prepared_pupil_cache[key] = item
        _prepared_pupil_hits += 1
        prepared = item[1]
    return replace(
        prepared,
        metrics={**prepared.metrics, "prepared_pupil_cache_hit": True},
        metadata={**prepared.metadata, "prepared_pupil_cache_hit": True},
    )


def _put_prepared_pupil(
    trace: TraceBundle, key: tuple[Any, ...], prepared: PreparedCartesianPupil
) -> None:
    with _prepared_pupil_lock:
        _prepared_pupil_cache.pop(key, None)
        _prepared_pupil_cache[key] = (trace, prepared)
        while len(_prepared_pupil_cache) > _PREPARED_PUPIL_CACHE_MAXSIZE:
            _prepared_pupil_cache.popitem(last=False)


def _propagated_field_key(
    prepared: PreparedCartesianPupil, options: CouplingOptions, distance_mm: float
) -> tuple[Any, ...]:
    return (
        prepared.fingerprint, round(float(distance_mm), 12),
        str(options.propagation_model), int(options.grid_size),
        int(options.output_grid_size or 0),
        None if options.field_extent_mm is None else float(options.field_extent_mm),
        None if options.output_extent_x_mm is None else float(options.output_extent_x_mm),
        None if options.output_extent_y_mm is None else float(options.output_extent_y_mm),
        float(options.zero_padding_factor),
        str(options.scaled_angular_spectrum_transfer_model),
        float(options.edge_power_threshold), float(options.energy_closure_threshold),
        float(options.nyquist_margin_min), bool(options.auto_expand_output),
        float(options.auto_expand_factor), int(options.auto_expand_max_steps),
        int(options.auto_expand_max_grid_size), bool(options.sampling_convergence_enabled),
        tuple(int(v) for v in options.sampling_convergence_grid_sizes),
        float(options.sampling_convergence_tolerance),
        float(options.issc_oversampling_factor), float(options.issc_padding_factor),
        int(options.issc_max_virtual_grid), bool(options.include_diagnostic_arrays),
        str(options.precision_mode),
    )


def _result_nbytes(result: CartesianPupilPropagationResult) -> int:
    seen: set[int] = set()

    def size(value: Any) -> int:
        ident = id(value)
        if ident in seen:
            return 0
        seen.add(ident)
        if isinstance(value, np.ndarray):
            return int(value.nbytes)
        if isinstance(value, dict):
            return sum(size(k) + size(v) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return sum(size(v) for v in value)
        return 0

    return size(result.field.values) + size(result.arrays)


def _get_propagated_field(key: tuple[Any, ...]) -> CartesianPupilPropagationResult | None:
    global _propagated_field_hits, _propagated_field_misses
    with _propagated_field_lock:
        item = _propagated_field_cache.pop(key, None)
        if item is None:
            _propagated_field_misses += 1
            return None
        _propagated_field_cache[key] = item
        _propagated_field_hits += 1
        result = item[0]
    return CartesianPupilPropagationResult(
        field=result.field,
        metrics={**result.metrics, "coupling_propagated_field_cache_hit": True},
        arrays=result.arrays,
        warnings=list(result.warnings),
        metadata={**result.metadata, "propagated_field_cache_hit": True},
    )


def _put_propagated_field(
    key: tuple[Any, ...], result: CartesianPupilPropagationResult
) -> None:
    global _propagated_field_cache_bytes
    nbytes = _result_nbytes(result)
    if nbytes > _PROPAGATED_FIELD_CACHE_MAX_BYTES:
        return
    with _propagated_field_lock:
        old = _propagated_field_cache.pop(key, None)
        if old is not None:
            _propagated_field_cache_bytes -= old[1]
        _propagated_field_cache[key] = (result, nbytes)
        _propagated_field_cache_bytes += nbytes
        while (
            _propagated_field_cache
            and _propagated_field_cache_bytes > _PROPAGATED_FIELD_CACHE_MAX_BYTES
        ):
            _, (_, removed_bytes) = _propagated_field_cache.popitem(last=False)
            _propagated_field_cache_bytes -= removed_bytes


def clear_cartesian_pupil_caches() -> None:
    global _prepared_pupil_hits, _prepared_pupil_misses
    _prepared_singleflight.clear()
    _propagated_singleflight.clear()
    global _propagated_field_hits, _propagated_field_misses, _propagated_field_cache_bytes
    clear_receiver_window_plan_cache()
    with _prepared_pupil_lock:
        _prepared_pupil_cache.clear()
        _prepared_pupil_hits = _prepared_pupil_misses = 0
    with _propagated_field_lock:
        _propagated_field_cache.clear()
        _propagated_field_cache_bytes = 0
        _propagated_field_hits = _propagated_field_misses = 0


def cartesian_pupil_cache_info() -> dict[str, Any]:
    with _prepared_pupil_lock, _propagated_field_lock:
        return {
            "prepared_pupil": {
                "hits": int(_prepared_pupil_hits), "misses": int(_prepared_pupil_misses),
                "currsize": len(_prepared_pupil_cache), "maxsize": _PREPARED_PUPIL_CACHE_MAXSIZE,
            },
            "propagated_field": {
                "hits": int(_propagated_field_hits), "misses": int(_propagated_field_misses),
                "currsize": len(_propagated_field_cache),
                "bytes": int(_propagated_field_cache_bytes),
                "max_bytes": int(_PROPAGATED_FIELD_CACHE_MAX_BYTES),
            },
            "receiver_window_plan": receiver_window_plan_cache_info(),
        }


_WINDOW_PLAN_CACHE_MAXSIZE = 64
_window_plan_cache: OrderedDict[tuple[Any, ...], tuple[float, int]] = OrderedDict()
_window_plan_lock = RLock()
_window_plan_hits = 0
_window_plan_misses = 0


def _window_plan_key(
    prepared: PreparedCartesianPupil, options: CouplingOptions, distance_mm: float
) -> tuple[Any, ...]:
    return (
        prepared.fingerprint, round(float(distance_mm), 12),
        str(options.propagation_model), int(options.output_grid_size or options.grid_size),
        float(options.output_extent_x_mm or options.field_extent_mm or 0.0),
        float(options.output_extent_y_mm or options.field_extent_mm or 0.0),
        float(options.zero_padding_factor), float(options.edge_power_threshold),
        float(options.energy_closure_threshold), float(options.auto_expand_factor),
        int(options.auto_expand_max_steps), int(options.auto_expand_max_grid_size),
    )


def _get_window_plan(key: tuple[Any, ...]) -> tuple[float, int] | None:
    global _window_plan_hits, _window_plan_misses
    with _window_plan_lock:
        item = _window_plan_cache.pop(key, None)
        if item is None:
            _window_plan_misses += 1
            return None
        _window_plan_cache[key] = item
        _window_plan_hits += 1
        return item


def _put_window_plan(key: tuple[Any, ...], scale: float, grid: int) -> None:
    with _window_plan_lock:
        _window_plan_cache.pop(key, None)
        _window_plan_cache[key] = (float(scale), int(grid))
        while len(_window_plan_cache) > _WINDOW_PLAN_CACHE_MAXSIZE:
            _window_plan_cache.popitem(last=False)


def clear_receiver_window_plan_cache() -> None:
    global _window_plan_hits, _window_plan_misses
    with _window_plan_lock:
        _window_plan_cache.clear()
        _window_plan_hits = 0
        _window_plan_misses = 0


def receiver_window_plan_cache_info() -> dict[str, int]:
    with _window_plan_lock:
        return {
            "hits": int(_window_plan_hits), "misses": int(_window_plan_misses),
            "currsize": len(_window_plan_cache), "maxsize": _WINDOW_PLAN_CACHE_MAXSIZE,
        }


def _stable_json(value: Any) -> str:
    def convert(item: Any) -> Any:
        if isinstance(item, np.ndarray):
            return item.tolist()
        if isinstance(item, np.generic):
            return item.item()
        if isinstance(item, dict):
            return {str(k): convert(v) for k, v in sorted(item.items(), key=lambda pair: str(pair[0]))}
        if isinstance(item, (list, tuple)):
            return [convert(v) for v in item]
        return item

    return json.dumps(convert(value), sort_keys=True, separators=(",", ":"), default=str)


def _prepared_field_fingerprint(payload: dict[str, Any], field: ScalarField2D) -> str:


    digest = hashlib.sha256()
    digest.update(_stable_json(payload).encode("utf-8"))
    for array in (field.grid.x_mm, field.grid.y_mm, field.values):
        contiguous = np.ascontiguousarray(array)
        digest.update(contiguous.dtype.str.encode("ascii"))
        digest.update(repr(tuple(contiguous.shape)).encode("ascii"))
        digest.update(memoryview(contiguous).cast("B"))
    digest.update(repr(float(field.wavelength_nm)).encode("ascii"))
    digest.update(repr(float(field.refractive_index)).encode("ascii"))
    return digest.hexdigest()


def _output_axes(
    options: CouplingOptions,
    grid_size: int | None = None,
    scale: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    n = int(grid_size or options.output_grid_size or options.grid_size)
    n = max(n, 17)
    if n % 2 == 0:
        n += 1
    default_extent = max(
        float(options.field_extent_mm or 0.0),
        6.0
        * 0.5e-3
        * max(
            float(options.mode_field_diameter_x_um),
            float(options.mode_field_diameter_y_um),
        ),
        0.01,
    )
    extent_x = float(options.output_extent_x_mm or default_extent) * float(scale)
    extent_y = float(options.output_extent_y_mm or default_extent) * float(scale)
    return (
        np.linspace(-extent_x, extent_x, n, dtype=float),
        np.linspace(-extent_y, extent_y, n, dtype=float),
    )


def _normalise_unit_power(field: ScalarField2D) -> ScalarField2D:
    values = np.asarray(field.values, dtype=np.complex128)
    power = float(np.sum(np.abs(values) ** 2) * abs(field.grid.dx_mm * field.grid.dy_mm))
    if power <= 0.0 or not np.isfinite(power):
        return field
    values = values / np.sqrt(power)
    return ScalarField2D(
        values=values,
        grid=field.grid,
        wavelength_nm=field.wavelength_nm,
        refractive_index=field.refractive_index,
        z_mm=field.z_mm,
        integrated_power=1.0,
        power_unit=PowerUnit.ARBITRARY,
        normalization=FieldNormalization.UNIT_POWER,
    )


def _resample_complex(field: ScalarField2D, x_mm: np.ndarray, y_mm: np.ndarray) -> np.ndarray:
    from scipy.interpolate import RegularGridInterpolator

    values = np.asarray(field.values, dtype=np.complex128)
    yy, xx = np.meshgrid(y_mm, x_mm, indexing="ij")
    points = np.column_stack([yy.ravel(), xx.ravel()])
    real = RegularGridInterpolator(
        (np.asarray(field.grid.y_mm, dtype=float), np.asarray(field.grid.x_mm, dtype=float)),
        np.real(values),
        bounds_error=False,
        fill_value=0.0,
    )
    imag = RegularGridInterpolator(
        (np.asarray(field.grid.y_mm, dtype=float), np.asarray(field.grid.x_mm, dtype=float)),
        np.imag(values),
        bounds_error=False,
        fill_value=0.0,
    )
    return (real(points) + 1j * imag(points)).reshape(y_mm.size, x_mm.size)


def _complex_overlap(a: np.ndarray, b: np.ndarray) -> float:
    av = np.asarray(a, dtype=np.complex128).ravel()
    bv = np.asarray(b, dtype=np.complex128).ravel()
    denom = float(np.sqrt(np.vdot(av, av).real * np.vdot(bv, bv).real))
    if denom <= 0.0:
        return 0.0
    return float(abs(np.vdot(av, bv)) / denom)


def _intensity_rmse(a: np.ndarray, b: np.ndarray) -> float:
    ia = np.abs(a) ** 2
    ib = np.abs(b) ** 2
    ia = ia / max(float(np.max(ia)), 1.0e-30)
    ib = ib / max(float(np.max(ib)), 1.0e-30)
    return float(np.sqrt(np.mean((ia - ib) ** 2)))


def _propagate_once(
    pupil: ScalarField2D,
    distance_mm: float,
    options: CouplingOptions,
    *,
    grid_size: int | None = None,
    output_scale: float = 1.0,
) -> PropagationResult:
    method = str(options.propagation_model or "scaled_fresnel")
    if method == "fresnel":
        method = "scaled_fresnel"
    if method == "none":
        return PropagationResult(
            field=pupil,
            diagnostics=SamplingDiagnostics(
                method="none",
                metrics={
                    "input_power_a.u.": float(pupil.integrated_power),
                    "output_power_a.u.": float(pupil.integrated_power),
                    "energy_closure_error": 0.0,
                    "edge_power_fraction": 0.0,
                    "nyquist_margin_min": float("inf"),
                },
                warnings=(),
            ),
            metadata={"method": "none", "reference_independent": True},
        )
    output_x = output_y = None
    if method in {"scaled_angular_spectrum", "scaled_fresnel", "issc", "matrix_fresnel"}:
        output_x, output_y = _output_axes(options, grid_size=grid_size, scale=output_scale)
    same_pitch_padding_methods = {"angular_spectrum", "band_limited_angular_spectrum"}
    effective_padding_factor = float(options.zero_padding_factor)
    if method in same_pitch_padding_methods:
        effective_padding_factor *= float(output_scale)
    raw = default_propagation_registry().propagate(
        pupil,
        PropagationPlan(
            method=method,
            distance_mm=float(distance_mm),
            output_x_mm=output_x,
            output_y_mm=output_y,
            options={
                "zero_padding_factor": effective_padding_factor,
                "edge_power_threshold": float(options.edge_power_threshold),
                "energy_closure_threshold": float(options.energy_closure_threshold),
                "nyquist_margin_min": float(options.nyquist_margin_min),
                "issc_oversampling_factor": float(options.issc_oversampling_factor),
                "issc_padding_factor": float(options.issc_padding_factor),
                "issc_max_virtual_grid": int(options.issc_max_virtual_grid),
                "scaled_angular_spectrum_transfer_model": str(
                    options.scaled_angular_spectrum_transfer_model
                ),
            },
        ),
    )
    if isinstance(raw, PropagationResult):
        result = raw
    else:
        result = PropagationResult(
            field=raw,
            diagnostics=SamplingDiagnostics(method=method, metrics={}, warnings=()),
            metadata={"method": method, "strategy_registry": True},
        )
    advice = advise_propagation_sampling(
        pupil,
        float(distance_mm),
        output_x_mm=output_x,
        output_y_mm=output_y,
        zero_padding_factor=effective_padding_factor,
    )
    advice_metrics = advice.to_metrics()
    base_metrics = {
        key: value for key, value in result.diagnostics.metrics.items()
        if key not in advice_metrics
    }
    merged_metrics = {
        **base_metrics,
        **{f"preflight_{key}": value for key, value in advice_metrics.items()},
    }
    preflight_warnings = [f"Sampling pre-flight: {item}" for item in advice.warnings]
    merged_warnings = tuple(dict.fromkeys([*result.diagnostics.warnings, *preflight_warnings]))
    return PropagationResult(
        field=result.field,
        diagnostics=SamplingDiagnostics(
            method=result.diagnostics.method,
            metrics=merged_metrics,
            warnings=merged_warnings,
        ),
        metadata={**result.metadata, "sampling_preflight": True},
    )


def prepare_cartesian_pupil_propagation(
    trace: TraceBundle,
    options: CouplingOptions,
) -> PreparedCartesianPupil:


    cache_key = _prepared_pupil_key(trace, options)
    cached = _get_prepared_pupil(trace, cache_key)
    if cached is not None:
        return cached

    exit_result = formal_complex_field_reconstructor().reconstruct(
        trace,
        ComplexFieldReconstructionRequest(
            wavelength_nm=float(options.wavelength_nm),
            image_refractive_index=float(options.receiver_medium_refractive_index),
            grid_size=int(options.pupil_grid_size),
            extent_scale=float(options.pupil_extent_scale),
            opl_fit_order=int(options.wavefront_fit_order),
            amplitude_weighting=str(options.pupil_amplitude_weighting),
            normalize_power=False,
            include_arrays=bool(options.include_diagnostic_arrays),
        ),
    )
    nominal_distance = float(
        options.propagation_distance_mm
        if options.propagation_distance_mm is not None
        else exit_result.propagation_distance_mm
    )
    payload = {
        "wavelength_nm": options.wavelength_nm,
        "pupil_grid_size": options.pupil_grid_size,
        "pupil_extent_scale": options.pupil_extent_scale,
        "wavefront_fit_order": options.wavefront_fit_order,
        "pupil_amplitude_weighting": options.pupil_amplitude_weighting,
        "receiver_medium_refractive_index": options.receiver_medium_refractive_index,
        "nominal_distance_mm": nominal_distance,
        "trace_ray_count": int(np.asarray(trace.valid_mask).size),
        "trace_valid_count": int(np.count_nonzero(np.asarray(trace.valid_mask, dtype=bool))),
        "exit_metrics": exit_result.metrics,
    }
    fingerprint = _prepared_field_fingerprint(payload, exit_result.field)
    prepared = PreparedCartesianPupil(
        field=exit_result.field,
        nominal_propagation_distance_mm=nominal_distance,
        image_plane_z_mm=float(exit_result.image_plane_z_mm),
        metrics={**dict(exit_result.metrics), "prepared_pupil_cache_hit": False},
        arrays=dict(exit_result.arrays),
        warnings=tuple(exit_result.warnings),
        metadata={**dict(exit_result.metadata), "prepared_pupil_cache_hit": False},
        fingerprint=fingerprint,
    )
    _put_prepared_pupil(trace, cache_key, prepared)
    return prepared


def propagate_prepared_cartesian_pupil(
    prepared: PreparedCartesianPupil,
    options: CouplingOptions,
) -> CartesianPupilPropagationResult:


    warnings = list(prepared.warnings)
    propagation_distance_mm = (
        float(prepared.nominal_propagation_distance_mm)
        + float(options.receiver_axial_offset_z_mm)
    )
    field_cache_key = _propagated_field_key(prepared, options, propagation_distance_mm)
    cached_field = _get_propagated_field(field_cache_key)
    if cached_field is not None:
        return cached_field

    output_scale = 1.0
    base_output_grid = int(options.output_grid_size or options.grid_size)
    if base_output_grid % 2 == 0:
        base_output_grid += 1
    current_output_grid = base_output_grid
    plan_key = _window_plan_key(prepared, options, propagation_distance_mm)
    cached_plan = _get_window_plan(plan_key) if bool(options.auto_expand_output) else None
    window_plan_cache_hit = cached_plan is not None
    if cached_plan is not None:
        output_scale, current_output_grid = cached_plan
    propagated = _propagate_once(
        prepared.field,
        propagation_distance_mm,
        options,
        grid_size=current_output_grid,
        output_scale=output_scale,
    )

    expansion_steps = 0
    expansion_limited_by_grid_cap = False
    propagation_method = str(options.propagation_model)
    same_pitch_padding_methods = {"angular_spectrum", "band_limited_angular_spectrum"}
    scaled_window_methods = {"scaled_angular_spectrum", "scaled_fresnel", "fresnel", "issc"}
    expandable = propagation_method in same_pitch_padding_methods | scaled_window_methods
    edge = float(propagated.diagnostics.metrics.get("edge_power_fraction", 0.0) or 0.0)
    energy_error_for_expansion = float(
        propagated.diagnostics.metrics.get("energy_closure_error", 0.0) or 0.0
    )
    if bool(options.auto_expand_output) and expandable:
        while (
            edge > float(options.edge_power_threshold)
            or energy_error_for_expansion > float(options.energy_closure_threshold)
        ) and expansion_steps < int(options.auto_expand_max_steps):
            candidate_scale = output_scale * float(options.auto_expand_factor)
            if propagation_method in scaled_window_methods:
                candidate_grid = int(np.ceil((base_output_grid - 1) * candidate_scale)) + 1
                if candidate_grid % 2 == 0:
                    candidate_grid += 1
            else:
                candidate_grid = int(
                    np.ceil(
                        max(prepared.field.values.shape)
                        * float(options.zero_padding_factor)
                        * candidate_scale
                    )
                )
                
                if (candidate_grid - max(prepared.field.values.shape)) % 2:
                    candidate_grid += 1
            if candidate_grid > int(options.auto_expand_max_grid_size):
                expansion_limited_by_grid_cap = True
                warnings.append(
                    "Receiver window auto-expansion stopped before allocating "
                    f"a {candidate_grid}x{candidate_grid} working grid; configured "
                    f"auto_expand_max_grid_size={int(options.auto_expand_max_grid_size)}."
                )
                break

            output_scale = candidate_scale
            expansion_steps += 1
            
            
            
            
            current_output_grid = candidate_grid if propagation_method in scaled_window_methods else base_output_grid
            propagated = _propagate_once(
                prepared.field,
                propagation_distance_mm,
                options,
                grid_size=current_output_grid,
                output_scale=output_scale,
            )
            edge = float(propagated.diagnostics.metrics.get("edge_power_fraction", 0.0) or 0.0)
            energy_error_for_expansion = float(
                propagated.diagnostics.metrics.get("energy_closure_error", 0.0) or 0.0
            )
        if expansion_steps:
            warnings.append(
                "Receiver window auto-expanded "
                f"{expansion_steps} time(s), final scale={output_scale:.6g}, "
                f"grid={current_output_grid}."
            )
    
    
    
    warnings.extend(propagated.diagnostics.warnings)
    auto_expand_converged = bool(
        edge <= float(options.edge_power_threshold)
        and energy_error_for_expansion <= float(options.energy_closure_threshold)
    )
    if auto_expand_converged and bool(options.auto_expand_output) and expandable:
        _put_window_plan(plan_key, output_scale, current_output_grid)
    if bool(options.auto_expand_output) and expandable and not auto_expand_converged:
        warnings.append(
            "Receiver window expansion reached its configured limit before "
            "all window-closure gates passed "
            f"(edge<={float(options.edge_power_threshold):.3g}, "
            f"energy_error<={float(options.energy_closure_threshold):.3g})."
        )

    
    
    output = _normalise_unit_power(propagated.field)
    convergence_metrics: dict[str, Any] = {}
    if bool(options.sampling_convergence_enabled):
        sizes = sorted({int(v) for v in options.sampling_convergence_grid_sizes if int(v) >= 17})
        if len(sizes) >= 2:
            low_result = _propagate_once(
                prepared.field,
                propagation_distance_mm,
                options,
                grid_size=sizes[-2],
                output_scale=output_scale,
            )
            high_result = _propagate_once(
                prepared.field,
                propagation_distance_mm,
                options,
                grid_size=sizes[-1],
                output_scale=output_scale,
            )
            low_on_high = _resample_complex(
                low_result.field,
                high_result.field.grid.x_mm,
                high_result.field.grid.y_mm,
            )
            overlap = _complex_overlap(high_result.field.values, low_on_high)
            irmse = _intensity_rmse(high_result.field.values, low_on_high)
            tolerance = float(options.sampling_convergence_tolerance)
            converged = bool(1.0 - overlap <= tolerance and irmse <= tolerance)
            convergence_metrics = {
                "sampling_convergence_low_grid": sizes[-2],
                "sampling_convergence_high_grid": sizes[-1],
                "sampling_convergence_complex_overlap": overlap,
                "sampling_convergence_intensity_rmse": irmse,
                "sampling_convergence_pass": converged,
                "sampling_convergence_tolerance": tolerance,
            }
            if not converged:
                warnings.append(
                    "Sampling convergence not reached: "
                    f"loss={1.0-overlap:.3g}, intensity RMSE={irmse:.3g}."
                )

    propagation_metrics = dict(propagated.diagnostics.metrics)
    energy_error = float(propagation_metrics.get("energy_closure_error", 0.0) or 0.0)
    nyquist_margin = float(propagation_metrics.get("nyquist_margin_min", float("inf")) or 0.0)
    edge_pass = bool(edge <= float(options.edge_power_threshold))
    energy_pass = bool(energy_error <= float(options.energy_closure_threshold))
    nyquist_pass = bool(np.isinf(nyquist_margin) or nyquist_margin >= float(options.nyquist_margin_min))
    convergence_pass = bool(
        not options.sampling_convergence_enabled
        or convergence_metrics.get("sampling_convergence_pass", False)
    )
    post_sampling_pass = bool(edge_pass and energy_pass and nyquist_pass and convergence_pass)
    failed_count = sum(not item for item in (edge_pass, energy_pass, nyquist_pass, convergence_pass))
    if failed_count >= 2:
        post_aliasing_risk = "critical"
    elif failed_count == 1:
        post_aliasing_risk = "high"
    else:
        edge_ratio = edge / max(float(options.edge_power_threshold), 1.0e-30)
        energy_ratio = energy_error / max(float(options.energy_closure_threshold), 1.0e-30)
        nyquist_ratio = 0.0 if np.isinf(nyquist_margin) else float(options.nyquist_margin_min) / max(nyquist_margin, 1.0e-30)
        post_aliasing_risk = "low" if max(edge_ratio, energy_ratio, nyquist_ratio) <= 0.5 else "moderate"
    metrics = merge_unique_mappings(
        prepared.metrics,
        {f"propagation_{key}": value for key, value in propagation_metrics.items()},
        convergence_metrics,
        {
            "coupling_propagation_distance_mm": float(propagation_distance_mm),
            "coupling_receiver_axial_offset_z_mm": float(options.receiver_axial_offset_z_mm),
            "coupling_output_window_scale": float(output_scale),
            "coupling_output_base_grid_size": int(base_output_grid),
            "coupling_output_final_grid_size": int(output.values.shape[1]),
            "coupling_output_pitch_preserved_during_expansion": True,
            "coupling_output_auto_expand_steps": int(expansion_steps),
            "coupling_output_window_plan_cache_hit": bool(window_plan_cache_hit),
            "coupling_propagated_field_cache_hit": False,
            "coupling_output_auto_expand_converged": auto_expand_converged,
            "coupling_output_auto_expand_limited_by_grid_cap": bool(expansion_limited_by_grid_cap),
            "coupling_output_auto_expand_max_grid_size": int(options.auto_expand_max_grid_size),
            "coupling_output_grid_size_x": int(output.values.shape[1]),
            "coupling_output_grid_size_y": int(output.values.shape[0]),
            "coupling_output_power_after_overlap_normalization_a.u.": float(output.integrated_power),
            
            
            
            "coupling_output_power_a.u.": float(output.integrated_power),
            "coupling_propagation_energy_pass": energy_pass,
            "coupling_propagation_edge_pass": edge_pass,
            "coupling_propagation_nyquist_pass": nyquist_pass,
            "coupling_propagation_sampling_pass": post_sampling_pass,
            "coupling_propagation_aliasing_risk": post_aliasing_risk,
            "coupling_propagation_preflight_sampling_pass": bool(
                propagation_metrics.get("preflight_sampling_pass", True)
            ),
            "coupling_propagation_preflight_aliasing_risk": str(
                propagation_metrics.get("preflight_aliasing_risk", "unknown")
            ),
            "coupling_propagation_required_grid_size": int(
                propagation_metrics.get("preflight_required_grid_size", output.values.shape[1])
            ),
            "coupling_propagation_required_window_mm": float(
                propagation_metrics.get("preflight_required_window_mm", 0.0)
            ),
            "coupling_propagation_required_padding_factor": float(
                propagation_metrics.get("preflight_required_padding_factor", 1.0)
            ),
            "prepared_pupil_cache_fingerprint": prepared.fingerprint,
        },
        collection="cartesian_pupil_propagation.metrics",
    )
    arrays = (
        merge_unique_mappings(
            prepared.arrays,
            {
                
                
                
                
                "propagated_field_real": np.real(output.values),
                "propagated_field_imag": np.imag(output.values),
            },
            collection="cartesian_pupil_propagation.arrays",
        )
        if options.include_diagnostic_arrays
        else {}
    )
    metadata = merge_unique_mappings(
        prepared.metadata,
        propagated.metadata,
        {
            "field_model": "cartesian_exit_pupil",
            "reconstructor_interface": "ComplexFieldReconstructor",
            "prepared_propagation_interface": True,
            "propagation_strategy_registry": True,
            "propagation_model": str(propagated.diagnostics.method),
            "precision_level": str(options.precision_mode),
            "reference_independent": True,
            "reference_data_used_as_input": False,
            "raw_power_diagnostics_preserved_before_overlap_normalization": True,
            "large_array_storage": "numpy_ndarray",
            "diagnostic_arrays_included": bool(options.include_diagnostic_arrays),
        },
        collection="cartesian_pupil_propagation.metadata",
    )
    result = CartesianPupilPropagationResult(
        field=output,
        metrics=metrics,
        arrays=arrays,
        warnings=warnings,
        metadata=metadata,
    )
    if post_sampling_pass:
        _put_propagated_field(field_cache_key, result)
    return result





_prepare_cartesian_pupil_propagation_impl = prepare_cartesian_pupil_propagation

def prepare_cartesian_pupil_propagation(
    trace: TraceBundle,
    options: CouplingOptions,
) -> PreparedCartesianPupil:
    key = _prepared_pupil_key(trace, options)
    with _prepared_singleflight.lock(key):
        return _prepare_cartesian_pupil_propagation_impl(trace, options)


_propagate_prepared_cartesian_pupil_impl = propagate_prepared_cartesian_pupil

def propagate_prepared_cartesian_pupil(
    prepared: PreparedCartesianPupil,
    options: CouplingOptions,
) -> CartesianPupilPropagationResult:
    distance_mm = (
        float(prepared.nominal_propagation_distance_mm)
        + float(options.receiver_axial_offset_z_mm)
    )
    key = _propagated_field_key(prepared, options, distance_mm)
    with _propagated_singleflight.lock(key):
        return _propagate_prepared_cartesian_pupil_impl(prepared, options)


def solve_cartesian_pupil_propagation(
    trace: TraceBundle,
    options: CouplingOptions,
) -> CartesianPupilPropagationResult:


    prepared = prepare_cartesian_pupil_propagation(trace, options)
    return propagate_prepared_cartesian_pupil(prepared, options)


__all__ = [
    "PreparedCartesianPupil",
    "CartesianPupilPropagationResult",
    "prepare_cartesian_pupil_propagation",
    "propagate_prepared_cartesian_pupil",
    "solve_cartesian_pupil_propagation",
    "clear_cartesian_pupil_caches",
    "cartesian_pupil_cache_info",
    "clear_receiver_window_plan_cache",
    "receiver_window_plan_cache_info",
]
