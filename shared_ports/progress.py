from typing import Protocol


class CancellationTokenPort(Protocol):
    @property
    def is_cancelled(self) -> bool: ...


class ProgressReporterPort(Protocol):
    def update(self, progress: float, stage: str, completed_items: int = 0, total_items: int = 1) -> None: ...
