"""Workbench job submit/progress routing for dataset, train, scan and optimize."""

from __future__ import annotations

from math import isfinite
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from frontend_pyside.app.workbench_payloads import explain_job_failure
from frontend_pyside.features.machine_learning.feature_adapter import (
    FeaturePathError,
    features_from_project,
)

_SUBMIT_KEY = "workbench.job.submit"
_RESULT_KEY = "workbench.job.result"
_CANCEL_KEY = "workbench.job.cancel"

MODEL_KIND = {
    "随机森林": "random_forest",
    "XGBoost物理残差": "xgboost_physics_residual",
    "BiLSTM": "bilstm_structure_sequence",
}
TARGET_KIND = {
    "耦合损耗(dB)": "coupling_loss_db",
    "耦合效率": "coupling_efficiency",
    "RMS 光斑": "rms_spot_radius_um",
    "Strehl": "strehl_estimate_marechal",
}
SAMPLING_KIND = {
    "Latin Hypercube": "latin_hypercube",
    "Sobol低差异采样": "sobol",
}
RESPONSE_KIND = {
    "耦合效率": "coupling_efficiency",
    "RMS 光斑": "rms_spot_radius_um",
    "Strehl": "strehl_estimate_marechal",
    "边缘功率": "edge_power",
}


def model_backend_kind(label: str) -> str:
    text = str(label or "").strip()
    return MODEL_KIND.get(text, text)


def shap_supported(model_type: str) -> bool:
    kind = model_backend_kind(model_type)
    return kind not in {"bilstm_structure_sequence", "BiLSTM"}


