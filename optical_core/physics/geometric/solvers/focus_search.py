

from __future__ import annotations

import numpy as np

from optical_core.models.representations.trace import TraceBundle
from optical_core.physics.geometric.analyses.spot.metrics import weighted_spot_metrics_mm


def ray_points_at_plane(trace: TraceBundle, z_mm: float) -> tuple[np.ndarray, np.ndarray]:
    pos = np.asarray(trace.final_positions_mm, dtype=float)
    dirs = np.asarray(trace.final_directions, dtype=float)
    valid = np.asarray(trace.valid_mask, dtype=bool)
    valid &= np.all(np.isfinite(pos), axis=1)
    valid &= np.all(np.isfinite(dirs), axis=1)
    valid &= np.abs(dirs[:, 2]) > 1.0e-14
    points = np.full_like(pos, np.nan, dtype=float)
    if np.any(valid):
        t = (float(z_mm) - pos[valid, 2]) / dirs[valid, 2]
        points[valid] = pos[valid] + t[:, None] * dirs[valid]
    return points, valid


def spot_metrics_at_plane(trace: TraceBundle, z_mm: float) -> dict[str, float]:
    points, valid = ray_points_at_plane(trace, z_mm)
    return weighted_spot_metrics_mm(
        points[:, 0],
        points[:, 1],
        trace.integration_weights,
        valid,
    )


def rms_radius_at_plane(trace: TraceBundle, z_mm: float) -> float:
    value_um = float(spot_metrics_at_plane(trace, z_mm)["rms_spot_radius_um"])
    return value_um / 1000.0 if np.isfinite(value_um) else float("nan")


def fit_best_focus_continuous(
    z_candidates_mm: np.ndarray,
    rms_radius_mm: np.ndarray,
    *,
    neighbor_count: int = 5,
) -> dict[str, float | int | bool]:


    z = np.asarray(z_candidates_mm, dtype=float).reshape(-1)
    rms = np.asarray(rms_radius_mm, dtype=float).reshape(-1)
    valid = np.isfinite(z) & np.isfinite(rms) & (rms >= 0.0)
    if np.count_nonzero(valid) < 3:
        return {
            "best_focus_z_mm": float("nan"),
            "best_focus_rms_radius_mm": float("nan"),
            "fit_success": False,
            "fit_point_count": 0,
        }
    z = z[valid]
    rms = rms[valid]
    order = np.argsort(z)
    z = z[order]
    rms = rms[order]
    minimum_index = int(np.argmin(rms))
    half = max(1, int(neighbor_count) // 2)
    left = max(0, minimum_index - half)
    right = min(z.size, minimum_index + half + 1)
    while right - left < 3:
        if left > 0:
            left -= 1
        elif right < z.size:
            right += 1
        else:
            break
    zf = z[left:right]
    yf = np.square(rms[left:right])
    if zf.size < 3 or np.ptp(zf) <= 0.0:
        return {
            "best_focus_z_mm": float(z[minimum_index]),
            "best_focus_rms_radius_mm": float(rms[minimum_index]),
            "fit_success": False,
            "fit_point_count": int(zf.size),
        }
    coefficients = np.polyfit(zf, yf, deg=2)
    a, b, c = map(float, coefficients)
    if not np.isfinite(a) or a <= 0.0:
        return {
            "best_focus_z_mm": float(z[minimum_index]),
            "best_focus_rms_radius_mm": float(rms[minimum_index]),
            "fit_success": False,
            "fit_point_count": int(zf.size),
        }
    best_z = -b / (2.0 * a)
    
    best_z = float(np.clip(best_z, np.min(zf), np.max(zf)))
    best_rms2 = max(a * best_z * best_z + b * best_z + c, 0.0)
    return {
        "best_focus_z_mm": best_z,
        "best_focus_rms_radius_mm": float(np.sqrt(best_rms2)),
        "fit_success": True,
        "fit_point_count": int(zf.size),
        "fit_a": a,
        "fit_b": b,
        "fit_c": c,
        "sampled_minimum_z_mm": float(z[minimum_index]),
        "sampled_minimum_rms_radius_mm": float(rms[minimum_index]),
        "minimum_at_scan_boundary": bool(minimum_index in {0, z.size - 1}),
    }


def find_best_focus(trace: TraceBundle, z_candidates_mm: np.ndarray) -> tuple[float, float]:
    values = np.asarray([rms_radius_at_plane(trace, z) for z in z_candidates_mm], dtype=float)
    fitted = fit_best_focus_continuous(np.asarray(z_candidates_mm, dtype=float), values)
    return float(fitted["best_focus_z_mm"]), float(fitted["best_focus_rms_radius_mm"])


__all__ = [
    "ray_points_at_plane",
    "spot_metrics_at_plane",
    "rms_radius_at_plane",
    "fit_best_focus_continuous",
    "find_best_focus",
]
