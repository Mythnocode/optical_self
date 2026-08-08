from __future__ import annotations

from typing import Literal

import numpy as np


Handedness = Literal["left", "right"]

PolarizationType = Literal[
    "zero",
    "linear",
    "left_circular",
    "right_circular",
    "elliptical",
]


def validate_jones_vector(jones: np.ndarray) -> np.ndarray:
    vector = np.asarray(jones, dtype=np.complex128)

    if vector.shape != (2,):
        raise ValueError("Jones vector must have shape (2,)")

    return vector


def validate_jones_matrix(matrix: np.ndarray) -> np.ndarray:
    array = np.asarray(matrix, dtype=np.complex128)

    if array.shape != (2, 2):
        raise ValueError("Jones matrix must have shape (2, 2)")

    return array


def validate_stokes_vector(stokes: np.ndarray) -> np.ndarray:
    vector = np.asarray(stokes, dtype=float)

    if vector.shape != (4,):
        raise ValueError("Stokes vector must have shape (4,)")

    return vector


def validate_mueller_matrix(matrix: np.ndarray) -> np.ndarray:
    array = np.asarray(matrix, dtype=float)

    if array.shape != (4, 4):
        raise ValueError("Mueller matrix must have shape (4, 4)")

    return array


def intensity_from_jones(jones: np.ndarray) -> float:
    vector = validate_jones_vector(jones)
    return float(np.sum(np.abs(vector) ** 2))


def normalize_jones(jones: np.ndarray) -> np.ndarray:
    vector = validate_jones_vector(jones)
    norm = np.sqrt(intensity_from_jones(vector))

    if norm == 0:
        raise ValueError("Cannot normalize a zero Jones vector")

    return vector / norm


def remove_global_phase(jones: np.ndarray, atol: float = 1.0e-14) -> np.ndarray:
    vector = validate_jones_vector(jones)

    for value in vector:
        if abs(value) > atol:
            return vector * np.exp(-1j * np.angle(value))

    return vector.copy()


def linear_jones(angle_rad: float, amplitude: complex = 1.0) -> np.ndarray:
    return np.asarray(
        [
            amplitude * np.cos(angle_rad),
            amplitude * np.sin(angle_rad),
        ],
        dtype=np.complex128,
    )


def horizontal_jones(amplitude: complex = 1.0) -> np.ndarray:
    return linear_jones(0.0, amplitude=amplitude)


def vertical_jones(amplitude: complex = 1.0) -> np.ndarray:
    return linear_jones(np.pi / 2.0, amplitude=amplitude)


def right_circular_jones(amplitude: complex = 1.0) -> np.ndarray:
    return np.asarray(
        [
            amplitude / np.sqrt(2.0),
            -1j * amplitude / np.sqrt(2.0),
        ],
        dtype=np.complex128,
    )


def left_circular_jones(amplitude: complex = 1.0) -> np.ndarray:
    return np.asarray(
        [
            amplitude / np.sqrt(2.0),
            1j * amplitude / np.sqrt(2.0),
        ],
        dtype=np.complex128,
    )


def circular_jones(
    handedness: Handedness,
    amplitude: complex = 1.0,
) -> np.ndarray:
    if handedness == "left":
        return left_circular_jones(amplitude=amplitude)

    if handedness == "right":
        return right_circular_jones(amplitude=amplitude)

    raise ValueError("handedness must be 'left' or 'right'")


def elliptical_jones(
    amplitude_ratio_y_over_x: float,
    phase_difference_rad: float,
    amplitude_x: complex = 1.0,
    normalize: bool = True,
) -> np.ndarray:
    if amplitude_ratio_y_over_x < 0:
        raise ValueError("amplitude_ratio_y_over_x must be non-negative")

    vector = np.asarray(
        [
            amplitude_x,
            amplitude_x
            * amplitude_ratio_y_over_x
            * np.exp(1j * phase_difference_rad),
        ],
        dtype=np.complex128,
    )

    if normalize:
        return normalize_jones(vector)

    return vector


def jones_inner_product(left: np.ndarray, right: np.ndarray) -> complex:
    left_vector = validate_jones_vector(left)
    right_vector = validate_jones_vector(right)

    return np.vdot(left_vector, right_vector)


