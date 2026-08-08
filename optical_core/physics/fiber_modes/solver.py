# 光纤模式计算模块。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.models.representations.vector_field import VectorField2D, lift_scalar_field_to_jones
from optical_core.physics.hybrid.operators.fiber_mode import (
    gaussian_fiber_mode,
    material_na,
    solve_lp01_eigenvalues,
    step_index_lp01_mode,
    v_number,
)


@dataclass(frozen=True, slots=True)
class FiberModeMetrics:
    mode_name: str
    effective_index: float
    propagation_constant_rad_per_mm: float
    effective_area_um2: float
    mfd_x_um: float
    mfd_y_um: float
    integrated_power: float
    cutoff: bool
    vector_fraction_longitudinal: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FiberModeResult:
    scalar_field: ScalarField2D
    vector_field: VectorField2D | None
    metrics: FiberModeMetrics
    warnings: tuple[str, ...] = ()


def _mode_moments(values: np.ndarray, grid: SamplingGrid2D) -> tuple[float, float, float]:
    intensity = np.abs(np.asarray(values)) ** 2
    area = abs(float(grid.dx_mm) * float(grid.dy_mm))
    power = float(np.sum(intensity) * area)
    if power <= 0.0:
        return 0.0, 0.0, 0.0
    xx, yy = np.meshgrid(grid.x_mm, grid.y_mm, indexing="xy")
    cx = float(np.sum(intensity * xx) * area / power)
    cy = float(np.sum(intensity * yy) * area / power)
    var_x = float(np.sum(intensity * (xx - cx) ** 2) * area / power)
    var_y = float(np.sum(intensity * (yy - cy) ** 2) * area / power)
    denominator = float(np.sum(intensity**2) * area)
    effective_area_mm2 = power * power / max(denominator, 1.0e-30)
    return 4.0 * np.sqrt(max(var_x, 0.0)) * 1.0e3, 4.0 * np.sqrt(max(var_y, 0.0)) * 1.0e3, effective_area_mm2 * 1.0e6


def _scalar_metrics(
    field: ScalarField2D,
    *,
    mode_name: str,
    effective_index: float,
    cutoff: bool,
    metadata: dict[str, Any] | None = None,
) -> FiberModeMetrics:
    mfd_x, mfd_y, effective_area = _mode_moments(field.values, field.grid)
    wavelength_mm = float(field.wavelength_nm) * 1.0e-6
    beta = 2.0 * np.pi * float(effective_index) / wavelength_mm
    return FiberModeMetrics(
        mode_name=mode_name,
        effective_index=float(effective_index),
        propagation_constant_rad_per_mm=float(beta),
        effective_area_um2=float(effective_area),
        mfd_x_um=float(mfd_x),
        mfd_y_um=float(mfd_y),
        integrated_power=float(field.integrated_power),
        cutoff=bool(cutoff),
        metadata=dict(metadata or {}),
    )


def solve_gaussian_mode(
    grid: SamplingGrid2D,
    *,
    wavelength_nm: float,
    mfd_x_um: float,
    mfd_y_um: float,
    refractive_index: float = 1.0,
    jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j),
    **placement: float,
) -> FiberModeResult:
    scalar = gaussian_fiber_mode(
        grid,
        wavelength_nm=wavelength_nm,
        mode_field_diameter_x_um=mfd_x_um,
        mode_field_diameter_y_um=mfd_y_um,
        refractive_index=refractive_index,
        **placement,
    ).normalized()
    vector = lift_scalar_field_to_jones(scalar, jones_vector).normalized()
    return FiberModeResult(
        scalar_field=scalar,
        vector_field=vector,
        metrics=_scalar_metrics(
            scalar,
            mode_name="gaussian",
            effective_index=refractive_index,
            cutoff=False,
            metadata={"fidelity": "engineering_gaussian"},
        ),
    )


