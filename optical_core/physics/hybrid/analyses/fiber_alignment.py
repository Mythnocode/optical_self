
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.analyses.fiber_tolerance import _coupling_options_from_dict
from optical_core.physics.hybrid.solvers.fiber_coupling import CouplingNumericalGateError
from optical_core.physics.hybrid.tolerance.evaluator import (
    AlignmentCancelled,
    PreparedToleranceEvaluator,
)
from optical_core.physics.hybrid.tolerance.models import FiberToleranceOptions


_EXPECTED_NUMERICAL_ERRORS = (
    ValueError,
    FloatingPointError,
    OverflowError,
    MemoryError,
    CouplingNumericalGateError,
)


def _cancellation_checker(cancellation: Any | None) -> Callable[[], bool] | None:
    if cancellation is None:
        return None

    def checker() -> bool:
        value = getattr(cancellation, "is_cancelled", False)
        return bool(value() if callable(value) else value)

    return checker


def _symmetric_range(
    opts: dict[str, Any],
    *,
    range_key: str,
    max_key: str,
    fallback: float,
) -> tuple[float, float]:
    if range_key in opts:
        raw = tuple(float(value) for value in opts[range_key])
        if len(raw) != 2:
            raise ValueError(f"{range_key} must contain exactly two values")
        return raw
    radius = abs(float(opts.get(max_key, fallback)))
    return (-radius, radius)


