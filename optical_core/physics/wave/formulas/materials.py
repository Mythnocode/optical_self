from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class OpticalMaterial(Protocol):
    name: str

    def n(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        ...

    def n_complex(self, wavelength_nm: float | np.ndarray) -> complex | np.ndarray:
        ...


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be positive and finite.")
    return value


def _validate_non_negative(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be non-negative and finite.")
    return value


def _as_wavelength_nm(value: float | np.ndarray) -> np.ndarray:
    wavelength = np.asarray(value, dtype=float)
    if not np.isfinite(wavelength).all():
        raise ValueError("wavelength_nm must contain only finite values.")
    if np.any(wavelength <= 0.0):
        raise ValueError("wavelength_nm must be positive.")
    return wavelength


def _maybe_scalar(original: float | np.ndarray, value: np.ndarray) -> float | np.ndarray:
    if np.asarray(original).ndim == 0:
        return float(value)
    return value


def _maybe_scalar_complex(
    original: float | np.ndarray,
    value: np.ndarray,
) -> complex | np.ndarray:
    if np.asarray(original).ndim == 0:
        return complex(value)
    return value


@dataclass(frozen=True)
class ConstantIndexMaterial:


    name: str
    refractive_index: float
    extinction_coefficient: float = 0.0

    def __post_init__(self) -> None:
        _validate_positive("refractive_index", self.refractive_index)
        _validate_non_negative("extinction_coefficient", self.extinction_coefficient)

    def n(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        result = np.full_like(wavelength, float(self.refractive_index), dtype=float)
        return _maybe_scalar(wavelength_nm, result)

    def kappa(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        result = np.full_like(
            wavelength,
            float(self.extinction_coefficient),
            dtype=float,
        )
        return _maybe_scalar(wavelength_nm, result)

    def n_complex(self, wavelength_nm: float | np.ndarray) -> complex | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        result = np.full_like(
            wavelength,
            complex(self.refractive_index, self.extinction_coefficient),
            dtype=np.complex128,
        )
        return _maybe_scalar_complex(wavelength_nm, result)


@dataclass(frozen=True)
class CauchyMaterial:


    name: str
    a: float
    b_um2: float = 0.0
    c_um4: float = 0.0
    extinction_coefficient: float = 0.0

    def __post_init__(self) -> None:
        _validate_positive("a", self.a)
        _validate_non_negative("extinction_coefficient", self.extinction_coefficient)

        for name, value in {
            "b_um2": self.b_um2,
            "c_um4": self.c_um4,
        }.items():
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite.")

    def n(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        wavelength_um = wavelength / 1000.0

        result = (
            self.a
            + self.b_um2 / (wavelength_um**2)
            + self.c_um4 / (wavelength_um**4)
        )

        return _maybe_scalar(wavelength_nm, result)

    def kappa(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        result = np.full_like(
            wavelength,
            float(self.extinction_coefficient),
            dtype=float,
        )
        return _maybe_scalar(wavelength_nm, result)

    def n_complex(self, wavelength_nm: float | np.ndarray) -> complex | np.ndarray:
        n_value = np.asarray(self.n(wavelength_nm), dtype=float)
        k_value = np.asarray(self.kappa(wavelength_nm), dtype=float)
        result = n_value + 1j * k_value
        return _maybe_scalar_complex(wavelength_nm, result)


@dataclass(frozen=True)
class SellmeierMaterial:


    name: str
    b_coefficients: tuple[float, ...]
    c_um2_coefficients: tuple[float, ...]
    extinction_coefficient: float = 0.0

    def __post_init__(self) -> None:
        if len(self.b_coefficients) == 0:
            raise ValueError("b_coefficients must not be empty.")
        if len(self.b_coefficients) != len(self.c_um2_coefficients):
            raise ValueError(
                "b_coefficients and c_um2_coefficients must have the same length."
            )

        for coefficient in self.b_coefficients:
            if not isinstance(coefficient, (int, float)) or not math.isfinite(float(coefficient)):
                raise ValueError("all b_coefficients must be finite.")

        for coefficient in self.c_um2_coefficients:
            if not isinstance(coefficient, (int, float)) or not math.isfinite(float(coefficient)):
                raise ValueError("all c_um2_coefficients must be finite.")

        _validate_non_negative("extinction_coefficient", self.extinction_coefficient)

    def n(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        wavelength_um = wavelength / 1000.0
        wavelength_um2 = wavelength_um**2

        n2 = np.ones_like(wavelength_um2, dtype=float)

        for b, c_um2 in zip(self.b_coefficients, self.c_um2_coefficients):
            denominator = wavelength_um2 - c_um2
            if np.any(np.abs(denominator) <= 1.0e-15):
                raise ValueError("wavelength is too close to a Sellmeier pole.")
            n2 = n2 + b * wavelength_um2 / denominator

        if np.any(n2 <= 0.0) or not np.isfinite(n2).all():
            raise ValueError("Sellmeier model produced invalid refractive index.")

        result = np.sqrt(n2)

        return _maybe_scalar(wavelength_nm, result)

    def kappa(self, wavelength_nm: float | np.ndarray) -> float | np.ndarray:
        wavelength = _as_wavelength_nm(wavelength_nm)
        result = np.full_like(
            wavelength,
            float(self.extinction_coefficient),
            dtype=float,
        )
        return _maybe_scalar(wavelength_nm, result)

    def n_complex(self, wavelength_nm: float | np.ndarray) -> complex | np.ndarray:
        n_value = np.asarray(self.n(wavelength_nm), dtype=float)
        k_value = np.asarray(self.kappa(wavelength_nm), dtype=float)
        result = n_value + 1j * k_value
        return _maybe_scalar_complex(wavelength_nm, result)


def fused_silica_sellmeier() -> SellmeierMaterial:


    return SellmeierMaterial(
        name="fused_silica",
        b_coefficients=(0.6961663, 0.4079426, 0.8974794),
        c_um2_coefficients=(
            0.0684043**2,
            0.1162414**2,
            9.896161**2,
        ),
    )


def air_material() -> ConstantIndexMaterial:
    """返回空气近似模型。"""

    return ConstantIndexMaterial(
        name="air",
        refractive_index=1.0,
    )


def absorption_coefficient_per_mm(
    material: OpticalMaterial,
    *,
    wavelength_nm: float | np.ndarray,
) -> float | np.ndarray:


    wavelength = _as_wavelength_nm(wavelength_nm)
    wavelength_mm = wavelength * 1.0e-6

    n_complex = np.asarray(material.n_complex(wavelength_nm), dtype=np.complex128)
    kappa = np.imag(n_complex)

    if np.any(kappa < 0.0):
        raise ValueError("extinction coefficient must not be negative.")

    alpha = 4.0 * math.pi * kappa / wavelength_mm

    return _maybe_scalar(wavelength_nm, alpha)


def intensity_transmission_through_material(
    material: OpticalMaterial,
    *,
    wavelength_nm: float | np.ndarray,
    thickness_mm: float,
) -> float | np.ndarray:


    thickness_mm = _validate_non_negative("thickness_mm", thickness_mm)

    alpha = np.asarray(
        absorption_coefficient_per_mm(
            material,
            wavelength_nm=wavelength_nm,
        ),
        dtype=float,
    )

    result = np.exp(-alpha * thickness_mm)

    return _maybe_scalar(wavelength_nm, result)


def estimate_group_index(
    material: OpticalMaterial,
    *,
    wavelength_nm: float,
    step_nm: float = 1.0e-3,
) -> float:


    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    step_nm = _validate_positive("step_nm", step_nm)

    if wavelength_nm - step_nm <= 0.0:
        raise ValueError("step_nm is too large for the given wavelength.")

    n_plus = float(material.n(wavelength_nm + step_nm))
    n_minus = float(material.n(wavelength_nm - step_nm))

    dn_dlambda = (n_plus - n_minus) / (2.0 * step_nm)

    return float(float(material.n(wavelength_nm)) - wavelength_nm * dn_dlambda)