

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import FieldNormalization, PowerUnit, ScalarField2D


def gaussian_fiber_mode(
    grid: SamplingGrid2D,
    *,
    wavelength_nm: float,
    mode_field_diameter_x_um: float,
    mode_field_diameter_y_um: float | None = None,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    tilt_x_rad: float = 0.0,
    tilt_y_rad: float = 0.0,
    refractive_index: float = 1.0,
) -> ScalarField2D:


    mfd_y = mode_field_diameter_y_um if mode_field_diameter_y_um is not None else mode_field_diameter_x_um
    wx_mm = max(float(mode_field_diameter_x_um) * 1e-3 / 2.0, 1e-12)
    wy_mm = max(float(mfd_y) * 1e-3 / 2.0, 1e-12)
    x, y = np.meshgrid(grid.x_mm, grid.y_mm, indexing="xy")
    envelope = np.exp(-(((x - offset_x_mm) / wx_mm) ** 2 + ((y - offset_y_mm) / wy_mm) ** 2))

    
    

    wavelength_mm = max(float(wavelength_nm) * 1.0e-6, 1.0e-15)
    n_medium = max(float(refractive_index), 1.0e-12)
    k_mm = 2.0 * math.pi * n_medium / wavelength_mm
    phase = k_mm * (float(tilt_x_rad) * (x - offset_x_mm) + float(tilt_y_rad) * (y - offset_y_mm))
    values = (envelope * np.exp(1j * phase)).astype(np.complex128)
    power = float(np.sum(np.abs(values) ** 2) * abs(grid.dx_mm * grid.dy_mm))
    return ScalarField2D(
        values=values, grid=grid, wavelength_nm=wavelength_nm,
        refractive_index=n_medium, z_mm=0.0, integrated_power=power,
        power_unit=PowerUnit.ARBITRARY, normalization=FieldNormalization.ARBITRARY,
    )


def material_na(n_core: float, n_clad: float) -> float:

    core = float(n_core)
    clad = float(n_clad)
    return float(math.sqrt(max(core * core - clad * clad, 0.0)))


def relative_index_difference(n_core: float, n_clad: float) -> float:
    core = max(float(n_core), 1.0e-15)
    clad = float(n_clad)
    return float((core - clad) / core)


def v_number(core_radius_um: float, wavelength_nm: float, na: float) -> float:
    wavelength_um = max(float(wavelength_nm) * 1e-3, 1.0e-15)
    return float(2.0 * math.pi * float(core_radius_um) * float(na) / wavelength_um)


def marcuse_mode_radius_um(core_radius_um: float, v_value: float) -> float:

    a = max(float(core_radius_um), 1.0e-15)
    v = max(float(v_value), 1.0e-9)
    return float(a * (0.65 + 1.619 / (v ** 1.5) + 2.879 / (v ** 6.0)))


def gaussian_na_from_mode_radius(mode_radius_um: float, wavelength_nm: float) -> float:
    radius = max(float(mode_radius_um), 1.0e-15)
    wavelength_um = max(float(wavelength_nm) * 1e-3, 1.0e-15)
    return float(wavelength_um / (math.pi * radius))


def normal_facet_transmission(n_out: float, n_effective: float) -> float:
    outside = float(n_out)
    effective = float(n_effective)
    denom = outside + effective
    if denom == 0.0:
        return 0.0
    reflectance = ((outside - effective) / denom) ** 2
    return float(np.clip(1.0 - reflectance, 0.0, 1.0))


def db_loss_to_transmission(loss_db: float) -> float:
    return float(10.0 ** (-max(float(loss_db), 0.0) / 10.0))


@dataclass(frozen=True, slots=True)
class StepIndexFiberSpec:
    core_radius_um: float = 4.1
    n_core: float = 1.4500
    n_clad: float = 1.4440
    wavelength_nm: float = 550.0
    length_m: float = 0.0
    attenuation_db_per_km: float = 0.0
    connector_loss_db: float = 0.0
    outside_index: float = 1.0


@dataclass(frozen=True, slots=True)
class FiberModeSolution:
    wavelength_nm: float
    n_core: float
    n_clad: float
    n_effective: float
    material_na: float
    relative_index_difference: float
    v_number: float
    single_mode: bool
    mode_radius_um: float
    mfd_x_um: float
    mfd_y_um: float
    gaussian_na: float
    facet_transmission: float
    propagation_transmission: float
    connector_transmission: float
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


