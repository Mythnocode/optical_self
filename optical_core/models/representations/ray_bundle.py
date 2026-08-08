

from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(slots=True, init=False)
class RayBundle:


    positions_mm: np.ndarray
    directions: np.ndarray
    field_amplitudes: np.ndarray
    optical_paths_mm: np.ndarray
    valid_mask: np.ndarray
    power_weights: np.ndarray
    quadrature_weights: np.ndarray
    ray_ids: np.ndarray
    pupil_coordinates_normalized: np.ndarray | None

    def __init__(
        self,
        positions_mm: np.ndarray,
        directions: np.ndarray,
        field_amplitudes: np.ndarray | None = None,
        optical_paths_mm: np.ndarray | None = None,
        valid_mask: np.ndarray | None = None,
        power_weights: np.ndarray | None = None,
        quadrature_weights: np.ndarray | None = None,
        ray_ids: np.ndarray | None = None,
        pupil_coordinates_normalized: np.ndarray | None = None,
    ) -> None:
        positions = np.asarray(positions_mm, dtype=float)
        directions_array = np.asarray(directions, dtype=float)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("RayBundle.positions_mm 必须是形状 (N, 3) 的 (x,y,z) 数组。")
        if directions_array.shape != positions.shape:
            raise ValueError("RayBundle.directions 必须与 positions_mm 同形状。")
        n = positions.shape[0]

        if field_amplitudes is None:
            field_amplitudes = np.ones(n, dtype=float)
        if power_weights is None:
            power_weights = np.square(np.asarray(field_amplitudes, dtype=float))

        if quadrature_weights is None:
            quadrature_weights = np.ones(n, dtype=float)
        if optical_paths_mm is None:
            optical_paths_mm = np.zeros(n, dtype=float)
        if valid_mask is None:
            valid_mask = np.ones(n, dtype=bool)

        fields = np.asarray(field_amplitudes, dtype=float).reshape(-1)
        powers = np.asarray(power_weights, dtype=float).reshape(-1)
        quadrature = np.asarray(quadrature_weights, dtype=float).reshape(-1)
        opl = np.asarray(optical_paths_mm, dtype=float).reshape(-1)
        valid = np.asarray(valid_mask, dtype=bool).reshape(-1)
        for name, value in {
            "field_amplitudes": fields,
            "power_weights": powers,
            "quadrature_weights": quadrature,
            "optical_paths_mm": opl,
            "valid_mask": valid,
        }.items():
            if value.shape != (n,):
                raise ValueError(f"RayBundle.{name} 必须是形状 (N,) 的数组。")
        for name, value in {
            "field_amplitudes": fields,
            "power_weights": powers,
            "quadrature_weights": quadrature,
        }.items():
            if np.any(~np.isfinite(value)) or np.any(value < 0.0):
                raise ValueError(f"RayBundle.{name} 必须为非负有限数。")

        norms = np.linalg.norm(directions_array, axis=1)
        if np.any(~np.isfinite(norms)) or np.any(norms <= 0.0):
            raise ValueError("RayBundle.directions 包含无效方向。")
        directions_array = directions_array / norms[:, None]

        ids = (
            np.asarray([f"R{i:06d}" for i in range(n)], dtype=object)
            if ray_ids is None
            else np.asarray(ray_ids, dtype=object).reshape(-1)
        )
        if ids.shape != (n,):
            raise ValueError("RayBundle.ray_ids 必须是形状 (N,) 的数组。")

        pupil = None
        if pupil_coordinates_normalized is not None:
            pupil = np.asarray(pupil_coordinates_normalized, dtype=float)
            if pupil.shape != (n, 2):
                raise ValueError("pupil_coordinates_normalized 必须是 (N,2) 的 (p_x,p_y)。")

        self.positions_mm = positions
        self.directions = directions_array
        self.field_amplitudes = fields
        self.optical_paths_mm = opl
        self.valid_mask = valid
        self.power_weights = powers
        self.quadrature_weights = quadrature
        self.ray_ids = ids
        self.pupil_coordinates_normalized = pupil

    @property
    def integration_weights(self) -> np.ndarray:

        return self.power_weights * self.quadrature_weights

    @classmethod
    def from_positions_and_directions(
        cls,
        positions_mm: np.ndarray,
        directions: np.ndarray,
        *,
        field_amplitude: float = 1.0,
        power_weight: float | None = None,
        quadrature_weight: float = 1.0,
        ray_ids: np.ndarray | None = None,
        pupil_coordinates_normalized: np.ndarray | None = None,
    ) -> "RayBundle":
        positions = np.asarray(positions_mm, dtype=float)
        n = positions.shape[0]
        p = float(field_amplitude) ** 2 if power_weight is None else float(power_weight)
        return cls(
            positions_mm=positions,
            directions=np.asarray(directions, dtype=float),
            field_amplitudes=np.full(n, float(field_amplitude), dtype=float),
            power_weights=np.full(n, p, dtype=float),
            quadrature_weights=np.full(n, float(quadrature_weight), dtype=float),
            optical_paths_mm=np.zeros(n, dtype=float),
            valid_mask=np.ones(n, dtype=bool),
            ray_ids=ray_ids,
            pupil_coordinates_normalized=pupil_coordinates_normalized,
        )