def are_orthogonal_jones(
    left: np.ndarray,
    right: np.ndarray,
    atol: float = 1.0e-12,
) -> bool:
    return abs(jones_inner_product(left, right)) <= atol


def rotation_matrix(angle_rad: float) -> np.ndarray:
    c = np.cos(angle_rad)
    s = np.sin(angle_rad)

    return np.asarray(
        [
            [c, -s],
            [s, c],
        ],
        dtype=np.complex128,
    )


def linear_polarizer_jones(angle_rad: float) -> np.ndarray:
    c = np.cos(angle_rad)
    s = np.sin(angle_rad)

    return np.asarray(
        [
            [c * c, s * c],
            [s * c, s * s],
        ],
        dtype=np.complex128,
    )


def horizontal_polarizer_jones() -> np.ndarray:
    return linear_polarizer_jones(0.0)


def vertical_polarizer_jones() -> np.ndarray:
    return linear_polarizer_jones(np.pi / 2.0)


def linear_retarder_jones(
    retardance_rad: float,
    fast_axis_angle_rad: float = 0.0,
) -> np.ndarray:

    axis = rotation_matrix(fast_axis_angle_rad)

    phase = np.asarray(
        [
            [1.0, 0.0],
            [0.0, np.exp(1j * retardance_rad)],
        ],
        dtype=np.complex128,
    )

    return axis @ phase @ axis.T


def quarter_wave_plate_jones(fast_axis_angle_rad: float = 0.0) -> np.ndarray:
    return linear_retarder_jones(
        retardance_rad=np.pi / 2.0,
        fast_axis_angle_rad=fast_axis_angle_rad,
    )


def half_wave_plate_jones(fast_axis_angle_rad: float = 0.0) -> np.ndarray:
    return linear_retarder_jones(
        retardance_rad=np.pi,
        fast_axis_angle_rad=fast_axis_angle_rad,
    )


def full_wave_plate_jones(fast_axis_angle_rad: float = 0.0) -> np.ndarray:
    return linear_retarder_jones(
        retardance_rad=2.0 * np.pi,
        fast_axis_angle_rad=fast_axis_angle_rad,
    )


def apply_jones_matrix(matrix: np.ndarray, jones: np.ndarray) -> np.ndarray:
    matrix = validate_jones_matrix(matrix)
    vector = validate_jones_vector(jones)

    return matrix @ vector


def compose_jones_matrices(*matrices: np.ndarray) -> np.ndarray:

    result = np.eye(2, dtype=np.complex128)

    for matrix in matrices:
        result = validate_jones_matrix(matrix) @ result

    return result


def stokes_from_jones(jones: np.ndarray) -> np.ndarray:

    vector = validate_jones_vector(jones)
    ex, ey = vector

    s0 = np.abs(ex) ** 2 + np.abs(ey) ** 2
    s1 = np.abs(ex) ** 2 - np.abs(ey) ** 2
    s2 = 2.0 * np.real(ex * np.conj(ey))
    s3 = -2.0 * np.imag(ex * np.conj(ey))

    return np.asarray([s0, s1, s2, s3], dtype=float)


def unpolarized_stokes(input_intensity: float = 1.0) -> np.ndarray:
    if input_intensity < 0:
        raise ValueError("input_intensity must be non-negative")

    return np.asarray([float(input_intensity), 0.0, 0.0, 0.0], dtype=float)


def degree_of_polarization(stokes: np.ndarray) -> float:
    vector = validate_stokes_vector(stokes)
    s0 = vector[0]

    if s0 <= 0:
        return 0.0

    return float(np.sqrt(vector[1] ** 2 + vector[2] ** 2 + vector[3] ** 2) / s0)


def apply_mueller_matrix(matrix: np.ndarray, stokes: np.ndarray) -> np.ndarray:
    matrix = validate_mueller_matrix(matrix)
    vector = validate_stokes_vector(stokes)

    return matrix @ vector