def evaluate_fiber_alignment(
    trace: TraceBundle,
    options: dict[str, Any] | None = None,
    *,
    cancellation: Any | None = None,
) -> dict[str, Any]:


    opts = dict(options or {})
    method = str(opts.get("method", "powell")).strip().lower().replace("-", "_")
    if method not in {"powell", "stable_powell", "prepared_powell"}:
        raise ValueError(
            "stable fiber_alignment supports Powell only; "
            f"unsupported method {opts.get('method')!r}"
        )

    base = _coupling_options_from_dict(opts)
    initial_x_mm = float(
        opts.get("initial_offset_x_um", opts.get("initial_x_um", base.offset_x_mm * 1.0e3))
    ) * 1.0e-3
    initial_y_mm = float(
        opts.get("initial_offset_y_um", opts.get("initial_y_um", base.offset_y_mm * 1.0e3))
    ) * 1.0e-3
    initial_tx_rad = _initial_tilt_rad(opts, "x", base.tilt_x_rad)
    initial_ty_rad = _initial_tilt_rad(opts, "y", base.tilt_y_rad)
    initial_z_mm = float(
        opts.get(
            "initial_axial_offset_z_um",
            opts.get("initial_z_um", base.receiver_axial_offset_z_mm * 1.0e3),
        )
    ) * 1.0e-3
    base = replace(
        base,
        offset_x_mm=initial_x_mm,
        offset_y_mm=initial_y_mm,
        receiver_axial_offset_z_mm=initial_z_mm,
        tilt_x_rad=initial_tx_rad,
        tilt_y_rad=initial_ty_rad,
    )

    max_offset_um = abs(float(opts.get("max_offset_um", 20.0)))
    max_tilt_urad = abs(float(opts.get("max_tilt_urad", 5000.0)))
    max_axial_um = abs(float(opts.get("max_axial_offset_um", 200.0)))
    request_mapping = {
        **opts,
        "dx_um_range": _symmetric_range(
            opts, range_key="dx_um_range", max_key="max_offset_x_um", fallback=max_offset_um
        ),
        "dy_um_range": _symmetric_range(
            opts, range_key="dy_um_range", max_key="max_offset_y_um", fallback=max_offset_um
        ),
        "dz_um_range": _symmetric_range(
            opts, range_key="dz_um_range", max_key="max_axial_offset_um", fallback=max_axial_um
        ),
        "tilt_x_urad_range": _symmetric_range(
            opts, range_key="tilt_x_urad_range", max_key="max_tilt_x_urad", fallback=max_tilt_urad
        ),
        "tilt_y_urad_range": _symmetric_range(
            opts, range_key="tilt_y_urad_range", max_key="max_tilt_y_urad", fallback=max_tilt_urad
        ),
        "auto_align_include_dz": bool(opts.get("include_dz", opts.get("auto_align_include_dz", False))),
        "auto_align_focus_only": bool(opts.get("focus_only", opts.get("auto_align_focus_only", False))),
        "auto_align_max_iterations": int(opts.get("max_iterations", opts.get("auto_align_max_iterations", 40))),
        "auto_align_max_function_evaluations": int(
            opts.get("max_function_evaluations", opts.get("auto_align_max_function_evaluations", 300))
        ),
        "auto_align_xtol": float(opts.get("xtol", opts.get("auto_align_xtol", 1.0e-3))),
        "auto_align_ftol": float(opts.get("ftol", opts.get("auto_align_ftol", 1.0e-6))),
        "auto_align_timeout_seconds": opts.get(
            "timeout_seconds", opts.get("auto_align_timeout_seconds", 60.0)
        ),
        "tolerance_lightweight_mode": bool(opts.get("alignment_lightweight_mode", True)),
        "include_arrays": False,
    }

    warnings: list[str] = []
    if bool(opts.get("return_history", False)):
        warnings.append(
            "Powell alignment does not retain full candidate field/history arrays in stable mode."
        )

    try:
        request = FiberToleranceOptions.from_mapping(request_mapping, base)
        evaluator = PreparedToleranceEvaluator(
            trace,
            request,
            cancellation_check=_cancellation_checker(cancellation),
        )
        alignment = evaluator.auto_align()
    except AlignmentCancelled as exc:
        return {
            "metrics": {
                "fiber_alignment_result_accepted": False,
                "fiber_alignment_optimizer_converged": False,
            },
            "arrays": {},
            "warnings": [*warnings, f"Alignment cancelled: {exc}"],
            "metadata": {
                "fiber_alignment_done": False,
                "cancelled": True,
                "status": "CANCELLED",
                "fiber_alignment_method": "powell",
            },
        }
    except _EXPECTED_NUMERICAL_ERRORS as exc:
        return {
            "metrics": {
                "fiber_alignment_result_accepted": False,
                "fiber_alignment_optimizer_converged": False,
            },
            "arrays": {},
            "warnings": [*warnings, f"ALIGNMENT_FAILED: {type(exc).__name__}: {exc}"],
            "metadata": {
                "fiber_alignment_done": False,
                "cancelled": False,
                "status": "ALIGNMENT_FAILED",
                "fiber_alignment_method": "powell",
            },
        }

    if alignment.cancelled or alignment.timed_out:
        status = "CANCELLED" if alignment.cancelled else "TIMED_OUT"
        return {
            "metrics": {
                "fiber_alignment_initial_efficiency": float(alignment.initial_efficiency),
                "fiber_alignment_best_efficiency": float(alignment.efficiency),
                "fiber_alignment_result_accepted": False,
                "fiber_alignment_optimizer_converged": False,
                "fiber_alignment_iterations": int(alignment.iterations),
                "fiber_alignment_function_evaluations": int(alignment.function_evaluations),
            },
            "arrays": {},
            "warnings": [*warnings, f"Alignment {status.lower()}; original state retained."],
            "metadata": {
                "fiber_alignment_done": False,
                "cancelled": bool(alignment.cancelled),
                "timed_out": bool(alignment.timed_out),
                "status": status,
                "fiber_alignment_method": "powell",
            },
        }

    if not alignment.accepted:
        warnings.append(
            "Powell did not produce an acceptable improvement; the original alignment state was retained: "
            f"{alignment.rejection_reason or alignment.message}"
        )

    metrics = {
        "fiber_alignment_initial_efficiency": float(alignment.initial_efficiency),
        "fiber_alignment_best_efficiency": float(alignment.efficiency),
        "fiber_alignment_efficiency_improvement": float(
            alignment.efficiency - alignment.initial_efficiency
        ),
        "fiber_alignment_optimizer_converged": bool(alignment.converged),
        "fiber_alignment_result_accepted": bool(alignment.accepted),
        "fiber_alignment_best_offset_x_um": float(alignment.offset_x_mm * 1.0e3),
        "fiber_alignment_best_offset_y_um": float(alignment.offset_y_mm * 1.0e3),
        "fiber_alignment_best_axial_offset_z_um": float(alignment.axial_offset_z_mm * 1.0e3),
        "fiber_alignment_best_tilt_x_rad": float(alignment.tilt_x_rad),
        "fiber_alignment_best_tilt_y_rad": float(alignment.tilt_y_rad),
        "fiber_alignment_best_tilt_x_urad": float(alignment.tilt_x_rad * 1.0e6),
        "fiber_alignment_best_tilt_y_urad": float(alignment.tilt_y_rad * 1.0e6),
        "fiber_alignment_initial_offset_x_um": float(initial_x_mm * 1.0e3),
        "fiber_alignment_initial_offset_y_um": float(initial_y_mm * 1.0e3),
        "fiber_alignment_initial_axial_offset_z_um": float(initial_z_mm * 1.0e3),
        "fiber_alignment_initial_tilt_x_urad": float(initial_tx_rad * 1.0e6),
        "fiber_alignment_initial_tilt_y_urad": float(initial_ty_rad * 1.0e6),
        "fiber_alignment_iterations": int(alignment.iterations),
        "fiber_alignment_function_evaluations": int(alignment.function_evaluations),
        "fiber_alignment_failed_evaluations": int(alignment.failed_evaluations),
        **evaluator.diagnostics(),
    }
    metadata = {
        "fiber_alignment_done": True,
        "fiber_alignment_method": "powell",
        "fiber_alignment_algorithm_version": "stable-powell-1.0",
        "coordinate_system": "right_handed_xyz_optical_axis_plus_z",
        "alignment_variables": list(alignment.active_axes),
        "tilt_model": "receiving_mode_linear_phase_ramp",
        "optimizer_converged": bool(alignment.converged),
        "alignment_result_accepted": bool(alignment.accepted),
        "rejection_reason": alignment.rejection_reason,
        "cancelled": bool(alignment.cancelled),
        "timed_out": bool(alignment.timed_out),
        "algorithm_chain": (
            "PreparedCouplingProblem -> bounded dimensionless SciPy Powell -> "
            "finite/bounds/non-degradation validation -> accept or rollback"
        ),
        "model_note": (
            "Alignment optimizes receiving-mode transverse offsets, optional axial receiver-plane "
            "position, and angular phase tilts. It does not retrace a mechanically moved fibre."
        ),
        "history_retained": False,
    }
    return {
        "metrics": metrics,
        "arrays": {},
        "warnings": list(dict.fromkeys([*warnings, *evaluator.problem.warnings])),
        "metadata": metadata,
    }


def _initial_tilt_rad(opts: dict[str, Any], axis: str, fallback: float) -> float:
    for key in (f"initial_tilt_{axis}_rad", f"tilt_{axis}_rad"):
        if key in opts:
            return float(opts[key])
    for key in (f"initial_tilt_{axis}_urad", f"tilt_{axis}_urad"):
        if key in opts:
            return float(opts[key]) * 1.0e-6
    return float(fallback)
