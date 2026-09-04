
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from frontend_pyside.shared.display_names import parameter_label


def latest_optimization_task(task_context) -> dict | None:
    """Return the most recent completed *automatic optimisation* task only.

    Parameter scans and tolerance jobs share the same page but are not valid
    sources for a "current best plan".
    """
    tasks = list(getattr(task_context, "tasks", []) or [])
    for task in tasks:
        if str(task.get("status", "")) != "已完成":
            continue
        kind = str(task.get("kind", ""))
        name = str(task.get("name", ""))
        if "容差" in name or "扫描" in kind or "参数扫描" in name:
            continue
        if "优化" not in kind and "优化" not in name:
            continue
        result = task_context.result(str(task.get("id", "")), {})
        if isinstance(result, dict) and isinstance(result.get("best_variables"), dict) and result.get("best_variables"):
            return dict(task)
    return None


def latest_optimization_result(task_context) -> dict:
    task = latest_optimization_task(task_context)
    if not task:
        return {}
    result = task_context.result(str(task.get("id", "")), {})
    return dict(result) if isinstance(result, dict) else {}


def latest_optimization_reference(task_context, project_context=None) -> dict:
    task = latest_optimization_task(task_context)
    result = latest_optimization_result(task_context)
    if not task or not result:
        return {}
    metadata = dict(result.get("metadata", {}) or {})
    # Bind the reference to the revision at optimisation submission/completion.
    # Never overwrite it with the project's *current* revision, otherwise an old
    # optimum would masquerade as belonging to the new design.
    revision = str(task.get("project_revision", "") or metadata.get("project_revision", "") or "")
    return {
        "task_id": str(task.get("id", "") or ""),
        "job_id": str(task.get("job_id", result.get("job_id", "")) or ""),
        "result_id": str(result.get("request_id", result.get("result_id", "")) or ""),
        "project_revision": revision,
        "best_variables": dict(result.get("best_variables", {}) or {}),
        "source": "后端自动优化",
    }

def latest_tolerance_result(task_context) -> dict:
    for task in list(getattr(task_context, "tasks", []) or []):
        if "容差" not in str(task.get("name", "")):
            continue
        result = task_context.result(str(task.get("id", "")), {})
        if isinstance(result, dict) and result:
            return dict(result)
    return {}


def latest_explainability_result(task_context) -> dict:
    for task in list(getattr(task_context, "tasks", []) or []):
        page = str(task.get("page", ""))
        kind = str(task.get("kind", ""))
        if page != "explainability" and "解释" not in kind:
            continue
        result = task_context.result(str(task.get("id", "")), {})
        if isinstance(result, dict) and result:
            return dict(result)
    return {}


def humanize_parameter_name(name: str) -> str:
    return parameter_label(name)


def _importance_records(payload: dict) -> list[tuple[str, float]]:
    for key in (
        "global_importance",
        "global_feature_importance",
        "feature_importance",
        "feature_importances",
    ):
        raw = payload.get(key)
        if isinstance(raw, dict):
            return [
                (humanize_parameter_name(name), abs(float(value)))
                for name, value in raw.items()
                if isinstance(value, (int, float))
            ]
        if isinstance(raw, list):
            records: list[tuple[str, float]] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = item.get("feature") or item.get("name") or item.get("feature_name")
                value = (
                    item.get("mean_abs_shap")
                    if isinstance(item.get("mean_abs_shap"), (int, float))
                    else item.get("abs_shap_value", item.get("importance"))
                )
                if name and isinstance(value, (int, float)):
                    records.append((humanize_parameter_name(str(name)), abs(float(value))))
            if records:
                return records
    return []


def top_influences(task_context, registry_context, *, limit: int = 5) -> tuple[list[tuple[str, float]], str]:

    explainability = latest_explainability_result(task_context)
    records = _importance_records(explainability)
    if records:
        records.sort(key=lambda item: item[1], reverse=True)
        return records[:limit], "SHAP解释结果"

    model_id = str(getattr(registry_context, "current_model_id", "") or "")
    model = registry_context.model(model_id) if model_id else None
    if isinstance(model, dict):
        records = _importance_records(model)
        if records:
            records.sort(key=lambda item: item[1], reverse=True)
            return records[:limit], "注册模型重要性"

    result = latest_optimization_result(task_context)
    variables = result.get("best_variables", {})
    if isinstance(variables, dict) and variables:
        
        
        names = [humanize_parameter_name(name) for name in variables]
        weights = list(range(len(names), 0, -1))
        return list(zip(names[:limit], map(float, weights[:limit]))), "当前优化重点参数（非SHAP）"

    return [], "尚无解释结果"


