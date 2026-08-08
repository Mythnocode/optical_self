
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

try: 
    from scipy.special import i0e as _bessel_i0e
    from scipy.special import j1 as _bessel_j1
except Exception:  
    _bessel_j1 = None
    _bessel_i0e = None

_AIRY_FIRST_ZERO = 3.8317059702075125


@dataclass(frozen=True, slots=True)
class AiryGaussianCouplingResult:
    airy_to_mode_radius_ratio: float
    coupling_efficiency: float
    overlap_abs: float
    offset_um: float
    arrays: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


def _j1(x: np.ndarray) -> np.ndarray:
    if _bessel_j1 is not None:
        return np.asarray(_bessel_j1(x), dtype=float)
    y = np.asarray(x, dtype=float)
    out = np.zeros_like(y)
    term = y / 2.0
    out += term
    for k in range(1, 18):
        term *= -0.25 * y * y / (k * (k + 1))
        out += term
    return out


def _i0e(x: np.ndarray) -> np.ndarray:
    if _bessel_i0e is not None:
        return np.asarray(_bessel_i0e(x), dtype=float)
    y = np.asarray(x, dtype=float)
    out = np.ones_like(y)
    term = np.ones_like(y)
    for k in range(1, 32):
        term *= np.square(y / 2.0) / (k * k)
        out += term
    return out * np.exp(-np.abs(y))


def airy_amplitude(r_um: np.ndarray, airy_radius_um: float) -> np.ndarray:
    r = np.asarray(r_um, dtype=float)
    radius = max(float(airy_radius_um), 1.0e-15)
    u = _AIRY_FIRST_ZERO * r / radius
    amp = np.ones_like(u, dtype=float)
    mask = np.abs(u) > 1.0e-12
    amp[mask] = 2.0 * _j1(u[mask]) / u[mask]
    return amp


def airy_gaussian_coupling_efficiency(
    *,
    airy_radius_um: float,
    mode_radius_um: float,
    offset_um: float = 0.0,
    radial_extent_factor: float = 80.0,
    sample_count: int = 30001,
) -> AiryGaussianCouplingResult:
    airy_radius = max(float(airy_radius_um), 1.0e-15)
    mode_radius = max(float(mode_radius_um), 1.0e-15)
    offset = abs(float(offset_um))
    r_max = radial_extent_factor * max(airy_radius, mode_radius, offset + mode_radius)
    r = np.linspace(0.0, r_max, max(int(sample_count), 1001), dtype=float)
    airy = airy_amplitude(r, airy_radius)

    if offset <= 1.0e-15:
        mode = np.exp(-np.square(r / mode_radius))
        weight = 2.0 * np.pi * r
        numerator = np.trapezoid(airy * mode * weight, r)
        airy_norm = np.trapezoid(np.square(np.abs(airy)) * weight, r)
        mode_norm = np.trapezoid(np.square(np.abs(mode)) * weight, r)
    else:
        
        
        
        
        arg = 2.0 * r * offset / (mode_radius * mode_radius)
        angular_num = (
            2.0
            * np.pi
            * airy
            * np.exp(-(r * r + offset * offset) / (mode_radius * mode_radius) + np.abs(arg))
            * _i0e(arg)
        )
        arg_mode = 4.0 * r * offset / (mode_radius * mode_radius)
        angular_mode = (
            2.0
            * np.pi
            * np.exp(-2.0 * (r * r + offset * offset) / (mode_radius * mode_radius) + np.abs(arg_mode))
            * _i0e(arg_mode)
        )
        numerator = np.trapezoid(angular_num * r, r)
        airy_norm = np.trapezoid(np.square(np.abs(airy)) * 2.0 * np.pi * r, r)
        mode_norm = np.trapezoid(angular_mode * r, r)

    denom = max(float(airy_norm * mode_norm), 1.0e-300)
    eta = float(np.clip(abs(numerator) ** 2 / denom, 0.0, 1.0))
    ratio = float(airy_radius / mode_radius)
    return AiryGaussianCouplingResult(
        airy_to_mode_radius_ratio=ratio,
        coupling_efficiency=eta,
        overlap_abs=float(np.sqrt(eta)),
        offset_um=float(offset_um),
        arrays={
            "airy_gaussian_radius_um": r.tolist(),
            "airy_gaussian_airy_amplitude": airy.tolist(),
        },
        metrics={
            "airy_gaussian_coupling_efficiency": eta,
            "airy_gaussian_overlap_abs": float(np.sqrt(eta)),
            "airy_to_mode_radius_ratio": ratio,
            "airy_radius_um": airy_radius,
            "gaussian_mode_radius_um": mode_radius,
            "offset_um": float(offset_um),
            "radial_extent_factor": float(radial_extent_factor),
            "sample_count": float(max(int(sample_count), 1001)),
        },
    )


def scan_airy_gaussian_radius_ratio(
    ratios: np.ndarray | list[float] | tuple[float, ...],
    *,
    mode_radius_um: float = 1.0,
    offset_um: float = 0.0,
    radial_extent_factor: float = 80.0,
    sample_count: int = 30001,
) -> dict[str, Any]:
    vals = []
    ratio_list = [float(v) for v in ratios]
    for ratio in ratio_list:
        vals.append(
            airy_gaussian_coupling_efficiency(
                airy_radius_um=ratio * float(mode_radius_um),
                mode_radius_um=float(mode_radius_um),
                offset_um=float(offset_um),
                radial_extent_factor=radial_extent_factor,
                sample_count=sample_count,
            ).coupling_efficiency
        )
    arr = np.asarray(vals, dtype=float)
    idx = int(np.nanargmax(arr)) if arr.size else 0
    return {
        "ratios": ratio_list,
        "coupling_efficiency": vals,
        "best_ratio": ratio_list[idx] if ratio_list else None,
        "best_coupling_efficiency": float(arr[idx]) if arr.size else None,
        "radial_extent_factor": float(radial_extent_factor),
        "sample_count": float(max(int(sample_count), 1001)),
    }
