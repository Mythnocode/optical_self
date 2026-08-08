from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optical_core.physics.wave.formulas.polarization import (
    apply_jones_matrix,
    intensity_from_jones,
    linear_polarizer_jones,
    normalize_jones,
    validate_jones_vector,
)


@dataclass(frozen=True)
class TwoBeamInterferenceResult:
    input_intensity_1: float
    input_intensity_2: float
    output_intensity: float
    visibility: float
    overlap_amplitude: float
    overlap_power: float
    relative_phase_rad: float


@dataclass(frozen=True)
class PhaseScanResult:
    phases_rad: np.ndarray
    intensities: np.ndarray
    visibility: float
    intensity_max: float
    intensity_min: float


def jones_field_overlap(left: np.ndarray, right: np.ndarray) -> complex:
    left_vector = validate_jones_vector(left)
    right_vector = validate_jones_vector(right)

    return complex(np.vdot(left_vector, right_vector))


def normalized_polarization_overlap_amplitude(
    left: np.ndarray,
    right: np.ndarray,
) -> float:
    left_vector = validate_jones_vector(left)
    right_vector = validate_jones_vector(right)

    left_intensity = intensity_from_jones(left_vector)
    right_intensity = intensity_from_jones(right_vector)

    if left_intensity <= 0 or right_intensity <= 0:
        return 0.0

    value = abs(jones_field_overlap(left_vector, right_vector)) / np.sqrt(
        left_intensity * right_intensity
    )

    return float(np.clip(value, 0.0, 1.0))


def normalized_polarization_overlap_power(
    left: np.ndarray,
    right: np.ndarray,
) -> float:
    amplitude = normalized_polarization_overlap_amplitude(left, right)
    return float(amplitude * amplitude)


def are_polarizations_orthogonal(
    left: np.ndarray,
    right: np.ndarray,
    atol: float = 1.0e-12,
) -> bool:
    return normalized_polarization_overlap_amplitude(left, right) <= atol


def are_polarizations_same(
    left: np.ndarray,
    right: np.ndarray,
    atol: float = 1.0e-12,
) -> bool:
    return abs(normalized_polarization_overlap_amplitude(left, right) - 1.0) <= atol


def coherent_superposition(
    first: np.ndarray,
    second: np.ndarray,
    relative_phase_rad: float = 0.0,
) -> np.ndarray:
    first_vector = validate_jones_vector(first)
    second_vector = validate_jones_vector(second)

    return first_vector + second_vector * np.exp(1j * relative_phase_rad)


def two_beam_interference_intensity(
    first: np.ndarray,
    second: np.ndarray,
    relative_phase_rad: float = 0.0,
    coherence_factor: float = 1.0,
) -> float:
    first_vector = validate_jones_vector(first)
    second_vector = validate_jones_vector(second)

    coherence = _validated_coherence_factor(coherence_factor)

    intensity_1 = intensity_from_jones(first_vector)
    intensity_2 = intensity_from_jones(second_vector)
    overlap = jones_field_overlap(first_vector, second_vector)

    value = intensity_1 + intensity_2 + 2.0 * coherence * np.real(
        np.exp(1j * relative_phase_rad) * overlap
    )

    return _non_negative_float(value)


def interference_visibility(
    first: np.ndarray,
    second: np.ndarray,
    coherence_factor: float = 1.0,
) -> float:
    first_vector = validate_jones_vector(first)
    second_vector = validate_jones_vector(second)

    coherence = _validated_coherence_factor(coherence_factor)

    intensity_1 = intensity_from_jones(first_vector)
    intensity_2 = intensity_from_jones(second_vector)
    denominator = intensity_1 + intensity_2

    if denominator <= 0:
        return 0.0

    overlap = abs(jones_field_overlap(first_vector, second_vector))

    return float(np.clip(2.0 * coherence * overlap / denominator, 0.0, 1.0))


