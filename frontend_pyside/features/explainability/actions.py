
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReportContentOptions:
    model_dataset: bool = True
    global_shap: bool = True
    local_samples: bool = True
    physical_formulas: bool = True
    consistency_anomalies: bool = True
    limitations: bool = True

    def selected_labels(self) -> tuple[str, ...]:
        pairs = (
            (self.model_dataset, "模型与数据集"),
            (self.global_shap, "全局 SHAP"),
            (self.local_samples, "局部样本"),
            (self.physical_formulas, "物理公式"),
            (self.consistency_anomalies, "一致性与异常"),
            (self.limitations, "适用边界"),
        )
        return tuple(label for enabled, label in pairs if enabled)





from shared_presentation.explainability import explain_shap_failure
from shared_presentation.explanation_formulas import (
    FORMULA_CATALOG,
    feature_display_name,
    formula_binding_for_feature,
    formula_chain_for_feature,
    formula_latex,
    formula_location_for_feature,
    physical_mechanism_for_feature,
    suggested_action_for_feature
)


PHYSICAL_MISMATCH_ORDER: tuple[str, ...] = (
    "中心位置失配",
    "尺寸失配",
    "焦面与曲率失配",
    "椭圆与像散失配",
    "角度与波前失配",
    "光束结构与像差",
)


def physical_mismatch_category(feature_name: str) -> str:

    text = str(feature_name).lower().replace(" ", "")
    if any(token in text for token in (
        "offset_x", "offset_y", "lateral_mismatch", "decenter", "centroid",
        "中心偏移", "横向偏移", "x偏移", "y偏移",
    )):
        return "中心位置失配"
    if any(token in text for token in (
        "ellipt", "astig", "cylind", "waist_separation", "qx", "qy",
        "椭圆", "像散", "柱面镜",
    )):
        return "椭圆与像散失配"
    if any(token in text for token in (
        "tilt", "angle", "pitch", "yaw", "angular_mismatch", "wavefront",
        "opd", "zernike", "strehl", "倾角", "角度", "波前",
    )):
        return "角度与波前失配"
    if any(token in text for token in (
        "size_ratio", "mfd", "mode_field", "waist_x", "waist_y",
        "beam_radius", "diameter", "束腰", "模场", "尺寸比",
    )):
        return "尺寸失配"
    if any(token in text for token in (
        "axial", "defocus", "offset_z", "distance", "curvature_mismatch",
        "wavefront_curvature", "radius_mm", ".radius", "curvature",
        "thickness", "air_gap", "spacing", "焦面", "离焦", "曲率",
        "空气间隔", "厚度",
    )):
        return "焦面与曲率失配"
    if any(token in text for token in (
        "psf", "spot", "mtf", "conic", "material", "glass", "aperture",
        "旁瓣", "像差", "非高斯",
    )):
        return "光束结构与像差"
    return "光束结构与像差"


def physical_category_totals(
    records: list[dict[str, Any]],
    values_by_feature: dict[str, float] | None = None,
    *,
    absolute: bool = True,
) -> list[dict[str, Any]]:

    totals = {name: 0.0 for name in PHYSICAL_MISMATCH_ORDER}
    members: dict[str, list[str]] = {name: [] for name in PHYSICAL_MISMATCH_ORDER}
    for record in records:
        feature = str(record.get("feature", record.get("name", "")))
        category = physical_mismatch_category(feature)
        if values_by_feature is not None and feature in values_by_feature:
            value = float(values_by_feature[feature])
        else:
            value = float(record.get("mean_abs_shap" if absolute else "mean_shap", 0.0) or 0.0)
        totals[category] += abs(value) if absolute else value
        members[category].append(feature_display_name(feature))
    rows = [
        {"category": category, "value": totals[category], "features": members[category]}
        for category in PHYSICAL_MISMATCH_ORDER
        if members[category] or totals[category] != 0.0
    ]
    rows.sort(key=lambda item: abs(float(item["value"])), reverse=True)
    return rows


