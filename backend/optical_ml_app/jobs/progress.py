

from __future__ import annotations

from typing import NamedTuple


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
            float(max(0.0, min(1.0, progress))),
            stage,
            completed_items,
            total_items,
        )


class PipeProgressReporter:


    def __init__(self, child_conn):
        self._conn = child_conn

    def update(self, progress, stage, completed_items=0, total_items=1):
        msg = ProgressMessage(
            float(max(0.0, min(1.0, progress))),
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
