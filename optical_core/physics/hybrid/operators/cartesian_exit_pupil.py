
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.coordinates import X_INDEX, Y_INDEX, Z_INDEX
from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import (
    FieldNormalization,
    PowerUnit,
    ScalarField2D,
)
from optical_core.models.representations.trace import PlaneTraceData, TraceBundle


@dataclass(slots=True)
class CartesianExitPupilResult:
    field: ScalarField2D
    propagation_distance_mm: float
    image_plane_z_mm: float
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _last_physical_record(trace: TraceBundle) -> PlaneTraceData:
    candidates: list[tuple[int, PlaneTraceData]] = []
    for name, record in dict(getattr(trace, "surface_records", {}) or {}).items():
        if not name.startswith("surface_"):
            continue
        try:
            number = int(name.split("_", 1)[1])
        except Exception:
            continue
        candidates.append((number, record))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    
    
    
    exit_pupil = dict(getattr(trace, "plane_records", {}) or {}).get("exit_pupil")
    if exit_pupil is not None:
        return exit_pupil
    raise ValueError(
        "Cartesian exit-pupil reconstruction requires recorded physical surfaces "
        "or an explicit plane_records['exit_pupil'] record."
    )


def _chief_index(trace: TraceBundle, valid: np.ndarray) -> int:
    indices = np.flatnonzero(valid)
    if indices.size == 0:
        return -1
    pupil = getattr(trace, "pupil_coordinates_normalized", None)
    if pupil is not None:
        coords = np.asarray(pupil, dtype=float)
        if coords.shape[0] == valid.size:
            return int(indices[np.argmin(np.sum(coords[indices] ** 2, axis=1))])
    return int(indices[0])


def _collapse_duplicate_samples(
    points_xy: np.ndarray,
    *sample_arrays: np.ndarray,
    decimals: int = 12,
) -> tuple[np.ndarray, tuple[np.ndarray, ...], int]:


    points = np.asarray(points_xy, dtype=float)
    rounded = np.round(points, decimals=decimals)
    unique, inverse = np.unique(rounded, axis=0, return_inverse=True)
    collapsed: list[np.ndarray] = []
    counts = np.bincount(inverse, minlength=unique.shape[0]).astype(float)
    for raw in sample_arrays:
        values = np.asarray(raw)
        trailing_shape = values.shape[1:]
        flat = values.reshape(values.shape[0], -1)
        summed = np.zeros((unique.shape[0], flat.shape[1]), dtype=values.dtype)
        np.add.at(summed, inverse, flat)
        averaged = summed / counts[:, None]
        collapsed.append(averaged.reshape((unique.shape[0], *trailing_shape)))
    return unique, tuple(collapsed), int(points.shape[0] - unique.shape[0])


def _interpolate_scattered(
    points_xy: np.ndarray,
    values: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    fill_value: float | complex,
) -> tuple[np.ndarray, np.ndarray, str]:


    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
    try:
        from scipy.spatial import QhullError
    except ImportError:  
        QhullError = RuntimeError  

    points = np.asarray(points_xy, dtype=float)
    sample_values = np.asarray(values)
    xx, yy = np.meshgrid(grid_x, grid_y, indexing="xy")
    query = np.column_stack([xx.ravel(), yy.ravel()])
    centered = points - np.mean(points, axis=0, keepdims=True)
    rank = int(np.linalg.matrix_rank(centered, tol=1.0e-12))
    method = "linear_nd"
    try:
        if rank < 2 or np.ptp(points[:, 0]) <= 1.0e-14 or np.ptp(points[:, 1]) <= 1.0e-14:
            raise ValueError("scattered point set is not genuinely two-dimensional")
        interpolator = LinearNDInterpolator(points, sample_values, fill_value=np.nan)
        result = np.asarray(interpolator(query)).reshape(yy.shape)
    except (QhullError, ValueError, FloatingPointError):
        method = "nearest_fallback"
        nearest = NearestNDInterpolator(points, sample_values)
        result = np.asarray(nearest(query)).reshape(yy.shape)
    mask = np.isfinite(result)
    return np.where(mask, result, fill_value), mask, method


