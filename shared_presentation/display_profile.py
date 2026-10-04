"""Display preferences are explicit in API calls and scoped to each request."""
from contextlib import contextmanager
from contextvars import ContextVar

# QSettings' float conversion gives this value for the original 0.67 preset.
DEFAULT_FILL_FRACTION = 0.6700000166893005
_profile = ContextVar("optical_display_profile", default=(True, DEFAULT_FILL_FRACTION))

def current_display_profile() -> tuple[bool, float]:
    return _profile.get()

@contextmanager
def use_display_profile(profile: dict | None = None):
    values = dict(profile or {})
    token = _profile.set((bool(values.get("auto_display_frame", True)), float(values.get("display_fill_fraction", DEFAULT_FILL_FRACTION))))
    try:
        yield
    finally:
        _profile.reset(token)
