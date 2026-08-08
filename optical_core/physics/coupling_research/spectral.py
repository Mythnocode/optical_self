
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True, slots=True)
class SpectralCouplingResult:
    wavelength_nm: np.ndarray
    efficiency: np.ndarray
    peak_wavelength_nm: float
    peak_efficiency: float
    one_db_bandwidth_nm: float
    one_db_interval_nm: tuple[float, float] | None


def evaluate_spectral_coupling(
    wavelengths_nm: np.ndarray,
    evaluator: Callable[[float], float],
) -> SpectralCouplingResult:
    wavelengths = np.unique(np.sort(np.asarray(wavelengths_nm, dtype=float).reshape(-1)))
    if wavelengths.size < 3 or np.any(wavelengths <= 0.0):
        raise ValueError("spectral coupling requires at least three positive wavelengths")
    efficiency = np.asarray([float(evaluator(float(value))) for value in wavelengths], dtype=float)
    peak_index = int(np.argmax(efficiency))
    peak = float(efficiency[peak_index])
    threshold = peak * 10.0 ** (-0.1)
    connected = _connected_interval(efficiency >= threshold, peak_index)
    interval = None
    bandwidth = 0.0
    if connected is not None:
        left, right = connected
        interval = (float(wavelengths[left]), float(wavelengths[right]))
        bandwidth = interval[1] - interval[0]
    return SpectralCouplingResult(
        wavelength_nm=wavelengths,
        efficiency=efficiency,
        peak_wavelength_nm=float(wavelengths[peak_index]),
        peak_efficiency=peak,
        one_db_bandwidth_nm=float(bandwidth),
        one_db_interval_nm=interval,
    )


def _connected_interval(mask: np.ndarray, center: int) -> tuple[int, int] | None:
    if not bool(mask[center]):
        return None
    left = right = int(center)
    while left > 0 and bool(mask[left - 1]):
        left -= 1
    while right + 1 < mask.size and bool(mask[right + 1]):
        right += 1
    return left, right


__all__ = ["SpectralCouplingResult", "evaluate_spectral_coupling"]
