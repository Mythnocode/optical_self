

from __future__ import annotations

FROZEN_COMPATIBILITY_MODULE = True

from dataclasses import replace
import math
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
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions
from optical_core.physics.hybrid.solvers.fiber_coupling import solve_fiber_coupling


_MIN_EFFICIENCY = 1.0e-300
_PARAMETER_NAMES = ("dx", "dy", "dz", "tilt_x", "tilt_y")


def evaluate_fiber_tolerance(trace: TraceBundle, options: dict[str, Any] | None = None) -> dict[str, Any]:


    opts = dict(options or {})
    count = max(int(opts.get("sample_count", opts.get("points", 11))), 3)
    include_offset_map = bool(opts.get("include_offset_map", False))
    include_angular_scans = bool(opts.get("include_angular_scans", True))
    include_theory_curves = bool(opts.get("include_theory_curves", True))
    include_sensitivity = bool(opts.get("include_sensitivity_matrix", False))
    scan_relative = bool(opts.get("scan_relative_to_base_offset", True))

    dx_um = _axis_values(opts.get("dx_um_values"), opts.get("dx_um_range", (-10.0, 10.0)), count)
    dy_um = _axis_values(opts.get("dy_um_values"), opts.get("dy_um_range", (-10.0, 10.0)), count)
    dz_um = _axis_values(opts.get("dz_um_values"), opts.get("dz_um_range", (-200.0, 200.0)), count)
    tilt_x_urad = _axis_values(
        opts.get("tilt_x_urad_values"), opts.get("tilt_x_urad_range", (-100000.0, 100000.0)), count
    )
    tilt_y_urad = _axis_values(
        opts.get("tilt_y_urad_values"), opts.get("tilt_y_urad_range", (-100000.0, 100000.0)), count
    )

    base = _coupling_options_from_dict(opts)
    base_result = solve_fiber_coupling(trace, base)
    base_eta = float(base_result.efficiency)
    threshold_abs, threshold_ratio, threshold_mode, threshold_loss_db = _resolve_threshold(opts, base_eta)

    base_x_mm = float(base.offset_x_mm) if scan_relative else 0.0
    base_y_mm = float(base.offset_y_mm) if scan_relative else 0.0
    base_z_mm = float(base.receiver_axial_offset_z_mm) if scan_relative else 0.0
    base_tx_rad = float(base.tilt_x_rad) if scan_relative else 0.0
    base_ty_rad = float(base.tilt_y_rad) if scan_relative else 0.0

    evaluator = _EfficiencyEvaluator(trace, base)
    dx_eta = [evaluator(offset_x_mm=base_x_mm + float(value) * 1.0e-3) for value in dx_um]
    dy_eta = [evaluator(offset_y_mm=base_y_mm + float(value) * 1.0e-3) for value in dy_um]
    dz_eta = [
        evaluator(receiver_axial_offset_z_mm=base_z_mm + float(value) * 1.0e-3)
        for value in dz_um
    ]
    if include_angular_scans:
        tx_eta = [evaluator(tilt_x_rad=base_tx_rad + float(value) * 1.0e-6) for value in tilt_x_urad]
        ty_eta = [evaluator(tilt_y_rad=base_ty_rad + float(value) * 1.0e-6) for value in tilt_y_urad]
    else:
        tx_eta, ty_eta = [], []

    offset_map = (
        _offset_map(evaluator, dx_um, dy_um, base_x_mm=base_x_mm, base_y_mm=base_y_mm)
        if include_offset_map
        else None
    )

    scales = gaussian_tolerance_scales(
        wavelength_nm=base.wavelength_nm,
        mode_field_diameter_x_um=base.mode_field_diameter_x_um,
        mode_field_diameter_y_um=base.mode_field_diameter_y_um,
        refractive_index=float(opts.get("receiver_medium_refractive_index", 1.0)),
    )

    arrays: dict[str, Any] = {}
    _add_curve(arrays, "dx_um", dx_um, dx_eta, base_eta)
    _add_curve(arrays, "dy_um", dy_um, dy_eta, base_eta)
    _add_curve(arrays, "dz_um", dz_um, dz_eta, base_eta)
    if include_angular_scans:
        _add_curve(arrays, "tilt_x_urad", tilt_x_urad, tx_eta, base_eta)
        _add_curve(arrays, "tilt_y_urad", tilt_y_urad, ty_eta, base_eta)
    if offset_map is not None:
        arrays["coupling_offset_map_xy"] = offset_map

    if include_theory_curves:
        arrays.update(
            {
                "fiber_tolerance_theory_eta_rel_dx": np.asarray(
                    gaussian_lateral_relative_efficiency(dx_um, scales.mode_radius_x_um), dtype=float
                ).tolist(),
                "fiber_tolerance_theory_eta_rel_dy": np.asarray(
                    gaussian_lateral_relative_efficiency(dy_um, scales.mode_radius_y_um), dtype=float
                ).tolist(),
                "fiber_tolerance_theory_eta_rel_dz": np.asarray(
                    gaussian_axial_relative_efficiency(
                        dz_um,
                        rayleigh_range_x_um=scales.rayleigh_range_x_um,
                        rayleigh_range_y_um=scales.rayleigh_range_y_um,
                    ),
                    dtype=float,
                ).tolist(),
            }
        )
        if include_angular_scans:
            arrays["fiber_tolerance_theory_eta_rel_tilt_x"] = np.asarray(
                gaussian_angular_relative_efficiency(
                    tilt_x_urad * 1.0e-6,
                    wavelength_nm=base.wavelength_nm,
                    mode_radius_um=scales.mode_radius_x_um,
                    refractive_index=scales.refractive_index,
                ),
                dtype=float,
            ).tolist()
            arrays["fiber_tolerance_theory_eta_rel_tilt_y"] = np.asarray(
                gaussian_angular_relative_efficiency(
                    tilt_y_urad * 1.0e-6,
                    wavelength_nm=base.wavelength_nm,
                    mode_radius_um=scales.mode_radius_y_um,
                    refractive_index=scales.refractive_index,
                ),
                dtype=float,
            ).tolist()

    metrics: dict[str, Any] = {
        "fiber_tolerance_baseline_efficiency": base_eta,
        "fiber_tolerance_threshold_efficiency": threshold_abs,
        "fiber_tolerance_threshold_relative_efficiency": threshold_ratio,
        "fiber_tolerance_threshold_loss_db": threshold_loss_db,
        "fiber_tolerance_threshold_mode": threshold_mode,
        "sampled_max_dx_um_for_eta_ge_threshold": _symmetric_tolerance(dx_um, dx_eta, threshold_abs),
        "sampled_max_dy_um_for_eta_ge_threshold": _symmetric_tolerance(dy_um, dy_eta, threshold_abs),
        "sampled_max_dz_um_for_eta_ge_threshold": _symmetric_tolerance(dz_um, dz_eta, threshold_abs),
        "fiber_tolerance_sample_count": float(count),
        "fiber_tolerance_include_offset_map": float(include_offset_map),
        "fiber_tolerance_include_angular_scans": float(include_angular_scans),
        "fiber_tolerance_scan_relative_to_base_offset": float(scan_relative),
        
        "fiber_tolerance_threshold_method": "sampled_axis_points_no_interpolation",
        **_scale_metrics(scales, threshold_ratio),
    }
    _add_interpolated_tolerance_metrics(metrics, "dx_um", dx_um, dx_eta, threshold_abs)
    _add_interpolated_tolerance_metrics(metrics, "dy_um", dy_um, dy_eta, threshold_abs)
    _add_interpolated_tolerance_metrics(metrics, "dz_um", dz_um, dz_eta, threshold_abs)
    if include_angular_scans:
        metrics["sampled_max_tilt_x_urad_for_eta_ge_threshold"] = _symmetric_tolerance(
            tilt_x_urad, tx_eta, threshold_abs
        )
        metrics["sampled_max_tilt_y_urad_for_eta_ge_threshold"] = _symmetric_tolerance(
            tilt_y_urad, ty_eta, threshold_abs
        )
        _add_interpolated_tolerance_metrics(metrics, "tilt_x_urad", tilt_x_urad, tx_eta, threshold_abs)
        _add_interpolated_tolerance_metrics(metrics, "tilt_y_urad", tilt_y_urad, ty_eta, threshold_abs)

    warnings = list(base_result.warnings)
    sensitivity_metadata: dict[str, Any] = {}
    if include_sensitivity:
        default_sensitivity_loss_db = threshold_loss_db if math.isfinite(threshold_loss_db) else 1.0
        sensitivity = _local_sensitivity_matrix(
            evaluator=evaluator,
            base_eta=base_eta,
            base=base,
            scales=scales,
            step=float(opts.get("sensitivity_dimensionless_step", 0.05)),
            allowed_loss_db=float(opts.get("sensitivity_allowed_loss_db", default_sensitivity_loss_db)),
        )
        arrays.update(sensitivity["arrays"])
        metrics.update(sensitivity["metrics"])
        warnings.extend(sensitivity["warnings"])
        sensitivity_metadata = sensitivity["metadata"]

    metadata = {
        "fiber_tolerance_done": True,
        "coordinate_system": "right_handed_xyz_optical_axis_plus_z",
        "axis_convention": (
            "dx_um->transverse_x, dy_um->transverse_y, dz_um->receiver_axial_offset_z, "
            "tilt_x_urad/tilt_y_urad->receiving_mode_linear_phase_tilt"
        ),
        "dz_um_model": "scalar_propagation_defocus_scan",
        "axial_scan_parameter": "receiver_axial_offset_z_mm",
        "include_offset_map": include_offset_map,
        "include_angular_scans": include_angular_scans,
        "include_theory_curves": include_theory_curves,
        "include_sensitivity_matrix": include_sensitivity,
        "scan_relative_to_base_offset": scan_relative,
        "base_offset_x_um": float(base.offset_x_mm * 1.0e3),
        "base_offset_y_um": float(base.offset_y_mm * 1.0e3),
        "base_axial_offset_z_um": float(base.receiver_axial_offset_z_mm * 1.0e3),
        "base_tilt_x_urad": float(base.tilt_x_rad * 1.0e6),
        "base_tilt_y_urad": float(base.tilt_y_rad * 1.0e6),
        "theory_reference": (
            "matched scalar Gaussian mode; numerical native complex-field overlap remains authoritative"
        ),
        "tolerance_interpolation": "connected interval around zero with linear threshold crossing",
        **sensitivity_metadata,
    }
    return {"metrics": metrics, "arrays": arrays, "warnings": warnings, "metadata": metadata}


