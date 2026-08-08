from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Mapping
import numpy as np

from .calculations import calculate
from .contracts import get_module


def evaluate_prediction(module: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    pred = get_module(module)["prediction"]
    selected = str(payload.get("answer", ""))
    correct = selected == pred["answer"]
    return {"correct": correct, "selected": selected, "answer": pred["answer"], "explanation": pred["explanation"]}


def run_parameter_scan(module: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    contract = get_module(module)
    parameter = str(payload.get("parameter", next(iter(contract["parameters"]))))
    metric = str(payload.get("metric", contract["scan_metrics"][0]))
    spec = contract["parameters"].get(parameter)
    if spec is None:
        raise ValueError(f"unknown parameter: {parameter}")
    start = float(payload.get("start", spec["minimum"]))
    stop = float(payload.get("stop", spec["maximum"]))
    points = int(np.clip(int(payload.get("points", 41)), 5, 201))
    base = dict(payload.get("inputs", {}))
    x = np.linspace(start, stop, points)
    series: dict[str, list[float]] = {name: [] for name in contract.get("metrics", {})}
    for value in x:
        current = dict(base); current[parameter] = float(value)
        result = calculate(module, current)
        for name in series:
            raw = result.get("metrics", {}).get(name)
            series[name].append(float(raw) if isinstance(raw, (int, float)) else float("nan"))
    y = series.get(metric, [])
    idx_max = int(np.nanargmax(y)); idx_min = int(np.nanargmin(y))
    return {"module": module, "parameter": parameter, "metric": metric,
            "x": x.tolist(), "y": y, "series": series,
            "maximum": {"x": float(x[idx_max]), "y": float(y[idx_max])},
            "minimum": {"x": float(x[idx_min]), "y": float(y[idx_min])}}


def run_numerical_diagnostic(module: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    result = calculate(module, payload.get("inputs", {}))
    settings = payload.get("settings", {})
    n = int(np.clip(int(settings.get("grid_points", 65)), 17, 513))
    if n % 2 == 0: n += 1
    window_factor = float(np.clip(float(settings.get("window_factor", 3.0)), 1.2, 8.0))
    characteristic = 1.0
    if module == "gaussian": characteristic = result["metrics"]["observation_radius_um"]
    elif module == "fiber": characteristic = result["inputs"]["core_radius_um"]
    elif module == "coupling": characteristic = min(result["inputs"]["beam_radius_um"], result["inputs"]["mfd_um"] / 2)
    elif module == "psf": characteristic = result["metrics"]["airy_radius_um"]
    dx = 2 * window_factor * characteristic / max(n-1, 1)
    coverage = characteristic / max(dx, 1e-15)
    edge = float(np.exp(-2 * window_factor**2))
    closure = min(1.0, edge * 2 + 1/max(coverage, 1e-9)**3)
    passed = coverage >= 4 and edge <= 0.002 and closure <= 0.005
    warnings = []
    if coverage < 4: warnings.append("特征半径像素覆盖不足，曲线或热图可能过粗。")
    if edge > 0.002: warnings.append("窗口边缘仍有较多能量，存在截断风险。")
    if closure > 0.005: warnings.append("离散采样与解析参考的闭合误差较大。")
    return {"sampling_pass": passed, "aliasing_risk": "low" if passed else ("high" if coverage < 2 else "moderate"),
            "grid_points": n, "window_factor": window_factor, "sample_pitch": dx,
            "pixels_per_characteristic_radius": coverage, "edge_power_fraction": edge,
            "energy_closure_error": closure, "warnings": warnings,
            "note": "该诊断用于教学演示采样、窗口与误差的关系，不替代正式数值收敛测试。"}


def score_experiment(module: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    prediction = bool(payload.get("prediction_correct", False))
    task = bool(payload.get("task_passed", False))
    records = list(payload.get("records", []))
    conclusion = str(payload.get("conclusion", "")).strip()
    diagnostic = payload.get("diagnostic", {})
    scores = {
        "预测": 15 if prediction else 0,
        "任务": 25 if task else 10,
        "数据记录": min(25, len(records) * 5),
        "物理解释": min(25, 5 + len(conclusion) // 8) if conclusion else 0,
        "数值可信度": 10 if diagnostic.get("sampling_pass") else (5 if diagnostic else 0),
    }
    return {"parts": scores, "total": int(sum(scores.values())), "maximum": 100}


def build_report_bundle(module: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    result = calculate(module, payload.get("inputs", {}))
    contract = get_module(module)
    score = score_experiment(module, payload)
    records = list(payload.get("records", []))
    lines = [f"# {contract['title']}实验报告", "", "> 计算模型：教学近似", "",
             "## 实验目标", *[f"- {x}" for x in contract["objectives"]], "",
             "## 公式与适用条件", f"- 公式：{contract['formula']}",
             *[f"- {x}" for x in contract["assumptions"]], "", "## 当前结果"]
    for key, value in result["metrics"].items(): lines.append(f"- {key}: {value:.6g}")
    lines += ["", "## 学生结论", str(payload.get("conclusion", "未填写")), "", f"## 自动评分：{score['total']}/100"]
    output = io.StringIO(); writer = csv.writer(output); writer.writerow(["序号", "时间", "参数", "指标", "备注"])
    for i, rec in enumerate(records, 1): writer.writerow([i, rec.get("time", ""), json.dumps(rec.get("inputs", {}), ensure_ascii=False), json.dumps(rec.get("metrics", {}), ensure_ascii=False), rec.get("note", "")])
    return {"markdown": "\n".join(lines), "csv": output.getvalue(),
            "json": json.dumps({"module": module, "created_at": datetime.now().isoformat(timespec="seconds"), "payload": payload, "result": result, "score": score}, ensure_ascii=False, indent=2)}
