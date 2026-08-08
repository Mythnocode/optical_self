from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from optical_core.physics.wave.formulas.polarization import (
    apply_jones_matrix,
    linear_retarder_jones,
)


CrystalType = Literal["positive", "negative"]
AxisComponent = Literal["ordinary", "extraordinary"]
WaveplateKind = Literal[
    "zero_order",
    "quarter_wave",
    "half_wave",
    "full_wave",
    "custom",
]


@dataclass(frozen=True)
class UniaxialCrystal:
    n_o: float
    n_e: float
    name: str = "uniaxial_crystal"

    def __post_init__(self) -> None:
        _validate_refractive_index(self.n_o, "n_o")
        _validate_refractive_index(self.n_e, "n_e")

        if self.n_o == self.n_e:
            raise ValueError("n_o and n_e must be different for a uniaxial crystal")

    @property
    def crystal_type(self) -> CrystalType:
        return classify_uniaxial_crystal(self.n_o, self.n_e)

    @property
    def n_fast(self) -> float:
        return min(self.n_o, self.n_e)

    @property
    def n_slow(self) -> float:
        return max(self.n_o, self.n_e)

    @property
    def fast_axis_component(self) -> AxisComponent:
        return fast_axis_component(self.n_o, self.n_e)

    @property
    def slow_axis_component(self) -> AxisComponent:
        return slow_axis_component(self.n_o, self.n_e)

    @property
    def birefringence_abs(self) -> float:
        return abs(self.n_e - self.n_o)

    @property
    def birefringence_signed(self) -> float:
        return self.n_e - self.n_o


def classify_uniaxial_crystal(n_o: float, n_e: float) -> CrystalType:
    _validate_refractive_index(n_o, "n_o")
    _validate_refractive_index(n_e, "n_e")

    if n_e > n_o:
        return "positive"

    if n_e < n_o:
        return "negative"

    raise ValueError("n_o and n_e must be different for a uniaxial crystal")


def is_positive_uniaxial(n_o: float, n_e: float) -> bool:
    return classify_uniaxial_crystal(n_o, n_e) == "positive"


def is_negative_uniaxial(n_o: float, n_e: float) -> bool:
    return classify_uniaxial_crystal(n_o, n_e) == "negative"


def fast_axis_component(n_o: float, n_e: float) -> AxisComponent:
    _validate_refractive_index(n_o, "n_o")
    _validate_refractive_index(n_e, "n_e")

    if n_o < n_e:
        return "ordinary"

    if n_e < n_o:
        return "extraordinary"

    raise ValueError("n_o and n_e must be different")


def slow_axis_component(n_o: float, n_e: float) -> AxisComponent:
    _validate_refractive_index(n_o, "n_o")
    _validate_refractive_index(n_e, "n_e")

    if n_o > n_e:
        return "ordinary"

    if n_e > n_o:
        return "extraordinary"

    raise ValueError("n_o and n_e must be different")


def fast_slow_indices(n_o: float, n_e: float) -> tuple[float, float]:
    _validate_refractive_index(n_o, "n_o")
    _validate_refractive_index(n_e, "n_e")

    if n_o == n_e:
        raise ValueError("n_o and n_e must be different")

    return min(n_o, n_e), max(n_o, n_e)


def ordinary_extraordinary_intensity_split(
    input_intensity: float,
    angle_to_principal_section_rad: float,
) -> tuple[float, float]:

    if input_intensity < 0:
        raise ValueError("input_intensity must be non-negative")

    ordinary = input_intensity * np.sin(angle_to_principal_section_rad) ** 2
    extraordinary = input_intensity * np.cos(angle_to_principal_section_rad) ** 2

    return float(ordinary), float(extraordinary)


def effective_extraordinary_index(
    n_o: float,
    n_e: float,
    angle_to_optic_axis_rad: float,
) -> float:

    _validate_refractive_index(n_o, "n_o")
    _validate_refractive_index(n_e, "n_e")

    c = np.cos(angle_to_optic_axis_rad)
    s = np.sin(angle_to_optic_axis_rad)

    inverse_square = (c * c) / (n_o * n_o) + (s * s) / (n_e * n_e)

    return float(1.0 / np.sqrt(inverse_square))


def birefringence_delta_n(
    n_o: float,
    n_e: float,
    signed: bool = False,
) -> float:
    _validate_refractive_index(n_o, "n_o")
    _validate_refractive_index(n_e, "n_e")

    delta = n_e - n_o

    if signed:
        return float(delta)

    return float(abs(delta))


def retardance_from_indices(
    n_slow: float,
    n_fast: float,
    thickness_m: float,
    wavelength_m: float,
) -> float:
    _validate_refractive_index(n_slow, "n_slow")
    _validate_refractive_index(n_fast, "n_fast")
    _validate_positive_length(wavelength_m, "wavelength_m")

    if n_slow <= n_fast:
        raise ValueError("n_slow must be greater than n_fast")
    if thickness_m < 0:
        raise ValueError("thickness_m must be non-negative")

    return float(2.0 * np.pi * (n_slow - n_fast) * thickness_m / wavelength_m)


def retardance_from_uniaxial_crystal(
    n_o: float,
    n_e: float,
    thickness_m: float,
    wavelength_m: float,
) -> float:
    n_fast, n_slow = fast_slow_indices(n_o, n_e)

    return retardance_from_indices(
        n_slow=n_slow,
        n_fast=n_fast,
        thickness_m=thickness_m,
        wavelength_m=wavelength_m,
    )


