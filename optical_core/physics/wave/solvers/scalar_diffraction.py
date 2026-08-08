from __future__ import annotations

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.propagation import PropagationPlan, default_propagation_registry
from optical_core.physics.wave.solvers.propagation_options import PropagationOptions


def make_sampling_grid(grid_size: int, extent_mm: float) -> SamplingGrid2D:
    if grid_size < 5:
        raise ValueError("grid_size 至少为 5。")
    if extent_mm <= 0:
        raise ValueError("extent_mm 必须为正数。")
    axis = np.linspace(-extent_mm, extent_mm, int(grid_size), dtype=float)
    step = float(axis[1] - axis[0])
    return SamplingGrid2D(x_mm=axis, y_mm=axis.copy(), dx_mm=step, dy_mm=step)


def field_from_aperture_options(options: PropagationOptions) -> ScalarField2D:
    options.validate()
    grid = make_sampling_grid(options.grid_size, options.extent_mm)
    x, y = np.meshgrid(grid.x_mm, grid.y_mm, indexing="xy")
    r = np.sqrt(x**2 + y**2)

    if options.aperture_type == "circular":
        values = (r <= options.aperture_diameter_mm / 2.0).astype(np.complex128)
    elif options.aperture_type == "rectangular":
        values = ((np.abs(x) <= options.aperture_width_mm / 2.0) & (np.abs(y) <= options.aperture_height_mm / 2.0)).astype(np.complex128)
    elif options.aperture_type == "single_slit":
        values = (np.abs(x) <= options.slit_width_mm / 2.0).astype(np.complex128)
    elif options.aperture_type == "gaussian":
        waist = max(float(options.gaussian_waist_mm), 1e-12)
        values = np.exp(-(r**2) / (waist**2)).astype(np.complex128)
    elif options.aperture_type == "uniform":
        values = np.ones((options.grid_size, options.grid_size), dtype=np.complex128)
    else:
        raise ValueError(f"未知孔径类型: {options.aperture_type!r}")

    return ScalarField2D(
        values=values,
        grid=grid,
        wavelength_nm=float(options.wavelength_nm),
        refractive_index=float(options.refractive_index),
        z_mm=0.0,
        integrated_power=float(np.sum(np.abs(values) ** 2) * abs(grid.dx_mm * grid.dy_mm)),
    )


def propagate_scalar_field(field: ScalarField2D, options: PropagationOptions) -> ScalarField2D:
    options.validate()
    propagated = default_propagation_registry().propagate(
        field,
        PropagationPlan(
            method=str(options.method),
            distance_mm=float(options.propagation_distance_mm),
            options={
                "normalize": bool(options.normalize),
                "zero_padding_factor": float(options.zero_padding_factor),
                "edge_power_threshold": float(options.edge_power_threshold),
                "energy_closure_threshold": float(
                    options.energy_closure_threshold
                ),
                "nyquist_margin_min": float(options.nyquist_margin_min),
            },
        ),
    )
    output = getattr(propagated, "field", propagated)

    if options.normalize:
        peak = float(np.max(np.abs(output.values) ** 2))
        if peak > 0:
            normalized_values = output.values / np.sqrt(peak)
            output = output.__class__(
                values=normalized_values,
                grid=output.grid,
                wavelength_nm=output.wavelength_nm,
                refractive_index=output.refractive_index,
                z_mm=output.z_mm,
                integrated_power=float(np.sum(np.abs(normalized_values) ** 2) * abs(output.grid.dx_mm * output.grid.dy_mm)),
            )
    return output
