from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Any

import numpy as np


@dataclass(frozen=True, slots=True)
class SellmeierCoefficients:
    b1: float
    b2: float
    b3: float
    c1_um2: float
    c2_um2: float
    c3_um2: float


@dataclass(frozen=True, slots=True)
class CauchyCoefficients:
    a: float
    b_um2: float = 0.0
    c_um4: float = 0.0


@dataclass(frozen=True, slots=True)
class CoatingLayer:
    refractive_index: float
    thickness_nm: float
    name: str = "layer"


@dataclass(frozen=True, slots=True)
class EngineeringGlass:
    name: str
    nd: float
    vd: float | None = None
    sellmeier: SellmeierCoefficients | None = None
    cauchy: CauchyCoefficients | None = None
    transmission_per_25mm: float = 1.0
    aliases: tuple[str, ...] = ()

    def n(self, wavelength_nm: float) -> float:
        if self.sellmeier is not None:
            return sellmeier_index(wavelength_nm, self.sellmeier)
        if self.cauchy is not None:
            return cauchy_index(wavelength_nm, self.cauchy)
        return float(self.nd)

    def bulk_transmission(self, thickness_mm: float) -> float:
        base = float(np.clip(self.transmission_per_25mm, 0.0, 1.0))
        if base <= 0.0:
            return 0.0
        return float(base ** (float(thickness_mm) / 25.0))


class MaterialCatalog:
    def __init__(self, materials: Sequence[EngineeringGlass] | None = None):
        self._items: dict[str, EngineeringGlass] = {}
        for material in materials or default_glasses():
            self.add(material)

    def add(self, material: EngineeringGlass) -> None:
        keys = (material.name, *material.aliases)
        for key in keys:
            self._items[str(key).strip().lower()] = material

    def get(self, name: str) -> EngineeringGlass:
        key = str(name).strip().lower()
        if key not in self._items:
            raise KeyError(f"unknown engineering glass: {name!r}")
        return self._items[key]

    def refractive_index(self, name: str, wavelength_nm: float) -> float:
        return self.get(name).n(wavelength_nm)

    def bulk_transmission(self, name: str, thickness_mm: float) -> float:
        return self.get(name).bulk_transmission(thickness_mm)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted({item.name for item in self._items.values()}))


def sellmeier_index(wavelength_nm: float, coeffs: SellmeierCoefficients) -> float:
    lam2 = (float(wavelength_nm) / 1000.0) ** 2
    n2 = 1.0
    for b, c in ((coeffs.b1, coeffs.c1_um2), (coeffs.b2, coeffs.c2_um2), (coeffs.b3, coeffs.c3_um2)):
        n2 += float(b) * lam2 / (lam2 - float(c))
    return float(np.sqrt(max(n2, 0.0)))


def cauchy_index(wavelength_nm: float, coeffs: CauchyCoefficients) -> float:
    lam = float(wavelength_nm) / 1000.0
    return float(coeffs.a + coeffs.b_um2 / (lam * lam) + coeffs.c_um4 / (lam ** 4))


def normal_interface_transmission(n1: float, n2: float) -> float:
    r = ((float(n1) - float(n2)) / (float(n1) + float(n2))) ** 2
    return float(1.0 - r)


def quarter_wave_thickness_nm(wavelength_nm: float, layer_index: float) -> float:
    return float(wavelength_nm / (4.0 * layer_index))


def quarter_wave_ar_layer(wavelength_nm: float, n_substrate: float, n_incident: float = 1.0, name: str = "QW_AR") -> CoatingLayer:
    n_layer = float(np.sqrt(float(n_incident) * float(n_substrate)))
    return CoatingLayer(refractive_index=n_layer, thickness_nm=quarter_wave_thickness_nm(wavelength_nm, n_layer), name=name)


def coating_stack_reflectance(
    wavelength_nm: float,
    layers: Sequence[CoatingLayer],
    *,
    n_incident: float = 1.0,
    n_substrate: float = 1.5,
) -> float:

    m = np.eye(2, dtype=complex)
    for layer in layers:
        n = complex(layer.refractive_index)
        delta = 2.0 * np.pi * n * float(layer.thickness_nm) / float(wavelength_nm)
        c = np.cos(delta)
        s = 1j * np.sin(delta)
        mat = np.array([[c, s / n], [s * n, c]], dtype=complex)
        m = m @ mat
    y = (m[0, 0] * n_substrate + m[0, 1]) / (m[1, 0] * n_substrate + m[1, 1])
    r = (n_incident - y) / (n_incident + y)
    return float(np.clip(abs(r) ** 2, 0.0, 1.0))


def coating_stack_transmission(
    wavelength_nm: float,
    layers: Sequence[CoatingLayer],
    *,
    n_incident: float = 1.0,
    n_substrate: float = 1.5,
) -> float:
    return float(1.0 - coating_stack_reflectance(wavelength_nm, layers, n_incident=n_incident, n_substrate=n_substrate))


def default_glasses() -> tuple[EngineeringGlass, ...]:
    return (
        EngineeringGlass(
            name="N-BK7",
            nd=1.5168,
            vd=64.17,
            sellmeier=SellmeierCoefficients(
                b1=1.03961212,
                b2=0.231792344,
                b3=1.01046945,
                c1_um2=0.00600069867,
                c2_um2=0.0200179144,
                c3_um2=103.560653,
            ),
            transmission_per_25mm=0.992,
            aliases=("BK7", "SCHOTT N-BK7"),
        ),
        EngineeringGlass(
            name="Fused Silica",
            nd=1.4585,
            vd=67.8,
            sellmeier=SellmeierCoefficients(
                b1=0.6961663,
                b2=0.4079426,
                b3=0.8974794,
                c1_um2=0.00467914826,
                c2_um2=0.0135120631,
                c3_um2=97.9340025,
            ),
            transmission_per_25mm=0.995,
            aliases=("SiO2", "silica"),
        ),
        EngineeringGlass(
            name="N-SF11",
            nd=1.7847,
            vd=25.68,
            cauchy=CauchyCoefficients(a=1.73759695, b_um2=0.013188707, c_um4=0.000326485),
            transmission_per_25mm=0.985,
            aliases=("SF11",),
        ),
    )


def default_material_catalog() -> MaterialCatalog:
    return MaterialCatalog(default_glasses())


__all__ = [
    "SellmeierCoefficients",
    "CauchyCoefficients",
    "CoatingLayer",
    "EngineeringGlass",
    "MaterialCatalog",
    "sellmeier_index",
    "cauchy_index",
    "normal_interface_transmission",
    "quarter_wave_thickness_nm",
    "quarter_wave_ar_layer",
    "coating_stack_reflectance",
    "coating_stack_transmission",
    "default_glasses",
    "default_material_catalog",
]
