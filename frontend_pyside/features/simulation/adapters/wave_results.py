from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import numpy as np
from .array_utils import _as_1d, _as_2d, _first, _preview_grid

FORMAL_SOURCE = "正式仿真"

def _spot_plot(arrays: Mapping[str, Any]) -> dict[str, Any] | None:
    points = _as_2d(_first(arrays, "spot_points_um", "wavefront_tools_spot_points_um"), columns=2)
    if not points.size:
        final_positions = _as_2d(arrays.get("raytrace_final_positions_mm"), columns=3)
        if final_positions.size:
            points = final_positions[:, :2] * 1000.0
    if not points.size:
        return None
    finite = np.all(np.isfinite(points), axis=1)
    points = points[finite]
    if not len(points):
        return None
    return {
        "kind": "scatter",
        "title": "正式点列图",
        "x": points[:, 0].astype(float).tolist(),
        "y": points[:, 1].astype(float).tolist(),
        "x_label": "x / μm",
        "y_label": "y / μm",
        "source": FORMAL_SOURCE,
        "description": f"有效像面样本：{len(points)}。",
    }

def _psf_plot(arrays: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, Any] | None:
    z = _as_2d(_first(arrays, "hybrid_psf_intensity", "psf_intensity", "diffraction_intensity"))
    if not z.size:
        return None
    axis_x = _as_1d(_first(arrays, "detector_grid_x_mm", "coupling_grid_x_mm"))
    axis_y = _as_1d(_first(arrays, "detector_grid_y_mm", "coupling_grid_y_mm"))
    if len(axis_x) != z.shape[1] or len(axis_y) != z.shape[0]:
        settings = dict(project.get("analysis_settings", {}) or {})
        extent = float(settings.get("output_extent_mm", 0.0) or 0.0)
        if extent <= 0:
            extent = 0.5 * max(z.shape) / 1000.0
        axis_x = np.linspace(-extent, extent, z.shape[1])
        axis_y = np.linspace(-extent, extent, z.shape[0])
    full_shape = z.shape
    z, axis_x, axis_y, _rows, _cols = _preview_grid(z, axis_x, axis_y)
    return {
        "kind": "heatmap",
        "title": "正式 PSF",
        "x": (axis_x * 1000.0).astype(float).tolist(),
        "y": (axis_y * 1000.0).astype(float).tolist(),
        "z": np.nan_to_num(z, nan=0.0).astype(np.float32).tolist(),
        "x_label": "x / μm",
        "y_label": "y / μm",
        "source": FORMAL_SOURCE,
        "auto_crop_fraction": float(np.exp(-2.0)),
        "description": f"PSF 原始网格：{full_shape[0]} × {full_shape[1]}；界面预览：{z.shape[0]} × {z.shape[1]}；按 1/e² 强度区域自动取景。",
    }

def _mtf_plot(arrays: Mapping[str, Any]) -> dict[str, Any] | None:
    cut = _as_1d(_first(arrays, "hybrid_mtf_center_cut", "mtf_x_cut", "mtf_center_cut"))
    frequency = _as_1d(_first(arrays, "hybrid_mtf_frequency_cycles_per_mm", "mtf_frequency_cycles_per_mm", "mtf_fx_cycles_per_mm"))
    if not cut.size:
        matrix = _as_2d(_first(arrays, "hybrid_mtf_values", "mtf_values"))
        if matrix.size:
            cut = matrix[matrix.shape[0] // 2]
    if not cut.size:
        return None
    if len(frequency) != len(cut):
        frequency = np.linspace(0.0, 1.0, len(cut))
        x_label = "归一化空间频率"
    else:
        
        if np.any(frequency < 0):
            keep = frequency >= 0
            frequency, cut = frequency[keep], cut[keep]
        x_label = "空间频率 / cycles·mm⁻¹"
    return {
        "kind": "line",
        "title": "正式 MTF 中心截线",
        "x": frequency.astype(float).tolist(),
        "y": np.nan_to_num(cut, nan=0.0).astype(float).tolist(),
        "x_label": x_label,
        "y_label": "MTF",
        "source": FORMAL_SOURCE,
        "description": f"中心截线数据点：{len(cut)}。",
    }

def _wavefront_plot(arrays: Mapping[str, Any]) -> dict[str, Any] | None:
    z = _as_2d(_first(arrays, "wavefront_tools_map_nm", "wavefront_opd_nm", "wavefront_tools_residual_map_nm"))
    if not z.size:
        return None
    axis_x = _as_1d(arrays.get("wavefront_grid_pupil_x_normalized"))
    axis_y = _as_1d(arrays.get("wavefront_grid_pupil_y_normalized"))
    if len(axis_x) != z.shape[1]:
        axis_x = np.linspace(-1.0, 1.0, z.shape[1])
    if len(axis_y) != z.shape[0]:
        axis_y = np.linspace(-1.0, 1.0, z.shape[0])
    full_shape = z.shape
    z, axis_x, axis_y, _rows, _cols = _preview_grid(z, axis_x, axis_y)
    return {
        "kind": "heatmap",
        "title": "正式波前 OPD",
        "x": axis_x.astype(float).tolist(),
        "y": axis_y.astype(float).tolist(),
        "z": np.nan_to_num(z, nan=0.0).astype(np.float32).tolist(),
        "x_label": "归一化光瞳 x",
        "y_label": "归一化光瞳 y",
        "source": FORMAL_SOURCE,
        "description": f"波前原始网格：{full_shape[0]} × {full_shape[1]}；界面预览：{z.shape[0]} × {z.shape[1]}，单位 nm。",
    }
