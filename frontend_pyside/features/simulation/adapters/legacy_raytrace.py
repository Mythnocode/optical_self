"""旧版光线追迹结果的兼容适配器。

它把历史 ray-trace 数据字段整理成当前绘图层使用的截面、光线和统计载荷，
从而让旧结果仍可复用统一的 2D/3D 渲染器。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import numpy as np
from .array_utils import _as_1d, _as_2d

FORMAL_SOURCE = "正式仿真"

def _raytrace_plots(arrays: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    paths = _as_2d(arrays.get("raytrace_path_points_mm"), columns=3)
    offsets = _as_1d(arrays.get("raytrace_path_offsets"), dtype=int)
    rays: list[dict[str, list[float]]] = []
    if paths.size and offsets.size >= 2:
        for start, end in zip(offsets[:-1], offsets[1:]):
            start_i, end_i = int(start), int(end)
            if 0 <= start_i < end_i <= len(paths):
                segment = paths[start_i:end_i]
                finite = np.all(np.isfinite(segment), axis=1)
                segment = segment[finite]
                if len(segment) >= 2:
                    rays.append(
                        {
                            "x": segment[:, 0].astype(float).tolist(),
                            "y": segment[:, 1].astype(float).tolist(),
                            "z": segment[:, 2].astype(float).tolist(),
                        }
                    )
    if not rays:
        final_positions = _as_2d(arrays.get("raytrace_final_positions_mm"), columns=3)
        if final_positions.size:
            object_z = -abs(float(project.get("object_distance_mm", 1.0) or 1.0))
            for point in final_positions[: min(len(final_positions), 81)]:
                if np.all(np.isfinite(point)):
                    rays.append(
                        {
                            "x": [0.0, float(point[0])],
                            "y": [0.0, float(point[1])],
                            "z": [object_z, float(point[2])],
                        }
                    )
    if not rays:
        return {}

    surfaces = _surface_geometry(project)
    common = {
        "surfaces": surfaces,
        "rays": rays,
        "source": FORMAL_SOURCE,
        "description": f"正式追迹路径：{len(rays)} 条光线，{len(surfaces)} 个启用表面。",
    }
    return {
        "光路": {
            "kind": "raytrace",
            "title": "正式二维光路",
            "x_label": "z / mm",
            "y_label": "y / mm",
            **common,
        },
        "3D光路": {
            "kind": "raytrace3d",
            "title": "正式三维光路",
            "x_label": "z / mm",
            "y_label": "x / mm",
            "z_label": "y / mm",
            **common,
        },
    }

def _surface_geometry(project: Mapping[str, Any]) -> list[dict[str, float]]:
    z = 0.0
    surfaces: list[dict[str, float]] = []
    for raw in project.get("surfaces", []) or []:
        item = dict(raw or {})
        if bool(item.get("enabled", True)):
            aperture = float(item.get("clear_aperture_mm", 1.0) or 1.0)
            surfaces.append(
                {
                    "z": z,
                    "aperture": aperture,
                    "decenter_x": float(item.get("decenter_x_mm", 0.0) or 0.0),
                    "decenter_y": float(item.get("decenter_y_mm", 0.0) or 0.0),
                }
            )
        z += float(item.get("distance_to_next_mm", 0.0) or 0.0)
    if project.get("image_distance_mm"):
        surfaces.append({"z": z + float(project["image_distance_mm"]), "aperture": 0.0, "decenter_x": 0.0, "decenter_y": 0.0})
    return surfaces