def solve_lp01_mode(
    grid: SamplingGrid2D,
    *,
    wavelength_nm: float,
    core_radius_um: float,
    n_core: float,
    n_clad: float,
    jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j),
    **placement: float,
) -> FiberModeResult:
    scalar = step_index_lp01_mode(
        grid,
        wavelength_nm=wavelength_nm,
        core_radius_um=core_radius_um,
        n_core=n_core,
        n_clad=n_clad,
        **placement,
    ).normalized()
    v = v_number(core_radius_um, wavelength_nm, material_na(n_core, n_clad))
    u, _ = solve_lp01_eigenvalues(v)
    k0 = 2.0 * np.pi / (float(wavelength_nm) * 1.0e-6)
    beta = np.sqrt(max((n_core * k0) ** 2 - (u / (core_radius_um * 1.0e-3)) ** 2, 0.0))
    n_eff = float(beta / k0)
    vector = lift_scalar_field_to_jones(scalar, jones_vector).normalized()
    return FiberModeResult(
        scalar_field=scalar,
        vector_field=vector,
        metrics=_scalar_metrics(
            scalar,
            mode_name="lp01_weak_guidance",
            effective_index=n_eff,
            cutoff=False,
            metadata={"fidelity": "scalar_step_index_eigenmode", "V": v, "u": u},
        ),
    )


def solve_he11_vector_mode(
    grid: SamplingGrid2D,
    *,
    wavelength_nm: float,
    core_radius_um: float,
    n_core: float,
    n_clad: float,
    jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j),
    **placement: float,
) -> FiberModeResult:

    lp = solve_lp01_mode(
        grid,
        wavelength_nm=wavelength_nm,
        core_radius_um=core_radius_um,
        n_core=n_core,
        n_clad=n_clad,
        jones_vector=jones_vector,
        **placement,
    )
    transverse = lift_scalar_field_to_jones(lp.scalar_field, jones_vector)
    beta = float(lp.metrics.propagation_constant_rad_per_mm)
    dex_dx = np.gradient(transverse.ex, float(grid.dx_mm), axis=1, edge_order=2)
    dey_dy = np.gradient(transverse.ey, float(grid.dy_mm), axis=0, edge_order=2)
    ez = 1j * (dex_dx + dey_dy) / max(beta, 1.0e-30)
    vector = VectorField2D(
        ex=transverse.ex,
        ey=transverse.ey,
        ez=ez,
        grid=grid,
        wavelength_nm=wavelength_nm,
        refractive_index=lp.metrics.effective_index,
    ).normalized()
    longitudinal_fraction = float(
        np.sum(np.abs(vector.ez) ** 2) / max(np.sum(vector.intensity), 1.0e-30)
    )
    metrics = FiberModeMetrics(
        mode_name="he11_vector",
        effective_index=lp.metrics.effective_index,
        propagation_constant_rad_per_mm=lp.metrics.propagation_constant_rad_per_mm,
        effective_area_um2=lp.metrics.effective_area_um2,
        mfd_x_um=lp.metrics.mfd_x_um,
        mfd_y_um=lp.metrics.mfd_y_um,
        integrated_power=vector.integrated_power,
        cutoff=False,
        vector_fraction_longitudinal=longitudinal_fraction,
        metadata={
            **dict(lp.metrics.metadata),
            "fidelity": "vector_step_index_with_transversality_correction",
        },
    )
    return FiberModeResult(lp.scalar_field, vector, metrics, lp.warnings)


