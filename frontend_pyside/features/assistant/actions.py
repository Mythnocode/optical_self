from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


_TARGET_CONTROLS = {
    "simulation.formal": "formal_run",
    "simulation.current": "formal_result",
    "simulation.result": "formal_result",
    "simulation.focus": "result_canvas",
    "optimization.scan": "scan_parameter",
    "optimization.current": "research_settings",
    "optimization.variables": "optimization_variables",
    "optimization.variable_structure": "variable_structure",
    "optimization.tolerance": "tolerance",
    "optimization.validation": "validation",
    "machine_learning.training": "training_dataset",
    "machine_learning.current": "model_quality",
    "machine_learning.current_model": "model_quality",
    "explainability.current": "shap_result",
    "teaching.explore": "teaching_explorer",
    "teaching.mismatch": "teaching_mismatch",
    "teaching.diagnosis": "teaching_diagnosis",
    "teaching.concept": "teaching_concept",
    "teaching.phenomenon": "teaching_diagnosis",
    "tasks.current": "task_list",
}


@dataclass(frozen=True, slots=True)
class AssistantAction:
    """Structured, inspectable assistant action.

    The assistant may navigate and prepare UI state, but execution of expensive
    scientific work remains a user-confirmed page action.
    """

    action_id: str
    label: str
    target: str
    target_page: str
    target_control: str
    level: str = "navigate"
    prerequisites: tuple[str, ...] = ()
    current_state: str = ""
    expected_effect: str = ""
    requires_confirmation: bool = False
    changes_revision: bool = False
    starts_job: bool = False
    undoable: bool = True
    why: str = ""
    what_happens_next: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _page_for_target(target: str) -> str:
    return str(target or "").split(".", 1)[0]


def normalize_action(value: Mapping[str, Any] | None, *, why: str = "", expected_effect: str = "") -> dict[str, Any]:
    payload = dict(value or {})
    target = str(payload.get("target", "") or "")
    level = str(payload.get("level", "navigate") or "navigate")
    page = str(payload.get("target_page", "") or _page_for_target(target))
    control = str(payload.get("target_control", "") or _TARGET_CONTROLS.get(target, "page_root"))
    label = str(payload.get("label", "") or "去处理")
    action_id = str(payload.get("action_id", "") or target or label)

    payload.update({
        "action_id": action_id,
        "label": label,
        "target": target,
        "target_page": page,
        "target_control": control,
        "level": level,
        "prerequisites": tuple(str(item) for item in (payload.get("prerequisites") or ())),
        "current_state": str(payload.get("current_state", "") or ""),
        "expected_effect": str(payload.get("expected_effect", "") or expected_effect or _default_effect(target, level)),
        "requires_confirmation": bool(payload.get("requires_confirmation", level == "prepare")),
        "changes_revision": bool(payload.get("changes_revision", False)),
        "starts_job": bool(payload.get("starts_job", False)),
        "undoable": bool(payload.get("undoable", True)),
        "why": str(payload.get("why", "") or why),
        "what_happens_next": str(payload.get("what_happens_next", "") or _default_next(target, level)),
    })
    return payload


def _default_effect(target: str, level: str) -> str:
    if level == "prepare":
        return "打开目标页面并准备相关设置；不会自动开始耗时计算。"
    if target.startswith("teaching."):
        return "打开对应的可视化教学场景，不会修改正式项目。"
    return "打开目标页面并定位到相关内容。"


def _default_next(target: str, level: str) -> str:
    if level == "prepare":
        return "检查预填设置后，由你决定是否执行。"
    if target.startswith("teaching."):
        return "你可以自由改变参数、观察现象，再返回正式研究验证。"
    return "到达目标位置后继续查看当前状态。"


__all__ = ["AssistantAction", "normalize_action"]
