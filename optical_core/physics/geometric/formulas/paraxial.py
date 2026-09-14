# 一阶近轴光学公式。

from __future__ import annotations

import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.domain.system import SequentialOpticalSystem

NM_TO_MM = 1.0e-6


def translation_matrix(distance_mm: float, refractive_index: float = 1.0) -> np.ndarray:
    return np.array([[1.0, float(distance_mm) / float(refractive_index)], [0.0, 1.0]], dtype=float)


def meridional_curvature(surface: OpticalSurface, axis: str | None = None) -> float:
    """Return curvature seen by an x/y paraxial meridian.

    A cylindrical surface has zero power along its cylinder axis and full power
    perpendicular to it.  For an oblique cylinder this is the diagonal part of
    the exact 2-D power tensor; the full ray tracer retains the cross coupling.
    ``axis=None`` preserves the legacy powered-meridian result.
    """
    curvature = surface.curvature
    if not surface.is_cylindrical or axis is None:
        return curvature
    name = str(axis).strip().lower()
    if name not in {"x", "y"}:
        raise ValueError("近轴方向必须是 x 或 y。")
    angle = np.deg2rad(float(surface.cylinder_axis_deg))
    power_axis = np.array([-np.sin(angle), np.cos(angle)], dtype=float)
    component = float(power_axis[0] if name == "x" else power_axis[1])
    return float(curvature * component * component)


def refraction_matrix(
    surface: OpticalSurface,
    n_before: float,
    n_after: float,
    *,
    axis: str | None = None,
) -> np.ndarray:
    power = (float(n_after) - float(n_before)) * meridional_curvature(surface, axis)
    return np.array([[1.0, 0.0], [-power, 1.0]], dtype=float)


def matrix_from_first_to_after_last(
    system: SequentialOpticalSystem,
    wavelength_nm: float | None = None,
    *,
    axis: str | None = None,
) -> np.ndarray:
    wavelength = float(wavelength_nm or system.wavelength_nm)
    matrix = np.eye(2)
    for index, surface in enumerate(system.surfaces):
        n_before = system.material_index(surface.material_before, wavelength)
        n_after = system.material_index(surface.material_after, wavelength)
        matrix = refraction_matrix(surface, n_before, n_after, axis=axis) @ matrix
        if index < len(system.surfaces) - 1:
            matrix = translation_matrix(surface.distance_to_next_mm, n_after) @ matrix
    return matrix


def effective_focal_length_mm(
    system: SequentialOpticalSystem,
    wavelength_nm: float | None = None,
    *,
    axis: str | None = None,
) -> float:
    wavelength = float(wavelength_nm or system.wavelength_nm)
    c_value = float(matrix_from_first_to_after_last(system, wavelength, axis=axis)[1, 0])
    n_output = system.material_index(system.surfaces[-1].material_after, wavelength)
    return float("inf") if abs(c_value) < 1.0e-15 else float(abs(-n_output / c_value))


def q_from_waist(waist_mm: float, wavelength_mm: float) -> complex:
    if waist_mm <= 0 or wavelength_mm <= 0:
        raise ValueError("束腰半径和波长必须大于 0。")
    return 1j * np.pi * float(waist_mm) ** 2 / float(wavelength_mm)


def propagate_q(matrix: np.ndarray, q_parameter: complex) -> complex:
    matrix = np.asarray(matrix, dtype=float)
    denominator = matrix[1, 0] * q_parameter + matrix[1, 1]
    if abs(denominator) < 1.0e-15:
        raise ZeroDivisionError("高斯光束传播矩阵产生奇异 Q 参数。")
    return (matrix[0, 0] * q_parameter + matrix[0, 1]) / denominator


def beam_size_and_radius(q_parameter: complex, wavelength_mm: float, refractive_index: float = 1.0) -> tuple[float, float]:
    inverse_q = 1.0 / q_parameter
    imaginary = float(np.imag(inverse_q))
    if imaginary >= 0:
        raise ValueError("Q 参数无效：Im(1/Q) 必须为负。")
    beam_radius = float(np.sqrt(-float(wavelength_mm) / (np.pi * imaginary)))
    real = float(np.real(inverse_q))
    physical_curvature = float("inf") if abs(real) < 1.0e-15 else float(float(refractive_index) / real)
    return beam_radius, physical_curvature
