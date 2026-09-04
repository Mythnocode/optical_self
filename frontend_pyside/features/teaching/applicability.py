from __future__ import annotations

"""Applicability and feasibility checks for the virtual optical platform.

The teaching canvas is intentionally permissive while the user is assembling a
system.  Formal calculation is not: it must first prove that the current scene
has a supported receiver, a monotonically ordered lens train, usable materials
and coatings, and mechanically possible air gaps.  This module is deliberately
Qt-free so the same rules can be regression tested and reused by reports.
"""

import math
from dataclasses import dataclass
from typing import Any

from .experiment_scene import SCENE_MM_PER_PX


@dataclass(frozen=True, slots=True)
class ApplicabilityIssue:
    code: str
    level: str
    message: str
    affected: str = ""


@dataclass(frozen=True, slots=True)
class ApplicabilityReport:
    wavelength_nm: float
    coupling_mode: str
    recommended_model: str
    prescription_source: str
    issues: tuple[ApplicabilityIssue, ...]

    @property
    def allowed(self) -> bool:
        return not any(item.level == "error" for item in self.issues)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(item.message for item in self.issues if item.level == "error")

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(item.message for item in self.issues if item.level == "warning")

    @property
    def messages(self) -> tuple[str, ...]:
        return tuple(
            ("错误：" if item.level == "error" else "提示：") + item.message
            for item in self.issues
        )


# Conservative transparency ranges.  A component can narrow this further with
# ``coating_min_nm`` / ``coating_max_nm`` or ``wavelength_min_nm`` /
# ``wavelength_max_nm``.  These ranges establish applicability, not throughput.
MATERIAL_BANDS_NM: dict[str, tuple[float, float]] = {
    "AIR": (180.0, 20_000.0),
    "N-BK7": (330.0, 2_500.0),
    "BK7": (330.0, 2_500.0),
    "FUSED_SILICA": (180.0, 3_500.0),
    "SIO2": (180.0, 3_500.0),
    "CAF2": (180.0, 8_000.0),
    "SF11": (370.0, 2_500.0),
}

RECEIVER_KINDS = frozenset({"fiber", "imaging_camera", "focus_scan_module", "beam_analyzer", "ccd", "camera"})


def _number(params: dict[str, Any], key: str, default: float) -> float:
    try:
        raw = params.get(key, default)
        value = float(default if raw is None or raw == "" else raw)
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def lens_prescription(node: Any) -> dict[str, Any]:
    """Return one normalized lens prescription with an explicit source label."""
    params = dict(getattr(node, "params", {}) or {})
    focal = _number(params, "focal_mm", 0.0)
    material = str(params.get("material", "N-BK7") or "N-BK7").strip().upper()
    refractive_index = _number(params, "refractive_index", 1.5168)
    explicit = all(
        isinstance(params.get(key), (int, float)) and abs(float(params[key])) > 1e-12
        for key in ("front_radius_mm", "back_radius_mm")
    )
    if explicit:
        front = float(params["front_radius_mm"])
        back = float(params["back_radius_mm"])
        source = str(params.get("prescription_source", "器件处方") or "器件处方")
    else:
        # Focal-length-only objects remain usable for teaching, but are clearly
        # marked as an approximation and never described as a catalog lens.
        radius = 2.0 * (refractive_index - 1.0) * focal
        front, back = radius, -radius
        source = "焦距推导的对称双凸近似"
    if bool(params.get("reversed", params.get("mount_flipped", False))):
        front, back = -back, -front
        front_conic = _number(params, "back_conic", 0.0)
        back_conic = _number(params, "front_conic", 0.0)
    else:
        front_conic = _number(params, "front_conic", 0.0)
        back_conic = _number(params, "back_conic", 0.0)
    return {
        "front_radius_mm": front,
        "back_radius_mm": back,
        "front_conic": front_conic,
        "back_conic": back_conic,
        "thickness_mm": _number(params, "thickness_mm", 3.0),
        "material": material,
        "semi_aperture_mm": _number(params, "semi_aperture_mm", 12.5),
        "mechanical_diameter_mm": _number(params, "mechanical_diameter_mm", 25.4),
        "coating": str(params.get("coating", "未指定") or "未指定"),
        "source": source,
        "explicit": explicit,
    }


def _receiver_mode(receiver: Any | None) -> str:
    kind = str(getattr(receiver, "kind", "") or "")
    return {
        "fiber": "自由空间→透镜聚焦→光纤耦合",
        "imaging_camera": "自由空间→透镜组合→相机测量",
        "ccd": "自由空间→透镜组合→CCD 测量",
        "camera": "自由空间→透镜组合→相机测量",
        "focus_scan_module": "自由空间→透镜组合→焦面扫描",
        "beam_analyzer": "自由空间→透镜组合→光束分析",
    }.get(kind, "未形成受支持的接收方式")


