
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from optical_core.models.domain.surface import OpticalSurface
from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray_bundle import RayBundle
from optical_core.models.representations.trace import PlaneTraceData, TraceBundle
from optical_core.physics.geometric.formulas.surface_sag import is_plane_radius
from optical_core.physics.geometric.solvers.trace_options import TraceOptions


OutputLevel = Literal["final", "planes"]


@dataclass(frozen=True, slots=True)
class CompactTraceSupport:
    supported: bool
    reason: str = ""


def compact_trace_support(system: SequentialOpticalSystem, options: TraceOptions) -> CompactTraceSupport:
    if options.include_group_delay:
        return CompactTraceSupport(False, "group delay requires the full coating audit path")
    for surface in system.surfaces:
        if bool(getattr(surface, "has_pose_transform", False)):
            return CompactTraceSupport(False, "decentered/tilted surfaces require the full posed-surface tracer")
        surface_type = str(surface.surface_type).strip().lower()
        if surface_type not in {"refractive", "transmissive", "refraction", "aspheric", "spherical", "plane", ""}:
            return CompactTraceSupport(False, f"surface type {surface.surface_type!r} requires the full tracer")
        if surface.coating_layers:
            return CompactTraceSupport(False, "multilayer coatings require the full tracer")
        if surface.grating_period_um is not None or surface.grating_orders:
            return CompactTraceSupport(False, "gratings require the branching tracer")
    return CompactTraceSupport(True)


