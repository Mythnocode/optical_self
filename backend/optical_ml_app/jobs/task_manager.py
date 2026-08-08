

from __future__ import annotations

import logging
import os
import multiprocessing as mp
import pickle
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from shared_contracts.errors import ApplicationError
from shared_contracts.jobs import JobStatus

from backend.optical_ml_app.domain.errors import BackendApplicationError
from backend.optical_ml_app.jobs.cancellation import CancellationToken
from backend.optical_ml_app.jobs.progress import PartialResultMessage, PipeProgressReporter, ProgressMessage
from backend.optical_ml_app.jobs.task_models import JobRecord
from backend.optical_ml_app.jobs.persistent_pool import PersistentTaskPool

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

GRACE_PERIOD = 5.0          
FORCE_KILL_PERIOD = 3.0     
PIPE_POLL_INTERVAL = 0.25   
HEARTBEAT_INTERVAL = 5.0    

_logger = logging.getLogger(__name__)

try:  
    import cloudpickle as _function_pickle
except ModuleNotFoundError:  
    _function_pickle = pickle


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_error(exc: Exception, stage: str) -> dict:

    if isinstance(exc, BackendApplicationError):
        return {
            "is_app_error": True,
            "code": exc.code,
            "stage": exc.stage,
            "message": exc.message,
            "retryable": exc.retryable,
        }
    return {
        "is_app_error": False,
        "code": "INTERNAL_ERROR",
        "stage": stage,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "retryable": False,
    }




def _result_field(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _semantic_result_status(result: Any) -> str:
    status = str(_result_field(result, "status", "completed") or "completed").lower()
    return status if status in {"completed", "failed", "cancelled"} else "completed"


def _result_application_error(result: Any, fallback_stage: str) -> ApplicationError | None:
    raw_errors = _result_field(result, "errors", []) or []
    if not raw_errors:
        return None
    raw = raw_errors[0]
    if isinstance(raw, ApplicationError):
        return raw
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, dict):
        return ApplicationError(
            code=str(raw.get("code", "SIMULATION_FAILED")),
            stage=str(raw.get("stage", fallback_stage) or fallback_stage),
            message=str(raw.get("message", "formal computation returned a failed result")),
            retryable=bool(raw.get("retryable", False)),
        )
    return ApplicationError(
        code="SIMULATION_FAILED",
        stage=fallback_stage,
        message=str(raw),
        retryable=False,
    )


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

class TaskExecutionContext:


    __slots__ = ("cancellation", "progress", "logger", "memory_budget_bytes", "resources")

    def __init__(
        self,
        cancellation: CancellationToken,
        progress: PipeProgressReporter,
        logger: logging.Logger,
    ) -> None:
        self.cancellation = cancellation
        self.progress = progress
        self.logger = logger
        self.memory_budget_bytes: int | None = None
        self.resources: dict[str, Any] = {}

    def get_or_create_resource(self, name: str, factory):
        key = str(name)
        if key not in self.resources:
            self.resources[key] = factory()
        return self.resources[key]


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

def _worker_target(
    conn,
    cancel_event,
    func_data: bytes,
    args: tuple,
    kwargs: dict,
) -> None:

    import logging as _logging
    import sys as _sys

    func = _function_pickle.loads(func_data)
    reporter = PipeProgressReporter(conn)
    token = CancellationToken(cancel_event)
    logger = _logging.getLogger("optical_ml.worker")

    context = TaskExecutionContext(token, reporter, logger)

    try:
        
        
        reporter.update(0.02, "worker.initializing", 0, 1)
        result = func(context, *args, **kwargs)
        if token.is_cancelled:
            conn.send(("_cancelled_",))
        else:
            conn.send(("_result_", result))
    except Exception as exc:
        _logger.exception("worker task failed")
        conn.send(("_error_", _serialize_error(exc, "worker")))
    finally:
        try:
            conn.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

