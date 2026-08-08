from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import weakref
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsagePaths:
    directory: Path
    events: Path
    summary: Path


def _default_usage_directory() -> Path:
    override = os.environ.get("OPTICAL_USAGE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.cwd() / "user_data" / "usage"


class UsageAnalyticsStore:


    def __init__(self, directory: Path | None = None):
        directory = directory or _default_usage_directory()
        self.paths = UsagePaths(
            directory=directory,
            events=directory / "usage_events.jsonl",
            summary=directory / "usage_summary.json",
        )
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._closed = False
        self._dropped_events = 0
        self._queue_limit = max(128, int(os.getenv("OPTICAL_USAGE_QUEUE_LIMIT", "4096")))
        self._max_file_bytes = max(
            1_048_576, int(os.getenv("OPTICAL_USAGE_MAX_FILE_BYTES", str(8 * 1024 * 1024)))
        )
        self._backup_count = max(1, int(os.getenv("OPTICAL_USAGE_BACKUP_COUNT", "3")))
        self._max_read_events = max(1_000, int(os.getenv("OPTICAL_USAGE_MAX_READ_EVENTS", "100000")))
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=self._queue_limit
        )
        owner_ref = weakref.ref(self)
        self._writer = threading.Thread(
            target=UsageAnalyticsStore._writer_loop_weak,
            args=(owner_ref, self._queue),
            name=f"frontend-usage-writer-{id(self):x}",
            daemon=True,
        )
        self._writer.start()
        
        
        
        self._finalizer = weakref.finalize(
            self, UsageAnalyticsStore._finalize_abandoned_writer,
            self._queue, self._writer,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _safe_text(value: Any, limit: int = 80) -> str:
        return str(value or "").replace("\n", " ").strip()[:limit]

    def record_task(self, task: dict[str, Any], event_type: str = "task_state") -> None:
        self._append(
            {
                "event_type": event_type,
                "timestamp": self._now(),
                "task_id": self._safe_text(task.get("id"), 64),
                "task_type": self._safe_text(task.get("kind"), 40) or "其他",
                "status": self._safe_text(task.get("status"), 30) or "未知",
                "page": self._safe_text(task.get("page"), 40),
                "duration_s": self._duration(task.get("duration_s")),
                "error_category": self._safe_text(task.get("error_category"), 50),
            }
        )

    def record_page_view(self, page: str) -> None:
        self._append(
            {
                "event_type": "page_view",
                "timestamp": self._now(),
                "page": self._safe_text(page, 40),
            }
        )

    @staticmethod
    def _duration(value: Any) -> float | None:
        try:
            number = float(value)
            return round(max(0.0, number), 4)
        except (TypeError, ValueError):
            return None

    def _append(self, payload: dict[str, Any]) -> None:
        
        
        with self._state_lock:
            if self._closed:
                return
        try:
            self._queue.put_nowait(dict(payload))
        except queue.Full:
            with self._state_lock:
                self._dropped_events += 1

    def _ensure_storage(self) -> None:
        self.paths.directory.mkdir(parents=True, exist_ok=True)
        if not self.paths.events.exists():
            self.paths.events.touch()
        if not self.paths.summary.exists():
            self._write_summary(self._empty_summary())

    def _rotated_path(self, index: int) -> Path:
        return self.paths.events.with_name(f"{self.paths.events.name}.{index}")

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        try:
            current_size = self.paths.events.stat().st_size
        except OSError:
            current_size = 0
        if current_size + incoming_bytes <= self._max_file_bytes:
            return
        oldest = self._rotated_path(self._backup_count)
        oldest.unlink(missing_ok=True)
        for index in range(self._backup_count - 1, 0, -1):
            source = self._rotated_path(index)
            if source.exists():
                os.replace(source, self._rotated_path(index + 1))
        if self.paths.events.exists():
            os.replace(self.paths.events, self._rotated_path(1))
        self.paths.events.touch()

    @staticmethod
    def _writer_loop_weak(
        owner_ref: "weakref.ReferenceType[UsageAnalyticsStore]",
        work_queue: queue.Queue[dict[str, Any] | None],
    ) -> None:
        while True:
            payload = work_queue.get()
            try:
                if payload is None:
                    return
                owner = owner_ref()
                if owner is None:
                    return
                line = json.dumps(payload, ensure_ascii=False) + "\n"
                encoded_size = len(line.encode("utf-8"))
                with owner._lock:
                    owner._ensure_storage()
                    owner._rotate_if_needed(encoded_size)
                    with owner.paths.events.open("a", encoding="utf-8") as stream:
                        stream.write(line)
                del owner
            except OSError:
                _logger.warning("无法写入本地使用统计", exc_info=True)
            finally:
                
                
                work_queue.task_done()

    @staticmethod
    def _finalize_abandoned_writer(
        work_queue: queue.Queue[dict[str, Any] | None],
        writer: threading.Thread,
    ) -> None:
        
        while True:
            try:
                work_queue.put_nowait(None)
                break
            except queue.Full:
                try:
                    work_queue.get_nowait()
                    work_queue.task_done()
                except queue.Empty:
                    break
        if writer.is_alive() and writer is not threading.current_thread():
            writer.join(timeout=0.5)

    def flush(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        condition = self._queue.all_tasks_done
        with condition:
            while self._queue.unfinished_tasks:
                if deadline is None:
                    condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                condition.wait(remaining)
        return True

    def close(self, timeout: float = 1.5) -> None:

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        flushed = self.flush(timeout=max(0.0, timeout * 0.65))
        if not flushed:
            
            
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return
        self._writer.join(timeout=max(0.0, timeout * 0.35))
        finalizer = getattr(self, "_finalizer", None)
        if finalizer is not None and finalizer.alive:
            finalizer.detach()

    def _event_files_oldest_first(self) -> list[Path]:
        files = [
            self._rotated_path(index)
            for index in range(self._backup_count, 0, -1)
            if self._rotated_path(index).is_file()
        ]
        if self.paths.events.is_file():
            files.append(self.paths.events)
        return files

    def read_events(self) -> list[dict[str, Any]]:
        
        self.flush(timeout=2.0)
        events: deque[dict[str, Any]] = deque(maxlen=self._max_read_events)
        with self._lock:
            try:
                self._ensure_storage()
                for path in self._event_files_oldest_first():
                    with path.open("r", encoding="utf-8") as stream:
                        for line in stream:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                item = json.loads(line)
                                if isinstance(item, dict):
                                    events.append(item)
                            except json.JSONDecodeError:
                                continue
            except OSError:
                _logger.warning("无法读取本地使用统计", exc_info=True)
                return []
        return list(events)

    @staticmethod
    def _parse_time(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def latest_tasks(self) -> list[dict[str, Any]]:
        return self.latest_tasks_from(self.read_events())

    def build_summary(self, days: int = 30) -> dict[str, Any]:
        events = self.read_events()
        tasks = self.latest_tasks_from(events)
        now = datetime.now().astimezone()
        start = now - timedelta(days=max(1, days) - 1)
        recent = [
            e
            for e in tasks
            if (
                self._parse_time(str(e.get("timestamp")))
                or datetime.min.replace(tzinfo=now.tzinfo)
            )
            >= start.replace(hour=0, minute=0, second=0, microsecond=0)
        ]
        page_events = [e for e in events if e.get("event_type") == "page_view"]

        statuses = Counter(str(e.get("status") or "未知") for e in recent)
        kinds = Counter(str(e.get("task_type") or "其他") for e in recent)
        page_counts = Counter(str(e.get("page") or "未知") for e in page_events)
        durations = [
            float(e["duration_s"])
            for e in recent
            if isinstance(e.get("duration_s"), (int, float))
            and float(e["duration_s"]) > 0
        ]
        errors = Counter(
            str(e.get("error_category") or "未分类")
            for e in recent
            if str(e.get("status")) == "失败"
        )
        duration_by_kind = defaultdict(list)
        for event in recent:
            if (
                isinstance(event.get("duration_s"), (int, float))
                and float(event["duration_s"]) > 0
            ):
                duration_by_kind[str(event.get("task_type") or "其他")].append(
                    float(event["duration_s"])
                )
        completed = statuses.get("已完成", 0)
        total = len(recent)
        active = sum(statuses.get(s, 0) for s in ("运行中", "等待后端", "排队中"))
        failures = statuses.get("失败", 0)
        today = now.date()
        today_count = sum(
            1
            for e in recent
            if (self._parse_time(str(e.get("timestamp"))) or now).date() == today
        )

        daily = defaultdict(int)
        daily_duration = defaultdict(float)
        for event in recent:
            dt = self._parse_time(str(event.get("timestamp")))
            if not dt:
                continue
            key = dt.date().isoformat()
            daily[key] += 1
            if isinstance(event.get("duration_s"), (int, float)):
                daily_duration[key] += float(event["duration_s"])

        labels: list[str] = []
        counts: list[int] = []
        durations_by_day: list[float] = []
        for offset in range(max(1, days) - 1, -1, -1):
            day = (now - timedelta(days=offset)).date().isoformat()
            labels.append(day[5:])
            counts.append(daily.get(day, 0))
            durations_by_day.append(round(daily_duration.get(day, 0.0), 3))

        with self._state_lock:
            dropped = self._dropped_events
        return {
            "generated_at": self._now(),
            "has_real_data": bool(tasks or page_events),
            "period_days": days,
            "today_tasks": today_count,
            "total_tasks": total,
            "completed": completed,
            "completion_rate": round(100.0 * completed / total, 1) if total else None,
            "failures": failures,
            "active": active,
            "average_duration_s": round(sum(durations) / len(durations), 3)
            if durations
            else None,
            "max_duration_s": round(max(durations), 3) if durations else None,
            "total_duration_s": round(sum(durations), 3),
            "status_counts": dict(statuses),
            "kind_counts": dict(kinds),
            "page_counts": dict(page_counts),
            "error_counts": dict(errors),
            "average_duration_by_kind": {
                key: round(sum(values) / len(values), 3)
                for key, values in duration_by_kind.items()
                if values
            },
            "max_duration_by_kind": {
                key: round(max(values), 3)
                for key, values in duration_by_kind.items()
                if values
            },
            "daily_labels": labels,
            "daily_task_counts": counts,
            "daily_duration_s": durations_by_day,
            "dropped_events": dropped,
            "events_file": str(self.paths.events),
            "summary_file": str(self.paths.summary),
        }

    @staticmethod
    def latest_tasks_from(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            if event.get("event_type") != "task_state":
                continue
            task_id = str(event.get("task_id") or "")
            if task_id:
                latest[task_id] = event
        return list(latest.values())

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "generated_at": None,
            "has_real_data": False,
            "period_days": 30,
            "today_tasks": 0,
            "total_tasks": 0,
            "completed": 0,
            "completion_rate": None,
            "failures": 0,
            "active": 0,
            "average_duration_s": None,
            "max_duration_s": None,
            "total_duration_s": 0.0,
            "status_counts": {},
            "kind_counts": {},
            "page_counts": {},
            "error_counts": {},
            "average_duration_by_kind": {},
            "max_duration_by_kind": {},
            "daily_labels": [],
            "daily_task_counts": [],
            "daily_duration_s": [],
            "dropped_events": 0,
        }

    def _write_summary(self, summary: dict[str, Any]) -> None:
        try:
            self.paths.directory.mkdir(parents=True, exist_ok=True)
            data = json.dumps(summary, ensure_ascii=False, indent=2)
            temporary = self.paths.summary.with_name(
                f".{self.paths.summary.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.paths.summary)
        except OSError:
            _logger.warning("无法写入使用统计摘要", exc_info=True)
            try:
                temporary.unlink(missing_ok=True)  
            except (OSError, UnboundLocalError):
                pass

    def summary(self, days: int = 30) -> dict[str, Any]:
        summary = self.build_summary(days)
        self._write_summary(summary)
        return summary
