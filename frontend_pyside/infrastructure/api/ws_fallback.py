
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class PollingOnlyJobWatcher(QObject):
    job_progress = Signal(str, float, str)
    job_partial = Signal(str, dict)
    job_completed = Signal(str, str, dict)
    job_failed = Signal(str, str)
    connection_changed = Signal(bool)

    def subscribe(self, job_id: str) -> None:
        
        self.connection_changed.emit(False)

    def unsubscribe(self, job_id: str) -> None:
        return

    def unsubscribe_all(self) -> None:
        return

    def disconnect(self) -> None:
        return


__all__ = ["PollingOnlyJobWatcher"]
