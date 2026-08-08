
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

import numpy as np

DisplayScaleMode = Literal["layout", "physical", "group_detail"]


@dataclass(frozen=True, slots=True)
class AxialDisplayTransform:
    physical_knots_mm: np.ndarray
    display_knots_mm: np.ndarray
    mode: DisplayScaleMode = "layout"
    selected_range_mm: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        physical = np.asarray(self.physical_knots_mm, dtype=float).reshape(-1)
        display = np.asarray(self.display_knots_mm, dtype=float).reshape(-1)
        if len(physical) != len(display) or len(physical) < 2:
            raise ValueError("Display transform requires at least two paired knots.")
        order = np.argsort(physical)
        physical = physical[order]
        display = display[order]
        unique = np.concatenate(([True], np.diff(physical) > 1.0e-12))
        physical = physical[unique]
        display = display[unique]
        if len(physical) < 2 or np.any(np.diff(display) <= 0.0):
            raise ValueError("Display transform knots must be strictly increasing.")
        physical.setflags(write=False)
        display.setflags(write=False)
        object.__setattr__(self, "physical_knots_mm", physical)
        object.__setattr__(self, "display_knots_mm", display)

    @classmethod
    def identity(cls, z_values_mm: Iterable[float]) -> "AxialDisplayTransform":
        values = _safe_knots(z_values_mm)
        return cls(values, values.copy(), mode="physical")

    @classmethod
    def build(
        cls,
        z_values_mm: Iterable[float],
        *,
        mode: DisplayScaleMode = "layout",
        selected_range_mm: tuple[float, float] | None = None,
    ) -> "AxialDisplayTransform":
        physical = _safe_knots(z_values_mm)
        if mode == "physical":
            return cls(physical, physical.copy(), mode=mode)

        gaps = np.diff(physical)
        positive = gaps[gaps > 1.0e-12]
        reference = float(np.median(positive)) if positive.size else 1.0
        reference = max(reference, 1.0e-6)

        
        
        
        normalized = np.maximum(gaps / reference, 0.0)
        display_gaps = reference * (0.58 + 1.18 * np.log1p(normalized))
        display_gaps = np.maximum(display_gaps, reference * 0.42)

        if mode == "group_detail" and selected_range_mm is not None:
            lo, hi = sorted(map(float, selected_range_mm))
            centres = 0.5 * (physical[:-1] + physical[1:])
            inside = (centres >= lo) & (centres <= hi)
            display_gaps = np.where(inside, display_gaps * 1.55, display_gaps * 0.28)

        display = np.concatenate(([0.0], np.cumsum(display_gaps)))
        
        
        display += physical[0]
        return cls(
            physical,
            display,
            mode=mode,
            selected_range_mm=selected_range_mm,
        )

    def map(self, z_mm):
        scalar = np.isscalar(z_mm)
        values = np.asarray(z_mm, dtype=float)
        original_shape = values.shape
        flat = values.reshape(-1)
        mapped = np.interp(
            flat,
            self.physical_knots_mm,
            self.display_knots_mm,
        ).astype(float, copy=False)
        
        left = flat < self.physical_knots_mm[0]
        right = flat > self.physical_knots_mm[-1]
        if np.any(left):
            slope = self._end_slope(left_end=True)
            mapped[left] = self.display_knots_mm[0] + slope * (
                flat[left] - self.physical_knots_mm[0]
            )
        if np.any(right):
            slope = self._end_slope(left_end=False)
            mapped[right] = self.display_knots_mm[-1] + slope * (
                flat[right] - self.physical_knots_mm[-1]
            )
        mapped = mapped.reshape(original_shape)
        return float(mapped.item()) if scalar else mapped

    def inverse(self, display_z_mm):
        scalar = np.isscalar(display_z_mm)
        values = np.asarray(display_z_mm, dtype=float)
        original_shape = values.shape
        flat = values.reshape(-1)
        physical = np.interp(
            flat,
            self.display_knots_mm,
            self.physical_knots_mm,
        ).astype(float, copy=False)
        left = flat < self.display_knots_mm[0]
        right = flat > self.display_knots_mm[-1]
        if np.any(left):
            slope = 1.0 / self._end_slope(left_end=True)
            physical[left] = self.physical_knots_mm[0] + slope * (
                flat[left] - self.display_knots_mm[0]
            )
        if np.any(right):
            slope = 1.0 / self._end_slope(left_end=False)
            physical[right] = self.physical_knots_mm[-1] + slope * (
                flat[right] - self.display_knots_mm[-1]
            )
        physical = physical.reshape(original_shape)
        return float(physical.item()) if scalar else physical

    @property
    def label(self) -> str:
        return {
            "physical": "物理比例",
            "layout": "布局视图（轴向显示映射）",
            "group_detail": "镜组细节（轴向显示映射）",
        }[self.mode]

    def _end_slope(self, *, left_end: bool) -> float:
        index = 0 if left_end else -2
        return float(
            (self.display_knots_mm[index + 1] - self.display_knots_mm[index])
            / (self.physical_knots_mm[index + 1] - self.physical_knots_mm[index])
        )


def _safe_knots(z_values_mm: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(z_values_mm), dtype=float).reshape(-1)
    values = values[np.isfinite(values)]
    if values.size < 2:
        values = np.asarray([0.0, 1.0], dtype=float)
    values = np.unique(values)
    if values.size < 2:
        values = np.asarray([values[0], values[0] + 1.0], dtype=float)
    return values


__all__ = ["AxialDisplayTransform", "DisplayScaleMode"]
