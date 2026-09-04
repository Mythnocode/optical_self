"""Process-safe trace worker for the teaching center.

The heavy teaching ray-trace is pure CPU and holds the GIL. Running it in a
separate process keeps the Qt UI thread and the trace worker from contending
for the GIL. Only plain teaching_runtime objects cross the process boundary;
no Qt/UI objects are touched here.
"""

from __future__ import annotations

from typing import Any

from .physical_scene import TeachingEngineTrace, TeachingOpticalEngineBridge, TeachingPhysicalScene


_bridge: TeachingOpticalEngineBridge | None = None


def _get_bridge() -> TeachingOpticalEngineBridge:
    global _bridge
    if _bridge is None:
        # Rebuilt inside the worker process; the engine itself is untouched.
        _bridge = TeachingOpticalEngineBridge()
    return _bridge


def trace_scene_in_process(scene: TeachingPhysicalScene) -> TeachingEngineTrace:
    """Run a single trace inside the worker process."""
    return _get_bridge().trace(scene)


def warmup() -> None:
    """Force engine construction inside the worker process on first use."""
    _get_bridge()


__all__ = ["trace_scene_in_process", "warmup"]
