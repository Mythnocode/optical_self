
from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import OrderedDict
from threading import RLock
import weakref
from typing import Any
import math

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class PropagationSamplingAdvice:
    sampling_pass: bool
    aliasing_risk: str
    required_grid_size: int
    required_window_mm: float
    required_padding_factor: float
    input_nyquist_pass: bool
    output_nyquist_pass: bool
    fresnel_sampling_pass: bool
    angular_spectrum_angle_pass: bool
    input_bandwidth_x_per_mm: float
    input_bandwidth_y_per_mm: float
    input_nyquist_x_per_mm: float
    input_nyquist_y_per_mm: float
    output_nyquist_x_per_mm: float
    output_nyquist_y_per_mm: float
    maximum_propagation_angle_deg: float
    space_bandwidth_product: float
    estimated_output_half_width_mm: float
    warnings: tuple[str, ...] = ()

    def to_metrics(self) -> dict[str, Any]:
        return asdict(self)


def _uniform_step(axis: np.ndarray) -> float:
    arr = np.asarray(axis, dtype=float).reshape(-1)
    if arr.size < 2:
        raise ValueError("sampling axis needs at least two points")
    step = float(np.mean(np.diff(arr)))
    if not np.isfinite(step) or step == 0.0:
        raise ValueError("sampling axis must be finite and uniform")
    return abs(step)


def _spectral_support(values: np.ndarray, dx: float, dy: float, power_fraction: float) -> tuple[float, float]:
    spectrum = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(values)))
    power = np.abs(spectrum) ** 2
    total = float(np.sum(power))
    if total <= 0.0:
        return 0.0, 0.0
    fx = np.fft.fftshift(np.fft.fftfreq(values.shape[1], d=dx))
    fy = np.fft.fftshift(np.fft.fftfreq(values.shape[0], d=dy))
    px = np.sum(power, axis=0)
    py = np.sum(power, axis=1)

    def support(axis: np.ndarray, marginal: np.ndarray) -> float:
        order = np.argsort(np.abs(axis))
        cumulative = np.cumsum(marginal[order]) / total
        index = int(np.searchsorted(cumulative, float(power_fraction), side="left"))
        index = min(index, axis.size - 1)
        return float(abs(axis[order[index]]))

    return support(fx, px), support(fy, py)


def _significant_half_width(axis: np.ndarray, marginal: np.ndarray, power_fraction: float = 0.999) -> float:
    total = float(np.sum(marginal))
    if total <= 0.0:
        return 0.0
    center_order = np.argsort(np.abs(axis))
    cumulative = np.cumsum(marginal[center_order]) / total
    index = min(int(np.searchsorted(cumulative, power_fraction)), axis.size - 1)
    return float(abs(axis[center_order[index]]))




def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    data = np.asarray(values, dtype=float).reshape(-1)
    weight = np.asarray(weights, dtype=float).reshape(-1)
    mask = np.isfinite(data) & np.isfinite(weight) & (weight > 0.0)
    if not np.any(mask):
        return 0.0
    data, weight = data[mask], weight[mask]
    order = np.argsort(data)
    data, weight = data[order], weight[order]
    cumulative = np.cumsum(weight)
    threshold = float(np.clip(quantile, 0.0, 1.0)) * float(cumulative[-1])
    index = min(int(np.searchsorted(cumulative, threshold, side="left")), data.size - 1)
    return float(data[index])


def _phase_projected_support(
    values: np.ndarray, x: np.ndarray, y: np.ndarray, wavelength_mm: float, distance_mm: float
) -> tuple[float, float, float, float]:

    intensity = np.abs(values) ** 2
    if float(np.sum(intensity)) <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    dx, dy = _uniform_step(x), _uniform_step(y)
    phase = np.unwrap(np.unwrap(np.angle(values), axis=1), axis=0)
    dphi_dy, dphi_dx = np.gradient(phase, dy, dx, edge_order=1)
    k = 2.0 * math.pi / wavelength_mm
    ux = dphi_dx / k
    uy = dphi_dy / k
    radial2 = ux**2 + uy**2
    valid = (intensity > float(np.max(intensity)) * 1.0e-10) & (radial2 < 0.999**2)
    denominator = np.sqrt(np.maximum(1.0 - radial2, 1.0e-12))
    projected_x_plus = x[None, :] + float(distance_mm) * ux / denominator
    projected_y_plus = y[:, None] + float(distance_mm) * uy / denominator
    projected_x_minus = x[None, :] - float(distance_mm) * ux / denominator
    projected_y_minus = y[:, None] - float(distance_mm) * uy / denominator
    weight = np.where(valid, intensity, 0.0)
    plus = (
        _weighted_quantile(np.abs(projected_x_plus), weight, 0.999),
        _weighted_quantile(np.abs(projected_y_plus), weight, 0.999),
    )
    minus = (
        _weighted_quantile(np.abs(projected_x_minus), weight, 0.999),
        _weighted_quantile(np.abs(projected_y_minus), weight, 0.999),
    )
    
    
    
    half_x, half_y = plus if max(plus) <= max(minus) else minus
    phase_bwx = _weighted_quantile(np.abs(dphi_dx) / (2.0 * math.pi), weight, 0.999)
    phase_bwy = _weighted_quantile(np.abs(dphi_dy) / (2.0 * math.pi), weight, 0.999)
    return half_x, half_y, phase_bwx, phase_bwy


