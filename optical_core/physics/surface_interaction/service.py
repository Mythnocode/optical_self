
from __future__ import annotations

import cmath
import math
from typing import Iterable

import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.representations.ray import Ray
from optical_core.physics.geometric.formulas.reflection import reflect_direction
from optical_core.physics.geometric.formulas.snell import refract_direction
from optical_core.physics.geometric.formulas.surface_normal import surface_normal_from_point
from optical_core.physics.surface_interaction.coating import coating_amplitudes
from optical_core.physics.surface_interaction.models import SurfaceInteractionResult


def _normalised(values: np.ndarray, *, name: str) -> np.ndarray:
    vector = np.asarray(values, dtype=np.complex128 if np.iscomplexobj(values) else float)
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1.0e-15:
        raise ValueError(f"{name} must be non-zero and finite")
    return vector / norm


def _surface_basis(direction: np.ndarray, normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    s = np.cross(direction, normal)
    if np.linalg.norm(s) <= 1.0e-12:
        reference = np.asarray([1.0, 0.0, 0.0])
        if abs(float(np.dot(reference, direction))) > 0.9:
            reference = np.asarray([0.0, 1.0, 0.0])
        s = np.cross(direction, reference)
    s = np.asarray(_normalised(s, name="s-polarization basis"), dtype=float)
    p = np.asarray(_normalised(np.cross(s, direction), name="p-polarization basis"), dtype=float)
    return s, p


def _polarized_branch(
    ray: Ray,
    *,
    outgoing_direction: np.ndarray,
    s_basis: np.ndarray,
    p_incident: np.ndarray,
    coefficient_s: complex,
    coefficient_p: complex,
    power_s: float,
    power_p: float,
    extra_survival: float,
    phase_label: str,
) -> tuple[Ray, float, complex]:
    incident_pol = np.asarray(ray.polarization_xyz, dtype=np.complex128)
    es = complex(np.vdot(s_basis, incident_pol))
    ep = complex(np.vdot(p_incident, incident_pol))
    p_out = np.asarray(
        _normalised(np.cross(s_basis, outgoing_direction), name="outgoing p basis"),
        dtype=float,
    )
    vector = coefficient_s * es * s_basis + coefficient_p * ep * p_out
    vector_norm = float(np.linalg.norm(vector))
    incident_norm2 = max(abs(es) ** 2 + abs(ep) ** 2, 1.0e-30)
    power_fraction = max(
        (float(power_s) * abs(es) ** 2 + float(power_p) * abs(ep) ** 2) / incident_norm2,
        0.0,
    ) * max(float(extra_survival), 0.0)
    if vector_norm <= 1.0e-30 or power_fraction <= 0.0:
        raise ValueError(f"{phase_label} branch has zero field")
    vector /= vector_norm
    coherent = (np.conj(es) * coefficient_s * es + np.conj(ep) * coefficient_p * ep) / incident_norm2
    phase = float(cmath.phase(complex(coherent))) if abs(coherent) > 0.0 else 0.0
    power = float(ray.power_weight) * power_fraction
    out = Ray(
        position_mm=ray.position_mm,
        direction=tuple(float(v) for v in outgoing_direction),
        wavelength_nm=ray.wavelength_nm,
        field_amplitude=float(ray.field_amplitude) * math.sqrt(power_fraction),
        power_weight=power,
        quadrature_weight=ray.quadrature_weight,
        optical_path_mm=ray.optical_path_mm,
        valid=True,
        polarization_xyz=tuple(complex(v) for v in vector),
        phase_offset_rad=float(ray.phase_offset_rad) + phase,
    )
    return out, power, coherent


def _roughness_specular_survival(
    roughness_rms_nm: float,
    wavelength_nm: float,
    incident_angle_rad: float,
) -> float:
    if roughness_rms_nm <= 0.0:
        return 1.0
    exponent = -((4.0 * math.pi * float(roughness_rms_nm) * math.cos(incident_angle_rad)) / float(wavelength_nm)) ** 2
    return float(np.clip(math.exp(exponent), 0.0, 1.0))


def _grating_branches(
    ray: Ray,
    surface: OpticalSurface,
    *,
    base_direction: np.ndarray,
    available_power_fraction: float,
) -> tuple[tuple[Ray, ...], tuple[int, ...]]:
    if surface.grating_period_um is None or not surface.grating_orders:
        return (), ()
    wavelength_mm = float(ray.wavelength_nm) * 1.0e-6
    period_mm = float(surface.grating_period_um) * 1.0e-3
    ky = float(base_direction[1])
    rays: list[Ray] = []
    orders: list[int] = []
    for order, efficiency in zip(surface.grating_orders, surface.grating_efficiencies, strict=True):
        kx = float(base_direction[0]) + int(order) * wavelength_mm / period_mm
        transverse2 = kx * kx + ky * ky
        if transverse2 >= 1.0 or efficiency <= 0.0:
            continue
        kz = math.copysign(math.sqrt(max(1.0 - transverse2, 0.0)), float(base_direction[2]))
        direction = np.asarray([kx, ky, kz], dtype=float)
        fraction = float(available_power_fraction) * float(efficiency)
        rays.append(
            Ray(
                position_mm=ray.position_mm,
                direction=tuple(direction),
                wavelength_nm=ray.wavelength_nm,
                field_amplitude=float(ray.field_amplitude) * math.sqrt(max(fraction, 0.0)),
                power_weight=float(ray.power_weight) * max(fraction, 0.0),
                quadrature_weight=ray.quadrature_weight,
                optical_path_mm=ray.optical_path_mm,
                valid=True,
                polarization_xyz=ray.polarization_xyz,
                phase_offset_rad=float(ray.phase_offset_rad),
            )
        )
        orders.append(int(order))
    return tuple(rays), tuple(orders)


def interact_ray_with_surface(
    ray: Ray,
    surface: OpticalSurface,
    *,
    hit_point_mm: np.ndarray,
    n_before: float,
    n_after: float,
    temperature_c: float = 20.0,
    include_group_delay: bool = False,
) -> SurfaceInteractionResult:

    direction = np.asarray(ray.direction, dtype=float)
    direction = np.asarray(_normalised(direction, name="incident direction"), dtype=float)
    normal = surface_normal_from_point(
        np.asarray(hit_point_mm, dtype=float),
        radius_mm=surface.radius_mm,
        conic=surface.conic,
        asphere_a2=surface.asphere_a2,
        asphere_coefficients=surface.asphere_coefficients,
        surface_type=surface.surface_type,
        metadata=surface.metadata,
    )
    if float(np.dot(direction, normal)) > 0.0:
        normal = -normal
    cos_i = float(np.clip(-np.dot(direction, normal), 0.0, 1.0))
    theta_i = float(math.acos(cos_i))
    s_basis, p_incident = _surface_basis(direction, normal)
    coating = coating_amplitudes(
        wavelength_nm=float(ray.wavelength_nm),
        incident_angle_rad=theta_i,
        n_incident=complex(float(n_before), 0.0),
        n_substrate=complex(float(n_after), 0.0),
        layers=tuple(surface.coating_layers),
        temperature_c=float(temperature_c),
        include_group_delay=bool(include_group_delay),
    )
    reflection_direction = reflect_direction(direction, normal)
    transmission_direction, refraction_ok = refract_direction(direction, normal, float(n_before), float(n_after))

    explicit_survival = 1.0 - float(surface.surface_absorption_fraction)
    specular_survival = _roughness_specular_survival(
        float(surface.roughness_rms_nm), float(ray.wavelength_nm), theta_i
    )
    branch_survival = explicit_survival * specular_survival
    surface_type = str(surface.surface_type).strip().lower()
    mirror = surface_type in {"mirror", "reflective", "reflection"}

    transmitted_ray: Ray | None = None
    reflected_ray: Ray | None = None
    transmitted_power = 0.0
    reflected_power = 0.0
    phase_delay = 0.0

    if mirror:
        
        if surface.coating_layers:
            rs, rp, Rs, Rp = coating.rs, coating.rp, coating.Rs, coating.Rp
        else:
            amplitude = complex(-math.sqrt(branch_survival), 0.0)
            rs = rp = amplitude
            Rs = Rp = branch_survival
        try:
            reflected_ray, reflected_power, coherent = _polarized_branch(
                ray,
                outgoing_direction=np.asarray(reflection_direction, dtype=float),
                s_basis=s_basis,
                p_incident=p_incident,
                coefficient_s=rs,
                coefficient_p=rp,
                power_s=Rs,
                power_p=Rp,
                extra_survival=branch_survival if surface.coating_layers else 1.0,
                phase_label="reflection",
            )
        except ValueError:
            reflected_ray = None
        if reflected_ray is not None:
            phase_delay = float(reflected_ray.phase_offset_rad - ray.phase_offset_rad)
    else:
        if refraction_ok and not coating.total_internal_reflection:
            try:
                transmitted_ray, transmitted_power, coherent = _polarized_branch(
                    ray,
                    outgoing_direction=np.asarray(transmission_direction, dtype=float),
                    s_basis=s_basis,
                    p_incident=p_incident,
                    coefficient_s=coating.ts,
                    coefficient_p=coating.tp,
                    power_s=coating.Ts,
                    power_p=coating.Tp,
                    extra_survival=branch_survival,
                    phase_label="transmission",
                )
                phase_delay = float(transmitted_ray.phase_offset_rad - ray.phase_offset_rad)
            except ValueError:
                transmitted_ray = None
        try:
            reflected_ray, reflected_power, _ = _polarized_branch(
                ray,
                outgoing_direction=np.asarray(reflection_direction, dtype=float),
                s_basis=s_basis,
                p_incident=p_incident,
                coefficient_s=coating.rs,
                coefficient_p=coating.rp,
                power_s=coating.Rs,
                power_p=coating.Rp,
                extra_survival=branch_survival,
                phase_label="reflection",
            )
        except ValueError:
            reflected_ray = None

    input_power = float(ray.power_weight)
    scattered_fraction = 1.0 - specular_survival
    explicit_absorbed_estimate = input_power * float(surface.surface_absorption_fraction)
    coating_absorption_estimate = input_power * branch_survival * 0.5 * (
        float(coating.absorption_s) + float(coating.absorption_p)
    )
    scattered_power = input_power * explicit_survival * scattered_fraction
    
    
    
    
    absorbed_power = max(input_power - transmitted_power - reflected_power - scattered_power, 0.0)
    accounted = transmitted_power + reflected_power + absorbed_power + scattered_power
    energy_error = abs(accounted - input_power) / max(input_power, 1.0e-30)

    grating_rays: tuple[Ray, ...] = ()
    grating_orders: tuple[int, ...] = ()
    if transmitted_ray is not None and surface.grating_orders:
        grating_rays, grating_orders = _grating_branches(
            transmitted_ray,
            surface,
            base_direction=np.asarray(transmitted_ray.direction, dtype=float),
            available_power_fraction=1.0,
        )

    return SurfaceInteractionResult(
        transmitted_ray=transmitted_ray,
        reflected_ray=reflected_ray,
        transmission_jones=np.diag([coating.ts, coating.tp]).astype(np.complex128),
        reflection_jones=np.diag([coating.rs, coating.rp]).astype(np.complex128),
        transmitted_power=float(transmitted_power),
        reflected_power=float(reflected_power),
        absorbed_power=float(absorbed_power),
        phase_delay_rad=float(phase_delay),
        incident_angle_rad=theta_i,
        total_internal_reflection=bool(coating.total_internal_reflection or not refraction_ok),
        diffraction_rays=grating_rays,
        diffraction_orders=grating_orders,
        energy_error=float(energy_error),
        diagnostics={
            "surface_index": int(surface.index),
            "coating_layer_count": len(surface.coating_layers),
            "input_power": input_power,
            "transmitted_power": transmitted_power,
            "reflected_power": reflected_power,
            "absorbed_power": absorbed_power,
            "scattered_power": scattered_power,
            "specular_survival": specular_survival,
            "surface_absorption_fraction": float(surface.surface_absorption_fraction),
            "explicit_absorbed_power_estimate": explicit_absorbed_estimate,
            "coating_absorbed_power_estimate": coating_absorption_estimate,
            "coating_Rs": coating.Rs,
            "coating_Rp": coating.Rp,
            "coating_Ts": coating.Ts,
            "coating_Tp": coating.Tp,
            "coating_absorption_s": coating.absorption_s,
            "coating_absorption_p": coating.absorption_p,
            "coating_energy_error_s": coating.energy_error_s,
            "coating_energy_error_p": coating.energy_error_p,
            "energy_accounted_power": accounted,
            "energy_error": energy_error,
        },
    )


__all__ = ["interact_ray_with_surface"]
