
from __future__ import annotations

_REGISTERED = False


def register_resources() -> bool:
    global _REGISTERED
    if _REGISTERED:
        return True
    try:
        pass  
    except ImportError:
        return False
    _REGISTERED = True
    return True


__all__ = ["register_resources"]
