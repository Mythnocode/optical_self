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
    "receiver.tilt_x_rad": "光纤 X 方向倾角（rad）",
    "receiver.tilt_y_rad": "光纤 Y 方向倾角（rad）",
    "receiver.tilt_x_urad": "光纤 X 方向倾角（μrad）",
    "receiver.tilt_y_urad": "光纤 Y 方向倾角（μrad）",
    "source.wavelength_nm": "波长（nm）",
    "source.waist_x_um": "X 方向束腰半径（μm）",
    "source.waist_y_um": "Y 方向束腰半径（μm）",
    "beam.size_ratio_x": "X 方向尺寸比",
    "beam.size_ratio_y": "Y 方向尺寸比",
    "size_ratio_x": "X 方向尺寸比",
    "size_ratio_y": "Y 方向尺寸比",
    "size_ratio": "尺寸失配",
    "lateral_mismatch": "横向失配",
    "angular_mismatch": "角度失配",
    "axial_mismatch": "轴向离焦",
    "curvature_mismatch": "曲率失配",
    "cylindrical_lens_spacing": "柱面镜间距",
    "wavefront_rms": "波前 RMS",
    "coupling_efficiency": "耦合效率",
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
        return f"参数{fallback_index}" if fallback_index is not None else "未命名参数"
    if text in _EXACT:
        return _EXACT[text]
    low = text.lower()
    if low in _EXACT:
        return _EXACT[low]

    surface = re.fullmatch(r"surfaces?\[(\d+)\]\.(.+)", low)
    if surface:
        number = int(surface.group(1)) + 1
        field = _FIELD_NAMES.get(surface.group(2))
        if field:
            return f"第{number}表面{field}"
        return f"第{number}表面参数"

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

    return f"参数{fallback_index}" if fallback_index is not None else "未命名参数"


__all__ = ["display_feature_name"]