def _fill_inside_support_nearest(
    points_xy: np.ndarray,
    sample_values: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    interpolated: np.ndarray,
    interpolation_mask: np.ndarray,
    support_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:


    missing = np.asarray(support_mask, dtype=bool) & ~np.asarray(interpolation_mask, dtype=bool)
    if not np.any(missing):
        return np.asarray(interpolated).copy(), missing
    from scipy.interpolate import NearestNDInterpolator

    xx, yy = np.meshgrid(grid_x, grid_y, indexing="xy")
    query = np.column_stack([xx[missing], yy[missing]])
    nearest = NearestNDInterpolator(np.asarray(points_xy, dtype=float), np.asarray(sample_values))
    filled = np.asarray(interpolated).copy()
    filled[missing] = nearest(query)
    return filled, missing


def _polynomial_powers(degree: int) -> list[tuple[int, int]]:
    return [(i, j) for i in range(degree + 1) for j in range(degree + 1 - i)]


def _fit_opl_polynomial(
    points_xy: np.ndarray,
    values_mm: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    radial_order: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:


    xy = np.asarray(points_xy, dtype=float)
    values = np.asarray(values_mm, dtype=float)
    scale_x = max(float(np.max(np.abs(xy[:, 0]))), 1.0e-12)
    scale_y = max(float(np.max(np.abs(xy[:, 1]))), 1.0e-12)
    xn = xy[:, 0] / scale_x
    yn = xy[:, 1] / scale_y
    requested_degree = max(2, 2 * int(radial_order))
    selected: tuple[int, list[tuple[int, int]], np.ndarray, int, float] | None = None
    for degree in range(requested_degree, -1, -1):
        powers = _polynomial_powers(degree)
        if len(powers) > values.size:
            continue
        design = np.column_stack([xn**i * yn**j for i, j in powers])
        rank = int(np.linalg.matrix_rank(design))
        condition = float(np.linalg.cond(design))
        if rank == len(powers) and np.isfinite(condition) and condition <= 1.0e12:
            selected = (degree, powers, design, rank, condition)
            break
    fallback = selected is None
    if fallback:
        degree = 0
        powers = [(0, 0)]
        design = np.ones((values.size, 1), dtype=float)
        rank = 1
        condition = 1.0
    else:
        degree, powers, design, rank, condition = selected
    coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
    if not np.all(np.isfinite(coefficients)):
        coefficients = np.asarray([float(np.nanmean(values))], dtype=float)
        degree = 0
        powers = [(0, 0)]
        design = np.ones((values.size, 1), dtype=float)
        rank = 1
        condition = 1.0
        fallback = True
    fitted_samples = design @ coefficients
    residual = fitted_samples - values

    xx, yy = np.meshgrid(grid_x, grid_y, indexing="xy")
    xxn = xx / scale_x
    yyn = yy / scale_y
    grid = np.zeros_like(xx, dtype=float)
    for coefficient, (i, j) in zip(coefficients, powers, strict=True):
        grid += float(coefficient) * xxn**i * yyn**j
    return grid, residual, {
        "requested_degree": requested_degree,
        "degree": degree,
        "term_count": len(powers),
        "design_rank": rank,
        "design_condition_number": condition,
        "automatic_order_reduction": bool(degree < requested_degree),
        "constant_fallback": fallback,
        "scale_x_mm": scale_x,
        "scale_y_mm": scale_y,
        "rms_residual_nm": float(np.sqrt(np.mean(residual**2)) * 1.0e6),
        "max_residual_nm": float(np.max(np.abs(residual)) * 1.0e6),
    }


def reconstruct_cartesian_exit_pupil(
    trace: TraceBundle,
    *,
    wavelength_nm: float,
    image_refractive_index: float = 1.0,
    grid_size: int = 257,
    extent_scale: float = 1.04,
    opl_fit_order: int = 2,
    amplitude_weighting: str = "quadrature",
    plane_clearance_mm: float = 1.0e-7,
    normalize_power: bool = False,
    include_arrays: bool = True,
) -> CartesianExitPupilResult:


    record = _last_physical_record(trace)
    points = np.asarray(record.positions_mm, dtype=float)
    directions = np.asarray(record.directions, dtype=float)
    opl = np.asarray(record.optical_paths_mm, dtype=float)
    field_amplitudes = np.asarray(record.field_amplitudes, dtype=float)
    quadrature_weights = np.asarray(record.quadrature_weights, dtype=float)
    phase_offsets = np.asarray(getattr(record, "phase_offsets_rad", np.zeros_like(opl)), dtype=float)
    polarization_vectors = np.asarray(
        getattr(record, "polarization_vectors_xyz", np.column_stack([np.ones_like(opl), np.zeros_like(opl), np.zeros_like(opl)])),
        dtype=np.complex128,
    )
    valid = np.asarray(record.valid_mask, dtype=bool).copy()
    valid &= np.all(np.isfinite(points), axis=1)
    valid &= np.all(np.isfinite(directions), axis=1)
    valid &= np.isfinite(opl) & np.isfinite(field_amplitudes) & np.isfinite(quadrature_weights)
    valid &= np.isfinite(phase_offsets)
    valid &= np.all(np.isfinite(polarization_vectors), axis=1)
    direction_norms = np.linalg.norm(directions, axis=1)
    valid &= np.isfinite(direction_norms) & (direction_norms > 1.0e-14)
    directions = directions.copy()
    directions[valid] /= direction_norms[valid, None]
    valid &= np.abs(directions[:, Z_INDEX]) > 1.0e-14
    if np.count_nonzero(valid) < 6:
        raise ValueError("At least six valid native rays are required for Cartesian reconstruction.")

    exit_plane_z = float(np.max(points[valid, Z_INDEX]) + max(float(plane_clearance_mm), 0.0))
    t = np.full(valid.shape, np.nan, dtype=float)
    t[valid] = (exit_plane_z - points[valid, Z_INDEX]) / directions[valid, Z_INDEX]
    valid &= np.isfinite(t) & (t >= -1.0e-12)
    if np.count_nonzero(valid) < 6:
        raise ValueError("Fewer than six rays can be projected to the common exit plane.")
    projected = points.copy()
    projected[valid] = points[valid] + t[valid, None] * directions[valid]
    plane_opl = np.full(opl.shape, np.nan, dtype=float)
    wavelength_mm = float(wavelength_nm) * 1.0e-6
    phase_equivalent_opl = phase_offsets * wavelength_mm / (2.0 * np.pi)
    plane_opl[valid] = opl[valid] + phase_equivalent_opl[valid] + float(image_refractive_index) * t[valid]

    final_positions = np.asarray(trace.final_positions_mm, dtype=float)
    final_valid = np.asarray(trace.valid_mask, dtype=bool)
    image_plane_z = float(np.nanmedian(final_positions[final_valid, Z_INDEX]))
    propagation_distance = image_plane_z - exit_plane_z
    if propagation_distance <= 0.0:
        raise ValueError(
            f"Image plane z={image_plane_z:.9g} mm is not after exit plane "
            f"z={exit_plane_z:.9g} mm."
        )

    xy = projected[valid][:, [X_INDEX, Y_INDEX]]
    max_x = float(np.max(np.abs(xy[:, 0])))
    max_y = float(np.max(np.abs(xy[:, 1])))
    extent_x = max(max_x * float(extent_scale), 1.0e-9)
    extent_y = max(max_y * float(extent_scale), 1.0e-9)
    n = max(int(grid_size), 17)
    if n % 2 == 0:
        n += 1
    x_axis = np.linspace(-extent_x, extent_x, n, dtype=float)
    y_axis = np.linspace(-extent_y, extent_y, n, dtype=float)
    dx = float(x_axis[1] - x_axis[0])
    dy = float(y_axis[1] - y_axis[0])

    chief = _chief_index(trace, valid)
    reference_opl = (
        float(plane_opl[chief])
        if chief >= 0 and np.isfinite(plane_opl[chief])
        else float(np.nanmean(plane_opl[valid]))
    )
    relative_opl = plane_opl[valid] - reference_opl
    weighting = str(amplitude_weighting).strip().lower()
    if weighting not in {"field", "quadrature", "flux"}:
        raise ValueError("amplitude_weighting must be field, quadrature, or flux")
    amplitude_samples = np.maximum(field_amplitudes[valid], 0.0)
    positive_q = quadrature_weights[valid][quadrature_weights[valid] > 0.0]
    q_reference = float(np.median(positive_q)) if positive_q.size else 1.0
    if weighting in {"quadrature", "flux"}:
        q_factor = np.maximum(quadrature_weights[valid], 0.0) / max(q_reference, 1.0e-30)
        amplitude_samples = amplitude_samples * np.sqrt(q_factor)
    obliquity_reference = 1.0
    if weighting == "flux":
        obliquity = np.abs(directions[valid, Z_INDEX])
        positive_obliquity = obliquity[obliquity > 0.0]
        obliquity_reference = float(np.median(positive_obliquity)) if positive_obliquity.size else 1.0
        amplitude_samples = amplitude_samples * np.sqrt(
            obliquity / max(obliquity_reference, 1.0e-30)
        )
    xy_interpolation, collapsed, duplicate_count = _collapse_duplicate_samples(
        xy,
        amplitude_samples,
        relative_opl,
        polarization_vectors[valid],
    )
    amplitude_samples_interpolation, relative_opl_interpolation, polarization_samples_interpolation = collapsed
    amplitude_grid, amplitude_mask, amplitude_interpolation_method = _interpolate_scattered(
        xy_interpolation,
        amplitude_samples_interpolation,
        x_axis,
        y_axis,
        fill_value=0.0,
    )
    xx_grid, yy_grid = np.meshgrid(x_axis, y_axis, indexing="xy")
    physical_pupil_mask = (
        (xx_grid / max(max_x, 1.0e-30)) ** 2
        + (yy_grid / max(max_y, 1.0e-30)) ** 2
        <= 1.0 + 1.0e-12
    )
    amplitude_grid, amplitude_support_fill_mask = _fill_inside_support_nearest(
        xy_interpolation,
        amplitude_samples_interpolation,
        x_axis,
        y_axis,
        amplitude_grid,
        amplitude_mask,
        physical_pupil_mask,
    )
    opl_grid, opl_fit_residual, opl_fit = _fit_opl_polynomial(
        xy_interpolation,
        relative_opl_interpolation,
        x_axis,
        y_axis,
        radial_order=int(opl_fit_order),
    )
    mask = physical_pupil_mask & (amplitude_grid > 0.0)
    phase_grid = 2.0 * np.pi * opl_grid / wavelength_mm
    values = np.zeros((n, n), dtype=np.complex128)
    values[mask] = amplitude_grid[mask] * np.exp(1j * phase_grid[mask])
    power = float(np.sum(np.abs(values) ** 2) * abs(dx * dy))
    if not np.isfinite(power):
        raise FloatingPointError("Cartesian exit-pupil reconstruction produced non-finite field power")
    negligible_power = bool(power <= 1.0e-30)
    normalization = FieldNormalization.ARBITRARY
    if normalize_power and not negligible_power:
        values /= np.sqrt(power)
        power = 1.0
        normalization = FieldNormalization.UNIT_POWER

    grid = SamplingGrid2D(x_mm=x_axis, y_mm=y_axis, dx_mm=dx, dy_mm=dy)
    field = ScalarField2D(
        values=values,
        grid=grid,
        wavelength_nm=float(wavelength_nm),
        refractive_index=float(image_refractive_index),
        z_mm=exit_plane_z,
        integrated_power=power,
        power_unit=PowerUnit.ARBITRARY,
        normalization=normalization,
    )
    
    
    
    
    polarization_grids: list[np.ndarray] = []
    if include_arrays:
        for component in range(3):
            component_samples = polarization_samples_interpolation[:, component]
            component_grid, component_mask, _ = _interpolate_scattered(
                xy_interpolation,
                component_samples,
                x_axis,
                y_axis,
                fill_value=0.0 + 0.0j,
            )
            component_grid, _ = _fill_inside_support_nearest(
                xy_interpolation,
                component_samples,
                x_axis,
                y_axis,
                component_grid,
                component_mask,
                physical_pupil_mask,
            )
            polarization_grids.append(np.asarray(component_grid, dtype=np.complex128))
        pol_norm = np.sqrt(sum(np.abs(component) ** 2 for component in polarization_grids))
        nonzero_pol = pol_norm > 1.0e-30
        for index in range(3):
            polarization_grids[index] = np.where(
                nonzero_pol,
                polarization_grids[index] / np.maximum(pol_norm, 1.0e-30),
                0.0 + 0.0j,
            )

    interpolation_residual = np.asarray(opl_fit_residual, dtype=float)
    warnings: list[str] = []
    support_fill_fraction = float(
        np.count_nonzero(amplitude_support_fill_mask)
        / max(np.count_nonzero(physical_pupil_mask), 1)
    )
    if negligible_power:
        warnings.append("ZERO_OR_NEGLIGIBLE_FIELD_POWER: reconstructed exit-pupil field power is effectively zero.")
    if duplicate_count > 0:
        warnings.append(f"Merged {duplicate_count} duplicate/near-duplicate exit-pupil samples before interpolation.")
    if amplitude_interpolation_method != "linear_nd":
        warnings.append("Exit-pupil scattered interpolation used nearest-neighbour fallback because the sample geometry was degenerate.")
    if bool(opl_fit.get("automatic_order_reduction")):
        warnings.append(
            f"Exit-pupil OPL fit order was reduced from degree {opl_fit['requested_degree']} to {opl_fit['degree']} for stability."
        )
    if support_fill_fraction > 0.20:
        warnings.append("Exit-pupil support fill exceeds 20%; reconstruction is low confidence.")
    elif support_fill_fraction > 0.05:
        warnings.append("Exit-pupil support fill exceeds 5%; inspect sampling/support quality.")
    if np.count_nonzero(mask) < 0.5 * mask.size:
        warnings.append("Exit-pupil field occupies less than half of the Cartesian grid; padding may be excessive.")
    rms_opl_nm = float(np.sqrt(np.mean(interpolation_residual**2)) * 1.0e6)
    if rms_opl_nm > float(wavelength_nm) / 100.0:
        warnings.append(f"Exit-plane OPL interpolation RMS is {rms_opl_nm:.3g} nm.")

    return CartesianExitPupilResult(
        field=field,
        propagation_distance_mm=float(propagation_distance),
        image_plane_z_mm=float(image_plane_z),
        metrics={
            "exit_plane_z_mm": exit_plane_z,
            "image_plane_z_mm": image_plane_z,
            "exit_to_image_distance_mm": float(propagation_distance),
            "exit_pupil_grid_size": n,
            "exit_pupil_amplitude_weighting": weighting,
            "exit_pupil_quadrature_weight_reference": q_reference,
            "exit_pupil_obliquity_reference": obliquity_reference,
            "exit_pupil_amplitude_sample_min": float(np.min(amplitude_samples)),
            "exit_pupil_amplitude_sample_max": float(np.max(amplitude_samples)),
            "exit_pupil_extent_x_mm": extent_x,
            "exit_pupil_extent_y_mm": extent_y,
            "exit_pupil_valid_ray_count": int(np.count_nonzero(valid)),
            "exit_pupil_mask_fraction": float(np.count_nonzero(mask) / mask.size),
            "exit_pupil_physical_support_fraction": float(np.count_nonzero(physical_pupil_mask) / physical_pupil_mask.size),
            "exit_pupil_support_fill_fraction": float(np.count_nonzero(amplitude_support_fill_mask) / physical_pupil_mask.size),
            "exit_pupil_support_fill_fraction_of_pupil": support_fill_fraction,
            "exit_pupil_reconstruction_fallback": amplitude_interpolation_method != "linear_nd",
            "exit_pupil_interpolation_method": amplitude_interpolation_method,
            "exit_pupil_duplicate_sample_count": int(duplicate_count),
            "exit_pupil_zero_or_negligible_power": negligible_power,
            "exit_pupil_power_a.u.": power,
            "exit_pupil_peak_intensity_a.u.": float(np.max(np.abs(values) ** 2)) if values.size else 0.0,
            "exit_pupil_opl_interpolation_rms_nm": rms_opl_nm,
            "exit_pupil_opl_fit_max_residual_nm": float(opl_fit["max_residual_nm"]),
            "exit_pupil_opl_fit_degree": int(opl_fit["degree"]),
            "exit_pupil_opl_fit_term_count": int(opl_fit["term_count"]),
            "exit_pupil_opl_fit_requested_degree": int(opl_fit["requested_degree"]),
            "exit_pupil_opl_fit_design_rank": int(opl_fit["design_rank"]),
            "exit_pupil_opl_fit_condition_number": float(opl_fit["design_condition_number"]),
            "exit_pupil_opl_fit_automatic_order_reduction": bool(opl_fit["automatic_order_reduction"]),
            "exit_pupil_sample_phase_span_rad": float(np.ptp(2.0 * np.pi * relative_opl / wavelength_mm)),
            "exit_pupil_surface_phase_span_rad": float(np.ptp(phase_offsets[valid])),
            "exit_pupil_mean_polarization_x_power": float(np.mean(np.abs(polarization_vectors[valid, 0]) ** 2)),
            "exit_pupil_mean_polarization_y_power": float(np.mean(np.abs(polarization_vectors[valid, 1]) ** 2)),
            "exit_pupil_mean_polarization_z_power": float(np.mean(np.abs(polarization_vectors[valid, 2]) ** 2)),
        },
        arrays=(
            {
                "exit_pupil_field_real": np.real(values),
                "exit_pupil_field_imag": np.imag(values),
                "exit_pupil_intensity_a.u.": np.abs(values) ** 2,
                "exit_pupil_phase_rad": np.angle(values),
                "exit_pupil_mask": mask,
                "exit_pupil_grid_x_mm": x_axis,
                "exit_pupil_grid_y_mm": y_axis,
                "exit_plane_sample_x_mm": xy[:, 0],
                "exit_plane_sample_y_mm": xy[:, 1],
                "exit_plane_sample_relative_opl_mm": relative_opl,
                "exit_plane_sample_surface_phase_rad": phase_offsets[valid],
                "exit_pupil_polarization_x_real": np.real(polarization_grids[0]),
                "exit_pupil_polarization_x_imag": np.imag(polarization_grids[0]),
                "exit_pupil_polarization_y_real": np.real(polarization_grids[1]),
                "exit_pupil_polarization_y_imag": np.imag(polarization_grids[1]),
                "exit_pupil_polarization_z_real": np.real(polarization_grids[2]),
                "exit_pupil_polarization_z_imag": np.imag(polarization_grids[2]),
            }
            if include_arrays
            else {}
        ),
        warnings=warnings,
        metadata={
            "operator": "reconstruct_cartesian_exit_pupil",
            "coordinate_system": "right-handed XYZ; optical axis +z; transverse x-y",
            "phase_source": "native_accumulated_opl_plus_surface_complex_phase_projected_to_common_exit_plane",
            "amplitude_source": "native_source_field_amplitudes_after_surface_transmission",
            "polarization_source": "native_surface_interaction_polarization_vectors",
            "interpolation": f"{amplitude_interpolation_method}_amplitude_with_physical_pupil_fill_plus_adaptive_native_unwrapped_opl_polynomial",
            "pupil_support_model": "ellipse_from_projected_native_marginal_rays",
            "opl_fit": opl_fit,
            "reference_independent": True,
            "zemax_data_used_as_input": False,
            "diagnostic_arrays_included": bool(include_arrays),
        },
    )


__all__ = ["CartesianExitPupilResult", "reconstruct_cartesian_exit_pupil"]
