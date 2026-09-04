
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock, local
from typing import Any, Iterable, Sequence

from shared_contracts.simulation import SimulationRequest, SimulationResult

from .engine import ByteBoundLRUCache, OpticalSimulationEngine


@dataclass(frozen=True, slots=True)
class WorkerPoolInfo:
    max_workers: int
    submitted: int
    completed: int
    trace_cache: dict[str, int]
    runtime_caches: dict[str, Any]


class OpticalWorkerPool:


    def __init__(
        self,
        *,
        max_workers: int = 4,
        trace_cache_max_bytes: int = 2 * 1024**3,
        internal_thread_limit: int | None = 1,
        thread_name_prefix: str = "optical-worker",
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.internal_thread_limit = (
            None if internal_thread_limit is None else max(1, int(internal_thread_limit))
        )
        self._shared_trace_cache = ByteBoundLRUCache(trace_cache_max_bytes)
        self._local = local()
        self._threadpool_limit_context = None
        if self.internal_thread_limit is not None:
            try:
                from threadpoolctl import threadpool_limits
                self._threadpool_limit_context = threadpool_limits(
                    limits=self.internal_thread_limit
                )
                self._threadpool_limit_context.__enter__()
            except ImportError:
                self._threadpool_limit_context = None
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=str(thread_name_prefix),
        )
        self._counter_lock = Lock()
        self._submitted = 0
        self._completed = 0
        self._closed = False

    def _engine(self) -> OpticalSimulationEngine:
        engine = getattr(self._local, "engine", None)
        if engine is None:
            engine = OpticalSimulationEngine(shared_trace_cache=self._shared_trace_cache)
            self._local.engine = engine
        return engine

    def _run(self, request: SimulationRequest, cancellation=None) -> SimulationResult:
        try:
            return self._engine().evaluate(request, cancellation=cancellation)
        finally:
            with self._counter_lock:
                self._completed += 1

    def submit(self, request: SimulationRequest, *, cancellation=None) -> Future[SimulationResult]:
        if self._closed:
            raise RuntimeError("OpticalWorkerPool is closed")
        with self._counter_lock:
            self._submitted += 1
        return self._executor.submit(self._run, request, cancellation)

    def evaluate(self, request: SimulationRequest, *, cancellation=None) -> SimulationResult:
        return self.submit(request, cancellation=cancellation).result()

    def map(
        self,
        requests: Sequence[SimulationRequest] | Iterable[SimulationRequest],
        *,
        chunksize: int = 1,
        cancellation=None,
        progress=None,
        stage: str = "batch.evaluate",
    ) -> list[SimulationResult]:
        if self._closed:
            raise RuntimeError("OpticalWorkerPool is closed")
        items = tuple(requests)
        if not items:
            return []
        # Submit explicitly rather than executor.map so backend progress reflects
        # completed optical samples instead of a synthetic timer.  Results are
        # placed back into request order, preserving deterministic semantics.
        futures: dict[Future[SimulationResult], int] = {}
        with self._counter_lock:
            self._submitted += len(items)
        for index, request in enumerate(items):
            futures[self._executor.submit(self._run, request, cancellation)] = index

        results: list[SimulationResult | None] = [None] * len(items)
        completed = 0
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
            completed += 1
            if progress is not None:
                progress.update(
                    completed / len(items),
                    stage,
                    completed_items=completed,
                    total_items=len(items),
                )
            is_cancelled = getattr(cancellation, "is_cancelled", False)
            if callable(is_cancelled):
                is_cancelled = is_cancelled()
            if is_cancelled:
                for pending in futures:
                    if not pending.done():
                        pending.cancel()
                break

        # A cancellation can leave not-yet-started futures empty.  The existing
        # batch API expects a complete list, so resolve any already-running work;
        # cancelled jobs are discarded by the caller's cancellation state.
        for future, index in futures.items():
            if results[index] is None and not future.cancelled():
                results[index] = future.result()
        return [item for item in results if item is not None]

    def warmup(self, requests: Sequence[SimulationRequest]) -> list[SimulationResult]:

        return self.map(requests)

    def clear_caches(self) -> None:
        
        
        OpticalSimulationEngine(shared_trace_cache=self._shared_trace_cache).clear_caches()

    def cache_info(self) -> WorkerPoolInfo:
        runtime = OpticalSimulationEngine(
            shared_trace_cache=self._shared_trace_cache
        ).cache_info()
        with self._counter_lock:
            submitted = self._submitted
            completed = self._completed
        return WorkerPoolInfo(
            max_workers=self.max_workers,
            submitted=int(submitted),
            completed=int(completed),
            trace_cache=self._shared_trace_cache.info(),
            runtime_caches=runtime,
        )

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=bool(wait), cancel_futures=bool(cancel_futures))
        if self._threadpool_limit_context is not None:
            self._threadpool_limit_context.__exit__(None, None, None)
            self._threadpool_limit_context = None

    def __enter__(self) -> "OpticalWorkerPool":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.shutdown(wait=True, cancel_futures=exc is not None)


__all__ = ["WorkerPoolInfo", "OpticalWorkerPool"]
