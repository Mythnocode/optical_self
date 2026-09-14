"""Workbench job submit/progress routing for dataset, train, scan and optimize."""

from __future__ import annotations

from math import isfinite
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from frontend_pyside.features.canvas.task_runner import explain_job_failure
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
    if name == "学习曲线":
        curve_status = str(
            metadata.get("training_curve_status")
            or summary.get("training_curve_status")
            or "unavailable"
        )
        if curve_status == "unavailable":
            if str(summary.get("convergence") or "") == "not_applicable":
                return "该模型没有逐轮训练记录；随机森林的训练收敛不按轮次定义，请查看残差图或实测对照。"
            return "该模型没有返回逐轮训练记录，暂时无法绘制学习曲线。"
        return "训练完成，但学习曲线数据为空。"
    if name == "残差图":
        return "训练完成，但测试集没有残差数据，无法绘制残差图。"
    if name == "实测对照":
        return "训练完成，但测试集没有完整的实测/预测对照数据。"
    return "训练完成，但没有可绘制的数据。"


def unwrap_job_result(data: object) -> dict[str, Any]:
    body = dict(data or {}) if isinstance(data, dict) else {}
    result = body.get("result", body)
    return dict(result) if isinstance(result, dict) else body


def train_chart_payload(result: dict[str, Any], name: str) -> dict[str, Any] | None:
    metadata = dict(result.get("metadata") or {})
    evaluation = dict(result.get("evaluation") or metadata.get("evaluation") or {})
    if name == "残差图":
        residual = evaluation.get("residual") or []
        ys = _first_column(residual)
        if not ys:
            return None
        return {
            "kind": "scatter", "x": list(range(len(ys))), "y": ys,
            "x_label": "样本", "y_label": "残差", "series_label": "测试残差",
            "source": "训练评估",
        }
    if name == "实测对照":
        actual = _first_column(evaluation.get("actual") or [])
        predicted = _first_column(evaluation.get("predicted") or [])
        if not actual or not predicted or len(actual) != len(predicted):
            return None
        return {
            "kind": "scatter", "x": actual, "y": predicted,
            "x_label": "实测", "y_label": "预测", "series_label": "测试样本",
            "source": "训练评估",
        }
    history = metadata.get("training_history") or result.get("training_history") or {}
    curve = result.get("oob_error_curve") or metadata.get("oob_error_curve")
    ys = _history_curve(history) if isinstance(history, dict) else []
    if not ys and isinstance(curve, (list, tuple)):
        ys = [float(value) for value in curve]
    if not ys:
        return None
    metadata_curve_label = str(metadata.get("training_curve_label") or "验证误差")
    return {
        "kind": "line",
        "x": list(range(len(ys))),
        "y": ys,
        "x_label": "轮次",
        "y_label": metadata_curve_label,
        "series_label": metadata_curve_label,
        "source": "训练评估",
        "description": str(metadata.get("training_curve_description") or ""),
    }


def scan_curve_payload(result: dict[str, Any], response_label: str) -> dict[str, Any] | None:
    grid = result.get("parameter_grid") or []
    key = RESPONSE_KIND.get(str(response_label), str(response_label or "coupling_efficiency"))
    ys = [float(value) for value in (result.get("response_values") or {}).get(key) or []]
    two_dimensional = bool(grid and isinstance(grid[0], (list, tuple)) and len(grid[0]) >= 2)
    if two_dimensional:
        pairs = [tuple(map(float, point[:2])) for point in grid if isinstance(point, (list, tuple)) and len(point) >= 2]
        if not pairs or len(pairs) != len(ys):
            return None
        xs = sorted({pair[0] for pair in pairs})
        second = sorted({pair[1] for pair in pairs})
        if not xs or not second:
            return None
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


def opt_chart_payload(result: dict[str, Any], name: str) -> dict[str, Any] | None:
    history = list(result.get("history") or [])
    if name == "候选对照":
        candidates = list(result.get("candidates") or [])
        source = candidates if candidates else history
        labels: list[str] = []
        values: list[float] = []
        for index, item in enumerate(source[:12]):
            if not isinstance(item, dict):
                continue
            metrics = dict(item.get("metrics") or {})
            value = metrics.get("coupling_efficiency")
            if value is None:
                continue
            labels.append(f"候选 {index + 1}")
            values.append(float(value))
        if not labels:
            return None
        return {
            "kind": "bar",
            "labels": labels,
            "values": values,
            "show_values": True,
            "source": "正式优化评价",
            "description": "候选方案的正式评价结果；过程曲线使用独立的评价历史。",
        }
    xs: list[float] = []
    ys: list[float] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        xs.append(float(item.get("evaluations", item.get("iteration", len(xs))) or len(xs)))
        ys.append(float(item.get("merit", 0.0) or 0.0))
    if not xs:
        return None
    return {
        "kind": "line", "x": xs, "y": ys,
        "x_label": "评价次数", "y_label": "评价函数",
        "series_label": "评价函数", "source": "正式优化过程",
    }


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


def _history_curve(history: dict[str, Any]) -> list[float]:
    stack: list[Any] = list(history.values())
    while stack:
        value = stack.pop(0)
        if isinstance(value, dict):
            for key in ("validation", "valid", "rmse", "error"):
                if key in value:
                    stack.insert(0, value[key])
                    break
            else:
                stack[0:0] = list(value.values())
        elif isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
            return [float(item) for item in value]
    return []


class WorkbenchJobController(QObject):
    """Submit workbench jobs and route watcher/result callbacks on the UI thread."""

    submitted = Signal(str, str)
    progress = Signal(str, float, str)
    finished = Signal(str, object)
    failed = Signal(str, str)

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
        self.failed.emit(str(pending.get("kind") or ""), f"任务{status}")

    def _on_job_failed(self, job_id: str, message: str) -> None:
        request_id = self._jobs.pop(str(job_id), "")
        pending = self._pending.pop(request_id, None) or {}
        if pending:
            self.failed.emit(str(pending.get("kind") or ""), explain_job_failure(message))
