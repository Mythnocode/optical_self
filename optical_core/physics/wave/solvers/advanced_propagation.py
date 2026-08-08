
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Literal

import numpy as np
from scipy.signal import CZT

from optical_core.physics.wave.solvers.sampling_advisor import advise_propagation_sampling
from optical_core.physics.wave.solvers.workspace import (
    PropagationWorkspacePool,
    global_propagation_workspace_pool,
    clear_global_propagation_workspaces,
    global_propagation_workspace_info,
)

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D


PropagationMethod = Literal[
    "angular_spectrum",
    "band_limited_angular_spectrum",
    "scaled_angular_spectrum",
    "scaled_fresnel",
    "issc",
]


@dataclass(frozen=True, slots=True)
class SamplingDiagnostics:
    method: str
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.warnings


@dataclass(frozen=True, slots=True)
class PropagationResult:
    field: ScalarField2D
    diagnostics: SamplingDiagnostics
    metadata: dict[str, Any] = field(default_factory=dict)


def _uniform_axis(axis: np.ndarray, name: str) -> tuple[np.ndarray, float]:
    values = np.asarray(axis, dtype=float).reshape(-1)
    if values.size < 2:
        raise ValueError(f"{name} 至少需要两个采样点。")
    differences = np.diff(values)
    step = float(np.mean(differences))
    if not np.all(np.isfinite(values)) or not np.isfinite(step) or step == 0.0:
        raise ValueError(f"{name} 必须是有限的单调均匀坐标。")
    tolerance = max(abs(step) * 1.0e-8, 1.0e-14)
    if not np.allclose(differences, step, rtol=1.0e-8, atol=tolerance):
        raise ValueError(f"{name} 必须均匀采样。")
    if step < 0.0:
        values = values[::-1].copy()
        step = -step
    return values, step


def _field_power(values: np.ndarray, dx_mm: float, dy_mm: float) -> float:
    return float(np.sum(np.abs(values) ** 2) * abs(float(dx_mm) * float(dy_mm)))


