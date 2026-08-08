from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from frontend_pyside.presets.demo_780nm_four_lens import (
    DEFAULT_RECEIVER_MFD_UM,
    DEFAULT_WAVELENGTH_NM,
    PROJECT_NAME,
)


def _stable_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass
class LensSurface:


    name: str
    radius_mm: float
    thickness_mm: float
    material: str
    semi_aperture_mm: float
    surface_type: str = "球面"
    conic: float = 0.0
    group_id: str = ""
    enabled: bool = True
    type_parameters: dict[str, Any] = field(default_factory=dict)
    coating: str = "无"
    roughness_nm: float = 0.0
    mechanical_diameter_mm: float = 0.0
    note: str = ""
    element_id: str = ""
    surface_id: str = ""

    def __post_init__(self) -> None:
        legacy_group = str(self.group_id or "").strip()
        self.element_id = str(self.element_id or _stable_id("element"))
        self.group_id = legacy_group or self.element_id
        self.surface_id = str(self.surface_id or _stable_id("surface"))


@dataclass
class ProjectSnapshot:
    name: str = PROJECT_NAME
    version: str = "v1"
    wavelength_nm: float = DEFAULT_WAVELENGTH_NM
    surfaces: list[LensSurface] = field(default_factory=list)
    receiver_mfd_um: float = DEFAULT_RECEIVER_MFD_UM
    metrics: dict[str, Any] = field(default_factory=dict)
    project_id: str = field(default_factory=lambda: _stable_id("project"))

    def ensure_stable_ids(self) -> None:
        for surface in self.surfaces:
            surface.__post_init__()


__all__ = ["LensSurface", "ProjectSnapshot"]
