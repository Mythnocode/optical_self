

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.optical_ml_app.jobs.event_bus import JobEventBus

_logger = logging.getLogger(__name__)

router = APIRouter()

_KEEPALIVE_SECONDS = 30.0
_SEND_TIMEOUT = 5.0


@router.websocket("/ws/jobs")
async def job_events(websocket: WebSocket) -> None:

    await websocket.accept()

    bus: JobEventBus = websocket.app.state.event_bus  
    bus.set_loop(asyncio.get_running_loop())

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    current_job_ids: list[str] = []
    cancel_event = asyncio.Event()

    async def drain_events() -> None:

        while not cancel_event.is_set():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await asyncio.wait_for(
                    websocket.send_json(event), timeout=_SEND_TIMEOUT
                )
            except (asyncio.TimeoutError, ConnectionError):
                cancel_event.set()
                return
            except Exception:
                _logger.exception("ws drain error")
                cancel_event.set()
                return
            finally:
                queue.task_done()

    async def read_control() -> None:

        nonlocal current_job_ids

        while not cancel_event.is_set():
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_KEEPALIVE_SECONDS
                )
            except asyncio.TimeoutError:
                try:
                    await asyncio.wait_for(
                        websocket.send_json({"type": "ping"}), timeout=_SEND_TIMEOUT
                    )
                except Exception:
                    cancel_event.set()
                    return
                continue
            except (WebSocketDisconnect, ConnectionResetError, ConnectionError):
                cancel_event.set()
                return

            try:
                data: dict[str, Any] = json.loads(raw or "{}")
            except json.JSONDecodeError:
                try:
                    await asyncio.wait_for(
                        websocket.send_json(
                            {"type": "error", "code": "BAD_JSON",
                             "message": "frame is not valid JSON"}
                        ),
                        timeout=_SEND_TIMEOUT,
                    )
                except Exception:
                    pass
                continue

            action = str(data.get("action", "")).strip().lower()

            if action == "subscribe":
                bus.unsubscribe_all(queue)
                job_ids = list(data.get("job_ids", []) or [])
                current_job_ids = [str(jid) for jid in job_ids if jid]
                if current_job_ids:
                    bus.subscribe(current_job_ids, queue)
                    _logger.debug(
                        "ws subscribed to %d job(s)", len(current_job_ids)
                    )

            elif action == "unsubscribe":
                bus.unsubscribe_all(queue)
                current_job_ids = []

            else:
                try:
                    await asyncio.wait_for(
                        websocket.send_json(
                            {"type": "error", "code": "UNKNOWN_ACTION",
                             "message": f"unknown action: {action!r}"}
                        ),
                        timeout=_SEND_TIMEOUT,
                    )
                except Exception:
                    pass

    
    
    drain_task = asyncio.create_task(drain_events())
    read_task = asyncio.create_task(read_control())

    try:
        done, pending = await asyncio.wait(
            [drain_task, read_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        
        
        
        
        
        for task in done:
            if task.cancelled():
                continue
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                continue
            if exc is not None:
                _logger.debug("ws task error: %s", exc)
    finally:
        cancel_event.set()
        for task in (drain_task, read_task):
            if not task.done():
                task.cancel()
        
        await asyncio.gather(drain_task, read_task, return_exceptions=True)
        bus.unsubscribe_all(queue)
