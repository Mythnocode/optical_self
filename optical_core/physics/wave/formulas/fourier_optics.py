from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


EvanescentMode = Literal["decay", "zero"]


@dataclass(frozen=True)
class SamplingGrid:
    sample_count: int
    extent_m: float
    spacing_m: float
    x_m: np.ndarray
    y_m: np.ndarray
    fx_per_m: np.ndarray
    fy_per_m: np.ndarray


def make_sampling_grid(sample_count: int, extent_m: float) -> SamplingGrid:
    if sample_count <= 1:
        raise ValueError("sample_count must be greater than 1")
    if extent_m <= 0:
        raise ValueError("extent_m must be positive")

    spacing_m = extent_m / sample_count

    axis = (np.arange(sample_count) - sample_count // 2) * spacing_m
    x_m, y_m = np.meshgrid(axis, axis, indexing="xy")

    freq_axis = np.fft.fftshift(np.fft.fftfreq(sample_count, d=spacing_m))
    fx_per_m, fy_per_m = np.meshgrid(freq_axis, freq_axis, indexing="xy")

    return SamplingGrid(
        sample_count=sample_count,
        extent_m=float(extent_m),
        spacing_m=float(spacing_m),
        x_m=x_m,
        y_m=y_m,
        fx_per_m=fx_per_m,
        fy_per_m=fy_per_m,
    )


def validate_square_complex_field(field: np.ndarray) -> np.ndarray:
    array = np.asarray(field)

    if array.ndim != 2:
        raise ValueError("field must be a 2D array")

    if array.shape[0] != array.shape[1]:
        raise ValueError("field must be a square 2D array")

    return array.astype(np.complex128, copy=False)


def fft2_centered(field: np.ndarray) -> np.ndarray:
    field = validate_square_complex_field(field)

    return np.fft.fftshift(
        np.fft.fft2(
            np.fft.ifftshift(field),
            norm="ortho",
        )
    )


def ifft2_centered(spectrum: np.ndarray) -> np.ndarray:
    spectrum = validate_square_complex_field(spectrum)

    return np.fft.fftshift(
        np.fft.ifft2(
            np.fft.ifftshift(spectrum),
            norm="ortho",
        )
    )


def intensity(field: np.ndarray) -> np.ndarray:
    return np.abs(np.asarray(field)) ** 2


def normalize_peak(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    peak = float(np.max(array))

    if peak <= 0:
        return array.copy()

    return array / peak


def plane_wave(
    grid: SamplingGrid,
    wavelength_m: float,
    theta_x_rad: float = 0.0,
    theta_y_rad: float = 0.0,
    amplitude: complex = 1.0,
) -> np.ndarray:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")

    k = 2.0 * np.pi / wavelength_m
    phase = k * (
        grid.x_m * np.sin(theta_x_rad)
        + grid.y_m * np.sin(theta_y_rad)
    )

    return complex(amplitude) * np.exp(1j * phase)


def spherical_wave(
    grid: SamplingGrid,
    wavelength_m: float,
    distance_m: float,
    amplitude: complex = 1.0,
    converging: bool = False,
) -> np.ndarray:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if distance_m == 0:
        raise ValueError("distance_m must be non-zero")

    k = 2.0 * np.pi / wavelength_m
    sign = -1.0 if converging else 1.0
    phase = sign * k * (grid.x_m**2 + grid.y_m**2) / (2.0 * distance_m)

    return complex(amplitude) * np.exp(1j * phase)


def off_axis_spherical_wave(
    grid: SamplingGrid,
    wavelength_m: float,
    distance_m: float,
    x0_m: float,
    y0_m: float,
    amplitude: complex = 1.0,
) -> np.ndarray:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if distance_m == 0:
        raise ValueError("distance_m must be non-zero")

    k = 2.0 * np.pi / wavelength_m
    phase = k * (
        (grid.x_m**2 + grid.y_m**2) / (2.0 * distance_m)
        - (grid.x_m * x0_m + grid.y_m * y0_m) / distance_m
    )

    return complex(amplitude) * np.exp(1j * phase)


def apply_screen(field: np.ndarray, screen: np.ndarray) -> np.ndarray:
    field = validate_square_complex_field(field)
    screen = validate_square_complex_field(screen)

    if field.shape != screen.shape:
        raise ValueError("field and screen must have the same shape")

    return field * screen


def circular_aperture(
    sample_count: int,
    extent_m: float,
    diameter_m: float,
) -> np.ndarray:
    if diameter_m <= 0:
        raise ValueError("diameter_m must be positive")

    grid = make_sampling_grid(sample_count=sample_count, extent_m=extent_m)
    radius = np.sqrt(grid.x_m**2 + grid.y_m**2)

    return (radius <= diameter_m / 2.0).astype(np.complex128)


def rectangular_aperture(
    grid: SamplingGrid,
    width_x_m: float,
    width_y_m: float,
) -> np.ndarray:
    if width_x_m <= 0:
        raise ValueError("width_x_m must be positive")
    if width_y_m <= 0:
        raise ValueError("width_y_m must be positive")

    mask = (
        (np.abs(grid.x_m) <= width_x_m / 2.0)
        & (np.abs(grid.y_m) <= width_y_m / 2.0)
    )

    return mask.astype(np.complex128)


def single_slit_screen(
    grid: SamplingGrid,
    slit_width_m: float,
    axis: Literal["x", "y"] = "x",
) -> np.ndarray:
    if slit_width_m <= 0:
        raise ValueError("slit_width_m must be positive")

    if axis == "x":
        mask = np.abs(grid.x_m) <= slit_width_m / 2.0
    elif axis == "y":
        mask = np.abs(grid.y_m) <= slit_width_m / 2.0
    else:
        raise ValueError("axis must be 'x' or 'y'")

    return mask.astype(np.complex128)


def thin_lens_phase(
    grid: SamplingGrid,
    wavelength_m: float,
    focal_length_m: float,
) -> np.ndarray:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if focal_length_m == 0:
        raise ValueError("focal_length_m must be non-zero")

    k = 2.0 * np.pi / wavelength_m
    phase = -k * (grid.x_m**2 + grid.y_m**2) / (2.0 * focal_length_m)

    return np.exp(1j * phase).astype(np.complex128)


def prism_phase(
    grid: SamplingGrid,
    wavelength_m: float,
    refractive_index: float,
    alpha_x_rad: float = 0.0,
    alpha_y_rad: float = 0.0,
) -> np.ndarray:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if refractive_index <= 0:
        raise ValueError("refractive_index must be positive")

    k = 2.0 * np.pi / wavelength_m
    phase = -k * (refractive_index - 1.0) * (
        alpha_x_rad * grid.x_m + alpha_y_rad * grid.y_m
    )

    return np.exp(1j * phase).astype(np.complex128)


def sinusoidal_grating_screen(
    grid: SamplingGrid,
    spatial_frequency_per_m: float,
    modulation: float = 0.5,
    bias: float = 0.5,
    phase_rad: float = 0.0,
    axis: Literal["x", "y"] = "x",
) -> np.ndarray:
    if spatial_frequency_per_m <= 0:
        raise ValueError("spatial_frequency_per_m must be positive")
    if modulation < 0:
        raise ValueError("modulation must be non-negative")

    if axis == "x":
        coordinate = grid.x_m
    elif axis == "y":
        coordinate = grid.y_m
    else:
        raise ValueError("axis must be 'x' or 'y'")

    transmittance = bias + modulation * np.cos(
        2.0 * np.pi * spatial_frequency_per_m * coordinate + phase_rad
    )

    return transmittance.astype(np.complex128)


def binary_grating_screen(
    grid: SamplingGrid,
    period_m: float,
    duty_cycle: float = 0.5,
    axis: Literal["x", "y"] = "x",
) -> np.ndarray:
    if period_m <= 0:
        raise ValueError("period_m must be positive")
    if not 0.0 < duty_cycle < 1.0:
        raise ValueError("duty_cycle must be between 0 and 1")

    if axis == "x":
        coordinate = grid.x_m
    elif axis == "y":
        coordinate = grid.y_m
    else:
        raise ValueError("axis must be 'x' or 'y'")

    phase_in_period = np.mod(coordinate + period_m / 2.0, period_m)
    mask = phase_in_period < duty_cycle * period_m

    return mask.astype(np.complex128)


def angular_spectrum_transfer_function(
    sample_count: int,
    spacing_m: float,
    wavelength_m: float,
    distance_m: float,
    evanescent: EvanescentMode = "decay",
) -> np.ndarray:
    if sample_count <= 1:
        raise ValueError("sample_count must be greater than 1")
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")

    fx = np.fft.fftshift(np.fft.fftfreq(sample_count, d=spacing_m))
    fy = np.fft.fftshift(np.fft.fftfreq(sample_count, d=spacing_m))
    fx_grid, fy_grid = np.meshgrid(fx, fy, indexing="xy")

    k = 2.0 * np.pi / wavelength_m
    argument = 1.0 - (wavelength_m * fx_grid) ** 2 - (wavelength_m * fy_grid) ** 2

    transfer = np.empty_like(argument, dtype=np.complex128)

    propagating = argument >= 0.0
    transfer[propagating] = np.exp(
        1j * k * distance_m * np.sqrt(argument[propagating])
    )

    evanescent_mask = ~propagating
    if evanescent == "decay":
        transfer[evanescent_mask] = np.exp(
            -k * abs(distance_m) * np.sqrt(-argument[evanescent_mask])
        )
    elif evanescent == "zero":
        transfer[evanescent_mask] = 0.0
    else:
        raise ValueError("evanescent must be 'decay' or 'zero'")

    return transfer


def angular_spectrum_propagate(
    field: np.ndarray,
    wavelength_m: float,
    spacing_m: float,
    distance_m: float,
    evanescent: EvanescentMode = "decay",
) -> np.ndarray:
    field = validate_square_complex_field(field)

    transfer = angular_spectrum_transfer_function(
        sample_count=field.shape[0],
        spacing_m=spacing_m,
        wavelength_m=wavelength_m,
        distance_m=distance_m,
        evanescent=evanescent,
    )

    spectrum = fft2_centered(field)
    propagated_spectrum = spectrum * transfer

    return ifft2_centered(propagated_spectrum)


def fresnel_transfer_function(
    sample_count: int,
    spacing_m: float,
    wavelength_m: float,
    distance_m: float,
) -> np.ndarray:
    if sample_count <= 1:
        raise ValueError("sample_count must be greater than 1")
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")

    fx = np.fft.fftshift(np.fft.fftfreq(sample_count, d=spacing_m))
    fy = np.fft.fftshift(np.fft.fftfreq(sample_count, d=spacing_m))
    fx_grid, fy_grid = np.meshgrid(fx, fy, indexing="xy")

    k = 2.0 * np.pi / wavelength_m

    return np.exp(1j * k * distance_m) * np.exp(
        -1j * np.pi * wavelength_m * distance_m * (fx_grid**2 + fy_grid**2)
    )


def fresnel_propagate(
    field: np.ndarray,
    wavelength_m: float,
    spacing_m: float,
    distance_m: float,
) -> np.ndarray:
    field = validate_square_complex_field(field)

    transfer = fresnel_transfer_function(
        sample_count=field.shape[0],
        spacing_m=spacing_m,
        wavelength_m=wavelength_m,
        distance_m=distance_m,
    )

    spectrum = fft2_centered(field)
    propagated_spectrum = spectrum * transfer

    return ifft2_centered(propagated_spectrum)


def fraunhofer_spectrum(field: np.ndarray) -> np.ndarray:
    field = validate_square_complex_field(field)
    return fft2_centered(field)


def fraunhofer_intensity(field: np.ndarray) -> np.ndarray:
    spectrum = fraunhofer_spectrum(field)
    return normalize_peak(intensity(spectrum))


def far_field_intensity_from_aperture(aperture_field: np.ndarray) -> np.ndarray:
    return fraunhofer_intensity(aperture_field)


def psf_from_pupil(pupil_field: np.ndarray) -> np.ndarray:
    return far_field_intensity_from_aperture(pupil_field)


def otf_from_psf(psf: np.ndarray) -> np.ndarray:
    psf_array = np.asarray(psf, dtype=float)

    if psf_array.ndim != 2:
        raise ValueError("psf must be a 2D array")
    if psf_array.shape[0] != psf_array.shape[1]:
        raise ValueError("psf must be a square 2D array")

    otf = fft2_centered(psf_array.astype(np.complex128))
    center = tuple(size // 2 for size in otf.shape)
    center_value = otf[center]

    if abs(center_value) == 0:
        return otf

    return otf / center_value


def mtf_from_psf(psf: np.ndarray) -> np.ndarray:
    otf = otf_from_psf(psf)
    return normalize_peak(np.abs(otf))


def make_circular_frequency_filter(
    grid: SamplingGrid,
    cutoff_frequency_per_m: float,
) -> np.ndarray:
    if cutoff_frequency_per_m <= 0:
        raise ValueError("cutoff_frequency_per_m must be positive")

    radius = np.sqrt(grid.fx_per_m**2 + grid.fy_per_m**2)
    mask = radius <= cutoff_frequency_per_m

    return mask.astype(np.complex128)


def make_annular_frequency_filter(
    grid: SamplingGrid,
    low_cutoff_per_m: float,
    high_cutoff_per_m: float,
) -> np.ndarray:
    if low_cutoff_per_m < 0:
        raise ValueError("low_cutoff_per_m must be non-negative")
    if high_cutoff_per_m <= low_cutoff_per_m:
        raise ValueError("high_cutoff_per_m must be greater than low_cutoff_per_m")

    radius = np.sqrt(grid.fx_per_m**2 + grid.fy_per_m**2)
    mask = (radius >= low_cutoff_per_m) & (radius <= high_cutoff_per_m)

    return mask.astype(np.complex128)


def make_directional_frequency_filter(
    grid: SamplingGrid,
    angle_rad: float,
    half_width_rad: float,
) -> np.ndarray:
    if half_width_rad <= 0:
        raise ValueError("half_width_rad must be positive")

    frequency_angle = np.arctan2(grid.fy_per_m, grid.fx_per_m)

    delta = np.angle(np.exp(1j * (frequency_angle - angle_rad)))
    opposite_delta = np.angle(np.exp(1j * (frequency_angle - angle_rad - np.pi)))

    mask = (np.abs(delta) <= half_width_rad) | (np.abs(opposite_delta) <= half_width_rad)

    return mask.astype(np.complex128)


def coherent_imaging(
    object_field: np.ndarray,
    pupil_or_filter: np.ndarray,
) -> dict[str, np.ndarray]:
    object_field = validate_square_complex_field(object_field)
    pupil_or_filter = validate_square_complex_field(pupil_or_filter)

    if object_field.shape != pupil_or_filter.shape:
        raise ValueError("object_field and pupil_or_filter must have the same shape")

    spectrum = fft2_centered(object_field)
    filtered_spectrum = spectrum * pupil_or_filter
    image_field = ifft2_centered(filtered_spectrum)
    image_intensity = intensity(image_field)

    return {
        "object_field": object_field,
        "spectrum": spectrum,
        "filtered_spectrum": filtered_spectrum,
        "image_field": image_field,
        "image_intensity": image_intensity,
    }


def spatial_filter(
    field: np.ndarray,
    grid: SamplingGrid,
    filter_mask: np.ndarray,
) -> np.ndarray:
    field = validate_square_complex_field(field)
    filter_mask = validate_square_complex_field(filter_mask)

    if field.shape != filter_mask.shape:
        raise ValueError("field and filter_mask must have the same shape")
    if field.shape != grid.x_m.shape:
        raise ValueError("field and grid must have the same shape")

    return ifft2_centered(fft2_centered(field) * filter_mask)


def fourier_plane_coordinates(
    grid: SamplingGrid,
    wavelength_m: float,
    focal_length_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if focal_length_m == 0:
        raise ValueError("focal_length_m must be non-zero")

    x_f_m = wavelength_m * focal_length_m * grid.fx_per_m
    y_f_m = wavelength_m * focal_length_m * grid.fy_per_m

    return x_f_m, y_f_m


def grating_order_angles(
    period_m: float,
    wavelength_m: float,
    max_order: int,
) -> dict[int, float]:
    if period_m <= 0:
        raise ValueError("period_m must be positive")
    if wavelength_m <= 0:
        raise ValueError("wavelength_m must be positive")
    if max_order < 0:
        raise ValueError("max_order must be non-negative")

    angles: dict[int, float] = {}

    for order in range(-max_order, max_order + 1):
        argument = order * wavelength_m / period_m

        if abs(argument) <= 1.0:
            angles[order] = float(np.arcsin(argument))

    return angles


def binary_grating_fourier_coefficients(
    period_m: float,
    slit_width_m: float,
    orders: np.ndarray,
) -> np.ndarray:
    if period_m <= 0:
        raise ValueError("period_m must be positive")
    if slit_width_m <= 0:
        raise ValueError("slit_width_m must be positive")
    if slit_width_m > period_m:
        raise ValueError("slit_width_m must not exceed period_m")

    order_array = np.asarray(orders, dtype=float)
    duty = slit_width_m / period_m

    coefficients = duty * np.sinc(order_array * duty)

    return coefficients.astype(np.complex128)