"""Tiny fallback used only for pure-state tests when PySide6 is absent.

The deployed application still uses real PySide6.  Keeping the model importable
without Qt makes coordinate and persistence tests runnable in CI environments
that do not install desktop dependencies.
"""

from __future__ import annotations

try:  # pragma: no cover - exercised only on a desktop installation
    from PySide6.QtCore import QObject, Signal
except ModuleNotFoundError:  # pragma: no cover - deterministic test fallback
    class _BoundSignal:
        def __init__(self) -> None:
            self._slots: list = []

        def connect(self, slot) -> None:
            self._slots.append(slot)

        def emit(self, *args, **kwargs) -> None:
            for slot in list(self._slots):
                slot(*args, **kwargs)

    class Signal:
        def __init__(self, *args, **kwargs) -> None:
            self._name = ""

        def __set_name__(self, owner, name) -> None:
            self._name = f"__signal_{name}"

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            signal = instance.__dict__.get(self._name)
            if signal is None:
                signal = _BoundSignal()
                instance.__dict__[self._name] = signal
            return signal

    class QObject:
        def __init__(self, parent=None) -> None:
            self._qt_parent = parent


__all__ = ["QObject", "Signal"]
