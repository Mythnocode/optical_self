# 定义几何像差结果的数据结构。


from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import ClassVar

import numpy as np


@dataclass(frozen=True, slots=True)
class RayFanProfiles:
    rho: np.ndarray
    tangential_um: np.ndarray
    sagittal_um: np.ndarray


@dataclass(frozen=True, slots=True)
class FieldCurvatureProfiles:
    field_grid_deg: np.ndarray
    tangential_focus_um: np.ndarray
    sagittal_focus_um: np.ndarray
    image_height_um: np.ndarray
    distortion_percent: np.ndarray
    field_used_deg: float
    marginal_radius_mm: float
    paraxial_focus_mm: float
    field_note: str


@dataclass(frozen=True, slots=True)
class WavefrontTermFit:
    names: np.ndarray
    coefficient_um: np.ndarray
    rms_um: np.ndarray
    fraction_percent: np.ndarray
    fit_rms_um: float
    residual_rms_um: float
    dominant: str


@dataclass(frozen=True, slots=True)
class WavefrontOverview:
    pupil_y: np.ndarray
    pupil_z: np.ndarray
    opd_um: np.ndarray
    rms_um: float
    peak_to_valley_um: float
    strehl: float
    terms: WavefrontTermFit


@dataclass(frozen=True, slots=True)
class AberrationOverviewResult(Mapping[str, object]):
    """不可变像差概览结果，可按字段名读取。"""

    ray_fan: RayFanProfiles
    field_curvature: FieldCurvatureProfiles
    wavefront: WavefrontOverview

    _MAPPING_KEYS: ClassVar[tuple[str, ...]] = (
        "rho",
        "fan_tangential_um",
        "fan_sagittal_um",
        "field_grid_deg",
        "tangential_focus_um",
        "sagittal_focus_um",
        "image_height_um",
        "distortion_percent",
        "field_used_deg",
        "marginal_radius_mm",
        "paraxial_focus_mm",
        "field_note",
        "wavefront_y",
        "wavefront_z",
        "wavefront_opd_um",
        "wavefront_rms_um",
        "wavefront_pv_um",
        "wavefront_strehl",
        "wavefront_term_names",
        "wavefront_term_coeff_um",
        "wavefront_term_rms_um",
        "wavefront_term_fraction_percent",
        "wavefront_fit_rms_um",
        "wavefront_residual_rms_um",
        "dominant_wavefront_term",
    )

    def to_mapping(self) -> dict[str, object]:
        fan = self.ray_fan
        field = self.field_curvature
        wavefront = self.wavefront
        terms = wavefront.terms
        return {
            "rho": fan.rho,
            "fan_tangential_um": fan.tangential_um,
            "fan_sagittal_um": fan.sagittal_um,
            "field_grid_deg": field.field_grid_deg,
            "tangential_focus_um": field.tangential_focus_um,
            "sagittal_focus_um": field.sagittal_focus_um,
            "image_height_um": field.image_height_um,
            "distortion_percent": field.distortion_percent,
            "field_used_deg": field.field_used_deg,
            "marginal_radius_mm": field.marginal_radius_mm,
            "paraxial_focus_mm": field.paraxial_focus_mm,
            "field_note": field.field_note,
            "wavefront_y": wavefront.pupil_y,
            "wavefront_z": wavefront.pupil_z,
            "wavefront_opd_um": wavefront.opd_um,
            "wavefront_rms_um": wavefront.rms_um,
            "wavefront_pv_um": wavefront.peak_to_valley_um,
            "wavefront_strehl": wavefront.strehl,
            "wavefront_term_names": terms.names,
            "wavefront_term_coeff_um": terms.coefficient_um,
            "wavefront_term_rms_um": terms.rms_um,
            "wavefront_term_fraction_percent": terms.fraction_percent,
            "wavefront_fit_rms_um": terms.fit_rms_um,
            "wavefront_residual_rms_um": terms.residual_rms_um,
            "dominant_wavefront_term": terms.dominant,
        }

    def __getitem__(self, key: str) -> object:
        try:
            return self.to_mapping()[key]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._MAPPING_KEYS)

    def __len__(self) -> int:
        return len(self._MAPPING_KEYS)


__all__ = [
    "AberrationOverviewResult",
    "FieldCurvatureProfiles",
    "RayFanProfiles",
    "WavefrontOverview",
    "WavefrontTermFit",
]
