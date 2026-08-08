from __future__ import annotations

from .catalog import MaterialDatabase, MaterialDescriptor, MaterialEntry, default_material_database
from .refractive_index import complex_refractive_index, refractive_index

__all__ = [
    "MaterialDatabase",
    "MaterialDescriptor",
    "MaterialEntry",
    "default_material_database",
    "refractive_index",
    "complex_refractive_index",
]

from .thermal import ThermalOpticModel, refractive_index_at_temperature, linear_thermal_scale
