
from __future__ import annotations

from typing import Any

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.solvers.fiber_coupling import (
    solve_fiber_coupling as _ORIGINAL_SOLVE_FIBER_COUPLING,
)
from optical_core.physics.hybrid.tolerance import (
    FiberToleranceOptions,
    coupling_options_from_mapping,
    evaluate_fiber_tolerance_typed,
)



solve_fiber_coupling = _ORIGINAL_SOLVE_FIBER_COUPLING


def _coupling_options_from_dict(options: dict[str, Any] | None = None):


    return coupling_options_from_mapping(dict(options or {}))


def evaluate_fiber_tolerance(
    trace: TraceBundle,
    options: dict[str, Any] | None = None,
    *,
    cancellation: Any | None = None,
) -> dict[str, Any]:
    opts = dict(options or {})

    
    
    if solve_fiber_coupling is not _ORIGINAL_SOLVE_FIBER_COUPLING:
        from optical_core.physics.hybrid.analyses import _legacy_fiber_tolerance

        _legacy_fiber_tolerance.solve_fiber_coupling = solve_fiber_coupling
        return _legacy_fiber_tolerance.evaluate_fiber_tolerance(trace, opts)

    coupling = coupling_options_from_mapping(opts)
    request = FiberToleranceOptions.from_mapping(opts, coupling)
    cancellation_check = None
    if cancellation is not None:
        def cancellation_check() -> bool:
            value = getattr(cancellation, "is_cancelled", False)
            return bool(value() if callable(value) else value)
    result = evaluate_fiber_tolerance_typed(
        trace,
        request,
        cancellation_check=cancellation_check,
    ).to_mapping()

    
    
    metadata = result["metadata"]
    metadata.update(
        {
            "dz_um_model": "scalar_propagation_defocus_scan",
            "axial_scan_parameter": "receiver_axial_offset_z_mm",
            "include_offset_map": request.include_offset_map,
            "include_angular_scans": request.include_angular_scans,
            "include_theory_curves": request.include_theory_curves,
            "include_sensitivity_matrix": request.include_sensitivity_matrix,
            "scan_relative_to_base_offset": request.scan_relative_to_base_offset,
            "base_offset_x_um": float(coupling.offset_x_mm * 1.0e3),
            "base_offset_y_um": float(coupling.offset_y_mm * 1.0e3),
            "base_axial_offset_z_um": float(coupling.receiver_axial_offset_z_mm * 1.0e3),
            "base_tilt_x_urad": float(coupling.tilt_x_rad * 1.0e6),
            "base_tilt_y_urad": float(coupling.tilt_y_rad * 1.0e6),
            "tolerance_interpolation": "deprecated alias; values are now bracketed root solutions",
        }
    )
    metrics = result["metrics"]
    metrics.update(
        {
            "fiber_tolerance_sample_count": float(request.sample_count),
            "fiber_tolerance_include_offset_map": float(request.include_offset_map),
            "fiber_tolerance_include_angular_scans": float(request.include_angular_scans),
            "fiber_tolerance_scan_relative_to_base_offset": float(
                request.scan_relative_to_base_offset
            ),
            "fiber_tolerance_threshold_method": "coarse_scan_plus_bracketed_root",
            "fiber_tolerance_threshold_solver_method": str(request.threshold_solver),
            
            "legacy_fiber_tolerance_threshold_method": "sampled_axis_points_no_interpolation",
        }
    )
    arrays = result["arrays"]
    if "fiber_tolerance_sensitivity_hessian" in arrays:
        arrays.setdefault(
            "fiber_tolerance_sensitivity_matrix",
            arrays["fiber_tolerance_sensitivity_hessian"],
        )
        arrays.setdefault(
            "fiber_tolerance_sensitivity_eigenvalues",
            arrays.get("fiber_tolerance_sensitivity_raw_eigenvalues", []),
        )
        arrays.setdefault(
            "fiber_tolerance_sensitivity_eigenvectors_columns",
            arrays.get("fiber_tolerance_sensitivity_eigenvectors_columns", []),
        )
    return result


__all__ = ["evaluate_fiber_tolerance", "solve_fiber_coupling", "_coupling_options_from_dict"]
