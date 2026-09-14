from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


_TERMINAL = {"已完成", "已取消", "失败", "未收敛", "completed", "cancelled", "failed", "error"}
_RUNNING = {"运行中", "等待后端", "等待中", "running", "queued", "submitting"}


def _task_id(task: Mapping[str, Any]) -> str:
    return str(task.get("job_id") or task.get("id") or "")


def _status(task: Mapping[str, Any]) -> str:
    return str(task.get("status", "") or "")


def _progress(task: Mapping[str, Any]) -> int:
    try:
        value = float(task.get("progress", 0) or 0)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= value <= 1.0:
        value *= 100.0
    return max(0, min(100, int(round(value))))


def _matches(target: str, task: Mapping[str, Any]) -> bool:
    page = str(task.get("page", "") or "")
    name = str(task.get("name", "") or "")
    kind = str(task.get("kind", "") or "")
    target = str(target or "")
    if target == "simulation.formal":
        return page == "simulation" or "仿真" in kind or "仿真" in name
    if target == "optimization.scan":
        return page == "optimization" and ("扫描" in name or "参数研究" in kind)
    if target == "optimization.tolerance":
        return page == "optimization" and "容差" in name
    if target in {"optimization.variables", "optimization.variable_structure"}:
        return page == "optimization" and ("优化" in name or "参数研究" in kind)
    if target == "machine_learning.training":
        return page == "machine_learning" and ("训练" in name or "机器学习" in kind)
    return False


@dataclass(slots=True)
class GuidanceView:
    active: bool = False
    eyebrow: str = "当前建议"
    title: str = ""
    state: str = ""
    why: str = ""
    effect: str = ""
    action: dict[str, Any] = field(default_factory=dict)
    phase: str = "idle"
    job_id: str = ""


