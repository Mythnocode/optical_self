from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

import numpy as np


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any, *, digits: int = 4) -> str:
    number = _finite_number(value)
    if number is None:
        return "—"
    magnitude = abs(number)
    if magnitude != 0.0 and (magnitude >= 1e4 or magnitude < 1e-3):
        return f"{number:.3e}"
    return f"{number:.{digits}g}"


def _metric(label: str, value: Any, unit: str = "") -> tuple[str, str]:
    text = _fmt(value)
    if text != "—" and unit:
        text = f"{text} {unit}"
    return label, text


def _scatter_metrics(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    try:
        x = np.asarray(data.get("x", []), dtype=float).reshape(-1)
        y = np.asarray(data.get("y", []), dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return []
    count = min(len(x), len(y))
    if count <= 0:
        return []
    x = x[:count]
    y = y[:count]
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.any(finite):
        return []
    x = x[finite]
    y = y[finite]
    cx = float(np.mean(x))
    cy = float(np.mean(y))
    rms = float(np.sqrt(np.mean((x - cx) ** 2 + (y - cy) ** 2)))
    unit = "μm" if "μm" in str(data.get("x_label", "")) else ""
    result = [
        _metric("RMS 半径", rms, unit),
        ("有效样本", str(len(x))),
    ]
    airy = _finite_number(data.get("airy_radius_um"))
    if airy is not None and airy > 0.0:
        result.insert(1, _metric("艾里斑半径", airy, "μm"))
    return result


def _beam_match_metrics(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    metrics = dict(data.get("metrics", {}) or {})
    result: list[tuple[str, str]] = []
    mapping = (
        ("center_offset_um", "中心偏移", "μm"),
        ("size_ratio_x", "X 尺寸比", ""),
        ("size_ratio_y", "Y 尺寸比", ""),
        ("ellipticity", "椭圆率", ""),
        ("coupling_efficiency_percent", "耦合效率", "%"),
        ("system_efficiency_percent", "系统效率", "%"),
        ("coupling_efficiency", "耦合效率", "%"),
        ("mode_overlap_efficiency", "模场效率", "%"),
    )
    for key, label, unit in mapping:
        value = _finite_number(metrics.get(key))
        if value is None:
            continue
        if unit == "%" and 0.0 <= value <= 1.0:
            value *= 100.0
        result.append(_metric(label, value, unit))
    return result


def _waist_metrics(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    metrics = dict(data.get("metrics", {}) or {})
    mapping = (
        ("fiber_to_x_waist_mm", "端面至 X 束腰", "mm"),
        ("fiber_to_y_waist_mm", "端面至 Y 束腰", "mm"),
        ("facet_spot_x_um", "端面 X 半径", "μm"),
        ("facet_spot_y_um", "端面 Y 半径", "μm"),
        ("target_radius_um", "目标模场半径", "μm"),
    )
    return [
        _metric(label, metrics[key], unit)
        for key, label, unit in mapping
        if _finite_number(metrics.get(key)) is not None
    ]


def _bar_metrics(data: Mapping[str, Any]) -> list[tuple[str, str]]:
    labels = list(data.get("labels", []) or [])
    values = list(data.get("values", []) or [])
    unit = "μm" if "μm" in str(data.get("y_label", "")) else ""
    result: list[tuple[str, str]] = []
    for label, value in zip(labels[:4], values[:4]):
        number = _finite_number(value)
        if number is not None:
            result.append(_metric(str(label), number, unit))
    if len(values) >= 2:
        first = _finite_number(values[0])
        second = _finite_number(values[1])
        if first is not None and second is not None and min(abs(first), abs(second)) > 1e-12:
            result.append(_metric("椭圆率", max(abs(first), abs(second)) / min(abs(first), abs(second))))
    return result


def key_metrics(data: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Return compact, user-facing metrics for a plot.

    The function deliberately keeps metrics subordinate to the analysis view:
    it extracts only a few values that help interpret the current plot.  More
    verbose descriptions remain in the foldable detail area.
    """
    data = dict(data or {})
    kind = str(data.get("kind", ""))
    explicit = data.get("key_metrics")
    if isinstance(explicit, (list, tuple)):
        normalized: list[tuple[str, str]] = []
        for item in explicit:
            if isinstance(item, Mapping):
                label = str(item.get("label", "")).strip()
                value = str(item.get("value", "")).strip()
                if label and value:
                    normalized.append((label, value))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                normalized.append((str(item[0]), str(item[1])))
        if normalized:
            return normalized[:6]
    if kind == "scatter":
        return _scatter_metrics(data)[:6]
    if kind == "beam_match":
        return _beam_match_metrics(data)[:6]
    if kind == "waist_position":
        return _waist_metrics(data)[:6]
    if kind in {"bar", "barh"}:
        return _bar_metrics(data)[:6]
    metrics = data.get("metrics")
    if isinstance(metrics, Mapping):
        # Only expose metrics that already carry a Chinese display label through
        # ``metric_labels``.  This prevents backend implementation keys leaking
        # into the interface.
        labels = dict(data.get("metric_labels", {}) or {})
        result: list[tuple[str, str]] = []
        for key, label in labels.items():
            if key not in metrics:
                continue
            value = _finite_number(metrics.get(key))
            if value is not None:
                result.append(_metric(str(label), value))
        return result[:6]
    return []


def detail_text(data: Mapping[str, Any] | None) -> str:
    data = dict(data or {})
    description = str(data.get("description", "") or "").strip()
    if description:
        return description
    source = str(data.get("source", "") or "").strip()
    return f"数据来源：{source}" if source else ""



def detail_report_sections(data: Mapping[str, Any] | None) -> list[tuple[str, list[tuple[str, str]]]]:
    """Build a dense data-only report from values actually present in a result payload.

    This deliberately does not invent optical metrics.  It exposes labelled metrics,
    provenance, sampling information and numerical array statistics that already exist
    in the formal/preview result payload.
    """
    payload = dict(data or {})
    sections: list[tuple[str, list[tuple[str, str]]]] = []

    summary = key_metrics(payload)
    if summary:
        sections.append(("关键指标", list(summary)))

    provenance: list[tuple[str, str]] = []
    source = str(payload.get("source", "") or "").strip()
    if source:
        provenance.append(("数据来源", source))
    description = str(payload.get("description", "") or "").strip()
    if description:
        provenance.append(("说明", description))
    render_key = str(payload.get("render_key", "") or "").strip()
    if render_key:
        provenance.append(("结果标识", render_key))
    if provenance:
        sections.append(("结果信息", provenance))

    metric_rows: list[tuple[str, str]] = []
    metrics = payload.get("metrics")
    labels = dict(payload.get("metric_labels", {}) or {})
    if isinstance(metrics, Mapping):
        for key, value in metrics.items():
            number = _finite_number(value)
            if number is None:
                continue
            label = str(labels.get(key, "") or "").strip()
            if not label:
                # Only show backend keys when they are already human-readable.
                text_key = str(key)
                if any("\u4e00" <= ch <= "\u9fff" for ch in text_key):
                    label = text_key
                else:
                    continue
            metric_rows.append(_metric(label, number))
    # Remove values already shown in the summary while preserving any richer metrics.
    if metric_rows:
        seen = {(a, b) for a, b in summary}
        metric_rows = [row for row in metric_rows if row not in seen]
        if metric_rows:
            sections.append(("完整指标", metric_rows))

    sampling: list[tuple[str, str]] = []
    for key, label in (
        ("x_label", "X 坐标"), ("y_label", "Y 坐标"), ("z_label", "Z 坐标"),
        ("frequency_label", "频率坐标"), ("units", "单位"),
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            sampling.append((label, value.strip()))

    array_stats: list[tuple[str, str]] = []
    array_keys = (
        ("x", "X 数据"), ("y", "Y 数据"), ("z", "Z 数据"),
        ("values", "数值"), ("image", "二维数据"), ("intensity", "强度"),
        ("phase", "相位"), ("amplitude", "振幅"),
    )
    visited: set[int] = set()
    for key, label in array_keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            arr = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            continue
        if arr.size <= 0 or id(value) in visited:
            continue
        visited.add(id(value))
        finite = arr[np.isfinite(arr)]
        shape_text = " × ".join(str(v) for v in arr.shape) if arr.ndim else "1"
        if finite.size:
            stats = f"{shape_text}；有限值 {finite.size}；min {_fmt(float(np.min(finite)))}；max {_fmt(float(np.max(finite)))}；mean {_fmt(float(np.mean(finite)))}"
        else:
            stats = f"{shape_text}；无有限数值"
        array_stats.append((label, stats))
    if sampling:
        sections.append(("坐标与采样", sampling))
    if array_stats:
        sections.append(("数值数据规模", array_stats))

    # Explicit detail rows supplied by an analysis adapter take precedence as a final section.
    explicit = payload.get("detail_rows")
    explicit_rows: list[tuple[str, str]] = []
    if isinstance(explicit, (list, tuple)):
        for item in explicit:
            if isinstance(item, Mapping):
                label = str(item.get("label", "") or "").strip()
                value = str(item.get("value", "") or "").strip()
                if label and value:
                    explicit_rows.append((label, value))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                explicit_rows.append((str(item[0]), str(item[1])))
    if explicit_rows:
        sections.append(("专业数据", explicit_rows))

    if not sections:
        message = str(payload.get("message", "当前结果尚无可展示的详细数值。") or "当前结果尚无可展示的详细数值。")
        sections.append(("详细数据", [("状态", message)]))
    return sections


def detail_report_html(data: Mapping[str, Any] | None) -> str:
    """Render the data-only detail view as compact, selectable HTML."""
    from html import escape

    payload = dict(data or {})
    title = str(payload.get("title", "详细数据") or "详细数据")
    sections = detail_report_sections(payload)
    blocks: list[str] = [
        '<div style="font-family:sans-serif; color:#172B4D;">',
        f'<div style="font-size:18pt; font-weight:700; margin-bottom:8px;">{escape(title)}</div>',
    ]
    # Use a two-column grid-like table per semantic section.  Long values remain selectable.
    for section, rows in sections:
        blocks.append(f'<div style="font-size:13pt; font-weight:700; color:#174EA6; margin-top:12px; margin-bottom:4px;">{escape(section)}</div>')
        blocks.append('<table cellspacing="0" cellpadding="5" width="100%" style="border-collapse:collapse; font-size:11.5pt;">')
        for index, (label, value) in enumerate(rows):
            bg = '#F7F9FC' if index % 2 == 0 else '#FFFFFF'
            blocks.append(
                f'<tr style="background:{bg};">'
                f'<td width="28%" style="font-weight:600; color:#344054; border-bottom:1px solid #E4E7EC;">{escape(str(label))}</td>'
                f'<td style="color:#101828; border-bottom:1px solid #E4E7EC;">{escape(str(value))}</td>'
                '</tr>'
            )
        blocks.append('</table>')
    blocks.append('</div>')
    return ''.join(blocks)
