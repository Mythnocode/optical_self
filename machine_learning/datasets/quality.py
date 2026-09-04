
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SimulationQualityDecision:
    accepted: bool
    code: str = ""
    message: str = ""
    checks: dict[str, Any] = field(default_factory=dict)


def validate_target(name: str, value: float) -> str:
    if not math.isfinite(value):
        return "NON_FINITE_TARGET"
    if name in {"coupling_efficiency", "raw_mode_overlap", "valid_ray_ratio"} and not 0.0 <= value <= 1.0:
        return "TARGET_OUT_OF_RANGE"
    return ""


def evaluate_simulation_quality(
    result: Any,
    targets: dict[str, float],
    required_targets: Iterable[str],
    *,
    require_converged: bool = True,
) -> SimulationQualityDecision:


    checks: dict[str, Any] = {
        "status": getattr(result, "status", "unknown"),
        "converged": bool(getattr(result, "converged", False)),
    }
    if checks["status"] != "completed":
        return SimulationQualityDecision(False, "SIMULATION_NOT_COMPLETED", str(checks["status"]), checks)
    if require_converged and not checks["converged"]:
        return SimulationQualityDecision(False, "SIMULATION_NOT_CONVERGED", "simulation convergence flag is false", checks)

    missing = [str(name) for name in required_targets if str(name) not in targets]
    if missing:
        checks["missing_targets"] = missing
        return SimulationQualityDecision(False, "MISSING_TARGET", ", ".join(missing), checks)
    for name, value in targets.items():
        code = validate_target(str(name), float(value))
        if code:
            checks["invalid_target"] = {"name": name, "value": value}
            return SimulationQualityDecision(False, code, f"invalid target {name}={value!r}", checks)

    metrics = dict(getattr(result, "metrics", {}) or {})
    quality_metrics = {
        "energy": _metric(metrics, "coupling_propagation_energy_pass"),
        "edge": _metric(metrics, "coupling_propagation_edge_pass"),
        "nyquist": _metric(metrics, "coupling_propagation_nyquist_pass"),
        "sampling_convergence": _metric(metrics, "sampling_convergence_pass"),
    }
    checks.update({f"quality_{key}": value for key, value in quality_metrics.items()})
    for key, value in quality_metrics.items():
        if value is None or bool(value):
            continue
        # scaled-Fresnel pre-flight Nyquist checks are deliberately conservative.
        # For ML data we do not silently ignore them: the sample is accepted only
        # when the engine has actually repeated the calculation at a finer grid and
        # the explicit sampling-convergence test passed.  Energy/edge failures are
        # never waived.
        if key == "nyquist" and quality_metrics.get("sampling_convergence") is not None and bool(quality_metrics.get("sampling_convergence")):
            checks["quality_nyquist_accepted_by_convergence"] = True
            continue
        return SimulationQualityDecision(
            False,
            f"OPTICAL_{key.upper()}_CHECK_FAILED",
            f"optical quality check failed: {key}",
            checks,
        )

    valid_ray_ratio = _metric(metrics, "valid_ray_ratio")
    if valid_ray_ratio is not None and valid_ray_ratio <= 0.0:
        checks["valid_ray_ratio"] = valid_ray_ratio
        return SimulationQualityDecision(False, "NO_VALID_RAYS", "ray trace contains no valid rays", checks)
    return SimulationQualityDecision(True, checks=checks)


def _metric(metrics: dict[str, Any], name: str) -> float | None:
    value = metrics.get(name)
    if isinstance(value, (bool, int, float)):
        return float(value)
    matches = [
        float(item)
        for key, item in metrics.items()
        if key.endswith(f".{name}") and isinstance(item, (bool, int, float))
    ]
    return matches[0] if len(matches) == 1 else None


__all__ = ["SimulationQualityDecision", "evaluate_simulation_quality", "validate_target"]