class GuidanceSession:
    """Deterministic continuity layer for assistant-led workflows.

    It does not execute scientific work.  It remembers the user's current goal,
    observes TaskContext, and turns real task transitions into the next visible
    instruction.  This is intentionally independent of any LLM.
    """

    def __init__(self) -> None:
        self.active = False
        self.target = ""
        self.action: dict[str, Any] = {}
        self.phase = "idle"
        self.job_id = ""
        self.seen_job_ids: set[str] = set()
        self.baseline_job_ids: set[str] = set()
        self.last_status = ""
        self.last_progress = 0
        self.last_transition_key = ""

    @property
    def expects_job(self) -> bool:
        return self.target in {
            "simulation.formal",
            "optimization.scan",
            "optimization.tolerance",
            "optimization.variables",
            "optimization.variable_structure",
            "machine_learning.training",
        }

    def begin(self, action: Mapping[str, Any], tasks: Iterable[Mapping[str, Any]]) -> None:
        payload = dict(action or {})
        target = str(payload.get("target", "") or "")
        if not target:
            return
        self.active = True
        self.target = target
        self.action = payload
        self.phase = "await_user" if self._action_can_continue(target) else "navigated"
        self.job_id = ""
        self.last_status = ""
        self.last_progress = 0
        self.last_transition_key = ""
        self.baseline_job_ids = {_task_id(row) for row in tasks if isinstance(row, Mapping) and _task_id(row)}
        self.seen_job_ids.update(self.baseline_job_ids)

    def stop(self) -> None:
        self.active = False
        self.phase = "idle"
        self.job_id = ""
        self.action = {}
        self.target = ""

    def observe(self, tasks: Iterable[Mapping[str, Any]]) -> tuple[GuidanceView | None, dict[str, Any] | None]:
        if not self.active:
            return None, None
        rows = [dict(row) for row in tasks if isinstance(row, Mapping)]

        # A completed scan can be followed by a user-triggered refinement without
        # another AI click.  Track every new matching job, not just the first one.
        candidates = [
            row for row in rows
            if _matches(self.target, row)
            and _task_id(row)
            and _task_id(row) not in self.seen_job_ids
        ]
        if candidates:
            row = candidates[0]
            self.job_id = _task_id(row)
            self.seen_job_ids.add(self.job_id)
            self.phase = "running"
            self.last_transition_key = ""

        current = None
        if self.job_id:
            current = next((row for row in rows if _task_id(row) == self.job_id), None)
        if current is not None:
            status = _status(current)
            progress = _progress(current)
            self.last_status = status
            self.last_progress = progress
            if status in _TERMINAL:
                self.phase = "completed" if status in {"已完成", "completed"} else "failed"
            elif status in _RUNNING or status:
                self.phase = "running"

        view = self.view(current)
        transition = None
        if current is not None and self.phase in {"completed", "failed"}:
            key = f"{self.job_id}:{self.phase}:{self.last_status}"
            if key != self.last_transition_key:
                self.last_transition_key = key
                transition = {
                    "phase": self.phase,
                    "target": self.target,
                    "job_id": self.job_id,
                    "task": dict(current),
                    "view": view,
                }
        return view, transition

    def view(self, current_task: Mapping[str, Any] | None = None) -> GuidanceView:
        if not self.active:
            return GuidanceView()
        action = dict(self.action)
        label = str(action.get("label") or "查看相关设置")
        if self.phase == "await_user":
            return GuidanceView(
                True,
                "持续指导 · 等待执行",
                self._goal_title(),
                "目标页面已经准备好。请检查设置并由你确认开始；AI 不会替你启动正式任务。",
                str(action.get("why") or "先完成这一步，后续建议才有新的真实结果作为依据。"),
                "开始后我会继续跟踪真实任务状态，完成或失败后自动给出下一步。",
                action,
                self.phase,
                self.job_id,
            )
        if self.phase == "running":
            status = self.last_status or "运行中"
            progress = self.last_progress
            return GuidanceView(
                True,
                "持续指导 · 正在执行",
                self._goal_title(),
                f"已跟踪真实任务 {self.job_id or '—'}：{status} · {progress}% 。",
                "当前先等待真实任务产生终态，不根据中间结果提前下结论。",
                "任务完成后，我会基于完成状态继续建议；失败时会转向错误恢复。",
                {"target": "tasks.current", "label": "查看当前任务", "level": "navigate"},
                self.phase,
                self.job_id,
            )
        if self.phase == "completed":
            title, state, why, effect, next_action = self._completed_content()
            return GuidanceView(True, "持续指导 · 已完成", title, state, why, effect, next_action, self.phase, self.job_id)
        if self.phase == "failed":
            return GuidanceView(
                True,
                "持续指导 · 需要处理",
                "这一步没有形成可用的正式结果",
                f"任务 {self.job_id or '—'} 的终态为：{self.last_status or '失败'}。",
                "失败任务不能作为后续科研结论的依据，应先查看错误原因并决定是否重试。",
                "打开任务中心查看错误码、保留进度和重试入口。",
                {"target": "tasks.current", "label": "查看失败任务", "level": "navigate"},
                self.phase,
                self.job_id,
            )
        return GuidanceView(
            True,
            "持续指导",
            self._goal_title(),
            "当前操作已定位。",
            str(action.get("why") or ""),
            str(action.get("what_happens_next") or "继续观察当前状态。"),
            action,
            self.phase,
            self.job_id,
        )

    def _completed_content(self) -> tuple[str, str, str, str, dict[str, Any]]:
        if self.target == "optimization.scan":
            return (
                "参数扫描已经完成",
                "扫描结果已成为当前 Guidance Session 的新证据。先看峰位、峰高、高效区和曲线形状，再决定是否细化。",
                "如果峰很尖或最佳点落在较窄区域，优先局部细化；如果最佳区域已经稳定，则可以进入容差分析。",
                "你可以在扫描页选择采样点继续细化；如果随后启动新的扫描，我会自动继续跟踪新的 job。",
                {"target": "optimization.scan", "label": "查看扫描结果", "level": "navigate"},
            )
        if self.target == "optimization.tolerance":
            return (
                "容差分析已经完成",
                "现在可以查看均值、离散程度、低分位和目标良率。",
                "工程可实现性应结合分布和良率判断，而不是只看名义峰值。",
                "查看容差结果后再决定是否应用候选或调整设计。",
                {"target": "optimization.tolerance", "label": "查看容差结果", "level": "navigate"},
            )
        if self.target == "simulation.formal":
            return (
                "正式仿真已经完成",
                "正式结果已经形成，可以查看当前设计的结果图和质量信息。",
                "后续分析应建立在这个正式结果上，而不是快速预览。",
                "进入仿真结果，按需打开需要的光路、PSF、复场或耦合图。",
                {"target": "simulation.current", "label": "查看正式结果", "level": "navigate"},
            )
        if self.target == "machine_learning.training":
            return (
                "模型训练已经完成",
                "先检查独立测试指标和训练域覆盖，再决定是否采用这个模型。",
                "训练完成不等于模型已经足够可靠；R²、RMSE、MAE 和训练域都需要一起看。",
                "打开模型质量区域检查结果；模型不会被 AI 自动设为当前模型。",
                {"target": "machine_learning.current", "label": "检查模型质量", "level": "navigate"},
            )
        return (
            "当前任务已经完成",
            "这一步已经形成新的结果。",
            "先检查结果，再决定下一项研究动作。",
            "返回对应页面查看结果。",
            dict(self.action),
        )

    def _goal_title(self) -> str:
        labels = {
            "simulation.formal": "完成当前系统的正式仿真",
            "optimization.scan": "完成参数扫描并根据结果继续研究",
            "optimization.tolerance": "评估当前系统的容差与良率",
            "optimization.variables": "完成参数优化",
            "optimization.variable_structure": "完成可变结构研究",
            "machine_learning.training": "训练并评估代理模型",
            "teaching.explore": "打开教学实验台",
            "teaching.mismatch": "打开教学实验台",
            "teaching.diagnosis": "打开教学实验台",
        }
        return labels.get(self.target, str(self.action.get("label") or "继续当前研究"))

    @staticmethod
    def _action_can_continue(target: str) -> bool:
        return bool(target)


__all__ = ["GuidanceSession", "GuidanceView"]
