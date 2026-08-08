
from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Sequence, Any
import math
import numpy as np

from optical_core.models.representations.scalar_field import ScalarField2D


@dataclass(frozen=True, slots=True)
class SpectralFieldComponent:
    field: ScalarField2D
    power_weight: float = 1.0
    coherence_group: Hashable | None = None
    phase_offset_rad: float = 0.0


@dataclass(frozen=True, slots=True)
class SpectralIntensityResult:
    intensity: np.ndarray
    normalized_weights: tuple[float, ...]
    group_count: int
    metadata: dict[str, Any]


def gaussian_spectral_lines(
    center_wavelength_nm: float,
    fwhm_nm: float,
    *,
    sample_count: int = 9,
    span_fwhm: float = 3.0,
) -> tuple[np.ndarray, np.ndarray]:

    center = float(center_wavelength_nm)
    width = float(fwhm_nm)
    count = max(1, int(sample_count))
    if center <= 0.0 or width < 0.0:
        raise ValueError("center wavelength must be positive and FWHM non-negative")
    if count == 1 or width == 0.0:
        return np.asarray([center]), np.asarray([1.0])
    sigma = width / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    axis = np.linspace(center - span_fwhm * width / 2.0, center + span_fwhm * width / 2.0, count)
    weights = np.exp(-0.5 * ((axis - center) / sigma) ** 2)
    weights /= float(np.sum(weights))
    return axis, weights


def combine_spectral_intensity(
    components: Sequence[SpectralFieldComponent],
    *,
    mutual_coherence_matrix: np.ndarray | None = None,
) -> SpectralIntensityResult:

    if not components:
        raise ValueError("at least one spectral field component is required")
    reference = components[0].field
    shape = reference.values.shape
    weights = np.asarray([float(item.power_weight) for item in components], dtype=float)
    if np.any(~np.isfinite(weights)) or np.any(weights < 0.0) or float(np.sum(weights)) <= 0.0:
        raise ValueError("power weights must be finite, non-negative and not all zero")
    weights /= float(np.sum(weights))

    fields: list[np.ndarray] = []
    for component in components:
        field = component.field
        if (
            field.values.shape != shape
            or not np.allclose(field.grid.x_mm, reference.grid.x_mm)
            or not np.allclose(field.grid.y_mm, reference.grid.y_mm)
        ):
            raise ValueError("all spectral components must share the same sampled output grid")
        fields.append(
            np.asarray(field.values, dtype=np.complex128)
            * np.exp(1j * float(component.phase_offset_rad))
        )

    if mutual_coherence_matrix is not None:
        gamma = np.asarray(mutual_coherence_matrix, dtype=np.complex128)
        n = len(components)
        if gamma.shape != (n, n):
            raise ValueError("mutual_coherence_matrix must be square with one row per component")
        if np.any(np.abs(gamma) > 1.0 + 1.0e-12):
            raise ValueError("mutual coherence magnitude cannot exceed one")
        if not np.allclose(gamma, gamma.conjugate().T, atol=1.0e-10):
            raise ValueError("mutual_coherence_matrix must be Hermitian")
        intensity = np.zeros(shape, dtype=float)
        for i, ei in enumerate(fields):
            intensity += weights[i] * np.abs(ei) ** 2
            for j in range(i + 1, n):
                cross = gamma[i, j] * math.sqrt(weights[i] * weights[j]) * ei * np.conjugate(fields[j])
                intensity += 2.0 * np.real(cross)
        intensity = np.maximum(intensity, 0.0)
        group_count = len(components)
        rule = "cross_spectral_density_partial_coherence"
    else:
        groups: dict[Hashable, np.ndarray] = {}
        for index, (component, weight, values) in enumerate(zip(components, weights, fields)):
            key: Hashable = ("independent", index) if component.coherence_group is None else component.coherence_group
            amplitude = math.sqrt(max(float(weight), 0.0)) * values
            groups[key] = groups.get(key, np.zeros(shape, dtype=np.complex128)) + amplitude
        intensity = np.zeros(shape, dtype=float)
        for amplitude in groups.values():
            intensity += np.abs(amplitude) ** 2
        group_count = len(groups)
        rule = "coherent_within_group_incoherent_between_groups"

    return SpectralIntensityResult(
        intensity=intensity,
        normalized_weights=tuple(float(v) for v in weights),
        group_count=group_count,
        metadata={
            "combination_rule": rule,
            "spectral_component_count": len(components),
            "mutual_coherence_matrix_used": mutual_coherence_matrix is not None,
        },
    )


__all__ = [
    "SpectralFieldComponent",
    "SpectralIntensityResult",
    "gaussian_spectral_lines",
    "combine_spectral_intensity",
]
