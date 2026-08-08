
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class FieldComparisonDiagnostics:
    intensity_rmse: float
    intensity_nrmse: float
    complex_overlap: float
    phase_rmse_remove_piston_tilt_rad: float
    phase_piston_rad: float
    phase_tilt_x_rad_per_mm: float
    phase_tilt_y_rad_per_mm: float
    efficiency_a: float | None = None
    efficiency_b: float | None = None
    efficiency_difference: float | None = None

    def to_metrics(self) -> dict[str, Any]:
        return asdict(self)


def compare_complex_fields(
    a: ScalarField2D,
    b: ScalarField2D,
    *,
    efficiency_a: float | None = None,
    efficiency_b: float | None = None,
    intensity_floor_fraction: float = 1.0e-6,
) -> FieldComparisonDiagnostics:
    if a.values.shape != b.values.shape or not np.allclose(a.grid.x_mm, b.grid.x_mm) or not np.allclose(a.grid.y_mm, b.grid.y_mm):
        raise ValueError("field comparison requires identical output grids")
    av = np.asarray(a.values, dtype=np.complex128)
    bv = np.asarray(b.values, dtype=np.complex128)
    ia, ib = np.abs(av) ** 2, np.abs(bv) ** 2
    sa, sb = float(np.sum(ia)), float(np.sum(ib))
    if sa > 0:
        ia = ia / sa
    if sb > 0:
        ib = ib / sb
    rmse = float(np.sqrt(np.mean((ia - ib) ** 2)))
    nrmse = float(rmse / max(float(np.max(ia)), float(np.max(ib)), 1.0e-30))
    denom = float(np.sqrt(np.sum(np.abs(av) ** 2) * np.sum(np.abs(bv) ** 2)))
    overlap = float(abs(np.vdot(av, bv)) / denom) if denom > 0 else 0.0

    weight = np.sqrt(ia * ib)
    mask = weight > float(np.max(weight)) * float(intensity_floor_fraction) if weight.size else np.zeros_like(weight, dtype=bool)
    phase_delta = np.angle(bv * np.conjugate(av))
    yy, xx = np.meshgrid(a.grid.y_mm, a.grid.x_mm, indexing="ij")
    if np.count_nonzero(mask) >= 3:
        X = np.column_stack([np.ones(np.count_nonzero(mask)), xx[mask], yy[mask]])
        w = np.sqrt(weight[mask])
        coeff, *_ = np.linalg.lstsq(X * w[:, None], phase_delta[mask] * w, rcond=None)
        residual = np.angle(np.exp(1j * (phase_delta[mask] - X @ coeff)))
        prmse = float(np.sqrt(np.average(residual**2, weights=weight[mask])))
        piston, tx, ty = (float(v) for v in coeff)
    else:
        prmse, piston, tx, ty = float("nan"), 0.0, 0.0, 0.0
    difference = None if efficiency_a is None or efficiency_b is None else float(abs(efficiency_a - efficiency_b))
    return FieldComparisonDiagnostics(
        intensity_rmse=rmse,
        intensity_nrmse=nrmse,
        complex_overlap=overlap,
        phase_rmse_remove_piston_tilt_rad=prmse,
        phase_piston_rad=piston,
        phase_tilt_x_rad_per_mm=tx,
        phase_tilt_y_rad_per_mm=ty,
        efficiency_a=efficiency_a,
        efficiency_b=efficiency_b,
        efficiency_difference=difference,
    )


__all__ = ["FieldComparisonDiagnostics", "compare_complex_fields"]