def two_beam_interference(
    first: np.ndarray,
    second: np.ndarray,
    relative_phase_rad: float = 0.0,
    coherence_factor: float = 1.0,
) -> TwoBeamInterferenceResult:
    first_vector = validate_jones_vector(first)
    second_vector = validate_jones_vector(second)

    return TwoBeamInterferenceResult(
        input_intensity_1=intensity_from_jones(first_vector),
        input_intensity_2=intensity_from_jones(second_vector),
        output_intensity=two_beam_interference_intensity(
            first_vector,
            second_vector,
            relative_phase_rad=relative_phase_rad,
            coherence_factor=coherence_factor,
        ),
        visibility=interference_visibility(
            first_vector,
            second_vector,
            coherence_factor=coherence_factor,
        ),
        overlap_amplitude=normalized_polarization_overlap_amplitude(
            first_vector,
            second_vector,
        ),
        overlap_power=normalized_polarization_overlap_power(
            first_vector,
            second_vector,
        ),
        relative_phase_rad=float(relative_phase_rad),
    )


def phase_scan_interference(
    first: np.ndarray,
    second: np.ndarray,
    phases_rad: np.ndarray,
    coherence_factor: float = 1.0,
) -> PhaseScanResult:
    phases = np.asarray(phases_rad, dtype=float).ravel()

    if phases.size == 0:
        raise ValueError("phases_rad must not be empty")
    if np.any(~np.isfinite(phases)):
        raise ValueError("phases_rad must be finite")

    intensities = np.asarray(
        [
            two_beam_interference_intensity(
                first,
                second,
                relative_phase_rad=phase,
                coherence_factor=coherence_factor,
            )
            for phase in phases
        ],
        dtype=float,
    )

    maximum = float(np.max(intensities))
    minimum = float(np.min(intensities))

    return PhaseScanResult(
        phases_rad=phases,
        intensities=intensities,
        visibility=visibility_from_intensity_scan(intensities),
        intensity_max=maximum,
        intensity_min=minimum,
    )


def visibility_from_intensity_scan(intensities: np.ndarray) -> float:
    values = np.asarray(intensities, dtype=float).ravel()

    if values.size == 0:
        raise ValueError("intensities must not be empty")
    if np.any(~np.isfinite(values)):
        raise ValueError("intensities must be finite")
    if np.any(values < -1.0e-12):
        raise ValueError("intensities must be non-negative")

    values = np.where((values < 0.0) & (values > -1.0e-12), 0.0, values)

    maximum = float(np.max(values))
    minimum = float(np.min(values))

    if maximum + minimum <= 0:
        return 0.0

    return float((maximum - minimum) / (maximum + minimum))


def path_phase_from_opd(
    optical_path_difference_m: float,
    wavelength_m: float,
) -> float:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")

    return float(2.0 * np.pi * optical_path_difference_m / wavelength_m)


def young_double_slit_phase(
    screen_x_m: np.ndarray,
    slit_separation_m: float,
    screen_distance_m: float,
    wavelength_m: float,
) -> np.ndarray:
    x = np.asarray(screen_x_m, dtype=float)

    if slit_separation_m <= 0:
        raise ValueError("slit_separation_m must be positive")
    if screen_distance_m <= 0:
        raise ValueError("screen_distance_m must be positive")
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")

    return 2.0 * np.pi * slit_separation_m * x / (
        wavelength_m * screen_distance_m
    )


def young_double_slit_polarization_pattern(
    screen_x_m: np.ndarray,
    slit_separation_m: float,
    screen_distance_m: float,
    wavelength_m: float,
    slit1_jones: np.ndarray,
    slit2_jones: np.ndarray,
    coherence_factor: float = 1.0,
) -> np.ndarray:
    phases = young_double_slit_phase(
        screen_x_m=screen_x_m,
        slit_separation_m=slit_separation_m,
        screen_distance_m=screen_distance_m,
        wavelength_m=wavelength_m,
    )

    return np.asarray(
        [
            two_beam_interference_intensity(
                slit1_jones,
                slit2_jones,
                relative_phase_rad=phase,
                coherence_factor=coherence_factor,
            )
            for phase in phases.ravel()
        ],
        dtype=float,
    ).reshape(np.asarray(screen_x_m).shape)