def solve_step_index_fiber_mode(spec: StepIndexFiberSpec) -> FiberModeSolution:
    na = material_na(spec.n_core, spec.n_clad)
    v = v_number(spec.core_radius_um, spec.wavelength_nm, na)
    single_mode = bool(v <= 2.405)
    mode_radius = marcuse_mode_radius_um(spec.core_radius_um, max(v, 1.0e-9))
    n_eff = float(0.5 * (float(spec.n_core) + float(spec.n_clad)))
    facet_t = normal_facet_transmission(spec.outside_index, n_eff)
    prop_t = db_loss_to_transmission(float(spec.attenuation_db_per_km) * max(float(spec.length_m), 0.0) / 1000.0)
    conn_t = db_loss_to_transmission(spec.connector_loss_db)
    warnings: list[str] = []
    if not single_mode:
        warnings.append("V number exceeds 2.405; Gaussian LP01 approximation may be optimistic.")
    solution = FiberModeSolution(
        wavelength_nm=float(spec.wavelength_nm),
        n_core=float(spec.n_core),
        n_clad=float(spec.n_clad),
        n_effective=n_eff,
        material_na=na,
        relative_index_difference=relative_index_difference(spec.n_core, spec.n_clad),
        v_number=v,
        single_mode=single_mode,
        mode_radius_um=mode_radius,
        mfd_x_um=2.0 * mode_radius,
        mfd_y_um=2.0 * mode_radius,
        gaussian_na=gaussian_na_from_mode_radius(mode_radius, spec.wavelength_nm),
        facet_transmission=facet_t,
        propagation_transmission=prop_t,
        connector_transmission=conn_t,
        warnings=tuple(warnings),
    )
    object.__setattr__(
        solution,
        "metrics",
        {
            "fiber_material_na": solution.material_na,
            "fiber_relative_index_difference": solution.relative_index_difference,
            "fiber_v_number": solution.v_number,
            "fiber_single_mode": solution.single_mode,
            "fiber_mode_radius_um": solution.mode_radius_um,
            "fiber_mode_field_diameter_um": solution.mfd_x_um,
            "fiber_gaussian_na": solution.gaussian_na,
            "fiber_facet_transmission": solution.facet_transmission,
            "fiber_propagation_transmission": solution.propagation_transmission,
            "fiber_connector_transmission": solution.connector_transmission,
        },
    )
    return solution


def solve_lp01_eigenvalues(v_value: float) -> tuple[float, float]:
    from scipy.optimize import brentq
    from scipy.special import jv, kv

    v = max(float(v_value), 1.0e-9)
    upper = min(v * (1.0 - 1.0e-10), 2.4048255577 * (1.0 - 1.0e-10))
    lower = max(min(1.0e-6, upper * 1.0e-3), 1.0e-12)

    def characteristic(u: float) -> float:
        w = math.sqrt(max(v * v - u * u, 1.0e-30))
        j0 = float(jv(0, u))
        k0 = float(kv(0, w))
        if abs(j0) < 1.0e-15 or abs(k0) < 1.0e-300:
            return float("nan")
        return float(u * jv(1, u) / j0 - w * kv(1, w) / k0)

    samples = np.linspace(lower, upper, 512, dtype=float)
    values = np.asarray([characteristic(float(u)) for u in samples], dtype=float)
    finite = np.isfinite(values)
    for index in range(samples.size - 1):
        if not (finite[index] and finite[index + 1]):
            continue
        y0, y1 = values[index], values[index + 1]
        if y0 == 0.0:
            u = float(samples[index])
            return u, math.sqrt(max(v * v - u * u, 0.0))
        if y0 * y1 < 0.0:
            u = float(brentq(characteristic, float(samples[index]), float(samples[index + 1]), xtol=1.0e-13))
            return u, math.sqrt(max(v * v - u * u, 0.0))
    u = float(min(max(v / math.sqrt(2.0), lower), upper))
    return u, math.sqrt(max(v * v - u * u, 0.0))


def step_index_lp01_mode(
    grid: SamplingGrid2D,
    *,
    wavelength_nm: float,
    core_radius_um: float,
    n_core: float,
    n_clad: float,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
    tilt_x_rad: float = 0.0,
    tilt_y_rad: float = 0.0,
) -> ScalarField2D:

# 采用此有界近似维持光场连续性，用于逼近展宽的弱导模式。

    from scipy.special import jv, kv

    radius_um = max(float(core_radius_um), 1.0e-12)
    na = material_na(n_core, n_clad)
    v = v_number(radius_um, wavelength_nm, na)
    u, w = solve_lp01_eigenvalues(v)

    xx, yy = np.meshgrid(grid.x_mm, grid.y_mm, indexing="xy")
    radial_um = np.sqrt((xx - float(offset_x_mm)) ** 2 + (yy - float(offset_y_mm)) ** 2) * 1.0e3
    rho = radial_um / radius_um
    envelope = np.empty_like(rho, dtype=float)
    core = rho <= 1.0
    envelope[core] = jv(0, u * rho[core])
    if np.any(~core):
        k0w = float(kv(0, max(w, 1.0e-12)))
        scale = float(jv(0, u) / max(k0w, 1.0e-300))
        envelope[~core] = scale * kv(0, max(w, 1.0e-12) * rho[~core])

    wavelength_mm = max(float(wavelength_nm) * 1.0e-6, 1.0e-15)
    k_mm = 2.0 * math.pi * float(0.5 * (n_core + n_clad)) / wavelength_mm
    phase = k_mm * (
        float(tilt_x_rad) * (xx - float(offset_x_mm))
        + float(tilt_y_rad) * (yy - float(offset_y_mm))
    )
    values = np.asarray(envelope * np.exp(1j * phase), dtype=np.complex128)
    area = abs(float(grid.dx_mm) * float(grid.dy_mm))
    power = float(np.sum(np.abs(values) ** 2) * area)
    if power > 0.0 and np.isfinite(power):
        values /= math.sqrt(power)
        power = 1.0
    return ScalarField2D(
        values=values,
        grid=grid,
        wavelength_nm=float(wavelength_nm),
        refractive_index=float(0.5 * (n_core + n_clad)),
        z_mm=0.0,
        integrated_power=power,
        power_unit=PowerUnit.ARBITRARY,
        normalization=FieldNormalization.UNIT_POWER,
    )
