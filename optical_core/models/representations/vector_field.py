


from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optical_core.models.representations.grid import SamplingGrid2D
from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class VectorField2D:
    ex: np.ndarray
    ey: np.ndarray
    ez: np.ndarray
    grid: SamplingGrid2D
    wavelength_nm: float
    refractive_index: float = 1.0
    z_mm: float = 0.0

    def __post_init__(self) -> None:
        ex = np.asarray(self.ex, dtype=np.complex128)
        ey = np.asarray(self.ey, dtype=np.complex128)
        ez = np.asarray(self.ez, dtype=np.complex128)
        expected = (self.grid.y_mm.size, self.grid.x_mm.size)
        if ex.shape != expected or ey.shape != expected or ez.shape != expected:
            raise ValueError("vector field components must match the Cartesian grid")
        if float(self.wavelength_nm) <= 0.0 or float(self.refractive_index) <= 0.0:
            raise ValueError("wavelength and refractive index must be positive")
        object.__setattr__(self, "ex", ex)
        object.__setattr__(self, "ey", ey)
        object.__setattr__(self, "ez", ez)

    @property
    def intensity(self) -> np.ndarray:
        return np.abs(self.ex) ** 2 + np.abs(self.ey) ** 2 + np.abs(self.ez) ** 2

    @property
    def integrated_power(self) -> float:
        area = abs(float(self.grid.dx_mm) * float(self.grid.dy_mm))
        return float(np.sum(self.intensity) * area)

    def normalized(self) -> "VectorField2D":
        power = self.integrated_power
        if power <= 0.0:
            return self
        factor = np.sqrt(power)
        return VectorField2D(
            ex=self.ex / factor,
            ey=self.ey / factor,
            ez=self.ez / factor,
            grid=self.grid,
            wavelength_nm=self.wavelength_nm,
            refractive_index=self.refractive_index,
            z_mm=self.z_mm,
        )


def lift_scalar_field_to_jones(
    field: ScalarField2D,
    jones_vector: tuple[complex, complex] = (1.0 + 0.0j, 0.0 + 0.0j),
) -> VectorField2D:
    vector = np.asarray(jones_vector, dtype=np.complex128).reshape(-1)
    if vector.shape != (2,):
        raise ValueError("jones_vector must contain exactly two components")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0.0:
        raise ValueError("jones_vector must have a non-zero finite norm")
    vector = vector / norm
    zeros = np.zeros_like(field.values, dtype=np.complex128)
    return VectorField2D(
        ex=vector[0] * field.values,
        ey=vector[1] * field.values,
        ez=zeros,
        grid=field.grid,
        wavelength_nm=field.wavelength_nm,
        refractive_index=field.refractive_index,
        z_mm=field.z_mm,
    )


__all__ = ["VectorField2D", "lift_scalar_field_to_jones"]