def _advise_propagation_sampling_uncached(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray | None = None,
    output_y_mm: np.ndarray | None = None,
    zero_padding_factor: float = 1.0,
    spectral_power_fraction: float = 0.999,
    safety_factor: float = 1.05,
) -> PropagationSamplingAdvice:


    values = np.asarray(field.values, dtype=np.complex128)
    x1 = np.asarray(field.grid.x_mm, dtype=float)
    y1 = np.asarray(field.grid.y_mm, dtype=float)
    x2 = x1 if output_x_mm is None else np.asarray(output_x_mm, dtype=float)
    y2 = y1 if output_y_mm is None else np.asarray(output_y_mm, dtype=float)
    dx1, dy1 = _uniform_step(x1), _uniform_step(y1)
    dx2, dy2 = _uniform_step(x2), _uniform_step(y2)
    wavelength_mm = float(field.wavelength_nm) * 1.0e-6 / float(field.refractive_index)
    z = abs(float(distance_mm))
    if wavelength_mm <= 0.0:
        raise ValueError("wavelength must be positive")

    raw_bwx, raw_bwy = _spectral_support(values, dx1, dy1, spectral_power_fraction)
    intensity = np.abs(values) ** 2
    half_x = _significant_half_width(x1, np.sum(intensity, axis=0))
    half_y = _significant_half_width(y1, np.sum(intensity, axis=1))
    projected_x, projected_y, phase_bwx, phase_bwy = _phase_projected_support(
        values, x1, y1, wavelength_mm, float(distance_mm)
    )
    aperture_x = max(2.0 * half_x, 2.0 * dx1)
    aperture_y = max(2.0 * half_y, 2.0 * dy1)
    
    
    
    
    diffraction_bwx = 2.0 / aperture_x
    diffraction_bwy = 2.0 / aperture_y
    bwx = min(raw_bwx, phase_bwx + diffraction_bwx)
    bwy = min(raw_bwy, phase_bwy + diffraction_bwy)
    in_nx, in_ny = 0.5 / dx1, 0.5 / dy1
    out_nx, out_ny = 0.5 / dx2, 0.5 / dy2
    input_pass = bool(bwx * safety_factor <= in_nx and bwy * safety_factor <= in_ny)
    output_pass = bool(bwx * safety_factor <= out_nx and bwy * safety_factor <= out_ny)

    normalized_frequency = min(0.999999999, wavelength_mm * math.hypot(bwx, bwy))
    max_angle = math.asin(normalized_frequency)
    diffraction_half_x = 1.22 * wavelength_mm * z / aperture_x if z > 0.0 else 0.0
    diffraction_half_y = 1.22 * wavelength_mm * z / aperture_y if z > 0.0 else 0.0
    phase_aware_half = max(projected_x + diffraction_half_x, projected_y + diffraction_half_y)
    magnitude_only_half = max(half_x, half_y) + z * math.tan(max_angle)
    estimated_half = min(magnitude_only_half, max(phase_aware_half, max(dx2, dy2) * 4.0))
    required_window = max(2.0 * estimated_half * safety_factor, dx2 * 16.0)
    current_window = max(float(np.ptp(x2) + dx2), float(np.ptp(y2) + dy2))
    required_padding = max(1.0, required_window / max(current_window, 1.0e-30))

    required_pitch = min(
        1.0 / max(2.0 * safety_factor * max(bwx, bwy), 1.0e-30),
        dx2,
        dy2,
    )
    required_grid = int(math.ceil(required_window / max(required_pitch, 1.0e-30))) + 1
    if required_grid % 2 == 0:
        required_grid += 1

    
    
    
    if z > 0.0:
        k = 2.0 * math.pi / wavelength_mm
        chirp_x = np.exp(1j * k * x1**2 / (2.0 * float(distance_mm)))
        chirp_y = np.exp(1j * k * y1**2 / (2.0 * float(distance_mm)))
        prephase = np.unwrap(
            np.unwrap(np.angle(values * chirp_y[:, None] * chirp_x[None, :]), axis=1),
            axis=0,
        )
        pre_dy, pre_dx = np.gradient(prephase, dy1, dx1, edge_order=1)
        phase_weight = np.abs(values) ** 2
        input_chirp_step = max(
            _weighted_quantile(np.abs(pre_dx) * dx1, phase_weight, 0.999),
            _weighted_quantile(np.abs(pre_dy) * dy1, phase_weight, 0.999),
        )
        output_chirp_step = 2.0 * math.pi * estimated_half * max(dx2, dy2) / (wavelength_mm * z)
        fresnel_pass = bool(max(input_chirp_step, output_chirp_step) <= math.pi / safety_factor)
    else:
        fresnel_pass = True

    max_supported_angle = math.asin(min(1.0, wavelength_mm * min(in_nx, in_ny)))
    angle_pass = bool(max_angle <= max_supported_angle / safety_factor if max_supported_angle > 0 else max_angle == 0)
    sbp = float(required_window * 2.0 * max(bwx, bwy))

    failures = sum(not flag for flag in (input_pass, output_pass, fresnel_pass, angle_pass))
    pad_shortfall = required_padding / max(float(zero_padding_factor), 1.0e-30)
    if failures == 0 and pad_shortfall <= 1.0:
        risk = "low"
    elif failures <= 1 and pad_shortfall <= 1.5:
        risk = "moderate"
    elif failures <= 2 and pad_shortfall <= 2.5:
        risk = "high"
    else:
        risk = "critical"
    warnings: list[str] = []
    if not input_pass:
        warnings.append("input field spectrum approaches or exceeds input Nyquist frequency")
    if not output_pass:
        warnings.append("requested output pitch cannot sample the estimated propagated bandwidth")
    if not fresnel_pass:
        warnings.append("Fresnel quadratic phase changes too rapidly at a sampled edge")
    if not angle_pass:
        warnings.append("angular-spectrum maximum propagation angle exceeds sampling support")
    if pad_shortfall > 1.0:
        warnings.append("configured zero padding is below the estimated no-wrap requirement")

    return PropagationSamplingAdvice(
        sampling_pass=bool(risk in {"low", "moderate"}),
        aliasing_risk=risk,
        required_grid_size=required_grid,
        required_window_mm=float(required_window),
        required_padding_factor=float(required_padding),
        input_nyquist_pass=input_pass,
        output_nyquist_pass=output_pass,
        fresnel_sampling_pass=fresnel_pass,
        angular_spectrum_angle_pass=angle_pass,
        input_bandwidth_x_per_mm=float(bwx),
        input_bandwidth_y_per_mm=float(bwy),
        input_nyquist_x_per_mm=float(in_nx),
        input_nyquist_y_per_mm=float(in_ny),
        output_nyquist_x_per_mm=float(out_nx),
        output_nyquist_y_per_mm=float(out_ny),
        maximum_propagation_angle_deg=float(math.degrees(max_angle)),
        space_bandwidth_product=sbp,
        estimated_output_half_width_mm=float(estimated_half),
        warnings=tuple(warnings),
    )


