

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

_PROGRESS_MIN_DELTA = 0.02       
_PROGRESS_MIN_INTERVAL = 0.2     


class JobEventBus:


    def __init__(self) -> None:
        self._subscriptions: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        
        self._throttle: dict[str, dict[str, Any]] = {}
        self._throttle_lock = threading.Lock()

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def subscribe(
        self, job_ids: list[str], queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        with self._lock:
            for job_id in job_ids:
                self._subscriptions.setdefault(job_id, set()).add(queue)

    def unsubscribe(
        self, job_ids: list[str], queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        with self._lock:
            for job_id in job_ids:
                subscribers = self._subscriptions.get(job_id)
                if subscribers is None:
                    continue
                subscribers.discard(queue)
                if not subscribers:
                    del self._subscriptions[job_id]

    def unsubscribe_all(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            empty: list[str] = []
            for job_id, subscribers in self._subscriptions.items():
                subscribers.discard(queue)
                if not subscribers:
                    empty.append(job_id)
            for job_id in empty:
                del self._subscriptions[job_id]

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def publish(self, job_id: str, event: dict[str, Any]) -> None:

        if not event:
            return

        event.setdefault("job_id", job_id)

        event_type = event.get("type", "")

        
        if event_type == "progress":
            if not self._should_emit_progress(job_id, event):
                return

        
        self._deliver(job_id, event)

        
        
        
        if event_type in {"completed", "failed", "cancelled"}:
            with self._throttle_lock:
                self._throttle.pop(str(job_id), None)

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def _deliver(self, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscriptions.get(job_id, set()))

        if not subscribers:
            return

        loop = self._loop
        if loop is None or not loop.is_running():
            return

        try:
            if loop is asyncio.get_running_loop():
                schedule = loop.call_soon
            else:
                schedule = loop.call_soon_threadsafe
        except RuntimeError:
            schedule = loop.call_soon_threadsafe

        for queue in subscribers:
            try:
                
                
                
                
                schedule(self._safe_queue_put, queue, dict(event))
            except Exception:
                _logger.debug(
                    "dropped event for job %s: queue closed", job_id
                )

    @staticmethod
    def _safe_queue_put(
        queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]
    ) -> None:
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass

        
        
        
        if str(event.get("type", "")) not in {"completed", "failed", "cancelled"}:
            return
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            return

    def _should_emit_progress(self, job_id: str, event: dict[str, Any]) -> bool:

        progress = float(event.get("progress", 0.0))
        stage = str(event.get("stage", ""))
        now = time.monotonic()

        with self._throttle_lock:
            state = self._throttle.get(job_id)

            if state is None:
                
                self._throttle[job_id] = {
                    "last_progress": progress,
                    "last_stage": stage,
                    "last_emit": now,
                }
                return True

            delta = abs(progress - float(state["last_progress"]))
            stage_changed = stage != state["last_stage"]
            elapsed = now - float(state["last_emit"])

            
            
            if (
                stage_changed
                or delta >= _PROGRESS_MIN_DELTA
                or elapsed >= _PROGRESS_MIN_INTERVAL
            ):
                state["last_progress"] = progress
                state["last_stage"] = stage
                state["last_emit"] = now
                return True

            return False
