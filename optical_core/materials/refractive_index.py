# 简化调用接口,供光线追迹等其他模块直接调用
from __future__ import annotations

from .catalog import MaterialDatabase, default_material_database


def refractive_index(
    material: str,
    wavelength_nm: float,
    *,
    source: str | None = None,
    database: MaterialDatabase | None = None,
) -> float:


    db = database or default_material_database()
    return db.get_n(material, wavelength_nm=wavelength_nm, source=source)


def complex_refractive_index(
    material: str,
    wavelength_nm: float,
    *,
    source: str | None = None,
    database: MaterialDatabase | None = None,
) -> complex:
    db = database or default_material_database()
    return db.get_complex_index(material, wavelength_nm=wavelength_nm, source=source)
