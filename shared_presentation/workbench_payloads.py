"""Payload and error helpers shared by ordinary workbench jobs."""

from __future__ import annotations

from typing import Any

from machine_learning.datasets.splitter import too_few_samples_message


def explain_job_failure(message: str) -> str:
    """Turn backend exception text into an actionable user-facing message."""
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


def _parameter_unit(path: str) -> str:
    text = str(path or "")
    if text == "source.wavelength_nm":
        return "nm"
    if "mode_field_diameter" in text:
        return "μm"
    if "tilt_" in text:
        return "°"
    return "mm"


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """Parse checkbox values; ``"False"`` must not become true by truthiness."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and value != 0
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "是", "开启"}:
        return True
    if text in {"", "0", "false", "no", "off", "否", "关闭"}:
        return False
    return bool(default)


def _augment_payload(payload: dict[str, Any], kind: str, config: dict[str, Any]) -> None:
    """Add task-specific fields to an ordinary workbench request."""
    if kind == "scan":
        mode = {
            "一维扫描": "line_1d", "二维扫描": "grid_2d", "多参数采样": "lhs",
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
        if mode == 'lhs':
            payload['scan_options']['max_samples'] = int(config.get('points', 21))
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
        payload["opt_variables"] = [{
            "path": str(config.get("param_path", "surfaces[0].radius_mm")),
            "label": str(config.get("param_label", "")),
            "unit": "mm",
            "lower_bound": float(config.get("lower", 4.0)),
            "upper_bound": float(config.get("upper", 6.5)),
            "initial_value": float(config.get("initial", 5.11)),
            "enabled": True,
        }]
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
        if kind == "optimize":
            # The rail controls evaluations (up to 100000). Keep that budget;
            # the separate iteration field has a 5000 limit in the API contract.
            payload["opt_max_iterations"] = min(payload["opt_max_iterations"], 5000)
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
            opt_options["engineering_constraints"] = {
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
        if kind == "random_forest" and int(hyperparameters.get("max_depth", 0) or 0) <= 0:
            hyperparameters.pop("max_depth", None)
        if kind == "random_forest" and hyperparameters.get("max_features") == "1.0":
            hyperparameters["max_features"] = 1.0
        if kind == "xgboost_physics_residual" and "early_stopping" in config:
            enabled = _coerce_bool(config.get("early_stopping"), True)
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


__all__ = ["_augment_payload", "explain_job_failure"]
