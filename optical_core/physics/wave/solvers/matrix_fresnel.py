
from __future__ import annotations

import math
from typing import Any

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.wave.solvers.advanced_propagation import (
    PropagationResult,
    SamplingDiagnostics,
)


def _power(values: np.ndarray, dx: float, dy: float) -> float:
    return float(np.sum(np.abs(values) ** 2) * abs(float(dx) * float(dy)))


def _edge_power(values: np.ndarray) -> float:
    intensity = np.abs(values) ** 2
    ny, nx = intensity.shape
    border = max(1, min(nx, ny) // 32)
    mask = np.zeros_like(intensity, dtype=bool)
    mask[:border, :] = mask[-border:, :] = True
    mask[:, :border] = mask[:, -border:] = True
    total = float(np.sum(intensity))
    return float(np.sum(intensity[mask]) / total) if total > 0.0 else 0.0


def propagate_matrix_fresnel(
    field: ScalarField2D,
    distance_mm: float,
    *,
    output_x_mm: np.ndarray,
    output_y_mm: np.ndarray,
    edge_power_threshold: float = 2.0e-3,
    energy_closure_threshold: float = 1.5e-2,
) -> PropagationResult:


    z = float(distance_mm)
    if z <= 0.0:
        raise ValueError("matrix Fresnel requires distance_mm > 0")
    x1 = np.asarray(field.grid.x_mm, dtype=float)
    y1 = np.asarray(field.grid.y_mm, dtype=float)
    x2 = np.asarray(output_x_mm, dtype=float)
    y2 = np.asarray(output_y_mm, dtype=float)
    if min(x1.size, y1.size, x2.size, y2.size) < 2:
        raise ValueError("all Fresnel axes require at least two samples")
    dx1 = abs(float(np.mean(np.diff(x1))))
    dy1 = abs(float(np.mean(np.diff(y1))))
    dx2 = abs(float(np.mean(np.diff(x2))))
    dy2 = abs(float(np.mean(np.diff(y2))))
    wavelength_mm = float(field.wavelength_nm) * 1.0e-6 / float(field.refractive_index)
    k = 2.0 * math.pi / wavelength_mm

    xx1, yy1 = np.meshgrid(x1, y1, indexing="xy")
    input_chirp = np.exp(1j * k * (xx1 * xx1 + yy1 * yy1) / (2.0 * z))
    pre = np.asarray(field.values, dtype=np.complex128) * input_chirp
    kernel_x = np.exp(-1j * (k / z) * np.outer(x2, x1))
    kernel_y = np.exp(-1j * (k / z) * np.outer(y2, y1))
    integral = (kernel_y @ pre @ kernel_x.T) * dx1 * dy1
    xx2, yy2 = np.meshgrid(x2, y2, indexing="xy")
    prefactor = np.exp(1j * k * z) / (1j * wavelength_mm * z)
    output = prefactor * np.exp(1j * k * (xx2 * xx2 + yy2 * yy2) / (2.0 * z)) * integral

    input_power = _power(field.values, dx1, dy1)
    output_power = _power(output, dx2, dy2)
    closure = abs(output_power - input_power) / max(abs(input_power), 1.0e-30)
    edge = _edge_power(output)
    warnings: list[str] = []
    if edge > float(edge_power_threshold):
        warnings.append(f"edge power {edge:.6g} exceeds {edge_power_threshold:.6g}")
    if closure > float(energy_closure_threshold):
        warnings.append(f"energy closure {closure:.6g} exceeds {energy_closure_threshold:.6g}")
    grid = SamplingGrid2D(x_mm=x2, y_mm=y2, dx_mm=dx2, dy_mm=dy2)
    out_field = ScalarField2D(
        values=output,
        grid=grid,
        wavelength_nm=field.wavelength_nm,
        refractive_index=field.refractive_index,
        z_mm=field.z_mm + z,
        integrated_power=output_power,
    )
    diagnostics = SamplingDiagnostics(
        method="matrix_fresnel",
        metrics={
            "input_power_a.u.": input_power,
            "output_power_a.u.": output_power,
            "energy_closure_error": closure,
            "edge_power_fraction": edge,
            "nyquist_margin_min": float("nan"),
            "matrix_shape_x": [int(x2.size), int(x1.size)],
            "matrix_shape_y": [int(y2.size), int(y1.size)],
        },
        warnings=tuple(warnings),
    )
    return PropagationResult(
        field=out_field,
        diagnostics=diagnostics,
        metadata={
            "method": "matrix_fresnel",
            "algorithm": "separable_direct_fresnel_integral",
            "fft_used": False,
            "reference_independent": True,
        },
    )


__all__ = ["propagate_matrix_fresnel"]
