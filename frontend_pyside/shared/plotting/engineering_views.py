from __future__ import annotations



from collections.abc import Mapping, Sequence
from typing import Any
import math
import numpy as np

from frontend_pyside.shared.feature_labels import display_feature_name
from frontend_pyside.shared.display_names import parameter_label


def _finite_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


def _recursive_number(data: Mapping[str, Any] | None, keys: Sequence[str]) -> float | None:
    if not isinstance(data, Mapping):
        return None
    for key in keys:
        number = _finite_number(data.get(key))
        if number is not None:
            return number
    for value in data.values():
        if isinstance(value, Mapping):
            number = _recursive_number(value, keys)
            if number is not None:
                return number
    return None


def _as_2d(value: Any) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except Exception:
        return np.empty((0, 0), dtype=float)
    return array if array.ndim == 2 and array.size else np.empty((0, 0), dtype=float)


def _as_3d(value: Any) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except Exception:
        return np.empty((0, 0, 0), dtype=float)
    return array if array.ndim == 3 and array.size else np.empty((0, 0, 0), dtype=float)


def _wrap_phase(value: np.ndarray) -> np.ndarray:
    return np.angle(np.exp(1j * np.nan_to_num(value, nan=0.0)))


def build_phase_comparison(arrays: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    incident = _as_2d(arrays.get("coupling_field_phase_rad"))
    if not incident.size:
        real = _as_2d(arrays.get("coupling_field_real"))
        imag = _as_2d(arrays.get("coupling_field_imag"))
        if real.size and imag.shape == real.shape:
            incident = np.arctan2(imag, real)
    if not incident.size:
        return {"kind": "empty", "message": "当前结果没有接收面相位数据。"}

    target = _as_2d(arrays.get("coupling_mode_phase_rad"))
    target_is_reference = False
    if target.shape != incident.shape:
        
        
        
        target = np.zeros_like(incident)
        target_is_reference = True
    residual = _wrap_phase(incident - target)
    return {
        "kind": "phase_comparison",
        "title": "相位对比",
        "incident": np.nan_to_num(incident, nan=0.0).tolist(),
        "target": np.nan_to_num(target, nan=0.0).tolist(),
        "residual": residual.tolist(),
        "labels": ["入射端面相位", "目标模式相位", "相位差"],
        "unit": "rad",
        "target_is_reference": target_is_reference,
        "source": source,
        "description": "目标相位为参考平面" if target_is_reference else "入射场、目标模式与相位残差同图比较。",
    }


def build_energy_flow(metrics: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    final_eff = _recursive_number(metrics, (
        "system_efficiency", "total_coupling_efficiency", "coupling_total_efficiency",
        "coupling_efficiency_total", "coupling_efficiency",
    ))
    field_eff = _recursive_number(metrics, (
        "field_coupling_efficiency", "complex_field_coupling_efficiency",
        "coupling_field_efficiency", "mode_overlap_efficiency",
    ))
    transmission = _recursive_number(metrics, (
        "material_transmission", "optical_transmission", "transmission_efficiency",
        "total_transmission", "hybrid_transmission",
    ))
    edge_fraction = _recursive_number(metrics, (
        "propagation_edge_power_fraction", "edge_power_fraction", "aperture_loss_fraction",
    ))
    facet = _recursive_number(metrics, (
        "fiber_facet_transmission", "facet_transmission", "fiber_interface_efficiency",
    ))
    phase_eff = _recursive_number(metrics, (
        "phase_efficiency", "coupling_phase_efficiency", "wavefront_efficiency",
    ))

    def clamp_eff(value: float | None) -> float | None:
        if value is None:
            return None
        if value > 1.000001 and value <= 100.0:
            value /= 100.0
        return float(np.clip(value, 0.0, 1.0))

    final_eff = clamp_eff(final_eff)
    field_eff = clamp_eff(field_eff)
    transmission = clamp_eff(transmission)
    facet = clamp_eff(facet)
    phase_eff = clamp_eff(phase_eff)
    aperture = None if edge_fraction is None else float(np.clip(1.0 - edge_fraction, 0.0, 1.0))

    stage_candidates = [
        ("光学透过", transmission),
        ("口径保留", aperture),
        ("波前相位", phase_eff),
        ("模场重叠", field_eff),
        ("光纤端面", facet),
    ]
    stages = [(name, value) for name, value in stage_candidates if value is not None]
    if not stages and final_eff is None:
        return {"kind": "empty", "message": "当前结果没有可用于效率分解的功率或损耗指标。"}

    labels = ["输入功率"]
    cumulative = [100.0]
    losses = [0.0]
    current = 1.0
    for name, efficiency in stages:
        labels.append(name)
        previous = current
        current *= efficiency
        cumulative.append(100.0 * current)
        losses.append(100.0 * max(previous - current, 0.0))
    if final_eff is not None:
        labels.append("最终输出")
        previous = current
        current = final_eff
        cumulative.append(100.0 * current)
        losses.append(100.0 * max(previous - current, 0.0))
    return {
        "kind": "energy_flow",
        "title": "能量流向与效率分解",
        "labels": labels,
        "cumulative": cumulative,
        "losses": losses,
        "y_label": "相对输入功率 / %",
        "source": source,
    }


def _scaled_intensity_frame(base: np.ndarray, scale_x: float, scale_y: float) -> np.ndarray:
    rows, cols = base.shape
    yy, xx = np.indices(base.shape, dtype=float)
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    sx = max(float(scale_x), 1.0e-4)
    sy = max(float(scale_y), 1.0e-4)
    src_x = np.clip(np.round(cx + (xx - cx) / sx).astype(int), 0, cols - 1)
    src_y = np.clip(np.round(cy + (yy - cy) / sy).astype(int), 0, rows - 1)
    return base[src_y, src_x] / max(sx * sy, 1.0e-12)


def _derived_multi_plane_frames(model: Mapping[str, Any], start_mm: float, stop_mm: float, count: int) -> list[dict[str, Any]]:
    base = _as_2d(model.get("base_intensity"))
    if not base.size:
        return []
    count = max(3, min(15, int(count)))
    start_mm, stop_mm = sorted((float(start_mm), float(stop_mm)))
    if math.isclose(start_mm, stop_mm, rel_tol=0.0, abs_tol=1.0e-12):
        stop_mm = start_mm + 1.0e-6
    wx0 = max(float(model.get("waist_x_um", 1.0)), 1.0e-9)
    wy0 = max(float(model.get("waist_y_um", 1.0)), 1.0e-9)
    zx0 = float(model.get("waist_x_z_mm", 0.0))
    zy0 = float(model.get("waist_y_z_mm", 0.0))
    zrx = max(float(model.get("rayleigh_x_mm", 1.0)), 1.0e-9)
    zry = max(float(model.get("rayleigh_y_mm", 1.0)), 1.0e-9)

    def radius(w0: float, z: float, z0: float, zr: float) -> float:
        return w0 * math.sqrt(1.0 + ((z - z0) / zr) ** 2)

    ref_x = max(radius(wx0, 0.0, zx0, zrx), 1.0e-9)
    ref_y = max(radius(wy0, 0.0, zy0, zry), 1.0e-9)
    planes: list[dict[str, Any]] = []
    for z_value in np.linspace(start_mm, stop_mm, count):
        sx = radius(wx0, float(z_value), zx0, zrx) / ref_x
        sy = radius(wy0, float(z_value), zy0, zry) / ref_y
        frame = np.nan_to_num(_scaled_intensity_frame(base, sx, sy), nan=0.0)
        maximum = float(np.max(frame)) if frame.size else 0.0
        if maximum > 0:
            frame = frame / maximum
        planes.append({"z": float(z_value), "intensity": frame.tolist()})
    return planes


def rebuild_multi_plane_evolution_range(
    data: Mapping[str, Any], start_mm: float, stop_mm: float, plane_count: int = 7,
) -> dict[str, Any]:
    """Return a display copy over a requested axial range.

    Derived Gaussian propagation can be regenerated continuously.  For formal
    multi-plane stacks we select the nearest available physical planes instead of
    inventing uncomputed fields.
    """
    payload = dict(data or {})
    start_mm, stop_mm = sorted((float(start_mm), float(stop_mm)))
    plane_count = max(3, min(15, int(plane_count)))
    model = payload.get("_derived_model")
    if isinstance(model, Mapping):
        payload["planes"] = _derived_multi_plane_frames(model, start_mm, stop_mm, plane_count)
        payload["range_mm"] = [start_mm, stop_mm]
        return payload

    planes = [dict(item) for item in list(payload.get("planes", []) or []) if isinstance(item, Mapping)]
    if not planes:
        return payload
    positions = np.asarray([float(item.get("z", 0.0)) for item in planes], dtype=float)
    targets = np.linspace(start_mm, stop_mm, min(plane_count, max(1, len(planes))))
    chosen: list[int] = []
    for target in targets:
        index = int(np.argmin(np.abs(positions - float(target))))
        if index not in chosen:
            chosen.append(index)
    if not chosen:
        chosen = [int(np.argmin(np.abs(positions - 0.5 * (start_mm + stop_mm))))]
    payload["planes"] = [planes[index] for index in chosen]
    payload["range_mm"] = [start_mm, stop_mm]
    payload["range_note"] = "正式传播结果仅显示请求范围内最接近的已计算平面。"
    return payload


def build_multi_plane_evolution(
    arrays: Mapping[str, Any],
    beam_match: Mapping[str, Any] | None,
    waist: Mapping[str, Any] | None,
    *,
    source: str,
) -> dict[str, Any]:
    stack = np.empty((0, 0, 0), dtype=float)
    z_positions: list[float] = []
    for key in (
        "coupling_intensity_by_z", "field_intensity_by_z", "propagation_intensity_stack",
        "multi_plane_intensity",
    ):
        candidate = _as_3d(arrays.get(key))
        if candidate.size:
            stack = candidate
            break
    for key in ("coupling_z_positions_mm", "propagation_z_mm", "multi_plane_z_mm"):
        values = arrays.get(key)
        if values is not None:
            try:
                z_positions = [float(value) for value in values]
            except Exception:
                z_positions = []
            if z_positions:
                break

    derived_model: dict[str, Any] | None = None
    description = "正式多平面传播结果"
    if not stack.size and isinstance(beam_match, Mapping):
        base = _as_2d(beam_match.get("z"))
        if base.size:
            metrics = dict(waist.get("metrics", {}) or {}) if isinstance(waist, Mapping) else {}
            zrx = max(float(metrics.get("rayleigh_x_mm", 0.25) or 0.25), 1.0e-6)
            zry = max(float(metrics.get("rayleigh_y_mm", 0.25) or 0.25), 1.0e-6)
            zx0 = float(metrics.get("waist_x_z_mm", 0.0) or 0.0)
            zy0 = float(metrics.get("waist_y_z_mm", 0.0) or 0.0)
            # Focused-coupling view: do not let an ill-conditioned Gaussian fit
            # explode into tens of metres.  The user can widen this explicitly.
            raw_half_span = max(0.5, 2.0 * max(zrx, zry), 1.5 * max(abs(zx0), abs(zy0)))
            auto_half_span = min(raw_half_span, 12.0)
            derived_model = {
                "base_intensity": np.nan_to_num(base, nan=0.0).tolist(),
                "waist_x_um": float(metrics.get("waist_x_um", 1.0) or 1.0),
                "waist_y_um": float(metrics.get("waist_y_um", 1.0) or 1.0),
                "waist_x_z_mm": zx0,
                "waist_y_z_mm": zy0,
                "rayleigh_x_mm": zrx,
                "rayleigh_y_mm": zry,
            }
            planes = _derived_multi_plane_frames(derived_model, -auto_half_span, auto_half_span, 7)
            return {
                "kind": "multi_plane_evolution",
                "title": "多平面光斑演化",
                "planes": planes,
                "derived": True,
                "source": source,
                "range_mm": [-auto_half_span, auto_half_span],
                "auto_range_capped": bool(raw_half_span > auto_half_span + 1.0e-9),
                "_derived_model": derived_model,
                "description": (
                    "由端面复场与高斯传播拟合外推；自动范围聚焦于耦合焦区，异常大的拟合瑞利长度不会直接扩展到几十米。"
                ),
            }
    if not stack.size:
        return {"kind": "empty", "message": "当前结果没有多平面光斑数据。"}

    indices = np.unique(np.linspace(0, stack.shape[0] - 1, min(9, stack.shape[0]), dtype=int))
    planes = []
    for index in indices:
        frame = np.nan_to_num(stack[int(index)], nan=0.0)
        maximum = float(np.max(frame)) if frame.size else 0.0
        if maximum > 0:
            frame = frame / maximum
        z_value = z_positions[int(index)] if int(index) < len(z_positions) else float(index)
        planes.append({"z": float(z_value), "intensity": frame.tolist()})
    range_mm = [min((p["z"] for p in planes), default=0.0), max((p["z"] for p in planes), default=0.0)]
    return {
        "kind": "multi_plane_evolution",
        "title": "多平面光斑演化",
        "planes": planes,
        "derived": False,
        "source": source,
        "range_mm": range_mm,
        "description": description,
    }

def _baseline_metrics(result: Mapping[str, Any], project_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Return the metrics frozen when the task was submitted.

    Optimisation results must not re-read the *current* project after a candidate
    has been applied; otherwise an old task can silently turn into a meaningless
    ``92.7 -> 92.7`` comparison.  The formal optimiser always records its first
    evaluation as the current-system baseline, so prefer that immutable record.
    """
    metadata = dict(result.get("metadata", {}) or {})
    explicit = metadata.get("baseline_metrics")
    if isinstance(explicit, Mapping) and explicit:
        return dict(explicit)
    history = [item for item in list(result.get("history", []) or []) if isinstance(item, Mapping)]
    if history:
        metrics = history[0].get("metrics")
        if isinstance(metrics, Mapping) and metrics:
            return dict(metrics)
    return dict(project_metrics or {})


def build_before_after_comparison(result: Mapping[str, Any], project_metrics: Mapping[str, Any]) -> dict[str, Any]:
    best_metrics = dict(result.get("best_metrics", {}) or {})
    baseline_metrics = _baseline_metrics(result, project_metrics)
    before_eff = _finite_number(baseline_metrics.get("coupling_efficiency"))
    after_eff = _finite_number(best_metrics.get("coupling_efficiency"))
    before_system = _finite_number(baseline_metrics.get("system_efficiency"))
    after_system = _finite_number(best_metrics.get("system_efficiency"))
    if before_eff is None and after_eff is None:
        return {"kind": "empty", "message": "当前优化结果没有优化前后效率数据。"}

    def percent(value: float | None) -> float | None:
        if value is None:
            return None
        return 100.0 * value if abs(value) <= 1.000001 else value

    variables = dict(result.get("best_variables", {}) or {})
    rows = []
    for name, value in list(variables.items())[:8]:
        rows.append({"name": parameter_label(name), "before": None, "after": value})
    return {
        "kind": "before_after",
        "title": "优化前后对比",
        "before": {
            "label": "当前系统",
            "coupling_efficiency": percent(before_eff),
            "system_efficiency": percent(before_system),
        },
        "after": {
            "label": "最佳候选",
            "coupling_efficiency": percent(after_eff),
            "system_efficiency": percent(after_system),
        },
        "parameters": rows,
        "source": "正式优化",
    }


def build_convergence_view(result: Mapping[str, Any], *, metric_label: str, efficiency: bool) -> dict[str, Any]:
    history = [item for item in list(result.get("history", []) or []) if isinstance(item, Mapping)]
    if not history:
        return {"kind": "empty", "message": "没有优化过程数据。"}
    x: list[float] = []
    current: list[float] = []
    best: list[float] = []
    maximize = bool(dict(result.get("metadata", {}) or {}).get("higher_is_better", True))
    for index, item in enumerate(history):
        metrics = dict(item.get("metrics", {}) or {})
        merit = _finite_number(metrics.get("coupling_efficiency")) if efficiency else None
        if merit is None:
            merit = _finite_number(item.get("merit"))
        if merit is None:
            continue
        if efficiency and abs(merit) <= 1.000001:
            merit *= 100.0
        x.append(float(item.get("iteration", index + 1)))
        current.append(merit)
        best.append(merit if not best else (max(best[-1], merit) if maximize else min(best[-1], merit)))
    if not x:
        return {"kind": "empty", "message": "没有有效优化过程数据。"}
    return {
        "kind": "convergence_curve",
        "title": "优化收敛",
        "x": x,
        "current": current,
        "best": best,
        "x_label": "正式仿真次数",
        "y_label": metric_label + (" / %" if efficiency else ""),
        "plot_bottom_margin": 0.27,
        "source": "正式优化",
    }


def build_candidate_comparison(result: Mapping[str, Any], *, efficiency: bool) -> dict[str, Any]:
    rows = [item for item in list(result.get("candidates", []) or result.get("candidate_results", []) or []) if isinstance(item, Mapping)]
    if not rows:
        
        
        
        history_rows = [item for item in list(result.get("history", []) or []) if isinstance(item, Mapping)]
        for index, item in enumerate(history_rows):
            metrics = dict(item.get("metrics", {}) or {})
            formal = metrics.get("coupling_efficiency") if efficiency else item.get("merit")
            rows.append({
                "label": f"候选{index + 1}",
                "formal_efficiency": formal,
                "predicted_efficiency": item.get("predicted_value"),
                "feasible": metrics.get("collimation_feasible", 1.0) >= 0.5,
            })
    if not rows:
        return {"kind": "empty", "message": "没有候选结果数据。"}
    normalized = []
    for index, item in enumerate(rows):
        formal = _finite_number(item.get("formal_efficiency", item.get("coupling_efficiency", item.get("formal_value"))))
        predicted = _finite_number(item.get("predicted_efficiency", item.get("predicted_value")))
        if formal is None and predicted is None:
            continue
        if efficiency:
            if formal is not None and abs(formal) <= 1.000001:
                formal *= 100.0
            if predicted is not None and abs(predicted) <= 1.000001:
                predicted *= 100.0
        raw_label = str(item.get("label", item.get("name", "")) or "").strip()
        # Legacy/demo result payloads sometimes used lettered candidate labels.
        # The platform has only one current system; optimisation produces candidates.
        if not raw_label or raw_label.startswith("方案"):
            raw_label = f"候选{index + 1}"
        normalized.append({
            "label": raw_label,
            "formal": formal,
            "predicted": predicted,
            "feasible": bool(item.get("feasible", item.get("constraint_passed", True))),
            "verified": formal is not None,
        })
    if not normalized:
        return {"kind": "empty", "message": "候选结果没有有效指标。"}
    normalized.sort(key=lambda item: item["formal"] if item["formal"] is not None else (item["predicted"] or -float("inf")), reverse=True)
    return {
        "kind": "candidate_compare",
        "title": "多候选结果对比",
        "candidates": normalized[:10],
        "y_label": "耦合效率 / %" if efficiency else "目标值",
        "source": "正式优化",
    }


def _compact_correlation_label(raw_key: str, display: str) -> str:
    key = str(raw_key or "")
    if key in {"receiver.axial_offset_z_mm", "receiver_axial_offset_z_mm", "axial_offset_z_mm"}:
        return "Z位置"
    if key in {"receiver.offset_x_mm", "receiver_offset_x_mm", "offset_x_mm"}:
        return "X偏移"
    if key in {"receiver.offset_y_mm", "receiver_offset_y_mm", "offset_y_mm"}:
        return "Y偏移"
    if key in {"receiver.tilt_x_deg", "tilt_x_deg"}:
        return "X倾角"
    if key in {"receiver.tilt_y_deg", "tilt_y_deg"}:
        return "Y倾角"
    if key == "目标值":
        return "目标值"
    import re
    match = re.match(r"surfaces\[(\d+)\]\.(distance_to_next_mm|radius_mm|semi_aperture_mm)", key)
    if match:
        surface = int(match.group(1)) + 1
        suffix = {
            "distance_to_next_mm": "厚度",
            "radius_mm": "曲率",
            "semi_aperture_mm": "口径",
        }[match.group(2)]
        return f"S{surface}{suffix}"
    text = str(display or key).replace("（mm）", "").replace(" (mm)", "").strip()
    return text if len(text) <= 8 else text[:7] + "…"


def build_correlation_view(result: Mapping[str, Any]) -> dict[str, Any]:
    history = [item for item in list(result.get("history", []) or []) if isinstance(item, Mapping)]
    records: list[dict[str, float]] = []
    variable_names = list(dict(result.get("best_variables", {}) or {}))
    for item in history:
        variables = item.get("variables", item.get("params", item.get("parameters", {})))
        if isinstance(variables, Mapping):
            row = {str(key): float(value) for key, value in variables.items() if _finite_number(value) is not None}
        elif isinstance(variables, Sequence) and not isinstance(variables, (str, bytes)):
            row = {
                str(variable_names[index] if index < len(variable_names) else f"参数{index + 1}"): float(value)
                for index, value in enumerate(variables)
                if _finite_number(value) is not None
            }
        else:
            continue
        merit = _finite_number(item.get("merit"))
        if merit is not None:
            row["目标值"] = merit
        if row:
            records.append(row)
    keys = sorted({key for row in records for key in row})
    if len(records) < 3 or len(keys) < 2:
        return {"kind": "empty", "message": "优化历史中的参数样本不足，无法计算相关性。"}
    matrix_rows = []
    valid_keys = []
    for key in keys:
        values = [row.get(key, float("nan")) for row in records]
        if np.sum(np.isfinite(values)) >= 3:
            valid_keys.append(key)
            matrix_rows.append(values)
    array = np.asarray(matrix_rows, dtype=float)
    
    
    for row_index in range(array.shape[0]):
        finite = np.isfinite(array[row_index])
        mean = float(np.mean(array[row_index, finite])) if np.any(finite) else 0.0
        array[row_index, ~finite] = mean
    correlation = np.corrcoef(array)
    labels = [display_feature_name(key, fallback_index=index + 1) for index, key in enumerate(valid_keys)]
    return {
        "kind": "correlation_heatmap",
        "title": "参数相关性",
        "labels": labels,
        "x_labels": [_compact_correlation_label(key, label) for key, label in zip(valid_keys, labels)],
        "raw_labels": valid_keys,
        "matrix": np.nan_to_num(correlation, nan=0.0).tolist(),
        "source": "优化历史",
    }


def build_adjustment_trajectory(records: Sequence[Mapping[str, Any]], *, source: str = "教学记录") -> dict[str, Any]:
    if len(records) < 2:
        return {"kind": "empty", "message": "至少记录两个调节状态后才能显示调节轨迹。"}
    metric_candidates = ("total_efficiency", "field_efficiency", "coupling_efficiency", "system_efficiency")
    parameter_candidates = ("offset_x_um", "offset_y_um", "axial_offset_um", "tilt_x_mrad", "tilt_y_mrad")
    steps = list(range(1, len(records) + 1))
    efficiency: list[float] = []
    series: dict[str, list[float]] = {name: [] for name in parameter_candidates}
    for record in records:
        metrics = dict(record.get("metrics", {}) or {})
        inputs = dict(record.get("inputs", {}) or {})
        value = next((_finite_number(metrics.get(name)) for name in metric_candidates if _finite_number(metrics.get(name)) is not None), None)
        if value is None:
            value = 0.0
        if abs(value) <= 1.000001:
            value *= 100.0
        efficiency.append(value)
        for name in parameter_candidates:
            series[name].append(float(inputs.get(name, 0.0) or 0.0))
    active = [{"label": display_feature_name(name, fallback_index=index + 1), "y": values} for index, (name, values) in enumerate(series.items()) if any(abs(value) > 1e-12 for value in values)]
    return {
        "kind": "adjustment_trajectory",
        "title": "调节过程轨迹",
        "x": steps,
        "efficiency": efficiency,
        "series": active,
        "x_label": "调节步数",
        "y_label": "耦合效率 / %",
        "source": source,
    }
