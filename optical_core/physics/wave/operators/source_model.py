from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from optical_core.physics.wave.operators.gaussian_beam import (
    GaussianBeamParameters,
    gaussian_field_at_plane as _gaussian_field_at_plane,
    gaussian_intensity_at_plane as _gaussian_intensity_at_plane,
    sample_gaussian_beam,
    waist_from_divergence,
)


@dataclass(frozen=True, slots=True)
class SourceModel:


    source_type: str = "gaussian"
    wavelength_nm: float = 550.0
    waist_x_mm: float = 0.25
    waist_y_mm: float = 0.25
    divergence_x_rad: float | None = None
    divergence_y_rad: float | None = None
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    amplitude: complex = 1.0 + 0.0j
    phase_rad: float = 0.0
    refractive_index: float = 1.0
    beam_quality_m2: float = 1.0
    beam_quality_m2_x: float | None = None
    beam_quality_m2_y: float | None = None
    waist_position_x_mm: float = 0.0
    waist_position_y_mm: float = 0.0
    axis_tilt_x_rad: float = 0.0
    axis_tilt_y_rad: float = 0.0
    power_drift_fraction: float = 0.0
    amplitude_map: Any | None = None
    phase_map_rad: Any | None = None

    def __post_init__(self) -> None:
        if float(self.beam_quality_m2) < 1.0:
            raise ValueError("beam_quality_m2 must be >= 1.0")
        for value in (self.beam_quality_m2_x, self.beam_quality_m2_y):
            if value is not None and float(value) < 1.0:
                raise ValueError("beam_quality_m2_x/y must be >= 1.0")


def gaussian_parameters_at_first_plane(source: Any) -> GaussianBeamParameters:
    wavelength_nm = float(getattr(source, "wavelength_nm", 550.0))
    refractive_index = float(getattr(source, "refractive_index", 1.0))
    beam_quality_m2 = float(getattr(source, "beam_quality_m2", 1.0))

    waist_x = getattr(source, "waist_x_mm", None)
    waist_y = getattr(source, "waist_y_mm", None)
    if waist_x is None or float(waist_x) <= 0.0:
        div_x = getattr(source, "divergence_x_rad", None) or getattr(source, "object_na_x", None) or 0.1
        waist_x = waist_from_divergence(
            wavelength_nm=wavelength_nm,
            divergence_half_angle_rad=float(div_x),
            refractive_index=refractive_index,
            beam_quality_m2=beam_quality_m2,
        )
    if waist_y is None or float(waist_y) <= 0.0:
        div_y = getattr(source, "divergence_y_rad", None) or getattr(source, "object_na_y", None) or 0.1
        waist_y = waist_from_divergence(
            wavelength_nm=wavelength_nm,
            divergence_half_angle_rad=float(div_y),
            refractive_index=refractive_index,
            beam_quality_m2=beam_quality_m2,
        )

    return GaussianBeamParameters(
        wavelength_nm=wavelength_nm,
        waist_x_mm=float(waist_x),
        waist_y_mm=float(waist_y),
        amplitude=complex(getattr(source, "amplitude", 1.0 + 0.0j)),
        center_x_mm=float(getattr(source, "center_x_mm", 0.0)),
        center_y_mm=float(getattr(source, "center_y_mm", 0.0)),
        phase_rad=float(getattr(source, "phase_rad", 0.0)),
        refractive_index=refractive_index,
        beam_quality_m2=beam_quality_m2,
    )


def gaussian_field_at_first_plane(x_mm: Any, y_mm: Any, source: Any) -> np.ndarray:
    return _gaussian_field_at_plane(x_mm, y_mm, gaussian_parameters_at_first_plane(source))


def gaussian_intensity_at_first_plane(x_mm: Any, y_mm: Any, source: Any) -> np.ndarray:
    return _gaussian_intensity_at_plane(x_mm, y_mm, gaussian_parameters_at_first_plane(source))


def sample_source_field(source: Any, *, grid_size: int = 65, extent_mm: float | None = None) -> dict[str, np.ndarray]:
    advanced = any(
        abs(float(getattr(source, name, 0.0) or 0.0)) > 0.0
        for name in ("waist_position_x_mm", "waist_position_y_mm", "axis_tilt_x_rad", "axis_tilt_y_rad", "power_drift_fraction")
    ) or any(
        getattr(source, name, None) is not None
        for name in ("beam_quality_m2_x", "beam_quality_m2_y", "amplitude_map", "phase_map_rad")
    )
    if advanced or str(getattr(source, "source_type", "")).lower() in {"realistic_gaussian", "measured_gaussian"}:
        from optical_core.models.representations.grid import SamplingGrid2D
        from optical_core.physics.wave.operators.realistic_source import (
            RealisticGaussianSourceParameters,
            realistic_gaussian_field,
        )
        base = gaussian_parameters_at_first_plane(source)
        extent = float(extent_mm if extent_mm is not None else 6.0 * max(base.waist_x_mm, base.waist_y_mm))
        axis = np.linspace(-extent / 2.0, extent / 2.0, max(3, int(grid_size)))
        grid = SamplingGrid2D(x_mm=axis, y_mm=axis, dx_mm=float(axis[1]-axis[0]), dy_mm=float(axis[1]-axis[0]))
        total_power = float(getattr(source, "power_value", 1.0) or 1.0)
        realistic = RealisticGaussianSourceParameters(
            wavelength_nm=base.wavelength_nm, waist_x_mm=base.waist_x_mm, waist_y_mm=base.waist_y_mm,
            waist_position_x_mm=float(getattr(source, "waist_position_x_mm", 0.0)),
            waist_position_y_mm=float(getattr(source, "waist_position_y_mm", 0.0)),
            beam_quality_m2_x=float(getattr(source, "beam_quality_m2_x", None) or base.beam_quality_m2),
            beam_quality_m2_y=float(getattr(source, "beam_quality_m2_y", None) or base.beam_quality_m2),
            center_x_mm=base.center_x_mm, center_y_mm=base.center_y_mm,
            axis_tilt_x_rad=float(getattr(source, "axis_tilt_x_rad", 0.0)),
            axis_tilt_y_rad=float(getattr(source, "axis_tilt_y_rad", 0.0)),
            refractive_index=base.refractive_index, total_power=total_power,
            power_drift_fraction=float(getattr(source, "power_drift_fraction", 0.0)),
            amplitude_map=getattr(source, "amplitude_map", None), phase_map_rad=getattr(source, "phase_map_rad", None),
        )
        field = realistic_gaussian_field(grid, realistic)
        return {"x_mm": axis, "y_mm": axis, "field": field.values, "intensity": np.abs(field.values)**2,
                "axial_z_mm": np.asarray(0.0), "field_normalization": np.asarray("requested_power")}
    params = gaussian_parameters_at_first_plane(source)
    return sample_gaussian_beam(params, grid_size=grid_size, extent_x_mm=extent_mm, extent_y_mm=extent_mm)
