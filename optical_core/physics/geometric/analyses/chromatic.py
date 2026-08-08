# 色差和纵向像差分析。
# 计算轴向色差、二级光谱、不同波长焦点曲线、纵向球差、横向球差以及球色差。
from __future__ import annotations

from typing import Any
import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.physics.geometric.analyses._native_helpers import (
    AnalysisResult,
    C_LINE_NM,
    F_LINE_NM,
    focus_z_from_terminal,
    finite_positive,
    trace_custom_rays,
)
from optical_core.physics.geometric.analyses.first_order import paraxial_focus_position_mm


def axial_chromatic_aberration_mm(
    system: SequentialOpticalSystem,
    *,
    wavelength_f_nm: float = F_LINE_NM,
    wavelength_c_nm: float = C_LINE_NM,
    collimated: bool = True,
) -> float:
    return float(
        paraxial_focus_position_mm(system, wavelength_f_nm, collimated=collimated)
        - paraxial_focus_position_mm(system, wavelength_c_nm, collimated=collimated)
    )


def secondary_spectrum_mm(
    system: SequentialOpticalSystem,
    *,
    reference_wavelength_nm: float | None = None,
    wavelength_f_nm: float = F_LINE_NM,
    wavelength_c_nm: float = C_LINE_NM,
    collimated: bool = True,
) -> float:
    reference = float(reference_wavelength_nm or system.wavelength_nm)
    focus_f = paraxial_focus_position_mm(system, wavelength_f_nm, collimated=collimated)
    focus_c = paraxial_focus_position_mm(system, wavelength_c_nm, collimated=collimated)
    focus_ref = paraxial_focus_position_mm(system, reference, collimated=collimated)
    return float(focus_ref - 0.5 * (focus_f + focus_c))


