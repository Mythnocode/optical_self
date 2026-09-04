
from __future__ import annotations

import os

_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def configure_native_thread_limits(default: int | None = None) -> int:
    limit = max(1, int(os.environ.get("NATIVE_THREAD_LIMIT", default or 1)))
    value = str(limit)
    for name in _THREAD_VARIABLES:
        os.environ.setdefault(name, value)
    return limit


def configured_batch_worker_count(default: int | None = None) -> int:
    """Return the bounded thread count used for independent optical samples.

    The optical worker pool already constrains BLAS/native libraries to one
    thread per optical worker.  Keeping this policy in one place prevents scan,
    tolerance and dataset services from inventing different parallelism rules.
    """

    # Keep the verified current-environment default serial.  The thread-pool
    # path remains available through OPTICAL_BATCH_THREAD_COUNT after running
    # a target-machine benchmark; on this container 4 optical threads were
    # slower because wave/FFT work competed for CPU and memory bandwidth.
    fallback = default if default is not None else 1
    return max(1, int(os.environ.get("OPTICAL_BATCH_THREAD_COUNT", fallback)))


__all__ = ["configure_native_thread_limits", "configured_batch_worker_count"]
