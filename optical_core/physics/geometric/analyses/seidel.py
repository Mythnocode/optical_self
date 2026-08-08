# 三阶赛德尔像差分析。
# 按光学表面估算球差、彗差、像散、场曲、畸变、佩兹瓦尔和色差贡献，并指出主要贡献面和可能的优化方向。
# 所得数值仅作为工程层面用于像差分级与平衡优化的参考指标，不可替代厂商专用标准完整赛德尔像差表。
from __future__ import annotations

from typing import Any
import math

import numpy as np

from optical_core.models.domain.system import SequentialOpticalSystem
from optical_core.physics.geometric.analyses._native_helpers import AnalysisResult, C_LINE_NM, F_LINE_NM


THIRD_ORDER_KEYS = ("SⅠ 球差", "SⅡ 彗差", "SⅢ 像散", "SⅣ 场曲", "SⅤ 畸变", "佩兹瓦尔", "色差")


def _engineering_advice(totals: np.ndarray, keys: tuple[str, ...]) -> list[str]:
    advice: list[str] = []
    abs_totals = np.abs(np.asarray(totals, dtype=float))
    finite = abs_totals[np.isfinite(abs_totals)]
    if not finite.size:
        return ["当前系统缺少可用三阶数据。"]
    scale = float(np.nanmax(finite)) or 1.0
    lookup = {key: float(abs_totals[i]) / scale for i, key in enumerate(keys[: len(abs_totals)])}
    if lookup.get("SⅠ 球差", 0.0) > 0.25:
        advice.append("球差较强：优先调整前组曲率、弯月形状，必要时加入非球面。")
    if lookup.get("SⅡ 彗差", 0.0) > 0.25:
        advice.append("彗差较强：检查光阑位置、离轴视场和主光线高度。")
    if lookup.get("SⅢ 像散", 0.0) > 0.25:
        advice.append("像散较强：检查离轴场点下子午/弧矢焦面分离。")
    if lookup.get("SⅣ 场曲", 0.0) > 0.25 or lookup.get("佩兹瓦尔", 0.0) > 0.25:
        advice.append("场曲较强：检查佩兹瓦尔和玻璃组合，可调整正负透镜功率分配。")
    if lookup.get("SⅤ 畸变", 0.0) > 0.25:
        advice.append("畸变较强：优先调整光阑位置和后组功率分配。")
    if lookup.get("色差", 0.0) > 0.25:
        advice.append("色差较强：调整玻璃阿贝数搭配，检查 N-BK7/N-SF11 等材料组合。")
    if not advice:
        advice.append("未发现单项三阶指标明显占优，可结合光线扇形图、光程差和 MTF 继续判断。")
    return advice


def _field_for_table(field_x_deg: float, field_y_deg: float) -> tuple[float, float, str]:
    fx = float(field_x_deg)
    fy = float(field_y_deg)
    if abs(fx) <= 1.0e-12 and abs(fy) <= 1.0e-12:
        return 0.2, 0.0, "当前为轴上视场；三阶离轴项使用 0.2° 参考视场，球差仍按轴上边缘光计算。"
    return fx, fy, "使用当前视场。"


