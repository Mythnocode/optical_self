
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import multiprocessing as mp
import os
import queue
import threading
import time
import traceback
from typing import Any, Callable

from backend.optical_ml_app.jobs.cancellation import CancellationToken
from backend.optical_ml_app.jobs.progress import ProgressMessage, worker_progress_fraction
from backend.optical_ml_app.jobs.process_lifecycle import arm_parent_death_signal

_logger = logging.getLogger(__name__)


def _close_mp_queue(value: Any) -> None:

    try:
        value.cancel_join_thread()
    except (AttributeError, OSError, ValueError):
        pass
    try:
        value.close()
    except (AttributeError, OSError, ValueError):
        pass


class PersistentProgressReporter:


    def __init__(self, output_queue, worker_id: str, job_id: str) -> None:
        self._output_queue = output_queue
        self._worker_id = worker_id
        self._job_id = job_id

    def update(self, progress, stage, completed_items=0, total_items=1) -> None:
        try:
            self._output_queue.put(
                (
                    "progress",
                    self._worker_id,
                    self._job_id,
                    ProgressMessage(
                        worker_progress_fraction(progress),
                        str(stage),
                        int(completed_items),
                        max(1, int(total_items)),
                    ),
                )
            )
        except (BrokenPipeError, EOFError, OSError):
            pass

    def partial(self, payload: Any, *, stage: str = "") -> None:

        try:
            self._output_queue.put(
                ("partial", self._worker_id, self._job_id, str(stage), payload)
            )
        except (BrokenPipeError, EOFError, OSError):
            pass


class _WorkerContext:
    __slots__ = (
        "cancellation",
        "progress",
        "logger",
        "memory_budget_bytes",
        "resources",
    )

    def __init__(self, cancellation, progress, logger, resources) -> None:
        self.cancellation = cancellation
        self.progress = progress
        self.logger = logger
        self.memory_budget_bytes: int | None = None
        self.resources = resources

    def get_or_create_resource(self, name: str, factory: Callable[[], Any]) -> Any:
        key = str(name)
        if key not in self.resources:
            self.resources[key] = factory()
        return self.resources[key]


def _limit_native_threads(limit: int) -> None:
    text = str(max(1, int(limit)))
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        os.environ.setdefault(name, text)


def _prewarm(job_type: str, resources: dict[str, Any]) -> None:

    if job_type == "simulation":
        from optical_runtime import create_optical_simulation_engine

        resources["optical_engine"] = create_optical_simulation_engine()
    elif job_type in {"training", "bilstm_structure_training"}:
        
        import numpy  
        import pandas  
        import scipy  
        import sklearn  


def _background_numerical_prewarm(
    job_type: str,
    resources: dict[str, Any],
    user_job_seen: threading.Event | None = None,
) -> None:

    if job_type != "simulation":
        return
    try:
        
        
        
        
        time.sleep(0.45)
        if user_job_seen is not None and user_job_seen.is_set():
            return
        import numpy as np
        from optical_core.models.representations.grid import SamplingGrid2D
        from optical_core.physics.hybrid.operators.fiber_mode import gaussian_fiber_mode

        templates: dict[int, Any] = {}
        
        mfd_um = float(2.0 * 0.780 / (np.pi * 0.13))
        for size in (129, 257, 513):
            axis = np.linspace(-0.03, 0.03, size, dtype=np.float64)
            step = float(axis[1] - axis[0])
            grid = SamplingGrid2D(axis, axis.copy(), step, step)
            templates[size] = gaussian_fiber_mode(
                grid,
                wavelength_nm=780.0,
                mode_field_diameter_x_um=mfd_um,
                mode_field_diameter_y_um=mfd_um,
            )
            if size <= 257:
                np.fft.fft2(np.zeros((size, size), dtype=np.complex64))
        resources["common_780nm_na013_mode_templates"] = templates
        resources["common_grid_sizes"] = (129, 257, 513)
    except Exception:
        _logger.debug("background numerical prewarm skipped", exc_info=True)


