# 固定光纤平面的宽带耦合。
# 计算多个波长在同一个物理光纤端面位置上的耦合效率
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from typing import Sequence, Any
import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.solvers.coupling_options import CouplingOptions
from optical_core.physics.hybrid.solvers.fiber_coupling import solve_fiber_coupling
from optical_core.physics.hybrid.optimization.engineering_objectives import BroadbandObjectiveWeights


@dataclass(frozen=True, slots=True)
class BroadbandCouplingCase:
    trace: TraceBundle
    options: CouplingOptions
    spectral_weight: float = 1.0


@dataclass(frozen=True, slots=True)
class FixedPlaneBroadbandCouplingResult:
    fixed_plane_offset_z_mm: float
    objective: float
    mean_total_efficiency: float
    spectral_efficiency_range: float
    best_focus_std_mm: float
    wavelengths_nm: tuple[float, ...]
    spectral_weights: tuple[float, ...]
    total_efficiencies: tuple[float, ...]
    field_overlap_efficiencies: tuple[float, ...]
    transmission_efficiencies: tuple[float, ...]
    polarization_efficiencies: tuple[float, ...]
    best_focus_offsets_z_mm: tuple[float, ...]
    per_wavelength: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_fixed_plane_broadband_coupling(
    cases: Sequence[BroadbandCouplingCase],
    *,
    fixed_plane_offset_z_mm: float,
    best_focus_scan_offsets_z_mm: Sequence[float] | None = None,
    objective_weights: BroadbandObjectiveWeights = BroadbandObjectiveWeights(),
    surface_count: int = 0,
    engineering_cost: float = 0.0,
) -> FixedPlaneBroadbandCouplingResult:

    if not cases:
        raise ValueError("at least one broadband coupling case is required")
    raw_weights = np.asarray([float(case.spectral_weight) for case in cases], dtype=float)
    if np.any(~np.isfinite(raw_weights)) or np.any(raw_weights < 0) or float(np.sum(raw_weights)) <= 0:
        raise ValueError("spectral weights must be finite, non-negative and not all zero")
    weights = raw_weights / float(np.sum(raw_weights))
    scan = None if best_focus_scan_offsets_z_mm is None else tuple(float(v) for v in best_focus_scan_offsets_z_mm)

    total: list[float] = []
    field: list[float] = []
    transmission: list[float] = []
    polarization: list[float] = []
    best_focus: list[float] = []
    details: list[dict[str, Any]] = []
    warnings: list[str] = []
    wavelengths: list[float] = []
    for case in cases:
        options = replace(
            case.options,
            receiver_axial_offset_z_mm=float(fixed_plane_offset_z_mm),
            result_array_policy="none",
            include_diagnostic_arrays=False,
            include_convergence=False,
        )
        result = solve_fiber_coupling(case.trace, options)
        wavelengths.append(float(options.wavelength_nm))
        total_eta = float(result.total_efficiency)
        field_eta = float(result.field_overlap_efficiency)
        trans_eta = float(result.metrics.get("transmission_efficiency", 1.0))
        pol_eta = float(result.metrics.get("polarization_overlap_efficiency", 1.0))
        total.append(total_eta)
        field.append(field_eta)
        transmission.append(trans_eta)
        polarization.append(pol_eta)
        warnings.extend(result.warnings)

        best_z = float(fixed_plane_offset_z_mm)
        best_total = total_eta
        if scan:
            for candidate_z in scan:
                candidate = solve_fiber_coupling(
                    case.trace,
                    replace(options, receiver_axial_offset_z_mm=candidate_z),
                )
                if candidate.total_efficiency > best_total:
                    best_total = float(candidate.total_efficiency)
                    best_z = float(candidate_z)
        best_focus.append(best_z)
        details.append({
            "wavelength_nm": float(options.wavelength_nm),
            "fixed_plane_offset_z_mm": float(fixed_plane_offset_z_mm),
            "total_efficiency": total_eta,
            "field_overlap_efficiency": field_eta,
            "transmission_efficiency": trans_eta,
            "polarization_efficiency": pol_eta,
            "best_focus_offset_z_mm_diagnostic": best_z,
            "best_focus_total_efficiency_diagnostic": best_total,
        })

    total_array = np.asarray(total, dtype=float)
    mean_total = float(np.dot(weights, total_array))
    spectral_range = float(np.ptp(total_array))
    focus_std = float(np.std(best_focus))
    objective = (
        -float(objective_weights.mean_total_efficiency) * mean_total
        + float(objective_weights.spectral_range) * spectral_range
        + float(objective_weights.best_focus_std_mm) * focus_std
        + float(objective_weights.surface_count) * int(surface_count)
        + float(objective_weights.engineering_cost) * float(engineering_cost)
    )
    return FixedPlaneBroadbandCouplingResult(
        fixed_plane_offset_z_mm=float(fixed_plane_offset_z_mm),
        objective=float(objective), mean_total_efficiency=mean_total,
        spectral_efficiency_range=spectral_range, best_focus_std_mm=focus_std,
        wavelengths_nm=tuple(wavelengths), spectral_weights=tuple(float(v) for v in weights),
        total_efficiencies=tuple(total), field_overlap_efficiencies=tuple(field),
        transmission_efficiencies=tuple(transmission), polarization_efficiencies=tuple(polarization),
        best_focus_offsets_z_mm=tuple(best_focus), per_wavelength=tuple(details),
        warnings=tuple(dict.fromkeys(warnings)),
    )


__all__ = [
    "BroadbandCouplingCase", "FixedPlaneBroadbandCouplingResult",
    "evaluate_fixed_plane_broadband_coupling",
]
