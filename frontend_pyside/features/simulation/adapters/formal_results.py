
"""正式仿真结果到通用绘图载荷的适配器。

后端返回的是包含 ``arrays``、``metrics``、状态和诊断信息的结果字典，绘图
控件并不直接理解这些后端字段。本模块按请求的图表名称把它们转换为统一
的 ``{"kind": ..., ...}`` 载荷，再交给 ``shared.plotting`` 渲染。

这里是“数据到图”的边界：修改图中使用的数据、绘图类型或某类图是否生成，
优先从本模块和同目录下的专业适配器查找。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..ray_data_model import FormalRayDataset
from ..ray_view_adapters import RayViewOptions, build_ray_view_plots
from .array_utils import _error_text
from .coupling_results import _coupling_plots, _derived_coupling_views, _mode_overlay_from_pair
from .wave_results import _mtf_plot, _psf_plot, _spot_plot, _psf_profile_plot, _psf_size_plot, _wavefront_plot
from frontend_pyside.shared.plotting.engineering_views import (
    build_energy_flow,
    build_multi_plane_evolution,
    build_phase_comparison,
)

FORMAL_SOURCE = "正式仿真"

def formal_result_to_plots(
    result: Mapping[str, Any],
    project: Mapping[str, Any] | None = None,
    ray_view_options: RayViewOptions | Mapping[str, Any] | None = None,
    *,
    requested_keys: set[str] | frozenset[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """将正式仿真结果转换为按显示名称索引的绘图载荷。

    ``requested_keys`` 控制只计算当前页面需要的图，避免一次结果刷新时
    生成所有诊断图。返回值只描述数据和图类型，不直接创建 Qt 或 Matplotlib
    对象。
    """
    arrays = dict(result.get("arrays", {}) or {})
    project = dict(project or {})
    requested = set(requested_keys or {
        "光路", "3D光路", "点列图", "PSF", "MTF", "端面匹配", "光束包络",
        "束腰位置", "模式重叠", "耦合场", "中心截面", "振幅", "相位",
        "相位对比", "多平面演化", "能量分解", "焦面截面", "光斑尺寸", "光纤基模", "XY模场比较", "重叠贡献", "波前",
    })
    plots: dict[str, dict[str, Any]] = {}

    # 几何光路由光线数据集适配器负责，2D/3D 结果共享同一份射线数据。
    if requested & {"光路", "3D光路"}:
        dataset = FormalRayDataset.from_backend(arrays, project)
        if dataset is not None:
            options = (
                ray_view_options
                if isinstance(ray_view_options, RayViewOptions)
                else RayViewOptions.from_mapping(
                    dict(ray_view_options or {}) if ray_view_options is not None else None
                )
            )
            ray_plots = build_ray_view_plots(dataset, options)
            for value in ray_plots.values():
                if str(value.get("kind", "")) in {"raytrace3d", "optical_scene_3d"}:
                    value.setdefault("render_quality", "high")
            plots.update({key: value for key, value in ray_plots.items() if key in requested})

    # 成像质量相关图表由 wave_results 统一生成。
    if "点列图" in requested:
        spot = _spot_plot(arrays, metrics=dict(result.get("metrics", {}) or {}))
        if spot:
            plots["点列图"] = spot

    if "PSF" in requested:
        psf = _psf_plot(arrays, project)
        if psf:
            plots["PSF"] = psf

    if "焦面截面" in requested:
        profile = _psf_profile_plot(arrays, project)
        if profile:
            plots["焦面截面"] = profile

    if "光斑尺寸" in requested:
        size = _psf_size_plot(arrays, project)
        if size:
            plots["光斑尺寸"] = size

    if "MTF" in requested:
        mtf = _mtf_plot(arrays)
        if mtf:
            plots["MTF"] = mtf

    if "波前" in requested:
        wavefront = _wavefront_plot(arrays)
        if wavefront:
            plots["波前"] = wavefront

    # 耦合类页面的多个视图共享同一组接收场、光纤模式和指标。
    coupling_keys = {
        "端面匹配", "光束包络", "束腰位置", "模式重叠", "耦合场",
        "中心截面", "振幅", "相位", "相位对比", "多平面演化",
        "能量分解", "光纤基模", "XY模场比较", "重叠贡献",
    }
    if requested & coupling_keys:
        coupling_plots = _coupling_plots(
            arrays, metrics=dict(result.get("metrics", {}) or {}), project=project
        )
        plots.update({key: value for key, value in coupling_plots.items() if key in requested})
        # 光束包络沿用束腰数据，只改标题，避免重复计算传播曲线。
        if "光束包络" in requested and "束腰位置" in coupling_plots:
            envelope = dict(coupling_plots["束腰位置"])
            envelope["title"] = "光束传播包络"
            plots["光束包络"] = envelope
        # 以下三类复合图由通用工程视图根据已有数组/指标派生。
        if "相位对比" in requested:
            plots["相位对比"] = build_phase_comparison(arrays, source=FORMAL_SOURCE)
        if "多平面演化" in requested:
            plots["多平面演化"] = build_multi_plane_evolution(
                arrays,
                coupling_plots.get("端面匹配"),
                coupling_plots.get("束腰位置"),
                source=FORMAL_SOURCE,
            )
        if "能量分解" in requested:
            plots["能量分解"] = build_energy_flow(
                dict(result.get("metrics", {}) or {}), source=FORMAL_SOURCE
            )

    # 所有正式结果统一标记来源，结果面板可据此显示“正式仿真”。
    for payload in plots.values():
        payload.setdefault("source", FORMAL_SOURCE)
    return plots

def formal_ray_dataset_from_result(
    result: Mapping[str, Any],
    project: Mapping[str, Any] | None = None,
) -> FormalRayDataset | None:
    """从正式结果构造光线数据集；数据不足时返回 None。"""
    arrays = dict(result.get("arrays", {}) or {})
    return FormalRayDataset.from_backend(arrays, dict(project or {}))

def formal_ray_views(
    dataset: FormalRayDataset,
    ray_view_options: RayViewOptions | Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """根据光线数据集和视图选项生成 2D/3D 光路载荷。"""
    options = (
        ray_view_options
        if isinstance(ray_view_options, RayViewOptions)
        else RayViewOptions.from_mapping(
            dict(ray_view_options or {}) if ray_view_options is not None else None
        )
    )
    return build_ray_view_plots(dataset, options)

def formal_result_diagnostics(result: Mapping[str, Any]) -> str:
    """把结果状态、收敛、耗时、警告和错误整理成可读诊断文本。"""
    lines = [
        f"结果状态：{result.get('status', 'unknown')}",
        f"收敛：{'是' if bool(result.get('converged', False)) else '否'}",
        f"耗时：{float(result.get('elapsed_ms', 0.0) or 0.0):.1f} ms",
    ]
    warnings = [str(item) for item in result.get("warnings", []) or []]
    errors = [_error_text(item) for item in result.get("errors", []) or []]
    if warnings:
        lines.append("警告：" + "；".join(warnings[:6]))
    if errors:
        lines.append("错误：" + "；".join(errors[:6]))
    metadata = dict(result.get("metadata", {}) or {})
    if metadata.get("sampling_converged") is not None:
        lines.append(f"采样收敛：{'是' if metadata.get('sampling_converged') else '否'}")
    return "\n".join(lines)

def preview_result_to_plots(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """整理快速预览结果，并补齐耦合类派生视图。"""
    plots = {
        str(key): dict(value or {})
        for key, value in result.items()
        if key != "诊断" and isinstance(value, Mapping)
    }
    for value in plots.values():
        if str(value.get("kind", "")) in {"raytrace3d", "optical_scene_3d"}:
            value.setdefault("render_quality", "interactive")

    # 预览结果可能只返回三种耦合入口之一，统一从它推导其他视图。
    coupling = plots.get("端面匹配") or plots.get("模式重叠") or plots.get("耦合场")
    if coupling:
        plots.setdefault("耦合场", dict(coupling))
        overlay = _mode_overlay_from_pair(coupling)
        if overlay is not None:
            plots["端面匹配"] = overlay
            plots["模式重叠"] = dict(overlay)
        derived = _derived_coupling_views(coupling, source=str(coupling.get("source", "快速预览")))
        plots.update(derived)
        if "束腰位置" in derived:
            envelope = dict(derived["束腰位置"])
            envelope["title"] = "光束传播包络"
            plots.setdefault("光束包络", envelope)
    return plots
