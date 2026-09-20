"""光纤耦合结果的专用绘图数据适配器。

本模块不直接画图，而是把接收面复场、目标光纤模式和耦合指标转换为
统一绘图载荷。载荷中的 ``kind`` 决定后续使用快速热图还是 Matplotlib，
而 ``x``、``y``、``z``、``series`` 和 ``metrics`` 决定图上具体显示内容。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import math
import numpy as np
from frontend_pyside.shared.settings import SimulationNumericsProfileStore

from .array_utils import _as_1d, _as_2d, _preview_grid

FORMAL_SOURCE = "正式仿真"


def _display_profile() -> tuple[bool, float]:
    """读取端面匹配图的自动取景和填充比例配置。"""
    try:
        profile = SimulationNumericsProfileStore().load()
        return bool(profile.get("auto_display_frame", True)), float(profile.get("display_fill_fraction", 0.67))
    except Exception:
        return True, 0.67


def _normalize(values: np.ndarray) -> np.ndarray:
    """将数组按最大值归一化，用于热图和剖面比较显示。"""
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    maximum = float(np.max(values)) if values.size else 0.0
    return values / maximum if maximum > 0.0 else values


def _moments(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    """计算场分布的质心和 X/Y 二阶矩尺寸。"""
    values = np.maximum(np.nan_to_num(values, nan=0.0), 0.0)
    total = float(np.sum(values))
    if total <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    xx, yy = np.meshgrid(x, y, indexing="xy")
    cx = float(np.sum(values * xx) / total)
    cy = float(np.sum(values * yy) / total)
    
    wx = 2.0 * math.sqrt(max(float(np.sum(values * (xx - cx) ** 2) / total), 0.0))
    wy = 2.0 * math.sqrt(max(float(np.sum(values * (yy - cy) ** 2) / total), 0.0))
    return cx, cy, wx, wy


def _recursive_number(data: Mapping[str, Any] | None, keys: tuple[str, ...], default: float) -> float:
    """从指标字典及其嵌套字典中按候选键查找有限数值。"""
    if not isinstance(data, Mapping):
        return default
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    for value in data.values():
        if isinstance(value, Mapping):
            found = _recursive_number(value, keys, float("nan"))
            if math.isfinite(found):
                return found
    return default


def _beam_match_view(
    field: np.ndarray,
    mode: np.ndarray,
    display_x: np.ndarray,
    display_y: np.ndarray,
    *,
    x_label: str,
    y_label: str,
    source: str,
) -> dict[str, Any]:
    """生成端面匹配载荷。

    主图使用入射场，``contour`` 叠加目标模式轮廓，X/Y profiles 用于显示
    两者的中心截面；metrics 则提供中心偏移、尺寸比和椭圆率。
    """
    # 通过二阶矩得到中心和 1/e² 尺寸，不依赖特定绘图库。
    incident = _moments(field, display_x, display_y)
    target = _moments(mode, display_x, display_y) if mode.shape == field.shape else (0.0, 0.0, 0.0, 0.0)
    cx, cy, wx, wy = incident
    tx, ty, twx, twy = target
    center_distance = math.hypot(cx - tx, cy - ty)
    ratio_x = wx / twx if twx > 0.0 else float("nan")
    ratio_y = wy / twy if twy > 0.0 else float("nan")
    ellipticity = max(wx, wy) / max(min(wx, wy), 1e-12) if wx > 0.0 and wy > 0.0 else float("nan")

    row_incident = int(np.argmin(np.abs(display_y - cy))) if len(display_y) else field.shape[0] // 2
    col_incident = int(np.argmin(np.abs(display_x - cx))) if len(display_x) else field.shape[1] // 2
    row_target = int(np.argmin(np.abs(display_y - ty))) if len(display_y) else mode.shape[0] // 2
    col_target = int(np.argmin(np.abs(display_x - tx))) if len(display_x) else mode.shape[1] // 2
    mode_valid = mode.shape == field.shape
    x_mode = _normalize(mode[row_target]) if mode_valid else np.zeros(field.shape[1])
    y_mode = _normalize(mode[:, col_target]) if mode_valid else np.zeros(field.shape[0])

    full_shape = field.shape
    field_preview, display_x_preview, display_y_preview, row_index, col_index = _preview_grid(
        field, display_x, display_y
    )
    if mode_valid:
        mode_preview = mode[np.ix_(row_index, col_index)]
    else:
        mode_preview = np.zeros_like(field_preview)

    # 大量背景像素会压缩主体，因此把自动取景信息传给渲染层。
    auto_frame, fill_fraction = _display_profile()
    description = (
        f"中心偏移 {center_distance:.3g} μm；X尺寸比 {ratio_x:.3f}；"
        f"Y尺寸比 {ratio_y:.3f}；椭圆率 {ellipticity:.3f}。"
        "尺寸比定义为入射光1/e²半径/目标模场1/e²半径：大于1表示入射光斑偏大。"
    )
    return {
        "kind": "beam_match",
        "title": "端面匹配",
        "x": display_x_preview.astype(float, copy=False),
        "y": display_y_preview.astype(float, copy=False),
        "z": _normalize(field_preview).astype(np.float32, copy=False),
        "contour": _normalize(mode_preview).astype(np.float32, copy=False),
        "x_profiles": {
            "入射光": _normalize(field[row_incident])[col_index].astype(np.float32, copy=False),
            "光纤模式": x_mode[col_index].astype(np.float32, copy=False),
        },
        "y_profiles": {
            "入射光": _normalize(field[:, col_incident])[row_index].astype(np.float32, copy=False),
            "光纤模式": y_mode[row_index].astype(np.float32, copy=False),
        },
        "incident_center": [cx, cy],
        "fiber_center": [tx, ty],
        "incident_radius": [wx, wy],
        "target_radius": [twx, twy],
        "metrics": {
            "center_offset_um": center_distance,
            "size_ratio_x": ratio_x,
            "size_ratio_y": ratio_y,
            "ellipticity": ellipticity,
        },
        "x_label": x_label,
        "y_label": y_label,
        "color_map": "energy",
        "normalization": "energy",
        "source": source,
        "auto_display_frame": bool(auto_frame),
        "auto_crop_fraction": float(np.exp(-2.0)) if auto_frame else None,
        "display_fill_fraction": fill_fraction,
        "preview_shape": [int(field_preview.shape[0]), int(field_preview.shape[1])],
        "original_shape": [int(full_shape[0]), int(full_shape[1])],
        "description": description,
    }


def _waist_position_view(
    beam_match: Mapping[str, Any],
    *,
    metrics: Mapping[str, Any] | None,
    project: Mapping[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    """根据端面光斑和轴向偏置估计 X/Y 束腰传播曲线。"""
    incident_radius = list(beam_match.get("incident_radius", [0.0, 0.0]))
    target_radius = list(beam_match.get("target_radius", [0.0, 0.0]))
    wx_plane = max(float(incident_radius[0] or 0.0), 0.1)
    wy_plane = max(float(incident_radius[1] or 0.0), 0.1)
    target = math.sqrt(max(float(target_radius[0] or 0.0), 0.1) * max(float(target_radius[1] or 0.0), 0.1))
    wavelength_nm = _recursive_number(project, ("wavelength_nm", "wavelength"), 808.0)
    dz_mm = _recursive_number(project, ("receiver_axial_offset_z_mm", "axial_offset_z_mm", "offset_z_mm"), 0.0)
    
    v_axial = _recursive_number(metrics, ("coupling_research_v_axial", "v_axial"), float("nan"))
    target_zr_mm = math.pi * target * target / max(wavelength_nm * 1e-3, 1e-9) / 1000.0
    if math.isfinite(v_axial):
        dz_mm = v_axial * target_zr_mm

    def waist_from_plane(plane_radius: float, offset_mm: float) -> tuple[float, float]:
        """由某一截面半径和传播距离反推束腰半径及瑞利长度。"""
        lam_um = wavelength_nm * 1e-3
        z_um = abs(offset_mm) * 1000.0
        a = plane_radius**2
        disc = max(a * a - 4.0 * (lam_um * z_um / math.pi) ** 2, 0.0)
        w0_sq = max(0.5 * (a + math.sqrt(disc)), 0.01)
        w0 = math.sqrt(w0_sq)
        zr_mm = math.pi * w0_sq / max(lam_um, 1e-9) / 1000.0
        return w0, max(zr_mm, 1e-6)

    waist_x, zr_x = waist_from_plane(wx_plane, dz_mm)
    waist_y, zr_y = waist_from_plane(wy_plane, dz_mm)
    waist_x_z = -dz_mm
    waist_y_z = -dz_mm
    
    
    separation = 0.15 * (wx_plane - wy_plane) / max(wx_plane + wy_plane, 1e-9) * max(zr_x + zr_y, 0.02)
    waist_x_z -= separation
    waist_y_z += separation
    span = max(0.45, 4.0 * max(zr_x, zr_y), 2.5 * abs(dz_mm))
    z = np.linspace(-span, span, 161)
    x_radius = waist_x * np.sqrt(1.0 + ((z - waist_x_z) / zr_x) ** 2)
    y_radius = waist_y * np.sqrt(1.0 + ((z - waist_y_z) / zr_y) ** 2)
    return {
        "kind": "waist_position",
        "title": "束腰位置",
        "x": z.astype(float).tolist(),
        "series": [
            {"label": "w_x(z)", "y": x_radius.astype(float).tolist()},
            {"label": "w_y(z)", "y": y_radius.astype(float).tolist()},
        ],
        "fiber_z": 0.0,
        "target_radius": target,
        "waist_points": [
            {"z": waist_x_z, "w": waist_x, "label": "X束腰", "marker": "o"},
            {"z": waist_y_z, "w": waist_y, "label": "Y束腰", "marker": "s"},
        ],
        "metrics": {
            "fiber_to_x_waist_mm": -waist_x_z,
            "fiber_to_y_waist_mm": -waist_y_z,
            "facet_spot_x_um": wx_plane,
            "facet_spot_y_um": wy_plane,
            "target_radius_um": target,
            "waist_x_um": waist_x,
            "waist_y_um": waist_y,
            "waist_x_z_mm": waist_x_z,
            "waist_y_z_mm": waist_y_z,
            "rayleigh_x_mm": zr_x,
            "rayleigh_y_mm": zr_y,
        },
        "x_label": "z / mm（光纤端面为0）",
        "y_label": "w / μm",
        "source": source,
        "description": (
            f"端面—X束腰距离 {-waist_x_z:+.3f} mm；端面—Y束腰距离 {-waist_y_z:+.3f} mm；"
            f"端面光斑 {wx_plane:.3g} × {wy_plane:.3g} μm。"
            "曲线由端面二阶矩、波长和接收器轴向偏置进行高斯拟合；无正式轴向信息时按端面为拟合束腰估计。"
        ),
    }


def _coupling_plots(
    arrays: Mapping[str, Any],
    *,
    metrics: Mapping[str, Any] | None = None,
    project: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """生成正式光纤耦合页面使用的全部绘图载荷。

    该函数只负责准备数据：当后端没有单独返回强度或相位时，会由复场的
    实部/虚部派生；当坐标缺失时，则退回像素坐标，保证图仍可显示。
    """
    # 后端数组是原始输入；后续所有视图都从这些数组派生，避免重复取数。
    x = _as_1d(arrays.get("coupling_grid_x_mm"))
    y = _as_1d(arrays.get("coupling_grid_y_mm"))
    real = _as_2d(arrays.get("coupling_field_real"))
    imag = _as_2d(arrays.get("coupling_field_imag"))
    field = _as_2d(arrays.get("coupling_field_intensity"))
    phase = _as_2d(arrays.get("coupling_field_phase_rad"))
    mode = _as_2d(arrays.get("coupling_mode_intensity"))
    mode_phase = _as_2d(arrays.get("coupling_mode_phase_rad"))

    # 兼容只返回复场实部/虚部的后端载荷。
    if not field.size and real.size and imag.shape == real.shape:
        field = real * real + imag * imag
    if not phase.size and real.size and imag.shape == real.shape:
        phase = np.arctan2(imag, real)
    if not field.size:
        return {}
    if not mode.size or mode.shape != field.shape:
        mode = np.zeros_like(field)

    # 坐标长度不匹配时使用像素坐标，避免数组索引和坐标轴长度不一致。
    if len(x) != field.shape[1]:
        display_x = np.arange(field.shape[1], dtype=float)
        x_label = "x / pixel"
    else:
        display_x = x * 1000.0
        x_label = "x / μm"
    if len(y) != field.shape[0]:
        display_y = np.arange(field.shape[0], dtype=float)
        y_label = "y / pixel"
    else:
        display_y = y * 1000.0
        y_label = "y / μm"

    field_preview, display_x_preview, display_y_preview, row_index, col_index = _preview_grid(
        field, display_x, display_y
    )
    mode_preview = mode[np.ix_(row_index, col_index)]
    phase_preview = phase[np.ix_(row_index, col_index)] if phase.size and phase.shape == field.shape else phase
    # heatmap_pair 供快速热图同时显示入射场和目标模式。
    diagnostic_pair = {
        "kind": "heatmap_pair", "title": "正式接收面场与光纤模式",
        "x": display_x_preview.astype(float, copy=False), "y": display_y_preview.astype(float, copy=False),
        "z1": np.nan_to_num(field_preview, nan=0.0).astype(np.float32, copy=False),
        "z2": np.nan_to_num(mode_preview, nan=0.0).astype(np.float32, copy=False),
        "x_label": x_label, "y_label": y_label, "source": FORMAL_SOURCE,
        "description": f"耦合场网格：{field.shape[0]} × {field.shape[1]}。",
    }
    # beam_match 是端面匹配主图，包含热图、模式轮廓、剖面和摘要指标。
    beam_match = _beam_match_view(field, mode, display_x, display_y, x_label=x_label, y_label=y_label, source=FORMAL_SOURCE)
    coupling_efficiency = _recursive_number(
        metrics,
        ("field_coupling_efficiency", "complex_field_coupling_efficiency",
         "coupling_field_efficiency", "mode_overlap_efficiency", "coupling_efficiency"),
        float("nan"),
    )
    system_efficiency = _recursive_number(
        metrics,
        ("system_efficiency", "total_coupling_efficiency",
         "coupling_total_efficiency", "coupling_efficiency_total"),
        float("nan"),
    )
    if math.isfinite(coupling_efficiency):
        beam_match["metrics"]["coupling_efficiency_percent"] = (
            100.0 * coupling_efficiency if abs(coupling_efficiency) <= 1.000001 else coupling_efficiency
        )
    if math.isfinite(system_efficiency):
        beam_match["metrics"]["system_efficiency_percent"] = (
            100.0 * system_efficiency if abs(system_efficiency) <= 1.000001 else system_efficiency
        )
    settings = dict(project.get("analysis_settings", {}) or {}) if isinstance(project, Mapping) else {}
    incident_intensity_only = bool(settings.get("incident_intensity_only", False))
    waist = _waist_position_view(beam_match, metrics=metrics, project=project, source=FORMAL_SOURCE)
    # 这里的 key 必须与 formal_results.py 和 results.py 中的请求名称一致。
    plots: dict[str, dict[str, Any]] = {
        "端面匹配": beam_match,
        "束腰位置": waist,
        
        "模式重叠": dict(beam_match),
        "耦合场": diagnostic_pair,
        "光强": {
            "kind": "heatmap", "title": "接收面光强图",
            "x": display_x_preview.astype(float, copy=False), "y": display_y_preview.astype(float, copy=False),
            "z": np.maximum(np.nan_to_num(field_preview, nan=0.0), 0.0).astype(np.float32, copy=False),
            "x_label": x_label, "y_label": y_label, "source": FORMAL_SOURCE,
            "color_map": "energy", "normalization": "energy",
            "equal_aspect": True,
            "description": "接收面复光场的强度分布，单位为归一化强度。",
        },
        "振幅": {
            "kind": "heatmap", "title": "正式接收面场振幅",
            "x": display_x_preview.astype(float, copy=False), "y": display_y_preview.astype(float, copy=False),
            "z": np.sqrt(np.maximum(np.nan_to_num(field_preview, nan=0.0), 0.0)).astype(np.float32, copy=False),
            "x_label": x_label, "y_label": y_label, "source": FORMAL_SOURCE,
        },
    }
    if incident_intensity_only:
        # Replace the composite endpoint-matching view with a plain intensity
        # heatmap.  This also makes ResultDocument export exactly this image,
        # because the selected payload no longer contains overlay artists.
        pure_intensity = dict(plots["光强"])
        pure_intensity["title"] = "入射光光强"
        pure_intensity["description"] = "仅显示入射光强度分布；未叠加光纤模式、剖面线、图例或中心标记。"
        plots["端面匹配"] = pure_intensity
        plots["模式重叠"] = dict(pure_intensity)
    # 相位数组可选；没有相位时不生成相位热图。
    if phase.size and phase.shape == field.shape:
        plots["相位"] = {
            "kind": "heatmap", "title": "正式接收面场相位",
            "x": display_x_preview.astype(float, copy=False), "y": display_y_preview.astype(float, copy=False),
            "z": np.nan_to_num(phase_preview, nan=0.0).astype(np.float32, copy=False),
            "x_label": x_label, "y_label": y_label, "source": FORMAL_SOURCE,
            "color_map": "phase", "normalization": "phase",
            "description": "相位单位：rad。",
        }
    plots["光纤基模"] = {
        "kind": "heatmap", "title": "光纤基模强度",
        "x": display_x_preview.astype(float, copy=False), "y": display_y_preview.astype(float, copy=False),
        "z": _normalize(mode_preview).astype(np.float32, copy=False),
        "x_label": x_label, "y_label": y_label, "source": FORMAL_SOURCE,
        "equal_aspect": True,
        "description": "接收光纤目标模式的归一化强度分布。",
    }
    # X/Y 两个方向分别比较入射场与目标模式，避免只看二维热图时遗漏椭圆率和偏心。
    row_incident = int(np.argmin(np.abs(display_y - beam_match.get("incident_center", [0.0, 0.0])[1]))) if len(display_y) else field.shape[0] // 2
    col_incident = int(np.argmin(np.abs(display_x - beam_match.get("incident_center", [0.0, 0.0])[0]))) if len(display_x) else field.shape[1] // 2
    row_target = int(np.argmin(np.abs(display_y - beam_match.get("fiber_center", [0.0, 0.0])[1]))) if len(display_y) else mode.shape[0] // 2
    col_target = int(np.argmin(np.abs(display_x - beam_match.get("fiber_center", [0.0, 0.0])[0]))) if len(display_x) else mode.shape[1] // 2
    # X/Y 两个方向分别比较入射场与目标模式，避免只看二维热图时遗漏椭圆率和偏心。
    plots["XY模场比较"] = {
        "kind": "profile_pair", "title": "X/Y 模场比较",
        "x_axis": display_x.astype(float).tolist(),
        "y_axis": display_y.astype(float).tolist(),
        "x_series": [
            {"label": "入射场", "y": _normalize(field[row_incident]).astype(float).tolist()},
            {"label": "光纤模式", "y": _normalize(mode[row_target]).astype(float).tolist()},
        ],
        "y_series": [
            {"label": "入射场", "y": _normalize(field[:, col_incident]).astype(float).tolist()},
            {"label": "光纤模式", "y": _normalize(mode[:, col_target]).astype(float).tolist()},
        ],
        "x_label": x_label, "y_label": y_label, "value_label": "归一化强度", "source": FORMAL_SOURCE,
        "description": "分别比较 X、Y 方向的入射场与光纤基模截面。",
    }
    # 复场重叠贡献需要入射场和目标模式都包含相位信息。
    if phase.size and phase.shape == field.shape and mode_phase.size and mode_phase.shape == field.shape:
        overlap = np.sqrt(np.maximum(field, 0.0) * np.maximum(mode, 0.0)) * np.cos(phase - mode_phase)
        scale = float(np.nanmax(np.abs(overlap))) if overlap.size else 0.0
        if scale > 0.0:
            overlap = overlap / scale
        overlap_preview = overlap[np.ix_(row_index, col_index)]
        plots["重叠贡献"] = {
            "kind": "heatmap", "title": "复场重叠实部贡献",
            "x": display_x_preview.astype(float, copy=False), "y": display_y_preview.astype(float, copy=False),
            "z": np.nan_to_num(overlap_preview, nan=0.0).astype(np.float32, copy=False),
            "x_label": x_label, "y_label": y_label, "source": FORMAL_SOURCE,
            "equal_aspect": True,
            "description": "由归一化复场重叠积分的点乘实部构造；正值表示同相贡献，负值表示相消贡献，不等同于局部效率。",
        }
    for key, value in _derived_coupling_views(diagnostic_pair, source=FORMAL_SOURCE).items():
        plots.setdefault(key, value)
    return plots


def _mode_overlay_from_pair(coupling: Mapping[str, Any]) -> dict[str, Any] | None:
    """把预览阶段的双热图载荷转换为端面匹配载荷。"""
    field = _as_2d(coupling.get("z1"))
    mode = _as_2d(coupling.get("z2"))
    if not field.size or mode.shape != field.shape:
        return None
    x = _as_1d(coupling.get("x"))
    y = _as_1d(coupling.get("y"))
    if len(x) != field.shape[1]:
        x = np.arange(field.shape[1], dtype=float)
    if len(y) != field.shape[0]:
        y = np.arange(field.shape[0], dtype=float)
    return _beam_match_view(
        field, mode, x, y,
        x_label=str(coupling.get("x_label", "x")),
        y_label=str(coupling.get("y_label", "y")),
        source=str(coupling.get("source", "快速预览")),
    )


def _derived_coupling_views(coupling: Mapping[str, Any], *, source: str) -> dict[str, dict[str, Any]]:
    """从一份耦合双热图载荷派生束腰和中心截面视图。"""
    field = _as_2d(coupling.get("z1"))
    mode = _as_2d(coupling.get("z2"))
    x = _as_1d(coupling.get("x"))
    y = _as_1d(coupling.get("y"))
    if not field.size:
        return {}
    if len(x) != field.shape[1]:
        x = np.arange(field.shape[1], dtype=float)
    if len(y) != field.shape[0]:
        y = np.arange(field.shape[0], dtype=float)
    beam_match = _beam_match_view(
        field, mode if mode.shape == field.shape else np.zeros_like(field), x, y,
        x_label=str(coupling.get("x_label", "x")),
        y_label=str(coupling.get("y_label", "y")), source=source,
    )
    
    
    waist = _waist_position_view(beam_match, metrics={}, project={}, source=source)
    center = field.shape[0] // 2
    field_cut = _normalize(field[center])
    mode_cut = _normalize(mode[center]) if mode.shape == field.shape else np.zeros_like(field_cut)
    return {
        "端面匹配": beam_match,
        "束腰位置": waist,
        "中心截面": {
            "kind": "line_multi", "title": "入射场与光纤模式中心截面",
            "x": x.astype(float).tolist(),
            "series": [
                {"label": "入射场", "y": field_cut.astype(float).tolist()},
                {"label": "光纤模式", "y": mode_cut.astype(float).tolist()},
            ],
            "x_label": str(coupling.get("x_label", "x")), "y_label": "归一化强度", "source": source,
        },
    }
