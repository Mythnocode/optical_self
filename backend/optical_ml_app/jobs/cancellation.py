

from __future__ import annotations

from threading import Event as ThreadingEvent
from typing import Any


class CancellationToken:


    def __init__(self, event: Any | None = None) -> None:
        self._event: Any = event if event is not None else ThreadingEvent()

    def cancel(self) -> None:

        self._event.set()

    @property
    def is_cancelled(self) -> bool:

        return bool(self._event.is_set())
