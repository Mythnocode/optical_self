
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D
from optical_core.physics.hybrid.operators.overlap_decomposition import decompose_scalar_overlap
from optical_core.physics.hybrid.operators.zernike import STANDARD_TERMS, ZernikeTerm, zernike


@dataclass(frozen=True, slots=True)
class AberrationSensitivity:
    term_index: int
    term_name: str
    coefficient_waves_rms: np.ndarray
    efficiency: np.ndarray
    loss_db: np.ndarray
    local_loss_db_per_wave2: float
    zero_coefficient_efficiency: float = 0.0
    maximum_efficiency: float = 0.0
    maximum_coefficient_waves_rms: float = 0.0
    zero_is_local_maximum: bool = False


def _aberration_summary(coefficients: np.ndarray, eta: np.ndarray) -> tuple[np.ndarray, float, float, float, bool]:
    zero_index = int(np.argmin(np.abs(coefficients)))
    zero_eta = max(float(eta[zero_index]), 1e-30)
    loss_db = -10.0 * np.log10(np.maximum(eta / zero_eta, 1e-30))
    symmetric_curvatures: list[float] = []
    for index, coefficient in enumerate(coefficients):
        if coefficient <= 1e-12:
            continue
        opposite = int(np.argmin(np.abs(coefficients + coefficient)))
        if abs(float(coefficients[opposite] + coefficient)) > 1e-9:
            continue
        symmetric_loss = 0.5 * (float(loss_db[index]) + float(loss_db[opposite]))
        symmetric_curvatures.append(symmetric_loss / max(float(coefficient) ** 2, 1e-30))
    if symmetric_curvatures:
        local = float(np.median(symmetric_curvatures))
    else:
        nonzero = np.abs(coefficients) > 1e-12
        local = float(np.median(loss_db[nonzero] / np.maximum(coefficients[nonzero] ** 2, 1e-30))) if np.any(nonzero) else 0.0
    maximum_index = int(np.argmax(eta))
    tolerance = max(1e-12, 1e-9 * abs(zero_eta))
    zero_is_maximum = bool(float(eta[maximum_index]) <= zero_eta + tolerance)
    return loss_db, local, zero_eta, float(coefficients[maximum_index]), zero_is_maximum


def apply_zernike_aberration(
    field: ScalarField2D,
    term: ZernikeTerm,
    coefficient_waves_rms: float,
    *,
    pupil_radius_mm: float | None = None,
) -> ScalarField2D:
    x, y = np.meshgrid(field.grid.x_mm, field.grid.y_mm, indexing="xy")
    radius = float(pupil_radius_mm) if pupil_radius_mm is not None else max(np.max(np.abs(field.grid.x_mm)), np.max(np.abs(field.grid.y_mm)))
    if radius <= 0.0:
        raise ValueError("pupil radius must be positive")
    rho = np.sqrt(x * x + y * y) / radius
    theta = np.arctan2(y, x)
    mask = rho <= 1.0
    phase = np.zeros_like(rho)
    phase[mask] = 2.0 * np.pi * float(coefficient_waves_rms) * zernike(term, rho[mask], theta[mask], normalization="noll")
    values = field.values * np.exp(1j * phase)
    return ScalarField2D(
        values=values,
        grid=field.grid,
        wavelength_nm=field.wavelength_nm,
        refractive_index=field.refractive_index,
        z_mm=field.z_mm,
    )


