from __future__ import annotations

import os
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from threading import RLock
from typing import Callable

from .physical_scene import TeachingEngineTrace, TeachingOpticalEngineBridge, TeachingPhysicalScene
from .trace_worker import trace_scene_in_process


def _use_process_mode() -> bool:
    value = os.environ.get("OPTICAL_TEACHING_TRACE_MODE", "").strip().lower()
    if value in {"process", "multi", "1"}:
        return True
    if value in {"thread", "0"}:
        return False
    # Default: threads (stable, no spawn overhead); process mode is opt-in.
    return False


class TeachingTraceScheduler:
    """Single-flight latest-wins scheduler for interactive teaching traces."""

    def __init__(
        self,
        bridge: TeachingOpticalEngineBridge | None = None,
        *,
        max_workers: int = 1,
        process_mode: bool | None = None,
    ) -> None:
        self._bridge = bridge or TeachingOpticalEngineBridge()
        self._process_mode = bool(process_mode if process_mode is not None else _use_process_mode())
        if self._process_mode:
            self._executor = ProcessPoolExecutor(max_workers=max(1, int(max_workers)))
            self._run = trace_scene_in_process
        else:
            self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="teaching-trace")
            self._run: Callable[[TeachingPhysicalScene], TeachingEngineTrace] = self._bridge.trace
        self._lock = RLock()
        self._latest_requested_generation = -1
        self._latest_completed: TeachingEngineTrace | None = None
        self._active: Future[TeachingEngineTrace] | None = None
        self._queued_scene: TeachingPhysicalScene | None = None
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
            if self._active is not None and not self._active.done():
                self._queued_scene = prepared
                return generation
            self._queued_scene = None
            self._start_locked(prepared)
        return generation

    def _start_locked(self, scene: TeachingPhysicalScene) -> None:
        future = self._executor.submit(self._run, scene)
        self._active = future
        future.add_done_callback(self._on_done)

    def _on_done(self, future: Future[TeachingEngineTrace]) -> None:
        result: TeachingEngineTrace | None = None
        try:
            if not future.cancelled():
                result = future.result()
        except Exception:
            result = None
        with self._lock:
            if self._active is future:
                self._active = None
            if self._closed:
                return
            if result is not None and int(result.generation) == int(self._latest_requested_generation):
                self._latest_completed = result
            queued = self._queued_scene
            self._queued_scene = None
            if queued is not None and not self._closed:
                self._start_locked(queued)

    def poll_latest(self) -> TeachingEngineTrace | None:
        with self._lock:
            result = self._latest_completed
            self._latest_completed = None
            return result

    def close(self) -> None:
        with self._lock:
            self._closed = True
            active = self._active
            self._active = None
            self._queued_scene = None
            self._latest_completed = None
        if active is not None and not active.done():
            active.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["TeachingTraceScheduler"]
