"""Original scan chart presentation, shared by both frontends."""
from typing import Any
RESPONSE_KIND={"耦合效率":"coupling_efficiency","RMS 光斑":"rms_spot_radius_um","Strehl":"strehl_estimate_marechal","边缘功率":"edge_power"}

def scan_curve_payload(result: dict[str, Any], response_label: str) -> dict[str, Any] | None:
    grid = result.get("parameter_grid") or []
    key = RESPONSE_KIND.get(str(response_label), str(response_label or "coupling_efficiency"))
    ys = [float(value) if value is not None else float("nan") for value in (result.get("response_values") or {}).get(key) or []]
    two_dimensional = bool(grid and isinstance(grid[0], (list, tuple)) and len(grid[0]) >= 2)
    if two_dimensional:
        pairs = [tuple(map(float, point[:2])) for point in grid if isinstance(point, (list, tuple)) and len(point) >= 2]
        if not pairs or len(pairs) != len(ys):
            return None
        xs = sorted({pair[0] for pair in pairs})
        second = sorted({pair[1] for pair in pairs})
        if not xs or not second:
            return None
        if len(xs) * len(second) > 1_000_000:
            return {'kind':'empty','message':'响应点过多，无法安全构造热图；请减小采样数量。'}
        row_index = {value: index for index, value in enumerate(second)}
        column_index = {value: index for index, value in enumerate(xs)}
        z = [[float("nan") for _ in xs] for _ in second]
        for (x_value, y_value), response in zip(pairs, ys):
            z[row_index[y_value]][column_index[x_value]] = response
        return {
            "kind": "heatmap", "z": z,
            "extent": [xs[0], xs[-1], second[0], second[-1]],
            "x_label": "参数 1", "y_label": "参数 2",
            "title": f"二维扫描 · {response_label}",
            "source": "正式二维参数扫描",
        }
    xs = [float(point[0]) for point in grid if isinstance(point, (list, tuple)) and point]
    if not xs or not ys or len(xs) != len(ys):
        return None
    return {
        "kind": "line", "x": xs, "y": ys,
        "x_label": "参数", "y_label": str(response_label or "响应"),
        "series_label": str(response_label or "响应"), "source": "正式参数扫描",
    }

