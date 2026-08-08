
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..ray_data_model import FormalRayDataset
from ..ray_view_adapters import RayViewOptions, build_ray_view_plots
from .array_utils import _error_text
from .coupling_results import _coupling_plots, _derived_coupling_views, _mode_overlay_from_pair
from .wave_results import _mtf_plot, _psf_plot, _spot_plot
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

    arrays = dict(result.get("arrays", {}) or {})
    project = dict(project or {})
    requested = set(requested_keys or {
        "光路", "3D光路", "点列图", "PSF", "MTF", "端面匹配", "光束包络",
        "束腰位置", "模式重叠", "耦合场", "中心截面", "振幅", "相位",
        "相位对比", "多平面演化", "能量分解",
    })
    plots: dict[str, dict[str, Any]] = {}

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

    if "点列图" in requested:
        spot = _spot_plot(arrays)
        if spot:
            plots["点列图"] = spot

    if "PSF" in requested:
        psf = _psf_plot(arrays, project)
        if psf:
            plots["PSF"] = psf

    if "MTF" in requested:
        mtf = _mtf_plot(arrays)
        if mtf:
            plots["MTF"] = mtf

    coupling_keys = {
        "端面匹配", "光束包络", "束腰位置", "模式重叠", "耦合场",
        "中心截面", "振幅", "相位", "相位对比", "多平面演化",
        "能量分解",
    }
    if requested & coupling_keys:
        coupling_plots = _coupling_plots(
            arrays, metrics=dict(result.get("metrics", {}) or {}), project=project
        )
        plots.update({key: value for key, value in coupling_plots.items() if key in requested})
        if "光束包络" in requested and "束腰位置" in coupling_plots:
            envelope = dict(coupling_plots["束腰位置"])
            envelope["title"] = "光束传播包络"
            plots["光束包络"] = envelope
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

    for payload in plots.values():
        payload.setdefault("source", FORMAL_SOURCE)
    return plots

def formal_ray_dataset_from_result(
    result: Mapping[str, Any],
    project: Mapping[str, Any] | None = None,
) -> FormalRayDataset | None:
    arrays = dict(result.get("arrays", {}) or {})
    return FormalRayDataset.from_backend(arrays, dict(project or {}))

def formal_ray_views(
    dataset: FormalRayDataset,
    ray_view_options: RayViewOptions | Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    options = (
        ray_view_options
        if isinstance(ray_view_options, RayViewOptions)
        else RayViewOptions.from_mapping(
            dict(ray_view_options or {}) if ray_view_options is not None else None
        )
    )
    return build_ray_view_plots(dataset, options)

def formal_result_diagnostics(result: Mapping[str, Any]) -> str:
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

    plots = {
        str(key): dict(value or {})
        for key, value in result.items()
        if key != "诊断" and isinstance(value, Mapping)
    }
    for value in plots.values():
        if str(value.get("kind", "")) in {"raytrace3d", "optical_scene_3d"}:
            value.setdefault("render_quality", "interactive")

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
