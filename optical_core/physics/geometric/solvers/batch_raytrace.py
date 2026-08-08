# 批量追迹统一入口；根据是否涉及偏振选择完整追迹或紧凑矢量化追迹
# 完整审计路径：功能完整，保留逐光线、逐表面的详细记录
# 紧凑批量路径：数组矢量化，速度更快，只返回必要结果
from __future__ import annotations

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.models.representations.ray import Ray
from optical_core.models.representations.ray_bundle import RayBundle
from optical_core.models.representations.trace import PlaneTraceData, TraceBundle
from optical_core.physics.geometric.solvers.scalar_raytrace import DetailedRayTrace, trace_single_ray_detailed
from optical_core.physics.geometric.solvers.trace_options import TraceOptions


def _plane_record(
    *,
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
    segment_lengths: np.ndarray | None = None,
    refractive_indices: np.ndarray | None = None,
    segment_opl: np.ndarray | None = None,
    cumulative_opl: np.ndarray | None = None,
    phase_offsets_rad: np.ndarray | None = None,
    polarization_vectors_xyz: np.ndarray | None = None,
) -> PlaneTraceData:
    return PlaneTraceData(
        plane_z_mm=float(plane_z_mm),
        positions_mm=np.asarray(positions, dtype=float),
        directions=np.asarray(directions, dtype=float),
        optical_paths_mm=np.asarray(optical_paths, dtype=float),
        field_amplitudes=np.asarray(field_amplitudes, dtype=float),
        power_weights=np.asarray(power_weights, dtype=float),
        quadrature_weights=np.asarray(quadrature_weights, dtype=float),
        valid_mask=np.asarray(valid, dtype=bool),
        ray_ids=np.asarray(ray_ids, dtype=object),
        status_codes=np.asarray(status_codes, dtype=object),
        segment_lengths_mm=None if segment_lengths is None else np.asarray(segment_lengths, dtype=float),
        refractive_indices=None if refractive_indices is None else np.asarray(refractive_indices, dtype=float),
        segment_opl_mm=None if segment_opl is None else np.asarray(segment_opl, dtype=float),
        cumulative_opl_mm=None if cumulative_opl is None else np.asarray(cumulative_opl, dtype=float),
        phase_offsets_rad=phase_offsets_rad,
        polarization_vectors_xyz=polarization_vectors_xyz,
    )


