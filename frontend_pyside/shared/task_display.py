from __future__ import annotations

from typing import Any

_TERMINAL = {"completed", "failed", "cancelled", "not_converged", "已完成", "失败", "已取消", "未收敛"}


def progress_fraction(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        number = 0.0
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))



def progress_percent(value: Any) -> int:

    return round(progress_fraction(value) * 100.0)


def extract_error_message(payload: dict | None, fallback: str = "任务失败") -> str:
    data = payload if isinstance(payload, dict) else {}
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "detail", "reason"):
            value = str(error.get(key, "") or "").strip()
            if value:
                return value
    elif error:
        return str(error)
    errors = data.get("errors") or []
    if isinstance(errors, (list, tuple)):
        values: list[str] = []
        for item in errors[:5]:
            if isinstance(item, dict):
                value = str(item.get("message", item.get("detail", item.get("reason", ""))) or "").strip()
            else:
                value = str(item).strip()
            if value:
                values.append(value)
        if values:
            return "；".join(values)
    for key in ("message", "detail", "reason"):
        value = str(data.get(key, "") or "").strip()
        if value:
            return value
    return str(fallback)



_JOB_ERROR_MESSAGES = {
    "BACKEND_RESTARTED": "后端在任务完成前发生了重启，本次任务没有产生正式结果。可以重新运行该任务。",
    "JOB_RESULT_NOT_AVAILABLE": "该任务没有可用的正式结果。",
    "QUEUE_TIMEOUT": "任务排队时间异常，长时间没有获得执行资源。",
    "WORKER_STALLED": "任务长时间没有新的工作进度，Worker 可能失去响应。",
    "WORKER_EXITED": "执行任务的 Worker 意外退出，本次任务未完成。",
    "WORKER_START_FAILED": "Worker 启动失败，本次任务未开始计算。",
    "TIMEOUT": "任务运行超过允许时间，已停止。",
    "RESULT_PERSIST_FAILED": "计算已结束，但结果保存失败。",
}

