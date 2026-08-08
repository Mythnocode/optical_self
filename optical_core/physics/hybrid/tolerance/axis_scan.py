
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .models import ScanMode


@dataclass(frozen=True, slots=True)
class AxisScan:
    name: str
    unit: str
    values: np.ndarray
    efficiencies: np.ndarray
    center_index: int
    valid_mask: np.ndarray
    failure_messages: tuple[str | None, ...] = ()

    @property
    def valid_point_count(self) -> int:
        return int(np.count_nonzero(self.valid_mask))

    @property
    def failed_point_count(self) -> int:
        return int(self.values.size - self.valid_point_count)

    @property
    def failed_indices(self) -> tuple[int, ...]:
        return tuple(int(index) for index in np.flatnonzero(~self.valid_mask))

    @property
    def partial_result(self) -> bool:
        return bool(self.failed_point_count > 0 and self.valid_point_count > 0)


def normalise_axis(
    *,
    explicit_values: tuple[float, ...] | None,
    value_range: tuple[float, float],
    count: int,
    scan_mode: ScanMode,
    require_zero: bool = True,
) -> np.ndarray:


    explicit = explicit_values is not None
    if explicit:
        values = np.asarray(explicit_values, dtype=float).reshape(-1)
    else:
        if len(tuple(value_range)) != 2:
            raise ValueError("tolerance scan range must contain exactly two values")
        lo, hi = (float(value_range[0]), float(value_range[1]))
        if not np.isfinite(lo) or not np.isfinite(hi):
            raise ValueError("tolerance scan bounds must be finite")
        if lo > hi:
            raise ValueError("tolerance scan lower bound cannot exceed upper bound")
        mode = str(scan_mode)
        if mode == "positive_only":
            lo = max(lo, 0.0)
        elif mode == "negative_only":
            hi = min(hi, 0.0)
        elif mode == "symmetric":
            radius = max(abs(lo), abs(hi))
            lo, hi = -radius, radius
        values = np.linspace(lo, hi, max(int(count), 3), dtype=float)

    if values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError("tolerance axis must be a finite non-empty vector")
    values = np.unique(np.asarray(values, dtype=float))
    if require_zero and not np.any(np.isclose(values, 0.0, rtol=0.0, atol=1.0e-15)):
        values = np.append(values, 0.0)
    values = np.sort(values)
    mode = str(scan_mode)
    if not explicit and mode == "symmetric" and (values[0] >= 0.0 or values[-1] <= 0.0):
        raise ValueError("symmetric scan must cover both negative and positive values")
    if not explicit and mode == "positive_only" and np.any(values < -1.0e-15):
        raise ValueError("positive_only scan cannot contain negative values")
    if not explicit and mode == "negative_only" and np.any(values > 1.0e-15):
        raise ValueError("negative_only scan cannot contain positive values")
    return values


def evaluate_axis(
    name: str,
    unit: str,
    values: np.ndarray,
    evaluator: Callable[[float], float],
) -> AxisScan:


    axis = np.asarray(values, dtype=float)
    efficiencies = np.full(axis.shape, np.nan, dtype=float)
    messages: list[str | None] = [None] * int(axis.size)
    for index, value in enumerate(axis):
        try:
            eta = float(evaluator(float(value)))
            if not np.isfinite(eta):
                messages[index] = "non_finite_efficiency"
                continue
            if eta < -1.0e-12 or eta > 1.0 + 1.0e-8:
                messages[index] = f"efficiency_out_of_range:{eta:.9g}"
                continue
            efficiencies[index] = min(max(eta, 0.0), 1.0)
        except Exception as exc:  
            if type(exc).__name__ == "AlignmentCancelled":
                raise
            messages[index] = f"{type(exc).__name__}: {exc}"
    valid = np.isfinite(efficiencies)
    center = int(np.argmin(np.abs(axis)))
    return AxisScan(
        name=name,
        unit=unit,
        values=axis,
        efficiencies=efficiencies,
        center_index=center,
        valid_mask=valid,
        failure_messages=tuple(messages),
    )


def connected_threshold_brackets(
    scan: AxisScan,
    threshold: float,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:


    axis = scan.values
    eta = scan.efficiencies
    valid = scan.valid_mask
    center = int(scan.center_index)
    if not valid[center] or eta[center] < float(threshold):
        return None, None

    negative: tuple[float, float] | None = None
    previous = center
    for index in range(center - 1, -1, -1):
        if not valid[index]:
            break
        if eta[index] < threshold <= eta[previous]:
            negative = (float(axis[index]), float(axis[previous]))
            break
        previous = index

    positive: tuple[float, float] | None = None
    previous = center
    for index in range(center + 1, axis.size):
        if not valid[index]:
            break
        if eta[index] < threshold <= eta[previous]:
            positive = (float(axis[previous]), float(axis[index]))
            break
        previous = index
    return negative, positive


def legacy_sampled_tolerance(scan: AxisScan, threshold: float) -> float | None:
    ok = scan.valid_mask & (scan.efficiencies >= float(threshold))
    if not np.any(ok):
        return None
    return float(np.max(np.abs(scan.values[ok])))
