
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import time
from typing import Any, Callable

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.analyses.coupling_tolerance_theory import (
    angular_tolerance_rad,
    axial_tolerance_um,
    efficiency_ratio_to_loss_db,
    gaussian_angular_relative_efficiency,
    gaussian_axial_relative_efficiency,
    gaussian_lateral_relative_efficiency,
    gaussian_tolerance_scales,
    lateral_tolerance_um,
    relative_efficiency_for_loss_db,
)
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions, apply_coupling_precision_defaults, parse_jones_pair
from optical_core.physics.hybrid.solvers.fiber_coupling import CouplingNumericalGateError
from .axis_scan import (
    AxisScan,
    connected_threshold_brackets,
    evaluate_axis,
    legacy_sampled_tolerance,
    normalise_axis,
)
from .evaluator import AlignmentCancelled, PreparedToleranceEvaluator
from .models import FiberToleranceOptions, ToleranceAnalysisResult
from .sensitivity import compute_sensitivity
from .statistics import evaluate_receiver_monte_carlo, linear_rss_and_worst_case
from .threshold_solver import ThresholdCrossingResult, solve_threshold_crossing


_MIN_EFFICIENCY = 1.0e-300
_EXPECTED_NUMERICAL_ERRORS = (
    ValueError,
    FloatingPointError,
    OverflowError,
    MemoryError,
    CouplingNumericalGateError,
)


def _int_tuple(value: Any) -> tuple[int, ...]:
    if isinstance(value, str):
        return tuple(int(item.strip()) for item in value.split(",") if item.strip())
    return tuple(int(item) for item in value)


def _tilt_rad_from_options(opts: dict[str, Any], axis: str) -> float:
    for suffix, scale in (("rad", 1.0), ("urad", 1.0e-6), ("mrad", 1.0e-3)):
        key = f"tilt_{axis}_{suffix}"
        if key in opts:
            return float(opts[key]) * scale
    deg_key = f"tilt_{axis}_deg"
    if deg_key in opts:
        return float(np.deg2rad(float(opts[deg_key])))
    return 0.0


