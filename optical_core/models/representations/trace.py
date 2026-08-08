# 定义光线追迹结果。

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np


def _vector(value: np.ndarray, *, name: str, n: int, dtype=float) -> np.ndarray:
    array = np.asarray(value, dtype=dtype).reshape(-1)
    if array.shape != (n,):
        raise ValueError(f"{name} must have shape (N,)")
    return array


@dataclass(slots=True, init=False)
class PlaneTraceData:


    plane_z_mm: float
    positions_mm: np.ndarray
    directions: np.ndarray
    optical_paths_mm: np.ndarray
    field_amplitudes: np.ndarray
    valid_mask: np.ndarray
    power_weights: np.ndarray
    quadrature_weights: np.ndarray
    ray_ids: np.ndarray | None
    status_codes: np.ndarray | None
    segment_lengths_mm: np.ndarray | None
    refractive_indices: np.ndarray | None
    segment_opl_mm: np.ndarray | None
    cumulative_opl_mm: np.ndarray | None
    phase_offsets_rad: np.ndarray
    polarization_vectors_xyz: np.ndarray

    def __init__(
        self,
        plane_z_mm: float,
        positions_mm: np.ndarray,
        directions: np.ndarray,
        optical_paths_mm: np.ndarray,
        field_amplitudes: np.ndarray,
        valid_mask: np.ndarray,
        power_weights: np.ndarray | None = None,
        quadrature_weights: np.ndarray | None = None,
        ray_ids: np.ndarray | None = None,
        status_codes: np.ndarray | None = None,
        segment_lengths_mm: np.ndarray | None = None,
        refractive_indices: np.ndarray | None = None,
        segment_opl_mm: np.ndarray | None = None,
        cumulative_opl_mm: np.ndarray | None = None,
        phase_offsets_rad: np.ndarray | None = None,
        polarization_vectors_xyz: np.ndarray | None = None,
    ) -> None:
        positions = np.asarray(positions_mm, dtype=float)
        directions_array = np.asarray(directions, dtype=float)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("positions_mm must have shape (N,3) in XYZ order")
        if directions_array.shape != positions.shape:
            raise ValueError("directions must have shape (N,3)")
        n = positions.shape[0]
        fields = _vector(field_amplitudes, name="field_amplitudes", n=n)
        powers = np.square(fields) if power_weights is None else _vector(power_weights, name="power_weights", n=n)
        quadrature = np.ones(n, dtype=float) if quadrature_weights is None else _vector(quadrature_weights, name="quadrature_weights", n=n)
        if np.any(fields < 0.0) or np.any(powers < 0.0) or np.any(quadrature < 0.0):
            raise ValueError("field amplitudes and weights must be non-negative")
        self.plane_z_mm = float(plane_z_mm)
        self.positions_mm = positions
        self.directions = directions_array
        self.optical_paths_mm = _vector(optical_paths_mm, name="optical_paths_mm", n=n)
        self.field_amplitudes = fields
        self.valid_mask = _vector(valid_mask, name="valid_mask", n=n, dtype=bool)
        self.power_weights = powers
        self.quadrature_weights = quadrature
        self.ray_ids = None if ray_ids is None else _vector(ray_ids, name="ray_ids", n=n, dtype=object)
        self.status_codes = None if status_codes is None else _vector(status_codes, name="status_codes", n=n, dtype=object)
        self.segment_lengths_mm = None if segment_lengths_mm is None else np.asarray(segment_lengths_mm, dtype=float)
        self.refractive_indices = None if refractive_indices is None else np.asarray(refractive_indices, dtype=float)
        self.segment_opl_mm = None if segment_opl_mm is None else np.asarray(segment_opl_mm, dtype=float)
        self.cumulative_opl_mm = None if cumulative_opl_mm is None else np.asarray(cumulative_opl_mm, dtype=float)
        self.phase_offsets_rad = np.zeros(n, dtype=float) if phase_offsets_rad is None else _vector(phase_offsets_rad, name="phase_offsets_rad", n=n)
        if polarization_vectors_xyz is None:
            polarization = np.zeros((n, 3), dtype=np.complex128)
            polarization[:, 0] = 1.0 + 0.0j
        else:
            polarization = np.asarray(polarization_vectors_xyz, dtype=np.complex128)
            if polarization.shape != (n, 3):
                raise ValueError("polarization_vectors_xyz must have shape (N,3)")
        self.polarization_vectors_xyz = polarization

    @property
    def integration_weights(self) -> np.ndarray:
        return self.power_weights * self.quadrature_weights


