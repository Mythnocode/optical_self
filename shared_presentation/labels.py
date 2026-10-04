"""Qt-independent display labels from the original presentation layer."""
def parameter_label(name: object) -> str:
    text = str(name or "").strip()
    direct = {
        "receiver.axial_offset_z_mm": "光纤轴向位置",
        "receiver_axial_offset_z_mm": "光纤轴向位置",
        "receiver.axial_offset_z_um": "光纤轴向位置",
        "receiver_axial_offset_z_um": "光纤轴向位置",
        "receiver.offset_x_mm": "光纤X方向偏移",
        "receiver_offset_x_mm": "光纤X方向偏移",
        "receiver.offset_y_mm": "光纤Y方向偏移",
        "receiver_offset_y_mm": "光纤Y方向偏移",
        "receiver.tilt_x_deg": "光纤X方向倾角",
        "receiver_tilt_x_deg": "光纤X方向倾角",
        "receiver.tilt_y_deg": "光纤Y方向倾角",
        "receiver_tilt_y_deg": "光纤Y方向倾角",
        "receiver.mode_field_diameter_x_um": "光纤模场直径",
        "source.wavelength_nm": "波长",
        "wavelength_nm": "波长",
    }
    if text in direct:
        return direct[text]
    if text.startswith("surfaces["):
        try:
            index = int(text.split("[", 1)[1].split("]", 1)[0])
        except (ValueError, IndexError):
            index = -1
        surface_no = index + 1 if index >= 0 else "?"
        if text.endswith("radius_mm"):
            return f"S{surface_no}曲率半径"
        if text.endswith("distance_to_next_mm") or text.endswith("thickness_mm"):
            return f"S{surface_no}厚度"
        if text.endswith("semi_aperture_mm"):
            return f"S{surface_no}有效孔径"
        return f"S{surface_no}参数"
    aliases = {
        "spacing": "厚度",
        "curvature": "镜面曲率",
        "fiber": "光纤位置",
        "alignment": "五轴装调",
        "lens_count": "镜片数量",
        "lens_type": "镜片类型",
        "lens_order": "镜片排列",
        "fiber_axial": "光纤轴向位置",
        "fiber lateral": "光纤横向位置",
        "fiber_lateral": "光纤横向位置",
        "fiber tilt": "光纤角度倾斜",
        "fiber_tilt": "光纤角度倾斜",
    }
    return aliases.get(text, text.replace("_", " ") or "参数")
