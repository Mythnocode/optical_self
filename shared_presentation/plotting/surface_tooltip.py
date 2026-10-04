"""Original optical-surface hover text, independent of the UI toolkit."""

def surface_tooltip(item: dict) -> str:
    return (
        f"S{int(item.get('surface_index', -1)) + 1} · {item.get('name', '')}\n"
        f"类型：{item.get('type', '—')}　材料：{item.get('material', '—')}\n"
        f"曲率半径：{float(item.get('radius', 0.0) or 0.0):.6g} mm\n"
        f"半口径：{float(item.get('aperture', 0.0) or 0.0):.6g} mm　"
        f"圆锥系数：{float(item.get('conic', 0.0) or 0.0):.6g}"
    )
