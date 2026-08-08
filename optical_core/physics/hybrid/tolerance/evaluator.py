
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.analyses.coupling_tolerance_theory import gaussian_tolerance_scales
from optical_core.physics.hybrid.solvers.fiber_coupling import (
    CouplingNumericalGateError,
    PreparedCouplingProblem,
    prepare_fiber_coupling,
)
from .models import FiberToleranceOptions


class AlignmentCancelled(RuntimeError):
    pass


class AlignmentTimedOut(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    offset_x_mm: float
    offset_y_mm: float
    axial_offset_z_mm: float
    tilt_x_rad: float
    tilt_y_rad: float
    efficiency: float
    initial_efficiency: float
    converged: bool
    accepted: bool
    iterations: int
    function_evaluations: int
    method: str
    message: str
    active_axes: tuple[str, ...] = ()
    failed_evaluations: int = 0
    last_failure: str | None = None
    rejection_reason: str | None = None
    cancelled: bool = False
    timed_out: bool = False


class PreparedToleranceEvaluator:


    def __init__(
        self,
        trace: TraceBundle,
        options: FiberToleranceOptions,
        *,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> None:
        self.request = options
        self.problem: PreparedCouplingProblem = prepare_fiber_coupling(trace, options.coupling)
        base = self.problem.options
        self.original_base = (
            float(base.offset_x_mm),
            float(base.offset_y_mm),
            float(base.receiver_axial_offset_z_mm),
            float(base.tilt_x_rad),
            float(base.tilt_y_rad),
        )
        (
            self.base_x_mm,
            self.base_y_mm,
            self.base_z_mm,
            self.base_tx_rad,
            self.base_ty_rad,
        ) = self.original_base
        self.alignment: AlignmentResult | None = None
        self.failed_evaluation_count = 0
        self.last_evaluation_failure: str | None = None
        self.cancellation_check = cancellation_check

    def _cancelled(self) -> bool:
        if self.cancellation_check is None:
            return False
        try:
            return bool(self.cancellation_check())
        except Exception:
            return False

    def _record_failure(self, exc: BaseException | str) -> None:
        self.failed_evaluation_count += 1
        if isinstance(exc, str):
            self.last_evaluation_failure = exc
        else:
            self.last_evaluation_failure = f"{type(exc).__name__}: {exc}"

    def _safe_efficiency(self, **kwargs: float | None) -> float:
        if self._cancelled():
            raise AlignmentCancelled("tolerance task cancelled")
        try:
            eta = float(self.problem.efficiency(**kwargs))
        except (ValueError, FloatingPointError, OverflowError, MemoryError, CouplingNumericalGateError) as exc:
            self._record_failure(exc)
            return float("nan")
        if not np.isfinite(eta):
            self._record_failure("non_finite_efficiency")
            return float("nan")
        if eta < -1.0e-12 or eta > 1.0 + 1.0e-8:
            self._record_failure(f"efficiency_out_of_range:{eta:.9g}")
            return float("nan")
        return min(max(eta, 0.0), 1.0)

    @property
    def base_efficiency(self) -> float:
        eta = self._safe_efficiency(
            offset_x_mm=self.base_x_mm,
            offset_y_mm=self.base_y_mm,
            receiver_axial_offset_z_mm=self.base_z_mm,
            tilt_x_rad=self.base_tx_rad,
            tilt_y_rad=self.base_ty_rad,
        )
        if not np.isfinite(eta):
            raise FloatingPointError(
                f"baseline coupling efficiency is invalid: {self.last_evaluation_failure}"
            )
        return eta

    def evaluate_absolute(
        self,
        *,
        offset_x_mm: float | None = None,
        offset_y_mm: float | None = None,
        axial_offset_z_mm: float | None = None,
        tilt_x_rad: float | None = None,
        tilt_y_rad: float | None = None,
        mode_field_diameter_x_um: float | None = None,
        mode_field_diameter_y_um: float | None = None,
    ) -> float:
        return self._safe_efficiency(
            offset_x_mm=self.base_x_mm if offset_x_mm is None else float(offset_x_mm),
            offset_y_mm=self.base_y_mm if offset_y_mm is None else float(offset_y_mm),
            receiver_axial_offset_z_mm=self.base_z_mm if axial_offset_z_mm is None else float(axial_offset_z_mm),
            tilt_x_rad=self.base_tx_rad if tilt_x_rad is None else float(tilt_x_rad),
            tilt_y_rad=self.base_ty_rad if tilt_y_rad is None else float(tilt_y_rad),
            mode_field_diameter_x_um=mode_field_diameter_x_um,
            mode_field_diameter_y_um=mode_field_diameter_y_um,
        )

    def axis_efficiency(self, axis: str, value: float) -> float:
        relative = bool(self.request.scan_relative_to_base_offset)
        x0 = self.base_x_mm if relative else 0.0
        y0 = self.base_y_mm if relative else 0.0
        z0 = self.base_z_mm if relative else 0.0
        tx0 = self.base_tx_rad if relative else 0.0
        ty0 = self.base_ty_rad if relative else 0.0
        if axis == "dx_um":
            return self.evaluate_absolute(offset_x_mm=x0 + float(value) * 1.0e-3)
        if axis == "dy_um":
            return self.evaluate_absolute(offset_y_mm=y0 + float(value) * 1.0e-3)
        if axis == "dz_um":
            return self.evaluate_absolute(axial_offset_z_mm=z0 + float(value) * 1.0e-3)
        if axis == "tilt_x_urad":
            return self.evaluate_absolute(tilt_x_rad=tx0 + float(value) * 1.0e-6)
        if axis == "tilt_y_urad":
            return self.evaluate_absolute(tilt_y_rad=ty0 + float(value) * 1.0e-6)
        raise KeyError(f"unknown tolerance axis: {axis}")

    def _physical_bounds(self, center: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        request = self.request
        deltas_lo = np.asarray(
            [
                request.dx_range_um[0] * 1.0e-3,
                request.dy_range_um[0] * 1.0e-3,
                request.dz_range_um[0] * 1.0e-3,
                request.tilt_x_range_urad[0] * 1.0e-6,
                request.tilt_y_range_urad[0] * 1.0e-6,
            ],
            dtype=float,
        )
        deltas_hi = np.asarray(
            [
                request.dx_range_um[1] * 1.0e-3,
                request.dy_range_um[1] * 1.0e-3,
                request.dz_range_um[1] * 1.0e-3,
                request.tilt_x_range_urad[1] * 1.0e-6,
                request.tilt_y_range_urad[1] * 1.0e-6,
            ],
            dtype=float,
        )
        return center + deltas_lo, center + deltas_hi

    def auto_align(self) -> AlignmentResult:


        from scipy.optimize import minimize

        base = self.problem.options
        scales = gaussian_tolerance_scales(
            wavelength_nm=base.wavelength_nm,
            mode_field_diameter_x_um=base.mode_field_diameter_x_um,
            mode_field_diameter_y_um=base.mode_field_diameter_y_um,
            refractive_index=base.receiver_medium_refractive_index,
        )
        physical_scales = np.asarray(
            [
                max(scales.mode_radius_x_um * 1.0e-3, 1.0e-9),
                max(scales.mode_radius_y_um * 1.0e-3, 1.0e-9),
                max(scales.effective_rayleigh_range_um * 1.0e-3, 1.0e-9),
                max(scales.divergence_x_rad, 1.0e-12),
                max(scales.divergence_y_rad, 1.0e-12),
            ],
            dtype=float,
        )
        center = np.asarray(
            [self.base_x_mm, self.base_y_mm, self.base_z_mm, self.base_tx_rad, self.base_ty_rad],
            dtype=float,
        )
        axis_names = ("dx", "dy", "dz", "tilt_x", "tilt_y")
        if self.request.auto_align_focus_only:
            active = [2]
        else:
            active = [0, 1, 3, 4]
            if self.request.auto_align_include_dz:
                active.insert(2, 2)
        active_axes = tuple(axis_names[index] for index in active)

        initial_eta = self.base_efficiency
        lower_physical, upper_physical = self._physical_bounds(center)
        lower_u = (lower_physical - center) / physical_scales
        upper_u = (upper_physical - center) / physical_scales
        
        
        lower_u = np.minimum(lower_u, 0.0)
        upper_u = np.maximum(upper_u, 0.0)
        lower_physical = center + lower_u * physical_scales
        upper_physical = center + upper_u * physical_scales
        bounds = [(float(lower_u[index]), float(upper_u[index])) for index in active]
        deadline = (
            None
            if self.request.auto_align_timeout_seconds is None
            else time.monotonic() + float(self.request.auto_align_timeout_seconds)
        )
        local_failed_before = self.failed_evaluation_count

        def objective(u_active: np.ndarray) -> float:
            if self._cancelled():
                raise AlignmentCancelled("Powell alignment cancelled")
            if deadline is not None and time.monotonic() > deadline:
                raise AlignmentTimedOut("Powell alignment exceeded time limit")
            u_active = np.asarray(u_active, dtype=float)
            if u_active.shape != (len(active),) or not np.all(np.isfinite(u_active)):
                self._record_failure("non_finite_optimizer_coordinates")
                return 1.0e3
            for value, (lo, hi) in zip(u_active, bounds, strict=True):
                if value < lo or value > hi:
                    return 1.0e3 + float(np.sum(u_active**2))
            u = np.zeros(5, dtype=float)
            u[active] = u_active
            values = center + u * physical_scales
            if np.any(values < lower_physical - 1.0e-15) or np.any(values > upper_physical + 1.0e-15):
                return 1.0e3 + float(np.sum(u_active**2))
            eta = self._safe_efficiency(
                offset_x_mm=float(values[0]),
                offset_y_mm=float(values[1]),
                receiver_axial_offset_z_mm=float(values[2]),
                tilt_x_rad=float(values[3]),
                tilt_y_rad=float(values[4]),
            )
            if not np.isfinite(eta):
                return 1.0e3
            return -eta

        result = None
        cancelled = False
        timed_out = False
        raised_message: str | None = None
        try:
            result = minimize(
                objective,
                np.zeros(len(active), dtype=float),
                method="Powell",
                bounds=bounds,
                options={
                    "maxiter": int(self.request.auto_align_max_iterations),
                    "maxfev": int(self.request.auto_align_max_function_evaluations),
                    "xtol": float(self.request.auto_align_xtol),
                    "ftol": float(self.request.auto_align_ftol),
                },
            )
        except AlignmentCancelled as exc:
            cancelled = True
            raised_message = str(exc)
        except AlignmentTimedOut as exc:
            timed_out = True
            raised_message = str(exc)
        except (ValueError, FloatingPointError, OverflowError, MemoryError, CouplingNumericalGateError) as exc:
            self._record_failure(exc)
            raised_message = f"{type(exc).__name__}: {exc}"

        aligned = center.copy()
        eta_final = initial_eta
        optimizer_converged = bool(result is not None and result.success)
        accepted = False
        rejection_reason: str | None = None
        candidate_valid = False
        if result is None:
            rejection_reason = "cancelled" if cancelled else "timed_out" if timed_out else "optimizer_exception"
        else:
            x = np.asarray(result.x, dtype=float)
            finite_result = x.shape == (len(active),) and np.all(np.isfinite(x)) and np.isfinite(float(result.fun))
            within_bounds = finite_result and all(
                lo - 1.0e-12 <= value <= hi + 1.0e-12
                for value, (lo, hi) in zip(x, bounds, strict=True)
            )
            if finite_result and within_bounds:
                u = np.zeros(5, dtype=float)
                u[active] = x
                candidate = center + u * physical_scales
                candidate_eta = self._safe_efficiency(
                    offset_x_mm=float(candidate[0]),
                    offset_y_mm=float(candidate[1]),
                    receiver_axial_offset_z_mm=float(candidate[2]),
                    tilt_x_rad=float(candidate[3]),
                    tilt_y_rad=float(candidate[4]),
                )
                if np.isfinite(candidate_eta):
                    candidate_valid = True
                    eta_final = float(candidate_eta)
                    aligned = candidate
            if not bool(result.success):
                rejection_reason = "optimizer_did_not_converge"
            elif not finite_result:
                rejection_reason = "non_finite_optimizer_result"
            elif not within_bounds:
                rejection_reason = "optimizer_result_out_of_bounds"
            elif not candidate_valid:
                rejection_reason = "candidate_evaluation_failed"
            elif not np.isfinite(eta_final):
                rejection_reason = "non_finite_final_efficiency"
            elif eta_final + float(self.request.auto_align_acceptance_tolerance) < initial_eta:
                rejection_reason = "result_worse_than_initial"
            else:
                accepted = True

        if not accepted:
            aligned = center.copy()
            eta_final = initial_eta

        message = (
            raised_message
            if raised_message is not None
            else str(getattr(result, "message", "optimizer did not return a result"))
        )
        alignment = AlignmentResult(
            offset_x_mm=float(aligned[0]),
            offset_y_mm=float(aligned[1]),
            axial_offset_z_mm=float(aligned[2]),
            tilt_x_rad=float(aligned[3]),
            tilt_y_rad=float(aligned[4]),
            efficiency=float(eta_final),
            initial_efficiency=float(initial_eta),
            converged=optimizer_converged,
            accepted=accepted,
            iterations=int(getattr(result, "nit", 0) or 0) if result is not None else 0,
            function_evaluations=int(getattr(result, "nfev", 0) or 0) if result is not None else 0,
            method="Powell_bounded_dimensionless_prepared_coupling",
            message=message,
            active_axes=active_axes,
            failed_evaluations=int(self.failed_evaluation_count - local_failed_before),
            last_failure=self.last_evaluation_failure,
            rejection_reason=rejection_reason,
            cancelled=cancelled,
            timed_out=timed_out,
        )
        if accepted:
            self.base_x_mm = alignment.offset_x_mm
            self.base_y_mm = alignment.offset_y_mm
            self.base_z_mm = alignment.axial_offset_z_mm
            self.base_tx_rad = alignment.tilt_x_rad
            self.base_ty_rad = alignment.tilt_y_rad
        self.problem.clear_transient_caches(keep_axial_offsets=(self.base_z_mm,))
        self.alignment = alignment
        return alignment

    def diagnostics(self) -> dict[str, Any]:
        data = dict(self.problem.cache_metrics())
        data.update(
            {
                "fiber_tolerance_failed_evaluation_count": int(self.failed_evaluation_count),
                "fiber_tolerance_last_evaluation_failure": self.last_evaluation_failure,
                "fiber_tolerance_original_baseline_offset_x_mm": self.original_base[0],
                "fiber_tolerance_original_baseline_offset_y_mm": self.original_base[1],
                "fiber_tolerance_original_baseline_axial_offset_z_mm": self.original_base[2],
                "fiber_tolerance_original_baseline_tilt_x_rad": self.original_base[3],
                "fiber_tolerance_original_baseline_tilt_y_rad": self.original_base[4],
                "fiber_tolerance_scan_center_offset_x_mm": self.base_x_mm,
                "fiber_tolerance_scan_center_offset_y_mm": self.base_y_mm,
                "fiber_tolerance_scan_center_axial_offset_z_mm": self.base_z_mm,
                "fiber_tolerance_scan_center_tilt_x_rad": self.base_tx_rad,
                "fiber_tolerance_scan_center_tilt_y_rad": self.base_ty_rad,
            }
        )
        if self.alignment is not None:
            data.update(
                {
                    "fiber_tolerance_auto_alignment_enabled": True,
                    "fiber_tolerance_auto_alignment_optimizer_converged": self.alignment.converged,
                    
                    
                    
                    "fiber_tolerance_auto_alignment_converged": self.alignment.converged,
                    "fiber_tolerance_auto_alignment_result_accepted": self.alignment.accepted,
                    "fiber_tolerance_auto_alignment_initial_efficiency": self.alignment.initial_efficiency,
                    "fiber_tolerance_auto_alignment_efficiency": self.alignment.efficiency,
                    "fiber_tolerance_auto_alignment_improvement": self.alignment.efficiency - self.alignment.initial_efficiency,
                    "fiber_tolerance_auto_alignment_offset_x_mm": self.alignment.offset_x_mm,
                    "fiber_tolerance_auto_alignment_offset_y_mm": self.alignment.offset_y_mm,
                    "fiber_tolerance_auto_alignment_axial_offset_z_mm": self.alignment.axial_offset_z_mm,
                    "fiber_tolerance_auto_alignment_tilt_x_rad": self.alignment.tilt_x_rad,
                    "fiber_tolerance_auto_alignment_tilt_y_rad": self.alignment.tilt_y_rad,
                    "fiber_tolerance_auto_alignment_focus_only": bool(self.request.auto_align_focus_only),
                    "fiber_tolerance_auto_alignment_active_axes": list(self.alignment.active_axes),
                    "fiber_tolerance_auto_alignment_iterations": self.alignment.iterations,
                    "fiber_tolerance_auto_alignment_function_evaluations": self.alignment.function_evaluations,
                    "fiber_tolerance_auto_alignment_failed_evaluations": self.alignment.failed_evaluations,
                    "fiber_tolerance_auto_alignment_rejection_reason": self.alignment.rejection_reason,
                    "fiber_tolerance_auto_alignment_cancelled": self.alignment.cancelled,
                    "fiber_tolerance_auto_alignment_timed_out": self.alignment.timed_out,
                }
            )
        else:
            data["fiber_tolerance_auto_alignment_enabled"] = False
        return data