def _recommended_model(model: Any, receiver: Any | None) -> str:
    na = abs(float(getattr(model, "receiver_na", 0.0) or 0.0))
    receiver_params = dict(getattr(receiver, "params", {}) or {}) if receiver is not None else {}
    na = max(na, abs(_number(receiver_params, "na", 0.0)))
    polarization_sensitive = bool(receiver_params.get("polarization_sensitive", False)) or any(
        str(getattr(node, "kind", "")) in {"pbs", "polarizer", "half_wave_plate"}
        for node in dict(getattr(model, "nodes", {}) or {}).values()
    )
    if na >= 0.35 or polarization_sensitive:
        return "矢量/复场模型（含偏振重叠）"
    if na >= 0.12:
        return "几何追迹＋标量复场重叠"
    return "近轴预估＋几何追迹；最终耦合用复场核验"


def evaluate_scene_applicability(model: Any) -> ApplicabilityReport:
    nodes = list(dict(getattr(model, "nodes", {}) or {}).values())
    laser = next((node for node in nodes if str(getattr(node, "kind", "")) == "laser"), None)
    laser_params = dict(getattr(laser, "params", {}) or {}) if laser is not None else {}
    wavelength = float(laser_params.get("wavelength_nm", getattr(model, "wavelength_nm", 0.0)) or 0.0)
    lenses = sorted(
        (node for node in nodes if str(getattr(node, "kind", "")) == "lens"),
        key=lambda node: float(getattr(node, "x", 0.0)),
    )
    receivers = sorted(
        (node for node in nodes if str(getattr(node, "kind", "")) in RECEIVER_KINDS),
        key=lambda node: float(getattr(node, "x", 0.0)),
    )
    receiver = next(
        (node for node in receivers if float(getattr(node, "x", 0.0)) > (float(getattr(lenses[-1], "x", 0.0)) if lenses else -math.inf)),
        receivers[0] if receivers else None,
    )
    issues: list[ApplicabilityIssue] = []

    if not math.isfinite(wavelength) or wavelength < 180.0 or wavelength > 20_000.0:
        issues.append(ApplicabilityIssue("wavelength", "error", f"波长 {wavelength:g} nm 超出平台支持的 180–20000 nm 基础范围。"))
    if not lenses:
        issues.append(ApplicabilityIssue(
            "lens_missing", "warning",
            "场景中没有透镜：仍可对 Laser→探测器等自由光路做场景追迹。",
        ))
    if receiver is None:
        issues.append(ApplicabilityIssue(
            "receiver_missing", "warning",
            "未放置接收面时光线会穿出场景；拖入 CCD/相机/光纤后可在命中点读光斑。",
        ))
    elif lenses and float(getattr(receiver, "x", 0.0)) <= float(getattr(lenses[-1], "x", 0.0)):
        issues.append(ApplicabilityIssue(
            "receiver_order", "warning",
            "接收面当前在透镜组之前或侧面：场景求解仍会追迹；命中该接收面即终止。顺序透镜组分析请把接收面放在最后一片透镜之后。",
            str(getattr(receiver, "id", "")),
        ))

    derived_count = 0
    explicit_count = 0
    for index, lens in enumerate(lenses):
        prescription = lens_prescription(lens)
        label = str(getattr(lens, "label", f"L{index + 1}") or f"L{index + 1}")
        if prescription["explicit"]:
            explicit_count += 1
        else:
            derived_count += 1
            issues.append(ApplicabilityIssue(
                "derived_prescription", "warning",
                f"{label} 只有焦距，正式场景暂用对称双凸近似；需补充曲率、厚度、材料、口径和安装方向后才能称为真实处方。",
                str(getattr(lens, "id", "")),
            ))
        if abs(float(prescription["front_radius_mm"])) <= 1e-9 or abs(float(prescription["back_radius_mm"])) <= 1e-9:
            issues.append(ApplicabilityIssue("invalid_radius", "error", f"{label} 的表面曲率无效。", str(getattr(lens, "id", ""))))
        if float(prescription["thickness_mm"]) <= 0.0:
            issues.append(ApplicabilityIssue("invalid_thickness", "error", f"{label} 的中心厚度必须大于 0 mm。", str(getattr(lens, "id", ""))))
        if float(prescription["semi_aperture_mm"]) <= 0.0:
            issues.append(ApplicabilityIssue("invalid_aperture", "error", f"{label} 的有效半口径必须大于 0 mm。", str(getattr(lens, "id", ""))))
        params = dict(getattr(lens, "params", {}) or {})
        band = MATERIAL_BANDS_NM.get(str(prescription["material"]).upper())
        low = _number(params, "wavelength_min_nm", band[0] if band else 0.0)
        high = _number(params, "wavelength_max_nm", band[1] if band else 0.0)
        if band is None and not (low > 0.0 and high > low):
            issues.append(ApplicabilityIssue("unknown_material", "error", f"{label} 的材料 {prescription['material']} 没有有效波段元数据。", str(getattr(lens, "id", ""))))
        elif wavelength and not (low <= wavelength <= high):
            issues.append(ApplicabilityIssue("material_band", "error", f"{label} 的材料适用波段为 {low:g}–{high:g} nm，当前为 {wavelength:g} nm。", str(getattr(lens, "id", ""))))
        coating_low = _number(params, "coating_min_nm", low)
        coating_high = _number(params, "coating_max_nm", high)
        if wavelength and coating_high > coating_low > 0.0 and not (coating_low <= wavelength <= coating_high):
            issues.append(ApplicabilityIssue("coating_band", "error", f"{label} 的镀膜适用波段为 {coating_low:g}–{coating_high:g} nm。", str(getattr(lens, "id", ""))))

    # Sequential spacing checks only apply to a monotonic lens train (and an
    # optional receiver that truly sits after the last lens).  Free-placement
    # layouts are validated by the scene ray-tree, not by forced x-order gaps.
    ordered = list(lenses)
    if receiver is not None and lenses and float(getattr(receiver, "x", 0.0)) > float(getattr(lenses[-1], "x", 0.0)):
        ordered.append(receiver)
    minimum_gap = max(0.0, float(getattr(model, "min_air_gap_mm", 0.5) or 0.5))
    physical_length_mm = 0.0
    has_explicit_spacing = False
    for index in range(max(0, len(ordered) - 1)):
        current = ordered[index]
        nxt = ordered[index + 1]
        params = dict(getattr(current, "params", {}) or {})
        thickness = lens_prescription(current)["thickness_mm"] if str(getattr(current, "kind", "")) == "lens" else 0.0
        if "air_gap_after_mm" in params:
            has_explicit_spacing = True
            centre_distance = _number(params, "air_gap_after_mm", 0.0) + float(thickness)
        else:
            has_explicit_spacing = has_explicit_spacing or "distance_to_next_mm" in params
            centre_distance = _number(
                params,
                "distance_to_next_mm",
                (float(getattr(nxt, "x", 0.0)) - float(getattr(current, "x", 0.0))) * SCENE_MM_PER_PX,
            )
        gap = centre_distance - float(thickness)
        physical_length_mm += max(0.0, centre_distance)
        if centre_distance <= 0.0 or gap < minimum_gap:
            issues.append(ApplicabilityIssue(
                "mechanical_overlap", "error",
                f"{getattr(current, 'label', '器件')}→{getattr(nxt, 'label', '器件')} 的空气间隔 {gap:.3f} mm 小于最小值 {minimum_gap:.3f} mm。",
                str(getattr(current, "id", "")),
            ))
    laser_distance = _number(laser_params, "object_distance_mm", 0.0)
    if laser_distance > 0.0:
        physical_length_mm += laser_distance
        has_explicit_spacing = True
    maximum_length = max(0.0, float(getattr(model, "max_system_length_mm", 0.0) or 0.0))
    if has_explicit_spacing and maximum_length > 0.0 and physical_length_mm > maximum_length:
        issues.append(ApplicabilityIssue(
            "system_length", "error",
            f"显式光学长度 {physical_length_mm:.3f} mm 超出当前结构上限 {maximum_length:.3f} mm。",
        ))

    if receiver is not None and str(getattr(receiver, "kind", "")) == "fiber":
        rp = dict(getattr(receiver, "params", {}) or {})
        if abs(_number(rp, "pitch_mrad", 0.0)) > 350.0 or abs(_number(rp, "yaw_mrad", 0.0)) > 350.0:
            issues.append(ApplicabilityIssue("high_angle", "warning", "光纤倾角已超出近轴范围，应使用高角度/矢量模型复核。", str(getattr(receiver, "id", ""))))
    if any(str(getattr(node, "kind", "")) in {"pbs", "polarizer", "half_wave_plate"} for node in nodes):
        issues.append(ApplicabilityIssue("polarization", "warning", "系统包含偏振器件；标量快速估算不包含完整偏振重叠，正式结论需使用偏振模型。"))

    if explicit_count and derived_count:
        source = "部分真实处方＋部分焦距近似"
    elif explicit_count:
        source = "器件级真实处方"
    elif derived_count:
        source = "焦距推导近似"
    else:
        source = "无透镜处方"
    return ApplicabilityReport(
        wavelength_nm=wavelength,
        coupling_mode=_receiver_mode(receiver),
        recommended_model=_recommended_model(model, receiver),
        prescription_source=source,
        issues=tuple(issues),
    )


__all__ = [
    "MATERIAL_BANDS_NM",
    "RECEIVER_KINDS",
    "ApplicabilityIssue",
    "ApplicabilityReport",
    "evaluate_scene_applicability",
    "lens_prescription",
]
