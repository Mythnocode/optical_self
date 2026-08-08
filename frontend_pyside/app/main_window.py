from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QSettings, QTimer, Qt, QVariantAnimation
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QToolButton, QWidget

from frontend_pyside.app.deferred_page import DeferredPageHost
from frontend_pyside.app.main_window_layout import build_main_window_layout
from frontend_pyside.app.page_registry import (
    IDLE_PRELOAD_SPECS,
    PAGE_SPEC_BY_KEY,
    PAGE_SPECS,
)
from frontend_pyside.app.shell_controller import ShellController
from frontend_pyside.core.constants import APP_NAME, APP_VERSION
from frontend_pyside.features.assistant import AiAssistantDialog, AssistantFloatingButton
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.lifecycle import dispose_widget_tree
from frontend_pyside.shared.performance import record_perf


class MainWindow(QMainWindow):


    EXPANDED_WIDTH = 252
    COLLAPSED_WIDTH = 76
    RESPONSIVE_THRESHOLD = 1220
    REAPER_INTERVAL_MS = 30_000

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.settings = QSettings()
        self.preferences = context.services.ui_preferences
        self._user_expanded = self.settings.value("main/sidebar_expanded", True, type=bool)
        self._auto_collapsed = False
        self._current_key = "home"
        self._pages: dict[str, DeferredPageHost] = {}
        self._page_last_used: dict[str, float] = {}
        self._idle_preload_queue = list(IDLE_PRELOAD_SPECS)

        self.setObjectName("mainWindow")
        self.setWindowTitle(f"{APP_NAME} · 前端 {APP_VERSION}")
        self.setMinimumSize(1080, 700)

        widgets = build_main_window_layout(self, PAGE_SPECS)
        self._layout_widgets = widgets
        self.central_root = widgets.central
        self.sidebar = widgets.sidebar
        self.brand_layout = widgets.brand_layout
        self.brand_icon = widgets.brand_icon
        self.brand_text = widgets.brand_text
        self.sidebar_toggle = widgets.sidebar_toggle
        self._nav_buttons: dict[str, QToolButton] = widgets.nav_buttons
        self._group_labels: list[QLabel] = widgets.group_labels
        self.connection_status = widgets.connection_status
        self.top_project = widgets.top_project
        self.top_version = widgets.top_version
        self.top_wave = widgets.top_wave
        self.top_surfaces = widgets.top_surfaces
        self.top_efficiency = widgets.top_efficiency
        self.top_mode = widgets.top_mode
        self.top_frontend = widgets.top_frontend
        self.display_mode = widgets.display_mode
        self.render_quality = widgets.render_quality
        self.stack = widgets.stack
        self.status_page = widgets.status_page
        self.status_source = widgets.status_source

        self.assistant_button = AssistantFloatingButton(self.central_root)
        self.assistant_button.clicked.connect(self._toggle_ai_assistant)
        self.assistant_button.show()

        for spec in PAGE_SPECS:
            self._nav_buttons[spec.key].clicked.connect(
                lambda checked=False, key=spec.key: self.navigate(key)
            )
        self.sidebar_toggle.clicked.connect(self._toggle_sidebar_by_user)

        self._sidebar_animation = QVariantAnimation(self)
        self._sidebar_animation.setDuration(190)
        self._sidebar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._sidebar_animation.valueChanged.connect(self._set_sidebar_width)
        self._sidebar_animation.finished.connect(self._sync_sidebar_contents)
        self._apply_sidebar_state(self._user_expanded, animate=False)

        self.shell_controller = ShellController(context, self)
        self.shell_controller.connectionChanged.connect(self._set_connection_status)

        context.project.project_changed.connect(self._refresh_project_meta)
        context.project.metrics_changed.connect(
            lambda _: self._refresh_project_meta(context.project.project)
        )
        self._refresh_project_meta(context.project.project)

        self.display_mode.setCurrentText(self.preferences.display_mode)
        self.render_quality.setCurrentText(self.preferences.render_quality)
        self.display_mode.currentTextChanged.connect(self.preferences.set_display_mode)
        self.render_quality.currentTextChanged.connect(self.preferences.set_render_quality)
        self.preferences.display_mode_changed.connect(self._apply_display_mode)
        self.preferences.render_quality_changed.connect(self._broadcast_render_quality)
        self._apply_display_mode(self.preferences.display_mode)

        self._page_reaper = QTimer(self)
        self._page_reaper.setInterval(self.REAPER_INTERVAL_MS)
        self._page_reaper.timeout.connect(self._release_idle_pages)
        self._page_reaper.start()

        self.navigate("home")
        QTimer.singleShot(0, self._position_assistant_button)
        QTimer.singleShot(500, self._idle_preload_next)
        QTimer.singleShot(800, self.shell_controller.check_backend_health)

    def _ensure_page(self, key: str, *, activate: bool = True) -> DeferredPageHost | None:
        existing = self._pages.get(key)
        if existing is not None:
            if activate:
                existing.activate()
            return existing
        spec = PAGE_SPEC_BY_KEY.get(key)
        if spec is None:
            return None
        host = DeferredPageHost(spec, self.context, self, auto_load=False)
        host.navigateRequested.connect(self.navigate)
        self._pages[key] = host
        self._page_last_used[key] = monotonic()
        self.stack.addWidget(host)
        if activate:
            host.activate()
        return host

    def _retry_page(self, key: str) -> None:
        host = self._pages.get(key)
        if isinstance(host, DeferredPageHost):
            host.retry()

    def navigate(self, key: str) -> None:
        timer = QElapsedTimer()
        timer.start()
        previous_key = self._current_key
        previous = self._pages.get(previous_key)
        if previous is not None and previous_key != key:
            previous.deactivate()
            self._page_last_used[previous_key] = monotonic()

        existing = self._pages.get(key)
        was_loaded = isinstance(existing, DeferredPageHost) and existing.loaded_page is not None
        page = self._ensure_page(key, activate=True)
        if page is None:
            return
        self._current_key = key
        self._page_last_used[key] = monotonic()
        self.stack.setCurrentWidget(page)
        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        spec = PAGE_SPEC_BY_KEY.get(key)
        self.status_page.setText(f"当前页面：{spec.title if spec else key}")
        dialog = getattr(self, "_assistant_dialog", None)
        if dialog is not None:
            dialog.set_page_context(key)
        self.shell_controller.record_page_view(key)
        QTimer.singleShot(
            0,
            lambda page_key=key, elapsed=timer.elapsed(), cached=was_loaded: record_perf(
                "page_navigation", elapsed, page=page_key, cached=cached
            ),
        )

    def release_page(self, key: str, *, force: bool = False) -> bool:
        if key == self._current_key:
            return False
        spec = PAGE_SPEC_BY_KEY.get(key)
        host = self._pages.get(key)
        if spec is None or host is None:
            return False
        if spec.lifetime == "resident" and not force:
            return False
        self._pages.pop(key, None)
        self._page_last_used.pop(key, None)
        self.stack.removeWidget(host)
        host.dispose()
        dispose_widget_tree(host)
        record_perf("page_released", 0.0, page=key, policy=spec.lifetime)
        return True

    def _release_idle_pages(self) -> None:
        now = monotonic()
        for key, host in tuple(self._pages.items()):
            if key == self._current_key:
                continue
            spec = PAGE_SPEC_BY_KEY.get(key)
            if spec is None or spec.lifetime == "resident":
                continue
            idle = now - max(self._page_last_used.get(key, 0.0), host.last_used_at)
            if idle >= float(spec.release_after_s):
                self.release_page(key)

    def _idle_preload_next(self) -> None:
        if not self.preferences.render_profile.idle_preload:
            return
        while self._idle_preload_queue:
            spec = self._idle_preload_queue.pop(0)
            if spec.key not in self._pages:
                
                
                self._ensure_page(spec.key, activate=False)
                record_perf("page_shell_preloaded", 0.0, page=spec.key)
                break
        if self._idle_preload_queue:
            QTimer.singleShot(600, self._idle_preload_next)

    def _apply_display_mode(self, mode: str) -> None:
        mode = str(mode or "标准")
        app = QApplication.instance()
        if app is not None:
            font = QFont(app.font())
            base = 12.5
            font.setPointSizeF({"紧凑": 11.5, "大字体": 14.0}.get(mode, base))
            app.setFont(font)
        self.setProperty("displayMode", mode)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def _broadcast_render_quality(self, quality: str) -> None:
        for host in self._pages.values():
            page = host.loaded_page
            callback = getattr(page, "set_render_quality", None) if page is not None else None
            if callable(callback):
                callback(str(quality))

    def _set_connection_status(self, text: str, tone: str) -> None:
        self.connection_status.setText(text)
        self.connection_status.setProperty("tone", tone)
        style = self.connection_status.style()
        style.unpolish(self.connection_status)
        style.polish(self.connection_status)

    def _ensure_ai_assistant(self) -> AiAssistantDialog:
        dialog = getattr(self, "_assistant_dialog", None)
        if dialog is None:
            dialog = AiAssistantDialog(self.context, self)
            dialog.set_page_context(self._current_key)
            dialog.visibilityChanged.connect(self.assistant_button.set_active)
            self._assistant_dialog = dialog
        return dialog

    def _open_ai_assistant(self) -> None:
        self._ensure_ai_assistant().show_anchored()

    def _toggle_ai_assistant(self) -> None:
        self._ensure_ai_assistant().toggle()

    def _position_assistant_button(self) -> None:
        if not hasattr(self, "assistant_button"):
            return
        margin = 18
        x = max(0, self.central_root.width() - self.assistant_button.width() - margin)
        y = max(0, self.central_root.height() - self.assistant_button.height() - margin)
        self.assistant_button.move(x, y)
        self.assistant_button.raise_()

    def _reposition_ai_assistant(self) -> None:
        dialog = getattr(self, "_assistant_dialog", None)
        if dialog is not None and dialog.isVisible():
            if getattr(dialog, "_user_moved", False):
                dialog.clamp_to_parent()
            else:
                dialog.anchor_to_parent()

    def _refresh_project_meta(self, project) -> None:
        metrics = getattr(project, "metrics", {}) or {}
        efficiency = metrics.get("coupling_efficiency")
        dirty = " *" if getattr(self.context.project, "dirty", False) else ""
        self.top_project.setText(f"当前项目：{project.name}{dirty}")
        self.top_version.setText(f"版本 {project.version}")
        self.top_wave.setText(f"λ {project.wavelength_nm:.0f} nm")
        self.top_surfaces.setText(f"表面 {len(project.surfaces)}")
        self.top_efficiency.setText(
            f"效率 {100 * float(efficiency):.1f}%" if efficiency is not None else "效率 待计算"
        )

    def _toggle_sidebar_by_user(self) -> None:
        self._user_expanded = not self._effective_sidebar_expanded()
        self._auto_collapsed = False
        self.settings.setValue("main/sidebar_expanded", self._user_expanded)
        self._apply_sidebar_state(self._user_expanded, animate=True)

    def _effective_sidebar_expanded(self) -> bool:
        return self.sidebar.width() > (self.COLLAPSED_WIDTH + self.EXPANDED_WIDTH) // 2

    def _apply_sidebar_state(self, expanded: bool, *, animate: bool) -> None:
        target = self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH
        if animate:
            self._sidebar_animation.stop()
            self._sidebar_animation.setStartValue(self.sidebar.width())
            self._sidebar_animation.setEndValue(target)
            self._sidebar_animation.start()
        else:
            self._set_sidebar_width(target)
            self._sync_sidebar_contents()

    def _set_sidebar_width(self, value) -> None:
        width = int(value)
        self.sidebar.setFixedWidth(width)
        for button in self._nav_buttons.values():
            button.setFixedWidth(width)

    def _sync_sidebar_contents(self) -> None:
        expanded = self._effective_sidebar_expanded()
        self.brand_icon.setVisible(expanded)
        self.brand_text.setVisible(expanded)
        self.brand_layout.setContentsMargins(14, 10, 10, 10) if expanded else self.brand_layout.setContentsMargins(22, 10, 22, 10)
        for label in self._group_labels:
            label.setVisible(expanded)
        for spec in PAGE_SPECS:
            button = self._nav_buttons[spec.key]
            button.setText(spec.title if expanded else "")
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if expanded
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            button.setToolTip(spec.title)
        self.connection_status.setVisible(expanded)
        self._set_sidebar_width(self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH)
        self.sidebar_toggle.setIcon(
            icon("chevron_left" if expanded else "chevron_right", theme.TEXT_INVERSE, 18)
        )
        self.sidebar_toggle.setToolTip("收起主导航" if expanded else "展开主导航")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_assistant_button()
        self._reposition_ai_assistant()
        if self.width() < self.RESPONSIVE_THRESHOLD and self._effective_sidebar_expanded():
            self._auto_collapsed = True
            self._apply_sidebar_state(False, animate=True)
        elif self.width() >= self.RESPONSIVE_THRESHOLD and self._auto_collapsed and self._user_expanded:
            self._auto_collapsed = False
            self._apply_sidebar_state(True, animate=True)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._reposition_ai_assistant()

    def closeEvent(self, event) -> None:
        dialog = getattr(self, "_assistant_dialog", None)
        if dialog is not None:
            dialog.shutdown()
        self.settings.setValue("main/window_geometry", self.saveGeometry())
        self.settings.setValue("main/window_state", self.saveState())
        self.settings.setValue("main/sidebar_expanded", self._user_expanded)
        self._page_reaper.stop()
        watcher = getattr(self.context.services, "job_watcher", None)
        if watcher is not None:
            try:
                watcher.unsubscribe_all()
                watcher.disconnect()
            except RuntimeError:
                pass
        usage = getattr(self.context.services, "usage", None)
        if usage is not None:
            usage.close()
        for key in tuple(self._pages):
            host = self._pages.pop(key)
            host.dispose()
        super().closeEvent(event)

    def restore_saved_window_state(self) -> None:
        geometry = self.settings.value("main/window_geometry")
        state = self.settings.value("main/window_state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
