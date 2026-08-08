


from __future__ import annotations

import numpy as np


def _normalise_rows(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(vectors, dtype=float)
    squared_norms = (
        values[:, 0] * values[:, 0]
        + values[:, 1] * values[:, 1]
        + values[:, 2] * values[:, 2]
    )
    norms = np.sqrt(np.maximum(squared_norms, 0.0))
    valid = np.isfinite(norms) & (norms > 0.0)
    result = np.full_like(values, np.nan, dtype=float)
    np.divide(values, norms[:, None], out=result, where=valid[:, None])
    return result, valid


def _sag_derivative_vector(
    radius: np.ndarray,
    curvature: float,
    conic_q: float,
    coefficients: tuple[float, ...],
) -> tuple[np.ndarray, np.ndarray]:
    product = curvature * radius
    radicand = 1.0 - conic_q * product * product
    valid = np.isfinite(radicand) & (radicand > 0.0)
    derivative = np.zeros_like(radius, dtype=float)
    nonzero = radius > 1.0e-16
    usable = valid & nonzero
    derivative[usable] = curvature * radius[usable] / np.sqrt(radicand[usable])
    radius_squared = radius * radius
    power = radius * radius_squared
    order = 2
    for coefficient in coefficients:
        derivative = derivative + 2.0 * order * float(coefficient) * power
        power = power * radius_squared
        order += 1
    derivative[~nonzero] = 0.0
    valid |= ~nonzero
    valid &= np.isfinite(derivative)
    return derivative, valid


def _surface_normals_batch(
    points: np.ndarray,
    *,
    is_plane: bool,
    curvature: float,
    conic_q: float,
    coefficients: tuple[float, ...],
) -> tuple[np.ndarray, np.ndarray]:
    normals = np.zeros_like(points, dtype=float)
    normals[:, 2] = 1.0
    if is_plane:
        return normals, np.ones(points.shape[0], dtype=bool)
    x = points[:, 0]
    y = points[:, 1]
    radius = np.sqrt(x * x + y * y)
    derivative, derivative_valid = _sag_derivative_vector(radius, curvature, conic_q, coefficients)
    nonzero = radius > 1.0e-15
    slope_scale = np.zeros_like(radius)
    np.divide(-derivative, radius, out=slope_scale, where=nonzero)
    normal_x = slope_scale * x
    normal_y = slope_scale * y
    inverse_norm = 1.0 / np.sqrt(1.0 + normal_x * normal_x + normal_y * normal_y)
    normal_valid = derivative_valid & np.isfinite(inverse_norm)
    normals[:, 0] = normal_x * inverse_norm
    normals[:, 1] = normal_y * inverse_norm
    normals[:, 2] = inverse_norm
    normals[~normal_valid] = np.nan
    return normals, normal_valid


def _fresnel_from_cosine_vector(cosine_incident: np.ndarray, n1: float, n2: float) -> np.ndarray:
    """非偏振界面功率透过率。"""
    if abs(n1 - n2) <= 1.0e-15 * max(abs(n1), abs(n2), 1.0):
        return np.ones_like(cosine_incident, dtype=float)
    cos_i = np.clip(np.asarray(cosine_incident, dtype=float), 0.0, 1.0)
    ratio = float(n1) / float(n2)
    sin_t_squared = ratio * ratio * np.maximum(0.0, 1.0 - cos_i * cos_i)
    total_internal = sin_t_squared >= 1.0
    cos_t = np.sqrt(np.maximum(0.0, 1.0 - sin_t_squared))
    denominator_s = n1 * cos_i + n2 * cos_t
    denominator_p = n1 * cos_t + n2 * cos_i
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        rs = np.square((n1 * cos_i - n2 * cos_t) / denominator_s)
        rp = np.square((n1 * cos_t - n2 * cos_i) / denominator_p)
    result = np.clip(1.0 - 0.5 * (rs + rp), 0.0, 1.0)
    result[total_internal | ~np.isfinite(result)] = 0.0
    return result


def refract_direction(
    incident_dir: np.ndarray,
    normal: np.ndarray,
    n1: float,
    n2: float,
) -> tuple[np.ndarray, bool]:
    """计算单根光线的折射方向。"""
    incident = np.asarray(incident_dir, dtype=float).reshape(1, 3)
    normals = np.asarray(normal, dtype=float).reshape(1, 3)
    outgoing, _, tir, valid = _refract_with_normals(incident, normals, n1=n1, n2=n2, evaluate_interface_transmission=False)
    return outgoing[0], bool(valid[0] and not tir[0])


def _refract_with_normals(
    incident: np.ndarray,
    normals: np.ndarray,
    *,
    n1: float,
    n2: float,
    evaluate_interface_transmission: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    dot = (
        incident[:, 0] * normals[:, 0]
        + incident[:, 1] * normals[:, 1]
        + incident[:, 2] * normals[:, 2]
    )
    flip = dot < 0.0
    normals = normals.copy()
    normals[flip] *= -1.0
    cosine_incident = np.clip(np.abs(dot), 0.0, 1.0)
    ratio = float(n1) / float(n2)
    tangent_squared = ratio * ratio * np.maximum(0.0, 1.0 - cosine_incident * cosine_incident)
    tir = tangent_squared > 1.0 + 1.0e-12
    tangent_squared = np.minimum(tangent_squared, 1.0)
    normal_component = np.sqrt(np.maximum(0.0, 1.0 - tangent_squared))
    normal_scale = normal_component - ratio * cosine_incident
    outgoing = ratio * incident + normal_scale[:, None] * normals
    outgoing, direction_valid = _normalise_rows(outgoing)
    if evaluate_interface_transmission:
        interface_tau = _fresnel_from_cosine_vector(cosine_incident, n1, n2)
    else:
        interface_tau = np.ones(incident.shape[0], dtype=float)
    return outgoing, interface_tau, tir, direction_valid & ~tir


def _refract_batch(
    incident: np.ndarray,
    points: np.ndarray,
    *,
    is_plane: bool,
    curvature: float,
    conic_q: float,
    coefficients: tuple[float, ...],
    n1: float,
    n2: float,
    evaluate_interface_transmission: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:

    normals, normal_valid = _surface_normals_batch(
        points,
        is_plane=is_plane,
        curvature=curvature,
        conic_q=conic_q,
        coefficients=coefficients,
    )
    outgoing, interface_tau, tir, direction_valid = _refract_with_normals(
        np.asarray(incident, dtype=float),
        normals,
        n1=n1,
        n2=n2,
        evaluate_interface_transmission=evaluate_interface_transmission,
    )
    valid = normal_valid & direction_valid & ~tir
    return outgoing, interface_tau, tir, valid
