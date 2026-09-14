"""M4 TaskRunner：tool 节点 → 后端 HTTP 任务（scan/tolerance/optimization）。

链路（与 RefreshController 的 L2 同构）：
- submit(node, surface_rows)：build_payload 组装 base project +
  task_kind 专属参数 → POST /scan|/tolerance|/optimization /jobs；
- 提交响应 → job_watcher.subscribe(job_id)（WebSocket 优先、1s HTTP 兜底）；
- 进度事件 → node.set_progress；完成 → /jobs/{id}/result → node.set_task_result；
- 提交失败 / 任务失败 → node.set_task_failed（工具任务不回退进程内：
  scan/tolerance/optimization 属正式批量计算，按方案走后端任务通道）；
- 节点删除 → 在途任务 cancel + unsubscribe。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.canvas.engine_bridge import build_payload, form_state, restrict_payload
from frontend_pyside.features.canvas.model_node import coerce_bool
from frontend_pyside.features.machine_learning.dataset_configuration import build_dataset_parameters
from machine_learning.datasets.splitter import too_few_samples_message
from machine_learning.features.coupling_physics import paired_coupling_targets

_SUBMIT_KEY = "canvas.task.submit"
_RESULT_KEY = "canvas.task.result"
_CANCEL_KEY = "canvas.task.cancel"


def explain_job_failure(message: str) -> str:
    """Turn backend exception text into a next-step sentence a non-specialist can act on."""
    text = str(message or "").strip()
    if text.startswith("任务失败"):
        text = text.split("：", 1)[-1].strip() or text
    lowered = text.lower()
    if "train/validation/test" in lowered or "非空 train" in text:
        return too_few_samples_message()
    if "学不成" in text or "没法学习" in text:
        return text
    if "MODEL_FEATURE_MISSING" in text or "缺少特征" in text:
        return "预测失败：当前镜头组缺少该模型需要的特征，请使用训练时的镜头结构或重新训练。"
    if "MODEL_QUALITY_REJECTED" in text or "测试 R²" in text:
        return "预测失败：该模型测试质量未达标，请重新训练或换用测试 R² 大于 0 的模型。"
    if "MODEL_NOT_FOUND" in text or "找不到这个模型" in text:
        return "预测失败：找不到这个模型，请刷新模型列表或重新训练。"
    if "MODEL_PREDICTION_FAILED" in text or "模型预测失败" in text:
        return "预测失败：模型运行时发生错误，请检查模型与当前镜头组是否匹配；必要时重新训练。"
    if "internal server error" in lowered:
        return "预测失败：后端发生内部错误，请查看后端日志；若模型已失效请重新训练。"
    return f"任务失败：{text}" if text else "任务失败"

_TASK_ENDPOINTS = {
    "scan": ("scan", "/scan/jobs"),
    "tolerance": ("tolerance", "/tolerance/jobs"),
    "optimize": ("optimization", "/optimization/jobs"),
    "physical_inverse": ("optimization", "/optimization/jobs"),
    "ml_inverse": ("optimization", "/optimization/jobs"),
    "random_forest": ("training", "/training/jobs"),
    "xgboost_physics_residual": ("training", "/training/jobs"),
    "bilstm_structure_sequence": ("training", "/structure-models/bilstm/jobs"),
    "dataset": ("dataset", "/dataset/jobs"),
}


class TaskRunner(QObject):
    """画布 tool 节点的任务提交与进度路由（主线程事件驱动）。"""

    stateChanged = Signal(str, str)  # (level, note) 过程提示
    taskFinished = Signal(str, str)  # (node_id, kind) 任务成功完成

    def __init__(
        self,
        api_client=None,
        clients: dict[str, Any] | None = None,
        job_client=None,
        job_watcher=None,
        parent=None,
    ):
        super().__init__(parent)
        self._api = api_client
        self._clients = clients or {}
        self._job_client = job_client
        self._job_watcher = job_watcher

        self._pending: dict[str, dict[str, Any]] = {}  # node_id → 提交在途信息
        self._jobs: dict[str, str] = {}  # job_id → node_id
        self._nodes: dict[str, Any] = {}  # node_id → node 引用（弱引用语义：删除时清理）

        if self._api is not None:
            self._api.completed.connect(self._on_api_completed)
            self._api.failed.connect(self._on_api_failed)
        if self._job_watcher is not None:
            self._job_watcher.job_progress.connect(self._on_job_progress)
            self._job_watcher.job_completed.connect(self._on_job_completed)
            self._job_watcher.job_failed.connect(self._on_job_failed)

    # ---- 主线程接口 ---------------------------------------------------------

    def register(self, node) -> None:
        """节点加入画布时注册（taskRunRequested → submit）。"""
        self._nodes[str(node.node_id)] = node
        node.taskRunRequested.connect(self._on_run_requested)

    def unregister(self, node_id: str) -> None:
        """节点移除：在途任务取消 + 取消订阅。"""
        node_id = str(node_id)
        self._nodes.pop(node_id, None)
        pending = self._pending.pop(node_id, None)
        job_id = str(pending.get("job_id") or "") if pending else ""
        if job_id and self._job_client is not None:
            self._job_client.cancel(f"{_CANCEL_KEY}:{job_id}", job_id)
        if job_id and self._job_watcher is not None:
            self._job_watcher.unsubscribe(job_id)
        self._jobs.pop(job_id, None)

    def submit(self, node, surface_rows: list[dict[str, Any]]) -> bool:
        """构造 payload 并提交；返回是否已发起（False = 无可用客户端）。"""
        if self._api is None:
            node.set_task_failed("后端不可用（无 API 连接）")
            return False
        kind = str(getattr(node, "task_kind", ""))
        entry = _TASK_ENDPOINTS.get(kind)
        if entry is None:
            node.set_task_failed(f"未知任务类型：{kind}")
            return False
        client_name, _ = entry
        client = self._clients.get(client_name)
        if client is None:
            node.set_task_failed(f"后端客户端不可用：{client_name}")
            return False

        node_id = str(node.node_id)
        request_id = f"task-{kind}-{uuid4().hex[:8]}"
        config = getattr(node, "config", {}) or {}
        if kind in {"random_forest", "xgboost_physics_residual"} and not str(config.get("dataset_id", "")).strip():
            node.set_task_failed("请先在「数据与目标」中设置数据集 ID")
            return False
        if kind == "bilstm_structure_sequence" and not str(config.get("dataset_path", "")).strip():
            node.set_task_failed("请先在「序列与字段」中设置数据集路径")
            return False
        if kind == "ml_inverse" and not str(config.get("surrogate_model_id", "")).strip():
            node.set_task_failed("请先在「代理模型」中选择已采用的模型 ID")
            return False
        if kind == "dataset":
            project_context = getattr(node, "project_context", None)
            project = getattr(project_context, "project", None)
            if project is None:
                node.set_task_failed("数据集任务缺少镜头组项目")
                return False
            # 数据集基线必须与镜头组节点当前的完整表单一致；否则采样任务
            # 会悄悄退回旧版默认光源/接收端参数，表现为“下拉选了但没生效”。
            project_payload = serialize_project(
                project,
                form_state(getattr(project, "_canvas_form_config", {})),
            )
            parameters = build_dataset_parameters(project_payload)
            if not parameters:
                node.set_task_failed("当前项目没有可采样的曲率或厚度参数")
                return False
            validation = min(0.45, max(0.05, float(config.get("validation_ratio", 0.15))))
            test = min(0.15, max(0.05, validation))
            payload = {
                "dataset_name": f"frontend-{uuid4().hex[:8]}",
                "base_project": project_payload,
                "parameters": parameters,
                "targets": paired_coupling_targets([str(config.get("target", "coupling_efficiency"))]),
                "sample_count": int(config.get("sample_count", 50)),
                "sampling_method": str(config.get("sampling_method", "latin_hypercube")),
                "train_ratio": max(0.0, 1.0 - validation - test),
                "validation_ratio": validation,
                "test_ratio": test,
                "random_seed": int(config.get("random_seed", 42)),
                "precision": str(config.get("precision", "standard")),
            }
        elif kind == "bilstm_structure_sequence":
            payload = {}
        else:
            payload = build_payload(surface_rows, request_id)
            payload = restrict_payload(payload, ("coupling",))
        _augment_payload(payload, kind, config)

        node.set_submitting()
        self._pending[node_id] = {"kind": kind, "request_id": request_id, "job_id": ""}
        title = {
            "scan": "参数研究", "tolerance": "容差分析", "optimize": "自动优化",
            "physical_inverse": "物理反向设计", "ml_inverse": "代理模型反向预测",
            "random_forest": "随机森林训练", "xgboost_physics_residual": "XGBoost物理残差训练",
            "bilstm_structure_sequence": "BiLSTM训练",
            "dataset": "数据集生成",
        }.get(kind, kind)
        self.stateChanged.emit(kind, f"已提交{title}任务")
        if kind == "bilstm_structure_sequence" and hasattr(client, "submit_bilstm"):
            client.submit_bilstm(f"{_SUBMIT_KEY}:{node_id}", payload)
        else:
            client.submit(f"{_SUBMIT_KEY}:{node_id}", payload)
        return True

    # ---- 内部路由 -----------------------------------------------------------

    def _node(self, node_id: str):
        return self._nodes.get(str(node_id))

    def _on_run_requested(self, node_id: str) -> None:
        node = self._node(node_id)
        if node is None:
            return
        rows = None
        kind = str(getattr(node, "task_kind", ""))
        scene = node.scene()
        if scene is not None:
            lens = next(iter(scene.nodes_by_key("lens_editor")), None)
            if lens is not None and hasattr(lens, "surface_rows"):
                rows = lens.surface_rows()
        if rows is None and kind not in {"random_forest", "xgboost_physics_residual", "bilstm_structure_sequence"}:
            node.set_task_failed("画布中无镜头组数据源")
            return
        rows = rows or []
        self.submit(node, rows)

    # ---- HTTP 回调 ----------------------------------------------------------

    def _on_api_completed(self, key: str, data) -> None:
        base, _, token = str(key).partition(":")
        if base == _SUBMIT_KEY:
            node_id = token
            pending = self._pending.get(node_id)
            node = self._node(node_id)
            if pending is None or node is None:
                return
            job_id = str(data.get("job_id", "") or "") if isinstance(data, dict) else ""
            if not job_id:
                self._pending.pop(node_id, None)
                node.set_task_failed("后端未返回任务 ID")
                return
            pending["job_id"] = job_id
            self._jobs[job_id] = node_id
            node.set_job(job_id)
            if self._job_watcher is not None:
                self._job_watcher.subscribe(job_id)
            self.stateChanged.emit(pending["kind"], f"任务已受理：{job_id[:16]}")
        elif base == _RESULT_KEY:
            job_id = token
            node_id = self._jobs.pop(job_id, "")
            self._pending.pop(node_id, None)
            node = self._node(node_id)
            if node is None:
                return
            body = data if isinstance(data, dict) else {}
            result = dict(body.get("result", body))
            if callable(getattr(result, "get", None)):
                if str(result.get("status", "") or "") in {"failed", "cancelled"}:
                    node.set_task_failed(f"任务{result.get('status')}")
                    return
            node.set_task_result(result)
            self.taskFinished.emit(node_id, str(getattr(node, "task_kind", "") or ""))

    def _on_api_failed(self, key: str, message: str) -> None:
        base, _, token = str(key).partition(":")
        if base == _SUBMIT_KEY:
            node_id = token
            pending = self._pending.pop(node_id, None)
            node = self._node(node_id)
            if node is None:
                return
            node.set_task_failed(f"提交失败：{message}")
        elif base == _RESULT_KEY:
            job_id = token
            node_id = self._jobs.pop(job_id, "")
            self._pending.pop(node_id, None)
            node = self._node(node_id)
            if node is not None:
                node.set_task_failed(explain_job_failure(message))

    # ---- 任务事件（WebSocket / 轮询） ---------------------------------------

    def _on_job_progress(self, job_id: str, progress: float, stage: str) -> None:
        node = self._node(self._jobs.get(str(job_id), ""))
        if node is not None:
            node.set_progress(progress, stage)

    def _on_job_completed(self, job_id: str, status: str, metrics: dict) -> None:
        job_id = str(job_id)
        node_id = self._jobs.get(job_id, "")
        node = self._node(node_id)
        if node is None:
            return
        if status == "completed":
            if self._job_client is not None:
                self._job_client.get_result(f"{_RESULT_KEY}:{job_id}", job_id)
                return
            node.set_task_result({"status": "completed", "metrics": dict(metrics or {})})
            self._jobs.pop(job_id, None)
            self._pending.pop(node_id, None)
            self.taskFinished.emit(node_id, str(getattr(node, "task_kind", "") or ""))
        else:
            self._jobs.pop(job_id, None)
            self._pending.pop(node_id, None)
            node.set_task_failed(f"任务{status}")

    def _on_job_failed(self, job_id: str, message: str) -> None:
        job_id = str(job_id)
        node_id = self._jobs.pop(job_id, "")
        self._pending.pop(node_id, None)
        node = self._node(node_id)
        if node is not None:
            node.set_task_failed(explain_job_failure(message))


# ---- payload 组装（task_kind 专属字段） -------------------------------------

def _parameter_unit(path: str) -> str:
    text = str(path or "")
    if text == "source.wavelength_nm":
        return "nm"
    if "mode_field_diameter" in text:
        return "μm"
    if "tilt_" in text:
        return "°"
    return "mm"


def _augment_payload(payload: dict[str, Any], kind: str, config: dict[str, Any]) -> None:
    if kind == "scan":
        mode = {
            "一维扫描": "line_1d", "二维扫描": "grid_2d", "多参数采样": "multi_parameter_sampling",
        }.get(str(config.get("scan_mode", "一维扫描")), "line_1d")
        response = {
            "耦合效率": "coupling_efficiency", "RMS 光斑": "rms_spot_radius_um",
            "Strehl": "strehl_estimate_marechal", "边缘功率": "edge_power",
        }.get(str(config.get("response", "耦合效率")), str(config.get("response", "coupling_efficiency")))
        payload["scan_mode"] = mode
        payload["scan_parameters"] = [{
            "path": str(config.get("param_path", "surfaces[0].radius_mm")),
            "label": str(config.get("param_label", "")),
            "unit": _parameter_unit(str(config.get("param_path", ""))),
            "start": float(config.get("start", 4.6)),
            "stop": float(config.get("stop", 5.6)),
            "points": int(config.get("points", 81)),
        }]
        second = str(config.get("param_path2", "") or "")
        if second:
            payload["scan_parameters"].append({
                "path": second,
                "label": str(config.get("param_label2", second)),
                "unit": _parameter_unit(second),
                "start": float(config.get("start2", -2.0)),
                "stop": float(config.get("stop2", 2.0)),
                "points": int(config.get("points2", 41)),
            })
        payload["scan_response_metrics"] = [response]
        payload["scan_sampling_strategy"] = {
            "线性采样": "linear", "对数采样": "log", "自适应加密": "adaptive",
        }.get(str(config.get("scale", "线性采样")), "linear")
        payload["scan_options"] = {
            "include_baseline": bool(config.get("include_baseline", True)),
            "local_refine": bool(config.get("local_refine", True)),
        }
    elif kind == "tolerance":
        distribution_name = {
            "正态": "normal", "均匀": "uniform", "三角": "triangular",
        }.get(str(config.get("distribution", "正态")), "normal")

        def distribution(nominal: float, sigma: float) -> dict[str, Any]:
            if distribution_name == "normal":
                return {"name": "normal", "sigma": abs(float(sigma))}
            lower, upper = float(nominal) - abs(float(sigma)), float(nominal) + abs(float(sigma))
            value = {"name": distribution_name, "lower": lower, "upper": upper}
            if distribution_name == "triangular":
                value["mode"] = float(nominal)
            return value

        parameters = []
        for item in (config.get("params") or []):
            if isinstance(item, dict):
                path = str(item.get("path", "") or "")
                nominal = float(item.get("nominal", 0.0) or 0.0)
                sigma = abs(float(item.get("sigma", item.get("tolerance", 0.0)) or 0.0))
                enabled = bool(item.get("enabled", True))
                row_distribution = str(item.get("distribution_label", item.get("distribution", "")) or "")
                row_distribution = {
                    "normal": "正态", "uniform": "均匀", "triangular": "三角",
                }.get(row_distribution, row_distribution)
                row_name = {"正态": "normal", "均匀": "uniform", "三角": "triangular"}.get(row_distribution, distribution_name)
                row_value = distribution(nominal, sigma) if row_name == distribution_name else (
                    {"name": "normal", "sigma": sigma}
                    if row_name == "normal" else {
                        "name": row_name, "lower": nominal - sigma, "upper": nominal + sigma,
                        **({"mode": nominal} if row_name == "triangular" else {}),
                    }
                )
            else:
                values = list(item) if isinstance(item, (tuple, list)) else []
                path = str(values[0] if len(values) > 0 else "")
                nominal = float(values[2] if len(values) > 2 else 0.0)
                sigma = abs(float(values[3] if len(values) > 3 else 0.0))
                enabled = True
                row_value = distribution(nominal, sigma)
            if path:
                parameters.append({
                    "path": path,
                    "nominal": nominal,
                    "unit": _parameter_unit(path),
                    "distribution": row_value,
                    "enabled": enabled,
                })
        payload["tolerance_parameters"] = parameters
        payload["tolerance_sampling_method"] = {
            "LHS": "lhs", "Sobol": "sobol", "随机": "random",
        }.get(str(config.get("sampling", "LHS")), str(config.get("sampling", "lhs")))
        payload["tolerance_distribution"] = distribution_name
        payload["tolerance_sample_count"] = int(config.get("sample_count", 256))
        threshold = config.get("threshold_efficiency")
        if threshold is not None:
            payload["tolerance_threshold_efficiency"] = float(threshold)
        payload["tolerance_options"] = {
            "candidate": str(config.get("candidate", "当前系统")),
            "parameter_template": str(config.get("template", "优化参数 + 常用装调")),
            "include_deterministic_budget": bool(config.get("include_deterministic_sensitivity", True)),
        }
    elif kind in {"optimize", "physical_inverse", "ml_inverse"}:
        algorithm = str(config.get("algorithm", "智能全局搜索"))
        payload["opt_optimizer"] = {
            "贝叶斯粗搜": "bayesian", "差分进化粗搜": "differential_evolution",
        }.get(algorithm, "auto")
        payload["opt_variables"] = [
            {
                "path": str(config.get("param_path", "surfaces[0].radius_mm")),
                "label": str(config.get("param_label", "")),
                "unit": "mm",
                "lower_bound": float(config.get("lower", 4.0)),
                "upper_bound": float(config.get("upper", 6.5)),
                "initial_value": float(config.get("initial", 5.11)),
                "enabled": True,
            }
        ]
        if kind in {"physical_inverse", "ml_inverse"}:
            payload["opt_objectives"] = [{
                "metric": "coupling_efficiency",
                "goal": "target",
                "target_value": float(config.get("target_efficiency", 0.95)),
                "weight": 1.0,
            }]
        else:
            objective = str(config.get("objective", "最大化耦合效率"))
            if objective == "最小化 RMS 光斑":
                payload["opt_objectives"] = [{"metric": "rms_spot_radius_um", "goal": "minimize", "weight": 1.0}]
            elif objective == "多目标加权":
                payload["opt_objectives"] = [
                    {"metric": "coupling_efficiency", "goal": "maximize", "weight": 0.7},
                    {"metric": "rms_spot_radius_um", "goal": "minimize", "weight": 0.3},
                ]
            else:
                payload["opt_objectives"] = [{"metric": "coupling_efficiency", "goal": "maximize", "weight": 1.0}]
        payload["opt_max_iterations"] = int(config.get("max_iterations", 300))
        payload["opt_max_evaluations"] = int(config.get("max_iterations", 300))
        opt_options = {
            "multi_start": int(config.get("starts", 1) or 1),
            "fixed_evaluation_budget": True,
            "timeout_seconds": 1200,
            "algorithm": {
                "智能全局搜索": "smart_global", "贝叶斯粗搜": "bayesian_coarse", "差分进化粗搜": "differential_evolution",
            }.get(str(config.get("algorithm", "智能全局搜索")), "smart_global"),
            "variable_filter": str(config.get("variable_filter", "全部参数")),
            "variable_scale": str(config.get("variable_scale", "线性")),
            "convergence_tolerance": float(config.get("convergence_tolerance", 1e-6)),
        }
        if kind == "optimize" and bool(config.get("collimation_enabled", False)):
            surface_value = config.get("collimation_surface", "")
            payload["opt_constraints"] = [{
                "type": "collimation",
                "enabled": True,
                "after_surface_index": int(surface_value) if str(surface_value).strip().isdigit() else None,
                "evaluation_span_mm": float(config.get("collimation_span", 10.0)),
                "max_radius_change_fraction": float(config.get("collimation_radius_change", 2.0)) / 100.0,
                "max_normalized_curvature": float(config.get("collimation_curvature", 0.05)),
                "max_centroid_drift_fraction": float(config.get("collimation_centroid_drift", 1.0)) / 100.0,
                "max_axis_tilt_mrad": float(config.get("collimation_axis_tilt", 1.0)),
                "hard": True,
            }]
        if kind == "optimize":
            # These values used to exist only in the inspector.  Keep them in
            # the formal request so the optimisation service can reject an
            # infeasible candidate instead of merely displaying the controls.
            payload.setdefault("opt_options", {})["engineering_constraints"] = {
                "evaluation_plane": str(config.get("evaluation_plane", "光纤模场")),
                "max_system_length_mm": config.get("max_system_length_mm"),
                "min_edge_thickness_mm": config.get("min_edge_thickness_mm"),
                "min_center_thickness_mm": config.get("min_center_thickness_mm"),
                "min_air_gap_mm": config.get("min_air_gap_mm"),
                "aperture_within_mechanical": bool(config.get("aperture_within_mechanical", False)),
            }
        if kind == "physical_inverse":
            opt_options["mode"] = "physical_inverse_design"
        elif kind == "ml_inverse":
            opt_options.update({
                "mode": "ml_inverse_prediction",
                "surrogate_model_id": str(config.get("surrogate_model_id", "") or ""),
                "coarse_fraction": 0.88,
            })
        elif kind == "optimize":
            # 实验验证仍属于旧版优化工作流的一部分；保留其指标/参考选择，
            # 让后端或后续验证节点能读取，而不会在节点化时丢失。
            payload["validation_options"] = {
                "metric": str(config.get("validation_metric", "E003 耦合效率")),
                "reference_type": str(config.get("validation_reference", "实验数据")),
            }
        payload["opt_options"] = opt_options
    elif kind in {"random_forest", "xgboost_physics_residual"}:
        hyperparameters = {
            key: value for key, value in config.items()
            if key not in {"dataset_id", "target_name", "seed", "n_jobs"}
        }
        # UI 中 0 表示“不限制深度”，不能直接传给 sklearn。
        if kind == "random_forest" and int(hyperparameters.get("max_depth", 0) or 0) <= 0:
            hyperparameters.pop("max_depth", None)
        if kind == "random_forest" and hyperparameters.get("max_features") == "1.0":
            hyperparameters["max_features"] = 1.0
        if kind == "xgboost_physics_residual":
            # 开关必须按真布尔解析：文本框里的 "False" 在 Python 里仍是 True。
            if "early_stopping" in config:
                enabled = coerce_bool(config.get("early_stopping"), True)
                hyperparameters["early_stopping"] = enabled
                hyperparameters["early_stopping_rounds"] = (
                    int(config.get("patience", config.get("early_stopping_rounds", 20)) or 20)
                    if enabled
                    else 0
                )
        payload.update({
            "dataset_id": str(config.get("dataset_id", "")),
            "model_type": kind,
            "target_names": [str(config.get("target_name", "coupling_efficiency"))],
            "random_seed": int(config.get("seed", 42) or 42),
            "hyperparameters": hyperparameters,
        })
    elif kind == "bilstm_structure_sequence":
        payload.update({
            "dataset_path": str(config.get("dataset_path", "")),
            "system_id_column": str(config.get("system_id_column", "system_id")),
            "order_column": str(config.get("order_column", "element_index")),
            "element_type_column": str(config.get("element_type_column", "element_type")),
            "numeric_feature_columns": [item.strip() for item in str(config.get("numeric_feature_columns", "")).split(",") if item.strip()],
            "target_columns": [item.strip() for item in str(config.get("target_columns", "")).split(",") if item.strip()],
            "config": {
                key: value for key, value in config.items()
                if key not in {"dataset_path", "system_id_column", "order_column", "element_type_column", "numeric_feature_columns", "target_columns"}
            },
        })


__all__ = ["TaskRunner", "explain_job_failure"]
