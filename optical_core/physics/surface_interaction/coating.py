
from __future__ import annotations

import cmath
import math
from typing import Iterable

import numpy as np

from optical_core.models.domain.coating import CoatingLayerSpec
from optical_core.physics.surface_interaction.models import CoatingAmplitudeResult

_C_M_PER_S = 299_792_458.0


def _forward_cosine(n0: complex, theta0: float, n: complex) -> complex:
    transverse = n0 * math.sin(float(theta0)) / n
    value = cmath.sqrt(1.0 - transverse * transverse)
    
    
    if value.real < 0.0 or (abs(value.real) < 1.0e-15 and value.imag > 0.0):
        value = -value
    return value


def _admittance(n: complex, cos_theta: complex, polarization: str) -> complex:
    if polarization == "s":
        return n * cos_theta
    return n / cos_theta


def _single_polarization(
    wavelength_nm: float,
    incident_angle_rad: float,
    n_incident: complex,
    n_substrate: complex,
    layers: Iterable[CoatingLayerSpec],
    polarization: str,
    temperature_c: float,
) -> tuple[complex, complex, float, float, float, complex]:
    cos0 = complex(math.cos(float(incident_angle_rad)), 0.0)
    coss = _forward_cosine(n_incident, incident_angle_rad, n_substrate)
    q0 = _admittance(n_incident, cos0, polarization)
    qs = _admittance(n_substrate, coss, polarization)
    matrix = np.eye(2, dtype=np.complex128)
    for layer in layers:
        n_layer = layer.index_at_temperature(temperature_c)
        thickness_nm = layer.thickness_at_temperature_nm(temperature_c)
        cos_layer = _forward_cosine(n_incident, incident_angle_rad, n_layer)
        q = _admittance(n_layer, cos_layer, polarization)
        delta = 2.0 * math.pi * n_layer * cos_layer * thickness_nm / float(wavelength_nm)
        c = cmath.cos(delta)
        s = 1j * cmath.sin(delta)
        matrix = matrix @ np.asarray([[c, s / q], [s * q, c]], dtype=np.complex128)
    b = matrix[0, 0] + matrix[0, 1] * qs
    c_term = matrix[1, 0] + matrix[1, 1] * qs
    denominator = q0 * b + c_term
    r = complex((q0 * b - c_term) / denominator)
    t_tangential = complex(2.0 * q0 / denominator)

    # The characteristic-matrix p admittance q=n/cos(theta) is written for
    # tangential electric field.  Downstream Jones propagation, however, stores
    # coefficients against unit s/p polarization vectors.  Convert the p
    # transmission coefficient back to the full electric-field amplitude; for s
    # the two conventions are identical.  Power transmission must use the same
    # optical-admittance convention as the characteristic matrix.  Reusing
    # n*cos(theta) for p can produce the unphysical result R+T>1 at oblique
    # incidence.
    if polarization == "p":
        if abs(coss) <= 1.0e-30:
            t = 0.0j
        else:
            t = complex(t_tangential * cos0 / coss)
    else:
        t = t_tangential

    reflectance = float(abs(r) ** 2)
    incident_flux = max(float(np.real(q0)), 1.0e-30)
    transmitted_flux = max(float(np.real(qs)), 0.0)
    transmittance = float(transmitted_flux / incident_flux * abs(t_tangential) ** 2)

    reflectance = max(reflectance, 0.0)
    transmittance = max(transmittance, 0.0)
    absorption = max(1.0 - reflectance - transmittance, 0.0)
    return r, t, reflectance, transmittance, absorption, coss


def _group_delay(
    wavelength_nm: float,
    phase_selector,
    *,
    relative_step: float = 1.0e-5,
) -> float:

    delta = max(abs(float(wavelength_nm)) * relative_step, 1.0e-5)
    lam_minus = max(float(wavelength_nm) - delta, 1.0e-9)
    lam_plus = float(wavelength_nm) + delta
    phases = np.unwrap(
        np.asarray(
            [cmath.phase(phase_selector(lam_minus)), cmath.phase(phase_selector(lam_plus))],
            dtype=float,
        )
    )
    omega_minus = 2.0 * math.pi * _C_M_PER_S / (lam_minus * 1.0e-9)
    omega_plus = 2.0 * math.pi * _C_M_PER_S / (lam_plus * 1.0e-9)
    return float((phases[1] - phases[0]) / (omega_plus - omega_minus))


def coating_amplitudes(
    *,
    wavelength_nm: float,
    incident_angle_rad: float,
    n_incident: complex,
    n_substrate: complex,
    layers: tuple[CoatingLayerSpec, ...] = (),
    temperature_c: float = 20.0,
    include_group_delay: bool = False,
) -> CoatingAmplitudeResult:

    if wavelength_nm <= 0.0:
        raise ValueError("wavelength_nm must be positive")
    if not 0.0 <= incident_angle_rad < math.pi / 2.0:
        raise ValueError("incident_angle_rad must be in [0, pi/2)")
    if complex(n_incident).real <= 0.0 or complex(n_substrate).real <= 0.0:
        raise ValueError("incident/substrate refractive indices must have positive real part")

    def one(lam: float, pol: str):
        return _single_polarization(
            lam,
            incident_angle_rad,
            complex(n_incident),
            complex(n_substrate),
            layers,
            pol,
            temperature_c,
        )

    rs, ts, Rs, Ts, As, cos_sub = one(float(wavelength_nm), "s")
    rp, tp, Rp, Tp, Ap, _ = one(float(wavelength_nm), "p")
    sin_sub = complex(n_incident) * math.sin(incident_angle_rad) / complex(n_substrate)
    tir = bool(abs(sin_sub) > 1.0 and abs(complex(n_substrate).imag) < 1.0e-14)
    theta_sub = None if tir else cmath.asin(sin_sub)

    gd = {
        "rs": 0.0,
        "rp": 0.0,
        "ts": 0.0,
        "tp": 0.0,
    }
    if include_group_delay:
        gd["rs"] = _group_delay(wavelength_nm, lambda lam: one(lam, "s")[0])
        gd["ts"] = _group_delay(wavelength_nm, lambda lam: one(lam, "s")[1])
        gd["rp"] = _group_delay(wavelength_nm, lambda lam: one(lam, "p")[0])
        gd["tp"] = _group_delay(wavelength_nm, lambda lam: one(lam, "p")[1])

    return CoatingAmplitudeResult(
        rs=rs,
        rp=rp,
        ts=ts,
        tp=tp,
        Rs=Rs,
        Rp=Rp,
        Ts=Ts,
        Tp=Tp,
        absorption_s=As,
        absorption_p=Ap,
        incident_angle_rad=float(incident_angle_rad),
        transmitted_angle_rad=theta_sub,
        total_internal_reflection=tir,
        group_delay_reflection_s=gd["rs"],
        group_delay_reflection_p=gd["rp"],
        group_delay_transmission_s=gd["ts"],
        group_delay_transmission_p=gd["tp"],
        metadata={
            "model": "complex_characteristic_matrix",
            "layer_count": len(layers),
            "temperature_c": float(temperature_c),
            "n_incident": complex(n_incident),
            "n_substrate": complex(n_substrate),
            "cos_transmitted": cos_sub,
            "energy_error_s": abs(Rs + Ts + As - 1.0),
            "energy_error_p": abs(Rp + Tp + Ap - 1.0),
        },
    )


__all__ = ["coating_amplitudes"]