@dataclass(slots=True, init=False)
class TraceBundle:
    """采用显式电场与积分权重求解单次光线追迹得到的共用结果。"""

    final_positions_mm: np.ndarray
    final_directions: np.ndarray
    optical_paths_mm: np.ndarray
    field_amplitudes: np.ndarray
    valid_mask: np.ndarray
    power_weights: np.ndarray
    quadrature_weights: np.ndarray
    plane_records: Dict[str, PlaneTraceData]
    surface_records: Dict[str, PlaneTraceData]
    warnings: list[str]
    ray_ids: np.ndarray | None
    pupil_coordinates_normalized: np.ndarray | None
    status_codes: np.ndarray | None
    termination_reasons: list[str]
    path_points_mm: np.ndarray | None
    path_offsets: np.ndarray | None
    path_surface_indices: np.ndarray | None
    segment_lengths_mm: np.ndarray | None
    segment_refractive_indices: np.ndarray | None
    segment_opl_mm: np.ndarray | None
    cumulative_opl_mm: np.ndarray | None
    phase_offsets_rad: np.ndarray
    polarization_vectors_xyz: np.ndarray
    surface_interaction_records: list[list[dict]]

    def __init__(
        self,
        final_positions_mm: np.ndarray,
        final_directions: np.ndarray,
        optical_paths_mm: np.ndarray,
        field_amplitudes: np.ndarray,
        valid_mask: np.ndarray | None = None,
        power_weights: np.ndarray | None = None,
        quadrature_weights: np.ndarray | None = None,
        plane_records: Dict[str, PlaneTraceData] | None = None,
        surface_records: Dict[str, PlaneTraceData] | None = None,
        warnings: list[str] | None = None,
        ray_ids: np.ndarray | None = None,
        pupil_coordinates_normalized: np.ndarray | None = None,
        status_codes: np.ndarray | None = None,
        termination_reasons: list[str] | None = None,
        path_points_mm: np.ndarray | None = None,
        path_offsets: np.ndarray | None = None,
        path_surface_indices: np.ndarray | None = None,
        segment_lengths_mm: np.ndarray | None = None,
        segment_refractive_indices: np.ndarray | None = None,
        segment_opl_mm: np.ndarray | None = None,
        cumulative_opl_mm: np.ndarray | None = None,
        phase_offsets_rad: np.ndarray | None = None,
        polarization_vectors_xyz: np.ndarray | None = None,
        surface_interaction_records: list[list[dict]] | None = None,
    ) -> None:
        positions = np.asarray(final_positions_mm, dtype=float)
        directions_array = np.asarray(final_directions, dtype=float)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("final_positions_mm must have shape (N,3) in XYZ order")
        if directions_array.shape != positions.shape:
            raise ValueError("final_directions must have shape (N,3)")
        n = positions.shape[0]
        fields = _vector(field_amplitudes, name="field_amplitudes", n=n)
        powers = np.square(fields) if power_weights is None else _vector(power_weights, name="power_weights", n=n)
        quadrature = np.ones(n, dtype=float) if quadrature_weights is None else _vector(quadrature_weights, name="quadrature_weights", n=n)
        self.final_positions_mm = positions
        self.final_directions = directions_array
        self.optical_paths_mm = _vector(optical_paths_mm, name="optical_paths_mm", n=n)
        self.field_amplitudes = fields
        self.valid_mask = np.ones(n, dtype=bool) if valid_mask is None else _vector(valid_mask, name="valid_mask", n=n, dtype=bool)
        self.power_weights = powers
        self.quadrature_weights = quadrature
        self.plane_records = dict(plane_records or {})
        self.surface_records = dict(surface_records or {})
        self.warnings = list(warnings or [])
        self.ray_ids = None if ray_ids is None else _vector(ray_ids, name="ray_ids", n=n, dtype=object)
        self.pupil_coordinates_normalized = None if pupil_coordinates_normalized is None else np.asarray(pupil_coordinates_normalized, dtype=float)
        self.status_codes = None if status_codes is None else _vector(status_codes, name="status_codes", n=n, dtype=object)
        self.termination_reasons = list(termination_reasons or [])
        self.path_points_mm = None if path_points_mm is None else np.asarray(path_points_mm, dtype=float)
        self.path_offsets = None if path_offsets is None else np.asarray(path_offsets)
        self.path_surface_indices = None if path_surface_indices is None else np.asarray(path_surface_indices)
        self.segment_lengths_mm = None if segment_lengths_mm is None else np.asarray(segment_lengths_mm, dtype=float)
        self.segment_refractive_indices = None if segment_refractive_indices is None else np.asarray(segment_refractive_indices, dtype=float)
        self.segment_opl_mm = None if segment_opl_mm is None else np.asarray(segment_opl_mm, dtype=float)
        self.cumulative_opl_mm = None if cumulative_opl_mm is None else np.asarray(cumulative_opl_mm, dtype=float)
        self.phase_offsets_rad = np.zeros(n, dtype=float) if phase_offsets_rad is None else _vector(phase_offsets_rad, name="phase_offsets_rad", n=n)
        if polarization_vectors_xyz is None:
            polarization = np.zeros((n, 3), dtype=np.complex128)
            polarization[:, 0] = 1.0 + 0.0j
        else:
            polarization = np.asarray(polarization_vectors_xyz, dtype=np.complex128)
            if polarization.shape != (n, 3):
                raise ValueError("polarization_vectors_xyz must have shape (N,3)")
        self.polarization_vectors_xyz = polarization
        records = list(surface_interaction_records or [[] for _ in range(n)])
        if len(records) != n:
            raise ValueError("surface_interaction_records must have one list per ray")
        self.surface_interaction_records = records

    @property
    def integration_weights(self) -> np.ndarray:
        return self.power_weights * self.quadrature_weights
