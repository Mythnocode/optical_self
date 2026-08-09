from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from threading import Lock
from typing import Callable

from .physical_scene import TeachingEngineTrace, TeachingOpticalEngineBridge, TeachingPhysicalScene


class TeachingTraceScheduler:
    def __init__(
        self,
        bridge: TeachingOpticalEngineBridge | None = None,
        *,
        max_workers: int = 1,
    ) -> None:
        self._bridge = bridge or TeachingOpticalEngineBridge()
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="teaching-trace")
        self._lock = Lock()
        self._latest_requested_generation = -1
        self._latest_completed: TeachingEngineTrace | None = None
        self._pending: Future[TeachingEngineTrace] | None = None
        self._closed = False

    @property
    def latest_requested_generation(self) -> int:
        with self._lock:
            return int(self._latest_requested_generation)

    def submit(
        self,
        scene: TeachingPhysicalScene,
        *,
        generation: int,
        quality: str,
    ) -> int:
        generation = int(generation)
        prepared = replace(scene, generation=generation, trace_quality=str(quality))
        with self._lock:
            if self._closed:
                return generation
            self._latest_requested_generation = generation
            pending = self._pending
            if pending is not None and not pending.running() and not pending.done():
                pending.cancel()
            future = self._executor.submit(self._bridge.trace, prepared)
            self._pending = future
        future.add_done_callback(self._on_done)
        return generation

    def _on_done(self, future: Future[TeachingEngineTrace]) -> None:
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception:
            return
        with self._lock:
            if self._closed:
                return
            if int(result.generation) != int(self._latest_requested_generation):
                return
            self._latest_completed = result

    def poll_latest(self) -> TeachingEngineTrace | None:
        with self._lock:
            result = self._latest_completed
            self._latest_completed = None
            return result

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pending = self._pending
            self._pending = None
            self._latest_completed = None
        if pending is not None and not pending.done():
            pending.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["TeachingTraceScheduler"]
