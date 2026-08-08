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


def stable_progress_text(status: object, progress: object = 0.0, *, loading_result: bool = False) -> str:
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
    if key in {"running", "运行中", "取消请求中"}:
        return f"进度 {progress_fraction(progress):.0%}"
    
    fraction = progress_fraction(progress)
    return f"进度 {fraction:.0%}" if fraction > 0.0 else "等待中"


def terminal_progress(status: object, progress: object) -> int:
    key = str(status or "").strip().lower()
    percent = progress_percent(progress)
    if key in {"completed", "已完成"}:
        return 100
    if key in {"failed", "失败", "cancelled", "已取消", "not_converged", "未收敛"}:
        return min(percent, 99)
    return percent


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


__all__ = [
    "extract_error_message",
    "progress_fraction",
    "progress_percent",
    "stable_progress_text",
    "terminal_progress",
    "terminal_stage",
]
