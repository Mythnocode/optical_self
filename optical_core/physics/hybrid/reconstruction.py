
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.hybrid.operators.cartesian_exit_pupil import (
    CartesianExitPupilResult,
    reconstruct_cartesian_exit_pupil,
)


@dataclass(frozen=True, slots=True)
class ComplexFieldReconstructionRequest:
    wavelength_nm: float
    image_refractive_index: float = 1.0
    grid_size: int = 257
    extent_scale: float = 1.04
    opl_fit_order: int = 2
    amplitude_weighting: str = "quadrature"
    normalize_power: bool = False
    include_arrays: bool = True


class ComplexFieldReconstructor(Protocol):
    name: str

    def reconstruct(
        self,
        trace: TraceBundle,
        request: ComplexFieldReconstructionRequest,
    ) -> CartesianExitPupilResult: ...


class CartesianExitPupilReconstructor:
    name = "cartesian_exit_pupil"

    def reconstruct(
        self,
        trace: TraceBundle,
        request: ComplexFieldReconstructionRequest,
    ) -> CartesianExitPupilResult:
        return reconstruct_cartesian_exit_pupil(
            trace,
            wavelength_nm=request.wavelength_nm,
            image_refractive_index=request.image_refractive_index,
            grid_size=request.grid_size,
            extent_scale=request.extent_scale,
            opl_fit_order=request.opl_fit_order,
            amplitude_weighting=request.amplitude_weighting,
            normalize_power=request.normalize_power,
            include_arrays=request.include_arrays,
        )


_FORMAL_RECONSTRUCTOR: ComplexFieldReconstructor = CartesianExitPupilReconstructor()


def formal_complex_field_reconstructor() -> ComplexFieldReconstructor:
    return _FORMAL_RECONSTRUCTOR


__all__ = [
    "ComplexFieldReconstructionRequest",
    "ComplexFieldReconstructor",
    "CartesianExitPupilReconstructor",
    "formal_complex_field_reconstructor",
]