def explain_factor(name: str) -> str:
    text = str(name or "")
    if "空气间隔" in text or "后间隔" in text or "厚度" in text:
        return "间隔变化会移动束腰和最佳焦面，并同时改变到达光纤端面的光斑尺寸与波前曲率。"
    if "轴向" in text or "离焦" in text:
        return "轴向位置决定光纤端面是否位于最佳焦面，偏离后通常同时产生尺寸失配和曲率失配。"
    if "曲率" in text:
        return "曲率决定聚焦能力和输出波前，变化会影响最终束腰位置、尺寸与像差。"
    if "偏移" in text:
        return "横向偏移使入射场中心与光纤模式中心分离，直接降低复场重叠。"
    if "倾角" in text or "角度" in text:
        return "角度误差主要引入线性相位梯度，即使光强外形接近也会降低耦合效率。"
    if "波长" in text:
        return "波长会改变衍射尺度、材料折射率和光纤模式尺寸，因此多波长性能需要联合复核。"
    if "数量" in text or "排列" in text or "类型" in text:
        return "镜片结构会改变光束状态的演化路径，候选结构必须经过独立正式仿真复核。"
    if "孔径" in text:
        return "有效孔径过小会引入截断和边缘能量损失，并可能改变最终光斑。"
    return "该参数与当前候选结果相关，建议结合参数关系图和完整仿真结果判断其物理作用。"


def current_model_quality(registry_context) -> dict[str, Any]:
    # “当前模型”只能是用户明确采用的模型。训练完成或刷新模型列表时，
    # 不能偷偷把列表第一项当成当前模型，否则模型分析、SHAP 和 AI 会
    # 把“最新模型”误认为“已经采用的模型”。
    model_id = str(getattr(registry_context, "current_model_id", "") or "")
    if not model_id:
        return {}
    model = registry_context.model(model_id)
    if not isinstance(model, dict) or not model:
        return {}
    metrics = dict(model.get("metrics", {}) or {})
    for key in ("r2", "mae", "rmse", "high_efficiency_mae", "created_at", "model_type", "name"):
        if key in model and key not in metrics:
            metrics[key] = model[key]
    metrics["model_id"] = str(model.get("model_id", model.get("id", "")) or "")
    metrics["feature_count"] = len(model.get("feature_paths", []) or [])
    metrics["target_names"] = list(model.get("target_names", []) or [])
    metrics["test_metrics"] = dict(model.get("test_metrics", {}) or {})
    metrics["validation_metrics"] = dict(model.get("validation_metrics", {}) or {})
    metrics["evaluation"] = dict(model.get("evaluation", {}) or {})
    metrics["training_history"] = model.get("training_history")
    metrics["oob_error_curve"] = model.get("oob_error_curve")
    metrics["feature_paths"] = list(model.get("feature_paths", []) or [])
    return metrics


def research_profile_text(profile: dict) -> str:
    if not profile:
        return "尚未设置研究。请先在“研究与优化”中选择研究对象和内容。"
    contents = list(profile.get("contents", []) or [])
    content_text = "、".join(humanize_parameter_name(item) for item in contents) or "未选择"
    return (
        f"研究对象：{profile.get('structure', '—')}\n"
        f"研究内容：{content_text}\n"
        f"目标：{profile.get('goal', '—')}\n"
        f"研究范围：{profile.get('depth', '—')}"
    )


__all__ = [
    "current_model_quality",
    "explain_factor",
    "humanize_parameter_name",
    "latest_explainability_result",
    "latest_optimization_result",
    "latest_optimization_reference",
    "latest_optimization_task",
    "latest_tolerance_result",
    "research_profile_text",
    "top_influences",
]
