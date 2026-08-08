
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer


class SignalConnectionBag:


    def __init__(self) -> None:
        self._connections: list[tuple[Any, Callable[..., Any]]] = []
        self._keys: set[tuple[int, int]] = set()

    def connect(self, signal, slot: Callable[..., Any], *, unique: bool = True) -> bool:
        key = (id(signal), id(slot))
        if unique and key in self._keys:
            return False
        try:
            
            
            
            
            signal.connect(slot)
        except (TypeError, RuntimeError):
            return False
        self._connections.append((signal, slot))
        self._keys.add(key)
        return True

    def disconnect_all(self) -> None:
        for signal, slot in reversed(self._connections):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._connections.clear()
        self._keys.clear()


class GenerationGate:


    def __init__(self) -> None:
        self._values: dict[str, int] = defaultdict(int)

    def next(self, channel: str = "default") -> int:
        channel = str(channel or "default")
        self._values[channel] += 1
        return self._values[channel]

    def current(self, channel: str = "default") -> int:
        return self._values[str(channel or "default")]

    def is_current(self, token: int, channel: str = "default") -> bool:
        return int(token) == self.current(channel)

    def invalidate(self, channel: str = "default") -> int:
        return self.next(channel)

    def invalidate_all(self) -> None:
        for channel in tuple(self._values):
            self._values[channel] += 1




def safe_single_shot(owner: QObject, interval_ms: int, callback: Callable[[], Any]) -> QTimer:

    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.setInterval(max(0, int(interval_ms)))

    def invoke() -> None:
        try:
            if bool(getattr(owner, "_disposed", False)):
                return
            callback()
        except RuntimeError:
            return
        finally:
            try:
                timer.deleteLater()
            except RuntimeError:
                pass

    timer.timeout.connect(invoke)
    timer.start()
    return timer


class ManagedPageResources:


    def __init__(self, owner: QObject) -> None:
        self.owner = owner
        self.connections = SignalConnectionBag()
        self.generations = GenerationGate()
        self._timers: set[QTimer] = set()
        self._workers: set[Any] = set()
        self._cleanup: list[Callable[[], Any]] = []
        self._disposed = False
        self.last_activated_at = monotonic()

    @property
    def disposed(self) -> bool:
        return self._disposed

    def connect(self, signal, slot: Callable[..., Any], *, unique: bool = True) -> bool:
        return self.connections.connect(signal, slot, unique=unique)

    def manage_timer(self, timer: QTimer) -> QTimer:
        self._timers.add(timer)
        return timer

    def single_shot(self, interval_ms: int, callback: Callable[[], Any]) -> QTimer:
        timer = safe_single_shot(self.owner, interval_ms, callback)
        self._timers.add(timer)
        timer.destroyed.connect(lambda *_: self._timers.discard(timer))
        return timer

    def manage_worker(self, worker: Any) -> Any:
        self._workers.add(worker)
        return worker

    def release_worker(self, worker: Any) -> None:
        self._workers.discard(worker)

    def add_cleanup(self, callback: Callable[[], Any]) -> None:
        self._cleanup.append(callback)

    def activated(self) -> None:
        self.last_activated_at = monotonic()

    def deactivate(self) -> None:
        for timer in tuple(self._timers):
            try:
                if bool(timer.property("stopWhenHidden")):
                    timer.stop()
            except RuntimeError:
                self._timers.discard(timer)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self.generations.invalidate_all()
        for timer in tuple(self._timers):
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass
        self._timers.clear()
        for worker in tuple(self._workers):
            for method_name in ("cancel", "requestInterruption", "quit"):
                method = getattr(worker, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
            wait = getattr(worker, "wait", None)
            if callable(wait):
                try:
                    wait(150)
                except Exception:
                    pass
        self._workers.clear()
        for callback in reversed(self._cleanup):
            try:
                callback()
            except Exception:
                pass
        self._cleanup.clear()
        self.connections.disconnect_all()


class Debouncer(QObject):


    def __init__(self, interval_ms: int, callback: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self._callback = callback
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, int(interval_ms)))
        self._timer.timeout.connect(self._invoke)

    @property
    def timer(self) -> QTimer:
        return self._timer

    def trigger(self, *_args, **_kwargs) -> None:
        self._timer.start()

    def cancel(self) -> None:
        self._timer.stop()

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._invoke()

    def _invoke(self) -> None:
        self._callback()


@dataclass(slots=True)
class PageActivity:
    page_key: str
    policy: str
    last_used_at: float

    def idle_seconds(self) -> float:
        return max(0.0, monotonic() - self.last_used_at)


def dispose_widget_tree(widget) -> None:

    if widget is None:
        return
    dispose = getattr(widget, "dispose_page", None) or getattr(widget, "dispose", None)
    if callable(dispose):
        try:
            dispose()
        except Exception:
            pass
    try:
        from matplotlib.figure import Figure
        from matplotlib import pyplot as plt

        for child in widget.findChildren(QObject):
            figure = getattr(child, "figure", None)
            if isinstance(figure, Figure):
                try:
                    figure.clear()
                    plt.close(figure)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        widget.deleteLater()
    except RuntimeError:
        pass


__all__ = [
    "Debouncer",
    "GenerationGate",
    "ManagedPageResources",
    "PageActivity",
    "SignalConnectionBag",
    "safe_single_shot",
    "dispose_widget_tree",
]