def _coupling_options_from_dict(opts: dict[str, Any]) -> CouplingOptions:
    conv = _int_tuple(opts.get("convergence_grid_sizes", (65, 129, 257)))
    sampling_conv = _int_tuple(opts.get("sampling_convergence_grid_sizes", (257, 513)))
    return CouplingOptions(
        wavelength_nm=float(opts.get("wavelength_nm", 550.0)),
        grid_size=int(opts.get("grid_size", 129)),
        field_extent_mm=opts.get("field_extent_mm", None),
        mode_field_diameter_x_um=float(opts.get("mode_field_diameter_x_um", 10.0)),
        mode_field_diameter_y_um=float(opts.get("mode_field_diameter_y_um", opts.get("mode_field_diameter_x_um", 10.0))),
        receiver_na_x=None if opts.get("receiver_na_x") is None else float(opts["receiver_na_x"]),
        receiver_na_y=None if opts.get("receiver_na_y") is None else float(opts["receiver_na_y"]),
        offset_x_mm=float(opts.get("offset_x_mm", 0.0)),
        offset_y_mm=float(opts.get("offset_y_mm", 0.0)),
        tilt_x_rad=_tilt_rad_from_options(opts, "x"),
        tilt_y_rad=_tilt_rad_from_options(opts, "y"),
        field_model=str(opts.get("field_model", "cartesian_pupil_propagation")),
        propagation_model=str(opts.get("propagation_model", "angular_spectrum")),
        propagation_distance_mm=None if opts.get("propagation_distance_mm") is None else float(opts["propagation_distance_mm"]),
        receiver_axial_offset_z_mm=float(opts.get("receiver_axial_offset_z_mm", opts.get("axial_offset_z_mm", 0.0))),
        sampling_model=str(opts.get("sampling_model", "equal_area_pupil")),
        convergence_enabled=bool(opts.get("convergence_enabled", True)),
        precision_mode=str(opts.get("precision_mode", "balanced")),
        wavefront_fit_order=int(opts.get("wavefront_fit_order", 2)),
        pupil_grid_size=int(opts.get("pupil_grid_size", 257)),
        pupil_extent_scale=float(opts.get("pupil_extent_scale", 1.04)),
        zero_padding_factor=float(opts.get("zero_padding_factor", 2.0)),
            scaled_angular_spectrum_transfer_model=str(opts.get("scaled_angular_spectrum_transfer_model", "fresnel")),
        edge_power_threshold=float(opts.get("edge_power_threshold", 1.0e-4)),
        auto_expand_output=bool(opts.get("auto_expand_output", True)),
        auto_expand_factor=float(opts.get("auto_expand_factor", 1.5)),
        auto_expand_max_steps=int(opts.get("auto_expand_max_steps", 3)),
        output_grid_size=None if opts.get("output_grid_size") is None else int(opts["output_grid_size"]),
        output_extent_x_mm=None if opts.get("output_extent_x_mm") is None else float(opts["output_extent_x_mm"]),
        output_extent_y_mm=None if opts.get("output_extent_y_mm") is None else float(opts["output_extent_y_mm"]),
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
        fiber_core_radius_um=opts.get("fiber_core_radius_um", None),
        fiber_n_core=opts.get("fiber_n_core", None),
        fiber_n_clad=opts.get("fiber_n_clad", None),
        fiber_length_m=float(opts.get("fiber_length_m", 0.0)),
        fiber_attenuation_db_per_km=float(opts.get("fiber_attenuation_db_per_km", 0.0)),
        fiber_connector_loss_db=float(opts.get("fiber_connector_loss_db", 0.0)),
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


def _axis_values(values: Any, value_range: Any, count: int) -> np.ndarray:
    if values is not None:
        arr = np.asarray(values, dtype=float)
        if arr.ndim != 1 or arr.size == 0 or not np.all(np.isfinite(arr)):
            raise ValueError("explicit tolerance axis values must be a finite, non-empty 1-D array")
        return arr
    lo, hi = value_range
    return np.linspace(float(lo), float(hi), int(count), dtype=float)


class _EfficiencyEvaluator:
    def __init__(self, trace: TraceBundle, base: CouplingOptions) -> None:
        self.trace = trace
        self.base = base
        self.cache: dict[tuple[tuple[str, float], ...], float] = {}

    def __call__(self, **kwargs: float) -> float:
        key = tuple(sorted((name, float(value)) for name, value in kwargs.items()))
        if key not in self.cache:
            self.cache[key] = float(solve_fiber_coupling(self.trace, replace(self.base, **kwargs)).efficiency)
        return self.cache[key]


def _offset_map(
    evaluator: Callable[..., float],
    dx_um: np.ndarray,
    dy_um: np.ndarray,
    *,
    base_x_mm: float,
    base_y_mm: float,
) -> list[list[float]]:
    return [
        [
            evaluator(
                offset_x_mm=base_x_mm + float(x_um) * 1.0e-3,
                offset_y_mm=base_y_mm + float(y_um) * 1.0e-3,
            )
            for x_um in dx_um
        ]
        for y_um in dy_um
    ]


def _resolve_threshold(opts: dict[str, Any], base_eta: float) -> tuple[float, float, str, float]:
    if "threshold_loss_db" in opts:
        loss_db = float(opts["threshold_loss_db"])
        ratio = relative_efficiency_for_loss_db(loss_db)
        return float(base_eta * ratio), ratio, "relative_loss_db", loss_db
    if "threshold_relative_efficiency" in opts:
        ratio = float(opts["threshold_relative_efficiency"])
        if not 0.0 < ratio <= 1.0:
            raise ValueError("threshold_relative_efficiency must be in (0, 1]")
        loss_db = float(-10.0 * math.log10(ratio))
        return float(base_eta * ratio), ratio, "relative_efficiency", loss_db
    absolute = float(opts.get("threshold_efficiency", opts.get("threshold", 0.5)))
    if not 0.0 <= absolute <= 1.0:
        raise ValueError("threshold_efficiency must be in [0, 1]")
    ratio = float(absolute / base_eta) if base_eta > 0.0 else 0.0
    loss_db = float(-10.0 * math.log10(max(ratio, _MIN_EFFICIENCY))) if ratio > 0.0 else float("inf")
    return absolute, ratio, "absolute_efficiency", loss_db


def _add_curve(arrays: dict[str, Any], axis_name: str, axis: np.ndarray, eta: list[float], base_eta: float) -> None:
    suffix = axis_name.removesuffix("_um").removesuffix("_urad")
    relative = np.asarray(eta, dtype=float) / max(float(base_eta), _MIN_EFFICIENCY)
    arrays[f"fiber_tolerance_{axis_name}"] = np.asarray(axis, dtype=float).tolist()
    arrays[f"fiber_tolerance_eta_{suffix}"] = [float(value) for value in eta]
    arrays[f"fiber_tolerance_eta_rel_{suffix}"] = relative.tolist()
    arrays[f"fiber_tolerance_loss_db_{suffix}"] = np.asarray(
        efficiency_ratio_to_loss_db(relative), dtype=float
    ).tolist()


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


def _symmetric_tolerance(axis_values: np.ndarray, eta: list[float], threshold: float) -> float | None:
    axis = np.asarray(axis_values, dtype=float)
    values = np.asarray(eta, dtype=float)
    ok = values >= float(threshold)
    if not np.any(ok):
        return None
    return float(np.max(np.abs(axis[ok])))


def _add_interpolated_tolerance_metrics(
    metrics: dict[str, Any],
    axis_name: str,
    axis: np.ndarray,
    eta: list[float],
    threshold: float,
) -> None:
    negative, positive = _connected_threshold_crossings(axis, np.asarray(eta, dtype=float), threshold)
    magnitudes = [abs(value) for value in (negative, positive) if value is not None]
    symmetric = min(magnitudes) if len(magnitudes) == 2 else (magnitudes[0] if magnitudes else None)
    metrics[f"interpolated_negative_{axis_name}_for_eta_ge_threshold"] = negative
    metrics[f"interpolated_positive_{axis_name}_for_eta_ge_threshold"] = positive
    metrics[f"interpolated_symmetric_{axis_name}_for_eta_ge_threshold"] = symmetric


def _connected_threshold_crossings(
    axis_values: np.ndarray,
    eta: np.ndarray,
    threshold: float,
) -> tuple[float | None, float | None]:
    order = np.argsort(axis_values)
    axis = np.asarray(axis_values, dtype=float)[order]
    values = np.asarray(eta, dtype=float)[order]
    if axis.size == 0:
        return None, None
    center = int(np.argmin(np.abs(axis)))
    if values[center] < threshold:
        return None, None

    left = center
    while left > 0 and values[left - 1] >= threshold:
        left -= 1
    right = center
    while right < axis.size - 1 and values[right + 1] >= threshold:
        right += 1

    negative = float(axis[left])
    if left > 0:
        negative = _linear_crossing(axis[left - 1], values[left - 1], axis[left], values[left], threshold)
    positive = float(axis[right])
    if right < axis.size - 1:
        positive = _linear_crossing(axis[right], values[right], axis[right + 1], values[right + 1], threshold)
    return negative, positive


def _linear_crossing(x0: float, y0: float, x1: float, y1: float, threshold: float) -> float:
    if y1 == y0:
        return float(0.5 * (x0 + x1))
    fraction = (float(threshold) - y0) / (y1 - y0)
    return float(x0 + np.clip(fraction, 0.0, 1.0) * (x1 - x0))


def _local_sensitivity_matrix(
    *,
    evaluator: _EfficiencyEvaluator,
    base_eta: float,
    base: CouplingOptions,
    scales: Any,
    step: float,
    allowed_loss_db: float,
) -> dict[str, Any]:
    h = float(step)
    if not math.isfinite(h) or not 0.0 < h <= 0.5:
        raise ValueError("sensitivity_dimensionless_step must be in (0, 0.5]")
    physical_scales = np.asarray(
        [
            scales.mode_radius_x_um * 1.0e-3,
            scales.mode_radius_y_um * 1.0e-3,
            scales.effective_rayleigh_range_um * 1.0e-3,
            scales.divergence_x_rad,
            scales.divergence_y_rad,
        ],
        dtype=float,
    )
    center = np.asarray(
        [
            base.offset_x_mm,
            base.offset_y_mm,
            base.receiver_axial_offset_z_mm,
            base.tilt_x_rad,
            base.tilt_y_rad,
        ],
        dtype=float,
    )
    cache: dict[tuple[float, ...], float] = {}

    def loss(u: np.ndarray) -> float:
        key = tuple(np.round(np.asarray(u, dtype=float), 14))
        if key not in cache:
            physical = center + np.asarray(u, dtype=float) * physical_scales
            eta = evaluator(
                offset_x_mm=float(physical[0]),
                offset_y_mm=float(physical[1]),
                receiver_axial_offset_z_mm=float(physical[2]),
                tilt_x_rad=float(physical[3]),
                tilt_y_rad=float(physical[4]),
            )
            cache[key] = float(-math.log(max(eta, _MIN_EFFICIENCY) / max(base_eta, _MIN_EFFICIENCY)))
        return cache[key]

    n = len(_PARAMETER_NAMES)
    gradient = np.zeros(n, dtype=float)
    matrix = np.zeros((n, n), dtype=float)
    zero = np.zeros(n, dtype=float)
    f0 = loss(zero)
    for i in range(n):
        plus = zero.copy(); plus[i] = h
        minus = zero.copy(); minus[i] = -h
        fp, fm = loss(plus), loss(minus)
        gradient[i] = (fp - fm) / (2.0 * h)
        matrix[i, i] = (fp + fm - 2.0 * f0) / (2.0 * h * h)
    for i in range(n):
        for j in range(i + 1, n):
            pp = zero.copy(); pp[i] = h; pp[j] = h
            pm = zero.copy(); pm[i] = h; pm[j] = -h
            mp = zero.copy(); mp[i] = -h; mp[j] = h
            mm = zero.copy(); mm[i] = -h; mm[j] = -h
            value = (loss(pp) - loss(pm) - loss(mp) + loss(mm)) / (8.0 * h * h)
            matrix[i, j] = matrix[j, i] = value

    matrix = 0.5 * (matrix + matrix.T)
    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    positive = np.maximum(eigenvalues, 0.0)
    natural_limit = math.log(10.0) * max(float(allowed_loss_db), 0.0) / 10.0
    semi_axes = np.asarray(
        [math.sqrt(natural_limit / value) if value > 1.0e-15 else float("inf") for value in positive],
        dtype=float,
    )
    warnings: list[str] = []
    if float(np.linalg.norm(gradient)) > 0.1:
        warnings.append(
            "Tolerance sensitivity baseline is not a local stationary point; linear gradient terms are significant."
        )
    if float(np.min(eigenvalues)) < -0.05:
        warnings.append(
            "Tolerance sensitivity matrix has a negative eigenvalue; reduce the perturbation step or align the baseline."
        )
    return {
        "metrics": {
            "fiber_tolerance_sensitivity_dimensionless_step": h,
            "fiber_tolerance_sensitivity_gradient_norm": float(np.linalg.norm(gradient)),
            "fiber_tolerance_sensitivity_min_eigenvalue": float(np.min(eigenvalues)),
            "fiber_tolerance_sensitivity_max_eigenvalue": float(np.max(eigenvalues)),
            "fiber_tolerance_sensitivity_condition_number_positive": _positive_condition_number(positive),
            "fiber_tolerance_sensitivity_evaluation_count": float(len(cache)),
            "fiber_tolerance_sensitivity_allowed_loss_db": float(allowed_loss_db),
        },
        "arrays": {
            "fiber_tolerance_sensitivity_parameter_names": list(_PARAMETER_NAMES),
            "fiber_tolerance_sensitivity_physical_scales": physical_scales.tolist(),
            "fiber_tolerance_sensitivity_gradient": gradient.tolist(),
            "fiber_tolerance_sensitivity_matrix": matrix.tolist(),
            "fiber_tolerance_sensitivity_eigenvalues": eigenvalues.tolist(),
            "fiber_tolerance_sensitivity_eigenvectors_columns": eigenvectors.tolist(),
            "fiber_tolerance_sensitivity_semi_axes_dimensionless": semi_axes.tolist(),
        },
        "warnings": warnings,
        "metadata": {
            "sensitivity_loss_model": "-ln(eta/eta0) ~= gradient.T*u + u.T*K*u",
            "sensitivity_dimensionless_variables": [
                "dx/mode_radius_x",
                "dy/mode_radius_y",
                "dz/effective_rayleigh_range",
                "tilt_x/divergence_x",
                "tilt_y/divergence_y",
            ],
            "sensitivity_physical_scale_units": ["mm", "mm", "mm", "rad", "rad"],
            "sensitivity_matrix_cross_terms": True,
        },
    }


def _positive_condition_number(values: np.ndarray) -> float:
    positive = np.asarray(values, dtype=float)
    positive = positive[positive > 1.0e-15]
    if positive.size < 2:
        return 1.0 if positive.size == 1 else float("inf")
    return float(np.max(positive) / np.min(positive))
