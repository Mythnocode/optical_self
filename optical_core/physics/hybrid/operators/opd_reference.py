
# 包括主光线、公共平面和参考球。
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optical_core.coordinates import Z_INDEX
from optical_core.models.representations.trace import TraceBundle


@dataclass(frozen=True, slots=True)
class OPDSamples:
    opd_mm: np.ndarray
    valid_mask: np.ndarray
    chief_index: int
    reference_type: str
    reference_image_point_mm: np.ndarray | None = None


def chief_ray_index(trace: TraceBundle) -> int:
    valid = np.asarray(trace.valid_mask, dtype=bool)
    if not np.any(valid):
        return -1
    indices = np.flatnonzero(valid)
    pupil = getattr(trace, "pupil_coordinates_normalized", None)
    if pupil is not None:
        coords = np.asarray(pupil, dtype=float)
        rho2 = np.sum(coords[indices] ** 2, axis=1)
        return int(indices[int(np.argmin(rho2))])
    dirs = np.asarray(trace.final_directions, dtype=float)[indices]
    unit = dirs / np.linalg.norm(dirs, axis=1)[:, None]
    return int(indices[int(np.argmax(unit[:, Z_INDEX]))])


def common_plane_relative_opl(trace: TraceBundle) -> OPDSamples:


    opl = np.asarray(trace.optical_paths_mm, dtype=float)
    valid = np.asarray(trace.valid_mask, dtype=bool) & np.isfinite(opl)
    chief = chief_ray_index(trace)
    result = np.full(opl.shape, np.nan, dtype=float)
    if chief >= 0 and valid[chief]:
        result[valid] = opl[valid] - opl[chief]
    return OPDSamples(result, valid, chief, "common_plane_relative_opl")


def _last_physical_record(trace: TraceBundle):
    records = dict(getattr(trace, "surface_records", {}) or {})
    physical = []
    for key, value in records.items():
        if key == "image":
            continue
        if key.startswith("surface_"):
            try:
                number = int(key.split("_", 1)[1])
            except Exception:
                number = 0
            physical.append((number, value))
    if not physical:
        return None
    return max(physical, key=lambda item: item[0])[1]


def reference_sphere_opd(
    trace: TraceBundle,
    *,
    image_refractive_index: float = 1.0,
    reference_image_point_mm: np.ndarray | None = None,
) -> OPDSamples:


    record = _last_physical_record(trace)
    n_rays = int(np.asarray(trace.final_positions_mm).shape[0])
    empty = np.full(n_rays, np.nan, dtype=float)
    chief = chief_ray_index(trace)
    if record is None or chief < 0:
        return OPDSamples(empty, np.zeros(n_rays, dtype=bool), chief, "reference_sphere_unavailable")

    points = np.asarray(record.positions_mm, dtype=float)
    opl_last = np.asarray(record.optical_paths_mm, dtype=float)
    valid = np.asarray(record.valid_mask, dtype=bool)
    valid &= np.all(np.isfinite(points), axis=1) & np.isfinite(opl_last)
    if reference_image_point_mm is None:
        final = np.asarray(trace.final_positions_mm, dtype=float)
        if chief < final.shape[0] and np.all(np.isfinite(final[chief])):
            q = final[chief].copy()
        else:
            q = np.nanmean(final[np.asarray(trace.valid_mask, dtype=bool)], axis=0)
    else:
        q = np.asarray(reference_image_point_mm, dtype=float).reshape(3)

    equivalent = np.full(n_rays, np.nan, dtype=float)
    equivalent[valid] = opl_last[valid] + float(image_refractive_index) * np.linalg.norm(
        q[None, :] - points[valid], axis=1
    )
    opd = np.full(n_rays, np.nan, dtype=float)
    if valid[chief]:
        
        
        
        opd[valid] = equivalent[chief] - equivalent[valid]
    return OPDSamples(opd, valid, chief, "explicit_reference_sphere", q)


__all__ = [
    "OPDSamples",
    "chief_ray_index",
    "common_plane_relative_opl",
    "reference_sphere_opd",
]