def _normalise_rows(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    array = np.asarray(values, dtype=float)
    norms = np.sqrt(np.sum(array * array, axis=1))
    valid = np.isfinite(norms) & (norms > 0.0)
    out = np.full_like(array, np.nan, dtype=float)
    np.divide(array, norms[:, None], out=out, where=valid[:, None])
    return out, valid


def _surface_sag_and_derivative(radial: np.ndarray, surface: OpticalSurface) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = np.asarray(radial, dtype=float)
    if is_plane_radius(surface.radius_mm):
        sag = np.zeros_like(r)
        derivative = np.zeros_like(r)
        return sag, derivative, np.ones_like(r, dtype=bool)
    curvature = 1.0 / float(surface.radius_mm)
    q = 1.0 + float(surface.conic)
    radicand = 1.0 - q * (curvature * r) ** 2
    valid = np.isfinite(radicand) & (radicand >= -1.0e-12)
    root = np.sqrt(np.maximum(radicand, 0.0))
    sag = curvature * r * r / (1.0 + root)
    derivative = np.zeros_like(r)
    nonzero = np.abs(r) > 1.0e-16
    derivative[nonzero] = curvature * r[nonzero] / np.sqrt(np.maximum(radicand[nonzero], 1.0e-300))
    sag += float(surface.asphere_a2) * r**2
    derivative += 2.0 * float(surface.asphere_a2) * r
    for order, coefficient in enumerate(surface.asphere_coefficients, start=2):
        coeff = float(coefficient)
        sag += coeff * r ** (2 * order)
        derivative += 2.0 * order * coeff * r ** (2 * order - 1)
    valid &= np.isfinite(sag) & np.isfinite(derivative)
    return sag, derivative, valid


def _intersect_batch(
    positions: np.ndarray,
    directions: np.ndarray,
    active: np.ndarray,
    surface: OpticalSurface,
    vertex_z_mm: float,
    max_iterations: int,
    tolerance_mm: float = 1.0e-10,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = positions.shape[0]
    points = np.full((n, 3), np.nan, dtype=float)
    distances = np.full(n, np.nan, dtype=float)
    valid = np.zeros(n, dtype=bool)
    indices = np.flatnonzero(active)
    if indices.size == 0:
        return points, distances, valid
    p0 = positions[indices]
    d = directions[indices]
    dz = d[:, 2]
    local_ok = np.isfinite(dz) & (np.abs(dz) >= 1.0e-14)
    t = np.full(indices.size, np.nan, dtype=float)
    t[local_ok] = (float(vertex_z_mm) - p0[local_ok, 2]) / dz[local_ok]
    local_ok &= np.isfinite(t)
    converged = np.zeros(indices.size, dtype=bool)
    failed = ~local_ok
    for _ in range(int(max_iterations)):
        work = local_ok & ~converged & ~failed
        if not np.any(work):
            break
        point = p0[work] + t[work, None] * d[work]
        radial = np.hypot(point[:, 0], point[:, 1])
        sag, derivative, shape_ok = _surface_sag_and_derivative(radial, surface)
        residual = point[:, 2] - (float(vertex_z_mm) + sag)
        work_indices = np.flatnonzero(work)
        bad_shape = ~shape_ok | ~np.isfinite(residual)
        if np.any(bad_shape):
            failed[work_indices[bad_shape]] = True
        now = (~bad_shape) & (np.abs(residual) <= tolerance_mm)
        if np.any(now):
            converged[work_indices[now]] = True
        update = (~bad_shape) & ~now
        if np.any(update):
            selected = work_indices[update]
            selected_point = point[update]
            selected_radial = radial[update]
            selected_derivative = derivative[update]
            radial_rate = np.zeros_like(selected_radial)
            nonzero = selected_radial > 1.0e-15
            radial_rate[nonzero] = (
                selected_point[nonzero, 0] * d[selected[nonzero], 0]
                + selected_point[nonzero, 1] * d[selected[nonzero], 1]
            ) / selected_radial[nonzero]
            jacobian = d[selected, 2] - selected_derivative * radial_rate
            jac_ok = np.isfinite(jacobian) & (np.abs(jacobian) > 1.0e-14)
            if np.any(jac_ok):
                t[selected[jac_ok]] -= residual[update][jac_ok] / jacobian[jac_ok]
            if np.any(~jac_ok):
                failed[selected[~jac_ok]] = True
    local_valid = converged & ~failed & np.isfinite(t) & (t >= -tolerance_mm)
    local_points = p0 + t[:, None] * d
    points[indices] = local_points
    distances[indices] = t
    valid[indices] = local_valid
    return points, distances, valid


def _surface_normals(points: np.ndarray, surface: OpticalSurface) -> tuple[np.ndarray, np.ndarray]:
    radial = np.hypot(points[:, 0], points[:, 1])
    _, derivative, valid = _surface_sag_and_derivative(radial, surface)
    normals = np.zeros_like(points, dtype=float)
    normals[:, 2] = 1.0
    scale = np.zeros_like(radial)
    nonzero = radial > 1.0e-15
    scale[nonzero] = -derivative[nonzero] / radial[nonzero]
    normals[:, 0] = scale * points[:, 0]
    normals[:, 1] = scale * points[:, 1]
    normals, normal_ok = _normalise_rows(normals)
    return normals, valid & normal_ok


def _surface_basis(direction: np.ndarray, normal: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    s = np.cross(direction, normal)
    s_norm = np.sqrt(np.sum(s * s, axis=1))
    degenerate = s_norm <= 1.0e-12
    if np.any(degenerate):
        reference = np.zeros((np.count_nonzero(degenerate), 3), dtype=float)
        reference[:, 0] = 1.0
        d = direction[degenerate]
        switch = np.abs(d[:, 0]) > 0.9
        reference[switch] = np.asarray([0.0, 1.0, 0.0])
        s[degenerate] = np.cross(d, reference)
    s, s_ok = _normalise_rows(s)
    p, p_ok = _normalise_rows(np.cross(s, direction))
    return s, p, s_ok & p_ok


def _uncoated_amplitudes(cos_i: np.ndarray, n1: float, n2: float) -> tuple[np.ndarray, ...]:
    cos_i = np.clip(np.asarray(cos_i, dtype=float), 0.0, 1.0)
    ratio = float(n1) / float(n2)
    sin_t2 = ratio * ratio * np.maximum(0.0, 1.0 - cos_i * cos_i)
    tir = sin_t2 > 1.0 + 1.0e-12
    cos_t = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(sin_t2, 1.0)))
    q0s = float(n1) * cos_i
    qss = float(n2) * cos_t
    q0p = np.divide(float(n1), cos_i, out=np.full_like(cos_i, np.inf), where=cos_i > 0.0)
    qsp = np.divide(float(n2), cos_t, out=np.full_like(cos_t, np.inf), where=cos_t > 0.0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        ts = 2.0 * q0s / (q0s + qss)
        # The p characteristic-matrix/admittance coefficient is a tangential-E
        # coefficient.  Convert it to the coefficient of the unit p vector used
        # by the ray Jones representation, while computing power with the p
        # optical-admittance ratio.  This mirrors coating._single_polarization
        # and prevents R+T>1 / compact-vs-full drift at oblique incidence.
        tp_tangential = 2.0 * q0p / (q0p + qsp)
        tp = np.divide(
            tp_tangential * cos_i,
            cos_t,
            out=np.zeros_like(tp_tangential),
            where=cos_t > 0.0,
        )
        Ts = np.divide(qss, q0s, out=np.zeros_like(cos_i), where=q0s > 0.0) * np.abs(ts) ** 2
        Tp = np.divide(qsp, q0p, out=np.zeros_like(cos_i), where=np.isfinite(q0p) & (q0p > 0.0)) * np.abs(tp_tangential) ** 2
    for array in (ts, tp, Ts, Tp):
        array[~np.isfinite(array)] = 0.0
    Ts = np.maximum(Ts, 0.0)
    Tp = np.maximum(Tp, 0.0)
    ts = ts.astype(np.complex128)
    tp = tp.astype(np.complex128)
    ts[tir] = 0.0
    tp[tir] = 0.0
    Ts[tir] = 0.0
    Tp[tir] = 0.0
    return ts, tp, Ts, Tp, cos_t, tir


def _transmit_batch(
    directions: np.ndarray,
    polarizations: np.ndarray,
    points: np.ndarray,
    active: np.ndarray,
    surface: OpticalSurface,
    *,
    n_before: float,
    n_after: float,
    wavelength_nm: float,
    apply_surface_physics: bool,
    polarization_sensitive: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = directions.shape[0]
    out_directions = directions.copy()
    out_polarizations = polarizations.copy()
    amplitude_factor = np.ones(n, dtype=float)
    power_factor = np.ones(n, dtype=float)
    phase_delta = np.zeros(n, dtype=float)
    valid = active.copy()
    indices = np.flatnonzero(active)
    if indices.size == 0:
        return out_directions, out_polarizations, amplitude_factor, power_factor, phase_delta, valid
    incident = directions[indices]
    normals, normal_ok = _surface_normals(points[indices], surface)
    dot = np.sum(incident * normals, axis=1)
    normals[dot > 0.0] *= -1.0
    cos_i = np.clip(-np.sum(incident * normals, axis=1), 0.0, 1.0)
    ratio = float(n_before) / float(n_after)
    sin_t2 = ratio * ratio * np.maximum(0.0, 1.0 - cos_i * cos_i)
    tir = sin_t2 > 1.0 + 1.0e-12
    cos_t = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(sin_t2, 1.0)))
    transmitted = ratio * incident + (ratio * cos_i - cos_t)[:, None] * normals
    transmitted, direction_ok = _normalise_rows(transmitted)
    local_valid = normal_ok & direction_ok & ~tir
    if apply_surface_physics:
        s, p_incident, basis_ok = _surface_basis(incident, normals)
        p_out, p_out_ok = _normalise_rows(np.cross(s, transmitted))
        ts, tp, Ts, Tp, _, coating_tir = _uncoated_amplitudes(cos_i, n_before, n_after)
        pol = polarizations[indices]
        explicit_survival = 1.0 - float(surface.surface_absorption_fraction)
        if float(surface.roughness_rms_nm) > 0.0:
            roughness_survival = np.exp(
                -((4.0 * np.pi * float(surface.roughness_rms_nm) * cos_i) / float(wavelength_nm)) ** 2
            )
            roughness_survival = np.clip(roughness_survival, 0.0, 1.0)
        else:
            roughness_survival = np.ones_like(cos_i)
        survival = explicit_survival * roughness_survival
        if polarization_sensitive:
            es = np.sum(np.conj(s) * pol, axis=1)
            ep = np.sum(np.conj(p_incident) * pol, axis=1)
            incident_norm2 = np.maximum(np.abs(es) ** 2 + np.abs(ep) ** 2, 1.0e-30)
            vector = ts[:, None] * es[:, None] * s + tp[:, None] * ep[:, None] * p_out
            vector_norm = np.sqrt(np.sum(np.abs(vector) ** 2, axis=1))
            fraction = (
                (Ts * np.abs(es) ** 2 + Tp * np.abs(ep) ** 2) / incident_norm2
            ) * survival
            coherent = (np.conj(es) * ts * es + np.conj(ep) * tp * ep) / incident_norm2
            phase = np.angle(coherent)
            branch_ok = basis_ok & p_out_ok & (vector_norm > 1.0e-30) & (fraction > 0.0) & ~coating_tir
            normalized_vector = np.zeros_like(vector)
            np.divide(vector, vector_norm[:, None], out=normalized_vector, where=vector_norm[:, None] > 0.0)
            out_polarizations[indices] = normalized_vector
        else:
            # Scalar / polarization-insensitive tracing must not inherit the arbitrary
            # lab-X Jones vector used as a storage placeholder.  Use the equal s/p
            # power average for an unpolarized scalar throughput, while retaining a
            # transverse placeholder vector only for diagnostics.
            fraction = 0.5 * (Ts + Tp) * survival
            coherent = 0.5 * (ts + tp)
            phase = np.angle(coherent)
            projected = pol - np.sum(np.conj(transmitted) * pol, axis=1)[:, None] * transmitted
            vector_norm = np.sqrt(np.sum(np.abs(projected) ** 2, axis=1))
            fallback = vector_norm <= 1.0e-30
            if np.any(fallback):
                projected[fallback] = s[fallback].astype(np.complex128)
                vector_norm[fallback] = 1.0
            out_polarizations[indices] = projected / np.maximum(vector_norm[:, None], 1.0e-30)
            branch_ok = (fraction > 0.0) & ~coating_tir
        local_valid &= branch_ok
        amplitude_factor[indices] = np.sqrt(np.maximum(fraction, 0.0))
        power_factor[indices] = np.maximum(fraction, 0.0)
        phase_delta[indices] = phase
    out_directions[indices] = transmitted
    valid[indices] = local_valid
    return out_directions, out_polarizations, amplitude_factor, power_factor, phase_delta, valid


def _plane_record(
    plane_z_mm: float,
    positions: np.ndarray,
    directions: np.ndarray,
    optical_paths: np.ndarray,
    field_amplitudes: np.ndarray,
    power_weights: np.ndarray,
    quadrature_weights: np.ndarray,
    valid: np.ndarray,
    ray_ids: np.ndarray,
    status_codes: np.ndarray,
    *,
    segment_lengths: np.ndarray | None = None,
    refractive_indices: np.ndarray | None = None,
    segment_opl: np.ndarray | None = None,
    cumulative_opl: np.ndarray | None = None,
    phase_offsets: np.ndarray | None = None,
    polarizations: np.ndarray | None = None,
) -> PlaneTraceData:
    return PlaneTraceData(
        plane_z_mm=float(plane_z_mm), positions_mm=positions, directions=directions,
        optical_paths_mm=optical_paths, field_amplitudes=field_amplitudes,
        power_weights=power_weights, quadrature_weights=quadrature_weights,
        valid_mask=valid, ray_ids=ray_ids, status_codes=status_codes,
        segment_lengths_mm=segment_lengths, refractive_indices=refractive_indices,
        segment_opl_mm=segment_opl, cumulative_opl_mm=cumulative_opl,
        phase_offsets_rad=phase_offsets, polarization_vectors_xyz=polarizations,
    )


def trace_ray_batch_compact(
    system: SequentialOpticalSystem,
    rays: RayBundle,
    options: TraceOptions,
    *,
    output_level: OutputLevel,
    progress_callback=None,
) -> TraceBundle:

    support = compact_trace_support(system, options)
    if not support.supported:
        raise ValueError(support.reason)
    positions = np.asarray(rays.positions_mm, dtype=float).copy()
    directions, direction_ok = _normalise_rows(np.asarray(rays.directions, dtype=float))
    n = positions.shape[0]
    optical_paths = np.asarray(rays.optical_paths_mm, dtype=float).copy()
    field_amplitudes = np.asarray(rays.field_amplitudes, dtype=float).copy()
    power_weights = np.asarray(rays.power_weights, dtype=float).copy()
    quadrature_weights = np.asarray(rays.quadrature_weights, dtype=float).copy()
    valid = np.asarray(rays.valid_mask, dtype=bool).copy() & direction_ok
    ray_ids = np.asarray(rays.ray_ids, dtype=object)
    phase_offsets = np.zeros(n, dtype=float)
    polarizations = np.zeros((n, 3), dtype=np.complex128)
    polarizations[:, 0] = 1.0 + 0.0j
    
    
    projection = np.sum(polarizations.real * directions, axis=1)
    polarizations -= projection[:, None] * directions
    pol_norm = np.sqrt(np.sum(np.abs(polarizations) ** 2, axis=1))
    fallback = pol_norm <= 1.0e-15
    if np.any(fallback):
        polarizations[fallback] = np.asarray([0.0, 1.0, 0.0])
        projection = np.sum(polarizations[fallback].real * directions[fallback], axis=1)
        polarizations[fallback] -= projection[:, None] * directions[fallback]
        pol_norm[fallback] = np.sqrt(np.sum(np.abs(polarizations[fallback]) ** 2, axis=1))
    polarizations /= np.maximum(pol_norm[:, None], 1.0e-30)
    input_polarizations = polarizations.copy()

    status_codes = np.full(n, "INVALID_INPUT", dtype=object)
    status_codes[valid] = "IN_PROGRESS"
    reasons = ["" for _ in range(n)]
    input_positions = positions.copy()
    input_directions = directions.copy()
    input_valid = valid.copy()

    segment_count = len(system.surfaces) + (1 if options.propagate_to_image and system.surfaces else 0)
    segment_lengths = np.full((n, segment_count), np.nan, dtype=float)
    segment_indices = np.full((n, segment_count), np.nan, dtype=float)
    segment_opl = np.full((n, segment_count), np.nan, dtype=float)
    cumulative_opl = np.full((n, segment_count), np.nan, dtype=float)
    plane_positions = np.full((segment_count, n, 3), np.nan, dtype=float) if output_level == "planes" else None
    plane_directions = np.full((segment_count, n, 3), np.nan, dtype=float) if output_level == "planes" else None
    plane_paths = np.full((segment_count, n), np.nan, dtype=float) if output_level == "planes" else None
    plane_valid = np.zeros((segment_count, n), dtype=bool) if output_level == "planes" else None

    # ``plane_valid`` means that a ray physically reached the surface/plane, not
    # that it also survived the interaction.  This matches the detailed tracer
    # and lets us reconstruct the exact ray polyline used by the ray-trace view.
    wavelength_nm = float(options.wavelength_nm or system.wavelength_nm)
    vertices = system.surface_vertex_z_positions()
    segment = 0
    progress_total = max(1, len(system.surfaces) + (1 if options.propagate_to_image and system.surfaces else 0))
    if progress_callback is not None:
        progress_callback(0.0)
    for surface_index, (surface, vertex_z) in enumerate(zip(system.surfaces, vertices)):
        before = valid.copy()
        points, distances, hit_valid = _intersect_batch(
            positions, directions, before, surface, float(vertex_z), options.max_intersection_iterations
        )
        failed_intersection = before & ~hit_valid
        for index in np.flatnonzero(failed_intersection):
            status_codes[index] = "INTERSECTION_FAILED"
            reasons[index] = "surface intersection failed"
        valid &= hit_valid
        reached = valid.copy()
        n_before = float(system.material_index(surface.material_before, wavelength_nm))
        lengths = np.abs(distances)
        optical_paths[valid] += lengths[valid] * n_before
        positions[valid] = points[valid]
        segment_lengths[valid, segment] = lengths[valid]
        segment_indices[valid, segment] = n_before
        segment_opl[valid, segment] = lengths[valid] * n_before
        cumulative_opl[valid, segment] = optical_paths[valid]

        if options.evaluate_apertures and surface.clear_aperture_mm is not None:
            aperture_ok = points[:, 0] ** 2 + points[:, 1] ** 2 <= float(surface.clear_aperture_mm) ** 2
            clipped = valid & ~aperture_ok
            for index in np.flatnonzero(clipped):
                status_codes[index] = "APERTURE_CLIPPED"
                reasons[index] = "clipped by clear aperture"
            valid &= aperture_ok

        n_after = float(system.material_index(surface.material_after, wavelength_nm))
        new_directions, new_polarizations, amp_factor, power_factor, phase_delta, transmit_valid = _transmit_batch(
            directions, polarizations, points, valid, surface,
            n_before=n_before, n_after=n_after, wavelength_nm=wavelength_nm,
            apply_surface_physics=options.apply_surface_physics,
            polarization_sensitive=options.polarization_sensitive,
        )
        failed_refraction = valid & ~transmit_valid
        for index in np.flatnonzero(failed_refraction):
            status_codes[index] = "REFRACTION_FAILED"
            reasons[index] = "total internal reflection or zero transmitted power"
        valid &= transmit_valid
        directions[valid] = new_directions[valid]
        polarizations[valid] = new_polarizations[valid]
        field_amplitudes[valid] *= amp_factor[valid]
        power_weights[valid] *= power_factor[valid]
        phase_offsets[valid] += phase_delta[valid]
        if output_level == "planes":
            assert plane_positions is not None and plane_directions is not None and plane_paths is not None and plane_valid is not None
            plane_positions[segment, reached] = positions[reached]
            # Successful rays carry their outgoing direction; rays terminated at
            # this surface keep the incoming direction, exactly like DetailedRayTrace.
            plane_directions[segment, reached] = directions[reached]
            plane_paths[segment, reached] = optical_paths[reached]
            plane_valid[segment] = reached
        segment += 1
        if progress_callback is not None:
            progress_callback(segment / progress_total)

    if options.propagate_to_image and system.surfaces:
        before = valid.copy()
        dz = directions[:, 2]
        image_z = float(vertices[-1] + system.image_distance_mm)
        distances = np.full(n, np.nan, dtype=float)
        image_ok = before & np.isfinite(dz) & (np.abs(dz) >= 1.0e-14)
        distances[image_ok] = (image_z - positions[image_ok, 2]) / dz[image_ok]
        image_ok &= np.isfinite(distances)
        failed = before & ~image_ok
        for index in np.flatnonzero(failed):
            status_codes[index] = "IMAGE_PROPAGATION_FAILED"
            reasons[index] = "cannot propagate to image plane"
        valid &= image_ok
        reached = valid.copy()
        points = positions + distances[:, None] * directions
        n_image = float(system.material_index(system.surfaces[-1].material_after, wavelength_nm))
        lengths = np.abs(distances)
        optical_paths[valid] += lengths[valid] * n_image
        positions[valid] = points[valid]
        segment_lengths[valid, segment] = lengths[valid]
        segment_indices[valid, segment] = n_image
        segment_opl[valid, segment] = lengths[valid] * n_image
        cumulative_opl[valid, segment] = optical_paths[valid]
        if output_level == "planes":
            assert plane_positions is not None and plane_directions is not None and plane_paths is not None and plane_valid is not None
            plane_positions[segment, reached] = positions[reached]
            plane_directions[segment, reached] = directions[reached]
            plane_paths[segment, reached] = optical_paths[reached]
            plane_valid[segment] = reached
        if progress_callback is not None:
            progress_callback(1.0)

    status_codes[valid] = "REACHED_IMAGE" if options.propagate_to_image else "REACHED_LAST_SURFACE"
    final_positions = np.full((n, 3), np.nan, dtype=float)
    final_directions = np.full((n, 3), np.nan, dtype=float)
    final_positions[:] = positions
    final_directions[:] = directions

    input_pupil = _plane_record(
        float(np.nanmedian(input_positions[:, 2])) if n else 0.0,
        input_positions, input_directions, np.asarray(rays.optical_paths_mm, dtype=float).copy(),
        np.asarray(rays.field_amplitudes, dtype=float).copy(),
        np.asarray(rays.power_weights, dtype=float).copy(), quadrature_weights.copy(),
        input_valid, ray_ids, np.where(input_valid, "INPUT_VALID", "INVALID_INPUT"),
        phase_offsets=np.zeros(n, dtype=float), polarizations=input_polarizations,
    )
    surface_records: dict[str, PlaneTraceData] = {}
    if output_level == "planes" and segment_count:
        assert plane_positions is not None and plane_directions is not None and plane_paths is not None and plane_valid is not None
        plane_z_values = list(vertices)
        if options.propagate_to_image and system.surfaces:
            plane_z_values.append(float(vertices[-1] + system.image_distance_mm))
        for item in range(segment_count):
            name = "image" if item == len(system.surfaces) else f"surface_{item + 1}"
            surface_records[name] = _plane_record(
                plane_z_values[item], plane_positions[item], plane_directions[item], plane_paths[item],
                field_amplitudes, power_weights, quadrature_weights, plane_valid[item], ray_ids,
                status_codes, segment_lengths=segment_lengths[:, item],
                refractive_indices=segment_indices[:, item], segment_opl=segment_opl[:, item],
                cumulative_opl=cumulative_opl[:, item], phase_offsets=phase_offsets,
                polarizations=polarizations,
            )

    path_points = None
    path_offsets = None
    path_surface_indices = None
    if output_level == "planes":
        assert plane_positions is not None and plane_valid is not None
        flat_points: list[np.ndarray] = []
        flat_indices: list[int] = []
        offsets = [0]
        for ray_index in range(n):
            flat_points.append(input_positions[ray_index])
            flat_indices.append(-1)
            for item in range(segment_count):
                if plane_valid[item, ray_index]:
                    flat_points.append(plane_positions[item, ray_index])
                    flat_indices.append(item)
            offsets.append(len(flat_points))
        path_points = (
            np.asarray(flat_points, dtype=float).reshape((-1, 3))
            if flat_points else np.empty((0, 3), dtype=float)
        )
        path_offsets = np.asarray(offsets, dtype=np.int64)
        path_surface_indices = np.asarray(flat_indices, dtype=np.int32)

    warnings = [f"ray[{i}] {ray_ids[i]}: {reason}" for i, reason in enumerate(reasons) if reason]
    return TraceBundle(
        final_positions_mm=final_positions, final_directions=final_directions,
        optical_paths_mm=optical_paths, field_amplitudes=field_amplitudes,
        power_weights=power_weights, quadrature_weights=quadrature_weights,
        valid_mask=valid, plane_records={"input_pupil": input_pupil},
        surface_records=surface_records, warnings=warnings, ray_ids=ray_ids,
        pupil_coordinates_normalized=(None if rays.pupil_coordinates_normalized is None else rays.pupil_coordinates_normalized.copy()),
        status_codes=status_codes, termination_reasons=reasons,
        path_points_mm=path_points, path_offsets=path_offsets, path_surface_indices=path_surface_indices,
        segment_lengths_mm=segment_lengths, segment_refractive_indices=segment_indices,
        segment_opl_mm=segment_opl, cumulative_opl_mm=cumulative_opl,
        phase_offsets_rad=phase_offsets, polarization_vectors_xyz=polarizations,
        surface_interaction_records=[[] for _ in range(n)],
        surface_physics_applied=bool(options.apply_surface_physics),
    )


__all__ = ["CompactTraceSupport", "compact_trace_support", "trace_ray_batch_compact"]
