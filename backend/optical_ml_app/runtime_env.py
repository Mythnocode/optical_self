
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


__all__ = ["configure_native_thread_limits"]
