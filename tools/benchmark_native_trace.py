"""Benchmark: Python full ray tracer vs C++ native multithreaded kernel.

Usage: py -3.12 tools/benchmark_native_trace.py [ray_count] [repeats]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import shiboken6  # noqa: F401
except Exception:
    pass
try:
    from frontend_pyside.core.shiboken_guard import harden_shiboken_signature_hook

    harden_shiboken_signature_hook()
except Exception:
    pass

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.state.project_context import default_project
from optical_core.physics.geometric.solvers.native_trace import native_available
from optical_runtime.request_compiler import compile_simulation_context
from shared_contracts.project import ProjectSnapshot


def build_context():
    snapshot = ProjectSnapshot.model_validate(
        serialize_project(default_project(), SimulationFormState())
    )
    request = {
        "project": snapshot.model_dump(),
        "options": {},
        "precision": "standard",
        "random_seed": 7,
    }

    class _Req:
        pass

    class _R:
        def __init__(self, payload):
            self._p = payload

        def __getattr__(self, item):
            return self._p.get(item)

    return compile_simulation_context(_R(request))


def time_once(native: bool) -> float:
    os.environ["OPTICAL_NATIVE"] = "1" if native else "0"
    context = build_context()
    start = time.perf_counter()
    context.get_or_create_trace()
    return time.perf_counter() - start


def main() -> None:
    if not native_available():
        print("native DLL 未找到，请先编译 native/build/optical_native.dll")
        return
    repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    for label, native in (("python full tracer", False), ("native C++ kernel", True)):
        for threads in (1, 0):
            if native:
                os.environ["OPTICAL_NATIVE_THREADS"] = str(threads)
            else:
                os.environ.pop("OPTICAL_NATIVE_THREADS", None)
            times = [time_once(native) for _ in range(repeats)]
            best = min(times)
            thread_label = "auto" if threads == 0 else str(threads)
            print(f"{label:20s} threads={thread_label:>4s}  best={best*1000:9.1f} ms  "
                  f"runs={['%.0f' % (t*1000) for t in times]}")


if __name__ == "__main__":
    main()