def solve_finite_difference_mode(
    grid: SamplingGrid2D,
    *,
    wavelength_nm: float,
    refractive_index_map: np.ndarray,
    mode_count: int = 1,
    mode_index: int = 0,
    jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j),
) -> FiberModeResult:

    from scipy.sparse import diags, eye, kron
    from scipy.sparse.linalg import eigsh

    n_map = np.asarray(refractive_index_map, dtype=float)
    expected = (grid.y_mm.size, grid.x_mm.size)
    if n_map.shape != expected or not np.all(np.isfinite(n_map)) or np.min(n_map) <= 0.0:
        raise ValueError("refractive_index_map must be positive, finite and match the grid")
    ny, nx = expected
    dx = float(grid.dx_mm)
    dy = float(grid.dy_mm)
    tx = diags([np.ones(nx - 1), -2.0 * np.ones(nx), np.ones(nx - 1)], [-1, 0, 1]) / dx**2
    ty = diags([np.ones(ny - 1), -2.0 * np.ones(ny), np.ones(ny - 1)], [-1, 0, 1]) / dy**2
    laplacian = kron(eye(ny), tx) + kron(ty, eye(nx))
    k0 = 2.0 * np.pi / (float(wavelength_nm) * 1.0e-6)
    operator = laplacian + diags((k0 * n_map.ravel()) ** 2, 0)
    count = max(int(mode_count), int(mode_index) + 1)
    eigenvalues, eigenvectors = eigsh(operator, k=count, which="LA")
    order = np.argsort(eigenvalues)[::-1]
    eigenvalue = float(eigenvalues[order[int(mode_index)]])
    values = np.asarray(eigenvectors[:, order[int(mode_index)]].reshape(expected), dtype=np.complex128)
    phase = np.angle(values[np.unravel_index(np.argmax(np.abs(values)), values.shape)])
    values *= np.exp(-1j * phase)
    area = abs(dx * dy)
    power = float(np.sum(np.abs(values) ** 2) * area)
    values /= np.sqrt(max(power, 1.0e-30))
    scalar = ScalarField2D(
        values=values,
        grid=grid,
        wavelength_nm=wavelength_nm,
        refractive_index=float(np.max(n_map)),
        z_mm=0.0,
        integrated_power=1.0,
    )
    beta = np.sqrt(max(eigenvalue, 0.0))
    n_eff = float(beta / k0)
    vector = lift_scalar_field_to_jones(scalar, jones_vector).normalized()
    return FiberModeResult(
        scalar_field=scalar,
        vector_field=vector,
        metrics=_scalar_metrics(
            scalar,
            mode_name="finite_difference_eigenmode",
            effective_index=n_eff,
            cutoff=not (float(np.min(n_map)) < n_eff <= float(np.max(n_map)) + 1.0e-9),
            metadata={
                "fidelity": "scalar_finite_difference_helmholtz",
                "eigenvalue_beta2": eigenvalue,
                "mode_index": int(mode_index),
            },
        ),
    )


def imported_mode_field(
    scalar_field: ScalarField2D,
    *,
    vector_field: VectorField2D | None = None,
    mode_name: str = "imported_measured_mode",
) -> FiberModeResult:
    scalar = scalar_field.normalized()
    vector = vector_field.normalized() if vector_field is not None else None
    effective_index = float(
        vector.refractive_index if vector is not None else scalar.refractive_index
    )
    return FiberModeResult(
        scalar_field=scalar,
        vector_field=vector,
        metrics=_scalar_metrics(
            scalar,
            mode_name=mode_name,
            effective_index=effective_index,
            cutoff=False,
            metadata={"fidelity": "imported_field"},
        ),
    )


def mode_orthogonality_matrix(modes: list[ScalarField2D]) -> np.ndarray:
    if not modes:
        return np.empty((0, 0), dtype=np.complex128)
    reference = modes[0]
    area = abs(float(reference.grid.dx_mm) * float(reference.grid.dy_mm))
    matrix = np.empty((len(modes), len(modes)), dtype=np.complex128)
    for i, left in enumerate(modes):
        for j, right in enumerate(modes):
            if left.values.shape != right.values.shape:
                raise ValueError("all modes must share a grid")
            denominator = np.sqrt(left.integrated_power * right.integrated_power)
            matrix[i, j] = (
                np.sum(left.values * np.conj(right.values)) * area / denominator
                if denominator > 0.0
                else 0.0
            )
    return matrix


__all__ = [
    "FiberModeMetrics",
    "FiberModeResult",
    "solve_gaussian_mode",
    "solve_lp01_mode",
    "solve_he11_vector_mode",
    "solve_finite_difference_mode",
    "imported_mode_field",
    "mode_orthogonality_matrix",
]
