from __future__ import annotations

"""CCD detector closed loop on top of formal geometric raytrace results.

RayResult (final pupil samples at the image plane) → intensity matrix + RMS.
Uses the same second-moment definitions as optical_core spot metrics; does not
invent a second ray engine.
"""

from typing import Any, Mapping, Sequence

import numpy as np

from optical_core.physics.geometric.analyses.spot.metrics import weighted_spot_metrics_mm


DEFAULT_CCD_SCAN_POSITIONS_MM = (10.0, 15.0, 17.5, 27.5, 37.5)


def parse_scan_positions_mm(raw: Any, default: Sequence[float] = DEFAULT_CCD_SCAN_POSITIONS_MM) -> tuple[float, ...]:
    if raw is None or raw == "":
        return tuple(float(v) for v in default)
    if isinstance(raw, (list, tuple)):
        values = [float(v) for v in raw]
        return tuple(values) if values else tuple(float(v) for v in default)
    text = str(raw).replace(";", ",")
    values = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return tuple(values) if values else tuple(float(v) for v in default)


def intensity_matrix_from_positions(
    positions_mm: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    valid_mask: np.ndarray | None = None,
    grid_size: int = 64,
    half_extent_mm: float | None = None,
) -> dict[str, Any]:
    """Bin ray hits into a simple intensity matrix on the CCD plane."""
    pts = np.asarray(positions_mm, dtype=float).reshape(-1, 3) if np.asarray(positions_mm).ndim == 2 else np.asarray(positions_mm, dtype=float)
    if pts.ndim == 1:
        pts = pts.reshape(-1, 3) if pts.size % 3 == 0 else np.zeros((0, 3))
    if pts.shape[0] == 0:
        size = int(grid_size)
        return {
            "intensity": [[0.0] * size for _ in range(size)],
            "grid_x_mm": list(np.linspace(-1.0, 1.0, size)),
            "grid_y_mm": list(np.linspace(-1.0, 1.0, size)),
            "half_extent_mm": 1.0,
        }
    x = pts[:, 0]
    y = pts[:, 1]
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool).reshape(-1)
        x = x[mask]
        y = y[mask]
        if weights is not None:
            weights = np.asarray(weights, dtype=float).reshape(-1)[mask]
    if weights is None:
        w = np.ones_like(x, dtype=float)
    else:
        w = np.asarray(weights, dtype=float).reshape(-1)
    if x.size == 0:
        size = int(grid_size)
        return {
            "intensity": [[0.0] * size for _ in range(size)],
            "grid_x_mm": list(np.linspace(-1.0, 1.0, size)),
            "grid_y_mm": list(np.linspace(-1.0, 1.0, size)),
            "half_extent_mm": 1.0,
        }
    span = float(half_extent_mm) if half_extent_mm and half_extent_mm > 0 else max(
        0.05, 1.5 * float(np.percentile(np.hypot(x, y), 95))
    )
    size = max(8, int(grid_size))
    hist, xedges, yedges = np.histogram2d(
        x, y, bins=size, range=[[-span, span], [-span, span]], weights=w
    )
    # histogram2d returns [x_bin, y_bin]; display as row=y, col=x
    intensity = hist.T
    return {
        "intensity": intensity.astype(float).tolist(),
        "grid_x_mm": list(0.5 * (xedges[:-1] + xedges[1:])),
        "grid_y_mm": list(0.5 * (yedges[:-1] + yedges[1:])),
        "half_extent_mm": span,
    }


def ccd_metrics_from_ray_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Extract RMS_x / RMS_y / radial RMS + intensity matrix from a raytrace result."""
    arrays = dict(result.get("arrays", {}) or {})
    metrics = dict(result.get("metrics", {}) or {})
    positions = np.asarray(arrays.get("raytrace_final_positions_mm", []), dtype=float)
    if positions.ndim == 1 and positions.size:
        positions = positions.reshape(-1, 3)
    valid = np.asarray(arrays.get("raytrace_valid_mask", []), dtype=bool)
    weights = np.asarray(arrays.get("raytrace_power_weights", []), dtype=float)
    if positions.size == 0:
        return {
            "valid": False,
            "rms_x_um": float("nan"),
            "rms_y_um": float("nan"),
            "radial_rms_um": float("nan"),
            "centroid_x_um": float("nan"),
            "centroid_y_um": float("nan"),
            "intensity_matrix": intensity_matrix_from_positions(np.zeros((0, 3))),
            "metric_source": "正式几何追迹（无有效击中）",
            "spot_valid_ray_count": 0,
        }
    if valid.size != positions.shape[0]:
        valid = np.ones(positions.shape[0], dtype=bool)
    if weights.size != positions.shape[0]:
        weights = np.ones(positions.shape[0], dtype=float)
    spot = weighted_spot_metrics_mm(positions[:, 0], positions[:, 1], weights, valid)
    matrix = intensity_matrix_from_positions(positions, weights=weights, valid_mask=valid)
    return {
        "valid": int(spot.get("spot_valid_ray_count", 0) or 0) > 0,
        "rms_x_um": float(spot.get("rms_spot_x_um", float("nan"))),
        "rms_y_um": float(spot.get("rms_spot_y_um", float("nan"))),
        "radial_rms_um": float(spot.get("rms_spot_radius_um", float("nan"))),
        "centroid_x_um": float(spot.get("spot_centroid_x_um", float("nan"))),
        "centroid_y_um": float(spot.get("spot_centroid_y_um", float("nan"))),
        "radius_x_um": float(spot.get("rms_spot_x_um", float("nan"))) * 2.0,
        "radius_y_um": float(spot.get("rms_spot_y_um", float("nan"))) * 2.0,
        "intensity_matrix": matrix,
        "metric_source": "正式几何追迹 · ISO 11146 二阶矩",
        "spot_valid_ray_count": int(spot.get("spot_valid_ray_count", 0) or 0),
        "engine_rms_spot_radius_mm": metrics.get("rms_spot_radius_mm"),
    }


def evaluate_ccd_scan(
    evaluate_at_offset_mm,
    positions_mm: Sequence[float],
) -> list[dict[str, Any]]:
    """Run ``evaluate_at_offset_mm(z)`` for each CCD plane and attach z to metrics."""
    rows: list[dict[str, Any]] = []
    for z_mm in positions_mm:
        body = evaluate_at_offset_mm(float(z_mm))
        if not isinstance(body, Mapping):
            rows.append({"plane_offset_mm": float(z_mm), "valid": False})
            continue
        row = ccd_metrics_from_ray_result(body)
        row["plane_offset_mm"] = float(z_mm)
        rows.append(row)
    return rows


__all__ = [
    "DEFAULT_CCD_SCAN_POSITIONS_MM",
    "ccd_metrics_from_ray_result",
    "evaluate_ccd_scan",
    "intensity_matrix_from_positions",
    "parse_scan_positions_mm",
]