def analyzer_restored_fields(
    first: np.ndarray,
    second: np.ndarray,
    analyzer_angle_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    polarizer = linear_polarizer_jones(analyzer_angle_rad)

    return (
        apply_jones_matrix(polarizer, validate_jones_vector(first)),
        apply_jones_matrix(polarizer, validate_jones_vector(second)),
    )


def analyzer_restored_visibility(
    first: np.ndarray,
    second: np.ndarray,
    analyzer_angle_rad: float,
    coherence_factor: float = 1.0,
) -> float:
    first_after, second_after = analyzer_restored_fields(
        first,
        second,
        analyzer_angle_rad=analyzer_angle_rad,
    )

    return interference_visibility(
        first_after,
        second_after,
        coherence_factor=coherence_factor,
    )


def analyzer_restored_interference_intensity(
    first: np.ndarray,
    second: np.ndarray,
    analyzer_angle_rad: float,
    relative_phase_rad: float = 0.0,
    coherence_factor: float = 1.0,
) -> float:
    first_after, second_after = analyzer_restored_fields(
        first,
        second,
        analyzer_angle_rad=analyzer_angle_rad,
    )

    return two_beam_interference_intensity(
        first_after,
        second_after,
        relative_phase_rad=relative_phase_rad,
        coherence_factor=coherence_factor,
    )


def which_path_distinguishability_from_overlap(
    first: np.ndarray,
    second: np.ndarray,
) -> float:
    overlap_power = normalized_polarization_overlap_power(first, second)
    return float(np.sqrt(np.clip(1.0 - overlap_power, 0.0, 1.0)))


def complementarity_from_polarization(
    first: np.ndarray,
    second: np.ndarray,
) -> dict[str, float]:
    visibility = normalized_polarization_overlap_amplitude(first, second)
    distinguishability = which_path_distinguishability_from_overlap(first, second)

    return {
        "visibility": float(visibility),
        "distinguishability": float(distinguishability),
        "v_squared_plus_d_squared": float(visibility**2 + distinguishability**2),
    }


def polarization_decoherence_factor(
    first: np.ndarray,
    second: np.ndarray,
) -> float:
    return normalized_polarization_overlap_amplitude(first, second)


def coherence_weighted_visibility(
    first: np.ndarray,
    second: np.ndarray,
    temporal_coherence_factor: float = 1.0,
    spatial_coherence_factor: float = 1.0,
) -> float:
    temporal = _validated_coherence_factor(temporal_coherence_factor)
    spatial = _validated_coherence_factor(spatial_coherence_factor)

    return interference_visibility(
        first,
        second,
        coherence_factor=temporal * spatial,
    )


def normalized_interference_pattern(
    intensities: np.ndarray,
) -> np.ndarray:
    values = np.asarray(intensities, dtype=float)

    maximum = float(np.max(values))

    if maximum <= 0:
        return np.zeros_like(values, dtype=float)

    return values / maximum


def equal_intensity_jones(
    jones: np.ndarray,
    intensity: float = 1.0,
) -> np.ndarray:
    if intensity < 0:
        raise ValueError("intensity must be non-negative")

    if intensity == 0:
        return np.asarray([0.0, 0.0], dtype=np.complex128)

    return normalize_jones(jones) * np.sqrt(intensity)


def _validated_coherence_factor(value: float) -> float:
    coherence = float(value)

    if coherence < 0.0 or coherence > 1.0:
        raise ValueError("coherence_factor must be between 0 and 1")

    return coherence


def _non_negative_float(value: float, tolerance: float = 1.0e-12) -> float:
    result = float(np.real(value))

    if result < 0.0 and result > -tolerance:
        return 0.0

    if result < 0.0:
        raise ValueError("computed intensity is negative")

    return result