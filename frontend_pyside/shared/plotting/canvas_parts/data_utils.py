from __future__ import annotations

import numpy as np

def _downsample_grid(
    z: np.ndarray,
    x: np.ndarray | None = None,
    y: np.ndarray | None = None,
    *,
    max_rows: int = 384,
    max_cols: int = 384,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray, np.ndarray]:

    array = np.asarray(z)
    if array.ndim != 2 or not array.size:
        empty = np.asarray([], dtype=int)
        return array, x, y, empty, empty
    rows, cols = array.shape
    row_count = max(2, min(rows, int(max_rows)))
    col_count = max(2, min(cols, int(max_cols)))
    row_idx = np.unique(np.linspace(0, rows - 1, row_count, dtype=int))
    col_idx = np.unique(np.linspace(0, cols - 1, col_count, dtype=int))
    view = array[np.ix_(row_idx, col_idx)]
    x_view = np.asarray(x)[col_idx] if x is not None and len(x) == cols else x
    y_view = np.asarray(y)[row_idx] if y is not None and len(y) == rows else y
    return view, x_view, y_view, row_idx, col_idx


def _scene_static_signature(data: dict) -> tuple:
    surfaces = tuple(
        (
            int(item.get("surface_index", -1)),
            str(item.get("type", "")),
            str(item.get("group_id", "")),
            float(item.get("z", 0.0) or 0.0),
            float(item.get("radius", 0.0) or 0.0),
            float(item.get("conic", 0.0) or 0.0),
            float(item.get("aperture", 0.0) or 0.0),
            float(item.get("decenter_x", 0.0) or 0.0),
            float(item.get("decenter_y", 0.0) or 0.0),
            float(item.get("tilt_x_deg", 0.0) or 0.0),
            float(item.get("tilt_y_deg", 0.0) or 0.0),
            float(item.get("tilt_z_deg", 0.0) or 0.0),
        )
        for item in data.get("surfaces", [])
    )
    objects = tuple(
        (
            str(item.get("kind", "")),
            float(item.get("z", 0.0) or 0.0),
            float(item.get("center_x", 0.0) or 0.0),
            float(item.get("center_y", 0.0) or 0.0),
            float(item.get("radius", 0.0) or 0.0),
            float(item.get("width", 0.0) or 0.0),
            float(item.get("height", 0.0) or 0.0),
        )
        for item in data.get("objects", [])
        if str(item.get("kind", "")) in {"detector", "image"}
    )
    lens_groups = tuple(
        (
            str(item.get("group_id", "")),
            str(item.get("label", "")),
            tuple(int(value) for value in item.get("surface_indices", [])),
        )
        for item in data.get("lens_groups", [])
    )
    return (
        str(data.get("render_quality", "high")),
        str(data.get("scale_mode", "")),
        tuple(float(value) for value in data.get("optical_axis", [])),
        surfaces,
        lens_groups,
        objects,
    )

def _remove_artists(artists) -> None:
    seen: set[int] = set()
    for artist in artists:
        if artist is None or id(artist) in seen:
            continue
        seen.add(id(artist))
        try:
            artist.remove()
        except (ValueError, NotImplementedError):
            continue

def _field_crop_slices(
    field: np.ndarray,
    contour: np.ndarray,
    *,
    fraction: float,
) -> tuple[slice, slice]:
    fraction = min(max(float(fraction), 1.0e-6), 0.95)
    mask = np.zeros(field.shape, dtype=bool)
    finite_field = np.nan_to_num(field, nan=0.0)
    maximum = float(np.max(finite_field)) if finite_field.size else 0.0
    if maximum > 0.0:
        mask |= finite_field >= maximum * fraction
    if contour.shape == field.shape:
        finite_contour = np.nan_to_num(contour, nan=0.0)
        contour_max = float(np.max(finite_contour)) if finite_contour.size else 0.0
        if contour_max > 0.0:
            mask |= finite_contour >= contour_max * fraction
    indices = np.argwhere(mask)
    if not len(indices):
        return slice(0, field.shape[0]), slice(0, field.shape[1])
    low = np.min(indices, axis=0)
    high = np.max(indices, axis=0)
    padding = np.maximum(((high - low + 1) * 0.18).astype(int), 2)
    row0 = max(0, int(low[0] - padding[0]))
    row1 = min(field.shape[0], int(high[0] + padding[0] + 1))
    col0 = max(0, int(low[1] - padding[1]))
    col1 = min(field.shape[1], int(high[1] + padding[1] + 1))
    return slice(row0, row1), slice(col0, col1)

def _numeric_arrays(data: dict) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for key, value in data.items():
        try:
            array = np.asarray(value)
        except Exception:
            continue
        if array.size and array.dtype.kind in "biufc":
            arrays[str(key)] = array
    if data.get("rays"):
        for index, ray in enumerate(data["rays"]):
            points = ray.get("points") or np.column_stack((ray.get("x", []), ray.get("y", []), ray.get("z", []))).tolist()
            array = np.asarray(points, dtype=float)
            if array.size:
                arrays[f"ray_{index}_points"] = array
    return arrays