def coupling_options_from_mapping(opts: dict[str, Any]) -> CouplingOptions:


    opts = apply_coupling_precision_defaults(opts)
    conv = _int_tuple(opts.get("convergence_grid_sizes", (65, 129, 257, 513)))
    sampling_conv = _int_tuple(opts.get("sampling_convergence_grid_sizes", (257, 513)))
    return CouplingOptions(
        wavelength_nm=float(opts.get("wavelength_nm", 550.0)),
        grid_size=int(opts.get("grid_size", 129)),
        field_extent_mm=opts.get("field_extent_mm", None),
        mode_field_diameter_x_um=float(opts.get("mode_field_diameter_x_um", 10.0)),
        mode_field_diameter_y_um=float(
            opts.get("mode_field_diameter_y_um", opts.get("mode_field_diameter_x_um", 10.0))
        ),
        mode_model=str(opts.get("mode_model", "gaussian")),
        vector_coupling_enabled=bool(opts.get("vector_coupling_enabled", False)),
        vector_coupling_model=str(opts.get("vector_coupling_model", "paraxial_trace")),
        polarization_sensitive=bool(opts.get("polarization_sensitive", False)),
        incident_jones_vector=parse_jones_pair(opts.get("incident_jones_vector", "linear_x")),
        fiber_mode_jones_vector=parse_jones_pair(opts.get("fiber_mode_jones_vector", "linear_x")),
        receiver_na_x=None if opts.get("receiver_na_x") is None else float(opts["receiver_na_x"]),
        receiver_na_y=None if opts.get("receiver_na_y") is None else float(opts["receiver_na_y"]),
        receiver_medium_refractive_index=float(opts.get("receiver_medium_refractive_index", 1.0)),
        offset_x_mm=float(opts.get("offset_x_mm", 0.0)),
        offset_y_mm=float(opts.get("offset_y_mm", 0.0)),
        tilt_x_rad=_tilt_rad_from_options(opts, "x"),
        tilt_y_rad=_tilt_rad_from_options(opts, "y"),
        field_model=str(opts.get("field_model", "cartesian_pupil_propagation")),
        propagation_model=str(opts.get("propagation_model", "angular_spectrum")),
        propagation_distance_mm=(
            None if opts.get("propagation_distance_mm") is None else float(opts["propagation_distance_mm"])
        ),
        receiver_axial_offset_z_mm=float(
            opts.get("receiver_axial_offset_z_mm", opts.get("axial_offset_z_mm", 0.0))
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
        include_diagnostic_arrays=bool(opts.get("include_diagnostic_arrays", False)),
        result_array_policy=str(opts.get("result_array_policy", "none")),
        output_grid_size=None if opts.get("output_grid_size") is None else int(opts["output_grid_size"]),
        output_extent_x_mm=(
            None if opts.get("output_extent_x_mm") is None else float(opts["output_extent_x_mm"])
        ),
        output_extent_y_mm=(
            None if opts.get("output_extent_y_mm") is None else float(opts["output_extent_y_mm"])
        ),
        sampling_convergence_enabled=bool(opts.get("sampling_convergence_enabled", False)),
        sampling_convergence_grid_sizes=sampling_conv,
        sampling_convergence_tolerance=float(opts.get("sampling_convergence_tolerance", 5.0e-3)),
        issc_oversampling_factor=float(opts.get("issc_oversampling_factor", 1.2)),
        issc_padding_factor=float(opts.get("issc_padding_factor", 0.1)),
        issc_max_virtual_grid=int(opts.get("issc_max_virtual_grid", 2048)),
        include_breakdown=bool(opts.get("include_breakdown", True)),
        include_convergence=bool(opts.get("include_convergence", False)),
        convergence_grid_sizes=conv,
        coherent=bool(opts.get("coherent", True)),
        fiber_core_radius_um=(
            None if opts.get("fiber_core_radius_um") is None else float(opts["fiber_core_radius_um"])
        ),
        fiber_n_core=None if opts.get("fiber_n_core") is None else float(opts["fiber_n_core"]),
        fiber_n_clad=None if opts.get("fiber_n_clad") is None else float(opts["fiber_n_clad"]),
        fiber_length_m=float(opts.get("fiber_length_m", 0.0)),
        fiber_attenuation_db_per_km=float(opts.get("fiber_attenuation_db_per_km", 0.0)),
        fiber_connector_loss_db=float(opts.get("fiber_connector_loss_db", 0.0)),
        finite_difference_refractive_index_map=opts.get("finite_difference_refractive_index_map", None),
        imported_mode_values=opts.get("imported_mode_values", None),
        fiber_mode_index=int(opts.get("fiber_mode_index", 0)),
    )


def _resolve_threshold(request: FiberToleranceOptions, base_eta: float) -> tuple[float, float, str, float]:
    if request.threshold_loss_db is not None:
        loss_db = float(request.threshold_loss_db)
        ratio = relative_efficiency_for_loss_db(loss_db)
        return float(base_eta * ratio), ratio, "relative_loss_db", loss_db
    if request.threshold_relative_efficiency is not None:
        ratio = float(request.threshold_relative_efficiency)
        if not 0.0 < ratio <= 1.0:
            raise ValueError("threshold_relative_efficiency must be in (0, 1]")
        loss_db = float(-10.0 * math.log10(ratio))
        return float(base_eta * ratio), ratio, "relative_efficiency", loss_db
    absolute = float(0.5 if request.threshold_efficiency is None else request.threshold_efficiency)
    if not 0.0 <= absolute <= 1.0:
        raise ValueError("threshold_efficiency must be in [0, 1]")
    ratio = float(absolute / base_eta) if base_eta > 0.0 else 0.0
    loss_db = (
        float(-10.0 * math.log10(max(ratio, _MIN_EFFICIENCY)))
        if ratio > 0.0
        else float("inf")
    )
    return absolute, ratio, "absolute_efficiency", loss_db


def _curve_arrays(scan: AxisScan, base_eta: float, *, relative_valid: bool) -> dict[str, Any]:
    suffix = scan.name.removesuffix("_um").removesuffix("_urad")
    arrays: dict[str, Any] = {
        f"fiber_tolerance_{scan.name}": scan.values.tolist(),
        f"fiber_tolerance_eta_{suffix}": scan.efficiencies.tolist(),
        f"fiber_tolerance_valid_{suffix}": scan.valid_mask.tolist(),
        f"fiber_tolerance_failed_indices_{suffix}": list(scan.failed_indices),
        f"fiber_tolerance_failure_messages_{suffix}": list(scan.failure_messages),
    }
    if relative_valid:
        relative = scan.efficiencies / max(float(base_eta), _MIN_EFFICIENCY)
        arrays[f"fiber_tolerance_eta_rel_{suffix}"] = relative.tolist()
        arrays[f"fiber_tolerance_loss_db_{suffix}"] = np.asarray(
            efficiency_ratio_to_loss_db(relative), dtype=float
        ).tolist()
    return arrays


def _crossing_metrics(prefix: str, result: ThresholdCrossingResult) -> dict[str, Any]:
    return {
        f"{prefix}_root": result.root,
        f"{prefix}_converged": result.converged,
        f"{prefix}_iterations": result.iterations,
        f"{prefix}_function_calls": result.function_calls,
        f"{prefix}_residual": result.residual,
        f"{prefix}_final_bracket_width": result.final_bracket_width,
        f"{prefix}_method": result.method,
        f"{prefix}_status": result.status,
        f"{prefix}_message": result.message,
    }


def _empty_crossing(status: str, message: str, method: str) -> ThresholdCrossingResult:
    return ThresholdCrossingResult(
        root=None,
        bracket=None,
        converged=False,
        iterations=0,
        function_calls=0,
        residual=None,
        final_bracket_width=None,
        method=str(method),
        status=status,
        message=message,
    )


def _solve_scan_crossings(
    scan: AxisScan,
    evaluator: PreparedToleranceEvaluator,
    request: FiberToleranceOptions,
    threshold: float,
    *,
    relative_valid: bool,
) -> tuple[ThresholdCrossingResult, ThresholdCrossingResult]:
    center = int(scan.center_index)
    if not relative_valid and request.threshold_efficiency is None:
        result = _empty_crossing(
            "BASELINE_TOO_LOW",
            "relative/dB threshold disabled because baseline efficiency is too low",
            request.threshold_solver,
        )
        return result, result
    if not scan.valid_mask[center]:
        result = _empty_crossing(
            "INSUFFICIENT_VALID_POINTS",
            "baseline scan point is invalid",
            request.threshold_solver,
        )
        return result, result
    if scan.efficiencies[center] < threshold:
        result = _empty_crossing(
            "ALREADY_BELOW_THRESHOLD_AT_BASELINE",
            "baseline is already below the requested threshold",
            request.threshold_solver,
        )
        return result, result
    negative_bracket, positive_bracket = connected_threshold_brackets(scan, threshold)
    function = lambda value: evaluator.axis_efficiency(scan.name, value)
    common = {
        "threshold": threshold,
        "method": request.threshold_solver,
        "position_xtol": request.threshold_position_xtol,
        "efficiency_ftol": request.threshold_efficiency_ftol,
        "max_iterations": request.threshold_max_iterations,
        "validation_fraction": request.root_validation_fraction,
    }
    return (
        solve_threshold_crossing(
            function,
            bracket=negative_bracket,
            missing_status=(
                "INSUFFICIENT_VALID_POINTS"
                if scan.failed_point_count and negative_bracket is None
                else "NOT_REACHED_WITHIN_SCAN"
            ),
            **common,
        ),
        solve_threshold_crossing(
            function,
            bracket=positive_bracket,
            missing_status=(
                "INSUFFICIENT_VALID_POINTS"
                if scan.failed_point_count and positive_bracket is None
                else "NOT_REACHED_WITHIN_SCAN"
            ),
            **common,
        ),
    )


def _scale_metrics(scales: Any, threshold_ratio: float) -> dict[str, float]:
    q = min(max(float(threshold_ratio), 1.0e-15), 1.0 - 1.0e-15)
    metrics = {
        "fiber_tolerance_mode_radius_x_um": float(scales.mode_radius_x_um),
        "fiber_tolerance_mode_radius_y_um": float(scales.mode_radius_y_um),
        "fiber_tolerance_divergence_x_rad": float(scales.divergence_x_rad),
        "fiber_tolerance_divergence_y_rad": float(scales.divergence_y_rad),
        "fiber_tolerance_divergence_x_urad": float(scales.divergence_x_rad * 1.0e6),
        "fiber_tolerance_divergence_y_urad": float(scales.divergence_y_rad * 1.0e6),
        "fiber_tolerance_rayleigh_range_x_um": float(scales.rayleigh_range_x_um),
        "fiber_tolerance_rayleigh_range_y_um": float(scales.rayleigh_range_y_um),
        "fiber_tolerance_effective_rayleigh_range_um": float(scales.effective_rayleigh_range_um),
    }
    if 0.0 < threshold_ratio < 1.0:
        metrics.update(
            {
                "gaussian_estimated_dx_um_at_threshold": lateral_tolerance_um(
                    mode_radius_um=scales.mode_radius_x_um, relative_efficiency=q
                ),
                "gaussian_estimated_dy_um_at_threshold": lateral_tolerance_um(
                    mode_radius_um=scales.mode_radius_y_um, relative_efficiency=q
                ),
                "gaussian_estimated_tilt_x_urad_at_threshold": angular_tolerance_rad(
                    wavelength_nm=scales.wavelength_vacuum_nm,
                    mode_radius_um=scales.mode_radius_x_um,
                    relative_efficiency=q,
                    refractive_index=scales.refractive_index,
                )
                * 1.0e6,
                "gaussian_estimated_tilt_y_urad_at_threshold": angular_tolerance_rad(
                    wavelength_nm=scales.wavelength_vacuum_nm,
                    mode_radius_um=scales.mode_radius_y_um,
                    relative_efficiency=q,
                    refractive_index=scales.refractive_index,
                )
                * 1.0e6,
                "gaussian_estimated_dz_um_at_threshold": axial_tolerance_um(
                    rayleigh_range_um=scales.effective_rayleigh_range_um,
                    relative_efficiency=q,
                ),
            }
        )
    return metrics


def _fingerprint_request(request: FiberToleranceOptions) -> str:
    payload = asdict(request)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evaluate_fiber_tolerance_typed(
    trace: TraceBundle,
    request: FiberToleranceOptions,
    *,
    cancellation_check: Callable[[], bool] | None = None,
) -> ToleranceAnalysisResult:
    started = time.perf_counter()
    try:
        evaluator = PreparedToleranceEvaluator(trace, request, cancellation_check=cancellation_check)
    except _EXPECTED_NUMERICAL_ERRORS as exc:
        return ToleranceAnalysisResult(
            metrics={
                "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                "fiber_tolerance_setup_failed": True,
            },
            warnings=[f"SETUP_FAILED: {type(exc).__name__}: {exc}"],
            metadata={
                "fiber_tolerance_done": False,
                "status": "SETUP_FAILED",
                "algorithm_version": request.algorithm_version,
            },
        )
    warnings = list(evaluator.problem.warnings)
    if request.auto_align_baseline:
        try:
            alignment = evaluator.auto_align()
        except (AlignmentCancelled, *_EXPECTED_NUMERICAL_ERRORS) as exc:
            status = "CANCELLED" if isinstance(exc, AlignmentCancelled) else "AUTO_ALIGNMENT_FAILED"
            return ToleranceAnalysisResult(
                metrics={
                    "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                    **evaluator.diagnostics(),
                },
                warnings=[*warnings, f"{status}: {type(exc).__name__}: {exc}"],
                metadata={
                    "fiber_tolerance_done": False,
                    "cancelled": status == "CANCELLED",
                    "status": status,
                    "algorithm_version": request.algorithm_version,
                },
            )
        if alignment.cancelled or alignment.timed_out:
            status = "CANCELLED" if alignment.cancelled else "AUTO_ALIGNMENT_TIMED_OUT"
            return ToleranceAnalysisResult(
                metrics={
                    "fiber_tolerance_baseline_efficiency": alignment.initial_efficiency,
                    "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                    **evaluator.diagnostics(),
                },
                warnings=[*warnings, f"{status}: original baseline retained."],
                metadata={
                    "fiber_tolerance_done": False,
                    "cancelled": bool(alignment.cancelled),
                    "timed_out": bool(alignment.timed_out),
                    "status": status,
                    "algorithm_version": request.algorithm_version,
                },
            )
        if not alignment.accepted:
            warnings.append(
                "Baseline auto-alignment result was rejected and the original baseline was retained: "
                f"{alignment.rejection_reason or alignment.message}"
            )

    try:
        base_eta = float(evaluator.base_efficiency)
    except (AlignmentCancelled, *_EXPECTED_NUMERICAL_ERRORS) as exc:
        status = "CANCELLED" if isinstance(exc, AlignmentCancelled) else "BASELINE_EVALUATION_FAILED"
        return ToleranceAnalysisResult(
            metrics={
                "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                "fiber_tolerance_baseline_efficiency": None,
                **evaluator.diagnostics(),
            },
            warnings=[*warnings, f"{status}: {type(exc).__name__}: {exc}"],
            metadata={
                "fiber_tolerance_done": False,
                "cancelled": status == "CANCELLED",
                "status": status,
                "algorithm_version": request.algorithm_version,
            },
        )
    threshold_abs, threshold_ratio, threshold_mode, threshold_loss_db = _resolve_threshold(request, base_eta)
    relative_valid = base_eta >= float(request.baseline_efficiency_minimum)
    if not relative_valid:
        warnings.append(
            "BASELINE_TOO_LOW: absolute efficiency scans are retained, but relative/dB "
            "thresholds, sensitivity and relative-loss results are disabled."
        )

    axes = {
        "dx_um": normalise_axis(
            explicit_values=request.dx_values_um,
            value_range=request.dx_range_um,
            count=request.sample_count,
            scan_mode=request.scan_mode,
        ),
        "dy_um": normalise_axis(
            explicit_values=request.dy_values_um,
            value_range=request.dy_range_um,
            count=request.sample_count,
            scan_mode=request.scan_mode,
        ),
        "dz_um": normalise_axis(
            explicit_values=request.dz_values_um,
            value_range=request.dz_range_um,
            count=request.sample_count,
            scan_mode=request.scan_mode,
        ),
    }
    if request.include_angular_scans:
        axes.update(
            {
                "tilt_x_urad": normalise_axis(
                    explicit_values=request.tilt_x_values_urad,
                    value_range=request.tilt_x_range_urad,
                    count=request.sample_count,
                    scan_mode=request.scan_mode,
                ),
                "tilt_y_urad": normalise_axis(
                    explicit_values=request.tilt_y_values_urad,
                    value_range=request.tilt_y_range_urad,
                    count=request.sample_count,
                    scan_mode=request.scan_mode,
                ),
            }
        )

    scans: dict[str, AxisScan] = {}
    try:
        for name, values in axes.items():
            scans[name] = evaluate_axis(
                name,
                "um" if name.endswith("_um") else "urad",
                values,
                lambda value, n=name: evaluator.axis_efficiency(n, value),
            )
    except AlignmentCancelled:
        return ToleranceAnalysisResult(
            metrics={
                "fiber_tolerance_baseline_efficiency": base_eta,
                "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                **evaluator.diagnostics(),
            },
            warnings=[*warnings, "Tolerance analysis was cancelled."],
            metadata={
                "fiber_tolerance_done": False,
                "cancelled": True,
                "algorithm_version": request.algorithm_version,
            },
        )
    arrays: dict[str, Any] = {}
    metrics: dict[str, Any] = {
        "fiber_tolerance_baseline_efficiency": base_eta,
        "fiber_tolerance_baseline_valid": bool(relative_valid),
        "fiber_tolerance_relative_metrics_enabled": bool(relative_valid),
        "fiber_tolerance_baseline_status": "OK" if relative_valid else "BASELINE_TOO_LOW",
        "fiber_tolerance_threshold_efficiency": threshold_abs,
        "fiber_tolerance_threshold_relative_efficiency": threshold_ratio,
        "fiber_tolerance_threshold_loss_db": threshold_loss_db,
        "fiber_tolerance_threshold_mode": threshold_mode,
        "fiber_tolerance_sample_count_requested": int(request.sample_count),
        "fiber_tolerance_threshold_method": "coarse_scan_plus_bracketed_root",
        "fiber_tolerance_legacy_sampled_metrics_present": True,
    }
    for scan in scans.values():
        if request.include_arrays:
            arrays.update(_curve_arrays(scan, base_eta, relative_valid=relative_valid))
        suffix = scan.name
        metrics[f"fiber_tolerance_{suffix}_valid_point_count"] = scan.valid_point_count
        metrics[f"fiber_tolerance_{suffix}_failed_point_count"] = scan.failed_point_count
        metrics[f"fiber_tolerance_{suffix}_partial_result"] = scan.partial_result
        legacy = legacy_sampled_tolerance(scan, threshold_abs)
        metrics[f"sampled_max_{suffix}_for_eta_ge_threshold"] = legacy
        metrics[f"legacy_sampled_max_{suffix}_for_eta_ge_threshold"] = legacy
        try:
            negative, positive = _solve_scan_crossings(
                scan, evaluator, request, threshold_abs, relative_valid=relative_valid
            )
        except AlignmentCancelled:
            return ToleranceAnalysisResult(
                metrics={
                    **metrics,
                    "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                    **evaluator.diagnostics(),
                },
                arrays=arrays,
                warnings=[*warnings, "Tolerance analysis was cancelled during threshold solving."],
                metadata={
                    "fiber_tolerance_done": False,
                    "cancelled": True,
                    "partial_result": True,
                    "algorithm_version": request.algorithm_version,
                },
            )
        metrics.update(_crossing_metrics(f"fiber_tolerance_negative_{suffix}", negative))
        metrics.update(_crossing_metrics(f"fiber_tolerance_positive_{suffix}", positive))
        roots = [abs(value) for value in (negative.root, positive.root) if value is not None]
        symmetric = min(roots) if len(roots) == 2 else (roots[0] if roots else None)
        
        
        metrics[f"interpolated_negative_{suffix}_for_eta_ge_threshold"] = negative.root
        metrics[f"interpolated_positive_{suffix}_for_eta_ge_threshold"] = positive.root
        metrics[f"interpolated_symmetric_{suffix}_for_eta_ge_threshold"] = symmetric
        metrics[f"root_solved_symmetric_{suffix}_for_eta_ge_threshold"] = symmetric

    if request.include_offset_map:
        dx = scans["dx_um"].values
        dy = scans["dy_um"].values
        try:
            offset_map = np.asarray(
                [
                    [
                        evaluator.evaluate_absolute(
                            offset_x_mm=evaluator.base_x_mm + float(x) * 1.0e-3,
                            offset_y_mm=evaluator.base_y_mm + float(y) * 1.0e-3,
                        )
                        for x in dx
                    ]
                    for y in dy
                ],
                dtype=float,
            )
        except AlignmentCancelled:
            return ToleranceAnalysisResult(
                metrics={
                    **metrics,
                    "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                    **evaluator.diagnostics(),
                },
                arrays=arrays,
                warnings=[*warnings, "Tolerance analysis was cancelled during offset-map evaluation."],
                metadata={
                    "fiber_tolerance_done": False,
                    "cancelled": True,
                    "partial_result": True,
                    "algorithm_version": request.algorithm_version,
                },
            )
        offset_valid = np.isfinite(offset_map)
        metrics["coupling_offset_map_valid_point_count"] = int(np.count_nonzero(offset_valid))
        metrics["coupling_offset_map_failed_point_count"] = int(offset_map.size - np.count_nonzero(offset_valid))
        metrics["coupling_offset_map_partial_result"] = bool(np.any(~offset_valid))
        if np.any(~offset_valid):
            warnings.append(
                "The X-Y offset map contains failed candidate points; invalid values are stored as NaN."
            )
        if request.include_arrays:
            arrays["coupling_offset_map_xy"] = offset_map.tolist()

    base = evaluator.problem.options
    scales = gaussian_tolerance_scales(
        wavelength_nm=base.wavelength_nm,
        mode_field_diameter_x_um=base.mode_field_diameter_x_um,
        mode_field_diameter_y_um=base.mode_field_diameter_y_um,
        refractive_index=base.receiver_medium_refractive_index,
    )
    metrics.update(_scale_metrics(scales, threshold_ratio if relative_valid else 0.0))
    if request.include_theory_curves and request.include_arrays and relative_valid:
        arrays.update(
            {
                "fiber_tolerance_theory_eta_rel_dx": np.asarray(
                    gaussian_lateral_relative_efficiency(scans["dx_um"].values, scales.mode_radius_x_um),
                    dtype=float,
                ).tolist(),
                "fiber_tolerance_theory_eta_rel_dy": np.asarray(
                    gaussian_lateral_relative_efficiency(scans["dy_um"].values, scales.mode_radius_y_um),
                    dtype=float,
                ).tolist(),
                "fiber_tolerance_theory_eta_rel_dz": np.asarray(
                    gaussian_axial_relative_efficiency(
                        scans["dz_um"].values,
                        rayleigh_range_x_um=scales.rayleigh_range_x_um,
                        rayleigh_range_y_um=scales.rayleigh_range_y_um,
                    ),
                    dtype=float,
                ).tolist(),
            }
        )
        if request.include_angular_scans:
            arrays["fiber_tolerance_theory_eta_rel_tilt_x"] = np.asarray(
                gaussian_angular_relative_efficiency(
                    scans["tilt_x_urad"].values * 1.0e-6,
                    wavelength_nm=base.wavelength_nm,
                    mode_radius_um=scales.mode_radius_x_um,
                    refractive_index=scales.refractive_index,
                ),
                dtype=float,
            ).tolist()
            arrays["fiber_tolerance_theory_eta_rel_tilt_y"] = np.asarray(
                gaussian_angular_relative_efficiency(
                    scans["tilt_y_urad"].values * 1.0e-6,
                    wavelength_nm=base.wavelength_nm,
                    mode_radius_um=scales.mode_radius_y_um,
                    refractive_index=scales.refractive_index,
                ),
                dtype=float,
            ).tolist()

    sensitivity_metadata: dict[str, Any] = {}
    sensitivity_result = None
    if request.include_sensitivity_matrix and relative_valid:
        allowed_loss = (
            float(request.sensitivity_allowed_loss_db)
            if request.sensitivity_allowed_loss_db is not None
            else (threshold_loss_db if math.isfinite(threshold_loss_db) else 1.0)
        )
        try:
            sensitivity_result = compute_sensitivity(
                evaluator,
                request,
                base_eta=base_eta,
                allowed_loss_db=allowed_loss,
            )
        except (AlignmentCancelled, *_EXPECTED_NUMERICAL_ERRORS) as exc:
            if isinstance(exc, AlignmentCancelled):
                return ToleranceAnalysisResult(
                    metrics={
                        **metrics,
                        "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                        **evaluator.diagnostics(),
                    },
                    arrays=arrays,
                    warnings=[*warnings, "Tolerance analysis was cancelled during sensitivity evaluation."],
                    metadata={
                        "fiber_tolerance_done": False,
                        "cancelled": True,
                        "partial_result": True,
                        "algorithm_version": request.algorithm_version,
                    },
                )
            metrics["fiber_tolerance_sensitivity_status"] = "NUMERICAL_FAILURE"
            warnings.append(f"Sensitivity analysis skipped after a controlled failure: {type(exc).__name__}: {exc}")
            sensitivity_result = None
        if sensitivity_result is not None:
            metrics.update(sensitivity_result.metrics)
            if request.include_arrays:
                arrays.update(sensitivity_result.arrays)
            warnings.extend(sensitivity_result.warnings)
            sensitivity_metadata.update(sensitivity_result.metadata)

    if request.monte_carlo.enabled and relative_valid:
        mc_threshold = (
            float(request.monte_carlo.threshold_efficiency)
            if request.monte_carlo.threshold_efficiency is not None
            else threshold_abs
        )
        try:
            mc = evaluate_receiver_monte_carlo(
                evaluator,
                request,
                threshold_efficiency=mc_threshold,
            )
        except (AlignmentCancelled, *_EXPECTED_NUMERICAL_ERRORS) as exc:
            if isinstance(exc, AlignmentCancelled):
                return ToleranceAnalysisResult(
                    metrics={
                        **metrics,
                        "fiber_tolerance_runtime_ms": float((time.perf_counter() - started) * 1000.0),
                        **evaluator.diagnostics(),
                    },
                    arrays=arrays,
                    warnings=[*warnings, "Tolerance analysis was cancelled during Monte Carlo evaluation."],
                    metadata={
                        "fiber_tolerance_done": False,
                        "cancelled": True,
                        "partial_result": True,
                        "algorithm_version": request.algorithm_version,
                    },
                )
            metrics["fiber_tolerance_monte_carlo_status"] = "NUMERICAL_FAILURE"
            warnings.append(f"Monte Carlo analysis skipped after a controlled failure: {type(exc).__name__}: {exc}")
        else:
            metrics.update(mc.metrics)
            if request.include_arrays:
                arrays.update(mc.arrays)
            warnings.extend(mc.warnings)
            sensitivity_metadata.update(mc.metadata)

    if sensitivity_result is not None:
        gradient = np.asarray(
            sensitivity_result.arrays["fiber_tolerance_sensitivity_gradient"], dtype=float
        )
        distribution = request.receiver_distribution
        sigma_physical = np.asarray(
            [
                distribution.dx_sigma_um * 1.0e-3,
                distribution.dy_sigma_um * 1.0e-3,
                distribution.dz_sigma_um * 1.0e-3,
                distribution.tilt_x_sigma_urad * 1.0e-6,
                distribution.tilt_y_sigma_urad * 1.0e-6,
            ],
            dtype=float,
        )
        physical_scales = np.asarray(
            sensitivity_result.arrays["fiber_tolerance_sensitivity_physical_scales"], dtype=float
        )
        sigma_dimensionless = sigma_physical / np.maximum(physical_scales, 1.0e-30)
        metrics.update(linear_rss_and_worst_case(gradient, sigma_dimensionless))

    base_field_result = None
    try:
        base_field_result = evaluator.problem.receiver_field(evaluator.base_z_mm)
    except _EXPECTED_NUMERICAL_ERRORS as exc:
        warnings.append(
            f"Final propagation diagnostics were unavailable after a controlled failure: {type(exc).__name__}: {exc}"
        )
    metrics.update(evaluator.diagnostics())
    metrics["fiber_tolerance_runtime_ms"] = float((time.perf_counter() - started) * 1000.0)
    if base_field_result is not None:
        metrics.update(
            {
                "fiber_tolerance_propagation_energy_closure_error": float(
                    base_field_result.metrics.get("propagation_energy_closure_error", 0.0) or 0.0
                ),
                "fiber_tolerance_propagation_edge_power_fraction": float(
                    base_field_result.metrics.get("propagation_edge_power_fraction", 0.0) or 0.0
                ),
                "fiber_tolerance_propagation_nyquist_margin_min": float(
                    base_field_result.metrics.get("propagation_nyquist_margin_min", float("inf"))
                ),
            }
        )
        warnings.extend(base_field_result.warnings)
    evaluator.problem.clear_transient_caches(keep_axial_offsets=(evaluator.base_z_mm,))
    metadata = {
        "fiber_tolerance_done": True,
        "algorithm_version": request.algorithm_version,
        "options_fingerprint": _fingerprint_request(request),
        "trace_fingerprint": evaluator.problem.prepared_pupil.fingerprint,
        "coordinate_system": "right_handed_xyz_optical_axis_plus_z",
        "axis_convention": (
            "dx/dy transverse receiver-mode displacement; dz receiver plane displacement along +z; "
            "tilt_x/tilt_y receiving-mode phase tilt"
        ),
        "threshold_solver": str(request.threshold_solver),
        "threshold_solver_strategy": "coarse connected bracket then derivative-free root solve",
        "prepared_coupling_problem": True,
        "field_reuse_policy": "dx/dy/tilt/MFD reuse receiver field; dz reuses prepared exit pupil",
        "array_storage_recommendation": "large arrays may be saved as compressed NPZ using tolerance.result.save_numeric_arrays_npz",
        "legacy_sampled_tolerance_status": "deprecated_compatibility_only",
        "receiver_medium_refractive_index": float(base.receiver_medium_refractive_index),
        "original_baseline": {
            "offset_x_mm": evaluator.original_base[0],
            "offset_y_mm": evaluator.original_base[1],
            "axial_offset_z_mm": evaluator.original_base[2],
            "tilt_x_rad": evaluator.original_base[3],
            "tilt_y_rad": evaluator.original_base[4],
        },
        "aligned_baseline": {
            "offset_x_mm": evaluator.base_x_mm,
            "offset_y_mm": evaluator.base_y_mm,
            "axial_offset_z_mm": evaluator.base_z_mm,
            "tilt_x_rad": evaluator.base_tx_rad,
            "tilt_y_rad": evaluator.base_ty_rad,
        },
        "scan_center": "aligned_baseline" if evaluator.alignment and evaluator.alignment.accepted else "original_baseline",
        "partial_result": any(scan.partial_result for scan in scans.values()),
        **sensitivity_metadata,
    }
    return ToleranceAnalysisResult(
        metrics=metrics,
        arrays=arrays,
        warnings=list(dict.fromkeys(warnings)),
        metadata=metadata,
    )