class TaskManager:


    def __init__(
        self,
        repository,
        max_workers: int = 4,
        event_bus=None,
        *,
        persistent_workers: dict[str, int] | None = None,
        internal_thread_limit: int = 1,
    ) -> None:
        self.repository = repository
        self.max_workers = max_workers
        self.event_bus = event_bus

        
        
        
        self._ctx = mp.get_context("spawn")
        
        
        
        
        self._semaphore = threading.BoundedSemaphore(max_workers)

        self.records: dict[str, JobRecord] = {}
        self._queue: list[tuple[str, JobRecord, bytes, tuple, dict]] = []
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self._shutdown = False
        self._max_memory_records = max(32, int(os.getenv("OPTICAL_JOB_MEMORY_RECORDS", "256")))
        
        
        
        
        self._persistence_executor: ThreadPoolExecutor | None = None
        
        
        
        
        self._persistent_worker_counts = {
            str(name): max(0, int(count))
            for name, count in dict(persistent_workers or {}).items()
            if int(count) > 0
        }
        self._internal_thread_limit = max(1, int(internal_thread_limit))
        self._persistent_pool = None

    def __del__(self) -> None:
        
        
        try:
            self.shutdown(wait=False)
        except Exception:
            pass

    # ==================================================================
    
    # ==================================================================

    def start_persistent_workers(
        self,
        *,
        wait_ready: bool = False,
        ready_job_types: set[str] | frozenset[str] | None = None,
        timeout: float = 30.0,
    ) -> bool:

        with self._lock:
            if self._shutdown:
                return False
            existing_pool = self._persistent_pool
            worker_counts = dict(self._persistent_worker_counts)
        if existing_pool is not None:
            return (
                existing_pool.wait_ready(
                    job_types=ready_job_types, timeout=timeout
                )
                if wait_ready else True
            )
        if not worker_counts:
            return True
        pool = PersistentTaskPool(
            self._ctx,
            worker_counts,
            self._handle_persistent_message,
            function_loader=_function_pickle.loads,
            internal_thread_limit=self._internal_thread_limit,
            start_job_types=(
                set(worker_counts)
                if ready_job_types is None else set(ready_job_types)
            ),
        )
        with self._lock:
            if self._shutdown or self._persistent_pool is not None:
                pool.shutdown(wait=False)
                existing_pool = self._persistent_pool
                return bool(existing_pool is not None)
            self._persistent_pool = pool
        if wait_ready:
            return pool.wait_ready(job_types=ready_job_types, timeout=timeout)
        return True

    def submit(self, job_type: str, function, *args, **kwargs) -> str:

        on_result = kwargs.pop("on_result", None)
        timeout_seconds = kwargs.pop("timeout_seconds", None)
        job_id = "job-" + uuid.uuid4().hex[:12]
        status = JobStatus(
            job_id=job_id,
            job_type=job_type,
            status="queued",
            created_at=now(),
        )
        record = JobRecord(
            status=status,
            cancellation=CancellationToken(),
            on_result=on_result,
            timeout_seconds=timeout_seconds,
            submitted_perf=time.perf_counter(),
        )

        with self._lock:
            if self._shutdown:
                raise RuntimeError("task manager has been shut down")
            self.records[job_id] = record

        self.repository.save_status(status)
        
        
        
        self._publish_event(
            job_id,
            {
                "type": "queued",
                "status": "queued",
                "job_type": job_type,
            },
        )

        
        
        
        try:
            func_data = _function_pickle.dumps(function)
        except Exception as exc:
            self._mark_start_failure(job_id, record, exc, stage="worker.serialization")
            return job_id

        if job_type in self._persistent_worker_counts and self._persistent_pool is None:
            self.start_persistent_workers(ready_job_types={job_type})
        persistent_pool = self._persistent_pool
        if persistent_pool is not None and persistent_pool.supports(job_type):
            persistent_pool.start_groups({job_type})
            record.persistent = True
            try:
                persistent_pool.submit(
                    job_id,
                    job_type,
                    func_data,
                    args,
                    kwargs,
                    timeout_seconds,
                )
            except Exception as exc:
                self._mark_start_failure(
                    job_id, record, exc, stage="persistent_worker.submit"
                )
            return job_id

        if self._semaphore.acquire(False):
            record.semaphore = self._semaphore
            self._start_process(job_id, record, func_data, args, kwargs)
        else:
            with self._lock:
                self._queue.append((job_id, record, func_data, args, kwargs))

        return job_id

    def cancel(self, job_id: str) -> bool:

        record = self._lookup(job_id)
        if record is None:
            
            try:
                persisted = self.repository.load_status(job_id)
            except FileNotFoundError:
                return False
            if persisted.status in ("queued", "running"):
                self.logger.info(
                    "cancelling job %s via repository fallback (current status: %s)",
                    job_id, persisted.status,
                )
                persisted.status = "cancelled"
                persisted.finished_at = now()
                self.repository.save_status(persisted)
                self._publish_event(
                    job_id,
                    {"type": "cancelled", "status": "cancelled"},
                )
                return True
            
            return False

        status = record.status.status
        if status not in {"queued", "running"}:
            return False

        if record.persistent:
            record.cancellation.cancel()
            pool = self._persistent_pool
            if pool is None:
                return False
            mode = pool.cancel(
                job_id,
                grace_period=GRACE_PERIOD,
                kill_period=FORCE_KILL_PERIOD,
            )
            if mode is None:
                return False
            with self._lock:
                if record.status.status not in {"completed", "failed", "cancelled"}:
                    record.status.status = "cancelled"
                    record.status.finished_at = now()
                    record.status.stage = "cancelled"
                    record.status.timings_ms["backend_total"] = round(
                        (time.perf_counter() - record.submitted_perf) * 1000.0, 3
                    )
                    self.repository.save_status(record.status)
                record._finalized = True
            self._publish_event(
                job_id,
                {"type": "cancelled", "status": "cancelled"},
            )
            return True

        
        if status == "queued":
            removed = False
            with self._lock:
                before = len(self._queue)
                self._queue = [
                    item for item in self._queue if item[0] != job_id
                ]
                removed = len(self._queue) < before
            if removed:
                record.status.status = "cancelled"
                record.status.finished_at = now()
                self.repository.save_status(record.status)
                self._publish_event(
                    job_id,
                    {"type": "cancelled", "status": "cancelled"},
                )
                
                return True
            
            
            
            record.status.status = "running"

        
        record.cancellation.cancel()

        with record.process_lock:
            process = record.process
            if process is not None:
                try:
                    if process.is_alive():
                        process.join(timeout=GRACE_PERIOD)

                    if process.is_alive():
                        self.logger.warning(
                            "job %s did not respond to cooperative cancellation — terminating",
                            job_id,
                        )
                        process.terminate()
                        process.join(timeout=FORCE_KILL_PERIOD)

                        if process.is_alive():
                            self.logger.error(
                                "job %s survived terminate — sending kill",
                                job_id,
                            )
                            process.kill()
                            process.join(timeout=2.0)
                except (AssertionError, AttributeError, OSError, ValueError):
                    
                    
                    
                    pass

        
        
        
        self._reap_process(record, timeout=1.0, close_handle=True)

        
        with self._lock:
            
            
            
            if record.status.status not in ("completed", "failed", "cancelled"):
                record.status.status = "cancelled"
                record.status.finished_at = now()
                self.repository.save_status(record.status)

            
            
            record.close_pipe()

        self._publish_event(
            job_id,
            {"type": "cancelled", "status": "cancelled"},
        )
        self._finalize_job(record)
        return True

    def get_status(self, job_id: str) -> JobStatus:

        with self._lock:
            record = self.records.get(job_id)
        if record is not None:
            return record.status
        return self.repository.load_status(job_id)

    def get_result(self, job_id: str):

        status = self.get_status(job_id)
        if not status.result_available:
            raise RuntimeError("result not available")
        with self._lock:
            record = self.records.get(job_id)
        return (
            record.result
            if record and record.result is not None
            else self.repository.load_result(job_id)
        )

    def get_live_result_local(self, job_id: str):

        with self._lock:
            record = self.records.get(job_id)
            live = record.live_result if record is not None else None
        if live is None:
            self.get_status(job_id)
            raise RuntimeError("live result not available")
        if not isinstance(live, dict):
            return live
        response = dict(live)
        metadata = dict(response.get("metadata") or {})
        metadata["transport_job_id"] = str(job_id)
        response["metadata"] = metadata
        return response

    def get_result_summary(self, job_id: str):

        status = self.get_status(job_id)
        if not status.result_available:
            raise RuntimeError("result not available")
        loader = getattr(self.repository, "load_result_summary", None)
        if callable(loader):
            summary = loader(job_id)
            if isinstance(summary, dict):
                summary = dict(summary)
                summary["job_timings_ms"] = dict(status.timings_ms)
                summary["result_version"] = int(status.result_version)
                if status.metrics and not isinstance(summary.get("metrics"), dict):
                    summary["metrics"] = dict(status.metrics)
                return summary
            return summary
        result = self.get_result(job_id)
        if not isinstance(result, dict):
            return {"result": result}
        return {
            key: value for key, value in result.items()
            if key not in {"arrays", "predictions", "history", "shap"}
        }

    def get_result_analysis(self, job_id: str, analysis: str):

        status = self.get_status(job_id)
        if not status.result_available:
            raise RuntimeError("result not available")
        loader = getattr(self.repository, "load_result_analysis", None)
        if not callable(loader):
            result = self.get_result(job_id)
            if not isinstance(result, dict) or analysis not in result:
                raise KeyError(analysis)
            return result[analysis]
        return loader(job_id, analysis)

    def list_jobs(self, limit: int = 20, offset: int = 0, status: str | None = None, job_type: str | None = None) -> list[dict]:

        return self.repository.list_jobs(
            limit=limit,
            offset=offset,
            status_filter=status,
            job_type=job_type,
        )

    def shutdown(self, wait: bool = True) -> None:

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            job_ids = [
                jid for jid, r in self.records.items()
                if r.status.status in {"queued", "running"}
            ]
        
        for job_id in job_ids:
            try:
                self.cancel(job_id)
            except Exception:
                self.logger.exception("error during shutdown cancel of %s", job_id)

        persistent_pool = self._persistent_pool
        if persistent_pool is not None:
            try:
                persistent_pool.shutdown(wait=wait)
            except Exception:
                self.logger.exception("persistent worker pool shutdown failed")

        
        
        
        
        
        with self._lock:
            records = list(self.records.values())
        for record in records:
            if record.persistent:
                continue
            monitor = record.monitor_thread
            if (
                wait
                and monitor is not None
                and monitor is not threading.current_thread()
                and monitor.is_alive()
            ):
                monitor.join(timeout=2.0)
            self._reap_process(record, timeout=2.0 if wait else 0.0, close_handle=True)
            record.monitor_thread = None
        
        
        with self._lock:
            self.records.clear()
            self._queue.clear()
        persistence_executor = self._persistence_executor
        self._persistence_executor = None
        if persistence_executor is not None:
            persistence_executor.shutdown(wait=wait, cancel_futures=not wait)

    # ==================================================================
    
    # ==================================================================

    def persistent_pool_info(self) -> dict[str, Any]:
        pool = self._persistent_pool
        return pool.stats() if pool is not None else {"groups": {}}

    def _handle_persistent_message(
        self, kind: str, job_id: str, payload: Any
    ) -> None:

        if kind == "worker_ready":
            info = dict(payload or {})
            self.logger.info(
                "persistent worker ready: %s (%s), prewarm=%.1f ms",
                info.get("worker_id", ""),
                info.get("job_type", ""),
                float(info.get("prewarm_ms", 0.0) or 0.0),
            )
            return
        if kind == "worker_bootstrap_error":
            self.logger.error("persistent worker bootstrap failed: %s", payload)
            return

        record = self._lookup(job_id)
        if record is None:
            return
        now_perf = time.perf_counter()

        if kind == "started":
            with self._lock:
                if record.status.status != "queued":
                    return
                record.dispatched_perf = now_perf
                record.worker_started_perf = now_perf
                record.status.status = "running"
                record.status.progress = max(float(record.status.progress), 0.01)
                record.status.stage = f"{record.status.job_type}.starting"
                record.status.started_at = now()
                record.status.timings_ms["queue_wait"] = round(
                    (now_perf - record.submitted_perf) * 1000.0, 3
                )
                
                
                record.status.timings_ms["process_startup"] = 0.0
                self.repository.save_status(record.status)
            self._publish_event(
                job_id,
                {
                    "type": "running",
                    "status": "running",
                    "progress": record.status.progress,
                    "stage": record.status.stage,
                    "timings_ms": dict(record.status.timings_ms),
                },
            )
            return

        if record.status.status in {"completed", "failed", "cancelled"}:
            return

        if kind == "progress" and isinstance(payload, ProgressMessage):
            with self._lock:
                if record.first_message_perf <= 0.0:
                    record.first_message_perf = now_perf
                    if record.worker_started_perf > 0.0:
                        record.status.timings_ms["worker_ready_to_first_progress"] = round(
                            (now_perf - record.worker_started_perf) * 1000.0, 3
                        )
                record.status.progress = float(payload.progress)
                record.status.stage = str(payload.stage)
                record.status.completed_items = int(payload.completed_items)
                record.status.total_items = int(payload.total_items)
                self._persist_progress_status(record, at=now_perf)
            self._publish_event(
                job_id,
                {
                    "type": "progress",
                    "progress": payload.progress,
                    "status": record.status.status,
                    "stage": payload.stage,
                    "completed_items": payload.completed_items,
                    "total_items": payload.total_items,
                },
            )
            return

        if kind == "partial":
            stage, partial = payload if isinstance(payload, tuple) else ("", payload)
            data = dict(partial or {}) if isinstance(partial, dict) else {"value": partial}
            metrics = data.get("metrics")
            with self._lock:
                if isinstance(metrics, dict):
                    record.status.metrics.update(metrics)
                record.partial_result = data
                record.status.partial_result_available = True
                record.status.result_version += 1
                record.status.stage = str(stage or data.get("stage") or record.status.stage)
                self.repository.save_status(record.status)
                version = record.status.result_version
            self._publish_event(
                job_id,
                {
                    "type": "partial",
                    "status": record.status.status,
                    "progress": record.status.progress,
                    "stage": record.status.stage,
                    "result_version": version,
                    "partial": data,
                },
            )
            return

        if kind == "result":
            result, worker_elapsed_ms = payload
            with self._lock:
                if record.cancellation.is_cancelled or record.status.status == "cancelled":
                    return
                record.status.progress = max(0.98, float(record.status.progress))
                record.status.stage = "result.persisting"
                record.status.timings_ms["worker_compute"] = round(
                    float(worker_elapsed_ms), 3
                )
                metrics = _result_field(result, "metrics", {}) or {}
                if isinstance(metrics, dict):
                    record.status.metrics.update(metrics)
                self.repository.save_status(record.status)
            self._publish_event(
                job_id,
                {
                    "type": "progress",
                    "status": "running",
                    "progress": record.status.progress,
                    "stage": "result.persisting",
                    "metrics": dict(record.status.metrics),
                },
            )
            self._submit_result_persistence(job_id, record, result)
            return

        if kind in {"error", "worker_exit", "timeout"}:
            if kind == "timeout":
                error = ApplicationError(
                    code="TIMEOUT",
                    stage=record.status.stage or "persistent_worker",
                    message=f"job timed out after {record.timeout_seconds} s",
                    retryable=False,
                )
            else:
                raw = payload[0] if kind == "error" and isinstance(payload, tuple) else payload
                raw = dict(raw or {}) if isinstance(raw, dict) else {"message": str(raw)}
                error = ApplicationError(
                    code="WORKER_EXITED" if kind == "worker_exit" else "INTERNAL_ERROR",
                    stage=record.status.stage or "persistent_worker",
                    message=str(raw.get("message", "persistent worker failed")),
                    retryable=kind == "worker_exit",
                )
            with self._lock:
                if record.status.status in {"completed", "cancelled"}:
                    return
                record.status.status = "failed"
                record.status.error = error
                record.status.finished_at = now()
                record.status.stage = error.stage
                record.status.timings_ms["backend_total"] = round(
                    (now_perf - record.submitted_perf) * 1000.0, 3
                )
                self.repository.save_status(record.status)
                record._finalized = True
            self._publish_event(
                job_id,
                {
                    "type": "failed",
                    "status": "failed",
                    "error": error.model_dump(),
                    "timings_ms": dict(record.status.timings_ms),
                },
            )
            return

        if kind == "cancelled":
            with self._lock:
                if record.status.status not in {"completed", "failed", "cancelled"}:
                    record.status.status = "cancelled"
                    record.status.finished_at = now()
                    record.status.stage = "cancelled"
                    record.status.timings_ms["backend_total"] = round(
                        (now_perf - record.submitted_perf) * 1000.0, 3
                    )
                    self.repository.save_status(record.status)
                record._finalized = True
            self._publish_event(job_id, {"type": "cancelled", "status": "cancelled"})

    def _persist_completed_result(
        self, job_id: str, record: JobRecord, result: Any
    ) -> None:

        if record.cancellation.is_cancelled or record.status.status == "cancelled":
            return
        self._attach_simulation_job_metadata(record, result)
        self._attach_timing_metadata(record, result)
        save_started = time.perf_counter()
        try:
            self.repository.save_result(job_id, result)
        except Exception as exc:
            self.logger.exception("failed to persist result for %s", job_id)
            with self._lock:
                if record.status.status == "cancelled":
                    return
                record.persistence_pending = False
                record.status.status = "failed"
                record.status.finished_at = now()
                record.status.error = ApplicationError(
                    code="RESULT_PERSIST_FAILED",
                    stage="result.persisting",
                    message=str(exc),
                    retryable=True,
                )
                self.repository.save_status(record.status)
            self._publish_event(
                job_id,
                {
                    "type": "failed",
                    "status": "failed",
                    "error": record.status.error.model_dump(),
                },
            )
            return

        save_ms = (time.perf_counter() - save_started) * 1000.0
        if not record.persistent and not record.cancellation.is_cancelled:
            
            
            
            
            
            
            
            self._reap_completed_process(record)
        semantic_status = _semantic_result_status(result)
        callback = None
        with self._lock:
            if record.cancellation.is_cancelled or record.status.status == "cancelled":
                return
            record.persistence_pending = False
            
            
            
            
            record.result = None
            record.status.status = semantic_status
            record.status.progress = 1.0
            record.status.result_available = True
            record.status.partial_result_available = False
            record.status.result_version += 1
            record.status.finished_at = now()
            record.status.stage = semantic_status
            record.status.timings_ms["result_save"] = round(save_ms, 3)
            record.status.timings_ms["backend_total"] = round(
                (time.perf_counter() - record.submitted_perf) * 1000.0, 3
            )
            metrics = _result_field(result, "metrics", {}) or {}
            if isinstance(metrics, dict):
                record.status.metrics.update(metrics)
            if semantic_status == "failed":
                record.status.error = _result_application_error(
                    result, "simulation"
                )
            self.repository.save_status(record.status)
            callback = record.on_result if semantic_status == "completed" else None
            if record.persistent:
                record._finalized = True

        event: dict[str, Any] = {
            "type": semantic_status,
            "status": semantic_status,
            "progress": 1.0,
            "result_available": True,
            "result_version": record.status.result_version,
            "metrics": dict(record.status.metrics),
            "timings_ms": dict(record.status.timings_ms),
        }
        if record.status.error is not None:
            event["error"] = record.status.error.model_dump()
        self._publish_event(job_id, event)
        if callback is not None:
            try:
                callback(result)
            except Exception:
                self.logger.exception("on_result callback failed for %s", job_id)
        with self._lock:
            self._prune_terminal_records_locked()

    def _publish_local_live_result(
        self, job_id: str, record: JobRecord, result: Any
    ) -> None:

        looks_like_optical_result = bool(
            isinstance(result, dict)
            and ("arrays" in result or "metrics" in result or "metadata" in result)
        ) or bool(getattr(result, "arrays", None) is not None)
        creator = getattr(self.repository, "create_local_result_view", None)
        if not looks_like_optical_result or not callable(creator):
            with self._lock:
                record.result = result
            return
        started = time.perf_counter()
        try:
            live = creator(job_id, result)
        except Exception:
            self.logger.exception("failed to create local live result for %s", job_id)
            with self._lock:
                record.result = result
            return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        with self._lock:
            if record.cancellation.is_cancelled or record.status.status == "cancelled":
                return
            record.result = result
            record.live_result = live
            record.partial_result = {
                "live_result_available": True,
                "metrics": dict(record.status.metrics),
            }
            record.status.partial_result_available = True
            record.status.result_version += 1
            record.status.timings_ms["local_result_transport"] = round(elapsed_ms, 3)
            version = record.status.result_version
            self.repository.save_status(record.status)
        self._publish_event(
            job_id,
            {
                "type": "partial",
                "status": "running",
                "progress": max(0.98, float(record.status.progress)),
                "stage": "result.local_ready",
                "result_version": version,
                "partial": {
                    "live_result_available": True,
                    "metrics": dict(record.status.metrics),
                    "timings_ms": dict(record.status.timings_ms),
                },
            },
        )

    def _submit_result_persistence(
        self, job_id: str, record: JobRecord, result: Any
    ) -> None:

        self._publish_local_live_result(job_id, record, result)
        if not record.persistent:
            self._persist_completed_result(job_id, record, result)
            return
        with self._lock:
            if self._shutdown:
                return
            executor = self._persistence_executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=max(1, min(2, int(self.max_workers))),
                    thread_name_prefix="result-persistence",
                )
                self._persistence_executor = executor
        executor.submit(self._persist_completed_result, job_id, record, result)

    @staticmethod
    def _attach_timing_metadata(record: JobRecord, result: Any) -> None:
        
        
        
        
        metadata = None
        if isinstance(result, dict):
            looks_like_optical_result = bool(
                "metadata" in result
                or {"metrics", "arrays", "diagnostics", "provenance"}
                & set(result)
            )
            if looks_like_optical_result:
                metadata = result.setdefault("metadata", {})
        else:
            metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            timing = metadata.setdefault("job_timings_ms", {})
            if isinstance(timing, dict):
                timing.update(dict(record.status.timings_ms))
            metadata.setdefault("result_delivery", "summary_then_lazy_bundle")

    def _persist_progress_status(
        self, record: JobRecord, *, force: bool = False, at: float | None = None
    ) -> bool:

        stamp = time.perf_counter() if at is None else float(at)
        progress = float(record.status.progress)
        stage = str(record.status.stage or "")
        should_write = bool(
            force
            or record.last_status_persist_perf <= 0.0
            or stamp - record.last_status_persist_perf >= 0.5
            or abs(progress - record.last_status_persist_progress) >= 0.05
            or stage != record.last_status_persist_stage
        )
        if not should_write:
            return False
        self.repository.save_status(record.status)
        record.last_status_persist_perf = stamp
        record.last_status_persist_progress = progress
        record.last_status_persist_stage = stage
        return True

    def _prune_terminal_records_locked(self) -> None:

        if len(self.records) <= self._max_memory_records:
            return
        for job_id, item in list(self.records.items()):
            if len(self.records) <= self._max_memory_records:
                break
            if item.persistence_pending or item.status.status in {"queued", "running"}:
                continue
            item.result = None
            item.partial_result = None
            item.live_result = None
            item.close_pipe()
            self.records.pop(job_id, None)

    def _lookup(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self.records.get(job_id)

    def _publish_event(self, job_id: str, event: dict) -> None:

        bus = self.event_bus
        if bus is not None:
            try:
                bus.publish(job_id, event)
            except Exception:
                self.logger.exception(
                    "failed to publish job event: job_id=%s type=%s",
                    job_id,
                    event.get("type", "unknown"),
                )

    def _start_process(
        self,
        job_id: str,
        record: JobRecord,
        func_data: bytes,
        args: tuple,
        kwargs: dict,
    ) -> None:

        dispatch_started = time.perf_counter()
        record.dispatched_perf = dispatch_started
        if record.submitted_perf > 0.0:
            record.status.timings_ms["queue_wait"] = round(
                (dispatch_started - record.submitted_perf) * 1000.0, 3
            )
        parent_conn, child_conn = self._ctx.Pipe(duplex=False)

        cancel_event = self._ctx.Event()
        record.cancellation = CancellationToken(cancel_event)
        record.pipe = parent_conn

        record.status.status = "running"
        record.status.progress = max(float(record.status.progress), 0.01)
        record.status.stage = f"{record.status.job_type}.starting"
        record.status.completed_items = 0
        record.status.total_items = max(1, int(record.status.total_items))
        record.status.started_at = now()
        self.repository.save_status(record.status)
        self._publish_event(
            job_id,
            {
                "type": "running",
                "status": "running",
                "progress": record.status.progress,
                "stage": record.status.stage,
                "completed_items": record.status.completed_items,
                "total_items": record.status.total_items,
                "started_at": record.status.started_at,
            },
        )

        process = self._ctx.Process(
            target=_worker_target,
            args=(child_conn, cancel_event, func_data, args, kwargs),
            name=f"optical-job-{job_id}",
            daemon=True,
        )
        record.process = process

        process_start = time.perf_counter()
        try:
            process.start()
            record.status.timings_ms["process_dispatch"] = round(
                (time.perf_counter() - process_start) * 1000.0, 3
            )
        except Exception as exc:
            try:
                child_conn.close()
            except OSError:
                pass
            record.process = None
            self._mark_start_failure(job_id, record, exc, stage="worker.start")
            return
        child_conn.close()  

        monitor = threading.Thread(
            target=self._monitor,
            args=(job_id, record),
            name=f"monitor-{job_id}",
            daemon=True,
        )
        record.monitor_thread = monitor
        monitor.start()

    def _mark_start_failure(
        self, job_id: str, record: JobRecord, exc: Exception, *, stage: str
    ) -> None:

        with self._lock:
            record.status.status = "failed"
            record.status.stage = stage
            record.status.finished_at = now()
            record.status.error = ApplicationError(
                code="WORKER_START_FAILED",
                stage=stage,
                message=str(exc) or type(exc).__name__,
                retryable=True,
            )
            self.repository.save_status(record.status)
        self._publish_event(
            job_id,
            {
                "type": "failed",
                "status": "failed",
                "stage": stage,
                "error": record.status.error.model_dump(),
            },
        )
        record.close_pipe()
        self._finalize_job(record)

    def _monitor(self, job_id: str, record: JobRecord) -> None:

        conn = record.pipe
        if conn is None:
            self._finalize_job(record)
            return

        stage_on_entry = record.status.stage
        timeout_at: float | None = None
        if record.timeout_seconds is not None and record.timeout_seconds > 0.0:
            timeout_at = time.monotonic() + record.timeout_seconds
        last_heartbeat_at = time.monotonic()

        try:
            while True:
                if conn.closed:
                    break
                if not conn.poll(timeout=PIPE_POLL_INTERVAL):
                    check_at = time.monotonic()
                    
                    
                    
                    if timeout_at is not None and check_at > timeout_at:
                        self.logger.warning(
                            "job %s timed out after %.0f s — terminating",
                            job_id, record.timeout_seconds,
                        )
                        record.cancellation.cancel()
                        with record.process_lock:
                            process = record.process
                            if process is not None and process.is_alive():
                                process.terminate()
                                process.join(timeout=FORCE_KILL_PERIOD)
                                if process.is_alive():
                                    process.kill()
                                    process.join(timeout=1.0)
                        with self._lock:
                            record.status.status = "failed"
                            record.status.error = ApplicationError(
                                code="TIMEOUT",
                                stage=record.status.stage or "monitor",
                                message=f"job timed out after {record.timeout_seconds} s",
                                retryable=False,
                            )
                            self.repository.save_status(record.status)
                        self._publish_event(
                            job_id,
                            {
                                "type": "failed",
                                "status": "failed",
                                "progress": record.status.progress,
                                "stage": record.status.stage,
                                "error": record.status.error.model_dump(),
                            },
                        )
                        break

                    
                    
                    
                    
                    if (
                        check_at - last_heartbeat_at >= HEARTBEAT_INTERVAL
                        and record.status.status == "running"
                    ):
                        with self._lock:
                            self.repository.save_status(record.status)
                            heartbeat = {
                                "type": "progress",
                                "heartbeat": True,
                                "progress": record.status.progress,
                                "status": record.status.status,
                                "stage": record.status.stage,
                                "completed_items": record.status.completed_items,
                                "total_items": record.status.total_items,
                            }
                        self._publish_event(job_id, heartbeat)
                        last_heartbeat_at = check_at
                    continue
                msg = conn.recv()
                last_heartbeat_at = time.monotonic()
                message_at = time.perf_counter()
                if record.first_message_perf <= 0.0:
                    record.first_message_perf = message_at
                    if record.dispatched_perf > 0.0:
                        record.status.timings_ms["worker_startup"] = round(
                            (message_at - record.dispatched_perf) * 1000.0, 3
                        )

                
                
                
                if isinstance(msg, PartialResultMessage):
                    data = dict(msg.payload or {}) if isinstance(msg.payload, dict) else {"value": msg.payload}
                    metrics = data.get("metrics")
                    with self._lock:
                        if isinstance(metrics, dict):
                            record.status.metrics.update(metrics)
                        record.partial_result = data
                        record.status.partial_result_available = True
                        record.status.result_version = max(
                            record.status.result_version + 1, int(msg.version)
                        )
                        record.status.stage = str(msg.stage or record.status.stage)
                        self.repository.save_status(record.status)
                        version = record.status.result_version
                    self._publish_event(
                        job_id,
                        {
                            "type": "partial",
                            "status": record.status.status,
                            "progress": record.status.progress,
                            "stage": record.status.stage,
                            "result_version": version,
                            "partial": data,
                        },
                    )

                elif isinstance(msg, ProgressMessage):
                    with self._lock:
                        record.status.progress = msg.progress
                        record.status.stage = msg.stage
                        record.status.completed_items = msg.completed_items
                        record.status.total_items = msg.total_items
                        self._persist_progress_status(record, at=message_at)
                    self._publish_event(
                        job_id,
                        {
                            "type": "progress",
                            "progress": msg.progress,
                            "status": record.status.status,
                            "stage": msg.stage,
                            "completed_items": msg.completed_items,
                            "total_items": msg.total_items,
                        },
                    )

                elif isinstance(msg, tuple):
                    tag = msg[0]

                    if tag == "_result_":
                        result = msg[1]
                        with self._lock:
                            if not record.cancellation.is_cancelled:
                                record.result = result
                                record.persistence_pending = True
                                record.status.progress = max(0.98, float(record.status.progress))
                                record.status.stage = "result.persisting"
                                if record.dispatched_perf > 0.0:
                                    record.status.timings_ms["worker_compute"] = round(
                                        (message_at - record.dispatched_perf) * 1000.0, 3
                                    )
                                metrics = _result_field(result, "metrics", {}) or {}
                                if isinstance(metrics, dict):
                                    record.status.metrics.update(metrics)
                                self.repository.save_status(record.status)
                        if not record.cancellation.is_cancelled:
                            self._publish_event(
                                job_id,
                                {
                                    "type": "progress",
                                    "status": "running",
                                    "progress": record.status.progress,
                                    "stage": "result.persisting",
                                    "metrics": dict(record.status.metrics),
                                },
                            )
                            self._submit_result_persistence(job_id, record, result)
                        break

                    elif tag == "_error_":
                        err = msg[1]
                        with self._lock:
                            if err.get("is_app_error"):
                                record.status.error = ApplicationError(
                                    code=err["code"],
                                    stage=err["stage"],
                                    message=err["message"],
                                    retryable=err.get("retryable", False),
                                )
                            else:
                                record.status.error = ApplicationError(
                                    code="INTERNAL_ERROR",
                                    stage=err.get("stage", stage_on_entry),
                                    message=err.get("message", ""),
                                    retryable=False,
                                )
                            record.status.status = "failed"
                        self._publish_event(
                            job_id,
                            {
                                "type": "failed",
                                "status": "failed",
                                "error": {
                                    "code": err.get("code", "INTERNAL_ERROR"),
                                    "message": err.get("message", ""),
                                },
                            },
                        )
                        break

                    elif tag == "_cancelled_":
                        
                        
                        
                        self._publish_event(
                            job_id,
                            {"type": "cancelled", "status": "cancelled"},
                        )
                        break

        except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
            
            pass
        finally:
            with self._lock:
                
                
                if record.status.status == "running" and not record.persistence_pending:
                    if record.cancellation.is_cancelled:
                        record.status.status = "cancelled"
                    else:
                        record.status.status = "failed"
                        record.status.error = ApplicationError(
                            code="WORKER_EXITED",
                            stage=record.status.stage or stage_on_entry or "worker",
                            message="worker process exited without returning a result",
                            retryable=True,
                        )
                if not record.persistence_pending:
                    if record.status.finished_at is None:
                        record.status.finished_at = now()
                    self.repository.save_status(record.status)
            record.close_pipe()
            self._finalize_job(record)

    def _finalize_job(self, record: JobRecord) -> None:

        with self._lock:
            if record._finalized:
                return
            record._finalized = True

        record.close_pipe()
        
        
        
        
        
        
        self._reap_process(record, timeout=1.0, close_handle=True)
        was_cancelled = record.cancellation.is_cancelled
        record.cancellation = CancellationToken()
        if was_cancelled:
            record.cancellation.cancel()
        record.release_semaphore()
        with self._lock:
            self._prune_terminal_records_locked()
        self._maybe_dequeue()

    def _reap_completed_process(self, record: JobRecord) -> None:

        with record.process_lock:
            process = record.process
            if process is None:
                return
            try:
                process.join(timeout=2.0)
                if process.is_alive():
                    self.logger.warning(
                        "completed job %s worker lingered during teardown; terminating",
                        record.status.job_id,
                    )
                    process.terminate()
                    process.join(timeout=1.0)
                if process.is_alive():
                    self.logger.error(
                        "completed job %s worker survived terminate; killing",
                        record.status.job_id,
                    )
                    process.kill()
                    process.join(timeout=1.0)
                if not process.is_alive():
                    try:
                        process.close()
                    except (AttributeError, OSError, ValueError):
                        pass
                    record.process = None
            except (AssertionError, AttributeError, OSError, ValueError):
                
                record.process = None

    def _reap_process(
        self, record: JobRecord, *, timeout: float, close_handle: bool
    ) -> None:
        with record.process_lock:
            process = record.process
            if process is None:
                return
            try:
                if process.is_alive() and timeout > 0.0:
                    process.join(timeout=timeout)
                elif not process.is_alive():
                    process.join(timeout=0.0)
                if close_handle and not process.is_alive():
                    try:
                        process.close()
                    except (AttributeError, OSError, ValueError):
                        pass
                    record.process = None
            except (AssertionError, AttributeError, OSError, ValueError):
                
                
                if close_handle:
                    record.process = None

    def _maybe_dequeue(self) -> None:

        with self._lock:
            if self._shutdown:
                return
            
            while self._queue:
                job_id, record, func_data, args, kwargs = self._queue[0]
                if record.status.status != "queued":
                    self._queue.pop(0)
                    continue
                break
            else:
                return

            if not self._semaphore.acquire(False):
                return  

            job_id, record, func_data, args, kwargs = self._queue.pop(0)
            record.semaphore = self._semaphore

        self._start_process(job_id, record, func_data, args, kwargs)

    def _attach_simulation_job_metadata(
        self, record: JobRecord, result: Any
    ) -> None:

        if record.status.job_type != "simulation":
            return
        if isinstance(result, dict):
            looks_like_optical_result = bool(
                "metadata" in result
                or {"metrics", "arrays", "diagnostics", "provenance"}
                & set(result)
            )
            if not looks_like_optical_result:
                return
            metadata = result.setdefault("metadata", {})
        else:
            metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            metadata.setdefault("job_id", record.status.job_id)
