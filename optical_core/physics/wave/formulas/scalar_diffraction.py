from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class DiffractionGrid:


    x_mm: np.ndarray
    y_mm: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.x_mm.shape


@dataclass(frozen=True)
class ScalarField:


    grid: DiffractionGrid
    complex_amplitude: np.ndarray
    wavelength_nm: float
    aperture_type: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ScalarDiffractionResult:
    """标量衍射计算结果。"""

    input_grid: DiffractionGrid
    output_grid: DiffractionGrid
    complex_amplitude: np.ndarray
    amplitude: np.ndarray
    phase_rad: np.ndarray
    intensity: np.ndarray
    wavelength_nm: float
    propagation_distance_mm: float
    aperture_type: str
    method: str
    normalized: bool
    metadata: dict[str, Any]


def _validate_positive(name: str, value: float) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite.")
    return value


def _validate_grid_size(grid_size: int) -> int:
    if not isinstance(grid_size, int):
        raise TypeError("grid_size must be an integer.")
    if grid_size < 5:
        raise ValueError("grid_size must be at least 5.")
    if grid_size % 2 == 0:
        raise ValueError("grid_size must be odd so that the grid has a center sample.")
    return grid_size


def _assert_same_shape(grid: DiffractionGrid, array: np.ndarray) -> None:
    if grid.x_mm.shape != grid.y_mm.shape:
        raise ValueError("grid.x_mm and grid.y_mm must have the same shape.")
    if array.shape != grid.x_mm.shape:
        raise ValueError("complex_amplitude shape must match grid shape.")


def _axis_from_grid(grid: DiffractionGrid) -> tuple[np.ndarray, np.ndarray]:
    x_axis = np.asarray(grid.x_mm[0, :], dtype=float)
    y_axis = np.asarray(grid.y_mm[:, 0], dtype=float)

    if x_axis.size < 2 or y_axis.size < 2:
        raise ValueError("grid must contain at least two samples along each axis.")

    dx = np.diff(x_axis)
    dy = np.diff(y_axis)

    if not np.allclose(dx, dx[0]):
        raise ValueError("x axis must be uniformly sampled.")
    if not np.allclose(dy, dy[0]):
        raise ValueError("y axis must be uniformly sampled.")

    return x_axis, y_axis


def make_uniform_grid(*, grid_size: int, extent_mm: float) -> DiffractionGrid:


    grid_size = _validate_grid_size(grid_size)
    extent_mm = _validate_positive("extent_mm", extent_mm)

    axis = np.linspace(-extent_mm, extent_mm, grid_size, dtype=float)
    x_mm, y_mm = np.meshgrid(axis, axis)
    return DiffractionGrid(x_mm=x_mm, y_mm=y_mm)


def _make_field(
    *,
    grid: DiffractionGrid,
    complex_amplitude: np.ndarray,
    wavelength_nm: float,
    aperture_type: str,
    metadata: dict[str, Any],
) -> ScalarField:
    wavelength_nm = _validate_positive("wavelength_nm", wavelength_nm)
    complex_amplitude = np.asarray(complex_amplitude, dtype=np.complex128)
    _assert_same_shape(grid, complex_amplitude)

    return ScalarField(
        grid=grid,
        complex_amplitude=complex_amplitude,
        wavelength_nm=wavelength_nm,
        aperture_type=aperture_type,
        metadata=dict(metadata),
    )


def single_slit_field(
    *,
    grid: DiffractionGrid,
    slit_width_mm: float,
    wavelength_nm: float,
) -> ScalarField:


    slit_width_mm = _validate_positive("slit_width_mm", slit_width_mm)
    mask = np.abs(grid.x_mm) <= slit_width_mm / 2.0

    return _make_field(
        grid=grid,
        complex_amplitude=mask.astype(np.complex128),
        wavelength_nm=wavelength_nm,
        aperture_type="single_slit",
        metadata={
            "slit_width_mm": slit_width_mm,
            "not_physical_result": False,
        },
    )


def rectangular_aperture_field(
    *,
    grid: DiffractionGrid,
    aperture_width_mm: float,
    aperture_height_mm: float,
    wavelength_nm: float,
) -> ScalarField:
    """生成矩形孔复振幅场。"""

    aperture_width_mm = _validate_positive("aperture_width_mm", aperture_width_mm)
    aperture_height_mm = _validate_positive("aperture_height_mm", aperture_height_mm)

    mask_x = np.abs(grid.x_mm) <= aperture_width_mm / 2.0
    mask_y = np.abs(grid.y_mm) <= aperture_height_mm / 2.0
    mask = mask_x & mask_y

    return _make_field(
        grid=grid,
        complex_amplitude=mask.astype(np.complex128),
        wavelength_nm=wavelength_nm,
        aperture_type="rectangular_aperture",
        metadata={
            "aperture_width_mm": aperture_width_mm,
            "aperture_height_mm": aperture_height_mm,
            "not_physical_result": False,
        },
    )


def circular_aperture_field(
    *,
    grid: DiffractionGrid,
    aperture_diameter_mm: float,
    wavelength_nm: float,
) -> ScalarField:
    """生成圆孔复振幅场。"""

    aperture_diameter_mm = _validate_positive("aperture_diameter_mm", aperture_diameter_mm)
    radius_mm = np.sqrt(grid.x_mm**2 + grid.y_mm**2)
    mask = radius_mm <= aperture_diameter_mm / 2.0

    return _make_field(
        grid=grid,
        complex_amplitude=mask.astype(np.complex128),
        wavelength_nm=wavelength_nm,
        aperture_type="circular_aperture",
        metadata={
            "aperture_diameter_mm": aperture_diameter_mm,
            "not_physical_result": False,
        },
    )


