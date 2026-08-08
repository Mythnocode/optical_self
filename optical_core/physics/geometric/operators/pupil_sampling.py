# 在圆形入瞳内采样，生成入瞳光线。

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np

from optical_core.models.representations.ray_bundle import RayBundle


def normalized_disk_grid(sample_count: int, *, edge_fraction: float = 1.0) -> tuple[np.ndarray, np.ndarray]:

    n_side = max(1, int(sample_count))
    edge = float(edge_fraction)
    if not np.isfinite(edge) or edge <= 0.0 or edge > 1.0 + 1.0e-12:
        raise ValueError("edge_fraction 必须位于 (0, 1]。")
    if n_side == 1:
        return np.array([0.0]), np.array([0.0])
    axis = np.linspace(-edge, edge, n_side, dtype=float)
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    mask = xx * xx + yy * yy <= edge * edge + 1.0e-12
    if not np.any(mask):
        return np.array([0.0]), np.array([0.0])
    return xx[mask], yy[mask]


def _normalise_directions(directions: np.ndarray) -> np.ndarray:
    dirs = np.asarray(directions, dtype=float)
    norms = np.linalg.norm(dirs, axis=1)
    if np.any(~np.isfinite(norms)) or np.any(norms <= 0.0):
        raise ValueError("光线方向包含无效向量。")
    return dirs / norms[:, None]


def gaussian_apodization_intensity(rho: np.ndarray, factor: float | None) -> np.ndarray:

    if factor is None or abs(float(factor)) <= 1.0e-15:
        return np.ones_like(rho, dtype=float)
    return np.exp(-2.0 * float(factor) * np.asarray(rho, dtype=float) ** 2)


def gaussian_apodization_amplitude(rho: np.ndarray, factor: float | None) -> np.ndarray:

    if factor is None or abs(float(factor)) <= 1.0e-15:
        return np.ones_like(rho, dtype=float)
    return np.exp(-float(factor) * np.asarray(rho, dtype=float) ** 2)


def gaussian_apodization_amplitude_xy(
    pupil_x_normalized: np.ndarray,
    pupil_y_normalized: np.ndarray,
    factor_x: float | None,
    factor_y: float | None,
) -> np.ndarray:


    gx = 0.0 if factor_x is None else float(factor_x)
    gy = gx if factor_y is None else float(factor_y)
    if gx < 0.0 or gy < 0.0 or not np.isfinite(gx) or not np.isfinite(gy):
        raise ValueError("Gaussian apodization factors must be finite and non-negative.")
    return np.exp(-gx * np.asarray(pupil_x_normalized, dtype=float) ** 2 - gy * np.asarray(pupil_y_normalized, dtype=float) ** 2)


def gaussian_apodization_intensity_xy(
    pupil_x_normalized: np.ndarray,
    pupil_y_normalized: np.ndarray,
    factor_x: float | None,
    factor_y: float | None,
) -> np.ndarray:


    amplitude = gaussian_apodization_amplitude_xy(
        pupil_x_normalized, pupil_y_normalized, factor_x, factor_y
    )
    return np.square(amplitude)


