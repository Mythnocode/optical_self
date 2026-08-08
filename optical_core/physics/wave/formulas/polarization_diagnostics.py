from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from optical_core.physics.wave.formulas.polarization import (
    analyzer_scan,
    classify_jones_polarization,
    degree_of_polarization,
    intensity_from_jones,
    stokes_from_jones,
    validate_jones_vector,
    validate_stokes_vector,
)


PolarizationDiagnosis = Literal[
    "zero",
    "unpolarized_or_depolarized",
    "linear",
    "circular",
    "elliptical",
    "partially_polarized",
]


@dataclass(frozen=True)
class AnalyzerScanFit:
    stokes: np.ndarray
    fitted_intensity: np.ndarray
    residual_rms: float
    visibility: float
    extinction_ratio: float
    estimated_linear_angle_rad: float
    estimated_linear_angle_deg: float
    degree_of_linear_polarization: float


@dataclass(frozen=True)
class PolarizationStateDiagnostics:
    input_intensity: float
    output_intensity: float
    input_stokes: np.ndarray
    output_stokes: np.ndarray
    input_degree_of_polarization: float
    output_degree_of_polarization: float
    input_type: str
    output_type: str
    transmission: float


def validate_scan_data(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    angles = np.asarray(analyzer_angles_rad, dtype=float).ravel()
    values = np.asarray(intensities, dtype=float).ravel()

    if angles.shape != values.shape:
        raise ValueError("analyzer_angles_rad and intensities must have the same shape")
    if angles.size < 3:
        raise ValueError("At least three analyzer samples are required")
    if np.any(~np.isfinite(angles)):
        raise ValueError("analyzer_angles_rad must be finite")
    if np.any(~np.isfinite(values)):
        raise ValueError("intensities must be finite")
    if np.any(values < 0):
        raise ValueError("intensities must be non-negative")

    return angles, values


def visibility_from_min_max(maximum: float, minimum: float) -> float:
    if maximum < 0 or minimum < 0:
        raise ValueError("maximum and minimum must be non-negative")
    if maximum < minimum:
        raise ValueError("maximum must be greater than or equal to minimum")
    if maximum + minimum <= 0:
        return 0.0

    return float((maximum - minimum) / (maximum + minimum))


def extinction_ratio_from_min_max(
    maximum: float,
    minimum: float,
    floor: float = 1.0e-15,
) -> float:
    if maximum < 0 or minimum < 0:
        raise ValueError("maximum and minimum must be non-negative")
    if maximum < minimum:
        raise ValueError("maximum must be greater than or equal to minimum")
    if floor <= 0:
        raise ValueError("floor must be positive")

    return float(maximum / max(minimum, floor))


def analyzer_scan_statistics(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> dict[str, float]:
    angles, values = validate_scan_data(analyzer_angles_rad, intensities)

    maximum = float(np.max(values))
    minimum = float(np.min(values))
    mean_value = float(np.mean(values))
    max_index = int(np.argmax(values))
    min_index = int(np.argmin(values))

    return {
        "sample_count": float(values.size),
        "intensity_max": maximum,
        "intensity_min": minimum,
        "intensity_mean": mean_value,
        "intensity_peak_to_peak": float(maximum - minimum),
        "visibility": visibility_from_min_max(maximum, minimum),
        "extinction_ratio": extinction_ratio_from_min_max(maximum, minimum),
        "max_angle_rad": float(angles[max_index]),
        "max_angle_deg": float(np.rad2deg(angles[max_index])),
        "min_angle_rad": float(angles[min_index]),
        "min_angle_deg": float(np.rad2deg(angles[min_index])),
    }


def fit_linear_analyzer_scan(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> AnalyzerScanFit:

    angles, values = validate_scan_data(analyzer_angles_rad, intensities)

    design = 0.5 * np.column_stack(
        [
            np.ones_like(angles),
            np.cos(2.0 * angles),
            np.sin(2.0 * angles),
        ]
    )

    coeffs, *_ = np.linalg.lstsq(design, values, rcond=None)
    fitted = design @ coeffs

    s0 = float(coeffs[0])
    s1 = float(coeffs[1])
    s2 = float(coeffs[2])
    stokes = np.asarray([s0, s1, s2, 0.0], dtype=float)

    residual = values - fitted
    residual_rms = float(np.sqrt(np.mean(residual**2)))

    fitted_for_metrics = np.where(
        (fitted < 0.0) & (fitted > -1.0e-12),
        0.0,
        fitted,
    )

    maximum = float(np.max(fitted_for_metrics))
    minimum = float(np.min(fitted_for_metrics))

    if minimum < 0.0:
        raise ValueError("fitted intensity contains a physically invalid negative value")

    if s0 <= 0:
        linear_degree = 0.0
    else:
        linear_degree = float(np.sqrt(s1 * s1 + s2 * s2) / s0)

    linear_degree = float(np.clip(linear_degree, 0.0, 1.0))
    angle_rad = 0.5 * np.arctan2(s2, s1)

    return AnalyzerScanFit(
        stokes=stokes,
        fitted_intensity=fitted,
        residual_rms=residual_rms,
        visibility=visibility_from_min_max(maximum, minimum),
        extinction_ratio=extinction_ratio_from_min_max(maximum, minimum),
        estimated_linear_angle_rad=float(angle_rad),
        estimated_linear_angle_deg=float(np.rad2deg(angle_rad)),
        degree_of_linear_polarization=linear_degree,
    )


def stokes_from_linear_analyzer_scan(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> np.ndarray:
    return fit_linear_analyzer_scan(analyzer_angles_rad, intensities).stokes


def estimate_linear_polarization_angle(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> float:
    return fit_linear_analyzer_scan(
        analyzer_angles_rad=analyzer_angles_rad,
        intensities=intensities,
    ).estimated_linear_angle_rad


def degree_of_linear_polarization_from_scan(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> float:
    return fit_linear_analyzer_scan(
        analyzer_angles_rad=analyzer_angles_rad,
        intensities=intensities,
    ).degree_of_linear_polarization


def classify_stokes_polarization(
    stokes: np.ndarray,
    atol: float = 1.0e-9,
) -> PolarizationDiagnosis:
    vector = validate_stokes_vector(stokes)
    s0, s1, s2, s3 = vector

    if s0 <= atol:
        return "zero"

    dop = degree_of_polarization(vector)

    if dop <= atol:
        return "unpolarized_or_depolarized"

    if dop < 1.0 - atol:
        return "partially_polarized"

    if abs(s3) <= atol:
        return "linear"

    if abs(s1) <= atol and abs(s2) <= atol and abs(abs(s3) - s0) <= atol:
        return "circular"

    return "elliptical"


def classify_scan_polarization(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
    visibility_linear_threshold: float = 0.95,
    visibility_unpolarized_threshold: float = 0.05,
) -> PolarizationDiagnosis:
    if visibility_linear_threshold <= visibility_unpolarized_threshold:
        raise ValueError(
            "visibility_linear_threshold must be greater than "
            "visibility_unpolarized_threshold"
        )

    fit = fit_linear_analyzer_scan(analyzer_angles_rad, intensities)

    if fit.visibility >= visibility_linear_threshold:
        return "linear"

    if fit.visibility <= visibility_unpolarized_threshold:
        return "unpolarized_or_depolarized"

    return "partially_polarized"


def ideal_analyzer_scan_from_jones(
    jones: np.ndarray,
    analyzer_angles_rad: np.ndarray,
) -> np.ndarray:
    vector = validate_jones_vector(jones)
    angles = np.asarray(analyzer_angles_rad, dtype=float)

    return analyzer_scan(vector, angles)


def diagnose_analyzer_scan(
    analyzer_angles_rad: np.ndarray,
    intensities: np.ndarray,
) -> dict[str, float | str | list[float]]:
    fit = fit_linear_analyzer_scan(analyzer_angles_rad, intensities)
    stats = analyzer_scan_statistics(analyzer_angles_rad, intensities)

    result: dict[str, float | str | list[float]] = {
        **stats,
        "fit_residual_rms": fit.residual_rms,
        "fit_visibility": fit.visibility,
        "fit_extinction_ratio": fit.extinction_ratio,
        "estimated_linear_angle_rad": fit.estimated_linear_angle_rad,
        "estimated_linear_angle_deg": fit.estimated_linear_angle_deg,
        "degree_of_linear_polarization": fit.degree_of_linear_polarization,
        "diagnosis": classify_scan_polarization(analyzer_angles_rad, intensities),
        "fitted_stokes": [float(item) for item in fit.stokes],
    }

    return result


def compare_jones_states(
    input_jones: np.ndarray,
    output_jones: np.ndarray,
) -> PolarizationStateDiagnostics:
    input_vector = validate_jones_vector(input_jones)
    output_vector = validate_jones_vector(output_jones)

    input_intensity = intensity_from_jones(input_vector)
    output_intensity = intensity_from_jones(output_vector)

    input_stokes = stokes_from_jones(input_vector)
    output_stokes = stokes_from_jones(output_vector)

    if input_intensity <= 1.0e-15:
        transmission = 0.0
    else:
        transmission = output_intensity / input_intensity

    return PolarizationStateDiagnostics(
        input_intensity=float(input_intensity),
        output_intensity=float(output_intensity),
        input_stokes=input_stokes,
        output_stokes=output_stokes,
        input_degree_of_polarization=degree_of_polarization(input_stokes),
        output_degree_of_polarization=degree_of_polarization(output_stokes),
        input_type=classify_jones_polarization(input_vector),
        output_type=classify_jones_polarization(output_vector),
        transmission=float(transmission),
    )


def stokes_error(
    expected: np.ndarray,
    measured: np.ndarray,
) -> dict[str, float]:
    expected_vector = validate_stokes_vector(expected)
    measured_vector = validate_stokes_vector(measured)

    difference = measured_vector - expected_vector

    return {
        "s0_error": float(difference[0]),
        "s1_error": float(difference[1]),
        "s2_error": float(difference[2]),
        "s3_error": float(difference[3]),
        "l2_error": float(np.linalg.norm(difference)),
        "relative_l2_error": _safe_relative_norm(difference, expected_vector),
    }


def normalized_stokes(stokes: np.ndarray) -> np.ndarray:
    vector = validate_stokes_vector(stokes)

    if vector[0] <= 0:
        raise ValueError("S0 must be positive for normalized Stokes parameters")

    return vector / vector[0]


def polarization_ellipse_angles_from_stokes(
    stokes: np.ndarray,
) -> dict[str, float]:
    vector = validate_stokes_vector(stokes)
    s0, s1, s2, s3 = vector

    if s0 <= 0:
        raise ValueError("S0 must be positive")

    orientation_rad = 0.5 * np.arctan2(s2, s1)
    ellipticity_angle_rad = 0.5 * np.arcsin(np.clip(s3 / s0, -1.0, 1.0))

    return {
        "orientation_rad": float(orientation_rad),
        "orientation_deg": float(np.rad2deg(orientation_rad)),
        "ellipticity_angle_rad": float(ellipticity_angle_rad),
        "ellipticity_angle_deg": float(np.rad2deg(ellipticity_angle_rad)),
        "ellipticity": float(np.tan(ellipticity_angle_rad)),
    }


def scan_residual_metrics(
    measured: np.ndarray,
    fitted: np.ndarray,
) -> dict[str, float]:
    measured_values = np.asarray(measured, dtype=float).ravel()
    fitted_values = np.asarray(fitted, dtype=float).ravel()

    if measured_values.shape != fitted_values.shape:
        raise ValueError("measured and fitted must have the same shape")
    if measured_values.size == 0:
        raise ValueError("measured and fitted must not be empty")

    residual = measured_values - fitted_values

    return {
        "mean_error": float(np.mean(residual)),
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "max_abs_error": float(np.max(np.abs(residual))),
    }


def _safe_relative_norm(
    difference: np.ndarray,
    expected: np.ndarray,
    floor: float = 1.0e-15,
) -> float:
    denominator = max(float(np.linalg.norm(expected)), floor)
    return float(np.linalg.norm(difference) / denominator)