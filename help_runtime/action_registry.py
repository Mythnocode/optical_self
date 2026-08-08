from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .schemas import ActionSpec


ACTION_REGISTRY: dict[str, ActionSpec] = {
    "simulation.open_receiver": ActionSpec(
        id="simulation.open_receiver",
        title="打开接收器设置",
        page_id="simulation",
        section="receiver",
        description="进入仿真系统并定位光纤接收器参数。",
    ),
    "simulation.open_sampling_settings": ActionSpec(
        id="simulation.open_sampling_settings",
        title="打开采样设置",
        page_id="simulation",
        section="calculation",
        control_id="sampling_settings",
        description="进入仿真系统的计算与采样设置。",
    ),
    "simulation.open_formal_analysis": ActionSpec(
        id="simulation.open_formal_analysis",
        title="打开正式分析",
        page_id="simulation",
        tab="formal_analysis",
        description="进入正式仿真分析工作区。",
    ),
    "optimization.open_convergence": ActionSpec(
        id="optimization.open_convergence",
        title="打开收敛研究",
        page_id="optimization",
        tab="convergence",
        description="进入参数研究与优化页面的收敛模式。",
    ),
    "optimization.open_focus_scan": ActionSpec(
        id="optimization.open_focus_scan",
        title="打开焦面扫描",
        page_id="optimization",
        tab="scan",
        preset="focus_position",
        description="进入接收面位置扫描。",
    ),
    "optimization.open_alignment": ActionSpec(
        id="optimization.open_alignment",
        title="打开五轴对准",
        page_id="optimization",
        tab="optimization",
        preset="five_axis_alignment",
        description="进入五轴对准候选搜索。",
    ),
    "optimization.open_tolerance": ActionSpec(
        id="optimization.open_tolerance",
        title="打开容差分析",
        page_id="optimization",
        tab="tolerance",
        description="进入一维、二维或随机容差研究。",
    ),
    "machine_learning.open_dataset": ActionSpec(
        id="machine_learning.open_dataset",
        title="打开数据集",
        page_id="machine_learning",
        tab="dataset",
        description="查看数据字段、特征契约和数据范围。",
    ),
    "machine_learning.open_prediction": ActionSpec(
        id="machine_learning.open_prediction",
        title="打开模型预测",
        page_id="machine_learning",
        tab="prediction",
        description="进入模型预测与输入校验。",
    ),
    "explainability.open_shap": ActionSpec(
        id="explainability.open_shap",
        title="打开模型解释",
        page_id="explainability",
        tab="shap",
        description="进入 SHAP 和物理公式联动解释。",
    ),
    "tasks.open_current": ActionSpec(
        id="tasks.open_current",
        title="查看当前任务",
        page_id="tasks",
        description="查看任务状态、警告和错误。",
    ),
}


def get_action(action_id: str) -> ActionSpec | None:
    return ACTION_REGISTRY.get(action_id)


def resolve_actions(action_ids: list[str]) -> list[ActionSpec]:
    return [ACTION_REGISTRY[action_id] for action_id in action_ids if action_id in ACTION_REGISTRY]


def execute_help_action(
    action_id: str,
    navigate: Callable[[str], Any],
    apply_navigation_context: Callable[[dict[str, Any]], Any] | None = None,
) -> bool:


    action = get_action(action_id)
    if action is None:
        return False
    navigate(action.page_id)
    if apply_navigation_context is not None:
        apply_navigation_context(action.model_dump(exclude_none=True))
    return True