def _coerce_explicit_samples(
    samples: Sequence[dict[str, Any]] | np.ndarray | None,
    *,
    pupil_x_normalized: Iterable[float] | None,
    pupil_y_normalized: Iterable[float] | None,
    power_weights: Iterable[float] | None,
    quadrature_weights: Iterable[float] | None,
    ray_ids: Iterable[str] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if samples is not None:
        if isinstance(samples, np.ndarray):
            arr = np.asarray(samples, dtype=float)
            if arr.ndim != 2 or arr.shape[1] < 2:
                raise ValueError("显式光瞳数组必须为 (N,2)、(N,3) 或 (N,4)。")
            px, py = arr[:, 0], arr[:, 1]
            p_weights = arr[:, 2] if arr.shape[1] >= 3 else None
            q_weights = arr[:, 3] if arr.shape[1] >= 4 else None
            ids = None
        else:
            px_values: list[float] = []
            py_values: list[float] = []
            p_values: list[float] = []
            q_values: list[float] = []
            id_values: list[str] = []
            has_power = True
            has_quadrature = True
            for index, item in enumerate(samples):
                
                px_values.append(float(item.get("pupil_x", item.get("px", 0.0))))
                py_values.append(float(item.get("pupil_y", item.get("py", 0.0))))
                p_value = item.get("power_weight", item.get("intensity", item.get("weight")))
                q_value = item.get("quadrature_weight")
                if p_value is None:
                    has_power = False
                    p_values.append(1.0)
                else:
                    p_values.append(float(p_value))
                if q_value is None:
                    has_quadrature = False
                    q_values.append(1.0)
                else:
                    q_values.append(float(q_value))
                id_values.append(str(item.get("ray_id", f"R{index:06d}")))
            px, py = np.asarray(px_values), np.asarray(py_values)
            p_weights = np.asarray(p_values) if has_power else None
            q_weights = np.asarray(q_values) if has_quadrature else None
            ids = np.asarray(id_values, dtype=object)
    else:
        if pupil_x_normalized is None or pupil_y_normalized is None:
            raise ValueError("必须提供 samples 或 pupil_x_normalized/pupil_y_normalized。")
        px = np.asarray(list(pupil_x_normalized), dtype=float).reshape(-1)
        py = np.asarray(list(pupil_y_normalized), dtype=float).reshape(-1)
        p_weights = None if power_weights is None else np.asarray(list(power_weights), dtype=float).reshape(-1)
        q_weights = None if quadrature_weights is None else np.asarray(list(quadrature_weights), dtype=float).reshape(-1)
        ids = None if ray_ids is None else np.asarray(list(ray_ids), dtype=object).reshape(-1)
    if px.shape != py.shape:
        raise ValueError("显式 pupil_x 与 pupil_y 长度必须一致。")
    n = px.size
    for name, value in {"power_weights": p_weights, "quadrature_weights": q_weights, "ray_ids": ids}.items():
        if value is not None and value.shape != (n,):
            raise ValueError(f"显式光线 {name} 长度必须与光瞳坐标一致。")
    rho2 = px * px + py * py
    if np.any(~np.isfinite(rho2)) or np.any(rho2 > 1.0 + 1.0e-10):
        raise ValueError("显式归一化光瞳坐标必须有限且位于单位圆内。")
    return px, py, p_weights, q_weights, ids


def sample_explicit_pupil_rays(
    *,
    pupil_radius_mm: float,
    wavelength_nm: float,
    samples: Sequence[dict[str, Any]] | np.ndarray | None = None,
    pupil_x_normalized: Iterable[float] | None = None,
    pupil_y_normalized: Iterable[float] | None = None,
    power_weights: Iterable[float] | None = None,
    quadrature_weights: Iterable[float] | None = None,
    ray_ids: Iterable[str] | None = None,
    start_z_mm: float = -1.0e-6,
    source_model: str = "parallel_pupil",
    object_distance_mm: float | None = None,
    object_space_na: float | None = None,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    beam_quality_m2: float = 1.0,
    apodization_type: str | None = None,
    apodization_factor: float | None = None,
    apodization_factor_x: float | None = None,
    apodization_factor_y: float | None = None,
    source_wavefront_radius_x_mm: float | None = None,
    source_wavefront_radius_y_mm: float | None = None,
    include_source_to_pupil_opl: bool = False,
) -> RayBundle:

    if not np.isfinite(float(beam_quality_m2)) or float(beam_quality_m2) < 1.0:
        raise ValueError("beam_quality_m2 must be finite and >= 1.0")
    px, py, explicit_power, explicit_quadrature, explicit_ids = _coerce_explicit_samples(
        samples,
        pupil_x_normalized=pupil_x_normalized,
        pupil_y_normalized=pupil_y_normalized,
        power_weights=power_weights,
        quadrature_weights=quadrature_weights,
        ray_ids=ray_ids,
    )
    pupil_radius = float(pupil_radius_mm)
    if not np.isfinite(pupil_radius) or pupil_radius <= 0.0:
        raise ValueError("pupil_radius_mm 必须为正有限数。")
    x = px * pupil_radius
    y = py * pupil_radius
    positions = np.column_stack([x, y, np.full_like(x, float(start_z_mm))])

    model = str(source_model or "parallel_pupil").strip().lower()
    initial_opl = np.zeros(px.size, dtype=float)
    if model in {"object_space_na", "finite_object_na"}:
        if object_distance_mm is not None and float(object_distance_mm) > 0.0:
            obj_dist = float(object_distance_mm)
        elif object_space_na is not None and float(object_space_na) > 0.0:
            na = min(max(float(object_space_na), 1.0e-12), 0.999999)
            obj_dist = pupil_radius * math.sqrt(max(1.0 - na * na, 1.0e-30)) / na
        else:
            obj_dist = 1.0
        object_point = np.array([0.0, 0.0, -obj_dist], dtype=float)
        vectors = positions - object_point[None, :]
        directions = _normalise_directions(vectors)
        if include_source_to_pupil_opl:
            distances = np.linalg.norm(vectors, axis=1)
            chief = int(np.argmin(px * px + py * py)) if px.size else 0
            initial_opl = distances - distances[chief]
    elif model in {"parallel_pupil", "parallel", "collimated", "gaussian"}:
        tx = math.tan(math.radians(float(field_x_deg)))
        ty = math.tan(math.radians(float(field_y_deg)))
        directions = _normalise_directions(
            np.tile(np.array([[tx, ty, 1.0]], dtype=float), (positions.shape[0], 1))
        )
    else:
        raise ValueError(f"unknown source_model: {source_model!r}")

    
    
    
    
    rx = source_wavefront_radius_x_mm
    ry = rx if source_wavefront_radius_y_mm is None else source_wavefront_radius_y_mm
    for coordinate, radius in ((x, rx), (y, ry)):
        if radius is None:
            continue
        radius_value = float(radius)
        if not math.isfinite(radius_value):
            continue
        if abs(radius_value) <= 1.0e-15:
            raise ValueError("source wavefront radius must be non-zero or infinite")
        initial_opl += coordinate * coordinate / (2.0 * radius_value)

    rho = np.sqrt(px * px + py * py)
    apo_type = str(apodization_type or "").strip().lower()
    if explicit_power is not None:
        p_weights = np.asarray(explicit_power, dtype=float)
        field_amplitudes = np.sqrt(np.clip(p_weights, 0.0, None))
    elif "gaussian" in apo_type:
        factor_x = apodization_factor if apodization_factor_x is None else apodization_factor_x
        factor_y = factor_x if apodization_factor_y is None else apodization_factor_y
        field_amplitudes = gaussian_apodization_amplitude_xy(px, py, factor_x, factor_y)
        p_weights = gaussian_apodization_intensity_xy(px, py, factor_x, factor_y)
    else:
        field_amplitudes = np.ones(px.size, dtype=float)
        p_weights = np.ones(px.size, dtype=float)
    q_weights = np.ones(px.size, dtype=float) if explicit_quadrature is None else np.asarray(explicit_quadrature, dtype=float)
    ids = explicit_ids if explicit_ids is not None else np.asarray([f"R{i:06d}" for i in range(px.size)], dtype=object)

    return RayBundle(
        positions_mm=positions,
        directions=directions,
        field_amplitudes=field_amplitudes,
        optical_paths_mm=initial_opl,
        valid_mask=np.ones(px.size, dtype=bool),
        power_weights=p_weights,
        quadrature_weights=q_weights,
        ray_ids=ids,
        pupil_coordinates_normalized=np.column_stack([px, py]),
    )


def sample_pupil_grid(
    *,
    pupil_radius_mm: float,
    sample_count: int,
    wavelength_nm: float,
    start_z_mm: float = -1.0e-6,
    source_model: str = "parallel_pupil",
    object_distance_mm: float | None = None,
    object_space_na: float | None = None,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    beam_quality_m2: float = 1.0,
    apodization_type: str | None = None,
    apodization_factor: float | None = None,
    apodization_factor_x: float | None = None,
    apodization_factor_y: float | None = None,
    source_wavefront_radius_x_mm: float | None = None,
    source_wavefront_radius_y_mm: float | None = None,
    include_source_to_pupil_opl: bool = False,
) -> RayBundle:
    px, py = normalized_disk_grid(sample_count)
    return sample_explicit_pupil_rays(
        pupil_radius_mm=pupil_radius_mm,
        wavelength_nm=wavelength_nm,
        pupil_x_normalized=px,
        pupil_y_normalized=py,
        start_z_mm=start_z_mm,
        source_model=source_model,
        object_distance_mm=object_distance_mm,
        object_space_na=object_space_na,
        field_x_deg=field_x_deg,
        field_y_deg=field_y_deg,
        beam_quality_m2=beam_quality_m2,
        apodization_type=apodization_type,
        apodization_factor=apodization_factor,
        apodization_factor_x=apodization_factor_x,
        apodization_factor_y=apodization_factor_y,
        source_wavefront_radius_x_mm=source_wavefront_radius_x_mm,
        source_wavefront_radius_y_mm=source_wavefront_radius_y_mm,
        include_source_to_pupil_opl=include_source_to_pupil_opl,
    )


__all__ = [
    "normalized_disk_grid",
    "gaussian_apodization_amplitude",
    "gaussian_apodization_intensity",
    "gaussian_apodization_amplitude_xy",
    "gaussian_apodization_intensity_xy",
    "sample_explicit_pupil_rays",
    "sample_pupil_grid",
]
