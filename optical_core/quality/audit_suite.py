from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True, slots=True)
class AuditReport:
    metrics: dict[str, float]
    warnings: list[str]
    metadata: dict[str, Any]


def aliasing_audit(field: Any, *, edge_threshold: float = 1e-3) -> AuditReport:
    arr = np.asarray(field, dtype=complex)
    spectrum = np.fft.fftshift(np.fft.fft2(arr))
    power = np.abs(spectrum) ** 2
    total = float(np.sum(power))
    if total <= 0:
        frac = 0.0
    else:
        edge = float(np.sum(power[0, :]) + np.sum(power[-1, :]) + np.sum(power[1:-1, 0]) + np.sum(power[1:-1, -1]))
        frac = edge / total
    warnings = [] if frac <= edge_threshold else [f"possible aliasing: Fourier edge power fraction {frac:.3g}"]
    return AuditReport(
        metrics={"aliasing_edge_power_fraction": frac, "aliasing_ok": 1.0 if not warnings else 0.0},
        warnings=warnings,
        metadata={"audit": "aliasing"},
    )


def sampling_audit(*, grid_size: int, extent_mm: float, wavelength_nm: float, propagation_distance_mm: float | None = None) -> AuditReport:
    dx = float(extent_mm) / max(int(grid_size) - 1, 1)
    wavelength_mm = float(wavelength_nm) * 1e-6
    fresnel_number = None
    metrics = {"sampling_grid_size": float(grid_size), "sampling_pitch_mm": dx, "sampling_wavelength_mm": wavelength_mm}
    warnings: list[str] = []
    if dx <= 0:
        warnings.append("non-positive sampling pitch")
    if propagation_distance_mm is not None:
        fresnel_number = (float(extent_mm) ** 2) / max(wavelength_mm * float(propagation_distance_mm), 1e-30)
        metrics["sampling_fresnel_number"] = float(fresnel_number)
        if fresnel_number > grid_size:
            warnings.append("Fresnel sampling may be too coarse for requested distance")
    if grid_size < 17:
        warnings.append("grid_size is very small; numerical optics results may be unstable")
    metrics["sampling_ok"] = 1.0 if not warnings else 0.0
    return AuditReport(metrics=metrics, warnings=warnings, metadata={"audit": "sampling"})


def performance_audit(*, grid_size: int, ray_count: int = 0, complex_arrays: int = 2) -> AuditReport:
    estimated_bytes = int(grid_size) * int(grid_size) * int(complex_arrays) * 16
    estimated_mb = estimated_bytes / (1024.0 * 1024.0)
    
    estimated_ops = float(max(grid_size, 1) ** 2 * np.log2(max(grid_size, 2)) + max(ray_count, 0))
    warnings = []
    if estimated_mb > 512:
        warnings.append("estimated memory exceeds 512 MB")
    return AuditReport(
        metrics={"performance_estimated_memory_mb": estimated_mb, "performance_estimated_work_units": estimated_ops, "performance_ok": 1.0 if not warnings else 0.0},
        warnings=warnings,
        metadata={"audit": "performance"},
    )


def standard_benchmarks() -> dict[str, dict[str, float]]:

    return {
        "air_flat_propagation": {"expected_valid_ray_ratio": 1.0, "expected_wavefront_rms_nm": 0.0},
        "unit_gaussian_overlap": {"expected_coupling_efficiency": 1.0},
        "normal_incidence_air_glass": {"expected_unpolarized_reflectance_approx": 0.04},
    }


def run_quality_audit_suite(options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    opts = dict(options or {})
    grid_size = int(opts.get("grid_size", 65))
    extent_mm = float(opts.get("extent_mm", opts.get("field_extent_mm", 1.0)))
    wavelength_nm = float(opts.get("wavelength_nm", 550.0))
    propagation_distance_mm = opts.get("propagation_distance_mm", None)
    start = time.perf_counter()
    axis = np.linspace(-1.0, 1.0, grid_size)
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    field = np.exp(-(xx * xx + yy * yy) / 0.25)
    reports = [
        aliasing_audit(field),
        sampling_audit(grid_size=grid_size, extent_mm=extent_mm, wavelength_nm=wavelength_nm, propagation_distance_mm=propagation_distance_mm),
        performance_audit(grid_size=grid_size, ray_count=int(opts.get("ray_count", 0))),
    ]
    metrics: dict[str, float] = {}
    warnings: list[str] = []
    for report in reports:
        metrics.update(report.metrics)
        warnings.extend(report.warnings)
    metrics["quality_audit_elapsed_ms"] = (time.perf_counter() - start) * 1000.0
    metrics["quality_audit_passed"] = 1.0 if not warnings else 0.0
    return {"metrics": metrics, "warnings": warnings, "metadata": {"quality_audit_suite_done": True}, "benchmarks": standard_benchmarks()}
