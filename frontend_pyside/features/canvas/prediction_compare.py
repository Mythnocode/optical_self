"""Forward-result card: current lens features vs physics baseline / residual."""

from __future__ import annotations

import math
from typing import Any

from frontend_pyside.shared.feature_labels import display_feature_name

_FEATURE_PRIORITY = (
    "source.wavelength_nm",
    "source.pupil_radius_mm",
    "pupil_radius_mm",
    "receiver.mode_field_diameter_um",
    "receiver_mfd_um",
)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _loss_db_from_efficiency(eta: float) -> float:
    return -10.0 * math.log10(max(float(eta), 1e-12))


def physics_baseline_metrics(context: Any, extra: dict[str, Any] | None = None) -> dict[str, float]:
    """Last formal / engine metrics available on the workspace context."""
    values: dict[str, float] = {}
    for source in (
        extra,
        getattr(getattr(getattr(context, "project", None), "project", None), "metrics", None),
    ):
        if not isinstance(source, dict):
            continue
        for key, raw in source.items():
            number = _finite(raw)
            if number is not None:
                values[str(key)] = number
    formal = getattr(getattr(context, "project", None), "formal_result", None)
    if isinstance(formal, dict):
        block = formal.get("metrics", formal)
        if isinstance(block, dict):
            for key, raw in block.items():
                number = _finite(raw)
                if number is not None:
                    values[str(key)] = number
    return values


def baseline_for_target(name: str, physics: dict[str, float]) -> float | None:
    key = str(name)
    if key in physics:
        return physics[key]
    lowered = key.lower()
    if "efficiency" in lowered and "coupling_efficiency" in physics:
        return physics["coupling_efficiency"]
    if key == "coupling_loss_db" and "coupling_efficiency" in physics:
        return _loss_db_from_efficiency(physics["coupling_efficiency"])
    return None


def _pick_features(features: dict[str, float], *, limit: int = 4) -> list[tuple[str, float]]:
    picked: list[tuple[str, float]] = []
    seen: set[str] = set()
    for path in _FEATURE_PRIORITY:
        number = _finite(features.get(path))
        if number is None or path in seen:
            continue
        seen.add(path)
        picked.append((path, number))
        if len(picked) >= limit:
            return picked
    for path, raw in features.items():
        if path in seen:
            continue
        number = _finite(raw)
        if number is None:
            continue
        seen.add(path)
        picked.append((str(path), number))
        if len(picked) >= limit:
            break
    return picked


def _format_feature(path: str, value: float) -> str:
    label = display_feature_name(path)
    if label.startswith("未登记特征"):
        label = path.split(".")[-1]
    if path.endswith("_nm") or "wavelength" in path:
        return f"{label} {value:.1f}"
    if abs(value) >= 100:
        return f"{label} {value:.1f}"
    if abs(value) >= 1:
        return f"{label} {value:.3g}"
    return f"{label} {value:.3g}"


def format_prediction_value(name: str, raw: Any) -> str:
    number = _finite(raw)
    if number is None:
        return str(raw)
    key = str(name).lower()
    if "efficiency" in key:
        return f"{number * 100.0:.2f} %"
    if "db" in key:
        return f"{number:+.3g} dB" if number < 0 or name.endswith("residual") else f"{number:.3g} dB"
    if "um" in key:
        return f"{number:.3g} μm"
    return f"{number:.4g}"


def format_residual_value(name: str, raw: Any) -> str:
    number = _finite(raw)
    if number is None:
        return "—"
    key = str(name).lower()
    if "efficiency" in key:
        return f"{number * 100.0:+.2f} %"
    if "db" in key:
        return f"{number:+.3g} dB"
    if "um" in key:
        return f"{number:+.3g} μm"
    return f"{number:+.4g}"


def prediction_label(name: str) -> str:
    labels = {
        "coupling_efficiency": "耦合效率",
        "coupling_loss_db": "耦合损耗",
        "rms_spot_radius_um": "RMS 光斑",
        "strehl_estimate_marechal": "Strehl",
    }
    return labels.get(str(name), str(name))


def build_forward_compare(
    result: dict[str, Any],
    *,
    features: dict[str, Any] | None = None,
    context: Any = None,
    extra_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach current-lens features, physics baseline and residual to a predict payload."""
    payload = dict(result or {})
    incoming = dict(payload.get("features") or {})
    incoming.update({str(key): float(value) for key, value in dict(features or {}).items() if _finite(value) is not None})
    payload["features"] = incoming
    physics = physics_baseline_metrics(context, extra_metrics)
    payload["physics_baseline"] = dict(physics)
    predictions = dict(payload.get("predictions") or {})
    residuals: dict[str, float] = {}
    matched_baseline: dict[str, float] = {}
    for name, raw in predictions.items():
        predicted = _finite(raw)
        baseline = baseline_for_target(str(name), physics)
        if predicted is None or baseline is None:
            continue
        matched_baseline[str(name)] = baseline
        residuals[str(name)] = predicted - baseline
    payload["matched_baseline"] = matched_baseline
    payload["residuals"] = residuals
    return payload


def compare_rows(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Result-card rows: lens params, prediction, formal baseline, residual."""
    payload = dict(result or {})
    predictions = dict(payload.get("predictions") or {})
    rows: list[tuple[str, str]] = [
        ("模型", str(payload.get("model_name") or payload.get("model_id") or "—")[:28]),
    ]
    feature_bits = [
        _format_feature(path, value)
        for path, value in _pick_features(
            {str(key): float(raw) for key, raw in dict(payload.get("features") or {}).items() if _finite(raw) is not None}
        )
    ]
    if feature_bits:
        rows.append(("当前透镜", " · ".join(feature_bits)[:72]))
    if not predictions:
        rows.append(("预测", str(payload.get("error") or "后端未返回预测值")))
        return rows
    primary = next(iter(predictions))
    for name in ("coupling_efficiency", "coupling_loss_db", "rms_spot_radius_um", "strehl_estimate_marechal"):
        if name in predictions:
            primary = name
            break
    rows.append((f"预测 {prediction_label(primary)}", format_prediction_value(primary, predictions[primary])))
    matched = dict(payload.get("matched_baseline") or {})
    if primary in matched:
        rows.append(("正式基线", format_prediction_value(primary, matched[primary])))
        rows.append(("残差", format_residual_value(primary, dict(payload.get("residuals") or {}).get(primary))))
    else:
        rows.append(("正式基线", "尚未正式计算"))
    return rows


__all__ = [
    "baseline_for_target",
    "build_forward_compare",
    "compare_rows",
    "format_prediction_value",
    "format_residual_value",
    "physics_baseline_metrics",
    "prediction_label",
]
