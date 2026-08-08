# 计算点列图。

from __future__ import annotations

import numpy as np


def weighted_spot_metrics(
    x_um: np.ndarray,
    y_um: np.ndarray,
    weights: np.ndarray | None = None,
    valid_mask: np.ndarray | None = None,
) -> dict[str, float]:
    x = np.asarray(x_um, dtype=float).reshape(-1)
    y = np.asarray(y_um, dtype=float).reshape(-1)
    if x.shape != y.shape:
        raise ValueError("x_um and y_um must have the same shape.")

    if weights is None:
        w = np.ones_like(x, dtype=float)
    else:
        w = np.asarray(weights, dtype=float).reshape(-1)
        if w.shape != x.shape:
            raise ValueError("weights must have the same shape as y_um.")

    if valid_mask is None:
        valid = np.ones_like(x, dtype=bool)
    else:
        valid = np.asarray(valid_mask, dtype=bool).reshape(-1)
        if valid.shape != x.shape:
            raise ValueError("valid_mask must have the same shape as y_um.")

    finite = (
        valid
        & np.isfinite(x)
        & np.isfinite(y)
        & np.isfinite(w)
        & (w > 0.0)
    )
    if not np.any(finite):
        return {
            "spot_total_integration_weight.a.u.": 0.0,
            "spot_centroid_x_um": float("nan"),
            "spot_centroid_y_um": float("nan"),
            "rms_spot_x_um": float("nan"),
            "rms_spot_y_um": float("nan"),
            "rms_spot_radius_um": float("nan"),
            "spot_valid_ray_count": 0.0,
            "spot_total_ray_count": float(x.size),
        }

    xf = x[finite]
    yf = y[finite]
    wf = w[finite]
    total = float(np.sum(wf))
    x0 = float(np.sum(xf * wf) / total)
    y0 = float(np.sum(yf * wf) / total)
    dx2 = np.square(xf - x0)
    dy2 = np.square(yf - y0)
    rms_x = float(np.sqrt(np.sum(wf * dx2) / total))
    rms_y = float(np.sqrt(np.sum(wf * dy2) / total))
    rms_r = float(np.sqrt(np.sum(wf * (dx2 + dy2)) / total))
    return {
        "spot_total_integration_weight.a.u.": total,
        "spot_centroid_x_um": x0,
        "spot_centroid_y_um": y0,
        "rms_spot_x_um": rms_x,
        "rms_spot_y_um": rms_y,
        "rms_spot_radius_um": rms_r,
        "spot_valid_ray_count": float(np.count_nonzero(finite)),
        "spot_total_ray_count": float(x.size),
    }


def weighted_spot_metrics_mm(
    x_mm: np.ndarray,
    y_mm: np.ndarray,
    weights: np.ndarray | None = None,
    valid_mask: np.ndarray | None = None,
) -> dict[str, float]:
    return weighted_spot_metrics(
        np.asarray(x_mm, dtype=float) * 1000.0,
        np.asarray(y_mm, dtype=float) * 1000.0,
        weights,
        valid_mask,
    )


def rms_spot_metrics(
    x_um: np.ndarray,
    y_um: np.ndarray,
    weights: np.ndarray | None = None,
) -> dict[str, float]:


    return weighted_spot_metrics(x_um, y_um, weights)


__all__ = ["weighted_spot_metrics", "weighted_spot_metrics_mm", "rms_spot_metrics"]
