from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import numpy as np
from frontend_pyside.shared.settings import SimulationNumericsProfileStore
from .array_utils import _as_1d, _as_2d, _first, _preview_grid

FORMAL_SOURCE = "正式仿真"


def _display_profile() -> tuple[bool, float]:
    try:
        profile = SimulationNumericsProfileStore().load()
        return bool(profile.get("auto_display_frame", True)), float(profile.get("display_fill_fraction", 0.67))
    except Exception:
        return True, 0.67

def _spot_plot(arrays: Mapping[str, Any], metrics: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
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
    center = np.mean(points, axis=0)
    radius = np.sqrt(np.sum((points - center) ** 2, axis=1))
    rms_radius = float(np.sqrt(np.mean(radius ** 2))) if len(radius) else float("nan")
    source_metrics = dict(metrics or {})
    backend_rms = source_metrics.get("rms_spot_radius_um", source_metrics.get("rms_spot_um"))
    try:
        backend_rms = float(backend_rms)
    except (TypeError, ValueError):
        backend_rms = float("nan")
    if np.isfinite(backend_rms):
        rms_radius = backend_rms
    airy = source_metrics.get("airy_radius_um")
    try:
        airy = float(airy)
    except (TypeError, ValueError):
        airy = float("nan")
    key_metrics = [
        {"label": "RMS 半径", "value": f"{rms_radius:.4g} μm" if np.isfinite(rms_radius) else "—"},
        {"label": "有效样本", "value": str(len(points))},
    ]
    if np.isfinite(airy) and airy > 0.0:
        key_metrics.insert(1, {"label": "艾里斑半径", "value": f"{airy:.4g} μm"})
    result = {
        "kind": "scatter",
        "title": "正式点列图",
        "x": points[:, 0].astype(float).tolist(),
        "y": points[:, 1].astype(float).tolist(),
        "x_label": "x / μm",
        "y_label": "y / μm",
        "source": FORMAL_SOURCE,
        "equal_aspect": True,
        "key_metrics": key_metrics,
        "description": (
            f"有效像面样本：{len(points)}；RMS 半径 {rms_radius:.4g} μm。"
            + (f" 艾里斑半径 {airy:.4g} μm。" if np.isfinite(airy) and airy > 0.0 else "")
        ),
    }
    if np.isfinite(airy) and airy > 0.0:
        result["airy_radius_um"] = airy
    return result

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
    auto_frame, fill_fraction = _display_profile()
    intensity = np.maximum(np.nan_to_num(z, nan=0.0), 0.0)
    total = float(np.sum(intensity))
    key_metrics = []
    if total > 0.0 and len(axis_x) == intensity.shape[1] and len(axis_y) == intensity.shape[0]:
        xx, yy = np.meshgrid(axis_x * 1000.0, axis_y * 1000.0, indexing="xy")
        cx = float(np.sum(intensity * xx) / total)
        cy = float(np.sum(intensity * yy) / total)
        rx = 2.0 * float(np.sqrt(max(np.sum(intensity * (xx - cx) ** 2) / total, 0.0)))
        ry = 2.0 * float(np.sqrt(max(np.sum(intensity * (yy - cy) ** 2) / total, 0.0)))
        ell = max(rx, ry) / max(min(rx, ry), 1e-12)
        key_metrics = [
            {"label": "X 光斑半径", "value": f"{rx:.4g} μm"},
            {"label": "Y 光斑半径", "value": f"{ry:.4g} μm"},
            {"label": "中心 X", "value": f"{cx:.4g} μm"},
            {"label": "中心 Y", "value": f"{cy:.4g} μm"},
            {"label": "椭圆率", "value": f"{ell:.4g}"},
        ]
    return {
        "kind": "heatmap",
        "title": "正式 PSF",
        "x": (axis_x * 1000.0).astype(float).tolist(),
        "y": (axis_y * 1000.0).astype(float).tolist(),
        "z": np.nan_to_num(z, nan=0.0).astype(np.float32).tolist(),
        "x_label": "x / μm",
        "y_label": "y / μm",
        "source": FORMAL_SOURCE,
        "key_metrics": key_metrics,
        "auto_crop_fraction": float(np.exp(-2.0)) if auto_frame else None,
        "display_fill_fraction": fill_fraction,
        "description": f"PSF 原始网格：{full_shape[0]} × {full_shape[1]}；界面预览：{z.shape[0]} × {z.shape[1]}；按 1/e² 强度区域自动取景。",
    }

def _mtf_plot(arrays: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build an MTF centre cut, deriving it from the formal PSF when needed.

    The backend's standard coupling pipeline already returns the formal PSF but
    does not currently materialise a separate ``mtf_*`` array section.  MTF is
    the magnitude of the normalised optical transfer function, i.e. the Fourier
    transform of that same PSF, so deriving it here avoids a second physical
    solve while preserving the formal-data provenance.
    """
    cut = _as_1d(_first(arrays, "hybrid_mtf_center_cut", "mtf_x_cut", "mtf_center_cut"))
    frequency = _as_1d(_first(arrays, "hybrid_mtf_frequency_cycles_per_mm", "mtf_frequency_cycles_per_mm", "mtf_fx_cycles_per_mm"))
    derived_from_psf = False
    if not cut.size:
        matrix = _as_2d(_first(arrays, "hybrid_mtf_values", "mtf_values"))
        if matrix.size:
            cut = matrix[matrix.shape[0] // 2]
    if not cut.size:
        psf = _as_2d(_first(arrays, "hybrid_psf_intensity", "psf_intensity", "diffraction_intensity"))
        if psf.size:
            psf = np.nan_to_num(psf, nan=0.0, posinf=0.0, neginf=0.0)
            otf = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(psf)))
            mtf = np.abs(otf)
            peak = float(np.max(mtf)) if mtf.size else 0.0
            if peak > 0.0:
                mtf = mtf / peak
            cut = mtf[mtf.shape[0] // 2].astype(float)
            axis_x = _as_1d(_first(arrays, "detector_grid_x_mm", "coupling_grid_x_mm", "psf_x_mm"))
            if len(axis_x) == psf.shape[1] and len(axis_x) > 1:
                diffs = np.diff(axis_x)
                finite = diffs[np.isfinite(diffs) & (np.abs(diffs) > 0.0)]
                dx = float(np.median(np.abs(finite))) if finite.size else 0.0
                if dx > 0.0:
                    frequency = np.fft.fftshift(np.fft.fftfreq(psf.shape[1], d=dx))
            derived_from_psf = True
    if not cut.size:
        return None
    if len(frequency) != len(cut):
        frequency = np.linspace(-1.0, 1.0, len(cut))
        x_label = "归一化空间频率"
    else:
        x_label = "空间频率 / cycles·mm⁻¹"
    if np.any(frequency < 0):
        keep = frequency >= 0
        frequency, cut = frequency[keep], cut[keep]
    description = f"中心截线数据点：{len(cut)}。"
    if derived_from_psf:
        description += " MTF 由同一正式 PSF 的归一化 OTF 派生，无需重复物理计算。"
    return {
        "kind": "line",
        "title": "正式 MTF 中心截线",
        "x": frequency.astype(float).tolist(),
        "y": np.nan_to_num(cut, nan=0.0).astype(float).tolist(),
        "x_label": x_label,
        "y_label": "MTF",
        "source": FORMAL_SOURCE,
        "description": description,
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


def _psf_profile_plot(arrays: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, Any] | None:
    base = _psf_plot(arrays, project)
    if not base:
        return None
    z = np.asarray(base.get("z", []), dtype=float)
    x = np.asarray(base.get("x", []), dtype=float)
    y = np.asarray(base.get("y", []), dtype=float)
    if z.ndim != 2 or not z.size:
        return None
    row = int(np.nanargmax(np.nanmax(z, axis=1))) if z.shape[0] else z.shape[0] // 2
    col = int(np.nanargmax(np.nanmax(z, axis=0))) if z.shape[1] else z.shape[1] // 2
    return {
        "kind": "profile_pair", "title": "焦面 X/Y 强度截面",
        "x_axis": x.tolist(), "y_axis": y.tolist(),
        "x_series": [{"label": "X 截面", "y": np.nan_to_num(z[row], nan=0.0).tolist()}],
        "y_series": [{"label": "Y 截面", "y": np.nan_to_num(z[:, col], nan=0.0).tolist()}],
        "x_label": str(base.get("x_label", "x")), "y_label": str(base.get("y_label", "y")),
        "value_label": "相对强度", "source": FORMAL_SOURCE,
    }

def _psf_size_plot(arrays: Mapping[str, Any], project: Mapping[str, Any]) -> dict[str, Any] | None:
    base = _psf_plot(arrays, project)
    if not base:
        return None
    z = np.maximum(np.asarray(base.get("z", []), dtype=float), 0.0)
    x = np.asarray(base.get("x", []), dtype=float); y = np.asarray(base.get("y", []), dtype=float)
    if z.ndim != 2 or not z.size or len(x) != z.shape[1] or len(y) != z.shape[0]:
        return None
    total = float(np.nansum(z))
    if total <= 0:
        return None
    xx, yy = np.meshgrid(x, y, indexing="xy")
    cx = float(np.nansum(z * xx) / total); cy = float(np.nansum(z * yy) / total)
    wx = 2.0 * float(np.sqrt(max(np.nansum(z * (xx-cx)**2) / total, 0.0)))
    wy = 2.0 * float(np.sqrt(max(np.nansum(z * (yy-cy)**2) / total, 0.0)))
    ell = max(wx, wy) / max(min(wx, wy), 1e-12)
    return {
        "kind": "bar", "title": "焦面光斑尺寸",
        "labels": ["X 方向 1/e²半径", "Y 方向 1/e²半径"], "values": [wx, wy],
        "y_label": "半径 / μm", "show_values": True, "source": FORMAL_SOURCE,
        "description": f"二阶矩估计：中心 ({cx:.3g}, {cy:.3g}) μm；椭圆率 {ell:.3f}。",
    }
