
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class BackgroundSignals(QObject):
    completed = Signal(str, int, object)
    failed = Signal(str, int, str)


class _PreparationRunnable(QRunnable):
    def __init__(
        self,
        channel: str,
        generation: int,
        function: Callable[[], Any],
        signals: BackgroundSignals,
    ) -> None:
        super().__init__()
        self.channel = channel
        self.generation = int(generation)
        self.function = function
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            value = self.function()
        except Exception:
            self.signals.failed.emit(
                self.channel,
                self.generation,
                traceback.format_exc(),
            )
            return
        self.signals.completed.emit(self.channel, self.generation, value)


class BackgroundPreparer(QObject):
    completed = Signal(str, int, object)
    failed = Signal(str, int, str)

    def __init__(self, parent=None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self.pool = pool or QThreadPool.globalInstance()
        self._signals = BackgroundSignals(self)
        self._signals.completed.connect(self.completed.emit)
        self._signals.failed.connect(self.failed.emit)

    def submit(self, channel: str, generation: int, function: Callable[[], Any]) -> None:
        self.pool.start(
            _PreparationRunnable(str(channel), int(generation), function, self._signals)
        )


__all__ = ["BackgroundPreparer"]
