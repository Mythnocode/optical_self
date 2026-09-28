"""Thread-count scaling sweep for the native ray trace kernel."""

from __future__ import annotations

import os
import sys
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

from tools.benchmark_native_trace import time_once


def main() -> None:
    os.environ["OPTICAL_NATIVE"] = "1"
    repeats = 5
    for threads in (1, 2, 4, 8, 12, 16, 24):
        os.environ["OPTICAL_NATIVE_THREADS"] = str(threads)
        times = sorted(time_once(True) for _ in range(repeats))
        best = times[0]
        median = times[len(times) // 2]
        print(f"threads={threads:>2d}  best={best*1000:8.1f} ms  median={median*1000:8.1f} ms")


if __name__ == "__main__":
    main()
