

from __future__ import annotations

from typing import NamedTuple

# Worker code reports computational progress only. 100% belongs to TaskManager
# after the result has been materialized, persisted and published successfully.
WORKER_PROGRESS_CEILING = 0.94


def worker_progress_fraction(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(WORKER_PROGRESS_CEILING, number))


class PartialResultMessage(NamedTuple):


    stage: str
    payload: object
    version: int = 1


class ProgressMessage(NamedTuple):


    progress: float
    stage: str
    completed_items: int = 0
    total_items: int = 1


class ProgressReporter:


    def __init__(self, callback):
        self._callback = callback

    def update(self, progress, stage, completed_items=0, total_items=1):
        self._callback(
            worker_progress_fraction(progress),
            stage,
            completed_items,
            total_items,
        )


class ScaledProgressReporter:
    """Map a child operation's 0..1 progress into a parent progress interval."""

    def __init__(self, parent, start: float, end: float, *, stage_prefix: str = ""):
        self._parent = parent
        self._start = float(max(0.0, min(1.0, start)))
        self._end = float(max(self._start, min(1.0, end)))
        self._prefix = str(stage_prefix or "").strip(".")

    def update(self, progress, stage, completed_items=0, total_items=1):
        if self._parent is None:
            return
        try:
            fraction = float(progress)
        except (TypeError, ValueError):
            fraction = 0.0
        fraction = max(0.0, min(1.0, fraction))
        mapped = self._start + (self._end - self._start) * fraction
        child_stage = str(stage or "").strip(".")
        if self._prefix and child_stage:
            child_stage = f"{self._prefix}.{child_stage}"
        elif self._prefix:
            child_stage = self._prefix
        self._parent.update(mapped, child_stage, completed_items, total_items)

    def partial(self, payload, *, stage="", version=1):
        publisher = getattr(self._parent, "partial", None)
        if not callable(publisher):
            return
        child_stage = str(stage or "").strip(".")
        if self._prefix and child_stage:
            child_stage = f"{self._prefix}.{child_stage}"
        elif self._prefix:
            child_stage = self._prefix
        try:
            publisher(payload, stage=child_stage, version=version)
        except TypeError:
            publisher(payload, stage=child_stage)


class PipeProgressReporter:


    def __init__(self, child_conn):
        self._conn = child_conn

    def update(self, progress, stage, completed_items=0, total_items=1):
        msg = ProgressMessage(
            worker_progress_fraction(progress),
            stage,
            completed_items,
            total_items,
        )
        try:
            self._conn.send(msg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  

    def partial(self, payload, *, stage="", version=1):
        try:
            self._conn.send(
                PartialResultMessage(str(stage), payload, max(1, int(version)))
            )
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
