from __future__ import annotations

import ctypes
import os
import signal
import sys


def arm_parent_death_signal() -> bool:
    """Ask Linux to terminate this worker when its direct parent dies.

    Multiprocessing daemon workers are cleaned up during a normal Python
    shutdown, but a hard-crashed backend (SIGKILL/power-manager kill) cannot run
    that cleanup.  On Linux this leaves CPU-heavy optical workers orphaned and
    they can compete with the restarted backend.  PR_SET_PDEATHSIG closes that
    gap without changing Windows/macOS behaviour.
    """

    if not sys.platform.startswith("linux"):
        return False

    parent_pid = os.getppid()
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        prctl.restype = ctypes.c_int
        # Linux prctl(2): PR_SET_PDEATHSIG = 1.
        if prctl(1, int(signal.SIGTERM), 0, 0, 0) != 0:
            return False
    except Exception:
        return False

    # The parent can die between getppid() and prctl().  In that race Linux
    # does not retroactively deliver the signal, so terminate ourselves.
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGTERM)
    return True


__all__ = ["arm_parent_death_signal"]
