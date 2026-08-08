
from __future__ import annotations

from dataclasses import replace
import numpy as np

from optical_core.physics.wave.operators.fft_operator import fft2_centered, ifft2_centered
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.solvers.advanced_propagation import (
    PropagationResult,
    SamplingDiagnostics,
    zero_pad_field,
)


def _field_power(field_values: np.ndarray, dx_mm: float, dy_mm: float) -> float:
    return float(np.sum(np.abs(field_values) ** 2) * abs(float(dx_mm) * float(dy_mm)))


def _edge_power_fraction(values: np.ndarray, edge_pixels: int | None = None) -> float:
    intensity = np.asarray(np.abs(values) ** 2, dtype=float)
    if intensity.size == 0:
        return 0.0
    ny, nx = intensity.shape
    border = int(edge_pixels or max(1, min(nx, ny) // 32))
    border = max(1, min(border, max(nx // 2, 1), max(ny // 2, 1)))
    mask = np.zeros_like(intensity, dtype=bool)
    mask[:border, :] = True
    mask[-border:, :] = True
    mask[:, :border] = True
    mask[:, -border:] = True
    total = float(np.sum(intensity))
    return float(np.sum(intensity[mask]) / total) if total > 0.0 else 0.0


def _transfer_and_metrics(field: ScalarField2D, distance_mm: float) -> tuple[np.ndarray, dict[str, float]]:
    wavelength0_mm = field.wavelength_nm * 1.0e-6
    wavelength_medium_mm = wavelength0_mm / field.refractive_index
    ny, nx = field.values.shape
    fx = np.fft.fftshift(np.fft.fftfreq(nx, d=field.grid.dx_mm))
    fy = np.fft.fftshift(np.fft.fftfreq(ny, d=field.grid.dy_mm))
    fxx, fyy = np.meshgrid(fx, fy, indexing="xy")
    root = 1.0 - (wavelength_medium_mm * fxx) ** 2 - (wavelength_medium_mm * fyy) ** 2
    propagating = root >= 0.0
    k = 2.0 * np.pi / wavelength_medium_mm
    transfer = np.zeros_like(root, dtype=np.complex128)
    transfer[propagating] = np.exp(1j * k * float(distance_mm) * np.sqrt(root[propagating]))

    
    
    phase = np.zeros_like(root, dtype=float)
    phase[propagating] = np.angle(transfer[propagating])
    phase_x = np.unwrap(phase, axis=1)
    phase_y = np.unwrap(phase, axis=0)
    max_step_x = float(np.max(np.abs(np.diff(phase_x, axis=1)))) if nx > 1 else 0.0
    max_step_y = float(np.max(np.abs(np.diff(phase_y, axis=0)))) if ny > 1 else 0.0
    max_step = max(max_step_x, max_step_y)
    nyquist_margin = float("inf") if max_step <= 0.0 else float(np.pi / max_step)
    return transfer, {
        "max_transfer_phase_step_x_rad": max_step_x,
        "max_transfer_phase_step_y_rad": max_step_y,
        "nyquist_margin_min": nyquist_margin,
        "transfer_nonzero_fraction": float(np.count_nonzero(transfer) / transfer.size),
    }


def propagate_angular_spectrum(field: ScalarField2D, distance_mm: float) -> ScalarField2D:


    transfer, _ = _transfer_and_metrics(field, distance_mm)
    output = ifft2_centered(fft2_centered(field.values) * transfer)
    power = _field_power(output, field.grid.dx_mm, field.grid.dy_mm)
    return replace(
        field,
        values=output,
        z_mm=field.z_mm + float(distance_mm),
        integrated_power=power,
    )


def propagate_angular_spectrum_with_diagnostics(
    field: ScalarField2D,
    distance_mm: float,
    *,
    zero_padding_factor: float = 1.0,
    edge_power_threshold: float = 1.0e-4,
    energy_closure_threshold: float = 5.0e-3,
    nyquist_margin_min: float = 1.0,
) -> PropagationResult:


    factor = float(zero_padding_factor)
    if not np.isfinite(factor) or factor < 1.0:
        raise ValueError("zero_padding_factor must be finite and >= 1")
    working = zero_pad_field(field, factor)
    transfer, transfer_metrics = _transfer_and_metrics(working, distance_mm)
    output = ifft2_centered(fft2_centered(working.values) * transfer)
    input_power = _field_power(working.values, working.grid.dx_mm, working.grid.dy_mm)
    output_power = _field_power(output, working.grid.dx_mm, working.grid.dy_mm)
    closure = float(abs(output_power - input_power) / max(abs(input_power), 1.0e-30))
    
    
    
    edge_pixels = max(1, min(field.values.shape) // 32)
    edge_fraction = _edge_power_fraction(output, edge_pixels=edge_pixels)
    nyquist_margin = float(transfer_metrics["nyquist_margin_min"])

    warnings: list[str] = []
    if closure > float(energy_closure_threshold):
        warnings.append(
            f"angular-spectrum energy closure error {closure:.3g} exceeds "
            f"{float(energy_closure_threshold):.3g}."
        )
    if edge_fraction > float(edge_power_threshold):
        warnings.append(
            f"angular-spectrum edge power fraction {edge_fraction:.3g} exceeds "
            f"{float(edge_power_threshold):.3g}."
        )
    if nyquist_margin < float(nyquist_margin_min):
        warnings.append(
            f"angular-spectrum Nyquist margin {nyquist_margin:.3g} is below "
            f"{float(nyquist_margin_min):.3g}."
        )

    propagated = replace(
        working,
        values=output,
        z_mm=working.z_mm + float(distance_mm),
        integrated_power=output_power,
    )
    metrics = {
        "zero_padding_factor": factor,
        "input_grid_size_x": int(field.values.shape[1]),
        "input_grid_size_y": int(field.values.shape[0]),
        "output_grid_size_x": int(output.shape[1]),
        "output_grid_size_y": int(output.shape[0]),
        "input_power_a.u.": input_power,
        "output_power_a.u.": output_power,
        "power_capture_ratio": float(output_power / max(abs(input_power), 1.0e-30)),
        "energy_closure_error": closure,
        "energy_closure_pass": bool(closure <= float(energy_closure_threshold)),
        "edge_power_fraction": edge_fraction,
        "edge_band_pixels": int(edge_pixels),
        "edge_band_width_x_mm": float(edge_pixels * abs(working.grid.dx_mm)),
        "edge_band_width_y_mm": float(edge_pixels * abs(working.grid.dy_mm)),
        "edge_power_pass": bool(edge_fraction <= float(edge_power_threshold)),
        "nyquist_margin_min": nyquist_margin,
        "nyquist_pass": bool(nyquist_margin >= float(nyquist_margin_min)),
        "output_dx_mm": float(working.grid.dx_mm),
        "output_dy_mm": float(working.grid.dy_mm),
        "output_extent_x_mm": float(np.ptp(working.grid.x_mm)),
        "output_extent_y_mm": float(np.ptp(working.grid.y_mm)),
        **transfer_metrics,
    }
    padded = bool(output.shape != field.values.shape)
    return PropagationResult(
        field=propagated,
        diagnostics=SamplingDiagnostics(
            method="angular_spectrum",
            metrics=metrics,
            warnings=tuple(warnings),
        ),
        metadata={
            "method": "angular_spectrum",
            "same_grid": not padded,
            "same_sample_pitch": True,
            "receiver_window_expanded_by_zero_padding": padded,
            "legacy_field_numerics_preserved": not padded,
            "legacy_field_numerics_preserved_when_unpadded": True,
            "reference_independent": True,
        },
    )


__all__ = [
    "propagate_angular_spectrum",
    "propagate_angular_spectrum_with_diagnostics",
]