def required_thickness_for_retardance(
    n_o: float,
    n_e: float,
    wavelength_m: float,
    target_retardance_rad: float,
) -> float:
    _validate_positive_length(wavelength_m, "wavelength_m")

    if target_retardance_rad < 0:
        raise ValueError("target_retardance_rad must be non-negative")

    delta_n = birefringence_delta_n(n_o, n_e, signed=False)

    if delta_n <= 0:
        raise ValueError("birefringence must be non-zero")

    return float(target_retardance_rad * wavelength_m / (2.0 * np.pi * delta_n))


def quarter_wave_thickness(
    n_o: float,
    n_e: float,
    wavelength_m: float,
) -> float:
    return required_thickness_for_retardance(
        n_o=n_o,
        n_e=n_e,
        wavelength_m=wavelength_m,
        target_retardance_rad=np.pi / 2.0,
    )


def half_wave_thickness(
    n_o: float,
    n_e: float,
    wavelength_m: float,
) -> float:
    return required_thickness_for_retardance(
        n_o=n_o,
        n_e=n_e,
        wavelength_m=wavelength_m,
        target_retardance_rad=np.pi,
    )


def full_wave_thickness(
    n_o: float,
    n_e: float,
    wavelength_m: float,
) -> float:
    return required_thickness_for_retardance(
        n_o=n_o,
        n_e=n_e,
        wavelength_m=wavelength_m,
        target_retardance_rad=2.0 * np.pi,
    )


def waveplate_kind(
    retardance_rad: float,
    tolerance_rad: float = 1.0e-6,
) -> WaveplateKind:
    if retardance_rad < 0:
        raise ValueError("retardance_rad must be non-negative")
    if tolerance_rad <= 0:
        raise ValueError("tolerance_rad must be positive")

    reduced = float(np.mod(retardance_rad, 2.0 * np.pi))

    if _angle_close(reduced, 0.0, tolerance_rad) or _angle_close(
        reduced,
        2.0 * np.pi,
        tolerance_rad,
    ):
        if retardance_rad <= tolerance_rad:
            return "zero_order"
        return "full_wave"

    if _angle_close(reduced, np.pi / 2.0, tolerance_rad):
        return "quarter_wave"

    if _angle_close(reduced, np.pi, tolerance_rad):
        return "half_wave"

    if _angle_close(reduced, 3.0 * np.pi / 2.0, tolerance_rad):
        return "quarter_wave"

    return "custom"


def waveplate_kind_from_crystal(
    n_o: float,
    n_e: float,
    thickness_m: float,
    wavelength_m: float,
    tolerance_rad: float = 1.0e-6,
) -> WaveplateKind:
    retardance = retardance_from_uniaxial_crystal(
        n_o=n_o,
        n_e=n_e,
        thickness_m=thickness_m,
        wavelength_m=wavelength_m,
    )

    return waveplate_kind(retardance, tolerance_rad=tolerance_rad)


def waveplate_jones_from_crystal(
    n_o: float,
    n_e: float,
    thickness_m: float,
    wavelength_m: float,
    fast_axis_angle_rad: float = 0.0,
) -> np.ndarray:
    retardance = retardance_from_uniaxial_crystal(
        n_o=n_o,
        n_e=n_e,
        thickness_m=thickness_m,
        wavelength_m=wavelength_m,
    )

    return linear_retarder_jones(
        retardance_rad=retardance,
        fast_axis_angle_rad=fast_axis_angle_rad,
    )


def apply_waveplate_from_crystal(
    jones: np.ndarray,
    n_o: float,
    n_e: float,
    thickness_m: float,
    wavelength_m: float,
    fast_axis_angle_rad: float = 0.0,
) -> np.ndarray:
    matrix = waveplate_jones_from_crystal(
        n_o=n_o,
        n_e=n_e,
        thickness_m=thickness_m,
        wavelength_m=wavelength_m,
        fast_axis_angle_rad=fast_axis_angle_rad,
    )

    return apply_jones_matrix(matrix, jones)


def crystal_summary(
    n_o: float,
    n_e: float,
    thickness_m: float,
    wavelength_m: float,
) -> dict[str, float | str]:
    crystal = UniaxialCrystal(n_o=n_o, n_e=n_e)

    retardance = retardance_from_uniaxial_crystal(
        n_o=n_o,
        n_e=n_e,
        thickness_m=thickness_m,
        wavelength_m=wavelength_m,
    )

    return {
        "crystal_type": crystal.crystal_type,
        "n_o": float(crystal.n_o),
        "n_e": float(crystal.n_e),
        "n_fast": float(crystal.n_fast),
        "n_slow": float(crystal.n_slow),
        "fast_axis_component": crystal.fast_axis_component,
        "slow_axis_component": crystal.slow_axis_component,
        "birefringence_signed": float(crystal.birefringence_signed),
        "birefringence_abs": float(crystal.birefringence_abs),
        "retardance_rad": float(retardance),
        "retardance_waves": float(retardance / (2.0 * np.pi)),
        "waveplate_kind": waveplate_kind(retardance),
    }


def _validate_refractive_index(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_positive_length(value: float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _angle_close(left: float, right: float, tolerance: float) -> bool:
    return abs(left - right) <= tolerance