def fraunhofer_diffraction(
    field: ScalarField,
    *,
    propagation_distance_mm: float,
    normalize: bool = True,
) -> ScalarDiffractionResult:
    """夫琅禾费标量衍射。

    这是远场近似，或者等价于透镜焦平面上的衍射分布。
    这里默认归一化峰值强度，适合做形状、相位、条纹位置验证。
    """

    propagation_distance_mm = _validate_positive(
        "propagation_distance_mm",
        propagation_distance_mm,
    )
    wavelength_mm = field.wavelength_nm * 1.0e-6

    x_axis, y_axis = _axis_from_grid(field.grid)
    dx_mm = float(x_axis[1] - x_axis[0])
    dy_mm = float(y_axis[1] - y_axis[0])

    rows, cols = field.complex_amplitude.shape

    spectrum = (
        np.fft.fftshift(
            np.fft.fft2(
                np.fft.ifftshift(field.complex_amplitude),
            ),
        )
        * dx_mm
        * dy_mm
    )

    fx = np.fft.fftshift(np.fft.fftfreq(cols, d=dx_mm))
    fy = np.fft.fftshift(np.fft.fftfreq(rows, d=dy_mm))

    output_x_axis_mm = wavelength_mm * propagation_distance_mm * fx
    output_y_axis_mm = wavelength_mm * propagation_distance_mm * fy
    output_x_mm, output_y_mm = np.meshgrid(output_x_axis_mm, output_y_axis_mm)

    complex_amplitude = spectrum.astype(np.complex128)
    raw_intensity = np.abs(complex_amplitude) ** 2
    peak_intensity = float(np.max(raw_intensity))

    if normalize and peak_intensity > 0:
        complex_amplitude = complex_amplitude / math.sqrt(peak_intensity)

    amplitude = np.abs(complex_amplitude)
    phase_rad = np.angle(complex_amplitude)
    intensity = amplitude**2

    metadata = {
        **field.metadata,
        "method": "fraunhofer_fft",
        "approximation": "far_field",
        "input_field_role": "pupil_function",
        "wavelength_nm": float(field.wavelength_nm),
        "wavelength_mm": float(wavelength_mm),
        "propagation_distance_mm": float(propagation_distance_mm),
        "input_dx_mm": dx_mm,
        "input_dy_mm": dy_mm,
        "output_x_min_mm": float(np.min(output_x_axis_mm)),
        "output_x_max_mm": float(np.max(output_x_axis_mm)),
        "output_y_min_mm": float(np.min(output_y_axis_mm)),
        "output_y_max_mm": float(np.max(output_y_axis_mm)),
        "raw_peak_intensity": peak_intensity,
        "intensity_normalized": bool(normalize),
        "omits_global_phase_and_scale": True,
        "not_physical_result": False,
    }

    return ScalarDiffractionResult(
        input_grid=field.grid,
        output_grid=DiffractionGrid(x_mm=output_x_mm, y_mm=output_y_mm),
        complex_amplitude=complex_amplitude,
        amplitude=amplitude,
        phase_rad=phase_rad,
        intensity=intensity,
        wavelength_nm=field.wavelength_nm,
        propagation_distance_mm=propagation_distance_mm,
        aperture_type=field.aperture_type,
        method="fraunhofer_fft",
        normalized=normalize,
        metadata=metadata,
    )


def single_slit_fraunhofer(
    *,
    grid_size: int,
    input_extent_mm: float,
    slit_width_mm: float,
    wavelength_nm: float,
    propagation_distance_mm: float,
    normalize: bool = True,
) -> ScalarDiffractionResult:
    grid = make_uniform_grid(grid_size=grid_size, extent_mm=input_extent_mm)
    field = single_slit_field(
        grid=grid,
        slit_width_mm=slit_width_mm,
        wavelength_nm=wavelength_nm,
    )
    return fraunhofer_diffraction(
        field,
        propagation_distance_mm=propagation_distance_mm,
        normalize=normalize,
    )


def rectangular_aperture_fraunhofer(
    *,
    grid_size: int,
    input_extent_mm: float,
    aperture_width_mm: float,
    aperture_height_mm: float,
    wavelength_nm: float,
    propagation_distance_mm: float,
    normalize: bool = True,
) -> ScalarDiffractionResult:
    grid = make_uniform_grid(grid_size=grid_size, extent_mm=input_extent_mm)
    field = rectangular_aperture_field(
        grid=grid,
        aperture_width_mm=aperture_width_mm,
        aperture_height_mm=aperture_height_mm,
        wavelength_nm=wavelength_nm,
    )
    return fraunhofer_diffraction(
        field,
        propagation_distance_mm=propagation_distance_mm,
        normalize=normalize,
    )


def circular_aperture_fraunhofer(
    *,
    grid_size: int,
    input_extent_mm: float,
    aperture_diameter_mm: float,
    wavelength_nm: float,
    propagation_distance_mm: float,
    normalize: bool = True,
) -> ScalarDiffractionResult:
    grid = make_uniform_grid(grid_size=grid_size, extent_mm=input_extent_mm)
    field = circular_aperture_field(
        grid=grid,
        aperture_diameter_mm=aperture_diameter_mm,
        wavelength_nm=wavelength_nm,
    )
    return fraunhofer_diffraction(
        field,
        propagation_distance_mm=propagation_distance_mm,
        normalize=normalize,
    )