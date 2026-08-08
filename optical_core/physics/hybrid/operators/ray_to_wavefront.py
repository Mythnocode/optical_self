
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.operators.opd_reference import (
    common_plane_relative_opl,
    reference_sphere_opd,
)


@dataclass(slots=True)
class WavefrontMap:
    opd_nm: np.ndarray
    phase_rad: np.ndarray
    grid: SamplingGrid2D
    mask: np.ndarray
    wavelength_nm: float
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _sample_opd(
    trace: TraceBundle,
    *,
    reference: str,
    image_refractive_index: float,
    reference_image_point_mm: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, int, str, np.ndarray | None]:
    mode = str(reference or "reference_sphere").strip().lower()
    if mode in {"reference_sphere", "sphere", "explicit_reference_sphere"}:
        result = reference_sphere_opd(
            trace,
            image_refractive_index=image_refractive_index,
            reference_image_point_mm=reference_image_point_mm,
        )
    elif mode in {"common_plane", "chief", "chief_relative", "raw_opl"}:
        result = common_plane_relative_opl(trace)
    else:
        raise ValueError(f"unknown wavefront reference: {reference!r}")
    return (
        np.asarray(result.opd_mm, dtype=float),
        np.asarray(result.valid_mask, dtype=bool),
        int(result.chief_index),
        str(result.reference_type),
        None if result.reference_image_point_mm is None else np.asarray(result.reference_image_point_mm, dtype=float),
    )


def trace_to_wavefront_map(
    trace: TraceBundle,
    *,
    wavelength_nm: float = 550.0,
    grid_size: int = 65,
    extent_mm: float | None = None,
    reference: str = "reference_sphere",
    image_refractive_index: float = 1.0,
    reference_image_point_mm: np.ndarray | None = None,
) -> WavefrontMap:
    grid_size = int(max(grid_size, 3))
    opd_mm, valid, chief_index, reference_type, reference_point = _sample_opd(
        trace,
        reference=reference,
        image_refractive_index=float(image_refractive_index),
        reference_image_point_mm=reference_image_point_mm,
    )

    pupil = getattr(trace, "pupil_coordinates_normalized", None)
    warnings: list[str] = []
    if pupil is not None:
        coords = np.asarray(pupil, dtype=float)
        if coords.shape != (valid.size, 2):
            raise ValueError("TraceBundle pupil coordinates must be (N,2).")
        u = coords[:, 0]
        v = coords[:, 1]
        coordinate_system = "normalized_entrance_pupil"
        axis = np.linspace(-1.0, 1.0, grid_size, dtype=float)
    else:
        positions = np.asarray(trace.final_positions_mm, dtype=float)
        xy = positions[:, 0:2]
        max_abs = float(np.nanmax(np.abs(xy[valid]))) if np.any(valid) else 1.0
        extent = max(float(extent_mm) if extent_mm is not None else max_abs * 1.2, 1.0e-12)
        u = xy[:, 0] / extent
        v = xy[:, 1] / extent
        coordinate_system = "normalized_terminal_plane_fallback"
        warnings.append("Explicit pupil coordinates unavailable; terminal-plane fallback used.")
        axis = np.linspace(-1.0, 1.0, grid_size, dtype=float)

    step = float(axis[1] - axis[0]) if grid_size > 1 else 1.0
    grid = SamplingGrid2D(x_mm=axis, y_mm=axis.copy(), dx_mm=step, dy_mm=step)
    finite = valid & np.isfinite(opd_mm) & np.isfinite(u) & np.isfinite(v)
    finite &= u * u + v * v <= 1.0 + 1.0e-10

    opd_sum = np.zeros((grid_size, grid_size), dtype=float)
    weight_sum = np.zeros((grid_size, grid_size), dtype=float)
    integration_weights = np.asarray(trace.integration_weights, dtype=float)
    if integration_weights.shape != valid.shape:
        integration_weights = np.ones(valid.shape, dtype=float)
    integration_weights = np.where(
        np.isfinite(integration_weights) & (integration_weights > 0.0),
        integration_weights,
        0.0,
    )

    u_idx = np.clip(np.rint((u[finite] + 1.0) * 0.5 * (grid_size - 1)).astype(int), 0, grid_size - 1)
    v_idx = np.clip(np.rint((v[finite] + 1.0) * 0.5 * (grid_size - 1)).astype(int), 0, grid_size - 1)
    opd_nm_samples = opd_mm[finite] * 1.0e6
    sample_integration_weights = integration_weights[finite]
    np.add.at(opd_sum, (v_idx, u_idx), opd_nm_samples * sample_integration_weights)
    np.add.at(weight_sum, (v_idx, u_idx), sample_integration_weights)

    mask = weight_sum > 0.0
    opd_nm = np.full((grid_size, grid_size), np.nan, dtype=float)
    opd_nm[mask] = opd_sum[mask] / weight_sum[mask]
    phase_rad = 2.0 * np.pi * opd_nm / float(wavelength_nm)

    sample_values = opd_nm_samples
    sample_w = sample_integration_weights
    if sample_values.size and np.sum(sample_w) > 0.0:
        mean = float(np.sum(sample_w * sample_values) / np.sum(sample_w))
        rms = float(np.sqrt(np.sum(sample_w * (sample_values - mean) ** 2) / np.sum(sample_w)))
        pv = float(np.max(sample_values) - np.min(sample_values))
    else:
        rms = pv = 0.0

    arrays = {
        "wavefront_opd_nm": np.nan_to_num(opd_nm, nan=0.0).tolist(),
        "wavefront_phase_rad": np.nan_to_num(phase_rad, nan=0.0).tolist(),
        "wavefront_mask": mask.tolist(),
        "wavefront_grid_pupil_x_normalized": axis.tolist(),
        "wavefront_grid_pupil_y_normalized": axis.tolist(),
        "wavefront_sample_opd_nm": (opd_mm * 1.0e6).tolist(),
        "wavefront_sample_valid_mask": finite.tolist(),
        "wavefront_sample_integration_weights": integration_weights.tolist(),
    }
    if pupil is not None:
        arrays["wavefront_sample_pupil_coordinates_normalized"] = np.asarray(pupil, dtype=float).tolist()

    return WavefrontMap(
        opd_nm=opd_nm,
        phase_rad=phase_rad,
        grid=grid,
        mask=mask,
        wavelength_nm=float(wavelength_nm),
        metrics={
            "wavefront_sample_count": int(np.count_nonzero(finite)),
            "wavefront_rms_nm": rms,
            "wavefront_pv_nm": pv,
            "wavefront_rms_waves": rms / float(wavelength_nm),
            "wavefront_pv_waves": pv / float(wavelength_nm),
            "wavefront_chief_ray_index": chief_index,
        },
        arrays=arrays,
        warnings=warnings,
        metadata={
            "operator": "trace_to_wavefront_map",
            "reference": reference_type,
            "coordinate_system": coordinate_system,
            "image_refractive_index": float(image_refractive_index),
            "reference_image_point_mm": None if reference_point is None else reference_point.tolist(),
            "piston_removed_for_rms": True,
            "tilt_removed": False,
            "defocus_removed": False,
        },
    )