def sequence_prediction_payload(project: Any, record: dict[str, Any] | None) -> dict[str, Any]:
    """Build the variable-length input expected by the BiLSTM endpoint."""
    from frontend_pyside.api.payloads import serialize_project
    from machine_learning.datasets.variable_schemes import resolve_lens_bindings

    source = serialize_project(project)
    surfaces = [row for row in source.get("surfaces", []) if isinstance(row, dict)]
    bindings = resolve_lens_bindings(source)
    if not bindings:
        raise ValueError("当前系统没有可识别的实体镜片，无法进行 BiLSTM 预测")
    names = [str(name) for name in list((record or {}).get("numeric_feature_names") or []) if str(name)]
    if not names:
        # Compatibility with early BiLSTM manifests, whose model list did not
        # expose numeric_feature_names and whose default import mapping was
        # radius_mm,thickness_mm.
        names = ["radius_mm", "thickness_mm"]
    receiver = source.get("receiver") if isinstance(source.get("receiver"), dict) else {}

    def number(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def surface_value(index: int, field: str) -> float:
        if 0 <= index < len(surfaces):
            return number(surfaces[index].get(field))
        return 0.0

    element_types: list[str] = []
    numeric_values: list[list[float]] = []
    for binding in bindings:
        front, back = binding.front_surface_index, binding.back_surface_index
        element_types.append(str(surfaces[front].get("material_after") or "lens"))
        aliases = {
            "radius_mm": surface_value(front, "radius_mm"),
            "thickness_mm": surface_value(front, "distance_to_next_mm"),
            "front_radius_mm": surface_value(front, "radius_mm"),
            "back_radius_mm": surface_value(back, "radius_mm"),
            "front_conic": surface_value(front, "conic"),
            "back_conic": surface_value(back, "conic"),
            "front_semi_aperture_mm": surface_value(front, "semi_aperture_mm"),
            "back_semi_aperture_mm": surface_value(back, "semi_aperture_mm"),
            "air_gap_after_mm": surface_value(back, "distance_to_next_mm"),
            "receiver_offset_x_um": number(receiver.get("offset_x_um")),
            "receiver_offset_y_um": number(receiver.get("offset_y_um")),
            "receiver_axial_offset_z_um": number(receiver.get("axial_offset_z_um")),
        }
        numeric_values.append([float(aliases.get(name, 0.0)) for name in names])
    return {"element_types": element_types, "numeric_values": numeric_values}


def target_backend_name(label: str) -> str:
    text = str(label or "").strip()
    return TARGET_KIND.get(text, text or "coupling_loss_db")


def sampling_backend_name(label: str) -> str:
    text = str(label or "").strip()
    return SAMPLING_KIND.get(text, text or "latin_hypercube")


def current_lens_features(project, feature_paths=None) -> dict[str, float]:
    """Return either the legacy display vector or an exact model vector.

    Prediction and current-system SHAP must pass the feature paths declared by
    the model manifest.  The optional argument keeps the small legacy vector
    available for callers that only need to display current lens values.
    """
    if feature_paths is not None:
        paths = [str(path) for path in list(feature_paths or []) if str(path).strip()]
        return features_from_project(project, paths)

    features: dict[str, float] = {
        "source.wavelength_nm": float(getattr(project, "wavelength_nm", 0.0) or 0.0),
        "pupil_radius_mm": float(getattr(project, "pupil_radius_mm", 0.0) or 0.0),
        "receiver.mode_field_diameter_x_um": float(getattr(project, "receiver_mfd_um", 0.0) or 0.0),
        "receiver.mode_field_diameter_y_um": float(getattr(project, "receiver_mfd_um", 0.0) or 0.0),
    }
    for index, surface in enumerate(list(getattr(project, "surfaces", ()) or ())):
        features[f"surfaces[{index}].radius_mm"] = float(getattr(surface, "radius_mm", 0.0) or 0.0)
        thickness = float(getattr(surface, "thickness_mm", 0.0) or 0.0)
        features[f"surfaces[{index}].thickness_mm"] = thickness
        features[f"surfaces[{index}].distance_to_next_mm"] = thickness
        features[f"surfaces[{index}].semi_aperture_mm"] = float(getattr(surface, "semi_aperture_mm", 0.0) or 0.0)
    return features


def model_prediction_status(record: dict[str, Any] | None) -> tuple[bool, str]:
    """Return whether a trained artifact is safe to expose as a predictor."""
    model = dict(record or {})
    quality = model.get("model_quality")
    if isinstance(quality, dict) and quality.get("prediction_usable") is False:
        return False, str(quality.get("reason") or "该模型质量未达到预测门槛。")

    metrics = model.get("test_metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    r2 = metrics.get("r2")
    if r2 is None:
        return True, ""
    try:
        score = float(r2)
    except (TypeError, ValueError):
        return False, "该模型的测试 R² 不是有效数值，不能用于预测。"
    if not isfinite(score) or score <= 0.0:
        return False, f"测试 R²={score:.4g}，低于 0，不能用于当前镜头预测；请重新训练模型。"
    return True, ""


def model_features(project, record: dict[str, Any] | None) -> dict[str, float]:
    """Build the current-project vector from the selected model manifest."""
    paths = list(dict(record or {}).get("feature_paths") or [])
    if not paths:
        raise FeaturePathError("模型记录没有声明 feature_paths，请刷新模型列表或重新训练。")
    return current_lens_features(project, paths)


def train_chart_unavailable_message(result: dict[str, Any], name: str) -> str:
    metadata = dict(result.get("metadata") or {})
    summary = dict(metadata.get("training_summary") or result.get("training_summary") or {})
    if name == "验证误差曲线":
        curve_status = str(
            metadata.get("training_curve_status")
            or summary.get("training_curve_status")
            or "unavailable"
        )
        if curve_status == "unavailable":
            if str(summary.get("convergence") or "") == "not_applicable":
                return "该模型没有逐轮训练记录；随机森林的训练收敛不按轮次定义，请查看残差图或实测值与预测值对照。"
            return "该模型没有返回逐轮训练记录，暂时无法绘制验证误差曲线。"
        return "训练完成，但验证误差曲线数据为空。"
    if name == "残差图":
        return "训练完成，但测试集没有残差数据，无法绘制残差图。"
    if name == "实测值与预测值对照":
        return "训练完成，但测试集没有完整的实测值与预测值对照数据。"
    if name == "残差分布":
        return "训练完成，但测试集没有残差数据，无法绘制残差分布。"
    return "训练完成，但没有可绘制的数据。"


def unwrap_job_result(data: object) -> dict[str, Any]:
    body = dict(data or {}) if isinstance(data, dict) else {}
    result = body.get("result", body)
    return dict(result) if isinstance(result, dict) else body


def train_chart_payload(result: dict[str, Any], name: str) -> dict[str, Any] | None:
    metadata = dict(result.get("metadata") or {})
    evaluation = dict(result.get("evaluation") or metadata.get("evaluation") or {})
    test_metrics = training_test_metrics(result)
    actual = _first_column(evaluation.get("actual") or [])
    predicted = _first_column(evaluation.get("predicted") or [])
    residual = _first_column(evaluation.get("residual") or [])
    def metric_labels() -> dict[str, str]:
        labels: dict[str, str] = {}
        for key, label, precision in (
            ("r2", "R²", ".4f"),
            ("mae", "MAE", ".4g"),
            ("rmse", "RMSE", ".4g"),
            ("max_absolute_error", "最大|e|", ".4g"),
        ):
            value = test_metrics.get(key)
            if isinstance(value, (int, float)) and isfinite(float(value)):
                labels[label] = format(float(value), precision)
        return labels

    metrics = metric_labels()
    if name == "残差图":
        if not residual:
            return None
        # The reference script in ``others`` uses the real simulation value on
        # the x-axis.  Keep that meaning when the training endpoint returns
        # point-level actual values; fall back to the sample index only for
        # legacy artifacts that predate the evaluation contract.
        x_values = actual[: len(residual)] if len(actual) == len(residual) else list(range(len(residual)))
        return {
            "kind": "residual",
            "actual": x_values,
            "residual": residual,
            "metrics": metrics,
            "simple": False,
            "x_label": "真实仿真值" if len(actual) == len(residual) else "样本",
            "y_label": "残差（预测 − 真实）",
            "source": "训练评估",
            "description": _training_chart_description(
                len(residual), metrics, "测试集残差"
            ),
        }
    if name == "实测值与预测值对照":
        if not actual or not predicted or len(actual) != len(predicted):
            return None
        return {
            "kind": "validation_scatter",
            "actual": actual,
            "predicted": predicted,
            "metrics": metrics,
            "simple": False,
            "x_label": "真实仿真值",
            "y_label": "模型预测值",
            "source": "训练评估",
            "description": _training_chart_description(
                len(actual), metrics, "测试集实测值与预测值对照"
            ),
        }
    if name == "残差分布":
        if not residual:
            return None
        return {
            "kind": "histogram",
            "values": residual,
            "bins": min(24, max(8, int(len(residual) ** 0.5) + 2)),
            "mean": sum(residual) / len(residual),
            "zero_line": True,
            "x_label": "残差（预测 − 真实）",
            "y_label": "样本数",
            "title": "测试集残差分布",
            "value_unit": "",
            "source": "训练评估",
            "description": _training_chart_description(
                len(residual), metrics, "测试集残差分布"
            ),
        }
    history = metadata.get("training_history") or result.get("training_history") or {}
    curve = result.get("oob_error_curve") or metadata.get("oob_error_curve")
    ys = _history_curve(history) if isinstance(history, (dict, list, tuple)) else []
    if not ys and isinstance(curve, (list, tuple)):
        ys = [float(value) for value in curve]
    if not ys:
        return None
    metadata_curve_label = str(
        result.get("training_curve_label")
        or metadata.get("training_curve_label")
        or "验证误差"
    )
    return {
        "kind": "line",
        "x": list(range(len(ys))),
        "y": ys,
        "x_label": "轮次",
        "y_label": metadata_curve_label,
        "series_label": metadata_curve_label,
        "source": "训练评估",
        "description": str(metadata.get("training_curve_description") or ""),
        "reference_y": test_metrics.get("rmse"),
        "reference_label": (
            f"测试集 RMSE = {float(test_metrics['rmse']):.4g}"
            if isinstance(test_metrics.get("rmse"), (int, float))
            and isfinite(float(test_metrics["rmse"]))
            else ""
        ),
    }


def _training_chart_description(sample_count: int, metrics: dict[str, str], title: str) -> str:
    parts = [title, f"测试样本 {sample_count}"]
    for key in ("R²", "MAE", "RMSE", "最大|e|"):
        if key in metrics:
            parts.append(f"{key}={metrics[key]}")
    return " ".join(parts)


def training_test_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Return one flat metric mapping for the selected training target."""
    metadata = dict(result.get("metadata") or {})
    raw = (
        result.get("test_metrics")
        or result.get("metrics")
        or metadata.get("test_metrics")
        or {}
    )
    metrics = dict(raw) if isinstance(raw, dict) else {}
    if any(key in metrics for key in ("r2", "mae", "rmse")):
        return metrics
    target_names = list(
        result.get("target_names")
        or metadata.get("target_names")
        or []
    )
    for target in target_names:
        nested = metrics.get(str(target))
        if isinstance(nested, dict):
            return dict(nested)
    for nested in metrics.values():
        if isinstance(nested, dict) and any(key in nested for key in ("r2", "mae", "rmse")):
            return dict(nested)
    return metrics


from shared_presentation.scan_results import scan_curve_payload


from shared_presentation.optimization_results import opt_chart_payload


def shap_dependence_item(body: dict[str, Any], selected: str) -> dict[str, Any]:
    dependence = dict(body.get("shap_dependence") or {})
    if selected in dependence and isinstance(dependence.get(selected), dict):
        return dict(dependence[selected])
    for feature, item in dependence.items():
        if not isinstance(item, dict):
            continue
        if str(feature) == str(selected) or str(item.get("feature") or "") == str(selected):
            return dict(item)
    return {}


def _first_column(values: Any) -> list[float]:
    rows = list(values or [])
    out: list[float] = []
    for item in rows:
        if isinstance(item, (list, tuple)):
            if not item:
                continue
            out.append(float(item[0]))
        else:
            out.append(float(item))
    return out


def _history_curve(history: dict[str, Any] | list[Any] | tuple[Any, ...]) -> list[float]:
    if isinstance(history, (list, tuple)) and history and all(isinstance(item, dict) for item in history):
        for key in (
            "validation_mse_scaled",
            "validation",
            "valid",
            "rmse",
            "error",
            "validation_loss",
            "val_loss",
        ):
            values = [item.get(key) for item in history]
            if values and all(isinstance(item, (int, float)) for item in values):
                return [float(item) for item in values]
    stack: list[Any] = list(history.values()) if isinstance(history, dict) else list(history)
    while stack:
        value = stack.pop(0)
        if isinstance(value, dict):
            for key in (
                "validation",
                "valid",
                "rmse",
                "error",
                "validation_mse_scaled",
                "validation_loss",
                "val_loss",
            ):
                if key in value:
                    candidate = value[key]
                    if isinstance(candidate, (list, tuple)):
                        return [float(item) for item in candidate]
                    stack.insert(0, candidate)
                    break
            else:
                stack[0:0] = list(value.values())
        elif isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
            return [float(item) for item in value]
    return []


def shap_beeswarm_payload(
    body: dict[str, Any],
    feature_label=None,
    *,
    limit: int = 8,
) -> dict[str, Any] | None:
    """Build the SHAP distribution chart from the cached explanation response.

    ``others/SHAP.docx`` describes a beeswarm plot as the companion to global
    mean-|SHAP| importance.  The backend already returns point-level SHAP
    values, so the desktop can render that chart without re-running the model
    or reading a hard-coded dataset path.
    """
    items = list(body.get("top_features") or body.get("feature_contributions") or [])
    if not items:
        targets = list(body.get("targets") or [])
        if targets and isinstance(targets[0], dict):
            items = list(targets[0].get("top_features") or [])
    samples = list(body.get("sample_shap_values") or [])
    if not samples:
        targets = list(body.get("targets") or [])
        if targets and isinstance(targets[0], dict):
            samples = list(targets[0].get("sample_shap_values") or [])
    if not items or not samples:
        return None

    selected = [
        item for item in items[: max(1, int(limit))]
        if isinstance(item, dict) and str(item.get("feature") or item.get("name") or "")
    ]
    if not selected:
        return None
    raw_features = [str(item.get("feature") or item.get("name") or "") for item in selected]
    labels = [
        str(feature_label(feature) if callable(feature_label) else feature)
        for feature in raw_features
    ]
    importance = [
        float(item.get("mean_abs_shap", abs(float(item.get("mean_shap", 0.0) or 0.0))) or 0.0)
        for item in selected
    ]
    feature_values: dict[str, list[float]] = {feature: [] for feature in raw_features}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        values = dict(sample.get("feature_values") or {})
        for feature in raw_features:
            value = values.get(feature)
            if isinstance(value, (int, float)) and isfinite(float(value)):
                feature_values[feature].append(float(value))

    points: list[dict[str, Any]] = []
    for sample_index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        shap_values = dict(sample.get("shap_values") or {})
        raw_feature_values = dict(sample.get("feature_values") or {})
        for feature in raw_features:
            value = shap_values.get(feature)
            if not isinstance(value, (int, float)) or not isfinite(float(value)):
                continue
            raw = raw_feature_values.get(feature)
            values = feature_values.get(feature) or []
            low = min(values) if values else 0.0
            high = max(values) if values else 1.0
            try:
                scaled = (float(raw) - low) / (high - low) if high > low else 0.5
            except (TypeError, ValueError):
                scaled = 0.5
            color = "#dc2626" if scaled >= 0.5 else "#2563eb"
            points.append(
                {
                    "feature": str(feature_label(feature) if callable(feature_label) else feature),
                    "value": float(value),
                    "sample_index": sample_index,
                    "color": color,
                }
            )
    if not points:
        return None
    target = str(body.get("target_name") or body.get("target") or "模型输出")
    return {
        "kind": "beeswarm",
        "labels": labels,
        "points": points,
        "importance": importance,
        "sample_count": len(samples),
        "x_label": f"SHAP 贡献 · {target}",
        "source": "模型解释",
        "summary": "红色表示该变量取值偏高，蓝色表示偏低；横轴为对模型输出的正负贡献。",
        "description": f"SHAP 分布 · {len(samples)} 个样本 · 前 {len(labels)} 个特征",
    }


class WorkbenchJobController(QObject):
    """Submit workbench jobs and route watcher/result callbacks on the UI thread."""

    submitted = Signal(str, str)
    progress = Signal(str, float, str)
    finished = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    cancellationFailed = Signal(str, str)

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self._context = context
        services = getattr(context, "services", None)
        self._api = getattr(context, "api_client", None)
        self._clients = {
            "dataset": getattr(services, "dataset", None),
            "training": getattr(services, "training", None),
            "scan": getattr(services, "scan", None),
            "optimization": getattr(services, "optimization", None),
        }
        self._job_client = getattr(services, "jobs", None)
        self._job_watcher = getattr(services, "job_watcher", None)
        self._pending: dict[str, dict[str, Any]] = {}
        self._jobs: dict[str, str] = {}
        if self._api is not None:
            self._api.completed.connect(self._on_api_completed)
            self._api.failed.connect(self._on_api_failed)
        if self._job_watcher is not None:
            self._job_watcher.job_progress.connect(self._on_job_progress)
            self._job_watcher.job_completed.connect(self._on_job_completed)
            self._job_watcher.job_failed.connect(self._on_job_failed)

    def is_busy(self, kind: str | None = None) -> bool:
        if kind is None:
            return bool(self._pending)
        return any(item.get("kind") == str(kind) for item in self._pending.values())

    def submit(self, kind: str, payload: dict[str, Any]) -> str:
        kind = str(kind or "")
        client_name, method_name = {
            "dataset": ("dataset", "submit"),
            "train": ("training", "submit"),
            "joint_train": ("training", "submit_joint"),
            "bilstm": ("training", "submit_bilstm"),
            "scan": ("scan", "submit"),
            "optimize": ("optimization", "submit"),
        }.get(kind, ("", ""))
        if self._api is None:
            return "后端不可用（无 API 连接）"
        client = self._clients.get(client_name)
        method = getattr(client, method_name, None) if client is not None else None
        if not callable(method):
            return f"后端客户端不可用：{client_name or kind}"
        if self.is_busy(kind):
            return "同一类任务仍在运行，请等待完成后再提交。"
        request_id = f"workbench-{kind}-{uuid4().hex[:8]}"
        self._pending[request_id] = {"kind": kind, "job_id": ""}
        method(f"{_SUBMIT_KEY}:{request_id}", payload)
        return ""

    def cancel(self, kind: str) -> str:
        """Request cancellation for the active job of ``kind``.

        The terminal event is still delivered by the job watcher, so callers
        can keep the row in its cancelling state until the worker confirms it.
        """
        kind = str(kind or "")
        pending_item = next(
            (
                (request_id, pending)
                for request_id, pending in self._pending.items()
                if str(pending.get("kind") or "") == kind
            ),
            None,
        )
        if pending_item is None:
            return "没有可取消的任务"
        request_id, pending = pending_item
        job_id = str(pending.get("job_id") or "")
        if not job_id:
            return "任务正在提交，请稍后再取消"
        if self._job_client is None:
            return "后端任务客户端不可用"
        if bool(pending.get("cancelling")):
            return "正在取消任务"
        pending["cancelling"] = True
        self._job_client.cancel(f"{_CANCEL_KEY}:{job_id}", job_id)
        return ""

    def _on_api_completed(self, key: str, data) -> None:
        base, _, token = str(key).partition(":")
        if base == _SUBMIT_KEY:
            pending = self._pending.get(token)
            if pending is None:
                return
            job_id = str(data.get("job_id", "") or "") if isinstance(data, dict) else ""
            if not job_id:
                self._pending.pop(token, None)
                self.failed.emit(str(pending.get("kind") or ""), "后端未返回任务 ID")
                return
            pending["job_id"] = job_id
            self._jobs[job_id] = token
            if self._job_watcher is not None:
                self._job_watcher.subscribe(job_id)
            self.submitted.emit(str(pending.get("kind") or ""), job_id)
        elif base == _RESULT_KEY:
            job_id = token
            request_id = self._jobs.pop(job_id, "")
            pending = self._pending.pop(request_id, None) or {}
            kind = str(pending.get("kind") or "")
            self.finished.emit(kind, unwrap_job_result(data))
        elif base == _CANCEL_KEY:
            # The watcher emits the authoritative terminal cancelled event.
            # A successful HTTP acknowledgement does not mean the worker has
            # exited yet, so deliberately keep the pending record here.
            return

    def _on_api_failed(self, key: str, message: str) -> None:
        base, _, token = str(key).partition(":")
        if base == _SUBMIT_KEY:
            pending = self._pending.pop(token, None) or {}
            self.failed.emit(str(pending.get("kind") or ""), f"提交失败：{message}")
        elif base == _RESULT_KEY:
            job_id = token
            request_id = self._jobs.pop(job_id, "")
            pending = self._pending.pop(request_id, None) or {}
            self.failed.emit(str(pending.get("kind") or ""), explain_job_failure(message))
        elif base == _CANCEL_KEY:
            job_id = token
            request_id = self._jobs.get(job_id, "")
            pending = self._pending.get(request_id) or {}
            if not pending:
                return
            pending["cancelling"] = False
            self.cancellationFailed.emit(
                str(pending.get("kind") or ""),
                f"取消任务失败：{message}",
            )

    def _on_job_progress(self, job_id: str, progress: float, stage: str) -> None:
        request_id = self._jobs.get(str(job_id), "")
        pending = self._pending.get(request_id) or {}
        if pending:
            self.progress.emit(str(pending.get("kind") or ""), float(progress or 0.0), str(stage or ""))

    def _on_job_completed(self, job_id: str, status: str, metrics: dict) -> None:
        job_id = str(job_id)
        request_id = self._jobs.get(job_id, "")
        pending = self._pending.get(request_id) or {}
        if not pending:
            return
        if status == "completed":
            if self._job_client is not None:
                self._job_client.get_result(f"{_RESULT_KEY}:{job_id}", job_id)
                return
            self._jobs.pop(job_id, None)
            self._pending.pop(request_id, None)
            self.finished.emit(str(pending.get("kind") or ""), {"status": "completed", "metrics": dict(metrics or {})})
            return
        self._jobs.pop(job_id, None)
        self._pending.pop(request_id, None)
        if status == "cancelled":
            self.cancelled.emit(str(pending.get("kind") or ""))
        else:
            self.failed.emit(str(pending.get("kind") or ""), f"任务{status}")

    def _on_job_failed(self, job_id: str, message: str) -> None:
        request_id = self._jobs.pop(str(job_id), "")
        pending = self._pending.pop(request_id, None) or {}
        if pending:
            self.failed.emit(str(pending.get("kind") or ""), explain_job_failure(message))