def _paraxial_surface_samples(
    system: SequentialOpticalSystem,
    *,
    wavelength_nm: float,
    field_x_deg: float,
    field_y_deg: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    count = len(system.surfaces)
    marginal_height = np.zeros(count, dtype=float)
    marginal_angle = np.zeros(count, dtype=float)
    chief_height = np.zeros(count, dtype=float)
    if count == 0:
        return marginal_height, marginal_angle, chief_height

    radius = float(system.pupil_radius_mm)
    field_angle = math.radians(math.hypot(float(field_x_deg), float(field_y_deg)))

    
    y_m = radius
    u_m = 0.0
    y_c = 0.0
    n0 = system.material_index(system.surfaces[0].material_before, wavelength_nm)
    u_c = n0 * math.tan(field_angle)

    for index, surface in enumerate(system.surfaces):
        n1 = system.material_index(surface.material_before, wavelength_nm)
        n2 = system.material_index(surface.material_after, wavelength_nm)
        marginal_height[index] = y_m
        marginal_angle[index] = math.degrees(math.atan2(u_m, max(n1, 1.0e-12)))
        chief_height[index] = y_c
        curvature = 0.0 if surface.is_plane else 1.0 / float(surface.radius_mm)
        power = (n2 - n1) * curvature
        u_m = u_m - power * y_m
        u_c = u_c - power * y_c
        if index < count - 1:
            distance = float(surface.distance_to_next_mm)
            y_m = y_m + distance * u_m / max(n2, 1.0e-12)
            y_c = y_c + distance * u_c / max(n2, 1.0e-12)
    return marginal_height, marginal_angle, chief_height


def third_order_seidel_table(
    system: SequentialOpticalSystem,
    *,
    field_x_deg: float = 0.0,
    field_y_deg: float = 0.0,
    wavelength_nm: float | None = None,
    wavelength_f_nm: float = F_LINE_NM,
    wavelength_c_nm: float = C_LINE_NM,
) -> dict[str, Any]:
    wl = float(wavelength_nm or system.wavelength_nm)
    fx, fy, field_note = _field_for_table(field_x_deg, field_y_deg)
    marginal_heights, marginal_angles, chief_heights = _paraxial_surface_samples(
        system,
        wavelength_nm=wl,
        field_x_deg=fx,
        field_y_deg=fy,
    )
    rows: list[dict[str, Any]] = []
    values: list[list[float]] = []
    scale = max(float(system.pupil_radius_mm), 1.0e-12)

    for index, surface in enumerate(system.surfaces):
        n1 = system.material_index(surface.material_before, wl)
        n2 = system.material_index(surface.material_after, wl)
        n1_f = system.material_index(surface.material_before, wavelength_f_nm)
        n2_f = system.material_index(surface.material_after, wavelength_f_nm)
        n1_c = system.material_index(surface.material_before, wavelength_c_nm)
        n2_c = system.material_index(surface.material_after, wavelength_c_nm)
        curvature = 0.0 if surface.is_plane else 1.0 / float(surface.radius_mm)
        power = (n2 - n1) * curvature
        power_f = (n2_f - n1_f) * curvature
        power_c = (n2_c - n1_c) * curvature
        h = float(marginal_heights[index])
        hb = float(chief_heights[index])
        hs = h / scale
        hbs = hb / scale
        sphere = power * hs**4
        coma = power * hs**3 * hbs
        astig = power * hs**2 * hbs**2
        petzval = -power / max(n2, 1.0e-12)
        field = astig + petzval
        distortion = power * hs * hbs**3
        chromatic = (power_f - power_c) * hs**2
        row_values = [sphere, coma, astig, field, distortion, petzval, chromatic]
        finite = np.asarray(row_values, dtype=float)
        main_idx = int(np.nanargmax(np.abs(finite))) if finite.size else 0
        label = f"第 {index + 1} 面"
        rows.append(
            {
                "surface": label,
                "radius_mm": float(surface.radius_mm) if not surface.is_plane else float("inf"),
                "before": str(surface.material_before),
                "after": str(surface.material_after),
                "n_before": float(n1),
                "n_after": float(n2),
                "surface_power": float(power),
                "marginal_height_mm": float(h),
                "marginal_angle_deg": float(marginal_angles[index]),
                "chief_height_mm": float(hb),
                "values": row_values,
                "dominant": THIRD_ORDER_KEYS[main_idx],
            }
        )
        values.append(row_values)

    arr = np.asarray(values, dtype=float) if values else np.zeros((0, len(THIRD_ORDER_KEYS)), dtype=float)
    totals = np.nansum(arr, axis=0) if arr.size else np.zeros(len(THIRD_ORDER_KEYS), dtype=float)
    dominant: dict[str, str] = {}
    labels = [row["surface"] for row in rows]
    for col, key in enumerate(THIRD_ORDER_KEYS):
        if arr.shape[0] and np.any(np.isfinite(arr[:, col])):
            idx = int(np.nanargmax(np.abs(arr[:, col])))
            dominant[key] = str(labels[idx])
        else:
            dominant[key] = "--"
    return {
        "keys": np.asarray(THIRD_ORDER_KEYS, dtype=object),
        "surface_labels": np.asarray(labels, dtype=object),
        "values": arr,
        "totals": totals,
        "rows": rows,
        "dominant_surfaces": dominant,
        "engineering_advice": _engineering_advice(totals, THIRD_ORDER_KEYS),
        "field_x_deg": float(fx),
        "field_y_deg": float(fy),
        "field_note": field_note,
        "wavelength_nm": float(wl),
        "unit_notes": "三阶赛德尔近轴设计指标：以面功率、边缘光高度和主光线高度归一化构造，适合面贡献排序和优化方向判断。",
    }


def evaluate_seidel(system: SequentialOpticalSystem, options: dict[str, Any] | None = None) -> AnalysisResult:
    opts = dict(options or {})
    table = third_order_seidel_table(
        system,
        field_x_deg=float(opts.get("field_x_deg", 0.0)),
        field_y_deg=float(opts.get("field_y_deg", 0.0)),
        wavelength_nm=opts.get("wavelength_nm", system.wavelength_nm),
        wavelength_f_nm=float(opts.get("wavelength_f_nm", F_LINE_NM)),
        wavelength_c_nm=float(opts.get("wavelength_c_nm", C_LINE_NM)),
    )
    keys = list(THIRD_ORDER_KEYS)
    totals = np.asarray(table["totals"], dtype=float)
    metrics = {
        "seidel_total_spherical": float(totals[0]),
        "seidel_total_coma": float(totals[1]),
        "seidel_total_astigmatism": float(totals[2]),
        "seidel_total_field_curvature": float(totals[3]),
        "seidel_total_distortion": float(totals[4]),
        "seidel_total_petzval": float(totals[5]),
        "seidel_total_chromatic": float(totals[6]),
        "seidel_surface_count": float(len(table["rows"])),
    }
    arrays = {
        "seidel_keys": keys,
        "seidel_surface_labels": np.asarray(table["surface_labels"], dtype=object).tolist(),
        "seidel_values": np.asarray(table["values"], dtype=float).tolist(),
        "seidel_totals": totals.tolist(),
        "seidel_rows": table["rows"],
        "seidel_engineering_advice": list(table["engineering_advice"]),
    }
    return AnalysisResult(metrics=metrics, arrays=arrays, metadata={"seidel_done": True, "field_note": table["field_note"], "optical_axis": "+z"})



def seidel_surface_contributions(system: SequentialOpticalSystem, **kwargs: Any) -> dict[str, Any]:
    return third_order_seidel_table(system, **kwargs)


__all__ = [
    "THIRD_ORDER_KEYS",
    "evaluate_seidel",
    "seidel_surface_contributions",
    "third_order_seidel_table",
]