def linear_polarizer_mueller(angle_rad: float) -> np.ndarray:
    c = np.cos(2.0 * angle_rad)
    s = np.sin(2.0 * angle_rad)

    return 0.5 * np.asarray(
        [
            [1.0, c, s, 0.0],
            [c, c * c, c * s, 0.0],
            [s, c * s, s * s, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
        dtype=float,
    )


def classify_jones_polarization(
    jones: np.ndarray,
    atol: float = 1.0e-9,
) -> PolarizationType:
    vector = validate_jones_vector(jones)

    if intensity_from_jones(vector) <= atol:
        return "zero"

    normalized = normalize_jones(vector)
    s0, s1, s2, s3 = stokes_from_jones(normalized)

    if abs(s3) <= atol:
        return "linear"

    if abs(s1) <= atol and abs(s2) <= atol and abs(abs(s3) - s0) <= atol:
        if s3 > 0:
            return "left_circular"

        return "right_circular"

    return "elliptical"


def ellipse_parameters_from_jones(jones: np.ndarray) -> dict[str, float | str]:
    vector = normalize_jones(jones)
    s0, s1, s2, s3 = stokes_from_jones(vector)

    orientation_rad = 0.5 * np.arctan2(s2, s1)

    ratio = np.clip(s3 / s0, -1.0, 1.0)
    ellipticity_angle_rad = 0.5 * np.arcsin(ratio)
    ellipticity = np.tan(ellipticity_angle_rad)

    if abs(s3) < 1.0e-12:
        handedness = "none"
    elif s3 > 0:
        handedness = "left"
    else:
        handedness = "right"

    return {
        "orientation_rad": float(orientation_rad),
        "orientation_deg": float(np.rad2deg(orientation_rad)),
        "ellipticity_angle_rad": float(ellipticity_angle_rad),
        "ellipticity_angle_deg": float(np.rad2deg(ellipticity_angle_rad)),
        "ellipticity": float(ellipticity),
        "handedness": handedness,
    }


def analyzer_intensity(
    jones: np.ndarray,
    analyzer_angle_rad: float,
) -> float:
    polarizer = linear_polarizer_jones(analyzer_angle_rad)
    output = apply_jones_matrix(polarizer, jones)

    return intensity_from_jones(output)


def analyzer_scan(
    jones: np.ndarray,
    analyzer_angles_rad: np.ndarray,
) -> np.ndarray:
    vector = validate_jones_vector(jones)
    angles = np.asarray(analyzer_angles_rad, dtype=float)

    return np.asarray(
        [analyzer_intensity(vector, angle) for angle in angles],
        dtype=float,
    )


def retardance_from_birefringence(
    n_slow: float,
    n_fast: float,
    thickness_m: float,
    wavelength_m: float,
) -> float:
    if n_slow <= 0:
        raise ValueError("n_slow must be positive")
    if n_fast <= 0:
        raise ValueError("n_fast must be positive")
    if n_slow <= n_fast:
        raise ValueError("n_slow must be greater than n_fast")
    if thickness_m < 0:
        raise ValueError("thickness_m must be non-negative")
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")

    return float(2.0 * np.pi * (n_slow - n_fast) * thickness_m / wavelength_m)


def required_waveplate_thickness(
    n_slow: float,
    n_fast: float,
    wavelength_m: float,
    target_retardance_rad: float,
) -> float:
    if n_slow <= 0:
        raise ValueError("n_slow must be positive")
    if n_fast <= 0:
        raise ValueError("n_fast must be positive")
    if n_slow <= n_fast:
        raise ValueError("n_slow must be greater than n_fast")
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if target_retardance_rad < 0:
        raise ValueError("target_retardance_rad must be non-negative")

    return float(
        target_retardance_rad
        * wavelength_m
        / (2.0 * np.pi * (n_slow - n_fast))
    )


def ordinary_extraordinary_intensity_split(
    input_intensity: float,
    angle_to_principal_section_rad: float,
) -> tuple[float, float]:

    if input_intensity < 0:
        raise ValueError("input_intensity must be non-negative")

    ordinary = input_intensity * np.sin(angle_to_principal_section_rad) ** 2
    extraordinary = input_intensity * np.cos(angle_to_principal_section_rad) ** 2

    return float(ordinary), float(extraordinary)