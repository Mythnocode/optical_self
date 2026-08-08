
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class AiryDiskResult:
    wavelength_nm: float
    numerical_aperture: float
    f_number: float
    airy_radius_um: float
    airy_diameter_um: float
    metrics: dict[str, Any] = field(default_factory=dict)


def numerical_aperture_from_f_number(f_number: float, *, refractive_index: float = 1.0) -> float:
    fno = max(float(f_number), 1.0e-15)
    return float(float(refractive_index) / (2.0 * fno))


def f_number_from_numerical_aperture(numerical_aperture: float, *, refractive_index: float = 1.0) -> float:
    na = max(float(numerical_aperture), 1.0e-15)
    return float(float(refractive_index) / (2.0 * na))


def airy_radius_um_from_na(wavelength_nm: float, numerical_aperture: float) -> float:
    wavelength_um = float(wavelength_nm) * 1.0e-3
    na = max(float(numerical_aperture), 1.0e-15)
    return float(0.61 * wavelength_um / na)


def airy_radius_um_from_f_number(
    wavelength_nm: float,
    f_number: float,
    *,
    refractive_index: float = 1.0,
) -> float:


    wavelength_um = float(wavelength_nm) * 1.0e-3
    n = float(refractive_index)
    if not np.isfinite(n) or n <= 0.0:
        raise ValueError("refractive_index must be finite and positive.")
    return float(1.22 * wavelength_um * float(f_number) / n)


def paraxial_airy_radius_um(
    wavelength_nm: float,
    effective_focal_length_mm: float,
    entrance_pupil_diameter_mm: float,
    *,
    refractive_index: float = 1.0,
) -> float:
    aperture = max(float(entrance_pupil_diameter_mm), 1.0e-15)
    f_number = abs(float(effective_focal_length_mm)) / aperture
    return airy_radius_um_from_f_number(
        wavelength_nm,
        f_number,
        refractive_index=refractive_index,
    )


def airy_radius_um_from_focal_aperture(
    wavelength_nm: float,
    focal_length_mm: float,
    aperture_diameter_mm: float,
    *,
    refractive_index: float = 1.0,
) -> float:
    return paraxial_airy_radius_um(
        wavelength_nm,
        focal_length_mm,
        aperture_diameter_mm,
        refractive_index=refractive_index,
    )


def real_ray_image_space_na(
    directions: np.ndarray,
    *,
    valid_mask: np.ndarray | None = None,
    pupil_coordinates_normalized: np.ndarray | None = None,
    refractive_index: float = 1.0,
) -> dict[str, float]:


    dirs = np.asarray(directions, dtype=float)
    if dirs.ndim != 2 or dirs.shape[1] != 3:
        raise ValueError("directions 必须是 (N,3)。")
    valid = np.all(np.isfinite(dirs), axis=1)
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool).reshape(-1)
        if mask.shape != valid.shape:
            raise ValueError("valid_mask 长度与 directions 不一致。")
        valid &= mask
    if not np.any(valid):
        return {
            "real_ray_image_space_na": float("nan"),
            "real_ray_marginal_angle_rad": float("nan"),
            "real_ray_chief_index": -1.0,
            "real_ray_marginal_index": -1.0,
        }

    indices = np.flatnonzero(valid)
    unit = dirs[valid] / np.linalg.norm(dirs[valid], axis=1)[:, None]
    if pupil_coordinates_normalized is not None:
        pupil = np.asarray(pupil_coordinates_normalized, dtype=float)
        if pupil.shape != (dirs.shape[0], 2):
            raise ValueError("pupil_coordinates_normalized 必须是 (N,2)。")
        rho = np.linalg.norm(pupil[valid], axis=1)
        chief_local = int(np.argmin(rho))
        marginal_local = int(np.argmax(rho))
    else:
        
        chief_local = int(np.argmax(unit[:, 2]))
        dots = unit @ unit[chief_local]
        marginal_local = int(np.argmin(dots))

    chief = unit[chief_local]
    marginal = unit[marginal_local]
    angle = float(np.arccos(np.clip(np.dot(chief, marginal), -1.0, 1.0)))
    na = float(refractive_index) * float(np.sin(angle))
    return {
        "real_ray_image_space_na": na,
        "real_ray_marginal_angle_rad": angle,
        "real_ray_chief_index": float(indices[chief_local]),
        "real_ray_marginal_index": float(indices[marginal_local]),
    }


def evaluate_airy_disk(
    *,
    wavelength_nm: float,
    numerical_aperture: float | None = None,
    f_number: float | None = None,
    focal_length_mm: float | None = None,
    aperture_diameter_mm: float | None = None,
    refractive_index: float = 1.0,
) -> AiryDiskResult:


    if numerical_aperture is not None:
        na = float(numerical_aperture)
        fno = f_number_from_numerical_aperture(na, refractive_index=refractive_index)
        radius = airy_radius_um_from_na(wavelength_nm, na)
        definition = "explicit_numerical_aperture"
    elif f_number is not None:
        fno = float(f_number)
        na = numerical_aperture_from_f_number(fno, refractive_index=refractive_index)
        radius = airy_radius_um_from_f_number(
            wavelength_nm,
            fno,
            refractive_index=refractive_index,
        )
        definition = "explicit_f_number"
    elif focal_length_mm is not None and aperture_diameter_mm is not None:
        fno = abs(float(focal_length_mm)) / max(float(aperture_diameter_mm), 1.0e-15)
        na = numerical_aperture_from_f_number(fno, refractive_index=refractive_index)
        radius = paraxial_airy_radius_um(
            wavelength_nm,
            focal_length_mm,
            aperture_diameter_mm,
            refractive_index=refractive_index,
        )
        definition = "paraxial_effl_over_epd"
    else:
        raise ValueError("Airy disk requires NA, F#, or focal_length_mm + aperture_diameter_mm.")

    metrics = {
        "airy_radius_um": float(radius),
        "airy_diameter_um": float(2.0 * radius),
        "paraxial_airy_radius_um": float(radius),
        "paraxial_airy_diameter_um": float(2.0 * radius),
        "paraxial_airy_numerical_aperture": float(na),
        "paraxial_airy_f_number": float(fno),
        "airy_wavelength_nm": float(wavelength_nm),
        "airy_definition": definition,
        
        "airy_numerical_aperture": float(na),
        "airy_f_number": float(fno),
        "airy_formula_model": "first_zero_scalar_airy_paraxial_vacuum_wavelength_with_image_index",
        "airy_image_space_refractive_index": float(refractive_index),
    }
    return AiryDiskResult(
        wavelength_nm=float(wavelength_nm),
        numerical_aperture=float(na),
        f_number=float(fno),
        airy_radius_um=float(radius),
        airy_diameter_um=float(2.0 * radius),
        metrics=metrics,
    )


__all__ = [
    "AiryDiskResult",
    "numerical_aperture_from_f_number",
    "f_number_from_numerical_aperture",
    "airy_radius_um_from_na",
    "airy_radius_um_from_f_number",
    "paraxial_airy_radius_um",
    "airy_radius_um_from_focal_aperture",
    "real_ray_image_space_na",
    "evaluate_airy_disk",
]