def _csv_rows(data: dict) -> list[list]:
    kind = data.get("kind")
    if kind in {"line", "scatter"}:
        return [[data.get("x_label", "x"), data.get("y_label", "y")], *zip(data.get("x", []), data.get("y", []))]
    if kind == "parameter_response":
        rows = [[data.get("x_label", "parameter"), data.get("y_label", "result"), "sample_type"]]
        rows.extend([x, y, "sample"] for x, y in zip(data.get("x", []), data.get("y", [])))
        for key, label in (("current_point", "current"), ("best_point", "best"), ("verified_point", "verified")):
            point = data.get(key)
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                rows.append([point[0], point[1], label])
        return rows
    if kind == "validation_scatter":
        return [["formal_value", "predicted_value"], *zip(data.get("actual", []), data.get("predicted", []))]
    if kind == "residual":
        return [["predicted_value", "prediction_minus_formal"], *zip(data.get("predicted", []), data.get("residual", []))]
    if kind == "waist_position":
        labels = [item.get("label", f"series_{i}") for i, item in enumerate(data.get("series", []))]
        columns = [data.get("x", [])] + [item.get("y", []) for item in data.get("series", [])]
        return [[data.get("x_label", "z"), *labels], *zip(*columns)] if columns else [["value"]]
    if kind == "waterfall":
        return [["feature", "shap_contribution"], *zip(data.get("labels", []), data.get("values", []))]
    if kind == "energy_flow":
        return [["stage", "remaining_percent", "loss_percent"], *zip(data.get("labels", []), data.get("cumulative", []), data.get("losses", []))]
    if kind == "candidate_compare":
        rows = [["candidate", "predicted", "formal", "feasible", "verified"]]
        for item in data.get("candidates", []):
            rows.append([item.get("label"), item.get("predicted"), item.get("formal"), item.get("feasible"), item.get("verified")])
        return rows
    if kind == "convergence_curve":
        return [["evaluation", "current", "best"], *zip(data.get("x", []), data.get("current", []), data.get("best", []))]
    if kind == "adjustment_trajectory":
        labels = [item.get("label", f"parameter_{i}") for i, item in enumerate(data.get("series", []))]
        columns = [data.get("x", []), data.get("efficiency", [])] + [item.get("y", []) for item in data.get("series", [])]
        return [["step", "efficiency_percent", *labels], *zip(*columns)] if columns else [["value"]]
    if kind == "teaching_scan":
        labels = [item.get("label", f"linked_{i}") for i, item in enumerate(data.get("linked_series", []))]
        columns = [data.get("x", []), data.get("primary", [])] + [item.get("y", []) for item in data.get("linked_series", [])]
        return [[data.get("x_label", "parameter"), data.get("primary_label", "primary"), *labels], *zip(*columns)] if columns else [["value"]]
    if kind == "mismatch_budget":
        return [
            ["physical_category", "global_mean_abs_shap", "current_signed_shap"],
            *zip(data.get("labels", []), data.get("global_values", []), data.get("local_values", [])),
        ]
    if kind == "beam_match":
        matrix = np.asarray(data.get("z", []))
        if matrix.ndim != 2:
            return [["value"]]
        x = list(data.get("x", range(matrix.shape[1])))
        y = list(data.get("y", range(matrix.shape[0])))
        rows = [["y/x", *x]]
        rows.extend([[y[index] if index < len(y) else index, *row] for index, row in enumerate(matrix.tolist())])
        return rows
    if kind == "line_multi":
        labels = [item.get("label", f"series_{i}") for i, item in enumerate(data.get("series", []))]
        columns = [data.get("x", [])] + [item.get("y", []) for item in data.get("series", [])]
        return [[data.get("x_label", "x"), *labels], *zip(*columns)]
    if kind in {"raytrace_section", "raytrace", "optical_scene_3d", "raytrace3d"}:
        rows = [["ray_index", "point_index", "x_mm", "y_mm", "z_mm", "role", "status_code"]]
        for ray in data.get("rays", []):
            if ray.get("points"):
                points = np.asarray(ray["points"], dtype=float)
            else:
                z = ray.get("z", [])
                x = ray.get("x", ray.get("t", []))
                y = ray.get("y", [0.0] * len(z))
                points = np.column_stack((x, y, z))
            for point_index, point in enumerate(points):
                rows.append([ray.get("ray_index", ""), point_index, *point.tolist(), ray.get("role", ""), ray.get("status_code", 0)])
        return rows
    if kind in {"heatmap", "heatmap_pair"}:
        key = "z" if kind == "heatmap" else "z1"
        matrix = np.asarray(data.get(key, []))
        return [[f"col_{i}" for i in range(matrix.shape[1])], *matrix.tolist()] if matrix.ndim == 2 else [["value"]]
    return [["key", "value"], *[[key, value] for key, value in data.items() if isinstance(value, (str, int, float, bool))]]

def _csv_cell(value) -> str:
    text = str(value)
    return '"' + text.replace('"', '""') + '"' if any(char in text for char in ',"\n') else text
