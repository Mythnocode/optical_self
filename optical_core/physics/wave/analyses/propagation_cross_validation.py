
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.solvers.advanced_propagation import (
    PropagationResult,
    propagate_scaled_angular_spectrum,
    propagate_scaled_fresnel,
)
from optical_core.physics.wave.solvers.matrix_fresnel import propagate_matrix_fresnel
from optical_core.physics.wave.solvers.field_comparison import compare_complex_fields


@dataclass(frozen=True, slots=True)
class PropagationCrossValidationResult:
    scaled_fresnel_vs_matrix: dict[str, Any]
    scaled_angular_spectrum_vs_matrix: dict[str, Any]
    scaled_fresnel_vs_scaled_angular_spectrum: dict[str, Any]
    gates: dict[str, bool]
    shared_grid: dict[str, Any]
    metadata: dict[str, Any]

    @property
    def passed(self) -> bool:
        return all(self.gates.values())

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


def validate_scaled_propagators(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray,
    output_y_mm: np.ndarray,
    zero_padding_factor: float = 2.0,
    sas_transfer_model: str = "fresnel",
    intensity_nrmse_limit: float = 5.0e-3,
    complex_overlap_min: float = 0.995,
    phase_rmse_limit_rad: float = 0.05,
    efficiency_difference_limit: float = 5.0e-3,
    efficiency_evaluator: Any | None = None,
) -> PropagationCrossValidationResult:


    x = np.asarray(output_x_mm, dtype=float)
    y = np.asarray(output_y_mm, dtype=float)
    sf = propagate_scaled_fresnel(
        field, distance_mm, output_x_mm=x, output_y_mm=y,
        edge_power_threshold=1.0, energy_closure_threshold=1.0,
    )
    sas = propagate_scaled_angular_spectrum(
        field, distance_mm, output_x_mm=x, output_y_mm=y,
        zero_padding_factor=zero_padding_factor,
        transfer_model=str(sas_transfer_model),
        edge_power_threshold=1.0, energy_closure_threshold=1.0,
    )
    matrix = propagate_matrix_fresnel(
        field, distance_mm, output_x_mm=x, output_y_mm=y,
        edge_power_threshold=1.0, energy_closure_threshold=1.0,
    )

    def eta(result: PropagationResult) -> float | None:
        return None if efficiency_evaluator is None else float(efficiency_evaluator(result.field))

    eta_sf, eta_sas, eta_matrix = eta(sf), eta(sas), eta(matrix)
    sf_m = compare_complex_fields(sf.field, matrix.field, efficiency_a=eta_sf, efficiency_b=eta_matrix)
    sas_m = compare_complex_fields(sas.field, matrix.field, efficiency_a=eta_sas, efficiency_b=eta_matrix)
    sf_sas = compare_complex_fields(sf.field, sas.field, efficiency_a=eta_sf, efficiency_b=eta_sas)

    comparisons = (sf_m, sas_m, sf_sas)
    gates = {
        "intensity_nrmse": all(item.intensity_nrmse <= intensity_nrmse_limit for item in comparisons),
        "complex_overlap": all(item.complex_overlap >= complex_overlap_min for item in comparisons),
        "phase_rmse_remove_piston_tilt": all(
            np.isfinite(item.phase_rmse_remove_piston_tilt_rad)
            and item.phase_rmse_remove_piston_tilt_rad <= phase_rmse_limit_rad
            for item in comparisons
        ),
        "efficiency_difference": all(
            item.efficiency_difference is None
            or item.efficiency_difference <= efficiency_difference_limit
            for item in comparisons
        ),
    }
    return PropagationCrossValidationResult(
        scaled_fresnel_vs_matrix=sf_m.to_metrics(),
        scaled_angular_spectrum_vs_matrix=sas_m.to_metrics(),
        scaled_fresnel_vs_scaled_angular_spectrum=sf_sas.to_metrics(),
        gates=gates,
        shared_grid={
            "nx": int(x.size), "ny": int(y.size),
            "dx_mm": float(abs(x[1] - x[0])), "dy_mm": float(abs(y[1] - y[0])),
            "extent_x_mm": float(np.ptp(x)), "extent_y_mm": float(np.ptp(y)),
            "distance_mm": float(distance_mm),
        },
        metadata={
            "sas_transfer_model": str(sas_transfer_model),
            "zero_padding_factor": float(zero_padding_factor),
            "scaled_fresnel_engine": sf.metadata.get("fft_engine"),
            "scaled_angular_spectrum_engine": sas.metadata.get("fft_engine"),
            "matrix_reference_fft_used": False,
        },
    )


__all__ = ["PropagationCrossValidationResult", "validate_scaled_propagators"]
