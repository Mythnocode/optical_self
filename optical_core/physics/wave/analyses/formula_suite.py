from __future__ import annotations

import math
from typing import Any

import numpy as np


def evaluate_grating(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.grating import (
        angular_dispersion_rad_per_nm,
        fraunhofer_grating_intensity,
        grating_orders,
        make_theta_axis,
        resolving_power,
        spectral_resolution_nm,
    )

    wavelength_nm = float(options.get("wavelength_nm", 550.0))
    slit_width_mm = float(options.get("slit_width_mm", 0.01))
    period_mm = float(options.get("period_mm", 0.02))
    slit_count = int(options.get("slit_count", 20))
    incident_angle_rad = float(options.get("incident_angle_rad", 0.0))
    theta_min_rad = float(options.get("theta_min_rad", -0.08))
    theta_max_rad = float(options.get("theta_max_rad", 0.08))
    sample_count = _odd_int(options.get("sample_count", 201), minimum=5)

    theta = make_theta_axis(
        theta_min_rad=theta_min_rad,
        theta_max_rad=theta_max_rad,
        sample_count=sample_count,
    )
    result = fraunhofer_grating_intensity(
        theta_rad=theta,
        wavelength_nm=wavelength_nm,
        slit_width_mm=slit_width_mm,
        period_mm=period_mm,
        slit_count=slit_count,
        incident_angle_rad=incident_angle_rad,
        normalize=bool(options.get("normalize", True)),
    )
    orders = grating_orders(
        wavelength_nm=wavelength_nm,
        period_mm=period_mm,
        incident_angle_rad=incident_angle_rad,
        max_order=options.get("max_order", None),
    )
    default_order = int(options.get("order", 1))
    metrics: dict[str, Any] = {
        "grating_peak_intensity": float(np.max(result.intensity)) if result.intensity.size else 0.0,
        "grating_total_intensity_a.u.": float(np.trapezoid(result.intensity, result.theta_rad)) if result.intensity.size else 0.0,
        "grating_order_count": int(len(orders)),
        "grating_resolving_power": int(resolving_power(order=abs(default_order), slit_count=slit_count)) if default_order != 0 else 0,
    }
    try:
        metrics["grating_angular_dispersion_rad_per_nm"] = float(
            angular_dispersion_rad_per_nm(
                order=default_order,
                wavelength_nm=wavelength_nm,
                period_mm=period_mm,
                incident_angle_rad=incident_angle_rad,
            )
        )
    except Exception:
        metrics["grating_angular_dispersion_rad_per_nm"] = 0.0
    try:
        metrics["grating_spectral_resolution_nm"] = float(
            spectral_resolution_nm(
                wavelength_nm=wavelength_nm,
                order=abs(default_order),
                slit_count=slit_count,
            )
        ) if default_order != 0 else 0.0
    except Exception:
        metrics["grating_spectral_resolution_nm"] = 0.0

    return {
        "metrics": metrics,
        "arrays": {
            "grating_theta_rad": result.theta_rad.tolist(),
            "grating_intensity": result.intensity.tolist(),
            "grating_single_slit_intensity": result.single_slit_intensity.tolist(),
            "grating_multi_slit_intensity": result.multi_slit_intensity.tolist(),
            "grating_orders": _jsonable(orders),
        },
        "metadata": {"analysis": "grating", **dict(result.metadata)},
    }


def evaluate_material_index(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.materials import (
        CauchyMaterial,
        ConstantIndexMaterial,
        SellmeierMaterial,
        air_material,
        absorption_coefficient_per_mm,
        estimate_group_index,
        fused_silica_sellmeier,
        intensity_transmission_through_material,
    )

    wavelength_nm = float(options.get("wavelength_nm", 550.0))
    material_name = str(options.get("material", options.get("material_name", "fused_silica"))).lower()
    thickness_mm = float(options.get("thickness_mm", 1.0))

    if material_name in {"air", "vacuum"}:
        material = air_material()
    elif material_name in {"fused_silica", "silica", "sio2"}:
        material = fused_silica_sellmeier()
    elif material_name == "constant":
        material = ConstantIndexMaterial(float(options.get("n", 1.5)), float(options.get("k", 0.0)))
    elif material_name == "cauchy":
        material = CauchyMaterial(
            a=float(options.get("cauchy_a", 1.5)),
            b=float(options.get("cauchy_b", 0.004)),
            c=float(options.get("cauchy_c", 0.0)),
        )
    elif material_name == "sellmeier":
        material = SellmeierMaterial(
            b1=float(options.get("b1", 0.6961663)),
            b2=float(options.get("b2", 0.4079426)),
            b3=float(options.get("b3", 0.8974794)),
            c1=float(options.get("c1", 0.0684043**2)),
            c2=float(options.get("c2", 0.1162414**2)),
            c3=float(options.get("c3", 9.896161**2)),
        )
    else:
        # 数值字符串也允许直接作为常折射率材料。
        try:
            material = ConstantIndexMaterial(float(material_name), 0.0)
        except ValueError:
            material = fused_silica_sellmeier()

    n_complex = complex(material.n_complex(wavelength_nm)) if hasattr(material, "n_complex") else complex(material.n(wavelength_nm))
    alpha = float(absorption_coefficient_per_mm(material, wavelength_nm=wavelength_nm))
    transmission = float(
        intensity_transmission_through_material(
            material,
            wavelength_nm=wavelength_nm,
            thickness_mm=thickness_mm,
        )
    )
    group_index = float(estimate_group_index(material, wavelength_nm=wavelength_nm))

    return {
        "metrics": {
            "material_refractive_index": float(n_complex.real),
            "material_extinction_coefficient": float(n_complex.imag),
            "material_absorption_coefficient_per_mm": alpha,
            "material_intensity_transmission": transmission,
            "material_group_index": group_index,
        },
        "metadata": {
            "analysis": "material_index",
            "material": material_name,
            "wavelength_nm": wavelength_nm,
            "thickness_mm": thickness_mm,
        },
    }


def evaluate_fresnel_interface(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.interfaces import (
        brewster_angle_rad,
        critical_angle_rad,
        fresnel_coefficients,
        fresnel_unpolarized_reflectance,
        fresnel_unpolarized_transmittance,
        normal_incidence_reflectance,
    )

    n1 = float(options.get("n1", 1.0))
    n2 = float(options.get("n2", 1.5))
    wavelength_nm = float(options.get("wavelength_nm", 550.0))
    incident_angle_rad = float(options.get("incident_angle_rad", 0.0))

    s = fresnel_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        polarization="s",
        wavelength_nm=wavelength_nm,
    )
    p = fresnel_coefficients(
        n1=n1,
        n2=n2,
        incident_angle_rad=incident_angle_rad,
        polarization="p",
        wavelength_nm=wavelength_nm,
    )
    critical = critical_angle_rad(n1=n1, n2=n2, wavelength_nm=wavelength_nm)

    return {
        "metrics": {
            "fresnel_s_reflectance": float(s.reflectance),
            "fresnel_s_transmittance": float(s.transmittance),
            "fresnel_p_reflectance": float(p.reflectance),
            "fresnel_p_transmittance": float(p.transmittance),
            "fresnel_unpolarized_reflectance": float(
                fresnel_unpolarized_reflectance(
                    n1=n1,
                    n2=n2,
                    incident_angle_rad=incident_angle_rad,
                    wavelength_nm=wavelength_nm,
                )
            ),
            "fresnel_unpolarized_transmittance": float(
                fresnel_unpolarized_transmittance(
                    n1=n1,
                    n2=n2,
                    incident_angle_rad=incident_angle_rad,
                    wavelength_nm=wavelength_nm,
                )
            ),
            "fresnel_normal_reflectance": float(normal_incidence_reflectance(n1=n1, n2=n2, wavelength_nm=wavelength_nm)),
            "fresnel_brewster_angle_rad": float(brewster_angle_rad(n1=n1, n2=n2, wavelength_nm=wavelength_nm)),
            "fresnel_critical_angle_rad": float(critical) if critical is not None else float("nan"),
            "fresnel_total_internal_reflection": bool(s.total_internal_reflection or p.total_internal_reflection),
        },
        "metadata": {"analysis": "fresnel_interface", "wavelength_nm": wavelength_nm},
    }


def evaluate_thin_film(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.thin_film import (
        two_beam_reflected_thin_film,
        two_beam_transmitted_thin_film,
        wedge_reflected_intensity,
    )

    n_incident = float(options.get("n_incident", 1.0))
    n_film = float(options.get("n_film", 1.38))
    n_exit = float(options.get("n_exit", 1.52))
    thickness_mm = float(options.get("thickness_mm", 0.0001))
    wavelength_nm = float(options.get("wavelength_nm", 550.0))
    incident_angle_rad = float(options.get("incident_angle_rad", 0.0))
    polarization = str(options.get("polarization", "s"))

    reflected = two_beam_reflected_thin_film(
        n_incident=n_incident,
        n_film=n_film,
        n_exit=n_exit,
        thickness_mm=thickness_mm,
        wavelength_nm=wavelength_nm,
        incident_angle_rad=incident_angle_rad,
        polarization=polarization,
    )
    transmitted = two_beam_transmitted_thin_film(
        n_incident=n_incident,
        n_film=n_film,
        n_exit=n_exit,
        thickness_mm=thickness_mm,
        wavelength_nm=wavelength_nm,
        incident_angle_rad=incident_angle_rad,
        polarization=polarization,
    )

    sample_count = int(options.get("sample_count", 101))
    coordinate_mm = np.linspace(0.0, float(options.get("wedge_length_mm", 1.0)), max(sample_count, 5))
    try:
        wedge = wedge_reflected_intensity(
            coordinate_mm=coordinate_mm,
            n_incident=n_incident,
            n_film=n_film,
            n_exit=n_exit,
            base_thickness_mm=float(options.get("base_thickness_mm", 0.0)),
            wedge_angle_rad=float(options.get("wedge_angle_rad", 1.0e-4)),
            wavelength_nm=wavelength_nm,
            incident_angle_rad=incident_angle_rad,
            polarization=polarization,
        )
        arrays = {
            "thin_film_coordinate_mm": wedge.coordinate.tolist(),
            "thin_film_thickness_mm": wedge.thickness_mm.tolist(),
            "thin_film_wedge_intensity": wedge.intensity.tolist(),
        }
    except Exception:
        arrays = {}

    return {
        "metrics": {
            "thin_film_reflected_intensity": float(reflected.intensity),
            "thin_film_transmitted_intensity": float(transmitted.intensity),
            "thin_film_phase_difference_rad": float(reflected.phase_difference_rad),
            "thin_film_opd_mm": float(reflected.optical_path_difference_mm),
            "thin_film_internal_angle_rad": float(reflected.film_angle_rad),
        },
        "arrays": arrays,
        "metadata": {"analysis": "thin_film", "model": "two_beam"},
    }


def evaluate_fabry_perot(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.fabry_perot import (
        airy_transmission,
        fabry_perot_spectrum,
        finesse_from_reflectance,
        free_spectral_range_nm,
        linewidth_nm,
        resolving_power,
    )

    center_wavelength_nm = float(options.get("wavelength_nm", options.get("center_wavelength_nm", 550.0)))
    span_nm = float(options.get("span_nm", 5.0))
    sample_count = int(options.get("sample_count", 201))
    mirror_reflectance = float(options.get("mirror_reflectance", 0.9))
    cavity_length_mm = float(options.get("cavity_length_mm", 1.0))
    n_medium = float(options.get("n_medium", 1.0))
    incident_angle_rad = float(options.get("incident_angle_rad", 0.0))

    wavelengths = np.linspace(center_wavelength_nm - span_nm / 2.0, center_wavelength_nm + span_nm / 2.0, max(sample_count, 5))
    spectrum = fabry_perot_spectrum(
        wavelength_nm=wavelengths,
        cavity_length_mm=cavity_length_mm,
        mirror_reflectance=mirror_reflectance,
        n_medium=n_medium,
        internal_angle_rad=incident_angle_rad,
    )

    return {
        "metrics": {
            "fabry_perot_peak_transmission": float(np.max(spectrum.transmission)) if spectrum.transmission.size else 0.0,
            "fabry_perot_min_transmission": float(np.min(spectrum.transmission)) if spectrum.transmission.size else 0.0,
            "fabry_perot_finesse": float(finesse_from_reflectance(mirror_reflectance=mirror_reflectance)),
            "fabry_perot_fsr_nm": float(free_spectral_range_nm(center_wavelength_nm=center_wavelength_nm, cavity_length_mm=cavity_length_mm, n_medium=n_medium, internal_angle_rad=incident_angle_rad)),
            "fabry_perot_linewidth_nm": float(linewidth_nm(center_wavelength_nm=center_wavelength_nm, cavity_length_mm=cavity_length_mm, mirror_reflectance=mirror_reflectance, n_medium=n_medium, internal_angle_rad=incident_angle_rad)),
            "fabry_perot_resolving_power": float(resolving_power(center_wavelength_nm=center_wavelength_nm, cavity_length_mm=cavity_length_mm, mirror_reflectance=mirror_reflectance, n_medium=n_medium, internal_angle_rad=incident_angle_rad)),
            "fabry_perot_center_transmission": float(airy_transmission(0.0, mirror_reflectance=mirror_reflectance)),
        },
        "arrays": {
            "fabry_perot_wavelength_nm": wavelengths.tolist(),
            "fabry_perot_transmission": np.asarray(spectrum.transmission, dtype=float).tolist(),
            "fabry_perot_reflection": np.asarray(spectrum.reflection, dtype=float).tolist(),
        },
        "metadata": {"analysis": "fabry_perot"},
    }


def evaluate_fourier_transform(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.fourier_optics import (
        circular_aperture,
        fft2_centered,
        fraunhofer_intensity,
        make_sampling_grid,
        mtf_from_psf,
        normalize_peak,
        psf_from_pupil,
        rectangular_aperture,
        spatial_filter,
    )

    sample_count = int(options.get("sample_count", options.get("grid_size", 64)))
    extent_m = float(options.get("extent_m", options.get("extent_mm", 1.0) * 1.0e-3))
    aperture_type = str(options.get("aperture_type", "circular"))
    grid = make_sampling_grid(sample_count=sample_count, extent_m=extent_m)

    if aperture_type == "rectangular":
        field = rectangular_aperture(
            grid,
            width_x_m=float(options.get("aperture_width_m", 0.5 * extent_m)),
            width_y_m=float(options.get("aperture_height_m", 0.5 * extent_m)),
        ).astype(np.complex128)
    else:
        field = circular_aperture(
            sample_count=sample_count,
            extent_m=extent_m,
            diameter_m=float(options.get("aperture_diameter_m", 0.5 * extent_m)),
        ).astype(np.complex128)

    spectrum = fft2_centered(field)
    fraunhofer = normalize_peak(fraunhofer_intensity(field))
    psf = psf_from_pupil(field)
    mtf = mtf_from_psf(psf)

    return {
        "metrics": {
            "fourier_spectrum_peak": float(np.max(np.abs(spectrum))) if spectrum.size else 0.0,
            "fourier_fraunhofer_peak_normalized": float(np.max(fraunhofer)) if fraunhofer.size else 0.0,
            "fourier_psf_peak_normalized": float(np.max(psf)) if psf.size else 0.0,
            "fourier_mtf_dc": float(mtf[mtf.shape[0] // 2, mtf.shape[1] // 2]) if mtf.size else 0.0,
        },
        "arrays": {
            "fourier_x_m": grid.x_m.tolist(),
            "fourier_y_m": grid.y_m.tolist(),
            "fourier_aperture": np.real(field).tolist(),
            "fourier_spectrum_abs": np.abs(spectrum).tolist(),
            "fourier_fraunhofer_intensity": fraunhofer.tolist(),
            "fourier_psf_intensity": psf.tolist(),
            "fourier_mtf_values": mtf.tolist(),
        },
        "metadata": {"analysis": "fourier_transform", "aperture_type": aperture_type},
    }


def evaluate_birefringence(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.birefringence import (
        birefringence_delta_n,
        crystal_summary,
        effective_extraordinary_index,
        ordinary_extraordinary_intensity_split,
        quarter_wave_thickness,
        retardance_from_indices,
        waveplate_kind,
    )

    n_o = float(options.get("n_o", 1.544))
    n_e = float(options.get("n_e", 1.553))
    thickness_mm = float(options.get("thickness_mm", 0.1))
    wavelength_nm = float(options.get("wavelength_nm", 550.0))
    propagation_angle_rad = float(options.get("propagation_angle_rad", math.pi / 4.0))
    input_angle_rad = float(options.get("input_angle_rad", math.pi / 4.0))

    retardance = retardance_from_indices(max(n_o, n_e), min(n_o, n_e), thickness_mm * 1.0e-3, wavelength_nm * 1.0e-9)
    ordinary, extraordinary = ordinary_extraordinary_intensity_split(1.0, input_angle_rad)
    summary = crystal_summary(n_o=n_o, n_e=n_e, thickness_m=thickness_mm * 1.0e-3, wavelength_m=wavelength_nm * 1.0e-9)

    return {
        "metrics": {
            "birefringence_delta_n": float(birefringence_delta_n(n_o, n_e)),
            "birefringence_effective_extraordinary_index": float(effective_extraordinary_index(n_o, n_e, propagation_angle_rad)),
            "birefringence_retardance_rad": float(retardance),
            "birefringence_ordinary_fraction": float(ordinary),
            "birefringence_extraordinary_fraction": float(extraordinary),
            "birefringence_quarter_wave_thickness_mm": float(quarter_wave_thickness(n_o, n_e, wavelength_nm * 1.0e-9) * 1.0e3),
        },
        "metadata": {"analysis": "birefringence", "waveplate_kind": str(waveplate_kind(retardance)), "summary": _jsonable(summary)},
    }


def evaluate_polarization_diagnostics(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.polarization import linear_jones
    from optical_core.physics.wave.formulas.polarization_diagnostics import (
        diagnose_analyzer_scan,
        ideal_analyzer_scan_from_jones,
    )

    input_angle_rad = float(options.get("input_angle_rad", 0.0))
    amplitude = float(options.get("amplitude", 1.0))
    sample_count = int(options.get("sample_count", 181))
    jones = linear_jones(input_angle_rad, amplitude=amplitude)
    angles = np.linspace(0.0, math.pi, max(sample_count, 9))
    intensities = ideal_analyzer_scan_from_jones(jones, angles)
    diag = diagnose_analyzer_scan(angles, intensities)

    metrics = {
        "polarization_scan_visibility": float(diag.get("fit_visibility", diag.get("visibility", 0.0))),
        "polarization_scan_extinction_ratio": float(diag.get("fit_extinction_ratio", diag.get("extinction_ratio", 0.0))),
        "polarization_scan_angle_rad": float(diag.get("estimated_linear_angle_rad", 0.0)),
        "polarization_degree_linear": float(diag.get("degree_of_linear_polarization", 0.0)),
    }
    return {
        "metrics": metrics,
        "arrays": {
            "polarization_scan_angles_rad": angles.tolist(),
            "polarization_scan_intensity": np.asarray(intensities, dtype=float).tolist(),
        },
        "metadata": {"analysis": "polarization_diagnostics", "classification": str(diag.get("diagnosis", ""))},
    }


def evaluate_polarization_interference(options: dict[str, Any]) -> dict[str, Any]:
    from optical_core.physics.wave.formulas.polarization import linear_jones
    from optical_core.physics.wave.formulas.polarization_interference import (
        complementarity_from_polarization,
        phase_scan_interference,
        two_beam_interference,
    )

    left_angle_rad = float(options.get("left_angle_rad", 0.0))
    right_angle_rad = float(options.get("right_angle_rad", math.pi / 4.0))
    coherence_factor = float(options.get("coherence_factor", 1.0))
    phase_rad = float(options.get("phase_rad", 0.0))
    sample_count = int(options.get("sample_count", 181))

    left = linear_jones(left_angle_rad)
    right = linear_jones(right_angle_rad)
    result = two_beam_interference(left, right, relative_phase_rad=phase_rad, coherence_factor=coherence_factor)
    scan = phase_scan_interference(left, right, phases_rad=np.linspace(0.0, 2.0 * math.pi, max(sample_count, 9)), coherence_factor=coherence_factor)
    comp = complementarity_from_polarization(left, right)

    return {
        "metrics": {
            "polarization_interference_intensity": float(result.output_intensity),
            "polarization_interference_visibility": float(result.visibility),
            "polarization_distinguishability": float(comp.get("distinguishability", 0.0)),
            "polarization_complementarity_sum": float(comp.get("v_squared_plus_d_squared", 0.0)),
        },
        "arrays": {
            "polarization_phase_scan_rad": np.asarray(scan.phases_rad, dtype=float).tolist(),
            "polarization_phase_scan_intensity": np.asarray(scan.intensities, dtype=float).tolist(),
        },
        "metadata": {"analysis": "polarization_interference"},
    }


def _odd_int(value: Any, *, minimum: int) -> int:
    number = int(value)
    if number < minimum:
        number = minimum
    if number % 2 == 0:
        number += 1
    return number


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, complex):
        return {"real": float(value.real), "imag": float(value.imag)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(value).items()}
    return value