def diagnosis_confidence(shap_data: dict[str, Any] | None) -> tuple[str, str]:

    data = shap_data or {}
    targets = list(data.get("targets", []) or [])
    target = targets[0] if targets and isinstance(targets[0], dict) else {}
    sample_count = int(data.get("sample_count", target.get("sample_count", 0)) or 0)
    in_domain = data.get("within_training_domain", data.get("in_training_domain"))
    if in_domain is None:
        in_domain = target.get("within_training_domain", target.get("in_training_domain"))
    rows = list(target.get("sample_shap_values", []) or [])
    formal_reviewed = any(
        isinstance(row, dict)
        and isinstance(row.get("formal_value", row.get("actual", row.get("target_value"))), (int, float))
        for row in rows
    )
    if in_domain is False:
        return "较低", "当前系统超出训练范围；失配方向仅供参考，建议运行正式扫描。"
    if sample_count < 10:
        return "暂不可判断", "有效解释样本不足10个，暂不评价诊断稳定性。"
    if in_domain is True and formal_reviewed:
        return "较高", "当前系统位于训练范围内，并有正式仿真值可用于复核。"
    if in_domain is True or sample_count >= 20:
        return "中等", "模型可用于判断失配方向，最终效率仍应以正式仿真为准。"
    return "较低", "训练域或完整仿真信息不足，建议补充正式仿真。"














def anomaly_rows(shap_data: dict[str, Any] | None, *, limit: int = 50) -> list[list[Any]]:
    if not shap_data:
        return []
    targets = list(shap_data.get("targets", []) or [])
    if not targets:
        return []
    target = targets[0]
    rows = []
    for sample in list(target.get("sample_shap_values", []) or []):
        values = sample.get("shap_values") or sample.get("values") or {}
        ranked = sorted(
            ((str(name), float(value)) for name, value in values.items()),
            key=lambda pair: abs(pair[1]),
            reverse=True,
        )
        total = sum(abs(value) for _, value in ranked)
        dominant = ranked[0] if ranked else ("—", 0.0)
        rows.append([
            str(sample.get("sample_id", "—")),
            total,
            dominant[0],
            dominant[1],
            str(target.get("target_name", shap_data.get("target_name", "—"))),
        ])
    rows.sort(key=lambda row: float(row[1]), reverse=True)
    return rows[: max(1, int(limit))]


