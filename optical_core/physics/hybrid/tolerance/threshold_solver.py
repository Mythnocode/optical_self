
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import math


@dataclass(frozen=True, slots=True)
class ThresholdCrossingResult:
    root: float | None
    bracket: tuple[float, float] | None
    converged: bool
    iterations: int
    function_calls: int
    residual: float | None
    final_bracket_width: float | None
    method: str
    validation_left: float | None = None
    validation_right: float | None = None
    status: str = "NUMERICAL_FAILURE"
    message: str = ""


def _failure(
    *,
    method: str,
    status: str,
    message: str,
    bracket: tuple[float, float] | None = None,
    calls: int = 0,
    residual: float | None = None,
) -> ThresholdCrossingResult:
    return ThresholdCrossingResult(
        root=None,
        bracket=bracket,
        converged=False,
        iterations=0,
        function_calls=int(calls),
        residual=residual,
        final_bracket_width=(None if bracket is None else abs(bracket[1] - bracket[0])),
        method=str(method),
        status=status,
        message=message,
    )


def solve_threshold_crossing(
    evaluator: Callable[[float], float],
    *,
    bracket: tuple[float, float] | None,
    threshold: float,
    method: str = "brent",
    position_xtol: float = 1.0e-3,
    efficiency_ftol: float = 1.0e-6,
    max_iterations: int = 40,
    validation_fraction: float = 0.02,
    missing_status: str = "NOT_REACHED_WITHIN_SCAN",
    missing_message: str = "threshold was not bracketed by the valid coarse scan",
) -> ThresholdCrossingResult:


    if bracket is None:
        return _failure(
            method=method,
            status=missing_status,
            message=missing_message,
        )
    a, b = sorted((float(bracket[0]), float(bracket[1])))
    calls = 0

    def function(x: float) -> float:
        nonlocal calls
        calls += 1
        try:
            eta = float(evaluator(float(x)))
        except Exception as exc:
            if type(exc).__name__ == "AlignmentCancelled":
                raise
            raise FloatingPointError(f"threshold evaluation failed at {x:.9g}: {exc}") from exc
        value = eta - float(threshold)
        if not math.isfinite(value):
            raise FloatingPointError(f"non-finite threshold residual at {x:.9g}")
        return value

    try:
        fa, fb = function(a), function(b)
    except (ValueError, FloatingPointError, OverflowError) as exc:
        return _failure(
            method=method,
            status="INSUFFICIENT_VALID_POINTS",
            message=str(exc),
            bracket=(a, b),
            calls=calls,
        )
    if abs(fa) <= efficiency_ftol:
        root, iterations, final_width = a, 0, abs(b - a)
    elif abs(fb) <= efficiency_ftol:
        root, iterations, final_width = b, 0, abs(b - a)
    elif fa * fb > 0.0:
        return _failure(
            method=method,
            status="INVALID_BRACKET",
            message="coarse bracket endpoints do not straddle the threshold",
            bracket=(a, b),
            calls=calls,
            residual=min(abs(fa), abs(fb)),
        )
    elif str(method).lower() == "bisection":
        left, right = a, b
        fleft = fa
        root = 0.5 * (left + right)
        iterations = 0
        try:
            for iterations in range(1, int(max_iterations) + 1):
                root = 0.5 * (left + right)
                fmid = function(root)
                if abs(fmid) <= efficiency_ftol or abs(right - left) <= position_xtol:
                    break
                if fleft * fmid <= 0.0:
                    right = root
                else:
                    left, fleft = root, fmid
        except (ValueError, FloatingPointError, OverflowError) as exc:
            return _failure(
                method=method,
                status="NUMERICAL_FAILURE",
                message=str(exc),
                bracket=(a, b),
                calls=calls,
            )
        final_width = abs(right - left)
    else:
        from scipy.optimize import brentq

        try:
            root, details = brentq(
                function,
                a,
                b,
                xtol=float(position_xtol),
                rtol=4.0 * float.fromhex("0x1.0000000000000p-52"),
                maxiter=int(max_iterations),
                full_output=True,
                disp=False,
            )
        except (ValueError, RuntimeError, FloatingPointError, OverflowError) as exc:
            return _failure(
                method=method,
                status="NUMERICAL_FAILURE",
                message=f"root solver failed: {exc}",
                bracket=(a, b),
                calls=calls,
            )
        iterations = int(details.iterations)
        final_width = min(abs(b - a), 2.0 * float(position_xtol))

    try:
        residual = abs(function(float(root)))
        width = max(abs(b - a), float(position_xtol))
        delta = max(float(position_xtol) * 2.0, width * max(float(validation_fraction), 0.0))
        left_probe = max(a, float(root) - delta)
        right_probe = min(b, float(root) + delta)
        left_value = float(evaluator(left_probe))
        right_value = float(evaluator(right_probe))
        calls += 2
        validation_finite = math.isfinite(left_value) and math.isfinite(right_value)
        crossing = validation_finite and (left_value - threshold) * (right_value - threshold) <= 0.0
    except Exception as exc:
        if type(exc).__name__ == "AlignmentCancelled":
            raise
        return ThresholdCrossingResult(
            root=float(root),
            bracket=(a, b),
            converged=False,
            iterations=int(iterations),
            function_calls=int(calls),
            residual=None,
            final_bracket_width=float(final_width),
            method="bisection" if str(method).lower() == "bisection" else "brent",
            status="VALIDATION_FAILED",
            message=f"root found but validation failed: {exc}",
        )

    converged = bool(
        residual <= max(float(efficiency_ftol), 1.0e-15)
        and final_width <= max(abs(b - a), 2.0 * float(position_xtol))
        and crossing
    )
    return ThresholdCrossingResult(
        root=float(root),
        bracket=(a, b),
        converged=converged,
        iterations=int(iterations),
        function_calls=int(calls),
        residual=float(residual),
        final_bracket_width=float(final_width),
        method="bisection" if str(method).lower() == "bisection" else "brent",
        validation_left=left_value,
        validation_right=right_value,
        status="CROSSING_FOUND" if converged else "VALIDATION_FAILED",
        message="converged" if converged else "root found but validation did not fully pass",
    )
