
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from frontend_pyside.shared.lifecycle import GenerationGate


class StagedPreviewScheduler(QObject):
    sectionRequested = Signal(int)
    simplified3dRequested = Signal(int)
    highQuality3dRequested = Signal(int)

    def __init__(
        self,
        *,
        section_delay_ms: int = 0,
        simplified_delay_ms: int = 250,
        high_quality_delay_ms: int = 800,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.generations = GenerationGate()
        self._section = self._timer(section_delay_ms, self._emit_section)
        self._simplified = self._timer(simplified_delay_ms, self._emit_simplified)
        self._high_quality = self._timer(high_quality_delay_ms, self._emit_high_quality)
        self._pending_generation = 0

    def _timer(self, interval: int, callback: Callable[[], Any]) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(max(0, int(interval)))
        timer.timeout.connect(callback)
        return timer

    def schedule(self, *, high_quality: bool = True) -> int:
        generation = self.generations.next("preview")
        self._pending_generation = generation
        self._section.start()
        self._simplified.start()
        if high_quality:
            self._high_quality.start()
        else:
            self._high_quality.stop()
        return generation

    def request_now(self, *, high_quality: bool = True) -> int:
        generation = self.generations.next("preview")
        self._pending_generation = generation
        self._section.stop()
        self._simplified.stop()
        self._high_quality.stop()
        self.sectionRequested.emit(generation)
        if high_quality:
            self.highQuality3dRequested.emit(generation)
        else:
            self.simplified3dRequested.emit(generation)
        return generation

    def cancel(self) -> None:
        self.generations.invalidate("preview")
        self._pending_generation = 0
        self._section.stop()
        self._simplified.stop()
        self._high_quality.stop()

    def is_current(self, generation: int) -> bool:
        return self.generations.is_current(generation, "preview")

    def _emit_section(self) -> None:
        self.sectionRequested.emit(self._pending_generation)

    def _emit_simplified(self) -> None:
        self.simplified3dRequested.emit(self._pending_generation)

    def _emit_high_quality(self) -> None:
        self.highQuality3dRequested.emit(self._pending_generation)


__all__ = ["StagedPreviewScheduler"]
