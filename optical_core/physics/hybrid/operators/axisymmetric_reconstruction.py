
# 将二维复场按半径分箱，提取轴对称的振幅、强度和相位径向分布。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(slots=True)
class AxisymmetricReconstructionResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def reconstruct_axisymmetric_field(
    field: ScalarField2D,
    *,
    radial_bins: int = 64,
) -> AxisymmetricReconstructionResult:


    radial_bins = int(max(radial_bins, 4))
    y_axis = np.asarray(field.grid.x_mm, dtype=float)
    z_axis = np.asarray(field.grid.y_mm, dtype=float)
    yy, zz = np.meshgrid(y_axis, z_axis, indexing="xy")
    radius = np.sqrt(yy * yy + zz * zz)
    r_max = float(np.max(radius)) if radius.size else 0.0
    if r_max <= 0.0:
        r_max = max(abs(float(field.grid.dx_mm)), abs(float(field.grid.dy_mm)), 1.0)

    bins = np.linspace(0.0, r_max, radial_bins + 1)
    centers = 0.5 * (bins[:-1] + bins[1:])
    amplitude = np.abs(field.values)
    intensity = amplitude**2
    phase = np.angle(field.values)

    amp_profile: list[float] = []
    int_profile: list[float] = []
    phase_profile: list[float] = []
    counts: list[int] = []

    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (radius >= lo) & (radius < hi)
        count = int(np.count_nonzero(mask))
        counts.append(count)
        if count == 0:
            amp_profile.append(0.0)
            int_profile.append(0.0)
            phase_profile.append(0.0)
        else:
            amp_profile.append(float(np.mean(amplitude[mask])))
            int_profile.append(float(np.mean(intensity[mask])))
            unit_phase = np.exp(1j * phase[mask])
            phase_profile.append(float(np.angle(np.mean(unit_phase))))

    return AxisymmetricReconstructionResult(
        metrics={
            "axisymmetric_radial_bins": radial_bins,
            "axisymmetric_max_radius_mm": r_max,
            "axisymmetric_peak_profile_intensity": float(max(int_profile)) if int_profile else 0.0,
        },
        arrays={
            "axisymmetric_radius_mm": centers.tolist(),
            "axisymmetric_amplitude_profile": amp_profile,
            "axisymmetric_intensity_profile": int_profile,
            "axisymmetric_phase_profile_rad": phase_profile,
            "axisymmetric_bin_counts": counts,
        },
        metadata={"operator": "reconstruct_axisymmetric_field"},
    )
