
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np


@dataclass(frozen=True, slots=True)
class JointToleranceMap:
    axis_x_name: str
    axis_y_name: str
    axis_x: np.ndarray
    axis_y: np.ndarray
    efficiency: np.ndarray
    threshold: float | None
    threshold_mask: np.ndarray | None
    metrics: Mapping[str, Any] = field(default_factory=dict)


def evaluate_joint_tolerance_map(
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    axis_x_name: str,
    axis_x: np.ndarray,
    axis_y_name: str,
    axis_y: np.ndarray,
    fixed_parameters: Mapping[str, float] | None = None,
    threshold: float | None = None,
) -> JointToleranceMap:
    x_values = np.asarray(axis_x, dtype=float).reshape(-1)
    y_values = np.asarray(axis_y, dtype=float).reshape(-1)
    if x_values.size < 2 or y_values.size < 2 or not np.all(np.isfinite(x_values)) or not np.all(np.isfinite(y_values)):
        raise ValueError("joint tolerance axes require at least two finite points")
    x_values = np.unique(np.sort(x_values))
    y_values = np.unique(np.sort(y_values))
    base = dict(fixed_parameters or {})
    values = np.empty((y_values.size, x_values.size), dtype=float)
    calls = 0
    for row, y_value in enumerate(y_values):
        for column, x_value in enumerate(x_values):
            parameters = dict(base)
            parameters[axis_x_name] = float(x_value)
            parameters[axis_y_name] = float(y_value)
            value = float(evaluator(parameters))
            if not np.isfinite(value):
                raise ValueError("coupling evaluator returned non-finite efficiency")
            values[row, column] = value
            calls += 1
    peak_index = np.unravel_index(int(np.argmax(values)), values.shape)
    mask = None if threshold is None else values >= float(threshold)
    return JointToleranceMap(
        axis_x_name=str(axis_x_name),
        axis_y_name=str(axis_y_name),
        axis_x=x_values,
        axis_y=y_values,
        efficiency=values,
        threshold=None if threshold is None else float(threshold),
        threshold_mask=mask,
        metrics={
            "evaluation_count": calls,
            "peak_efficiency": float(values[peak_index]),
            "peak_axis_x": float(x_values[peak_index[1]]),
            "peak_axis_y": float(y_values[peak_index[0]]),
            "mean_efficiency": float(np.mean(values)),
            "minimum_efficiency": float(np.min(values)),
            "threshold_area_fraction": None if mask is None else float(np.mean(mask)),
        },
    )


def conditional_lateral_tolerance(
    evaluator: Callable[[Mapping[str, float]], float],
    *,
    axial_values: np.ndarray,
    lateral_values: np.ndarray,
    threshold: float,
    axial_name: str = "dz_um",
    lateral_name: str = "dx_um",
) -> dict[str, np.ndarray]:
    mapping = evaluate_joint_tolerance_map(
        evaluator,
        axis_x_name=lateral_name,
        axis_x=lateral_values,
        axis_y_name=axial_name,
        axis_y=axial_values,
        threshold=threshold,
    )
    tolerances = np.full(mapping.axis_y.size, np.nan, dtype=float)
    for index, row in enumerate(mapping.efficiency):
        accepted = np.flatnonzero(row >= float(threshold))
        if accepted.size:
            tolerances[index] = float(np.max(np.abs(mapping.axis_x[accepted])))
    return {
        "axial_values": mapping.axis_y,
        "lateral_tolerance": tolerances,
        "efficiency_map": mapping.efficiency,
    }


__all__ = ["JointToleranceMap", "evaluate_joint_tolerance_map", "conditional_lateral_tolerance"]
