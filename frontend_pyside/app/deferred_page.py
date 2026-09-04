
from __future__ import annotations

from time import monotonic
import traceback

from PySide6.QtCore import QElapsedTimer, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from frontend_pyside.app.startup import append_startup_log
from frontend_pyside.shared.components.errors import PageLoadErrorWidget
from frontend_pyside.shared.lifecycle import dispose_widget_tree, safe_single_shot
from frontend_pyside.shared.performance import record_perf


class DeferredPageHost(QWidget):


    navigateRequested = Signal(str)
    assistantActionRequested = Signal(object)
    pageReady = Signal(object)

    def __init__(self, spec, context, parent=None, *, auto_load: bool = False) -> None:
        super().__init__(parent)
        self.spec = spec
        self.context = context
        self._loaded_page: QWidget | None = None
        self._loading = False
        self._active = False
        self._disposed = False
        self.last_used_at = monotonic()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._loading_label = QLabel(f"{spec.title}将在首次打开时加载。")
        self._loading_label.setObjectName("pageLoadingPlaceholder")
        self._layout.addWidget(self._loading_label)
        self._layout.addStretch(1)
        self._deferred_timers: set[QTimer] = set()
        if auto_load:
            self._defer(0, self.activate)

    def _defer(self, interval_ms: int, callback) -> None:
        timer = safe_single_shot(self, interval_ms, callback)
        self._deferred_timers.add(timer)
        timer.destroyed.connect(lambda *_: self._deferred_timers.discard(timer))

    @property
    def loaded_page(self) -> QWidget | None:
        return self._loaded_page

    @property
    def is_loaded(self) -> bool:
        return self._loaded_page is not None

    def activate(self) -> None:
        if self._disposed:
            return
        self._active = True
        self.last_used_at = monotonic()
        if self._loaded_page is None:
            self._defer(0, self.load)
            return
        callback = getattr(self._loaded_page, "on_activated", None)
        if callable(callback):
            callback()

    def deactivate(self) -> None:
        if self._disposed:
            return
        self._active = False
        self.last_used_at = monotonic()
        callback = getattr(self._loaded_page, "on_deactivated", None)
        if callable(callback):
            callback()

    def load(self) -> None:
        if self._disposed or self._loading or self._loaded_page is not None:
            return
        self._loading = True
        timer = QElapsedTimer()
        timer.start()
        try:
            self._loading_label.setText(f"正在打开{self.spec.title}…")
            import_timer = QElapsedTimer()
            import_timer.start()
            factory = self.spec.load_factory()
            record_perf("page_import", import_timer.elapsed(), page=self.spec.key)
            build_timer = QElapsedTimer()
            build_timer.start()
            page = factory(self.context)
            record_perf("page_widget_build", build_timer.elapsed(), page=self.spec.key)
            if hasattr(page, "navigateRequested"):
                page.navigateRequested.connect(self.navigateRequested.emit)
            if hasattr(page, "assistantActionRequested"):
                page.assistantActionRequested.connect(self.assistantActionRequested.emit)
            self._install(page)
            record_perf("page_build", timer.elapsed(), page=self.spec.key)
            self.pageReady.emit(page)
            if self._active:
                callback = getattr(page, "on_activated", None)
                if callable(callback):
                    callback()
        except Exception as exc:
            details = traceback.format_exc()
            append_startup_log(f"PAGE LOAD FAILED: {self.spec.key}", details)
            error = PageLoadErrorWidget(self.spec.title, str(exc), details)
            error.retryRequested.connect(self.retry)
            self._install(error)
            record_perf("page_build_failed", timer.elapsed(), page=self.spec.key)
        finally:
            self._loading = False

    def retry(self) -> None:
        page = self._loaded_page
        self._loaded_page = None
        if page is not None:
            self._layout.removeWidget(page)
            dispose_widget_tree(page)
        self._loading_label = QLabel(f"正在重新打开{self.spec.title}…")
        self._loading_label.setObjectName("pageLoadingPlaceholder")
        self._layout.addWidget(self._loading_label)
        self._defer(0, self.load)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        for timer in tuple(self._deferred_timers):
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass
        self._deferred_timers.clear()
        page, self._loaded_page = self._loaded_page, None
        if page is not None:
            self._layout.removeWidget(page)
            dispose_widget_tree(page)

    def _install(self, page: QWidget) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not page:
                widget.deleteLater()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(page, 1)
        self._loaded_page = page


__all__ = ["DeferredPageHost"]
