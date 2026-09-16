
"""光学元件几何生成与空间布局工具。

本模块只生成可绘制的点、线、面和包围盒等几何数据；颜色、线宽和交互状态
由上层渲染器及样式模块决定。
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Mapping

import numpy as np

_SPECIAL_TOKENS = (
    "aperture",
    "stop",
    "光阑",
    "detector",
    "image",
    "像面",
    "探测器",
    "coordinate",
    "坐标断点",
)


def is_optical_surface(surface: Mapping) -> bool:

    if not bool(surface.get("enabled", True)):
        return False
    surface_type = str(surface.get("type", surface.get("surface_type", ""))).lower()
    name = str(surface.get("name", "")).lower()
    text = f"{surface_type} {name}"
    return not any(token in text for token in _SPECIAL_TOKENS)


def infer_lens_groups(surfaces: Iterable[Mapping]) -> list[dict]:

    items = [dict(surface) for surface in surfaces if is_optical_surface(surface)]
    if not items:
        return []

    explicit: "OrderedDict[str, list[dict]]" = OrderedDict()
    ungrouped: list[dict] = []
    for item in items:
        group_id = str(item.get("group_id", "") or "").strip()
        if group_id and group_id.upper() not in {"AIR", "IMAGE", "STOP"}:
            explicit.setdefault(group_id, []).append(item)
        else:
            ungrouped.append(item)

    result: list[dict] = []
    used_indices: set[int] = set()
    lens_number = 1

    for group_id, group_items in explicit.items():
        ordered = sorted(group_items, key=lambda value: float(value.get("z", 0.0) or 0.0))
        indices = [int(value.get("surface_index", -1)) for value in ordered]
        used_indices.update(index for index in indices if index >= 0)
        result.append(_group_record(group_id, ordered, fallback_number=lens_number))
        lens_number += 1

    remaining = [
        item
        for item in sorted(ungrouped, key=lambda value: float(value.get("z", 0.0) or 0.0))
        if int(item.get("surface_index", -1)) not in used_indices
    ]
    index = 0
    while index < len(remaining):
        pair = remaining[index:index + 2]
        label = f"L{lens_number}"
        result.append(_group_record(label, pair, fallback_number=lens_number))
        lens_number += 1
        index += 2

    return sorted(result, key=lambda value: float(value.get("z_min", 0.0)))


def _group_record(group_id: str, items: list[dict], *, fallback_number: int) -> dict:
    ordered = sorted(items, key=lambda value: float(value.get("z", 0.0) or 0.0))
    z_values = [float(value.get("z", 0.0) or 0.0) for value in ordered]
    apertures = [max(float(value.get("aperture", 0.0) or 0.0), 0.0) for value in ordered]
    material = next(
        (
            str(value.get("material", "") or "")
            for value in ordered
            if str(value.get("material", "") or "").strip().upper() not in {"", "AIR"}
        ),
        "",
    )
    label = str(group_id or f"L{fallback_number}")
    if not label.upper().startswith("L") and label.isdigit():
        label = f"L{label}"
    return {
        "group_id": str(group_id or label),
        "label": label,
        "surface_indices": [int(value.get("surface_index", -1)) for value in ordered],
        "z_min": min(z_values),
        "z_max": max(z_values),
        "aperture": max(apertures, default=0.0),
        "material": material,
    }


def build_beam_envelope(
    rays: Iterable[Mapping],
    *,
    sample_count: int = 28,
    percentile: float = 94.0,
) -> list[dict]:

    prepared: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for ray in rays:
        if str(ray.get("role", "")).lower() == "failed":
            continue
        points = np.asarray(ray.get("points", []), dtype=float)
        if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2:
            continue
        finite = points[np.all(np.isfinite(points), axis=1)]
        if len(finite) < 2:
            continue
        order = np.argsort(finite[:, 2])
        finite = finite[order]
        z, unique_indices = np.unique(finite[:, 2], return_index=True)
        if len(z) < 2:
            continue
        prepared.append((z, finite[unique_indices, 0], finite[unique_indices, 1]))

    if len(prepared) < 2:
        return []

    z_low = max(min(values[0]) for values in prepared)
    z_high = min(max(values[0]) for values in prepared)
    if not np.isfinite(z_low) or not np.isfinite(z_high) or z_high <= z_low:
        z_low = min(min(values[0]) for values in prepared)
        z_high = max(max(values[0]) for values in prepared)
    if z_high <= z_low:
        return []

    grid = np.linspace(float(z_low), float(z_high), max(8, int(sample_count)))
    rows: list[dict] = []
    for z_value in grid:
        x_values: list[float] = []
        y_values: list[float] = []
        for z, x, y in prepared:
            if z_value < z[0] or z_value > z[-1]:
                continue
            x_values.append(float(np.interp(z_value, z, x)))
            y_values.append(float(np.interp(z_value, z, y)))
        if len(x_values) < 2:
            continue
        x_array = np.asarray(x_values, dtype=float)
        y_array = np.asarray(y_values, dtype=float)
        centre_x = float(np.median(x_array))
        centre_y = float(np.median(y_array))
        radius_x = float(np.percentile(np.abs(x_array - centre_x), percentile))
        radius_y = float(np.percentile(np.abs(y_array - centre_y), percentile))
        rows.append(
            {
                "z": float(z_value),
                "center_x": centre_x,
                "center_y": centre_y,
                "radius_x": max(radius_x, 1.0e-6),
                "radius_y": max(radius_y, 1.0e-6),
            }
        )

    if len(rows) >= 5:
        for key in ("center_x", "center_y", "radius_x", "radius_y"):
            values = np.asarray([float(row[key]) for row in rows], dtype=float)
            padded = np.pad(values, (1, 1), mode="edge")
            smoothed = np.convolve(padded, np.ones(3) / 3.0, mode="valid")
            for row, value in zip(rows, smoothed):
                row[key] = float(value)
    return rows


def focus_from_envelope(envelope: Iterable[Mapping]) -> dict | None:
    rows = [dict(item) for item in envelope]
    if len(rows) < 3:
        return None
    areas = np.asarray(
        [
            max(float(item.get("radius_x", 0.0)), 1.0e-12)
            * max(float(item.get("radius_y", 0.0)), 1.0e-12)
            for item in rows
        ],
        dtype=float,
    )
    index = int(np.argmin(areas))
    if index == 0:
        
        
        if areas[0] >= 0.35 * float(np.max(areas)):
            return None
    elif index == len(rows) - 1:
        
        
        
        if areas[-1] >= 0.35 * areas[0]:
            return None
    item = rows[index]
    return {
        "z": float(item.get("z", 0.0)),
        "center_x": float(item.get("center_x", 0.0)),
        "center_y": float(item.get("center_y", 0.0)),
        "radius_x": float(item.get("radius_x", 0.0)),
        "radius_y": float(item.get("radius_y", 0.0)),
        "label": "束腰",
    }


__all__ = [
    "build_beam_envelope",
    "focus_from_envelope",
    "infer_lens_groups",
    "is_optical_surface",
]
