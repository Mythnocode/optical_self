from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EngineeringMaterial:
    name: str
    refractive_index_d: float
    abbe_number: float | None = None
    transmission_per_25mm: float = 1.0
    aliases: tuple[str, ...] = ()

    def refractive_index(self, wavelength_nm: float | None = None) -> float:
        
        if wavelength_nm is None or self.abbe_number in (None, 0):
            return float(self.refractive_index_d)
        delta = (587.6 - float(wavelength_nm)) / 1000.0
        return float(self.refractive_index_d + delta / float(self.abbe_number))

    def bulk_transmission(self, thickness_mm: float) -> float:
        t25 = min(max(float(self.transmission_per_25mm), 0.0), 1.0)
        return float(t25 ** (max(0.0, float(thickness_mm)) / 25.0))


@dataclass(slots=True)
class EngineeringMaterialLibrary:
    materials: dict[str, EngineeringMaterial] = field(default_factory=dict)

    def add(self, material: EngineeringMaterial) -> None:
        self.materials[_key(material.name)] = material
        for alias in material.aliases:
            self.materials[_key(alias)] = material

    def get(self, name: str | None, default: str = "AIR") -> EngineeringMaterial:
        key = _key(name or default)
        if key in self.materials:
            return self.materials[key]
        numeric = _try_float(name)
        if numeric is not None:
            return EngineeringMaterial(name=str(name), refractive_index_d=numeric)
        raise KeyError(f"unknown engineering material: {name!r}")

    def refractive_index(self, name: str | None, wavelength_nm: float | None = None) -> float:
        return self.get(name).refractive_index(wavelength_nm)

    def bulk_transmission(self, name: str | None, thickness_mm: float) -> float:
        return self.get(name).bulk_transmission(thickness_mm)


def default_engineering_material_library() -> EngineeringMaterialLibrary:
    lib = EngineeringMaterialLibrary()
    for material in (
        EngineeringMaterial("AIR", 1.0, aliases=("air", "vacuum", "none", "")),
        EngineeringMaterial("BK7", 1.5168, abbe_number=64.17, transmission_per_25mm=0.992, aliases=("N-BK7", "n-bk7")),
        EngineeringMaterial("FUSED_SILICA", 1.4585, abbe_number=67.82, transmission_per_25mm=0.995, aliases=("SILICA", "FS", "UVFS")),
        EngineeringMaterial("SF11", 1.7847, abbe_number=25.76, transmission_per_25mm=0.970, aliases=("N-SF11", "n-sf11")),
        EngineeringMaterial("SAPPHIRE", 1.768, abbe_number=72.0, transmission_per_25mm=0.985),
    ):
        lib.add(material)
    return lib


def fresnel_normal_incidence_transmission(n1: float, n2: float) -> float:
    n1 = float(n1)
    n2 = float(n2)
    if abs(n1 + n2) < 1e-15:
        return 0.0
    r = ((n1 - n2) / (n1 + n2)) ** 2
    return float(max(0.0, min(1.0, 1.0 - r)))


def material_sequence_transmission(
    material_names: list[str],
    thickness_mm: list[float] | None = None,
    *,
    wavelength_nm: float = 550.0,
    library: EngineeringMaterialLibrary | None = None,
) -> dict[str, object]:
    lib = library or default_engineering_material_library()
    if len(material_names) < 2:
        material_names = ["AIR"] + list(material_names or ["AIR"])
    thickness_mm = list(thickness_mm or [0.0] * max(0, len(material_names) - 1))

    interface_values: list[float] = []
    bulk_values: list[float] = []
    cumulative: list[float] = []
    total = 1.0

    for i in range(len(material_names) - 1):
        n1 = lib.refractive_index(material_names[i], wavelength_nm)
        n2 = lib.refractive_index(material_names[i + 1], wavelength_nm)
        t_interface = fresnel_normal_incidence_transmission(n1, n2)
        t_bulk = lib.bulk_transmission(material_names[i + 1], thickness_mm[i] if i < len(thickness_mm) else 0.0)
        total *= t_interface * t_bulk
        interface_values.append(t_interface)
        bulk_values.append(t_bulk)
        cumulative.append(total)

    return {
        "interface_transmission": float(math.prod(interface_values)) if interface_values else 1.0,
        "bulk_transmission": float(math.prod(bulk_values)) if bulk_values else 1.0,
        "total_transmission": float(total),
        "interface_transmission_by_surface": interface_values,
        "bulk_transmission_by_surface": bulk_values,
        "cumulative_transmission_by_surface": cumulative,
    }


def _key(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _try_float(value: object) -> float | None:
    try:
        return float(value)  
    except Exception:
        return None
