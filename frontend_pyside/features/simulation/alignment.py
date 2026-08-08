
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AlignmentSolution:
    offset_x_um: float
    offset_y_um: float
    axial_offset_z_um: float
    tilt_x_urad: float
    tilt_y_urad: float
    initial_efficiency: float
    best_efficiency: float
    accepted: bool
    converged: bool
    iterations: int
    function_evaluations: int

    @property
    def improvement(self) -> float:
        return self.best_efficiency - self.initial_efficiency


def alignment_solution_from_result(result: Mapping[str, Any]) -> AlignmentSolution | None:
    metrics = result.get("metrics", {})
    if not isinstance(metrics, Mapping):
        return None
    required = (
        "fiber_alignment_best_offset_x_um",
        "fiber_alignment_best_offset_y_um",
        "fiber_alignment_best_axial_offset_z_um",
        "fiber_alignment_best_tilt_x_urad",
        "fiber_alignment_best_tilt_y_urad",
    )
    if not all(key in metrics for key in required):
        return None
    try:
        return AlignmentSolution(
            offset_x_um=float(metrics[required[0]]),
            offset_y_um=float(metrics[required[1]]),
            axial_offset_z_um=float(metrics[required[2]]),
            tilt_x_urad=float(metrics[required[3]]),
            tilt_y_urad=float(metrics[required[4]]),
            initial_efficiency=float(metrics.get("fiber_alignment_initial_efficiency", 0.0) or 0.0),
            best_efficiency=float(metrics.get("fiber_alignment_best_efficiency", 0.0) or 0.0),
            accepted=bool(metrics.get("fiber_alignment_result_accepted", False)),
            converged=bool(metrics.get("fiber_alignment_optimizer_converged", False)),
            iterations=int(metrics.get("fiber_alignment_iterations", 0) or 0),
            function_evaluations=int(metrics.get("fiber_alignment_function_evaluations", 0) or 0),
        )
    except (TypeError, ValueError, OverflowError):
        return None


def alignment_summary(solution: AlignmentSolution) -> str:
    state = "已接受" if solution.accepted else "未接受，保留初始位置"
    convergence = "收敛" if solution.converged else "未收敛"
    return (
        f"五轴 Powell：{state}，{convergence}；"
        f"η {100.0 * solution.initial_efficiency:.3f}% → "
        f"{100.0 * solution.best_efficiency:.3f}%；"
        f"X/Y/Z={solution.offset_x_um:.3f}/{solution.offset_y_um:.3f}/"
        f"{solution.axial_offset_z_um:.3f} μm，"
        f"θx/θy={solution.tilt_x_urad:.3f}/{solution.tilt_y_urad:.3f} μrad；"
        f"迭代 {solution.iterations}，评估 {solution.function_evaluations}。"
    )


__all__ = ["AlignmentSolution", "alignment_solution_from_result", "alignment_summary"]