def shap_rows(shap_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not shap_data:
        return []
    rows: list[dict[str, Any]] = []
    for target in list(shap_data.get("targets", []) or []):
        target_name = str(target.get("target_name", ""))
        for item in list(target.get("top_features", []) or []):
            rows.append({
                "target_name": target_name,
                "feature": str(item.get("name", item.get("feature", ""))),
                "mean_shap": float(item.get("mean_shap", 0.0)),
                "mean_abs_shap": float(item.get("mean_abs_shap", 0.0)),
                "direction": str(item.get("direction", "neutral")),
                "sample_value": item.get("sample_value", ""),
            })
    return rows


def build_markdown_report(
    shap_data: dict[str, Any] | None,
    narrative: str = "",
    options: ReportContentOptions | None = None,
) -> str:
    data = shap_data or {}
    options = options or ReportContentOptions()
    lines = ["# 模型解释报告", ""]

    if options.model_dataset:
        lines.extend([
            "## 模型与数据集",
            "",
            f"- 模型：`{data.get('model_id', '—')}`",
            f"- 数据集：`{data.get('dataset_id', '—')}`",
            f"- 解释器：{data.get('explainer', '—')}",
            f"- 真实样本数：{data.get('sample_count', 0)}",
            f"- 背景样本数：{data.get('background_sample_count', 0)}",
            f"- 使用合成样本：{'是' if data.get('synthetic_samples') else '否'}",
            "",
        ])

    targets = list(data.get("targets", []) or [])

    
    
    source_records = list(data.get("feature_contributions", []) or data.get("top_features", []) or data.get("global_importance", []) or [])
    if not source_records and targets and isinstance(targets[0], dict):
        source_records = list(targets[0].get("top_features", []) or targets[0].get("global_importance", []) or [])
    normalized_records = []
    for item in source_records:
        if not isinstance(item, dict):
            continue
        feature = str(item.get("feature", item.get("name", "")))
        normalized_records.append({
            "feature": feature,
            "mean_abs_shap": float(item.get("mean_abs_shap", abs(float(item.get("mean_shap", 0.0) or 0.0))) or 0.0),
            "mean_shap": float(item.get("mean_shap", item.get("shap_value", 0.0)) or 0.0),
        })
    category_rows = physical_category_totals(normalized_records)
    confidence, confidence_note = diagnosis_confidence(data)
    lines.extend([
        "## 模场失配诊断",
        "",
        f"- 诊断可信度：**{confidence}**",
        f"- 判断说明：{confidence_note}",
        "",
    ])
    if category_rows:
        maximum = max(float(row["value"]) for row in category_rows) or 1.0
        lines.extend(["| 物理失配类别 | 相对重要程度 | 关联原始特征 |", "|---|---:|---|"])
        for row in category_rows:
            lines.append(
                f"| {row['category']} | {100.0 * float(row['value']) / maximum:.1f}% | "
                f"{'、'.join(row['features'][:6]) or '—'} |"
            )
        lines.append("")

    if options.global_shap:
        for target in targets:
            target_name = str(target.get("target_name", "输出"))
            lines.extend([
                f"## 全局 SHAP · {target_name}",
                "",
                f"Expected value：{target.get('base_value', '—')}",
                "",
                "| 特征 | 平均 SHAP | 平均绝对 SHAP | 方向 |",
                "|---|---:|---:|---|",
            ])
            for item in list(target.get("top_features", []) or []):
                lines.append(
                    f"| {item.get('name', '—')} | {float(item.get('mean_shap', 0.0)):.6g} | "
                    f"{float(item.get('mean_abs_shap', 0.0)):.6g} | {item.get('direction', 'neutral')} |"
                )
            lines.append("")

    if options.local_samples:
        lines.extend(["## 局部样本", ""])
        local_rows = anomaly_rows(data, limit=10)
        if local_rows:
            lines.extend([
                "| 样本 | 总 |SHAP| | 主导特征 | 主导贡献 | 输出 |",
                "|---|---:|---|---:|---|",
            ])
            for sample_id, total, feature, contribution, output in local_rows:
                lines.append(
                    f"| {sample_id} | {float(total):.6g} | {feature} | "
                    f"{float(contribution):.6g} | {output} |"
                )
        else:
            lines.append("当前解释结果未提供样本级 SHAP 数据。")
        lines.append("")

    if options.physical_formulas:
        lines.extend(["## 对应物理公式", ""])
        used_features: set[str] = set()
        for target in targets:
            for item in list(target.get("top_features", []) or [])[:8]:
                feature = str(item.get("feature", item.get("name", "")))
                if not feature or feature in used_features:
                    continue
                used_features.add(feature)
                steps = formula_chain_for_feature(feature)
                lines.extend([f"### {feature_display_name(feature)}", ""])
                if not steps:
                    lines.extend(["当前变量尚无可靠的专属解析公式映射。", ""])
                    continue
                for index, (stage, latex) in enumerate(steps, start=1):
                    lines.extend([
                        f"**公式 {index} · {stage}**",
                        "",
                        "$$",
                        latex,
                        "$$",
                        "",
                    ])
        if not used_features:
            lines.append("- 当前尚无可定位的真实特征。")
        lines.append("")

    if options.consistency_anomalies:
        lines.extend([
            "## 一致性与异常",
            "",
            "高绝对 SHAP 样本应结合正式光学仿真、变量共线性与公式适用条件复核。",
            "",
        ])

    if narrative.strip():
        lines.extend(["## 结论与说明", "", narrative.strip(), ""])

    if options.limitations:
        lines.extend([
            "## 使用边界",
            "",
            "SHAP 解释描述模型在已注册数据分布中的行为，不自动等同于因果关系；工程结论应结合正式光学仿真和公式适用条件复核。",
            "",
        ])
    return "\n".join(lines)



def build_structured_report_html(
    shap_data: dict[str, Any] | None,
    options: ReportContentOptions | None = None,
) -> str:

    from html import escape

    data = shap_data or {}
    options = options or ReportContentOptions()
    targets = [item for item in list(data.get("targets", []) or []) if isinstance(item, dict)]
    target = targets[0] if targets else {}
    source_records = list(
        data.get("feature_contributions", [])
        or data.get("top_features", [])
        or data.get("global_importance", [])
        or target.get("top_features", [])
        or []
    )
    normalized_records: list[dict[str, Any]] = []
    for item in source_records:
        if not isinstance(item, dict):
            continue
        feature = str(item.get("feature", item.get("name", "")))
        mean_shap = float(item.get("mean_shap", item.get("shap_value", 0.0)) or 0.0)
        mean_abs = float(item.get("mean_abs_shap", abs(mean_shap)) or abs(mean_shap))
        normalized_records.append({"feature": feature, "mean_shap": mean_shap, "mean_abs_shap": mean_abs})

    category_rows = physical_category_totals(normalized_records)
    confidence, confidence_note = diagnosis_confidence(data)
    top_feature = normalized_records[0]["feature"] if normalized_records else ""
    top_category = physical_mismatch_category(top_feature) if top_feature else "尚未形成诊断"

    def formula_image_html(latex: str) -> str:
        from base64 import b64encode

        from frontend_pyside.features.explainability.formula_presentation import render_formula_png

        encoded = b64encode(render_formula_png(latex)).decode("ascii")
        return (
            "<img class='formula-image' alt='物理公式' "
            f"src='data:image/png;base64,{encoded}'>"
        )

    css = """
    body { font-family: 'Microsoft YaHei','SimSun',sans-serif; color:#182235; margin:0; padding:12px; }
    h1 { font-size:22px; margin:0 0 12px 0; }
    h2 { font-size:16px; margin:0 0 9px 0; }
    .card { border:1px solid #b7c2d4; border-radius:8px; padding:12px 14px; margin:0 0 10px 0; background:#ffffff; }
    .grid { width:100%; border-collapse:collapse; }
    .grid td, .grid th { padding:6px 8px; border-bottom:1px solid #e0e5ee; vertical-align:top; }
    .grid th { text-align:left; background:#f3f6fb; font-weight:600; }
    .key { color:#5f6f87; width:20%; white-space:nowrap; }
    .badge { display:inline-block; padding:2px 8px; border-radius:10px; background:#eef3fb; font-weight:600; }
    .note { color:#526177; line-height:1.55; }
    .warning { background:#fff7e8; border-color:#e8c77d; }
    .muted { color:#6b778c; }
    .formula-image { display:block; max-width:100%; height:auto; margin:8px 0; }
    """
    parts = [f"<html><head><style>{css}</style></head><body>", "<h1>模型解释报告</h1>"]

    if not data:
        parts.append(
            "<div class='card'><h2>尚未生成解释结果</h2>"
            "<div class='note'>完成真实 SHAP 计算后，这里将显示模型信息、物理失配诊断、局部样本、公式联动和适用边界。</div></div>"
        )
        parts.append("</body></html>")
        return "".join(parts)

    if options.model_dataset:
        parts.append("<div class='card'><h2>模型与数据集信息</h2><table class='grid'>")
        rows = [
            ("模型", data.get("model_name") or data.get("model_id", "—")),
            ("数据集", data.get("dataset_name") or data.get("dataset_id", "—")),
            ("解释器", data.get("explainer", "—")),
            ("真实样本数", data.get("sample_count", target.get("sample_count", 0))),
            ("背景样本数", data.get("background_sample_count", 0)),
            ("合成样本", "是" if data.get("synthetic_samples") else "否"),
        ]
        for key, value in rows:
            parts.append(f"<tr><td class='key'>{escape(str(key))}</td><td>{escape(str(value))}</td></tr>")
        parts.append("</table></div>")

    parts.append(
        "<div class='card'><h2>模场失配诊断</h2>"
        f"<table class='grid'><tr><td class='key'>主要失配</td><td>{escape(top_category)}</td></tr>"
        f"<tr><td class='key'>诊断可信度</td><td><span class='badge'>{escape(confidence)}</span></td></tr>"
        f"<tr><td class='key'>判断说明</td><td>{escape(confidence_note)}</td></tr></table></div>"
    )

    if options.global_shap:
        parts.append("<div class='card'><h2>全局 SHAP 结果</h2>")
        if category_rows:
            maximum = max(float(row["value"]) for row in category_rows) or 1.0
            parts.append("<table class='grid'><tr><th>物理失配类别</th><th>相对重要程度</th><th>关联特征</th></tr>")
            for row in category_rows:
                importance = 100.0 * float(row["value"]) / maximum
                members = "、".join(row["features"][:6]) or "—"
                parts.append(
                    f"<tr><td>{escape(str(row['category']))}</td><td>{importance:.1f}%</td>"
                    f"<td>{escape(members)}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>当前解释结果未提供可汇总的全局特征贡献。</div>")
        parts.append("</div>")

    if options.local_samples:
        parts.append("<div class='card'><h2>局部样本解释</h2>")
        local = anomaly_rows(data, limit=8)
        if local:
            parts.append("<table class='grid'><tr><th>样本</th><th>总绝对贡献</th><th>主导特征</th><th>主导贡献</th></tr>")
            for sample_id, total, feature, contribution, _output in local:
                parts.append(
                    f"<tr><td>{escape(str(sample_id))}</td><td>{float(total):.6g}</td>"
                    f"<td>{escape(feature_display_name(str(feature)))}</td><td>{float(contribution):.6g}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>当前解释结果未提供样本级 SHAP 数据。</div>")
        parts.append("</div>")

    if options.physical_formulas:
        parts.append("<div class='card'><h2>对应物理公式</h2>")
        if normalized_records:
            formula_features: set[str] = set()
            for record in normalized_records[:8]:
                feature = str(record.get("feature") or "")
                if not feature or feature in formula_features:
                    continue
                formula_features.add(feature)
                steps = formula_chain_for_feature(feature)
                parts.append(f"<h3>{escape(feature_display_name(feature))}</h3>")
                if not steps:
                    parts.append("<div class='muted'>该变量尚无可靠的专属解析公式映射。</div>")
                    continue
                for index, (stage, latex) in enumerate(steps, start=1):
                    parts.append(f"<div><b>公式 {index} · {escape(stage)}</b></div>")
                    parts.append(formula_image_html(latex))
        else:
            parts.append("<div class='muted'>当前尚无可定位的真实特征。</div>")
        parts.append("</div>")

    if options.consistency_anomalies:
        additive = data.get("additivity_error", data.get("shap_additivity_error", "—"))
        in_domain = data.get("within_training_domain", data.get("in_training_domain"))
        domain_text = "训练域内" if in_domain is True else ("超出训练域" if in_domain is False else "尚未判断")
        parts.append(
            "<div class='card'><h2>一致性与异常说明</h2><table class='grid'>"
            f"<tr><td class='key'>SHAP 加性误差</td><td>{escape(str(additive))}</td></tr>"
            f"<tr><td class='key'>训练范围</td><td>{escape(domain_text)}</td></tr>"
            "<tr><td class='key'>完整仿真</td><td>高贡献样本仍需结合正式光学仿真复核。</td></tr>"
            "</table></div>"
        )

    if options.limitations:
        parts.append(
            "<div class='card warning'><h2>适用范围与局限</h2>"
            "<div class='note'>SHAP 描述模型在已注册数据分布中的行为，不自动等同于因果关系。"
            "结构参数可能通过完整复场间接影响耦合，最终工程结论应以正式仿真和数值质量检查为准。</div></div>"
        )

    parts.append("</body></html>")
    return "".join(parts)

def write_shap_json(path: str | Path, shap_data: dict[str, Any] | None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(shap_data or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_shap_csv(path: str | Path, shap_data: dict[str, Any] | None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = shap_rows(shap_data)
    fields = ["target_name", "feature", "mean_shap", "mean_abs_shap", "direction", "sample_value"]
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return target


def write_report(
    path: str | Path,
    shap_data: dict[str, Any] | None,
    narrative: str = "",
    options: ReportContentOptions | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_markdown_report(shap_data, narrative, options),
        encoding="utf-8",
    )
    return target


__all__ = [
    "FORMULA_CATALOG",
    "ReportContentOptions",
    "anomaly_rows",
    "build_markdown_report",
    "build_structured_report_html",
    "feature_display_name",
    "explain_shap_failure",
    "formula_binding_for_feature",
    "formula_latex",
    "formula_chain_for_feature",
    "formula_location_for_feature",
    "physical_mechanism_for_feature",
    "suggested_action_for_feature",
    "shap_rows",
    "write_report",
    "write_shap_csv",
    "write_shap_json",
]
