from __future__ import annotations



from collections.abc import Mapping, Sequence
from typing import Any
import math
import numpy as np

from frontend_pyside.shared.feature_labels import display_feature_name


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

    derived = False
    if not stack.size and isinstance(beam_match, Mapping):
        base = _as_2d(beam_match.get("z"))
        if base.size:
            
            
            derived = True
            positions = np.linspace(-1.0, 1.0, 7)
            frames: list[np.ndarray] = []
            rows, cols = base.shape
            yy, xx = np.indices(base.shape, dtype=float)
            cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
            for value in positions:
                scale = 0.72 + 0.55 * abs(value)
                src_x = np.clip(np.round(cx + (xx - cx) / scale).astype(int), 0, cols - 1)
                src_y = np.clip(np.round(cy + (yy - cy) / scale).astype(int), 0, rows - 1)
                frame = base[src_y, src_x] / max(scale * scale, 1e-12)
                frames.append(frame)
            stack = np.asarray(frames)
            span = 1.0
            if isinstance(waist, Mapping):
                x_values = list(waist.get("x", []) or [])
                if x_values:
                    span = max(abs(float(min(x_values))), abs(float(max(x_values))), 1.0)
            z_positions = np.linspace(-span, span, len(frames)).tolist()
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
    return {
        "kind": "multi_plane_evolution",
        "title": "多平面光斑演化",
        "planes": planes,
        "derived": derived,
        "source": source,
        "description": "由端面复场与高斯传播拟合外推" if derived else "正式多平面传播结果",
    }


def build_before_after_comparison(result: Mapping[str, Any], project_metrics: Mapping[str, Any]) -> dict[str, Any]:
    best_metrics = dict(result.get("best_metrics", {}) or {})
    before_eff = _finite_number(project_metrics.get("coupling_efficiency"))
    after_eff = _finite_number(best_metrics.get("coupling_efficiency"))
    before_system = _finite_number(project_metrics.get("system_efficiency"))
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
        rows.append({"name": str(name), "before": None, "after": value})
    return {
        "kind": "before_after",
        "title": "优化前后对比",
        "before": {
            "label": "优化前",
            "coupling_efficiency": percent(before_eff),
            "system_efficiency": percent(before_system),
        },
        "after": {
            "label": "优化后",
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
                "label": f"方案{index + 1}",
                "formal_efficiency": formal,
                "predicted_efficiency": item.get("predicted_value"),
                "feasible": metrics.get("collimation_feasible", 1.0) >= 0.5,
            })
    if not rows:
        return {"kind": "empty", "message": "没有候选方案数据。"}
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
        normalized.append({
            "label": str(item.get("label", item.get("name", f"方案{index + 1}"))),
            "formal": formal,
            "predicted": predicted,
            "feasible": bool(item.get("feasible", item.get("constraint_passed", True))),
            "verified": formal is not None,
        })
    if not normalized:
        return {"kind": "empty", "message": "候选方案没有有效指标。"}
    normalized.sort(key=lambda item: item["formal"] if item["formal"] is not None else (item["predicted"] or -float("inf")), reverse=True)
    return {
        "kind": "candidate_compare",
        "title": "多候选方案对比",
        "candidates": normalized[:10],
        "y_label": "耦合效率 / %" if efficiency else "目标值",
        "source": "正式优化",
    }


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
    return {
        "kind": "correlation_heatmap",
        "title": "参数相关性",
        "labels": [display_feature_name(key, fallback_index=index + 1) for index, key in enumerate(valid_keys)],
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
