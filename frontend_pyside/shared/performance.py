
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading
from time import perf_counter
from typing import Iterator

_ENABLED = os.environ.get("OPTICAL_PERF_LOG", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
_QUEUE: queue.Queue[dict | None] = queue.Queue(maxsize=4096)
_WRITER_STARTED = False
_WRITER_LOCK = threading.Lock()


def _log_path() -> Path:
    override = os.environ.get("OPTICAL_PERF_LOG_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    
    return Path(__file__).resolve().parents[2] / "logs" / "frontend_performance.jsonl"


def _writer_loop() -> None:
    path = _log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    while True:
        item = _QUEUE.get()
        try:
            if item is None:
                return
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
        finally:
            _QUEUE.task_done()


def _ensure_writer() -> None:
    global _WRITER_STARTED
    if not _ENABLED or _WRITER_STARTED:
        return
    with _WRITER_LOCK:
        if _WRITER_STARTED:
            return
        threading.Thread(
            target=_writer_loop,
            name="frontend-performance-writer",
            daemon=True,
        ).start()
        _WRITER_STARTED = True


def record_perf(name: str, elapsed_ms: float, **fields: object) -> None:
    if not _ENABLED:
        return
    _ensure_writer()
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "event": str(name),
        "elapsed_ms": round(float(elapsed_ms), 3),
        **fields,
    }
    try:
        _QUEUE.put_nowait(payload)
    except queue.Full:
        
        pass


@contextmanager
def perf_span(name: str, **fields: object) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        record_perf(name, (perf_counter() - started) * 1000.0, **fields)


def flush_perf() -> None:
    if _WRITER_STARTED:
        _QUEUE.join()


__all__ = ["flush_perf", "perf_span", "record_perf"]