def scan_zernike_coupling_sensitivity(
    field: ScalarField2D,
    receiving_mode: ScalarField2D,
    *,
    coefficients_waves_rms: np.ndarray,
    terms: Iterable[ZernikeTerm] = STANDARD_TERMS[3:],
    pupil_radius_mm: float | None = None,
) -> tuple[AberrationSensitivity, ...]:
    coefficients = np.asarray(coefficients_waves_rms, dtype=float).reshape(-1)
    if coefficients.size < 3 or not np.any(np.isclose(coefficients, 0.0)):
        raise ValueError("aberration scan requires at least three coefficients including zero")
    results: list[AberrationSensitivity] = []
    for term in terms:
        efficiencies = []
        for coefficient in coefficients:
            perturbed = apply_zernike_aberration(field, term, float(coefficient), pupil_radius_mm=pupil_radius_mm)
            efficiencies.append(decompose_scalar_overlap(perturbed, receiving_mode).complex_efficiency)
        eta = np.asarray(efficiencies, dtype=float)
        loss_db, local, zero_eta, maximum_coefficient, zero_is_maximum = _aberration_summary(coefficients, eta)
        results.append(
            AberrationSensitivity(
                term_index=term.index,
                term_name=term.name,
                coefficient_waves_rms=coefficients.copy(),
                efficiency=eta,
                loss_db=loss_db,
                local_loss_db_per_wave2=local,
                zero_coefficient_efficiency=zero_eta,
                maximum_efficiency=float(np.max(eta)),
                maximum_coefficient_waves_rms=maximum_coefficient,
                zero_is_local_maximum=zero_is_maximum,
            )
        )
    return tuple(sorted(results, key=lambda item: abs(item.local_loss_db_per_wave2), reverse=True))


def scan_pupil_zernike_coupling_sensitivity(
    problem,
    *,
    coefficients_waves_rms: np.ndarray,
    terms: Iterable[ZernikeTerm] = STANDARD_TERMS[3:],
    pupil_radius_mm: float | None = None,
) -> tuple[AberrationSensitivity, ...]:

    from dataclasses import replace
    import hashlib

    from optical_core.physics.hybrid.solvers.cartesian_pupil_propagation import (
        propagate_prepared_cartesian_pupil,
    )

    coefficients = np.asarray(coefficients_waves_rms, dtype=float).reshape(-1)
    if coefficients.size < 3 or not np.any(np.isclose(coefficients, 0.0)):
        raise ValueError("aberration scan requires at least three coefficients including zero")
    pupil = problem.prepared_pupil.field
    radius = (
        float(pupil_radius_mm)
        if pupil_radius_mm is not None
        else max(np.max(np.abs(pupil.grid.x_mm)), np.max(np.abs(pupil.grid.y_mm)))
    )
    results: list[AberrationSensitivity] = []
    for term in terms:
        efficiencies: list[float] = []
        for coefficient in coefficients:
            perturbed = apply_zernike_aberration(
                pupil, term, float(coefficient), pupil_radius_mm=radius
            )
            fingerprint = hashlib.sha256(
                f"{problem.prepared_pupil.fingerprint}:{term.index}:{float(coefficient):.16g}".encode("utf-8")
            ).hexdigest()
            prepared = replace(
                problem.prepared_pupil,
                field=perturbed,
                fingerprint=fingerprint,
                metadata={
                    **dict(problem.prepared_pupil.metadata),
                    "aberration_application_plane": "exit_pupil",
                    "zernike_term_index": int(term.index),
                    "zernike_coefficient_waves_rms": float(coefficient),
                },
            )
            propagated = propagate_prepared_cartesian_pupil(prepared, problem.options)
            mode = problem.receiving_mode(
                propagated.field,
                offset_x_mm=problem.options.offset_x_mm,
                offset_y_mm=problem.options.offset_y_mm,
                tilt_x_rad=problem.options.tilt_x_rad,
                tilt_y_rad=problem.options.tilt_y_rad,
            )
            efficiencies.append(
                decompose_scalar_overlap(propagated.field, mode).complex_efficiency
            )
        eta = np.asarray(efficiencies, dtype=float)
        loss_db, local, zero_eta, maximum_coefficient, zero_is_maximum = _aberration_summary(coefficients, eta)
        results.append(
            AberrationSensitivity(
                term_index=term.index,
                term_name=term.name,
                coefficient_waves_rms=coefficients.copy(),
                efficiency=eta,
                loss_db=loss_db,
                local_loss_db_per_wave2=local,
                zero_coefficient_efficiency=zero_eta,
                maximum_efficiency=float(np.max(eta)),
                maximum_coefficient_waves_rms=maximum_coefficient,
                zero_is_local_maximum=zero_is_maximum,
            )
        )
    return tuple(sorted(results, key=lambda item: abs(item.local_loss_db_per_wave2), reverse=True))


__all__ = ["AberrationSensitivity", "apply_zernike_aberration", "scan_zernike_coupling_sensitivity", "scan_pupil_zernike_coupling_sensitivity"]
