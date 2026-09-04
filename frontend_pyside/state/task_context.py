from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import logging
import re
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from frontend_pyside.shared.task_display import (
    extract_error_message,
    friendly_job_error,
    friendly_job_stage,
    progress_percent,
    terminal_progress,
    terminal_stage,
)


_TERMINAL_STATUSES = {"已完成", "已取消", "失败", "未收敛"}
_logger = logging.getLogger(__name__)


_BACKEND_STATUS_TEXT = {
    "queued": "等待后端",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


class TaskContext(QObject):


    tasks_changed = Signal(list)
    task_added = Signal(dict)
    task_updated = Signal(str, dict)
    task_removed = Signal(str)
    current_task_changed = Signal(str)
    task_result_changed = Signal(str, object)
    task_log_changed = Signal(str, list)
    backend_refresh_changed = Signal(bool)

    def __init__(self, usage_store=None, parent=None):
        super().__init__(parent)
        self._tasks: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._by_job_id: dict[str, str] = {}
        self._started: dict[str, float] = {}
        self._results: dict[str, object] = {}
        self._logs: dict[str, list[dict]] = defaultdict(list)
        self._last_log_fingerprint: dict[str, tuple[str, str, float]] = {}
        self._current_task_id = ""
        self.usage_store = usage_store
        self._backend_refreshed_at = 0.0
        self._backend_refreshing = False

    @property
    def tasks(self) -> list[dict]:
        return deepcopy(self._tasks)

    @property
    def current_task_id(self) -> str:
        return self._current_task_id

    @property
    def current_task(self) -> dict | None:
        task = self._by_id.get(self._current_task_id)
        return deepcopy(task) if task else None

    @property
    def active_count(self) -> int:
        return sum(str(item.get("status", "")) not in _TERMINAL_STATUSES for item in self._tasks)

    def should_refresh_backend(self, *, ttl_s: float = 3.0, force: bool = False) -> bool:
        if self._backend_refreshing:
            return False
        fresh = self._backend_refreshed_at > 0 and (
            monotonic() - self._backend_refreshed_at
        ) < max(0.0, float(ttl_s))
        if fresh and not force:
            return False
        self._backend_refreshing = True
        self.backend_refresh_changed.emit(True)
        return True

    def mark_backend_refresh_failed(self) -> None:
        self._backend_refreshing = False
        self.backend_refresh_changed.emit(False)

    def mark_backend_refreshed(self) -> None:
        self._backend_refreshed_at = monotonic()
        self._backend_refreshing = False
        self.backend_refresh_changed.emit(False)

    def add(
        self,
        name,
        kind,
        status="已完成",
        progress=100,
        note="",
        *,
        page="",
        duration_s=None,
        error_category="",
        job_id="",
        task_id: str = "",
    ) -> dict:
        task_id = str(task_id or uuid4().hex)
        normalized_status = self._normalize_status(status)
        normalized_progress = terminal_progress(normalized_status, self._normalize_progress(progress))
        error_message = str(note or "") if normalized_status in {"失败", "未收敛"} else ""
        task = {
            "id": task_id,
            "job_id": str(job_id or ""),
            "name": str(name),
            "kind": str(kind),
            "status": normalized_status,
            "progress": normalized_progress,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": str(note or ""),
            "page": str(page or ""),
            "duration_s": duration_s,
            "error_category": str(error_category or ""),
            "stage": terminal_stage(normalized_status, "") if normalized_status in _TERMINAL_STATUSES else "",
            "error_message": error_message,
            "error_code": "",
            "error_stage": "",
            "error_retryable": False,
            "error_context": {},
            "result_available": False,
            "retry_available": False,
            "retry_of": None,
            "last_activity_at": None,
        }
        if task["status"] not in _TERMINAL_STATUSES:
            self._started[task_id] = monotonic()
        self._tasks.insert(0, task)
        self._tasks = self._tasks[:500]
        self._reindex()
        self._record(task)
        self.task_added.emit(deepcopy(task))
        self.tasks_changed.emit(self.tasks)
        return deepcopy(task)

    def upsert_backend_job(self, job: dict) -> dict | None:
        if not isinstance(job, dict):
            return None
        job_id = str(job.get("job_id", "") or "")
        if not job_id:
            return None
        task = self.find_by_job_id(job_id)
        raw_status = str(job.get("status", "") or "")
        status = self._normalize_status(raw_status)
        raw_stage = str(job.get("stage", "") or "")
        progress = terminal_progress(raw_status or status, job.get("progress", 0))
        error_payload = job.get("error") if isinstance(job.get("error"), dict) else {}
        error_message = extract_error_message(job, "")
        friendly_error = friendly_job_error(job, error_message or "任务失败")
        normalized_stage = terminal_stage(raw_status or status, raw_stage)
        if status in {"失败", "未收敛"}:
            note = friendly_error or "任务失败"
        elif status == "已取消":
            note = error_message or str(job.get("note") or "任务已取消")
        elif status == "已完成":
            note = str(job.get("note") or "任务已完成")
        else:
            # Backend stages are machine-readable lifecycle identifiers.  The
            # task center should show the same human-facing stage wording as the
            # simulation page instead of leaking strings such as
            # ``optical_engine.trace.running`` into the progress detail.
            note = str(job.get("note") or friendly_job_stage(raw_stage) or raw_stage or "")
        changes = {
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "note": note,
            "stage": normalized_stage,
            "error_message": friendly_error if status in {"失败", "未收敛"} else error_message,
            "error_code": str(error_payload.get("code", "") or ""),
            "error_stage": str(error_payload.get("stage", "") or ""),
            "error_retryable": bool(error_payload.get("retryable", False)),
            "error_context": dict(error_payload.get("context") or {}),
            "result_available": bool(job.get("result_available", False)),
            "retry_available": bool(job.get("retry_available", False)),
            "retry_of": job.get("retry_of"),
            "last_activity_at": job.get("last_activity_at"),
        }
        if task is None:
            created = self.add(
                job.get("name") or f"后端任务 {job_id[:8]}",
                job.get("kind") or job.get("job_type") or "后端任务",
                status,
                progress,
                note or f"job_id: {job_id}",
                page=str(job.get("page", "")),
                job_id=job_id,
                task_id=f"remote:{job_id}",
            )
            
            
            return self.update_task(str(created.get("id", "")), **changes)
        return self.update_task(str(task.get("id", "")), **changes)

    def update_latest(self, **changes):
        if not self._tasks:
            return None
        return self.update_task(str(self._tasks[0].get("id", "")), **changes)

    def update_task(self, task_id: str, **changes):
        task = self._by_id.get(str(task_id or ""))
        if task is None:
            return None
        changed = self._apply_changes(task, changes)
        if not changed:
            return deepcopy(task)
        self._reindex()
        snapshot = deepcopy(task)
        self.task_updated.emit(str(task_id), snapshot)
        self.tasks_changed.emit(self.tasks)
        return snapshot

    def update_job(self, job_id: str, **changes):
        task_id = self._by_job_id.get(str(job_id or ""))
        if not task_id:
            return None
        changes.setdefault("job_id", str(job_id or ""))
        return self.update_task(task_id, **changes)

    def remove_task(self, task_id: str) -> bool:
        task_id = str(task_id or "")
        if task_id not in self._by_id:
            return False
        self._tasks = [item for item in self._tasks if str(item.get("id", "")) != task_id]
        self._results.pop(task_id, None)
        self._logs.pop(task_id, None)
        self._last_log_fingerprint.pop(task_id, None)
        self._started.pop(task_id, None)
        if self._current_task_id == task_id:
            self._current_task_id = ""
            self.current_task_changed.emit("")
        self._reindex()
        self.task_removed.emit(task_id)
        self.tasks_changed.emit(self.tasks)
        return True

    def find_by_job_id(self, job_id: str) -> dict | None:
        task_id = self._by_job_id.get(str(job_id or ""))
        task = self._by_id.get(task_id or "")
        return deepcopy(task) if task else None

    def find(self, task_id: str) -> dict | None:
        task = self._by_id.get(str(task_id or ""))
        return deepcopy(task) if task else None

    def set_current_task(self, task_id: str) -> None:
        task_id = str(task_id or "")
        if task_id and task_id not in self._by_id:
            return
        if task_id == self._current_task_id:
            return
        self._current_task_id = task_id
        self.current_task_changed.emit(task_id)

    def set_result(self, task_or_job_id: str, result: object) -> str:
        task_id = self._resolve_task_id(task_or_job_id)
        if not task_id:
            task_id = str(task_or_job_id or "")
        self._results[task_id] = result
        self.task_result_changed.emit(task_id, result)
        return task_id

    def result(self, task_or_job_id: str, default=None):
        task_id = self._resolve_task_id(task_or_job_id) or str(task_or_job_id or "")
        return self._results.get(task_id, default)

    def append_log(
        self,
        task_or_job_id: str,
        message: str,
        *,
        level: str = "INFO",
        timestamp: str = "",
        limit: int = 2000,
    ) -> None:
        task_id = self._resolve_task_id(task_or_job_id) or str(task_or_job_id or "")
        if not task_id:
            return
        normalized_level = str(level or "INFO").upper()
        normalized_message = str(message or "")
        stamp = monotonic()
        previous = self._last_log_fingerprint.get(task_id)
        if previous is not None and previous[0] == normalized_level and previous[1] == normalized_message and stamp - previous[2] <= 2.0:
            return
        self._last_log_fingerprint[task_id] = (normalized_level, normalized_message, stamp)
        entry = {
            "time": timestamp or datetime.now().strftime("%H:%M:%S"),
            "level": normalized_level,
            "message": normalized_message,
        }
        rows = self._logs[task_id]
        rows.append(entry)
        if len(rows) > max(1, int(limit)):
            del rows[: len(rows) - int(limit)]
        self.task_log_changed.emit(task_id, deepcopy(rows))

    def logs(self, task_or_job_id: str) -> list[dict]:
        task_id = self._resolve_task_id(task_or_job_id) or str(task_or_job_id or "")
        return deepcopy(self._logs.get(task_id, []))

    def reconcile_backend_jobs(self, jobs: list[dict]) -> None:

        self.mark_backend_refreshed()
        changed = False
        for job in jobs:
            before = self.find_by_job_id(str(job.get("job_id", ""))) if isinstance(job, dict) else None
            after = self.upsert_backend_job(job)
            if after is not None and after != before:
                changed = True
        if changed:
            
            
            self.tasks_changed.emit(self.tasks)

    @staticmethod
    def _normalize_status(value: object) -> str:
        text = str(value or "")
        return _BACKEND_STATUS_TEXT.get(text.lower(), text)

    @staticmethod
    def _normalize_progress(value: object) -> int:
        return progress_percent(value)

    @staticmethod
    def _task_job_id(task: dict) -> str:
        value = str(task.get("job_id", ""))
        if value:
            return value
        match = re.search(r"job_id:\s*([^\s,]+)", str(task.get("note", "")))
        return match.group(1) if match else ""

    def _resolve_task_id(self, task_or_job_id: str) -> str:
        value = str(task_or_job_id or "")
        if value in self._by_id:
            return value
        return self._by_job_id.get(value, "")

    def _apply_changes(self, task: dict, changes: dict) -> bool:
        normalized = dict(changes)
        allow_reset = bool(normalized.pop("allow_progress_reset", False))
        if "status" in normalized:
            normalized["status"] = self._normalize_status(normalized["status"])
        if "progress" in normalized:
            normalized["progress"] = self._normalize_progress(normalized["progress"])

        current_status = str(task.get("status", ""))
        incoming_status = str(normalized.get("status", current_status))
        
        
        
        if not allow_reset:
            if current_status in _TERMINAL_STATUSES and incoming_status not in _TERMINAL_STATUSES:
                # 终态之后到达的旧 queued/running 响应属于乱序网络事件。
                # 不仅状态/进度不能回退，所有与任务生命周期绑定的字段也不能
                # 覆盖已经确认的终态真值，否则会出现“仍显示已完成，但结果按钮
                # 悄悄失效”之类的静默状态漂移。
                for key in (
                    "status",
                    "progress",
                    "stage",
                    "note",
                    "error_message",
                    "error_code",
                    "error_stage",
                    "error_retryable",
                    "error_context",
                    "result_available",
                    "retry_available",
                    "retry_of",
                    "last_activity_at",
                ):
                    normalized.pop(key, None)
                incoming_status = current_status
            elif current_status in {"运行中", "取消请求中"} and incoming_status in {"等待后端", "排队中", "等待中"}:
                normalized.pop("status", None)
                incoming_status = current_status

            current_progress = self._normalize_progress(task.get("progress", 0))
            if "progress" in normalized and incoming_status not in _TERMINAL_STATUSES:
                normalized["progress"] = max(current_progress, int(normalized["progress"]))

            # 正式结果一旦被后端确认可用，同一 job 的较旧/重复状态不能把它
            # 从 True 降回 False。结果可用性与进度一样是单调事实。
            if bool(task.get("result_available", False)) and normalized.get("result_available") is False:
                normalized.pop("result_available", None)

        candidate_status = normalized.get("status", task.get("status", ""))
        candidate_progress = normalized.get("progress", task.get("progress", 0))
        # Every task display uses the same lifecycle reduction.  In particular,
        # running/persisting tasks are never allowed to render as 100%; 100 is
        # reserved for a confirmed completed state.
        if "progress" in normalized or "status" in normalized:
            normalized["progress"] = terminal_progress(candidate_status, candidate_progress)
        if str(candidate_status) in _TERMINAL_STATUSES:
            normalized["stage"] = terminal_stage(
                candidate_status,
                normalized.get("stage", task.get("stage", "")),
            )
            if str(candidate_status) in {"失败", "未收敛"}:
                error_message = str(
                    normalized.get("error_message", task.get("error_message", "")) or ""
                )
                if error_message:
                    normalized["note"] = error_message
        changed = any(task.get(key) != value for key, value in normalized.items())
        if not changed:
            return False
        task.update(normalized)
        status = str(task.get("status", ""))
        task_id = str(task.get("id", ""))
        if status in _TERMINAL_STATUSES and task.get("duration_s") is None:
            started = self._started.pop(task_id, None)
            if started is not None:
                task["duration_s"] = max(0.0, monotonic() - started)
        elif status not in _TERMINAL_STATUSES and task_id not in self._started:
            self._started[task_id] = monotonic()
        self._record(task)
        return True

    def _reindex(self) -> None:
        self._by_id = {str(item.get("id", "")): item for item in self._tasks}
        self._by_job_id = {}
        for item in self._tasks:
            job_id = self._task_job_id(item)
            if job_id:
                self._by_job_id[job_id] = str(item.get("id", ""))

    def _record(self, task: dict) -> None:
        if self.usage_store is None:
            return
        try:
            self.usage_store.record_task(task)
        except Exception:
            _logger.warning("任务已更新，但使用记录持久化失败。", exc_info=True)


__all__ = ["TaskContext"]
