from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from optical_core.models.representations.scalar_field import ScalarField2D


PropagationMethod = Literal[
    "angular_spectrum",
    "band_limited_angular_spectrum",
    "scaled_angular_spectrum",
    "scaled_fresnel",
    "issc",
    "fresnel",
    "fraunhofer",
    "matrix_fresnel",
]

SUPPORTED_PROPAGATION_METHODS = (
    "angular_spectrum",
    "band_limited_angular_spectrum",
    "scaled_angular_spectrum",
    "scaled_fresnel",
    "issc",
    "fresnel",
    "fraunhofer",
    "matrix_fresnel",
)

ApertureType = Literal[
    "circular",
    "rectangular",
    "single_slit",
    "gaussian",
    "uniform",
]


class PropagationPort(Protocol):
    def propagate(
        self,
        field: ScalarField2D,
        distance_mm: float,
    ) -> ScalarField2D:
        ...


@dataclass(frozen=True, slots=True)
class PropagationOptions:


    wavelength_nm: float = 550.0
    refractive_index: float = 1.0
    grid_size: int = 129
    extent_mm: float = 1.0
    propagation_distance_mm: float = 100.0

    method: PropagationMethod = "angular_spectrum"
    aperture_type: ApertureType = "circular"

    aperture_diameter_mm: float = 1.0
    aperture_width_mm: float = 1.0
    aperture_height_mm: float = 1.0
    slit_width_mm: float = 0.2
    gaussian_waist_mm: float = 0.35

    normalize: bool = True

    zero_padding_factor: float = 2.0
    edge_power_threshold: float = 1.0e-4
    energy_closure_threshold: float = 5.0e-3
    nyquist_margin_min: float = 1.0

    def validate(self) -> "PropagationOptions":
        if self.wavelength_nm <= 0:
            raise ValueError("wavelength_nm ??????")

        if self.refractive_index <= 0:
            raise ValueError("refractive_index ??????")

        if self.grid_size < 5:
            raise ValueError("grid_size ??? 5?")

        if self.extent_mm <= 0:
            raise ValueError("extent_mm ??????")

        if self.propagation_distance_mm < 0:
            raise ValueError("propagation_distance_mm ??????")

        if self.method not in SUPPORTED_PROPAGATION_METHODS:
            raise ValueError(f"unsupported propagation method: {self.method!r}")

        if self.aperture_type not in {
            "circular",
            "rectangular",
            "single_slit",
            "gaussian",
            "uniform",
        }:
            raise ValueError(f"??????: {self.aperture_type!r}")

        if self.zero_padding_factor < 1.0:
            raise ValueError("zero_padding_factor ???? 1?")

        if not 0.0 <= self.edge_power_threshold < 1.0:
            raise ValueError(
                "edge_power_threshold ??? [0, 1) ??"
            )

        if not 0.0 <= self.energy_closure_threshold < 1.0:
            raise ValueError(
                "energy_closure_threshold ??? [0, 1) ??"
            )

        if self.nyquist_margin_min <= 0.0:
            raise ValueError("nyquist_margin_min ??????")

        return self
