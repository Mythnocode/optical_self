

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Event as MultiprocessingEvent
from typing import Any

from shared_contracts.jobs import JobStatus
from backend.optical_ml_app.jobs.cancellation import CancellationToken


@dataclass
class JobRecord:


    status: JobStatus
    cancellation: CancellationToken
    result: Any | None = None
    live_result: Any | None = None
    partial_result: Any | None = None
    process: Any | None = None
    process_lock: Any = field(default_factory=threading.RLock, repr=False)
    monitor_thread: Any | None = None
    pipe: Connection | None = None
    semaphore: Any | None = None
    on_result: Any | None = None
    timeout_seconds: float | None = None
    _finalized: bool = False
    persistent: bool = False
    persistence_pending: bool = False
    submitted_perf: float = 0.0
    dispatched_perf: float = 0.0
    worker_started_perf: float = 0.0
    first_message_perf: float = 0.0
    last_status_persist_perf: float = 0.0
    last_status_persist_progress: float = -1.0
    last_status_persist_stage: str = ""

    def close_pipe(self) -> None:

        if self.pipe is not None:
            try:
                self.pipe.close()
            except OSError:
                pass
            finally:
                self.pipe = None

    def release_semaphore(self) -> None:

        if self.semaphore is not None:
            try:
                self.semaphore.release()
            except ValueError:
                pass  
            finally:
                self.semaphore = None