def chromatic_focus_curve_mm(
    system: SequentialOpticalSystem,
    wavelengths_nm: np.ndarray | None = None,
    *,
    collimated: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    wavelengths = np.asarray(
        np.linspace(430.0, 700.0, 31) if wavelengths_nm is None else wavelengths_nm,
        dtype=float,
    )
    wavelengths = wavelengths[np.isfinite(wavelengths) & (wavelengths > 0.0)]
    if wavelengths.size < 2:
        wavelengths = np.asarray([F_LINE_NM, float(system.wavelength_nm), C_LINE_NM], dtype=float)
    focus = np.asarray(
        [paraxial_focus_position_mm(system, float(w), collimated=collimated) for w in wavelengths],
        dtype=float,
    )
    return wavelengths, focus


def spherical_aberration_profile_mm(
    system: SequentialOpticalSystem,
    wavelength_nm: float | None = None,
    *,
    samples: int = 41,
    pupil_radius_mm: float | None = None,
    collimated: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    wl = float(wavelength_nm or system.wavelength_nm)
    count = max(5, int(samples))
    marginal = finite_positive(pupil_radius_mm, system.pupil_radius_mm)
    paraxial_focus = paraxial_focus_position_mm(system, wl, collimated=collimated)
    rho = np.linspace(0.0, 1.0, count)
    pupil_x = rho * marginal
    pupil_y = np.zeros_like(pupil_x)
    trace = trace_custom_rays(
        system,
        pupil_x,
        pupil_y,
        wavelength_nm=wl,
        propagate_to_image=False,
    )
    points = np.asarray(trace.final_positions_mm, dtype=float)
    directions = np.asarray(trace.final_directions, dtype=float)
    valid = np.asarray(trace.valid_mask, dtype=bool)
    longitudinal = np.full(count, np.nan, dtype=float)
    transverse = np.full(count, np.nan, dtype=float)
    focus_valid = valid & np.isfinite(points).all(axis=1) & np.isfinite(directions).all(axis=1)
    for i in range(count):
        if not focus_valid[i]:
            continue
        focus_z = focus_z_from_terminal(points[i], directions[i], transverse_axis=0)
        longitudinal[i] = focus_z - paraxial_focus if np.isfinite(focus_z) else np.nan
        if abs(directions[i, 2]) > 1.0e-14:
            distance = (paraxial_focus - points[i, 2]) / directions[i, 2]
            image_point = points[i] + distance * directions[i]
            transverse[i] = image_point[0]
    if count:
        longitudinal[0] = 0.0
        transverse[0] = 0.0
    return rho, longitudinal, transverse, float(paraxial_focus), float(marginal)


def longitudinal_spherical_aberration_mm(
    system: SequentialOpticalSystem,
    wavelength_nm: float | None = None,
    *,
    pupil_radius_mm: float | None = None,
    collimated: bool = True,
) -> float:
    _, longitudinal, _, _, _ = spherical_aberration_profile_mm(
        system,
        wavelength_nm,
        samples=11,
        pupil_radius_mm=pupil_radius_mm,
        collimated=collimated,
    )
    finite = longitudinal[np.isfinite(longitudinal)]
    return float(finite[-1]) if finite.size else float("nan")


def spherochromatism_mm(
    system: SequentialOpticalSystem,
    *,
    wavelength_f_nm: float = F_LINE_NM,
    wavelength_c_nm: float = C_LINE_NM,
    pupil_radius_mm: float | None = None,
    collimated: bool = True,
) -> float:
    return float(
        longitudinal_spherical_aberration_mm(system, wavelength_f_nm, pupil_radius_mm=pupil_radius_mm, collimated=collimated)
        - longitudinal_spherical_aberration_mm(system, wavelength_c_nm, pupil_radius_mm=pupil_radius_mm, collimated=collimated)
    )


def longitudinal_aberration_profiles(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = dict(options or {})
    wavelengths = np.asarray(opts.get("wavelengths_nm", [F_LINE_NM, system.wavelength_nm, C_LINE_NM]), dtype=float)
    samples = int(opts.get("samples", 41))
    curves = []
    focus_values = []
    for wavelength in wavelengths:
        rho, longitudinal, transverse, paraxial_focus, marginal = spherical_aberration_profile_mm(
            system,
            float(wavelength),
            samples=samples,
            pupil_radius_mm=opts.get("pupil_radius_mm", None),
            collimated=bool(opts.get("collimated", True)),
        )
        curves.append(
            {
                "wavelength_nm": float(wavelength),
                "rho": rho,
                "longitudinal_um": longitudinal * 1000.0,
                "transverse_um": transverse * 1000.0,
                "paraxial_focus_z_mm": float(paraxial_focus),
                "marginal_radius_mm": float(marginal),
                "absolute_focus_mm": paraxial_focus + longitudinal,
            }
        )
        focus_values.append(paraxial_focus)
    focus_arr = np.asarray(focus_values, dtype=float)
    reference_focus = paraxial_focus_position_mm(system, system.wavelength_nm, collimated=bool(opts.get("collimated", True)))
    return {
        "curves": curves,
        "wavelengths_nm": wavelengths,
        "paraxial_focus_z_mm": focus_arr,
        "relative_focus_um": (focus_arr - reference_focus) * 1000.0,
        "reference_wavelength_nm": float(system.wavelength_nm),
        "reference_focus_z_mm": float(reference_focus),
    }


def evaluate_chromatic(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> AnalysisResult:
    opts = dict(options or {})
    wavelengths, focus = chromatic_focus_curve_mm(
        system,
        opts.get("wavelengths_nm", None),
        collimated=bool(opts.get("collimated", True)),
    )
    rho, lsa, tsa, paraxial_focus, marginal = spherical_aberration_profile_mm(
        system,
        opts.get("wavelength_nm", system.wavelength_nm),
        samples=int(opts.get("samples", 41)),
        pupil_radius_mm=opts.get("pupil_radius_mm", None),
        collimated=bool(opts.get("collimated", True)),
    )
    metrics = {
        "axial_chromatic_aberration_mm": axial_chromatic_aberration_mm(system, collimated=bool(opts.get("collimated", True))),
        "secondary_spectrum_mm": secondary_spectrum_mm(system, collimated=bool(opts.get("collimated", True))),
        "spherochromatism_mm": spherochromatism_mm(system, collimated=bool(opts.get("collimated", True))),
        "longitudinal_spherical_aberration_mm": float(lsa[np.isfinite(lsa)][-1]) if np.any(np.isfinite(lsa)) else float("nan"),
        "paraxial_focus_z_mm": float(paraxial_focus),
        "marginal_radius_mm": float(marginal),
    }
    arrays = {
        "chromatic_wavelengths_nm": wavelengths.tolist(),
        "chromatic_focus_mm": focus.tolist(),
        "chromatic_relative_focus_um": ((focus - paraxial_focus_position_mm(system, system.wavelength_nm)) * 1000.0).tolist(),
        "spherical_rho": rho.tolist(),
        "longitudinal_spherical_um": (lsa * 1000.0).tolist(),
        "transverse_spherical_um": (tsa * 1000.0).tolist(),
    }
    return AnalysisResult(metrics=metrics, arrays=arrays, metadata={"chromatic_done": True, "optical_axis": "+z"})

__all__ = [
    "axial_chromatic_aberration_mm",
    "chromatic_focus_curve_mm",
    "evaluate_chromatic",
    "longitudinal_aberration_profiles",
    "longitudinal_spherical_aberration_mm",
    "secondary_spectrum_mm",
    "spherical_aberration_profile_mm",
    "spherochromatism_mm",
]