def trace_ray_batch(system: SequentialOpticalSystem, rays: RayBundle, options: TraceOptions | None = None) -> TraceBundle:

    options = options or TraceOptions()
    output_level = str(options.output_level).strip().lower()
    if output_level not in {"full", "planes", "final"}:
        raise ValueError("TraceOptions.output_level must be full, planes, or final")
    if output_level != "full":
        from optical_core.physics.geometric.solvers.compact_batch_raytrace import (
            compact_trace_support, trace_ray_batch_compact,
        )
        support = compact_trace_support(system, options)
        if support.supported:
            return trace_ray_batch_compact(
                system, rays, options, output_level="planes" if output_level == "planes" else "final"
            )
    n = rays.positions_mm.shape[0]
    final_positions = np.full((n, 3), np.nan, dtype=float)
    final_directions = np.full((n, 3), np.nan, dtype=float)
    optical_paths = np.asarray(rays.optical_paths_mm, dtype=float).copy()
    field_amplitudes = np.asarray(rays.field_amplitudes, dtype=float).copy()
    power_weights = np.asarray(rays.power_weights, dtype=float).copy()
    quadrature_weights = np.asarray(rays.quadrature_weights, dtype=float).copy()
    valid = np.asarray(rays.valid_mask, dtype=bool).copy()
    phase_offsets = np.zeros(n, dtype=float)
    polarization_vectors = np.zeros((n, 3), dtype=np.complex128)
    polarization_vectors[:, 0] = 1.0 + 0.0j
    surface_interactions: list[list[dict]] = [[] for _ in range(n)]
    ray_ids = np.asarray(rays.ray_ids, dtype=object)
    status_codes = np.full(n, "INVALID_INPUT", dtype=object)
    reasons = ["" for _ in range(n)]
    warnings: list[str] = []

    input_pupil = _plane_record(
        plane_z_mm=float(np.nanmedian(rays.positions_mm[:, 2])) if n else 0.0,
        positions=rays.positions_mm.copy(),
        directions=rays.directions.copy(),
        optical_paths=optical_paths.copy(),
        field_amplitudes=field_amplitudes.copy(),
        power_weights=power_weights.copy(),
        quadrature_weights=quadrature_weights.copy(),
        valid=valid.copy(),
        ray_ids=ray_ids,
        status_codes=np.where(valid, "INPUT_VALID", "INVALID_INPUT"),
        phase_offsets_rad=phase_offsets.copy(),
        polarization_vectors_xyz=polarization_vectors.copy(),
    )

    details: list[DetailedRayTrace] = []
    for i in range(n):
        wavelength_nm = float(options.wavelength_nm or system.wavelength_nm)
        ray = Ray(
            position_mm=tuple(float(v) for v in rays.positions_mm[i]),
            direction=tuple(float(v) for v in rays.directions[i]),
            wavelength_nm=wavelength_nm,
            field_amplitude=float(field_amplitudes[i]),
            power_weight=float(power_weights[i]),
            quadrature_weight=float(quadrature_weights[i]),
            optical_path_mm=float(optical_paths[i]),
            valid=bool(valid[i]),
            phase_offset_rad=float(phase_offsets[i]),
            polarization_xyz=tuple(complex(v) for v in polarization_vectors[i]),
        )
        detail = trace_single_ray_detailed(system, ray, options)
        details.append(detail)
        traced = detail.final_ray
        final_positions[i] = np.asarray(traced.position_mm, dtype=float)
        final_directions[i] = np.asarray(traced.direction, dtype=float)
        optical_paths[i] = float(traced.optical_path_mm)
        field_amplitudes[i] = float(traced.field_amplitude)
        power_weights[i] = float(traced.power_weight)
        quadrature_weights[i] = float(traced.quadrature_weight)
        valid[i] = bool(traced.valid)
        phase_offsets[i] = float(traced.phase_offset_rad)
        polarization_vectors[i] = np.asarray(traced.polarization_xyz, dtype=np.complex128)
        surface_interactions[i] = list(detail.surface_interactions)
        status_codes[i] = detail.status_code
        reasons[i] = detail.termination_reason
        if detail.termination_reason:
            warnings.append(f"ray[{i}] {ray_ids[i]}: {detail.termination_reason}")

    max_segments = max((len(item.segment_lengths_mm) for item in details), default=0)
    segment_lengths = np.full((n, max_segments), np.nan, dtype=float)
    segment_indices = np.full((n, max_segments), np.nan, dtype=float)
    segment_opl = np.full((n, max_segments), np.nan, dtype=float)
    cumulative_opl = np.full((n, max_segments), np.nan, dtype=float)
    for i, detail in enumerate(details):
        count = len(detail.segment_lengths_mm)
        if count:
            segment_lengths[i, :count] = detail.segment_lengths_mm
            segment_indices[i, :count] = detail.segment_refractive_indices
            segment_opl[i, :count] = detail.segment_opl_mm
            cumulative_opl[i, :count] = detail.cumulative_opl_mm

    flat_points: list[tuple[float, float, float]] = []
    flat_surface_indices: list[int] = []
    offsets = [0]
    for detail in details:
        flat_points.extend(detail.path_points_mm)
        flat_surface_indices.extend(detail.path_surface_indices)
        offsets.append(len(flat_points))
    path_points = np.asarray(flat_points, dtype=float).reshape((-1, 3)) if flat_points else np.empty((0, 3))

    surface_records: dict[str, PlaneTraceData] = {}
    if options.record_surfaces and max_segments:
        vertices = list(system.surface_vertex_z_positions())
        if options.propagate_to_image and system.surfaces:
            vertices.append(float(vertices[-1] + system.image_distance_mm))
        for segment_index in range(max_segments):
            positions = np.full((n, 3), np.nan, dtype=float)
            directions = np.full((n, 3), np.nan, dtype=float)
            paths = np.full(n, np.nan, dtype=float)
            segment_valid = np.zeros(n, dtype=bool)
            for ray_index, detail in enumerate(details):
                if segment_index < len(detail.surface_points_mm):
                    positions[ray_index] = detail.surface_points_mm[segment_index]
                    directions[ray_index] = detail.surface_directions[segment_index]
                    paths[ray_index] = detail.cumulative_opl_mm[segment_index]
                    segment_valid[ray_index] = True
            plane_z = vertices[segment_index] if segment_index < len(vertices) else float("nan")
            name = "image" if segment_index == len(system.surfaces) else f"surface_{segment_index + 1}"
            surface_records[name] = _plane_record(
                plane_z_mm=plane_z,
                positions=positions,
                directions=directions,
                optical_paths=paths,
                field_amplitudes=field_amplitudes,
                power_weights=power_weights,
                quadrature_weights=quadrature_weights,
                valid=segment_valid,
                ray_ids=ray_ids,
                status_codes=status_codes,
                segment_lengths=segment_lengths[:, segment_index],
                refractive_indices=segment_indices[:, segment_index],
                segment_opl=segment_opl[:, segment_index],
                cumulative_opl=cumulative_opl[:, segment_index],
                phase_offsets_rad=phase_offsets,
                polarization_vectors_xyz=polarization_vectors,
            )

    return TraceBundle(
        final_positions_mm=final_positions,
        final_directions=final_directions,
        optical_paths_mm=optical_paths,
        field_amplitudes=field_amplitudes,
        power_weights=power_weights,
        quadrature_weights=quadrature_weights,
        valid_mask=valid,
        plane_records={"input_pupil": input_pupil},
        surface_records=surface_records,
        warnings=warnings,
        ray_ids=ray_ids,
        pupil_coordinates_normalized=None if rays.pupil_coordinates_normalized is None else rays.pupil_coordinates_normalized.copy(),
        status_codes=status_codes,
        termination_reasons=reasons,
        path_points_mm=path_points,
        path_offsets=np.asarray(offsets, dtype=np.int64),
        path_surface_indices=np.asarray(flat_surface_indices, dtype=np.int32),
        segment_lengths_mm=segment_lengths,
        segment_refractive_indices=segment_indices,
        segment_opl_mm=segment_opl,
        cumulative_opl_mm=cumulative_opl,
        phase_offsets_rad=phase_offsets,
        polarization_vectors_xyz=polarization_vectors,
        surface_interaction_records=surface_interactions,
    )