def _edge_power_fraction_from_intensity(
    intensity: np.ndarray, edge_pixels: int | None = None
) -> float:
    intensity = np.asarray(intensity, dtype=float)
    if intensity.size == 0:
        return 0.0
    ny, nx = intensity.shape
    border = int(edge_pixels or max(1, min(nx, ny) // 32))
    border = max(1, min(border, max(nx // 2, 1), max(ny // 2, 1)))
    total = float(np.sum(intensity))
    if total <= 0.0:
        return 0.0
    edge = float(np.sum(intensity[:border, :]) + np.sum(intensity[-border:, :]))
    if ny > 2 * border:
        middle = intensity[border:-border, :]
        edge += float(np.sum(middle[:, :border]) + np.sum(middle[:, -border:]))
    return float(edge / total)


def _edge_power_fraction(values: np.ndarray, edge_pixels: int | None = None) -> float:
    return _edge_power_fraction_from_intensity(
        np.asarray(np.abs(values) ** 2, dtype=float), edge_pixels=edge_pixels
    )




def _nyquist_margin_from_phase_step(*steps: float) -> float:
    finite = [abs(float(step)) for step in steps if np.isfinite(step) and abs(float(step)) > 0.0]
    if not finite:
        return float("inf")
    return float(np.pi / max(finite))


def _power_diagnostics(input_power: float, output_power: float) -> dict[str, float]:
    capture = float(output_power / max(abs(input_power), 1.0e-30))
    closure = float(abs(output_power - input_power) / max(abs(input_power), 1.0e-30))
    return {
        "input_power_a.u.": float(input_power),
        "output_power_a.u.": float(output_power),
        "power_capture_ratio": capture,
        "energy_closure_error": closure,
    }

def _grid_from_axes(x_mm: np.ndarray, y_mm: np.ndarray) -> SamplingGrid2D:
    x, dx = _uniform_axis(x_mm, "x_mm")
    y, dy = _uniform_axis(y_mm, "y_mm")
    return SamplingGrid2D(x_mm=x, y_mm=y, dx_mm=dx, dy_mm=dy)


def _make_field(template: ScalarField2D, values: np.ndarray, grid: SamplingGrid2D, z_mm: float) -> ScalarField2D:
    array = np.asarray(values, dtype=np.complex128)
    return ScalarField2D(
        values=array,
        grid=grid,
        wavelength_nm=float(template.wavelength_nm),
        refractive_index=float(template.refractive_index),
        z_mm=float(z_mm),
        integrated_power=_field_power(array, grid.dx_mm, grid.dy_mm),
    )


def zero_pad_field(field: ScalarField2D, factor: float = 2.0) -> ScalarField2D:


    factor = float(factor)
    if factor <= 1.0 + 1.0e-12:
        return replace(field, values=np.asarray(field.values, dtype=np.complex128).copy())
    values = np.asarray(field.values, dtype=np.complex128)
    ny, nx = values.shape
    out_nx = max(nx, int(np.ceil(nx * factor)))
    out_ny = max(ny, int(np.ceil(ny * factor)))
    
    if (out_nx - nx) % 2:
        out_nx += 1
    if (out_ny - ny) % 2:
        out_ny += 1
    padded = np.zeros((out_ny, out_nx), dtype=np.complex128)
    y0 = (out_ny - ny) // 2
    x0 = (out_nx - nx) // 2
    padded[y0 : y0 + ny, x0 : x0 + nx] = values
    x_axis = (np.arange(out_nx, dtype=float) - (out_nx - 1) / 2.0) * float(field.grid.dx_mm)
    y_axis = (np.arange(out_ny, dtype=float) - (out_ny - 1) / 2.0) * float(field.grid.dy_mm)
    grid = SamplingGrid2D(
        x_mm=x_axis,
        y_mm=y_axis,
        dx_mm=float(field.grid.dx_mm),
        dy_mm=float(field.grid.dy_mm),
    )
    return _make_field(field, padded, grid, field.z_mm)



@lru_cache(maxsize=96)
def _czt_forward_plan_cached(
    n: int, m: int, dx: float, df: float, f0: float, x0: float
) -> tuple[CZT, np.ndarray]:
    a = np.exp(1j * 2.0 * np.pi * float(f0) * float(dx))
    w = np.exp(-1j * 2.0 * np.pi * float(df) * float(dx))
    plan = CZT(n=int(n), m=int(m), w=w, a=a)
    frequencies = float(f0) + np.arange(int(m), dtype=float) * float(df)
    phase = np.exp(-1j * 2.0 * np.pi * frequencies * float(x0))
    phase.setflags(write=False)
    return plan, phase


@lru_cache(maxsize=96)
def _czt_inverse_plan_cached(
    n: int, m: int, df: float, dx: float, x0: float, f0: float
) -> tuple[CZT, np.ndarray]:
    a = np.exp(-1j * 2.0 * np.pi * float(x0) * float(df))
    w = np.exp(1j * 2.0 * np.pi * float(dx) * float(df))
    plan = CZT(n=int(n), m=int(m), w=w, a=a)
    coordinates = float(x0) + np.arange(int(m), dtype=float) * float(dx)
    phase = np.exp(1j * 2.0 * np.pi * coordinates * float(f0))
    phase.setflags(write=False)
    return plan, phase


def _czt_forward_axis(
    values: np.ndarray,
    input_axis: np.ndarray,
    output_frequency: np.ndarray,
    *,
    axis: int,
) -> np.ndarray:

    x, dx = _uniform_axis(input_axis, "CZT input axis")
    f, df = _uniform_axis(output_frequency, "CZT output frequency")
    plan, phase = _czt_forward_plan_cached(
        x.size, f.size, float(dx), float(df), float(f[0]), float(x[0])
    )
    transformed = plan(values, axis=axis)
    shape = [1] * transformed.ndim
    shape[axis] = f.size
    return transformed * phase.reshape(shape)


def _czt_inverse_axis(
    spectrum: np.ndarray,
    input_frequency: np.ndarray,
    output_axis: np.ndarray,
    *,
    axis: int,
) -> np.ndarray:

    f, df = _uniform_axis(input_frequency, "CZT input frequency")
    x, dx = _uniform_axis(output_axis, "CZT output axis")
    plan, phase = _czt_inverse_plan_cached(
        f.size, x.size, float(df), float(dx), float(x[0]), float(f[0])
    )
    transformed = plan(spectrum, axis=axis)
    shape = [1] * transformed.ndim
    shape[axis] = x.size
    return transformed * phase.reshape(shape)

def _czt_forward_2d(
    values: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    fx_axis: np.ndarray,
    fy_axis: np.ndarray,
) -> np.ndarray:
    first = _czt_forward_axis(values, x_axis, fx_axis, axis=1)
    return _czt_forward_axis(first, y_axis, fy_axis, axis=0)


def _czt_inverse_2d(
    spectrum: np.ndarray,
    fx_axis: np.ndarray,
    fy_axis: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
) -> np.ndarray:
    first = _czt_inverse_axis(spectrum, fx_axis, x_axis, axis=1)
    return _czt_inverse_axis(first, fy_axis, y_axis, axis=0)


@lru_cache(maxsize=8)
def _angular_spectrum_transfer_cached(
    nx: int,
    ny: int,
    dx_mm: float,
    dy_mm: float,
    wavelength_nm: float,
    refractive_index: float,
    distance_mm: float,
    band_limited: bool,
    transfer_model: str,
) -> tuple[np.ndarray, tuple[tuple[str, float], ...]]:
    transfer, metrics = _angular_spectrum_transfer_uncached(
        nx=nx,
        ny=ny,
        dx_mm=dx_mm,
        dy_mm=dy_mm,
        wavelength_nm=wavelength_nm,
        refractive_index=refractive_index,
        distance_mm=distance_mm,
        band_limited=band_limited,
        transfer_model=transfer_model,
    )
    transfer.setflags(write=False)
    return transfer, tuple(sorted((str(k), float(v)) for k, v in metrics.items()))


def _angular_spectrum_transfer_uncached(
    *,
    nx: int,
    ny: int,
    dx_mm: float,
    dy_mm: float,
    wavelength_nm: float,
    refractive_index: float,
    distance_mm: float,
    band_limited: bool,
    transfer_model: str = "exact",
) -> tuple[np.ndarray, dict[str, float]]:
    wavelength0_mm = float(wavelength_nm) * 1.0e-6
    n_medium = float(refractive_index)
    if wavelength0_mm <= 0.0 or n_medium <= 0.0:
        raise ValueError("波长和折射率必须为正数。")
    fx = np.fft.fftfreq(nx, d=float(dx_mm))
    fy = np.fft.fftfreq(ny, d=float(dy_mm))
    cutoff = n_medium / wavelength0_mm
    radial2 = fy[:, None] ** 2 + fx[None, :] ** 2
    propagating = radial2 <= cutoff**2
    model = str(transfer_model).strip().lower()
    transfer = np.zeros((ny, nx), dtype=np.complex128)
    if model == "exact":
        kz = np.zeros((ny, nx), dtype=float)
        kz[propagating] = 2.0 * np.pi * np.sqrt(np.maximum(cutoff**2 - radial2[propagating], 0.0))
        transfer[propagating] = np.exp(1j * kz[propagating] * float(distance_mm))
    elif model == "fresnel":
        wavelength_medium_mm = wavelength0_mm / n_medium
        k = 2.0 * np.pi / wavelength_medium_mm
        transfer[propagating] = np.exp(1j * k * float(distance_mm)) * np.exp(
            -1j * np.pi * wavelength_medium_mm * float(distance_mm) * radial2[propagating]
        )
    else:
        raise ValueError("transfer_model must be 'exact' or 'fresnel'")

    lx = nx * abs(float(dx_mm))
    ly = ny * abs(float(dy_mm))
    fx_limit = cutoff
    fy_limit = cutoff
    if band_limited and abs(float(distance_mm)) > 0.0:
        z = abs(float(distance_mm))
        
        fx_limit = min(cutoff, (0.5 * lx) / (wavelength0_mm * np.sqrt(z * z + (0.5 * lx) ** 2)))
        fy_limit = min(cutoff, (0.5 * ly) / (wavelength0_mm * np.sqrt(z * z + (0.5 * ly) ** 2)))
        band_mask = (np.abs(fx)[None, :] <= fx_limit) & (np.abs(fy)[:, None] <= fy_limit)
        transfer *= band_mask

    phase = np.angle(np.where(np.abs(transfer) > 0.0, transfer, 1.0 + 0.0j))
    unwrapped_x = np.unwrap(phase, axis=1)
    unwrapped_y = np.unwrap(phase, axis=0)
    max_step_x = float(np.max(np.abs(np.diff(unwrapped_x, axis=1)))) if nx > 1 else 0.0
    max_step_y = float(np.max(np.abs(np.diff(unwrapped_y, axis=0)))) if ny > 1 else 0.0
    return transfer, {
        "propagating_cutoff_per_mm": float(cutoff),
        "bandlimit_fx_per_mm": float(fx_limit),
        "bandlimit_fy_per_mm": float(fy_limit),
        "max_transfer_phase_step_x_rad": max_step_x,
        "max_transfer_phase_step_y_rad": max_step_y,
        "transfer_nonzero_fraction": float(np.count_nonzero(transfer) / transfer.size),
        "transfer_model_exact": float(model == "exact"),
        "transfer_model_fresnel": float(model == "fresnel"),
    }



def _angular_spectrum_transfer(**kwargs: Any) -> tuple[np.ndarray, dict[str, float]]:
    transfer, items = _angular_spectrum_transfer_cached(
        int(kwargs["nx"]), int(kwargs["ny"]), float(kwargs["dx_mm"]), float(kwargs["dy_mm"]),
        float(kwargs["wavelength_nm"]), float(kwargs["refractive_index"]), float(kwargs["distance_mm"]),
        bool(kwargs["band_limited"]), str(kwargs.get("transfer_model", "exact")),
    )
    return transfer, dict(items)


def clear_propagation_spectrum_cache() -> None:
    _angular_spectrum_transfer_cached.cache_clear()


def clear_czt_plan_cache() -> None:
    _czt_forward_plan_cached.cache_clear()
    _czt_inverse_plan_cached.cache_clear()


def clear_all_propagation_caches() -> None:
    clear_propagation_spectrum_cache()
    clear_czt_plan_cache()
    clear_global_propagation_workspaces()
    try:
        from optical_core.physics.wave.solvers.sampling_advisor import clear_sampling_advice_cache
        clear_sampling_advice_cache()
    except ImportError:
        pass


def propagation_spectrum_cache_info() -> dict[str, int]:
    info = _angular_spectrum_transfer_cached.cache_info()
    forward = _czt_forward_plan_cached.cache_info()
    inverse = _czt_inverse_plan_cached.cache_info()
    return {
        "hits": int(info.hits), "misses": int(info.misses),
        "maxsize": int(info.maxsize or 0), "currsize": int(info.currsize),
        "czt_forward_hits": int(forward.hits), "czt_forward_misses": int(forward.misses),
        "czt_inverse_hits": int(inverse.hits), "czt_inverse_misses": int(inverse.misses),
        **{f"workspace_{key}": value for key, value in global_propagation_workspace_info().items()},
    }

def propagate_angular_spectrum_advanced(
    field: ScalarField2D,
    distance_mm: float,
    *,
    zero_padding_factor: float = 2.0,
    band_limited: bool = False,
    transfer_model: Literal["exact", "fresnel"] = "exact",
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    workspace_pool: PropagationWorkspacePool | None = None,
) -> PropagationResult:


    if float(distance_mm) < 0.0:
        raise ValueError("当前前向传播接口要求 distance_mm >= 0。")
    working = zero_pad_field(field, zero_padding_factor)
    values = np.asarray(working.values, dtype=np.complex128)
    transfer, transfer_metrics = _angular_spectrum_transfer(
        nx=values.shape[1],
        ny=values.shape[0],
        dx_mm=working.grid.dx_mm,
        dy_mm=working.grid.dy_mm,
        wavelength_nm=working.wavelength_nm,
        refractive_index=working.refractive_index,
        distance_mm=distance_mm,
        band_limited=band_limited,
        transfer_model=transfer_model,
    )
    pool = workspace_pool or global_propagation_workspace_pool()
    with pool.acquire(values.shape) as workspace:
        workspace.fft2(values)
        output_workspace = workspace.propagate_spectrum(transfer)
        intensity = workspace.update_intensity(output_workspace)
        output_power = float(np.sum(intensity) * abs(working.grid.dx_mm * working.grid.dy_mm))
        edge_fraction = _edge_power_fraction_from_intensity(intensity)
        
        output = output_workspace.copy()
    out = _make_field(working, output, working.grid, working.z_mm + float(distance_mm))
    input_power = _field_power(values, working.grid.dx_mm, working.grid.dy_mm)
    closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
    nyquist_margin = _nyquist_margin_from_phase_step(
        transfer_metrics["max_transfer_phase_step_x_rad"],
        transfer_metrics["max_transfer_phase_step_y_rad"],
    )
    warnings: list[str] = []
    if edge_fraction > float(edge_power_threshold):
        warnings.append(
            f"输出边缘功率占比 {edge_fraction:.3g} 超过阈值 {edge_power_threshold:.3g}。"
        )
    if nyquist_margin < float(nyquist_margin_min):
        warnings.append(
            f"角谱传递函数 Nyquist 余量 {nyquist_margin:.3g} 小于要求 {float(nyquist_margin_min):.3g}。"
        )
    if closure > float(energy_closure_threshold):
        warnings.append(
            f"角谱传播能量闭合误差 {closure:.3g} 超过阈值 {float(energy_closure_threshold):.3g}。"
        )
    method = "band_limited_angular_spectrum" if band_limited else "angular_spectrum"
    metrics: dict[str, Any] = {
        **transfer_metrics,
        "zero_padding_factor": float(zero_padding_factor),
        "input_power_a.u.": input_power,
        "output_power_a.u.": output_power,
        "energy_closure_error": float(closure),
        "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
        "nyquist_margin_min": float(nyquist_margin),
        "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
        "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
        "edge_power_fraction": float(edge_fraction),
        "output_dx_mm": float(out.grid.dx_mm),
        "output_dy_mm": float(out.grid.dy_mm),
        "output_extent_x_mm": float(out.grid.x_mm[-1] - out.grid.x_mm[0]),
        "output_extent_y_mm": float(out.grid.y_mm[-1] - out.grid.y_mm[0]),
    }
    return PropagationResult(
        field=out,
        diagnostics=SamplingDiagnostics(method=method, metrics=metrics, warnings=tuple(warnings)),
        metadata={"method": method, "reference_independent": True, "transfer_model": str(transfer_model)},
    )


def propagate_angular_spectrum_batch(
    field: ScalarField2D,
    distances_mm: list[float] | tuple[float, ...] | np.ndarray,
    *,
    zero_padding_factor: float = 2.0,
    band_limited: bool = False,
    transfer_model: Literal["exact", "fresnel"] = "exact",
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    workspace_pool: PropagationWorkspacePool | None = None,
) -> tuple[PropagationResult, ...]:

    distances = tuple(float(value) for value in distances_mm)
    if any(value < 0.0 for value in distances):
        raise ValueError("current forward propagation interface requires distance_mm >= 0")
    if not distances:
        return ()
    working = zero_pad_field(field, zero_padding_factor)
    values = np.asarray(working.values, dtype=np.complex128)
    input_power = _field_power(values, working.grid.dx_mm, working.grid.dy_mm)
    results: list[PropagationResult] = []
    pool = workspace_pool or global_propagation_workspace_pool()
    with pool.acquire(values.shape) as workspace:
        workspace.fft2(values)
        for distance_mm in distances:
            transfer, transfer_metrics = _angular_spectrum_transfer(
                nx=values.shape[1], ny=values.shape[0],
                dx_mm=working.grid.dx_mm, dy_mm=working.grid.dy_mm,
                wavelength_nm=working.wavelength_nm, refractive_index=working.refractive_index,
                distance_mm=distance_mm, band_limited=band_limited, transfer_model=transfer_model,
            )
            output_workspace = workspace.propagate_spectrum(transfer)
            intensity = workspace.update_intensity(output_workspace)
            output_power = float(np.sum(intensity) * abs(working.grid.dx_mm * working.grid.dy_mm))
            edge_fraction = _edge_power_fraction_from_intensity(intensity)
            output = output_workspace.copy()
            out = _make_field(working, output, working.grid, working.z_mm + distance_mm)
            closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
            nyquist_margin = _nyquist_margin_from_phase_step(
                transfer_metrics["max_transfer_phase_step_x_rad"],
                transfer_metrics["max_transfer_phase_step_y_rad"],
            )
            warnings: list[str] = []
            if edge_fraction > float(edge_power_threshold):
                warnings.append(
                    f"输出边缘功率占比 {edge_fraction:.3g} 超过阈值 {edge_power_threshold:.3g}。"
                )
            if nyquist_margin < float(nyquist_margin_min):
                warnings.append(
                    f"角谱传递函数 Nyquist 余量 {nyquist_margin:.3g} 小于要求 {float(nyquist_margin_min):.3g}。"
                )
            if closure > float(energy_closure_threshold):
                warnings.append(
                    f"角谱传播能量闭合误差 {closure:.3g} 超过阈值 {float(energy_closure_threshold):.3g}。"
                )
            method = "band_limited_angular_spectrum" if band_limited else "angular_spectrum"
            metrics: dict[str, Any] = {
                **transfer_metrics,
                "zero_padding_factor": float(zero_padding_factor),
                "input_power_a.u.": input_power, "output_power_a.u.": output_power,
                "energy_closure_error": float(closure),
                "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
                "nyquist_margin_min": float(nyquist_margin),
                "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
                "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
                "edge_power_fraction": float(edge_fraction),
                "output_dx_mm": float(out.grid.dx_mm), "output_dy_mm": float(out.grid.dy_mm),
                "output_extent_x_mm": float(out.grid.x_mm[-1] - out.grid.x_mm[0]),
                "output_extent_y_mm": float(out.grid.y_mm[-1] - out.grid.y_mm[0]),
                "batch_forward_fft_reused": True,
            }
            results.append(PropagationResult(
                field=out, diagnostics=SamplingDiagnostics(method=method, metrics=metrics, warnings=tuple(warnings)),
                metadata={
                    "method": method, "reference_independent": True,
                    "transfer_model": str(transfer_model), "batch_forward_fft_reused": True,
                },
            ))
    return tuple(results)



def propagate_band_limited_angular_spectrum(
    field: ScalarField2D,
    distance_mm: float,
    *,
    zero_padding_factor: float = 2.0,
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    workspace_pool: PropagationWorkspacePool | None = None,
) -> PropagationResult:
    return propagate_angular_spectrum_advanced(
        field,
        distance_mm,
        zero_padding_factor=zero_padding_factor,
        band_limited=True,
        edge_power_threshold=edge_power_threshold,
        energy_closure_threshold=energy_closure_threshold,
        nyquist_margin_min=nyquist_margin_min,
    )



def propagate_scaled_angular_spectrum(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray,
    output_y_mm: np.ndarray,
    zero_padding_factor: float = 2.0,
    band_limited: bool = False,
    transfer_model: Literal["exact", "fresnel"] = "exact",
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    workspace_pool: PropagationWorkspacePool | None = None,
) -> PropagationResult:


    z = float(distance_mm)
    if z < 0.0:
        raise ValueError("scaled angular spectrum requires distance_mm >= 0.")
    working = zero_pad_field(field, zero_padding_factor)
    x1, dx1 = _uniform_axis(working.grid.x_mm, "input x")
    y1, dy1 = _uniform_axis(working.grid.y_mm, "input y")
    x2, dx2 = _uniform_axis(output_x_mm, "output x")
    y2, dy2 = _uniform_axis(output_y_mm, "output y")
    values = np.asarray(working.values, dtype=np.complex128)
    ny, nx = values.shape
    if values.shape != (y1.size, x1.size):
        raise ValueError("input field shape does not match input axes.")

    fx = np.fft.fftshift(np.fft.fftfreq(nx, d=dx1))
    fy = np.fft.fftshift(np.fft.fftfreq(ny, d=dy1))
    dfx = float(abs(fx[1] - fx[0]))
    dfy = float(abs(fy[1] - fy[0]))
    spectrum = (
        np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(values)))
        * dx1
        * dy1
    )
    transfer_unshifted, transfer_metrics = _angular_spectrum_transfer(
        nx=nx,
        ny=ny,
        dx_mm=dx1,
        dy_mm=dy1,
        wavelength_nm=working.wavelength_nm,
        refractive_index=working.refractive_index,
        distance_mm=z,
        band_limited=band_limited,
        transfer_model=transfer_model,
    )
    transfer = np.fft.fftshift(transfer_unshifted)
    np.multiply(spectrum, transfer, out=spectrum)
    output = _czt_inverse_2d(spectrum, fx, fy, x2, y2)
    output *= dfx * dfy

    grid = _grid_from_axes(x2, y2)
    out = _make_field(field, output, grid, field.z_mm + z)
    sampling_advice = advise_propagation_sampling(
        field, z, output_x_mm=x2, output_y_mm=y2,
        zero_padding_factor=zero_padding_factor,
    )
    input_power = _field_power(values, dx1, dy1)
    output_power = _field_power(output, dx2, dy2)
    edge_fraction = _edge_power_fraction(output)
    closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
    nyquist_margin = _nyquist_margin_from_phase_step(
        transfer_metrics["max_transfer_phase_step_x_rad"],
        transfer_metrics["max_transfer_phase_step_y_rad"],
    )
    warnings: list[str] = []
    if edge_fraction > float(edge_power_threshold):
        warnings.append(
            f"scaled angular-spectrum output edge-power fraction {edge_fraction:.3g} "
            f"exceeds {edge_power_threshold:.3g}."
        )
    if nyquist_margin < float(nyquist_margin_min):
        warnings.append(
            "Angular-spectrum transfer-function Nyquist margin "
            f"{nyquist_margin:.3g} is below {float(nyquist_margin_min):.3g}; "
            "increase the input window or use band-limited angular spectrum."
        )
    if closure > float(energy_closure_threshold):
        warnings.append(
            f"scaled angular-spectrum energy closure error {closure:.3g} "
            f"exceeds {float(energy_closure_threshold):.3g}."
        )
    method = (
        "scaled_band_limited_angular_spectrum"
        if band_limited
        else "scaled_angular_spectrum"
    )
    return PropagationResult(
        field=out,
        diagnostics=SamplingDiagnostics(
            method=method,
            metrics={
                **transfer_metrics,
                "zero_padding_factor": float(zero_padding_factor),
                "input_dx_mm": dx1,
                "input_dy_mm": dy1,
                "output_dx_mm": dx2,
                "output_dy_mm": dy2,
                "frequency_dx_per_mm": dfx,
                "frequency_dy_per_mm": dfy,
                "input_power_a.u.": input_power,
                "output_power_a.u.": output_power,
                "output_power_in_requested_window_a.u.": output_power,
                "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
                "energy_closure_error": float(closure),
                "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
                "nyquist_margin_min": float(nyquist_margin),
                "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
                "edge_power_fraction": edge_fraction,
                **sampling_advice.to_metrics(),
            },
            warnings=tuple(warnings),
        ),
        metadata={
            "method": method,
            "implementation": "angular_spectrum_czt_inverse_fourier",
            "reference_independent": True,
            "transfer_model": str(transfer_model),
            "fft_engine": "scipy.signal.czt",
        },
    )

def propagate_scaled_fresnel(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray,
    output_y_mm: np.ndarray,
    normalize_power: bool = False,
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    workspace_pool: PropagationWorkspacePool | None = None,
) -> PropagationResult:


    z = float(distance_mm)
    if z <= 0.0:
        raise ValueError("scaled Fresnel requires distance_mm > 0。")
    x1, dx1 = _uniform_axis(field.grid.x_mm, "input x")
    y1, dy1 = _uniform_axis(field.grid.y_mm, "input y")
    x2, dx2 = _uniform_axis(output_x_mm, "output x")
    y2, dy2 = _uniform_axis(output_y_mm, "output y")
    values = np.asarray(field.values, dtype=np.complex128)
    if values.shape != (y1.size, x1.size):
        raise ValueError("输入场形状与输入坐标不一致。")
    wavelength0_mm = float(field.wavelength_nm) * 1.0e-6
    n_medium = float(field.refractive_index)
    wavelength_mm = wavelength0_mm / n_medium
    k = 2.0 * np.pi / wavelength_mm

    input_phase_x = np.exp(1j * k * x1**2 / (2.0 * z))
    input_phase_y = np.exp(1j * k * y1**2 / (2.0 * z))
    pool = workspace_pool or global_propagation_workspace_pool()
    with pool.acquire(values.shape) as workspace:
        pre = workspace.spectral_product
        np.multiply(values, input_phase_y[:, None], out=pre)
        np.multiply(pre, input_phase_x[None, :], out=pre)
        fx2 = x2 / (wavelength_mm * z)
        fy2 = y2 / (wavelength_mm * z)
        transformed = _czt_forward_2d(pre, x1, y1, fx2, fy2)
    prefactor = np.exp(1j * k * z) / (1j * wavelength_mm * z)
    output_phase_x = np.exp(1j * k * x2**2 / (2.0 * z))
    output_phase_y = np.exp(1j * k * y2**2 / (2.0 * z))
    
    
    output = transformed
    output *= prefactor * dx1 * dy1
    output *= output_phase_y[:, None]
    output *= output_phase_x[None, :]
    input_power = _field_power(values, dx1, dy1)
    output_power = _field_power(output, dx2, dy2)
    if normalize_power and output_power > 0.0 and input_power > 0.0:
        output = output * np.sqrt(input_power / output_power)
        output_power = _field_power(output, dx2, dy2)
    grid = _grid_from_axes(x2, y2)
    out = _make_field(field, output, grid, field.z_mm + z)
    sampling_advice = advise_propagation_sampling(
        field, z, output_x_mm=x2, output_y_mm=y2, zero_padding_factor=1.0
    )
    edge_fraction = _edge_power_fraction(output)
    closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
    input_chirp_step_x = abs(k * max(abs(x1[0]), abs(x1[-1])) * dx1 / z)
    input_chirp_step_y = abs(k * max(abs(y1[0]), abs(y1[-1])) * dy1 / z)
    output_chirp_step_x = abs(k * max(abs(x2[0]), abs(x2[-1])) * dx2 / z)
    output_chirp_step_y = abs(k * max(abs(y2[0]), abs(y2[-1])) * dy2 / z)
    kernel_step_x = abs(2.0 * np.pi * max(abs(x2[0]), abs(x2[-1])) * dx1 / (wavelength_mm * z))
    kernel_step_y = abs(2.0 * np.pi * max(abs(y2[0]), abs(y2[-1])) * dy1 / (wavelength_mm * z))
    nyquist_margin = _nyquist_margin_from_phase_step(
        input_chirp_step_x, input_chirp_step_y,
        output_chirp_step_x, output_chirp_step_y,
        kernel_step_x, kernel_step_y,
    )
    fresnel_number_x = (max(abs(x1[0]), abs(x1[-1])) ** 2) / max(wavelength_mm * z, 1.0e-30)
    warnings: list[str] = []
    if edge_fraction > edge_power_threshold:
        warnings.append(
            f"scaled Fresnel 输出边缘功率占比 {edge_fraction:.3g} 超过阈值 {edge_power_threshold:.3g}。"
        )
    if closure > float(energy_closure_threshold):
        warnings.append(
            f"scaled Fresnel 能量闭合误差 {closure:.3g} 超过阈值 {float(energy_closure_threshold):.3g}。"
        )
    if nyquist_margin < float(nyquist_margin_min):
        warnings.append(
            f"scaled Fresnel Nyquist 余量 {nyquist_margin:.3g} 小于要求 {float(nyquist_margin_min):.3g}。"
        )
    
    na_est = max(abs(x1[0]), abs(x1[-1]), abs(y1[0]), abs(y1[-1])) / np.sqrt(
        z * z + max(abs(x1[0]), abs(x1[-1]), abs(y1[0]), abs(y1[-1])) ** 2
    )
    if na_est > 0.20:
        warnings.append(f"估算 NA={na_est:.3g}，scaled Fresnel 近轴误差可能不可忽略。")
    diagnostics = SamplingDiagnostics(
        method="scaled_fresnel",
        metrics={
            "input_dx_mm": dx1,
            "input_dy_mm": dy1,
            "output_dx_mm": dx2,
            "output_dy_mm": dy2,
            "input_power_a.u.": input_power,
            "output_power_a.u.": output_power,
            "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
            "energy_closure_error": float(closure),
            "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
            "edge_power_fraction": float(edge_fraction),
            "nyquist_margin_min": float(nyquist_margin),
            "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
            "input_chirp_phase_step_x_rad": float(input_chirp_step_x),
            "input_chirp_phase_step_y_rad": float(input_chirp_step_y),
            "output_chirp_phase_step_x_rad": float(output_chirp_step_x),
            "output_chirp_phase_step_y_rad": float(output_chirp_step_y),
            "kernel_phase_step_x_rad": float(kernel_step_x),
            "kernel_phase_step_y_rad": float(kernel_step_y),
            "fresnel_number_x": float(fresnel_number_x),
            "estimated_na": float(na_est),
            **sampling_advice.to_metrics(),
        },
        warnings=tuple(warnings),
    )
    return PropagationResult(
        field=out,
        diagnostics=diagnostics,
        metadata={"method": "scaled_fresnel_czt_fft", "reference_independent": True, "fft_engine": "scipy.signal.czt"},
    )


def _bilinear_complex_resample(
    values: np.ndarray,
    input_x: np.ndarray,
    input_y: np.ndarray,
    output_x: np.ndarray,
    output_y: np.ndarray,
) -> np.ndarray:
    from scipy.interpolate import RegularGridInterpolator

    x, _ = _uniform_axis(input_x, "input_x")
    y, _ = _uniform_axis(input_y, "input_y")
    ox = np.asarray(output_x, dtype=float)
    oy = np.asarray(output_y, dtype=float)
    yy, xx = np.meshgrid(oy, ox, indexing="ij")
    points = np.column_stack([yy.ravel(), xx.ravel()])
    real = RegularGridInterpolator((y, x), np.real(values), bounds_error=False, fill_value=0.0)
    imag = RegularGridInterpolator((y, x), np.imag(values), bounds_error=False, fill_value=0.0)
    return (real(points) + 1j * imag(points)).reshape(oy.size, ox.size)


def propagate_independent_sampling_rs(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray,
    output_y_mm: np.ndarray,
    oversampling_factor: float = 1.2,
    padding_factor: float = 0.1,
    max_virtual_grid: int = 2048,
    fallback_to_scaled_fresnel: bool = True,
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
) -> PropagationResult:


    from scipy.signal import fftconvolve

    z = float(distance_mm)
    if z <= 0.0:
        raise ValueError("ISSC/RS propagation requires distance_mm > 0。")
    x1, dx1 = _uniform_axis(field.grid.x_mm, "input x")
    y1, dy1 = _uniform_axis(field.grid.y_mm, "input y")
    x2, dx2 = _uniform_axis(output_x_mm, "output x")
    y2, dy2 = _uniform_axis(output_y_mm, "output y")
    wavelength0_mm = float(field.wavelength_nm) * 1.0e-6
    wavelength_mm = wavelength0_mm / float(field.refractive_index)
    k = 2.0 * np.pi / wavelength_mm

    
    
    max_delta_x = max(abs(x2[0] - x1[-1]), abs(x2[-1] - x1[0]))
    max_delta_y = max(abs(y2[0] - y1[-1]), abs(y2[-1] - y1[0]))
    rmax = np.sqrt(z * z + max_delta_x**2 + max_delta_y**2)
    fx_max = max_delta_x / max(wavelength_mm * rmax, 1.0e-30)
    fy_max = max_delta_y / max(wavelength_mm * rmax, 1.0e-30)
    nyquist_dx = 1.0 / max(2.0 * fx_max, 1.0e-30)
    nyquist_dy = 1.0 / max(2.0 * fy_max, 1.0e-30)
    gamma = max(float(oversampling_factor), 1.0)
    delta_x = min(dx1, dx2, nyquist_dx / gamma)
    delta_y = min(dy1, dy2, nyquist_dy / gamma)

    min_x = min(x1[0], x2[0])
    max_x = max(x1[-1], x2[-1])
    min_y = min(y1[0], y2[0])
    max_y = max(y1[-1], y2[-1])
    span_x = max_x - min_x
    span_y = max_y - min_y
    nx = int(np.ceil(span_x / delta_x)) + 1
    ny = int(np.ceil(span_y / delta_y)) + 1
    pad_x = int(np.ceil(max(float(padding_factor), 0.0) * nx))
    pad_y = int(np.ceil(max(float(padding_factor), 0.0) * ny))
    nx += 2 * pad_x
    ny += 2 * pad_y

    if nx > int(max_virtual_grid) or ny > int(max_virtual_grid):
        if not fallback_to_scaled_fresnel:
            raise MemoryError(
                f"ISSC virtual grid {ny}x{nx} exceeds max_virtual_grid={max_virtual_grid}."
            )
        fallback = propagate_scaled_fresnel(
            field,
            z,
            output_x_mm=x2,
            output_y_mm=y2,
            normalize_power=False,
            edge_power_threshold=edge_power_threshold,
            energy_closure_threshold=energy_closure_threshold,
            nyquist_margin_min=nyquist_margin_min,
        )
        warnings = list(fallback.diagnostics.warnings)
        warnings.append(
            f"ISSC virtual grid {ny}x{nx} exceeded {max_virtual_grid}; scaled Fresnel fallback used."
        )
        return PropagationResult(
            field=fallback.field,
            diagnostics=SamplingDiagnostics(
                method="issc_scaled_fresnel_fallback",
                metrics={
                    **fallback.diagnostics.metrics,
                    "requested_virtual_grid_x": nx,
                    "requested_virtual_grid_y": ny,
                    "kernel_nyquist_dx_mm": float(nyquist_dx),
                    "kernel_nyquist_dy_mm": float(nyquist_dy),
                },
                warnings=tuple(warnings),
            ),
            metadata={
                "method": "issc_independent_sampling_rs_fft",
                "implementation": "scaled_fresnel_fallback_due_to_virtual_grid_limit",
                "reference_independent": True,
            },
        )

    vx = min_x - pad_x * delta_x + np.arange(nx, dtype=float) * delta_x
    vy = min_y - pad_y * delta_y + np.arange(ny, dtype=float) * delta_y
    input_virtual = _bilinear_complex_resample(
        np.asarray(field.values, dtype=np.complex128), x1, y1, vx, vy
    )

    
    kx = (np.arange(2 * nx - 1, dtype=float) - (nx - 1)) * delta_x
    ky = (np.arange(2 * ny - 1, dtype=float) - (ny - 1)) * delta_y
    xx, yy = np.meshgrid(kx, ky, indexing="xy")
    r = np.sqrt(xx**2 + yy**2 + z**2)
    
    h = (z / (2.0 * np.pi * r)) * (1.0 / r - 1j * k) * np.exp(1j * k * r) / r
    convolved = fftconvolve(input_virtual, h, mode="same") * delta_x * delta_y
    output = _bilinear_complex_resample(convolved, vx, vy, x2, y2)
    grid = _grid_from_axes(x2, y2)
    out = _make_field(field, output, grid, field.z_mm + z)
    input_power = _field_power(field.values, dx1, dy1)
    output_power = _field_power(output, dx2, dy2)
    edge_fraction = _edge_power_fraction(output)
    closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
    nyquist_margin = float(min(nyquist_dx / max(delta_x, 1.0e-30), nyquist_dy / max(delta_y, 1.0e-30)))
    warnings: list[str] = []
    if edge_fraction > float(edge_power_threshold):
        warnings.append(
            f"ISSC output edge-power fraction {edge_fraction:.3g} exceeds {float(edge_power_threshold):.3g}."
        )
    if closure > float(energy_closure_threshold):
        warnings.append(
            f"ISSC energy closure error {closure:.3g} exceeds {float(energy_closure_threshold):.3g}."
        )
    if nyquist_margin < float(nyquist_margin_min):
        warnings.append(
            f"ISSC kernel Nyquist margin {nyquist_margin:.3g} is below {float(nyquist_margin_min):.3g}."
        )
    diagnostics = SamplingDiagnostics(
        method="issc",
        metrics={
            "virtual_grid_x": nx,
            "virtual_grid_y": ny,
            "virtual_dx_mm": float(delta_x),
            "virtual_dy_mm": float(delta_y),
            "kernel_nyquist_dx_mm": float(nyquist_dx),
            "kernel_nyquist_dy_mm": float(nyquist_dy),
            "oversampling_factor": gamma,
            "padding_factor": float(padding_factor),
            "input_power_a.u.": input_power,
            "output_power_a.u.": output_power,
            "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
            "energy_closure_error": float(closure),
            "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
            "edge_power_fraction": float(edge_fraction),
            "nyquist_margin_min": float(nyquist_margin),
            "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
        },
        warnings=tuple(warnings),
    )
    return PropagationResult(
        field=out,
        diagnostics=diagnostics,
        metadata={
            "method": "issc_independent_sampling_rs_fft",
            "implementation": "virtual_equal_pitch_rs1_linear_convolution",
            "reference_independent": True,
        },
    )


def propagate_complex_field(
    field: ScalarField2D,
    distance_mm: float,
    *,
    method: PropagationMethod,
    output_x_mm: np.ndarray | None = None,
    output_y_mm: np.ndarray | None = None,
    zero_padding_factor: float = 2.0,
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
    issc_oversampling_factor: float = 1.2,
    issc_padding_factor: float = 0.1,
    issc_max_virtual_grid: int = 2048,
    scaled_angular_spectrum_transfer_model: Literal["exact", "fresnel"] = "exact",
    workspace_pool: PropagationWorkspacePool | None = None,
) -> PropagationResult:
    selected = str(method)
    if selected == "angular_spectrum":
        return propagate_angular_spectrum_advanced(
            field,
            distance_mm,
            zero_padding_factor=zero_padding_factor,
            band_limited=False,
            edge_power_threshold=edge_power_threshold,
            energy_closure_threshold=energy_closure_threshold,
            nyquist_margin_min=nyquist_margin_min,
            workspace_pool=workspace_pool,
        )
    if selected == "band_limited_angular_spectrum":
        return propagate_band_limited_angular_spectrum(
            field,
            distance_mm,
            zero_padding_factor=zero_padding_factor,
            edge_power_threshold=edge_power_threshold,
            energy_closure_threshold=energy_closure_threshold,
            nyquist_margin_min=nyquist_margin_min,
            workspace_pool=workspace_pool,
        )
    if output_x_mm is None or output_y_mm is None:
        raise ValueError(f"{selected} 需要显式 output_x_mm/output_y_mm。")
    if selected == "scaled_angular_spectrum":
        return propagate_scaled_angular_spectrum(
            field,
            distance_mm,
            output_x_mm=output_x_mm,
            output_y_mm=output_y_mm,
            zero_padding_factor=zero_padding_factor,
            band_limited=False,
            transfer_model=scaled_angular_spectrum_transfer_model,
            edge_power_threshold=edge_power_threshold,
            energy_closure_threshold=energy_closure_threshold,
            nyquist_margin_min=nyquist_margin_min,
            workspace_pool=workspace_pool,
        )
    if selected == "scaled_fresnel":
        return propagate_scaled_fresnel(
            field,
            distance_mm,
            output_x_mm=output_x_mm,
            output_y_mm=output_y_mm,
            edge_power_threshold=edge_power_threshold,
            energy_closure_threshold=energy_closure_threshold,
            nyquist_margin_min=nyquist_margin_min,
            workspace_pool=workspace_pool,
        )
    if selected == "issc":
        return propagate_independent_sampling_rs(
            field,
            distance_mm,
            output_x_mm=output_x_mm,
            output_y_mm=output_y_mm,
            oversampling_factor=issc_oversampling_factor,
            padding_factor=issc_padding_factor,
            max_virtual_grid=issc_max_virtual_grid,
            edge_power_threshold=edge_power_threshold,
            energy_closure_threshold=energy_closure_threshold,
            nyquist_margin_min=nyquist_margin_min,
        )
    raise ValueError(f"unknown propagation method: {method!r}")


def propagate_complex_field_batch(
    field: ScalarField2D,
    distances_mm: list[float] | tuple[float, ...] | np.ndarray,
    *,
    method: PropagationMethod = "angular_spectrum",
    output_x_mm: np.ndarray | None = None,
    output_y_mm: np.ndarray | None = None,
    **options: Any,
) -> tuple[PropagationResult, ...]:

    selected = str(method)
    if selected in {"angular_spectrum", "band_limited_angular_spectrum"}:
        return propagate_angular_spectrum_batch(
            field, distances_mm,
            zero_padding_factor=float(options.get("zero_padding_factor", 2.0)),
            band_limited=selected == "band_limited_angular_spectrum",
            transfer_model=str(options.get("transfer_model", "exact")),
            edge_power_threshold=float(options.get("edge_power_threshold", 1.0e-4)),
            energy_closure_threshold=float(options.get("energy_closure_threshold", 5.0e-3)),
            nyquist_margin_min=float(options.get("nyquist_margin_min", 1.0)),
            workspace_pool=options.get("workspace_pool"),
        )
    return tuple(
        propagate_complex_field(
            field, float(distance), method=selected,
            output_x_mm=output_x_mm, output_y_mm=output_y_mm, **options,
        )
        for distance in distances_mm
    )


__all__ = [
    "PropagationMethod",
    "SamplingDiagnostics",
    "PropagationResult",
    "zero_pad_field",
    "propagate_angular_spectrum_advanced",
    "propagate_angular_spectrum_batch",
    "propagate_band_limited_angular_spectrum",
    "propagate_scaled_angular_spectrum",
    "propagate_scaled_fresnel",
    "propagate_independent_sampling_rs",
    "propagate_complex_field",
    "propagate_complex_field_batch",
    "clear_propagation_spectrum_cache",
    "clear_czt_plan_cache",
    "clear_all_propagation_caches",
    "propagation_spectrum_cache_info",
]
