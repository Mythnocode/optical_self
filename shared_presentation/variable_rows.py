"""Original authored-surface labels shared by desktop and Web presentation."""

def variable_rows(project) -> list[tuple[str, str, str, str]]:
    """Return (key, group, face, parameter) rows for filters and the variable table."""
    rows: list[tuple[str, str, str, str]] = []
    surfaces = list(getattr(project, "surfaces", ()) or ())
    for index, surface in enumerate(surfaces):
        group = str(getattr(surface, "group_id", "") or getattr(surface, "name", "") or f"S{index + 1}")
        name = str(getattr(surface, "name", "") or f"面{index}")
        kind = str(getattr(surface, "surface_type", "球面") or "球面")
        if kind not in {"光阑", "平面", "探测器/像面", "像面", "物面"}:
            rows.append((f"surfaces[{index}].radius_mm", group, name, "曲率"))
            if hasattr(surface, "conic"):
                rows.append((f"surfaces[{index}].conic", group, name, "圆锥系数"))
        if kind not in {"探测器/像面", "像面"}:
            rows.append((f"surfaces[{index}].distance_to_next_mm", group, name, "厚度"))
        if kind == "光阑":
            rows.append((f"surfaces[{index}].semi_aperture_mm", group, name, "半口径"))
    rows.extend(
        (
            ("receiver.axial_offset_z_um", "光纤", "接收端", "轴向位置"),
            ("receiver.offset_x_um", "光纤", "接收端", "X 偏移"),
            ("receiver.offset_y_um", "光纤", "接收端", "Y 偏移"),
        )
    )
    return rows

