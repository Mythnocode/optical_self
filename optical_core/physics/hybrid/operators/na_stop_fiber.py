
from __future__ import annotations

from dataclasses import dataclass
from math import asin, isfinite, pi, sqrt


@dataclass(frozen=True, slots=True)
class FibreGeometry:
    core_radius_um: float = 4.1
    length_m: float = 0.0


@dataclass(frozen=True, slots=True)
class FibreMaterial:
    n_core: float = 1.450
    n_clad: float = 1.444
    attenuation_db_per_km: float = 0.0
    connector_loss_db: float = 0.0


@dataclass(frozen=True, slots=True)
class FibreSpecification:
    wavelength_nm: float = 550.0
    geometry: FibreGeometry = FibreGeometry()
    material: FibreMaterial = FibreMaterial()


@dataclass(frozen=True, slots=True)
class FibreModeSolution:
    v_number: float
    material_na: float
    relative_index_difference: float
    mode_radius_um: float
    mode_field_diameter_um: float
    gaussian_na: float
    single_mode: bool
    total_transmission: float


def material_na(n_core: float, n_clad: float) -> float:
    return sqrt(max(float(n_core) ** 2 - float(n_clad) ** 2, 0.0))


def relative_index_difference(n_core: float, n_clad: float) -> float:
    n_core = float(n_core)
    if n_core == 0:
        return 0.0
    return (n_core - float(n_clad)) / n_core


def v_number(core_radius_um: float, wavelength_nm: float, na: float) -> float:
    wavelength_um = max(float(wavelength_nm) * 1e-3, 1e-12)
    return 2.0 * pi * float(core_radius_um) * float(na) / wavelength_um


def marcuse_mode_radius_um(core_radius_um: float, v: float) -> float:
    a = float(core_radius_um)
    v = max(float(v), 1e-9)
    
    return a * (0.65 + 1.619 / (v ** 1.5) + 2.879 / (v ** 6.0))


def gaussian_na_from_mode_radius(wavelength_nm: float, mode_radius_um: float) -> float:
    wavelength_um = max(float(wavelength_nm) * 1e-3, 1e-12)
    w = max(float(mode_radius_um), 1e-12)
    return min(1.0, wavelength_um / (pi * w))


def fibre_bulk_transmission(length_m: float, attenuation_db_per_km: float, connector_loss_db: float = 0.0) -> float:
    loss_db = float(attenuation_db_per_km) * float(length_m) / 1000.0 + float(connector_loss_db)
    return 10.0 ** (-loss_db / 10.0)


def solve_fibre_mode(spec: FibreSpecification) -> FibreModeSolution:
    na = material_na(spec.material.n_core, spec.material.n_clad)
    delta = relative_index_difference(spec.material.n_core, spec.material.n_clad)
    v = v_number(spec.geometry.core_radius_um, spec.wavelength_nm, na)
    radius = marcuse_mode_radius_um(spec.geometry.core_radius_um, v)
    return FibreModeSolution(
        v_number=float(v),
        material_na=float(na),
        relative_index_difference=float(delta),
        mode_radius_um=float(radius),
        mode_field_diameter_um=float(2.0 * radius),
        gaussian_na=float(gaussian_na_from_mode_radius(spec.wavelength_nm, radius)),
        single_mode=bool(v < 2.405),
        total_transmission=float(
            fibre_bulk_transmission(
                spec.geometry.length_m,
                spec.material.attenuation_db_per_km,
                spec.material.connector_loss_db,
            )
        ),
    )


def recommend_system_na(fibre_na: float, *, fill_factor: float = 0.85, safety_margin: float = 0.95) -> float:
    return max(0.0, min(1.0, float(fibre_na) * float(fill_factor) * float(safety_margin)))


def object_na_from_entrance_radius(entrance_radius_mm: float, object_distance_mm: float) -> float:
    r = abs(float(entrance_radius_mm))
    d = abs(float(object_distance_mm))
    if d <= 0:
        return 1.0
    return r / sqrt(r * r + d * d)


def entrance_radius_from_object_na(object_na: float, object_distance_mm: float) -> float:
    na = max(0.0, min(0.999999, float(object_na)))
    d = abs(float(object_distance_mm))
    return d * na / sqrt(max(1.0 - na * na, 1e-12))


def solve_stop_radius_from_object_na(object_na: float, stop_distance_mm: float) -> float:
    return entrance_radius_from_object_na(object_na, stop_distance_mm)


def transmitted_object_na(input_na: float, aperture_radius_mm: float, distance_mm: float) -> float:
    aperture_na = object_na_from_entrance_radius(aperture_radius_mm, distance_mm)
    return min(max(float(input_na), 0.0), aperture_na)


def guided_pupil_sampling_radius(system_na: float, pupil_distance_mm: float) -> float:
    return entrance_radius_from_object_na(system_na, pupil_distance_mm)


def acceptance_angle_rad(na: float, external_index: float = 1.0) -> float:
    ratio = max(0.0, min(1.0, float(na) / max(float(external_index), 1e-12)))
    return asin(ratio)


def evaluate_na_stop_fibre(options: dict | None = None) -> dict[str, float]:
    opts = dict(options or {})
    spec = FibreSpecification(
        wavelength_nm=float(opts.get("wavelength_nm", 550.0)),
        geometry=FibreGeometry(
            core_radius_um=float(opts.get("fiber_core_radius_um", opts.get("fibre_core_radius_um", 4.1))),
            length_m=float(opts.get("fiber_length_m", opts.get("fibre_length_m", 0.0))),
        ),
        material=FibreMaterial(
            n_core=float(opts.get("fiber_n_core", opts.get("fibre_n_core", 1.450))),
            n_clad=float(opts.get("fiber_n_clad", opts.get("fibre_n_clad", 1.444))),
            attenuation_db_per_km=float(opts.get("fiber_attenuation_db_per_km", 0.0)),
            connector_loss_db=float(opts.get("fiber_connector_loss_db", 0.0)),
        ),
    )
    solution = solve_fibre_mode(spec)
    rec_na = recommend_system_na(solution.material_na, fill_factor=float(opts.get("fill_factor", 0.85)))
    object_distance = float(opts.get("object_distance_mm", 100.0))
    stop_distance = float(opts.get("stop_distance_mm", object_distance))
    stop_radius = solve_stop_radius_from_object_na(rec_na, stop_distance)
    return {
        "fiber_v_number": solution.v_number,
        "fiber_material_na": solution.material_na,
        "fiber_relative_index_difference": solution.relative_index_difference,
        "fiber_mode_radius_um": solution.mode_radius_um,
        "fiber_mode_field_diameter_um": solution.mode_field_diameter_um,
        "fiber_gaussian_na": solution.gaussian_na,
        "fiber_single_mode": 1.0 if solution.single_mode else 0.0,
        "fiber_total_transmission": solution.total_transmission,
        "recommended_system_na": rec_na,
        "recommended_stop_radius_mm": stop_radius,
        "recommended_entrance_radius_mm": entrance_radius_from_object_na(rec_na, object_distance),
        "recommended_acceptance_angle_rad": acceptance_angle_rad(solution.material_na),
    }