_ADVICE_CACHE_MAXSIZE = 64
_advice_cache: OrderedDict[tuple[Any, ...], tuple[weakref.ReferenceType[np.ndarray], PropagationSamplingAdvice]] = OrderedDict()
_advice_cache_lock = RLock()
_advice_cache_hits = 0
_advice_cache_misses = 0


def _axis_signature(axis: np.ndarray | None) -> tuple[int, float, float, float] | None:
    if axis is None:
        return None
    values = np.asarray(axis, dtype=float).reshape(-1)
    step = 0.0 if values.size < 2 else float(values[1] - values[0])
    return (int(values.size), float(values[0]), float(values[-1]), step)


def advise_propagation_sampling(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray | None = None,
    output_y_mm: np.ndarray | None = None,
    zero_padding_factor: float = 1.0,
    spectral_power_fraction: float = 0.999,
    safety_factor: float = 1.05,
) -> PropagationSamplingAdvice:

    global _advice_cache_hits, _advice_cache_misses
    values = np.asarray(field.values, dtype=np.complex128)
    key = (
        id(values), tuple(values.shape), tuple(values.strides),
        float(field.wavelength_nm), float(field.refractive_index),
        float(distance_mm), _axis_signature(output_x_mm), _axis_signature(output_y_mm),
        float(zero_padding_factor), float(spectral_power_fraction), float(safety_factor),
    )
    with _advice_cache_lock:
        entry = _advice_cache.pop(key, None)
        if entry is not None and entry[0]() is values:
            _advice_cache[key] = entry
            _advice_cache_hits += 1
            return entry[1]
        _advice_cache_misses += 1
    advice = _advise_propagation_sampling_uncached(
        field, distance_mm, output_x_mm=output_x_mm, output_y_mm=output_y_mm,
        zero_padding_factor=zero_padding_factor,
        spectral_power_fraction=spectral_power_fraction, safety_factor=safety_factor,
    )
    with _advice_cache_lock:
        _advice_cache[key] = (weakref.ref(values), advice)
        while len(_advice_cache) > _ADVICE_CACHE_MAXSIZE:
            _advice_cache.popitem(last=False)
    return advice


def clear_sampling_advice_cache() -> None:
    global _advice_cache_hits, _advice_cache_misses
    with _advice_cache_lock:
        _advice_cache.clear()
        _advice_cache_hits = 0
        _advice_cache_misses = 0


def sampling_advice_cache_info() -> dict[str, int]:
    with _advice_cache_lock:
        return {
            "hits": int(_advice_cache_hits), "misses": int(_advice_cache_misses),
            "maxsize": int(_ADVICE_CACHE_MAXSIZE), "currsize": len(_advice_cache),
        }


__all__ = [
    "PropagationSamplingAdvice", "advise_propagation_sampling",
    "clear_sampling_advice_cache", "sampling_advice_cache_info",
]
