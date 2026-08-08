# 色散计算


from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class DispersionResult:


    wavelength_um: float
    n: float | None = None
    k: float | None = None

    @property
    def complex_index(self) -> complex:
        if self.n is None:
            raise ValueError("this material dataset does not provide n.")
        return complex(float(self.n), float(self.k or 0.0))


def wavelength_nm_to_um(wavelength_nm: float) -> float:
    value = float(wavelength_nm)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("wavelength_nm must be positive and finite.")
    return value / 1000.0


def validate_wavelength_um(
    wavelength_um: float,
    *,
    wl_min: float | None = None,
    wl_max: float | None = None,
) -> float:
    value = float(wavelength_um)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("wavelength_um must be positive and finite.")
    if wl_min is not None and value < float(wl_min) - 1.0e-15:
        raise ValueError(
            f"wavelength {value:g} um is below dataset range {float(wl_min):g} um."
        )
    if wl_max is not None and value > float(wl_max) + 1.0e-15:
        raise ValueError(
            f"wavelength {value:g} um is above dataset range {float(wl_max):g} um."
        )
    return value


def formula1_n(wavelength_um: float, coeffs: Sequence[float]) -> float:


    wavelength = validate_wavelength_um(wavelength_um)
    if len(coeffs) < 2 or len(coeffs) % 2 != 0:
        raise ValueError("formula1 requires coefficient pairs [B, C, ...].")

    lam2 = wavelength * wavelength
    n2 = 1.0
    for i in range(0, len(coeffs), 2):
        b = float(coeffs[i])
        c = float(coeffs[i + 1])
        denom = lam2 - c * c
        if abs(denom) <= 1.0e-15:
            raise ValueError("wavelength is too close to a formula1 pole.")
        n2 += b * lam2 / denom

    if not math.isfinite(n2) or n2 <= 0.0:
        raise ValueError("formula1 produced invalid n^2.")
    return float(math.sqrt(n2))


def formula2_n(wavelength_um: float, coeffs: Sequence[float]) -> float:


    wavelength = validate_wavelength_um(wavelength_um)
    if len(coeffs) < 3 or len(coeffs[1:]) % 2 != 0:
        raise ValueError("formula2 requires [A0, B1, C1, B2, C2, ...].")

    lam2 = wavelength * wavelength
    n2 = 1.0 + float(coeffs[0])
    for i in range(1, len(coeffs), 2):
        b = float(coeffs[i])
        c = float(coeffs[i + 1])
        denom = lam2 - c
        if abs(denom) <= 1.0e-15:
            raise ValueError("wavelength is too close to a formula2 pole.")
        n2 += b * lam2 / denom

    if not math.isfinite(n2) or n2 <= 0.0:
        raise ValueError("formula2 produced invalid n^2.")
    return float(math.sqrt(n2))


def interpolate_linear(
    wavelength_um: float,
    pts: Sequence[Sequence[float]],
    *,
    column: int,
) -> float:


    wavelength = validate_wavelength_um(wavelength_um)
    if len(pts) < 2:
        raise ValueError("tabulated interpolation requires at least two points.")

    arr = np.asarray(pts, dtype=float)
    if arr.ndim != 2 or arr.shape[1] <= column:
        raise ValueError(f"tabulated points do not contain column {column}.")
    if not np.isfinite(arr).all():
        raise ValueError("tabulated points must be finite.")

    x = arr[:, 0]
    y = arr[:, column]
    order = np.argsort(x)
    x = x[order]
    y = y[order]

    if np.any(np.diff(x) <= 0.0):
        raise ValueError("tabulated wavelengths must be strictly increasing.")
    validate_wavelength_um(wavelength, wl_min=float(x[0]), wl_max=float(x[-1]))
    return float(np.interp(wavelength, x, y))


def evaluate_dataset(entry: dict[str, object], wavelength_um: float) -> DispersionResult:


    typ = str(entry.get("type", "")).strip().lower()
    wl_min = entry.get("wl_min")
    wl_max = entry.get("wl_max")
    wavelength = validate_wavelength_um(
        wavelength_um,
        wl_min=float(wl_min) if wl_min is not None else None,
        wl_max=float(wl_max) if wl_max is not None else None,
    )

    if typ == "formula1":
        return DispersionResult(
            wavelength_um=wavelength,
            n=formula1_n(wavelength, entry.get("coeffs", ()) or ()),
            k=0.0,
        )
    if typ == "formula2":
        return DispersionResult(
            wavelength_um=wavelength,
            n=formula2_n(wavelength, entry.get("coeffs", ()) or ()),
            k=0.0,
        )
    if typ == "tabulated_n":
        return DispersionResult(
            wavelength_um=wavelength,
            n=interpolate_linear(wavelength, entry.get("pts", ()) or (), column=1),
            k=0.0,
        )
    if typ == "tabulated_k":
        return DispersionResult(
            wavelength_um=wavelength,
            n=None,
            k=interpolate_linear(wavelength, entry.get("pts", ()) or (), column=1),
        )
    if typ == "tabulated_nk":
        pts = entry.get("pts", ()) or ()
        return DispersionResult(
            wavelength_um=wavelength,
            n=interpolate_linear(wavelength, pts, column=1),
            k=interpolate_linear(wavelength, pts, column=2),
        )

    raise NotImplementedError(f"unsupported refractiveindex.info data type: {typ!r}")


def dataset_provides_n(entry: dict[str, object]) -> bool:
    return str(entry.get("type", "")).strip().lower() in {
        "formula1",
        "formula2",
        "tabulated_n",
        "tabulated_nk",
    }