def friendly_job_error(payload: dict | None, fallback: str = "任务失败") -> str:
    data = payload if isinstance(payload, dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else data
    code = str(error.get("code", "") or "") if isinstance(error, dict) else ""
    if code in _JOB_ERROR_MESSAGES:
        return _JOB_ERROR_MESSAGES[code]
    return extract_error_message(data, fallback)

def stable_progress_text(status: object, progress: object = 0.0, *, loading_result: bool = False) -> str:
    """Human-facing lifecycle text from the same reduced progress used by bars.

    A non-terminal backend stage may legitimately report 1.0 while it is still
    persisting/materialising the result.  Rendering that as "100% 运行中" is
    contradictory, so all non-terminal display progress is capped at 99%.
    """
    key = str(status or "").strip().lower()
    if loading_result:
        return "正在加载结果"
    if key in {"submitting", "queued", "等待后端", "等待中", "排队中"}:
        return "等待中"
    if key in {"completed", "已完成"}:
        return "已完成"
    if key in {"failed", "失败", "not_converged", "未收敛"}:
        return "失败" if key not in {"not_converged", "未收敛"} else "未收敛"
    if key in {"cancelled", "已取消"}:
        return "已取消"
    percent = terminal_progress(status, progress)
    if key in {"running", "运行中", "取消请求中"}:
        return f"进度 {percent}%"
    return f"进度 {percent}%" if percent > 0 else "等待中"


def terminal_progress(status: object, progress: object) -> int:
    """Return display progress with 100 reserved for a confirmed completion."""
    key = str(status or "").strip().lower()
    percent = progress_percent(progress)
    if key in {"completed", "已完成"}:
        return 100
    # 100% means the lifecycle has reached its terminal success state.  Running,
    # persisting, cancelling and failure states keep their last real progress but
    # never visually claim completion.
    return min(percent, 99)


def friendly_job_stage(stage: object) -> str:
    """Translate backend lifecycle stages into stable user-facing wording."""
    text = str(stage or "").strip()
    if not text:
        return ""
    mapping = {
        "result.persisting": "正在保存结果",
        "result.materializing": "正在整理结果",
        "result.local_ready": "正式结果已生成，正在完成存档",
        "result.loading": "正在加载结果",
        "worker.starting": "正在启动计算",
        "worker.initializing": "正在初始化 Worker",
        "worker.ready": "Worker 已就绪",
        "queue.waiting": "正在等待计算资源",
        "optical_engine.compile": "正在校验并编译光学输入",
        "optical_engine.compiled": "光学输入编译完成",
        "optical_engine.graph_ready": "计算任务图已建立",
        "optical_engine.trace.running": "正在进行光线追迹",
        "optical_engine.trace.completed": "光线追迹完成",
        "optical_engine.finalizing": "正在整理正式计算结果",
        "optical_engine.multipath.finalizing": "正在整理多光路结果",
    }
    if text in mapping:
        return mapping[text]
    if text.startswith("optical_engine.analysis."):
        parts = text.split(".")
        analysis = parts[2] if len(parts) > 2 else "analysis"
        state = parts[-1] if len(parts) > 3 else "running"
        names = {
            "raytrace": "光线追迹分析",
            "coupling": "光纤耦合分析",
            "fiber_coupling": "光纤耦合分析",
            "mode_overlap": "模场重叠分析",
            "alignment_5axis": "五轴失配分析",
            "spot": "光斑分析",
            "spot_diagram": "光斑分析",
            "wavefront": "波前分析",
            "psf": "PSF 分析",
            "mtf": "MTF 分析",
        }
        label = names.get(analysis, analysis)
        return f"{label}完成" if state == "completed" else f"正在进行{label}"
    return text


def terminal_stage(status: object, stage: object = "") -> str:
    key = str(status or "").strip().lower()
    current = str(stage or "").strip()
    if key in {"completed", "已完成"}:
        return "completed"
    if key in {"failed", "失败", "not_converged", "未收敛"}:
        return "failed" if key not in {"not_converged", "未收敛"} else "not_converged"
    if key in {"cancelled", "已取消"}:
        return "cancelled"
    return current or key



class MonotonicProgress:
    """Per-job progress reducer used by pages with asynchronous backend stages.

    Backend progress can arrive as fractions or percents, can be duplicated/out-of-order,
    and several restored jobs may coexist.  The UI should never jump backwards for one job.
    """
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._terminal: set[str] = set()

    def reset(self, job_id: object) -> int:
        key = str(job_id or "")
        self._values[key] = 0
        self._terminal.discard(key)
        return 0

    def value(self, job_id: object, status: object, progress: object) -> int:
        key = str(job_id or "")
        raw = terminal_progress(status, progress)
        state = str(status or "").strip().lower()
        previous = self._values.get(key, 0)
        # 终态后若收到延迟/乱序的 running 事件，不允许 UI 重新回到运行态。
        if key in self._terminal and state not in {"completed", "已完成", "failed", "失败", "cancelled", "已取消", "not_converged", "未收敛"}:
            return previous
        if state in {"completed", "已完成"}:
            current = 100
        elif state in {"failed", "失败", "cancelled", "已取消", "not_converged", "未收敛"}:
            current = max(previous, min(raw, 99))
        else:
            current = max(previous, raw)
        current = max(0, min(100, int(current)))
        self._values[key] = current
        if state in {"completed", "已完成", "failed", "失败", "cancelled", "已取消", "not_converged", "未收敛"}:
            self._terminal.add(key)
        return current

    def forget(self, job_id: object) -> None:
        key = str(job_id or "")
        self._values.pop(key, None)
        self._terminal.discard(key)


__all__ = [
    "extract_error_message",
    "friendly_job_error",
    "progress_fraction",
    "progress_percent",
    "stable_progress_text",
    "terminal_progress",
    "terminal_stage",
    "friendly_job_stage",
    "MonotonicProgress",
]