def _persistent_worker_main(
    worker_id: str,
    job_type: str,
    input_queue,
    output_queue,
    cancel_event,
    function_loader: Callable[[bytes], Any],
    internal_thread_limit: int,
) -> None:
    arm_parent_death_signal()
    _limit_native_threads(internal_thread_limit)
    resources: dict[str, Any] = {}
    user_job_seen = threading.Event()
    prewarm_started = time.perf_counter()
    try:
        _prewarm(job_type, resources)
        output_queue.put(
            (
                "ready",
                worker_id,
                "",
                (time.perf_counter() - prewarm_started) * 1000.0,
            )
        )
        threading.Thread(
            target=_background_numerical_prewarm,
            args=(job_type, resources, user_job_seen),
            name=f"{worker_id}-background-prewarm",
            daemon=True,
        ).start()
    except Exception as exc:
        output_queue.put(
            (
                "bootstrap_error",
                worker_id,
                "",
                {
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
        )
        return

    logger = logging.getLogger(f"optical_ml.persistent_worker.{job_type}")
    while True:
        command = input_queue.get()
        if not command:
            continue
        if command[0] == "shutdown":
            return
        _, job_id, func_data, args, kwargs = command
        user_job_seen.set()
        cancel_event.clear()
        reporter = PersistentProgressReporter(output_queue, worker_id, job_id)
        context = _WorkerContext(
            CancellationToken(cancel_event), reporter, logger, resources
        )
        output_queue.put(("started", worker_id, job_id, time.perf_counter()))
        started = time.perf_counter()
        try:
            function = function_loader(func_data)
            reporter.update(0.02, "worker.ready", 0, 1)
            result = function(context, *args, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if context.cancellation.is_cancelled:
                output_queue.put(("cancelled", worker_id, job_id, elapsed_ms))
            else:
                output_queue.put(("result", worker_id, job_id, result, elapsed_ms))
        except Exception as exc:
            output_queue.put(
                (
                    "error",
                    worker_id,
                    job_id,
                    {
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                        "error_type": type(exc).__name__,
                    },
                    (time.perf_counter() - started) * 1000.0,
                )
            )


@dataclass
class _PendingJob:
    job_id: str
    job_type: str
    func_data: bytes
    args: tuple
    kwargs: dict
    timeout_seconds: float | None
    submitted_at: float = field(default_factory=time.perf_counter)
    terminal_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class _WorkerSlot:
    worker_id: str
    job_type: str
    input_queue: Any
    cancel_event: Any
    process: Any
    ready: bool = False
    current_job_id: str = ""
    started_at: float = 0.0
    prewarm_ms: float = 0.0


class PersistentTaskPool:


    def __init__(
        self,
        ctx,
        worker_counts: dict[str, int],
        callback: Callable[[str, str, Any], None],
        *,
        function_loader: Callable[[bytes], Any],
        internal_thread_limit: int = 1,
        monitor_interval: float = 0.1,
        start_job_types: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._ctx = ctx
        self._callback = callback
        self._function_loader = function_loader
        self._internal_thread_limit = max(1, int(internal_thread_limit))
        self._monitor_interval = max(0.02, float(monitor_interval))
        self._output_queue = ctx.Queue()
        self._lock = threading.RLock()
        self._ready_condition = threading.Condition(self._lock)
        self._closed = False
        self._slots: dict[str, _WorkerSlot] = {}
        self._groups: dict[str, list[str]] = {}
        self._pending: dict[str, deque[_PendingJob]] = {}
        self._worker_counts: dict[str, int] = {}
        self._jobs: dict[str, _PendingJob] = {}
        self._job_to_worker: dict[str, str] = {}

        for job_type, count in dict(worker_counts or {}).items():
            normalized = str(job_type)
            count = max(0, int(count))
            if count <= 0:
                continue
            self._worker_counts[normalized] = count
            self._groups[normalized] = []
            self._pending[normalized] = deque()

        self._monitor = threading.Thread(
            target=self._monitor_loop,
            name="persistent-task-pool-monitor",
            daemon=True,
        )
        self._monitor.start()
        selected = (
            set(self._worker_counts)
            if start_job_types is None
            else {str(item) for item in start_job_types}
        )
        self.start_groups(selected)

    @property
    def supported_job_types(self) -> frozenset[str]:
        return frozenset(self._groups)

    def supports(self, job_type: str) -> bool:
        return str(job_type) in self._groups

    def start_groups(self, job_types: set[str] | frozenset[str]) -> None:

        with self._lock:
            if self._closed:
                return
            for job_type in {str(item) for item in job_types}:
                count = int(self._worker_counts.get(job_type, 0))
                if count <= 0:
                    continue
                while len(self._groups.get(job_type, [])) < count:
                    self._spawn_slot(job_type, len(self._groups[job_type]))

    def wait_ready(
        self,
        *,
        job_types: set[str] | frozenset[str] | None = None,
        timeout: float | None = None,
    ) -> bool:

        selected = (
            {str(item) for item in job_types}
            if job_types is not None
            else set(self._groups)
        )
        selected &= set(self._groups)
        if not selected:
            return True
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._ready_condition:
            while not self._closed:
                slots = [
                    self._slots[worker_id]
                    for job_type in selected
                    for worker_id in self._groups.get(job_type, [])
                ]
                if slots and all(slot.ready for slot in slots):
                    return True
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        return False
                else:
                    remaining = None
                self._ready_condition.wait(timeout=remaining)
        return False

    def submit(
        self,
        job_id: str,
        job_type: str,
        func_data: bytes,
        args: tuple,
        kwargs: dict,
        timeout_seconds: float | None,
    ) -> None:
        self.start_groups({str(job_type)})
        pending = _PendingJob(
            job_id=str(job_id),
            job_type=str(job_type),
            func_data=func_data,
            args=tuple(args),
            kwargs=dict(kwargs),
            timeout_seconds=(
                None if timeout_seconds is None else float(timeout_seconds)
            ),
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("persistent task pool is closed")
            if pending.job_type not in self._groups:
                raise KeyError(pending.job_type)
            self._jobs[pending.job_id] = pending
            self._pending[pending.job_type].append(pending)
            self._dispatch_locked(pending.job_type)

    def cancel(
        self,
        job_id: str,
        *,
        grace_period: float,
        kill_period: float,
    ) -> str | None:
        job_id = str(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            pending_queue = self._pending.get(job.job_type, deque())
            for item in tuple(pending_queue):
                if item.job_id == job_id:
                    pending_queue.remove(item)
                    self._jobs.pop(job_id, None)
                    item.terminal_event.set()
                    return "queued"
            worker_id = self._job_to_worker.get(job_id)
            slot = self._slots.get(worker_id or "")
            if slot is None:
                return None
            slot.cancel_event.set()
            terminal_event = job.terminal_event

        if terminal_event.wait(timeout=max(0.0, float(grace_period))):
            return "running"

        with self._lock:
            worker_id = self._job_to_worker.get(job_id)
            slot = self._slots.get(worker_id or "")
            if slot is not None and slot.current_job_id == job_id:
                self._replace_slot_locked(slot, join_timeout=max(0.0, float(kill_period)))
                self._finish_job_locked(job_id, dispatch=True)
        return "running"

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "groups": {
                    job_type: {
                        "workers": len(worker_ids),
                        "configured_workers": int(self._worker_counts.get(job_type, 0)),
                        "ready": sum(
                            1 for worker_id in worker_ids
                            if self._slots[worker_id].ready
                        ),
                        "busy": sum(
                            1 for worker_id in worker_ids
                            if self._slots[worker_id].current_job_id
                        ),
                        "queued": len(self._pending[job_type]),
                        "prewarm_ms": [
                            round(self._slots[worker_id].prewarm_ms, 3)
                            for worker_id in worker_ids
                        ],
                    }
                    for job_type, worker_ids in self._groups.items()
                }
            }

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            slots = list(self._slots.values())
            for slot in slots:
                try:
                    slot.cancel_event.set()
                    slot.input_queue.put_nowait(("shutdown",))
                except Exception:
                    pass
            self._ready_condition.notify_all()
        for slot in slots:
            process = slot.process
            try:
                if wait:
                    process.join(timeout=2.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1.0)
                try:
                    process.close()
                except (OSError, ValueError):
                    pass
            except (OSError, ValueError, AssertionError):
                pass
            _close_mp_queue(slot.input_queue)
        if (
            wait
            and self._monitor is not threading.current_thread()
            and self._monitor.is_alive()
        ):
            self._monitor.join(timeout=2.0)
        _close_mp_queue(self._output_queue)

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def _spawn_slot(self, job_type: str, index: int) -> _WorkerSlot:
        worker_id = f"{job_type}-{index}"
        input_queue = self._ctx.Queue(maxsize=1)
        cancel_event = self._ctx.Event()
        process = self._ctx.Process(
            target=_persistent_worker_main,
            args=(
                worker_id,
                job_type,
                input_queue,
                self._output_queue,
                cancel_event,
                self._function_loader,
                self._internal_thread_limit,
            ),
            name=f"persistent-{worker_id}",
            daemon=True,
        )
        slot = _WorkerSlot(
            worker_id=worker_id,
            job_type=job_type,
            input_queue=input_queue,
            cancel_event=cancel_event,
            process=process,
        )
        self._slots[worker_id] = slot
        if worker_id not in self._groups.setdefault(job_type, []):
            self._groups[job_type].append(worker_id)
        process.start()
        return slot

    def _replace_slot_locked(self, slot: _WorkerSlot, *, join_timeout: float) -> None:
        old_process = slot.process
        try:
            if old_process.is_alive():
                old_process.terminate()
                old_process.join(timeout=join_timeout)
            if old_process.is_alive():
                old_process.kill()
                old_process.join(timeout=1.0)
            try:
                old_process.close()
            except (OSError, ValueError):
                pass
        except (OSError, ValueError, AssertionError):
            pass
        _close_mp_queue(slot.input_queue)

        worker_id = slot.worker_id
        input_queue = self._ctx.Queue(maxsize=1)
        cancel_event = self._ctx.Event()
        process = self._ctx.Process(
            target=_persistent_worker_main,
            args=(
                worker_id,
                slot.job_type,
                input_queue,
                self._output_queue,
                cancel_event,
                self._function_loader,
                self._internal_thread_limit,
            ),
            name=f"persistent-{worker_id}",
            daemon=True,
        )
        slot.input_queue = input_queue
        slot.cancel_event = cancel_event
        slot.process = process
        slot.ready = False
        slot.current_job_id = ""
        slot.started_at = 0.0
        slot.prewarm_ms = 0.0
        process.start()

    def _dispatch_locked(self, job_type: str) -> None:
        if self._closed:
            return
        pending = self._pending.get(job_type)
        if not pending:
            return
        for worker_id in self._groups.get(job_type, []):
            if not pending:
                break
            slot = self._slots[worker_id]
            if not slot.ready or slot.current_job_id:
                continue
            job = pending.popleft()
            if job.job_id not in self._jobs:
                continue
            slot.cancel_event.clear()
            slot.current_job_id = job.job_id
            slot.started_at = 0.0
            self._job_to_worker[job.job_id] = worker_id
            slot.input_queue.put(
                ("run", job.job_id, job.func_data, job.args, job.kwargs)
            )

    def _finish_job_locked(self, job_id: str, *, dispatch: bool) -> None:
        job = self._jobs.pop(str(job_id), None)
        worker_id = self._job_to_worker.pop(str(job_id), None)
        slot = self._slots.get(worker_id or "")
        job_type = job.job_type if job is not None else (slot.job_type if slot else "")
        if job is not None:
            job.terminal_event.set()
        if slot is not None and slot.current_job_id == str(job_id):
            slot.current_job_id = ""
            slot.started_at = 0.0
            try:
                slot.cancel_event.clear()
            except Exception:
                pass
        if dispatch and job_type:
            self._dispatch_locked(job_type)

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return
            try:
                message = self._output_queue.get(timeout=self._monitor_interval)
            except queue.Empty:
                self._check_timeouts()
                self._check_worker_health()
                continue
            try:
                self._handle_message(message)
            except Exception:
                _logger.exception("persistent worker message handling failed")
            self._check_timeouts()
            self._check_worker_health()

    def _handle_message(self, message: tuple) -> None:
        kind, worker_id, job_id, *payload = message
        callback_payload: Any = payload[0] if len(payload) == 1 else tuple(payload)
        terminal = kind in {"result", "error", "cancelled"}
        with self._lock:
            slot = self._slots.get(str(worker_id))
            if slot is None:
                return
            if kind == "ready":
                slot.ready = True
                slot.prewarm_ms = float(payload[0] if payload else 0.0)
                self._ready_condition.notify_all()
                self._dispatch_locked(slot.job_type)
            elif kind == "bootstrap_error":
                slot.ready = False
                self._ready_condition.notify_all()
            elif kind == "started":
                slot.started_at = time.perf_counter()
            elif job_id and slot.current_job_id != str(job_id):
                
                return

        if kind == "ready":
            self._callback("worker_ready", "", {
                "worker_id": worker_id,
                "job_type": slot.job_type,
                "prewarm_ms": slot.prewarm_ms,
            })
            return
        if kind == "bootstrap_error":
            self._callback("worker_bootstrap_error", "", callback_payload)
            return

        
        
        
        if terminal:
            with self._lock:
                self._finish_job_locked(str(job_id), dispatch=True)
        self._callback(str(kind), str(job_id), callback_payload)

    def _check_timeouts(self) -> None:
        timed_out: list[tuple[str, _WorkerSlot, float]] = []
        now = time.perf_counter()
        with self._lock:
            for job_id, worker_id in tuple(self._job_to_worker.items()):
                job = self._jobs.get(job_id)
                slot = self._slots.get(worker_id)
                if (
                    job is None
                    or slot is None
                    or slot.started_at <= 0.0
                    or job.timeout_seconds is None
                    or job.timeout_seconds <= 0.0
                ):
                    continue
                elapsed = now - slot.started_at
                if elapsed > job.timeout_seconds:
                    timed_out.append((job_id, slot, elapsed))
            for job_id, slot, _elapsed in timed_out:
                slot.cancel_event.set()
                self._replace_slot_locked(slot, join_timeout=0.5)
                self._finish_job_locked(job_id, dispatch=True)
        for job_id, _slot, elapsed in timed_out:
            self._callback("timeout", job_id, float(elapsed))

    def _check_worker_health(self) -> None:
        failed: list[tuple[str, str]] = []
        with self._lock:
            # ``shutdown()`` closes multiprocessing Process handles outside the
            # pool lock.  The monitor can already be between queue polling and
            # this health check; stop immediately once closure has started so a
            # late ``is_alive()`` cannot turn into a ValueError traceback.
            if self._closed:
                return
            for slot in tuple(self._slots.values()):
                try:
                    alive = slot.process.is_alive()
                except (OSError, ValueError, AssertionError):
                    # A worker handle may have been closed by an external
                    # shutdown/parent-death path.  Treat it as exited and let
                    # the normal replacement path decide whether recovery is
                    # still allowed.
                    alive = False
                if alive:
                    continue
                job_id = slot.current_job_id
                failed.append((slot.worker_id, job_id))
                if job_id:
                    self._finish_job_locked(job_id, dispatch=False)
                self._replace_slot_locked(slot, join_timeout=0.0)
            for job_type in self._groups:
                self._dispatch_locked(job_type)
        for worker_id, job_id in failed:
            if job_id:
                self._callback(
                    "worker_exit",
                    job_id,
                    {"worker_id": worker_id, "message": "persistent worker exited"},
                )


__all__ = ["PersistentProgressReporter", "PersistentTaskPool"]
