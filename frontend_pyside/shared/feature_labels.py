from __future__ import annotations



import re


_EXACT = {
    "target": "目标值",
    "目标值": "目标值",
    "receiver.axial_offset_z_mm": "光纤轴向偏移 Z（mm）",
    "receiver.axial_offset_z_um": "光纤轴向偏移 Z（μm）",
    "receiver.offset_x_mm": "光纤 X 方向偏移（mm）",
    "receiver.offset_y_mm": "光纤 Y 方向偏移（mm）",
    "receiver.offset_x_um": "光纤 X 方向偏移（μm）",
    "receiver.offset_y_um": "光纤 Y 方向偏移（μm）",
    "fiber.offset_x_mm": "光纤 X 方向偏移（mm）",
    "fiber.offset_y_mm": "光纤 Y 方向偏移（mm）",
    "fiber.offset_x_um": "光纤 X 方向偏移（μm）",
    "fiber.offset_y_um": "光纤 Y 方向偏移（μm）",
    "offset_x_mm": "光纤 X 方向偏移（mm）",
    "offset_y_mm": "光纤 Y 方向偏移（mm）",
    "offset_x_um": "光纤 X 方向偏移（μm）",
    "offset_y_um": "光纤 Y 方向偏移（μm）",
    "axial_offset_z_mm": "光纤轴向偏移 Z（mm）",
    "axial_offset_z_um": "光纤轴向偏移 Z（μm）",
    "receiver.tilt_x_rad": "光纤 X 方向倾角（rad）",
    "receiver.tilt_y_rad": "光纤 Y 方向倾角（rad）",
    "receiver.tilt_x_urad": "光纤 X 方向倾角（μrad）",
    "receiver.tilt_y_urad": "光纤 Y 方向倾角（μrad）",
    "receiver.tilt_x_deg": "光纤 X 方向倾角（°）",
    "receiver.tilt_y_deg": "光纤 Y 方向倾角（°）",
    "fiber.tilt_x_deg": "光纤 X 方向倾角（°）",
    "fiber.tilt_y_deg": "光纤 Y 方向倾角（°）",
    "fiber.tilt_x_rad": "光纤 X 方向倾角（rad）",
    "fiber.tilt_y_rad": "光纤 Y 方向倾角（rad）",
    "source.wavelength_nm": "波长（nm）",
    "source.waist_x_um": "X 方向束腰半径（μm）",
    "source.waist_y_um": "Y 方向束腰半径（μm）",
    # 系统轴向距离采用统一术语。image_distance 是最后光学表面到
    # 接收面/像面的距离，不与 object_distance（物距）混用。
    "image_distance": "接收面位置（mm）",
    "image_distance_mm": "接收面位置（mm）",
    "system.image_distance": "接收面位置（mm）",
    "system.image_distance_mm": "接收面位置（mm）",
    "object_distance": "物距（mm）",
    "object_distance_mm": "物距（mm）",
    "source.object_distance": "物距（mm）",
    "source.object_distance_mm": "物距（mm）",
    "beam.size_ratio_x": "X 方向尺寸比",
    "beam.size_ratio_y": "Y 方向尺寸比",
    "size_ratio_x": "X 方向尺寸比",
    "size_ratio_y": "Y 方向尺寸比",
    "size_log_mismatch": "尺寸失配程度（对数）",
    "size_log_signed": "光束与模场尺寸对数比",
    "size_ratio": "光束与模场尺寸比",
    "fiber_mode_radius_um": "光纤模场半径（μm）",
    "beam_radius_at_receiver_um": "接收面光束半径（μm）",
    "lateral_mismatch": "横向失配",
    "angular_mismatch": "角度失配",
    "axial_mismatch": "轴向离焦",
    "curvature_mismatch": "曲率失配",
    "cylindrical_lens_spacing": "柱面镜间距",
    "wavefront_rms": "波前 RMS",
    "coupling_efficiency": "模式耦合效率",
    "total_coupling_efficiency": "总耦合效率",
    "system_efficiency": "系统总效率",
}

_FIELD_NAMES = {
    "radius_mm": "曲率半径（mm）",
    "curvature": "曲率",
    "thickness_mm": "厚度（mm）",
    "distance_to_next_mm": "后间距（mm）",
    "semi_diameter_mm": "半口径（mm）",
    "conic": "圆锥系数",
    "material": "材料",
}


def display_feature_name(name: object, *, fallback_index: int | None = None) -> str:

    text = str(name or "").strip()
    if not text:
        return f"未登记特征 #{fallback_index}" if fallback_index is not None else "未登记特征"
    if text in _EXACT:
        return _EXACT[text]
    low = text.lower()
    if low in _EXACT:
        return _EXACT[low]

    # 支持数组路径 surfaces[1].field，也支持部分数据框/Parquet 展平后
    # 出现的 surfaces.1.field；二者统一进入同一个显示名注册表。
    surface = re.fullmatch(r"surfaces?(?:\[(\d+)\]|\.(\d+))\.(.+)", low)
    if surface:
        raw_index = surface.group(1) if surface.group(1) is not None else surface.group(2)
        number = int(raw_index) + 1
        field = _FIELD_NAMES.get(surface.group(3))
        if field:
            return f"第{number}表面{field}"
        return f"未登记特征：{text}"

    gap = re.fullmatch(r"(?:gap|air_gap|distance)[_\-]?(\d+)(?:_mm)?", low)
    if gap:
        return f"第{int(gap.group(1))}段镜间距（mm）"

    lens_gap = re.fullmatch(r"lens[_\-]?(\d+)[_\-]?(?:to|_)[_\-]?lens[_\-]?(\d+).*", low)
    if lens_gap:
        return f"透镜{int(lens_gap.group(1))}—透镜{int(lens_gap.group(2))}间距（mm）"

    
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    if text.upper() in {"NA", "M²", "RMS", "MAE", "R²", "SHAP", "LP01", "HE11", "PSF", "MTF"}:
        return text

    return f"未登记特征：{text}"


def is_adjustable_feature_name(name: object) -> bool:
    """Return True when a SHAP feature maps to a parameter the user can scan directly."""
    text = str(name or "").strip().lower()
    if not text:
        return False
    if re.fullmatch(r"surfaces?(?:\[(\d+)\]|\.(\d+))\.(radius_mm|distance_to_next_mm)", text):
        return True
    if text in {
        "image_distance", "image_distance_mm", "system.image_distance", "system.image_distance_mm",
        "receiver.axial_offset_z_mm", "axial_offset_z_mm",
        "receiver.offset_x_mm", "receiver.offset_y_mm", "offset_x_mm", "offset_y_mm",
        "receiver.tilt_x_deg", "receiver.tilt_y_deg",
        "source.wavelength_nm", "source.waist_x_um", "source.waist_y_um",
    }:
        return True
    return False


def is_unmapped_feature_name(name: object) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    return display_feature_name(text).startswith("未登记特征")


__all__ = ["display_feature_name", "is_unmapped_feature_name", "is_adjustable_feature_name"]
