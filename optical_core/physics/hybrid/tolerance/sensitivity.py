
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from optical_core.physics.hybrid.analyses.coupling_tolerance_theory import gaussian_tolerance_scales
from .evaluator import PreparedToleranceEvaluator
from .models import FiberToleranceOptions


_MIN_EFFICIENCY = 1.0e-300
_PARAMETER_NAMES = ("dx", "dy", "dz", "tilt_x", "tilt_y")


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    metrics: dict[str, Any]
    arrays: dict[str, Any]
    warnings: list[str]
    metadata: dict[str, Any]


def _one_step(
    evaluator: PreparedToleranceEvaluator,
    base_eta: float,
    center: np.ndarray,
    physical_scales: np.ndarray,
    h: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    cache: dict[tuple[float, ...], float] = {}

    def loss(u: np.ndarray) -> float:
        key = tuple(np.round(np.asarray(u, dtype=float), 14))
        if key not in cache:
            physical = center + np.asarray(u, dtype=float) * physical_scales
            eta = evaluator.evaluate_absolute(
                offset_x_mm=float(physical[0]),
                offset_y_mm=float(physical[1]),
                axial_offset_z_mm=float(physical[2]),
                tilt_x_rad=float(physical[3]),
                tilt_y_rad=float(physical[4]),
            )
            cache[key] = float(-math.log(max(eta, _MIN_EFFICIENCY) / max(base_eta, _MIN_EFFICIENCY)))
        return cache[key]

    n = 5
    zero = np.zeros(n, dtype=float)
    f0 = loss(zero)
    gradient = np.zeros(n, dtype=float)
    matrix = np.zeros((n, n), dtype=float)
    for i in range(n):
        plus = zero.copy(); plus[i] = h
        minus = zero.copy(); minus[i] = -h
        fp, fm = loss(plus), loss(minus)
        gradient[i] = (fp - fm) / (2.0 * h)
        
        matrix[i, i] = (fp + fm - 2.0 * f0) / (2.0 * h * h)
    for i in range(n):
        for j in range(i + 1, n):
            pp = zero.copy(); pp[i] = h; pp[j] = h
            pm = zero.copy(); pm[i] = h; pm[j] = -h
            mp = zero.copy(); mp[i] = -h; mp[j] = h
            mm = zero.copy(); mm[i] = -h; mm[j] = -h
            value = (loss(pp) - loss(pm) - loss(mp) + loss(mm)) / (8.0 * h * h)
            matrix[i, j] = matrix[j, i] = value
    return gradient, 0.5 * (matrix + matrix.T), len(cache)


def _relative_change(new: np.ndarray, old: np.ndarray) -> float:
    return float(np.linalg.norm(new - old) / max(np.linalg.norm(new), 1.0e-15))


def compute_sensitivity(
    evaluator: PreparedToleranceEvaluator,
    request: FiberToleranceOptions,
    *,
    base_eta: float,
    allowed_loss_db: float,
) -> SensitivityResult:
    base = evaluator.problem.options
    scales = gaussian_tolerance_scales(
        wavelength_nm=base.wavelength_nm,
        mode_field_diameter_x_um=base.mode_field_diameter_x_um,
        mode_field_diameter_y_um=base.mode_field_diameter_y_um,
        refractive_index=base.receiver_medium_refractive_index,
    )
    physical_scales = np.asarray(
        [
            scales.mode_radius_x_um * 1.0e-3,
            scales.mode_radius_y_um * 1.0e-3,
            scales.effective_rayleigh_range_um * 1.0e-3,
            scales.divergence_x_rad,
            scales.divergence_y_rad,
        ],
        dtype=float,
    )
    center = np.asarray(
        [
            evaluator.base_x_mm,
            evaluator.base_y_mm,
            evaluator.base_z_mm,
            evaluator.base_tx_rad,
            evaluator.base_ty_rad,
        ],
        dtype=float,
    )
    steps = tuple(sorted({float(v) for v in request.sensitivity_steps}, reverse=True))
    gradients: list[np.ndarray] = []
    matrices: list[np.ndarray] = []
    counts: list[int] = []
    matrix_changes: list[float] = []
    gradient_changes: list[float] = []
    for h in steps:
        gradient, matrix, count = _one_step(evaluator, base_eta, center, physical_scales, h)
        if matrices:
            matrix_changes.append(_relative_change(matrix, matrices[-1]))
            gradient_changes.append(_relative_change(gradient, gradients[-1]))
        gradients.append(gradient)
        matrices.append(matrix)
        counts.append(count)

    raw_gradient = gradients[-1]
    raw_matrix = matrices[-1]
    richardson_used = len(matrices) >= 2
    if richardson_used:
        
        
        gradient = gradients[-1] + (gradients[-1] - gradients[-2]) / 3.0
        matrix = matrices[-1] + (matrices[-1] - matrices[-2]) / 3.0
        matrix = 0.5 * (matrix + matrix.T)
    else:
        gradient, matrix = raw_gradient, raw_matrix

    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    projected_eigenvalues = np.maximum(eigenvalues, 0.0)
    projected = eigenvectors @ np.diag(projected_eigenvalues) @ eigenvectors.T
    projection_error = float(
        np.linalg.norm(projected - matrix) / max(np.linalg.norm(matrix), 1.0e-15)
    )
    natural_limit = math.log(10.0) * max(float(allowed_loss_db), 0.0) / 10.0
    semi_axes = np.asarray(
        [
            math.sqrt(natural_limit / value) if value > 1.0e-15 else float("inf")
            for value in projected_eigenvalues
        ],
        dtype=float,
    )
    matrix_convergence = matrix_changes[-1] if matrix_changes else 0.0
    gradient_convergence = gradient_changes[-1] if gradient_changes else 0.0
    gradient_norm = float(np.linalg.norm(gradient))
    min_eigenvalue = float(np.min(eigenvalues))
    valid = bool(
        gradient_norm <= float(request.sensitivity_gradient_tolerance)
        and matrix_convergence <= float(request.sensitivity_convergence_tolerance)
        and min_eigenvalue >= -float(request.sensitivity_negative_eigenvalue_tolerance)
    )
    warnings: list[str] = []
    if gradient_norm > float(request.sensitivity_gradient_tolerance):
        warnings.append(
            "Tolerance sensitivity baseline is not stationary; auto-align the baseline before using the ellipsoid."
        )
    if matrix_convergence > float(request.sensitivity_convergence_tolerance):
        warnings.append(
            "Tolerance Hessian did not converge across perturbation step sizes."
        )
    if min_eigenvalue < -float(request.sensitivity_negative_eigenvalue_tolerance):
        warnings.append(
            "Raw tolerance Hessian has a significant negative eigenvalue; the PSD engineering ellipsoid is only a projection."
        )

    positive = projected_eigenvalues[projected_eigenvalues > 1.0e-15]
    condition = (
        float(np.max(positive) / np.min(positive))
        if positive.size >= 2
        else (1.0 if positive.size == 1 else float("inf"))
    )
    return SensitivityResult(
        metrics={
            "fiber_tolerance_sensitivity_gradient_norm": gradient_norm,
            "fiber_tolerance_sensitivity_min_eigenvalue": min_eigenvalue,
            "fiber_tolerance_sensitivity_max_eigenvalue": float(np.max(eigenvalues)),
            "fiber_tolerance_sensitivity_condition_number_positive": condition,
            "fiber_tolerance_sensitivity_evaluation_count": int(sum(counts)),
            "fiber_tolerance_sensitivity_allowed_loss_db": float(allowed_loss_db),
            "fiber_tolerance_sensitivity_matrix_convergence_error": matrix_convergence,
            "fiber_tolerance_sensitivity_gradient_convergence_error": gradient_convergence,
            "fiber_tolerance_sensitivity_projection_error": projection_error,
            "fiber_tolerance_ellipsoid_valid": valid,
            "fiber_tolerance_sensitivity_richardson_used": richardson_used,
        },
        arrays={
            "fiber_tolerance_sensitivity_parameter_names": list(_PARAMETER_NAMES),
            "fiber_tolerance_sensitivity_physical_scales": physical_scales.tolist(),
            "fiber_tolerance_sensitivity_step_sizes": list(steps),
            "fiber_tolerance_sensitivity_step_matrix_changes": matrix_changes,
            "fiber_tolerance_sensitivity_step_gradient_changes": gradient_changes,
            "fiber_tolerance_sensitivity_raw_gradient": raw_gradient.tolist(),
            "fiber_tolerance_sensitivity_gradient": gradient.tolist(),
            "fiber_tolerance_sensitivity_raw_hessian": raw_matrix.tolist(),
            "fiber_tolerance_sensitivity_hessian": matrix.tolist(),
            "fiber_tolerance_sensitivity_raw_eigenvalues": eigenvalues.tolist(),
            "fiber_tolerance_sensitivity_eigenvectors_columns": eigenvectors.tolist(),
            "fiber_tolerance_sensitivity_projected_psd_hessian": projected.tolist(),
            "fiber_tolerance_sensitivity_projected_eigenvalues": projected_eigenvalues.tolist(),
            "fiber_tolerance_sensitivity_semi_axes_dimensionless": semi_axes.tolist(),
        },
        warnings=warnings,
        metadata={
            "sensitivity_loss_model": "-ln(eta/eta0) ~= gradient.T*u + u.T*K*u",
            "sensitivity_difference_scheme": "multi_step_central_difference_plus_Richardson",
            "sensitivity_dimensionless_variables": [
                "dx/mode_radius_x",
                "dy/mode_radius_y",
                "dz/effective_rayleigh_range",
                "tilt_x/divergence_x",
                "tilt_y/divergence_y",
            ],
            "sensitivity_physical_scale_units": ["mm", "mm", "mm", "rad", "rad"],
            "raw_and_projected_hessian_both_reported": True,
        },
    )
