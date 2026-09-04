from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPoint, QRect, QSettings, QTimer, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QFrame, QLineEdit, QLabel, QMainWindow, QMessageBox, QMenu, QProgressBar, QTabBar, QToolButton, QWidget

from frontend_pyside.app.deferred_page import DeferredPageHost
from frontend_pyside.app.main_window_layout import build_main_window_layout
from frontend_pyside.app.compact_shell import ShellAction
from frontend_pyside.app.page_registry import (
    IDLE_PRELOAD_SPECS,
    PAGE_SPEC_BY_KEY,
    PAGE_SPECS,
)
from frontend_pyside.app.shell_controller import ShellController
from frontend_pyside.core.constants import APP_NAME, APP_VERSION
from frontend_pyside.features.assistant import AiAssistantDialog, AssistantFloatingButton
from frontend_pyside.features.assistant.actions import normalize_action
from frontend_pyside.features.optimization.task_window import OptimizationTaskWindow
from frontend_pyside.features.machine_learning.task_window import MachineLearningPredictionTaskWindow
from frontend_pyside.shared.icons import icon
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.lifecycle import dispose_widget_tree
from frontend_pyside.shared.performance import record_perf
from frontend_pyside.state.session_recovery import SessionRecoveryStore


class _DraggableToolButton(QToolButton):
    """Click-or-drag floating launcher used by the global toolbox."""

    dragFinished = Signal(QPoint)
    DRAG_THRESHOLD = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._press_global: QPoint | None = None
        self._start_pos = QPoint()
        self._dragging = False
        self._user_moved = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_pos = self.pos()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() < self.DRAG_THRESHOLD:
            return
        self._dragging = True
        self._user_moved = True
        target = self._start_pos + delta
        parent = self.parentWidget()
        if parent is not None:
            target.setX(max(0, min(target.x(), max(0, parent.width() - self.width()))))
            target.setY(max(0, min(target.y(), max(0, parent.height() - self.height()))))
        self.move(target)
        self.raise_()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        dragged = self._dragging
        self._press_global = None
        self._dragging = False
        if dragged and event.button() == Qt.MouseButton.LeftButton:
            self.setDown(False)
            self.dragFinished.emit(self.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):


    EXPANDED_WIDTH = 252
    COLLAPSED_WIDTH = 76
    RESPONSIVE_THRESHOLD = 1220
    DENSE_WORK_PAGES = {"simulation", "optimization", "machine_learning", "explainability", "teaching", "tasks"}
    DENSE_EXPANDED_MIN_WORKSPACE = 1240
    REAPER_INTERVAL_MS = 30_000

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.settings = QSettings()
        self.preferences = context.services.ui_preferences
        self._current_key = "home"
        self._pages: dict[str, DeferredPageHost] = {}
        self._page_last_used: dict[str, float] = {}
        self._idle_preload_queue = list(IDLE_PRELOAD_SPECS)
        self.recovery_store = SessionRecoveryStore(context.project, self)
        self._drawer_category = ""
        self._document_routes: dict[str, tuple[str, str, dict, str, str]] = {}
        self._current_document_key = "home"
        self._optimization_task_window: OptimizationTaskWindow | None = None
        self._ml_prediction_task_window: MachineLearningPredictionTaskWindow | None = None

        self.setObjectName("mainWindow")
        self.setWindowTitle(f"{APP_NAME} · {APP_VERSION}")
        self.setMinimumSize(720, 600)

        widgets = build_main_window_layout(self, PAGE_SPECS)
        self._layout_widgets = widgets
        self.central_root = widgets.central
        self.rail = widgets.rail
        self.drawer = widgets.drawer
        self.document_tabs = widgets.document_tabs
        self.stack = widgets.stack
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
        self.status_page = widgets.status_page
        self.status_source = widgets.status_source
        self.footer_efficiency = widgets.footer_efficiency
        self.footer_notice = widgets.footer_notice
        self.footer_result_button = widgets.footer_result_button
        self.footer_tasks_button = widgets.footer_tasks_button
        self.command_buttons = widgets.command_buttons

        # 左下工具箱与右下 AI 分担两种不同职责：工具箱负责能力入口，
        # AI 负责上下文辅助。工具箱覆盖主工作区，不挤压中央画布。
        self.drawer.setParent(self.central_root)
        self.toolbox_button = _DraggableToolButton(self.central_root)
        self.toolbox_button.setObjectName("toolboxFloatingButton")
        self.toolbox_button.setText("工具")
        self.toolbox_button.setToolTip("打开工具箱；可搜索全部平台功能")
        self.toolbox_button.setFixedSize(46, 46)
        self.toolbox_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toolbox_button.clicked.connect(self._toggle_toolbox)
        self.toolbox_button.dragFinished.connect(lambda pos: self.settings.setValue("ui/toolbox_floating_pos", pos))
        saved_tool_pos = self.settings.value("ui/toolbox_floating_pos")
        if isinstance(saved_tool_pos, QPoint):
            self.toolbox_button.move(saved_tool_pos)
            self.toolbox_button._user_moved = True
        self.toolbox_button.show()

        self.assistant_button = AssistantFloatingButton(self.central_root)
        self.assistant_button.clicked.connect(self._toggle_ai_assistant)
        if hasattr(self.assistant_button, "dragFinished"):
            self.assistant_button.dragFinished.connect(lambda pos: self.settings.setValue("ui/assistant_floating_pos", pos))
        saved_ai_pos = self.settings.value("ui/assistant_floating_pos")
        if isinstance(saved_ai_pos, QPoint):
            self.assistant_button.move(saved_ai_pos)
            self.assistant_button._user_moved = True
        self.assistant_button.show()

        self.rail.homeRequested.connect(lambda: self.navigate("home"))
        self.rail.categoryRequested.connect(self._toggle_category_drawer)
        self.drawer.closeRequested.connect(self._close_tool_drawer)
        self.drawer.actionTriggered.connect(self._launch_shell_action)
        self.document_tabs.pageRequested.connect(self._activate_document)
        self.document_tabs.pageCloseRequested.connect(self._close_document_tab)
        home_button = self.central_root.findChild(QToolButton, "shellHomeButton")
        if home_button is not None:
            home_button.clicked.connect(lambda: self.navigate("home", update_document=False))
        self._configure_command_bar()
        self.footer_result_button.clicked.connect(
            lambda: self.navigate_action("simulation", "simulation.result")
        )
        self.footer_tasks_button.clicked.connect(lambda: self.navigate("tasks"))

        # 全局壳层只保留真正可用的通用操作。保存直接生成项目版本；
        # 撤销/重做由各具体编辑器自行管理，避免显示一个并不存在的“全局撤销”。
        for button in self.central_root.findChildren(QToolButton):
            action = str(button.property("shellAction") or "")
            if action == "save":
                button.clicked.connect(self._save_project_version)
            elif action in {"undo", "redo"}:
                button.hide()
        menu_button = self.central_root.findChild(QToolButton, "shellMenuButton")
        if menu_button is not None:
            menu_button.clicked.connect(lambda: self._toggle_category_drawer("engineering"))

        self.shell_controller = ShellController(context, self)
        self.shell_controller.connectionChanged.connect(self._set_connection_status)

        context.project.project_changed.connect(self._refresh_project_meta)
        context.project.metrics_changed.connect(
            lambda _: self._refresh_project_meta(context.project.project)
        )
        for signal in (
            context.project.formal_result_changed,
            context.project.design_revision_changed,
            context.project.findings_changed,
            context.registry.current_model_changed,
            context.tasks.tasks_changed,
        ):
            signal.connect(lambda *_: self._refresh_assistant_attention())
        self._refresh_project_meta(context.project.project)
        self._refresh_assistant_attention()

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
        QTimer.singleShot(0, self._position_floating_tools)
        QTimer.singleShot(500, self._idle_preload_next)
        QTimer.singleShot(800, self.shell_controller.check_backend_health)
        QTimer.singleShot(350, self._offer_workspace_recovery)


    def _configure_command_bar(self) -> None:
        """Top level switches stable work environments, not mixed actions.

        Simulation contains its own run button and analysis selector.  Optimisation,
        surrogate modelling and teaching are peer workspaces.  The searchable
        toolbox remains the capability catalogue / shortcut layer.
        """
        simulation = self.command_buttons.get("simulation")
        if simulation is not None:
            simulation.clicked.connect(lambda: self.navigate("simulation", update_document=False))

        optimization = self.command_buttons.get("optimization")
        if optimization is not None:
            optimization.clicked.connect(lambda: self.navigate("optimization", update_document=False))

        surrogate = self.command_buttons.get("surrogate")
        if surrogate is not None:
            surrogate.clicked.connect(lambda: self.navigate("machine_learning", update_document=False))

        explainability = self.command_buttons.get("explainability")
        if explainability is not None:
            explainability.clicked.connect(lambda: self.navigate("explainability", update_document=False))

        teaching = self.command_buttons.get("teaching")
        if teaching is not None:
            teaching.clicked.connect(lambda: self.navigate("teaching", update_document=False))

    def _offer_workspace_recovery(self) -> None:
        if not self.recovery_store.has_recovery():
            return
        answer = QMessageBox.question(
            self,
            "恢复工作状态",
            "检测到上次未保存的工作状态。是否恢复？\n\n" + self.recovery_store.summary(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if self.recovery_store.restore():
                self.statusBar().showMessage("已恢复上次未保存的工作状态", 5000)
                self._refresh_project_meta(self.context.project.project)
            else:
                QMessageBox.warning(self, "恢复失败", "恢复文件无法读取，已保留当前默认项目。")
                self.recovery_store.clear()
        else:
            self.recovery_store.clear()

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
        host.assistantActionRequested.connect(self._handle_assistant_action)
        # Deferred pages finalize their child geometry after navigation. Reposition
        # floating launchers when that geometry actually exists so they never sit
        # on top of the parameter navigator merely because the first layout pass
        # happened before the page finished loading.
        host.pageReady.connect(lambda _page: QTimer.singleShot(0, self._position_floating_tools))
        if key == "machine_learning":
            host.pageReady.connect(self._wire_machine_learning_page)
        self._pages[key] = host
        self._page_last_used[key] = monotonic()
        self.stack.addWidget(host)
        if activate:
            host.activate()
        return host

    def _wire_machine_learning_page(self, page) -> None:
        signal = getattr(page, "inversePredictionRequested", None)
        if signal is not None and not bool(page.property("inversePredictionConnected")):
            signal.connect(lambda: self._open_optimization_task("optimization.ml_inverse_prediction", {}))
            page.setProperty("inversePredictionConnected", True)

    def _retry_page(self, key: str) -> None:
        host = self._pages.get(key)
        if isinstance(host, DeferredPageHost):
            host.retry()

    def navigate(self, key: str, *, update_document: bool = True) -> None:
        key = str(key or "home")
        if key not in PAGE_SPEC_BY_KEY:
            return
        workspace_key = {
            "simulation": "simulation",
            "optimization": "optimization",
            "machine_learning": "surrogate",
            "explainability": "explainability",
            "teaching": "teaching",
        }.get(key, "")
        for command_key, button in self.command_buttons.items():
            button.setChecked(bool(workspace_key and command_key == workspace_key))
        if key == self._current_key and key in self._pages:
            spec = PAGE_SPEC_BY_KEY.get(key)
            if spec is not None and update_document:
                self._register_document(key, key, "", {}, spec.title, spec.icon_name)
                self.document_tabs.open_page(key, spec.title, spec.icon_name)
                self._current_document_key = key
            self._close_tool_drawer()
            QTimer.singleShot(0, self._position_floating_tools)
            return

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
        spec = PAGE_SPEC_BY_KEY.get(key)
        if spec is not None:
            if update_document:
                self._register_document(key, key, "", {}, spec.title, spec.icon_name)
                self.document_tabs.open_page(key, spec.title, spec.icon_name)
                self._current_document_key = key
            self.status_page.setText(f"当前页面：{spec.title}")
        self.footer_notice.setText(spec.title if spec is not None else "就绪")
        self._sync_rail_for_page(key)
        self._close_tool_drawer()

        dialog = getattr(self, "_assistant_dialog", None)
        if dialog is not None:
            dialog.set_page_context(key)
        self.shell_controller.record_page_view(key)
        QTimer.singleShot(0, self._position_assistant_button)
        QTimer.singleShot(0, self._position_floating_tools)
        QTimer.singleShot(
            0,
            lambda page_key=key, elapsed=timer.elapsed(), cached=was_loaded: record_perf(
                "page_navigation", elapsed, page=page_key, cached=cached
            ),
        )

    def _register_document(
        self, document_key: str, page_key: str, target: str, payload: dict | None, title: str, icon_name: str = ""
    ) -> None:
        self._document_routes[str(document_key)] = (
            str(page_key), str(target or ""), dict(payload or {}), str(title), str(icon_name or "")
        )

    def _activate_document(self, document_key: str) -> None:
        document_key = str(document_key or "home")
        route = self._document_routes.get(document_key)
        if route is None:
            if document_key in PAGE_SPEC_BY_KEY:
                self.navigate(document_key)
            return
        page_key, target, payload, title, icon_name = route
        self._current_document_key = document_key
        self.document_tabs.open_page(document_key, title, icon_name)
        self.navigate_action(page_key, target, payload, update_document=False)

    def navigate_action(
        self,
        page_key: str,
        target: str = "",
        payload: dict | None = None,
        *,
        update_document: bool = True,
        document_key: str = "",
        document_title: str = "",
        document_icon: str = "",
    ) -> None:
        """Open a task without forcing the user through separate page workspaces.

        A shell action may own its own document tab (for example ``模场匹配`` or
        ``正向预测``) while reusing the same underlying page implementation.
        Preparing a document never starts a long-running backend calculation.
        """
        if str(page_key) == "optimization" and str(target) in {
            "optimization.scan", "optimization.tolerance", "optimization.variables",
            "optimization.inverse_design", "optimization.ml_inverse_prediction", "optimization.validation",
        }:
            self._open_optimization_task(str(target), dict(payload or {}))
            return
        if str(page_key) == "machine_learning" and str(target) == "machine_learning.prediction":
            self._open_ml_prediction_task()
            return
        if update_document and document_key:
            title = document_title or document_key
            self._register_document(document_key, page_key, target, payload, title, document_icon)
            self.document_tabs.open_page(document_key, title, document_icon)
            self._current_document_key = document_key
        self.navigate(page_key, update_document=not bool(document_key) if update_document else False)
        if not target:
            return
        host = self._pages.get(page_key)
        if host is None:
            return
        action = {"target": str(target), "level": "navigate", "payload": dict(payload or {})}

        def deliver(page) -> None:
            handler = getattr(page, "handle_assistant_action", None)
            if callable(handler):
                handler(action)

        if host.loaded_page is not None:
            QTimer.singleShot(0, lambda page=host.loaded_page: deliver(page))
        else:
            host.pageReady.connect(deliver, Qt.ConnectionType.SingleShotConnection)

    def _close_document_tab(self, key: str) -> None:
        key = str(key or "")
        if not key or key == "home":
            return
        is_current = key == self._current_document_key
        self.document_tabs.close_key(key)
        self._document_routes.pop(key, None)
        if not is_current:
            return
        remaining = [
            str(self.document_tabs.tabData(i) or "")
            for i in range(self.document_tabs.count())
            if str(self.document_tabs.tabData(i) or "")
        ]
        next_key = remaining[-1] if remaining else "home"
        self._activate_document(next_key)

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
            base = 13.5
            font.setPointSizeF({"紧凑": 12.25, "大字体": 15.5}.get(mode, base))
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
        full_text = str(text or "").strip()
        lowered = full_text.lower()
        if "未连接" in full_text or "refused" in lowered or "failed" in lowered or "error" in lowered:
            compact = "● 后端未连接"
        elif "连接" in full_text or "正常" in full_text or "ready" in lowered or "ok" in lowered:
            compact = "●"
        else:
            compact = "●"
        self.connection_status.setText(compact)
        self.connection_status.setToolTip(full_text or compact)
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
            dialog.actionRequested.connect(self._handle_assistant_action)
            self._assistant_dialog = dialog
        return dialog

    def _refresh_assistant_attention(self) -> None:
        count = 0
        details: list[str] = []
        formal = getattr(self.context.project, "formal_result", None)
        if isinstance(formal, dict) and formal:
            current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
            formal_revision = formal.get("design_revision", formal.get("project_revision", formal.get("revision")))
            if isinstance(formal_revision, (int, float)) and current_revision and int(formal_revision) != current_revision:
                count += 1; details.append("正式结果已与当前系统不同步")
            status = str(formal.get("status", "") or "").lower()
            if status in {"failed", "cancelled", "error"} or formal.get("converged") is False:
                count += 1; details.append("正式计算需要处理")
        failed_tasks = 0
        for task in list(getattr(self.context.tasks, "tasks", []) or []):
            if not isinstance(task, dict):
                continue
            if str(task.get("status", "") or "").lower() in {"失败", "failed", "error"}:
                failed_tasks += 1
        if failed_tasks:
            count += 1; details.append(f"{failed_tasks} 个任务失败")
        try:
            model_id = str(getattr(self.context.registry, "current_model_id", "") or "")
            model = self.context.registry.model(model_id) if model_id else None
        except Exception:
            model = None
        if isinstance(model, dict):
            metrics = dict(model.get("test_metrics", {}) or {})
            r2 = metrics.get("r2", metrics.get("test_r2"))
            if isinstance(r2, (int, float)) and float(r2) < 0.0:
                count += 1; details.append("当前模型独立测试表现较差")
        stale = sum(1 for row in list(getattr(self.context.project, "findings", []) or []) if isinstance(row, dict) and str(row.get("status", "")) == "需更新")
        if stale:
            count += 1; details.append(f"{stale} 条分析记录需要更新")
        self.assistant_button.set_attention_count(count, "；".join(details))

    @staticmethod
    def _assistant_page_for_target(target: str) -> str:
        prefix = str(target or "").split(".", 1)[0]
        return {
            "simulation": "simulation",
            "machine_learning": "machine_learning",
            "explainability": "explainability",
            "optimization": "optimization",
            "teaching": "teaching",
            "tasks": "tasks",
            "home": "home",
        }.get(prefix, "")

    def _handle_assistant_action(self, action: object) -> None:
        payload = normalize_action(dict(action) if isinstance(action, dict) else {})
        target = str(payload.get("target", "") or "")
        level = str(payload.get("level", "navigate") or "navigate")
        # The assistant is allowed to navigate and prepare only. Execute always requires
        # an explicit page-level confirmation and is therefore rejected here.
        if level == "execute" or bool(payload.get("starts_job")):
            self.statusBar().showMessage("智能助手不会未经确认直接启动耗时计算。请在目标页面确认执行。", 5000)
            return
        if bool(payload.get("disabled")):
            self.statusBar().showMessage("当前条件还不满足这项操作，请先处理智能助手提示的前置条件。", 5000)
            return
        page_key = self._assistant_page_for_target(target)
        if not page_key:
            return
        if page_key == "optimization" and target in {
            "optimization.scan", "optimization.tolerance", "optimization.variables",
            "optimization.inverse_design", "optimization.ml_inverse_prediction", "optimization.validation",
        }:
            self._open_optimization_task(target, dict(payload.get("payload") or {}))
            task_window = self._optimization_task_window
            page = task_window.page if task_window is not None else None
            if page is not None:
                target_provider = getattr(page, "assistant_action_target_widget", None)
                target_widget = target_provider(payload) if callable(target_provider) else page
                QTimer.singleShot(0, lambda widget=target_widget: self._highlight_assistant_target(widget))
            return
        if target == "machine_learning.prediction":
            self._open_ml_prediction_task()
            window = self._ml_prediction_task_window
            page = window.page if window is not None else None
            if page is not None:
                target_provider = getattr(page, "assistant_action_target_widget", None)
                target_widget = target_provider(payload) if callable(target_provider) else page
                QTimer.singleShot(0, lambda widget=target_widget: self._highlight_assistant_target(widget))
            return
        self.navigate(page_key)
        host = self._pages.get(page_key)
        if host is None:
            return

        def deliver(page) -> None:
            handler = getattr(page, "handle_assistant_action", None)
            if callable(handler):
                handler(payload)
            target_provider = getattr(page, "assistant_action_target_widget", None)
            target_widget = target_provider(payload) if callable(target_provider) else page
            QTimer.singleShot(0, lambda widget=target_widget: self._highlight_assistant_target(widget))
            self.statusBar().showMessage(
                "智能助手已定位并准备下一步；不会自动启动计算。" if level == "prepare" else "智能助手已定位到建议位置。",
                4200,
            )

        if host.loaded_page is not None:
            QTimer.singleShot(0, lambda page=host.loaded_page: deliver(page))
        else:
            host.pageReady.connect(deliver, Qt.ConnectionType.SingleShotConnection)

    def _highlight_assistant_target(self, widget: QWidget | None) -> None:
        # Highlight the control explicitly registered by the destination page.
        # Falling back to the page root is deterministic; focusWidget() is not
        # used because keyboard focus can point at an unrelated control.
        if widget is None:
            return
        try:
            if widget.window() is not self:
                return
            widget.setProperty("assistantHighlight", True)
            style = widget.style(); style.unpolish(widget); style.polish(widget)
        except RuntimeError:
            return
        def clear(target=widget):
            try:
                target.setProperty("assistantHighlight", False)
                target.style().unpolish(target); target.style().polish(target)
            except RuntimeError:
                pass
        QTimer.singleShot(1800, clear)

    def _open_ai_assistant(self) -> None:
        self._ensure_ai_assistant().show_anchored()

    def _toggle_ai_assistant(self) -> None:
        self._ensure_ai_assistant().toggle()

    def _floating_task_progress_top(self) -> int | None:
        """Return the top edge of a visible task progress/status strip.

        Floating launchers may cover plots, but they must not cover primary task
        status/progress/actions. Focused optimisation pages place that strip along
        the lower result edge, so reserve it dynamically instead of guessing a
        fixed footer height.
        """
        if self._current_key != "optimization":
            return None
        host = self._pages.get("optimization")
        page = host.loaded_page if host is not None else None
        if page is None:
            return None
        try:
            panels = page.findChildren(QFrame, "taskProgressPanel")
            # The optimization result area keeps an idle status panel visible even
            # before a task starts.  Treating that static hint as live progress
            # pushed the toolbox launcher up onto the result-view tab/header.
            # Reserve space only for a panel that actually exposes a progress bar.
            visible_panels = []
            for panel in panels:
                if not panel.isVisible() or panel.visibleRegion().isEmpty():
                    continue
                bars = panel.findChildren(QProgressBar)
                if any(bar.isVisible() and not bar.visibleRegion().isEmpty() for bar in bars):
                    visible_panels.append(panel)
            if not visible_panels:
                return None
            tops = [panel.mapTo(self.central_root, QPoint(0, 0)).y() for panel in visible_panels]
            return min(tops) if tops else None
        except RuntimeError:
            return None

    def _floating_exclusion_rects(self, *, include_plot: bool = True) -> list[QRect]:
        """Return visible interaction/plot regions floating launchers should avoid.

        This is intentionally geometric rather than page-name-specific: newly added
        controls automatically participate without another hard-coded offset.
        User-dragged positions remain under user control; avoidance selects only the
        default/restored automatic position.
        """
        rects: list[QRect] = []
        host = self._pages.get(self._current_key)
        page = host.loaded_page if host is not None else None
        if page is None:
            return rects
        classes = (QAbstractButton, QComboBox, QLineEdit, QProgressBar, QTabBar)
        try:
            for widget in page.findChildren(QWidget):
                if widget is self.toolbox_button or widget is self.assistant_button:
                    continue
                if not widget.isVisible() or widget.visibleRegion().isEmpty():
                    continue
                class_name = type(widget).__name__.lower()
                important = isinstance(widget, classes)
                if include_plot and ("figurecanvas" in class_name or widget.objectName() in {"plotCanvas", "resultCanvas"}):
                    important = True
                if not important:
                    continue
                pos = widget.mapTo(self.central_root, QPoint(0, 0))
                rect = QRect(pos, widget.size()).adjusted(-6, -6, 6, 6)
                # Ignore microscopic internals/badges that do not represent a usable target.
                if rect.width() >= 24 and rect.height() >= 20:
                    rects.append(rect)
        except RuntimeError:
            return []
        return rects

    @staticmethod
    def _overlap_area(left: QRect, right: QRect) -> int:
        inter = left.intersected(right)
        return max(0, inter.width()) * max(0, inter.height()) if not inter.isEmpty() else 0

    def _avoid_floating_hotspots(self, button: QWidget, preferred: QPoint, *, side: str) -> QPoint:
        width = max(0, self.central_root.width())
        height = max(0, self.central_root.height())
        margin = 14
        max_x = max(0, width - button.width())
        max_y = max(0, height - button.height())
        preferred = QPoint(max(0, min(preferred.x(), max_x)), max(0, min(preferred.y(), max_y)))
        exclusions = self._floating_exclusion_rects(include_plot=True)
        if not exclusions:
            return preferred
        edge_x = margin if side == "left" else max(margin, max_x - margin)
        ys = [
            preferred.y(), 74, 124, int(height * 0.24), int(height * 0.38),
            int(height * 0.54), int(height * 0.70), max(70, max_y - 96),
        ]
        # Edge positions are preferred; the opposite edge is a fallback when a
        # docked inspector consumes the normal side.
        other_x = max(margin, max_x - margin) if side == "left" else margin
        candidates = [preferred]
        candidates.extend(QPoint(edge_x, max(0, min(y, max_y))) for y in ys)
        candidates.extend(QPoint(other_x, max(0, min(y, max_y))) for y in ys)
        best = preferred
        best_score = float("inf")
        for candidate in candidates:
            rect = QRect(candidate, button.size())
            overlap = sum(self._overlap_area(rect, exclusion) for exclusion in exclusions)
            travel = abs(candidate.x() - preferred.x()) + abs(candidate.y() - preferred.y())
            score = overlap * 1000 + travel
            if score < best_score:
                best, best_score = candidate, score
                if overlap == 0 and travel == 0:
                    break
        return best

    def _position_assistant_button(self) -> None:
        if not hasattr(self, "assistant_button"):
            return
        if getattr(self.assistant_button, "_user_moved", False):
            x = max(0, min(self.assistant_button.x(), self.central_root.width() - self.assistant_button.width()))
            y = max(0, min(self.assistant_button.y(), self.central_root.height() - self.assistant_button.height()))
        else:
            margin = 18
            x = max(0, self.central_root.width() - self.assistant_button.width() - margin)
            # Keep the floating launcher out of bottom status/progress/action rows.
            # A plain 18 px bottom margin covered completed-task progress bars and
            # footer buttons on 1366×768.  Reserve one compact control-row height
            # everywhere; users can still drag the launcher if a plot annotation is
            # more important in a particular view.
            bottom_clearance = 132
            y = max(72 if self._current_key == "teaching" else 0, self.central_root.height() - self.assistant_button.height() - bottom_clearance)
            # When the teaching inspector is docked on the right, keep the AI
            # launcher over the optical bench rather than covering explanation
            # text/actions in the inspector.
            if self._current_key == "teaching":
                # The teaching page can become much taller than the viewport.  A
                # bottom-anchored floating launcher then sits on top of “原理与验证”
                # and its blue follow-up action after the page is scrolled.  Keep
                # both auxiliary launchers over the optical canvas instead: away
                # from the vertical tool strips and away from text/action cards.
                x = max(0, self.central_root.width() - self.assistant_button.width() - 72)
                y = max(110, int(self.central_root.height() * 0.36))
            elif self._current_key == "optimization":
                # Research result/status cards live near the bottom of compact
                # pages.  Mid-height is normally plot/preview territory and is a
                # safer default for the auxiliary AI launcher.
                y = max(110, int(self.central_root.height() * 0.48))
            progress_top = self._floating_task_progress_top()
            if progress_top is not None:
                y = min(y, max(72, progress_top - self.assistant_button.height() - 12))
            safe = self._avoid_floating_hotspots(self.assistant_button, QPoint(x, y), side="right")
            x, y = safe.x(), safe.y()
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
        efficiency_text = f"效率 {100 * float(efficiency):.1f}%" if efficiency is not None else "效率 待计算"
        self.top_efficiency.setText(efficiency_text)
        self.footer_efficiency.setText("耦合" + efficiency_text[2:] if efficiency_text.startswith("效率") else efficiency_text)
        self.setWindowTitle(f"{APP_NAME} · {project.name}{dirty}")

    def _toggle_toolbox(self) -> None:
        if self.drawer.isVisible():
            self._close_tool_drawer()
            return
        self._drawer_category = "all"
        self.drawer.show_all()
        self._position_floating_tools()

    def _position_floating_tools(self) -> None:
        margin = 18
        if getattr(self.toolbox_button, "_user_moved", False) and not self.drawer.isVisible():
            x = max(0, min(self.toolbox_button.x(), self.central_root.width() - self.toolbox_button.width()))
            y = max(0, min(self.toolbox_button.y(), self.central_root.height() - self.toolbox_button.height()))
            self.toolbox_button.move(x, y)
            self.toolbox_button.raise_()
            return
        footer_height = 34
        # 浮动球始终留在底部状态栏上方，避免遮挡任务/历史等全局动作。
        # Reserve one extra compact status-row height. Teaching/long tasks often
        # place their own status strip directly above the global footer.
        tool_y = max(70, self.central_root.height() - footer_height - self.toolbox_button.height() - margin - 82)
        tool_x = margin
        # When the simulation parameter navigator is visible, keep the floating
        # launcher beside it instead of covering lens/fiber rows. The drawer itself
        # still opens from the left edge, preserving left-bottom spatial memory.
        if not self.drawer.isVisible() and self._current_key == "simulation":
            page = self._simulation_page_instance()
            params = getattr(page, "params", None) if page is not None else None
            if params is not None and params.isVisible():
                try:
                    pos = params.mapTo(self.central_root, QPoint(0, 0))
                    tool_x = min(self.central_root.width() - self.toolbox_button.width() - margin, pos.x() + params.width() + 12)
                except RuntimeError:
                    tool_x = margin
        elif not self.drawer.isVisible() and self._current_key == "optimization":
            host = self._pages.get("optimization")
            page = host.loaded_page if host is not None else None
            splitter = getattr(page, "main_splitter", None) if page is not None else None
            settings = splitter.widget(0) if splitter is not None and splitter.count() >= 1 else None
            if settings is not None and settings.isVisible():
                try:
                    pos = settings.mapTo(self.central_root, QPoint(0, 0))
                    tool_x = min(self.central_root.width() - self.toolbox_button.width() - margin, pos.x() + settings.width() + 12)
                except RuntimeError:
                    tool_x = margin
            tool_y = max(110, int(self.central_root.height() * 0.48))
        elif not self.drawer.isVisible() and self._current_key == "teaching":
            # Keep the toolbox launcher over the optical canvas instead of on top
            # of scrolled teaching explanations/actions.  72 px clears the
            # workbench's own left-side tool strip.
            tool_x = min(self.central_root.width() - self.toolbox_button.width() - margin, 72)
            tool_y = max(110, int(self.central_root.height() * 0.36))
        progress_top = self._floating_task_progress_top()
        if progress_top is not None:
            tool_y = min(tool_y, max(72, progress_top - self.toolbox_button.height() - 12))
        if not self.drawer.isVisible():
            safe = self._avoid_floating_hotspots(
                self.toolbox_button, QPoint(max(margin, tool_x), tool_y), side="left"
            )
            tool_x, tool_y = safe.x(), safe.y()
        self.toolbox_button.move(max(margin, tool_x), tool_y)
        self.toolbox_button.raise_()
        if self.drawer.isVisible():
            drawer_bottom = tool_y - 8
            drawer_top = 54
            drawer_height = max(300, drawer_bottom - drawer_top)
            self.drawer.setGeometry(14, drawer_top, 344, drawer_height)
            self.drawer.raise_()
            self.toolbox_button.raise_()

    def _toggle_category_drawer(self, key: str) -> None:
        key = str(key or "engineering")
        if self.drawer.isVisible() and self.drawer.category_key == key:
            self._close_tool_drawer()
            return
        self._drawer_category = key
        self.drawer.show_category(key)
        self.rail.set_current_category(key)
        QTimer.singleShot(0, self._position_assistant_button)

    def _close_tool_drawer(self) -> None:
        if self.drawer.isVisible():
            self.drawer.hide()
        self._drawer_category = ""
        # 收起工具抽屉只影响导航外观，不能清空已经打开的文档路由。
        # 否则从抽屉打开“正向预测/模场匹配”等任务后，navigate()
        # 自动收起抽屉时会立即让相应标签失去可恢复的目标。
        self._sync_rail_for_page(self._current_key)
        QTimer.singleShot(0, self._position_assistant_button)
        QTimer.singleShot(0, self._position_floating_tools)

    def _launch_shell_action(self, action: object) -> None:
        if not isinstance(action, ShellAction):
            return
        if action.page_key == "optimization" and action.target in {
            "optimization.scan",
            "optimization.tolerance",
            "optimization.variables",
            "optimization.inverse_design",
            "optimization.ml_inverse_prediction",
            "optimization.validation",
        }:
            self._open_optimization_task(action.target, action.payload)
            return
        if action.page_key == "machine_learning" and action.target == "machine_learning.prediction":
            self._open_ml_prediction_task()
            return
        self.navigate_action(
            action.page_key,
            action.target,
            action.payload,
            update_document=False,
        )

    def _ensure_ml_prediction_task_window(self) -> MachineLearningPredictionTaskWindow:
        window = self._ml_prediction_task_window
        if window is None:
            window = MachineLearningPredictionTaskWindow(self.context, self)
            window.navigateRequested.connect(lambda key: self.navigate(str(key or "simulation"), update_document=False))
            window.openInWorkspaceRequested.connect(self._open_ml_prediction_workspace)
            self._ml_prediction_task_window = window
        return window

    def _open_ml_prediction_task(self) -> None:
        self.navigate("simulation", update_document=False)
        window = self._ensure_ml_prediction_task_window()
        window.bring_to_front()
        self.footer_notice.setText("已打开正向预测；主仿真工作台仍可操作")

    def _open_ml_prediction_workspace(self) -> None:
        window = getattr(self, "_ml_prediction_task_window", None)
        if window is not None and window.isVisible():
            window.hide()
        self.navigate("machine_learning", update_document=False)
        host = self._pages.get("machine_learning")
        if host is None:
            return

        def deliver(page) -> None:
            prepare = getattr(page, "prepare_prediction_workspace", None)
            if callable(prepare):
                prepare()
            signal = getattr(page, "predictionPopoutRequested", None)
            if signal is not None and not bool(page.property("predictionPopoutConnected")):
                signal.connect(self._open_ml_prediction_task_from_workspace)
                page.setProperty("predictionPopoutConnected", True)

        if host.loaded_page is not None:
            QTimer.singleShot(0, lambda page=host.loaded_page: deliver(page))
        else:
            host.pageReady.connect(deliver, Qt.ConnectionType.SingleShotConnection)
        self.footer_notice.setText("已在主工作区打开正向预测；可随时切回独立窗口")

    def _open_ml_prediction_task_from_workspace(self) -> None:
        self.navigate("simulation", update_document=False)
        window = self._ensure_ml_prediction_task_window()
        window.bring_to_front()
        self.footer_notice.setText("已切换到正向预测独立窗口；主仿真工作台仍可操作")

    def _ensure_optimization_task_window(self) -> OptimizationTaskWindow:
        window = self._optimization_task_window
        if window is None:
            window = OptimizationTaskWindow(self.context, self)
            window.navigateRequested.connect(lambda key: self.navigate(str(key or "simulation"), update_document=False))
            window.previewRequested.connect(self._preview_task_candidate)
            window.previewCleared.connect(self._clear_task_candidate_preview)
            window.openInWorkspaceRequested.connect(self._open_optimization_workspace)
            self._optimization_task_window = window
        return window

    def _open_optimization_task(self, target: str, payload: dict | None = None) -> None:
        # Research/optimization stays beside the persistent simulation workbench.
        # Reuse one major task window instead of spawning a desktop full of dialogs.
        self.navigate("simulation", update_document=False)
        window = self._ensure_optimization_task_window()
        window.set_target(target, payload)
        window.bring_to_front()
        self.footer_notice.setText(f"已打开{window.windowTitle()}；主仿真工作台仍可操作")

    def _open_optimization_workspace(self, target: str, payload: dict | None = None) -> None:
        """Open the same research task as a complete main-workspace page.

        The floating task window is useful for simulation linkage, but compact
        screens and long advanced forms need a full page as well.  This changes
        only the presentation container; task parameters/results remain owned by
        the same OptimizationPage implementation.
        """
        task_window = getattr(self, "_optimization_task_window", None)
        if task_window is not None and task_window.isVisible():
            task_window.hide()
        self.navigate("optimization", update_document=False)
        host = self._pages.get("optimization")
        if host is None:
            return

        def deliver(page) -> None:
            prepare = getattr(page, "prepare_workspace_task", None)
            if callable(prepare):
                prepare(str(target or "optimization.scan"), {})
            importer = getattr(page, "import_task_state", None)
            if callable(importer) and payload:
                importer(dict(payload or {}))
            if hasattr(page, "popoutRequested") and not bool(page.property("taskPopoutConnected")):
                page.popoutRequested.connect(self._open_optimization_task_from_workspace)
                page.setProperty("taskPopoutConnected", True)
            scroll = getattr(page, "research_scroll", None)
            if scroll is not None and not bool(page.property("floatingScrollConnected")):
                bar = scroll.verticalScrollBar()
                bar.valueChanged.connect(lambda _value: self._reposition_task_launchers())
                page.setProperty("floatingScrollConnected", True)
            QTimer.singleShot(0, self._reposition_task_launchers)

        if host.loaded_page is not None:
            QTimer.singleShot(0, lambda page=host.loaded_page: deliver(page))
        else:
            host.pageReady.connect(deliver, Qt.ConnectionType.SingleShotConnection)
        self.footer_notice.setText("已在主工作区打开完整研究任务；可随时切回独立窗口")

    def _open_optimization_task_from_workspace(self, target: str, task_state: object = None) -> None:
        self.navigate("simulation", update_document=False)
        window = self._ensure_optimization_task_window()
        window.set_target(str(target or "optimization.scan"), {})
        importer = getattr(window.page, "import_task_state", None)
        if callable(importer) and isinstance(task_state, dict):
            importer(dict(task_state))
        window.bring_to_front()
        self.footer_notice.setText(f"已切换到{window.windowTitle()}独立窗口；主仿真工作台仍可操作")

    def _reposition_task_launchers(self) -> None:
        try:
            self._position_floating_tools()
            self._position_assistant_button()
        except RuntimeError:
            pass

    def _simulation_page_instance(self):
        host = self._pages.get("simulation")
        return host.loaded_page if host is not None else None

    def _preview_task_candidate(self, changes: dict, label: str) -> None:
        self.navigate("simulation", update_document=False)
        host = self._pages.get("simulation")
        if host is None:
            return
        def deliver(page) -> None:
            handler = getattr(page, "show_candidate_preview", None)
            if callable(handler):
                handler(dict(changes or {}), str(label or "候选"))
        if host.loaded_page is not None:
            QTimer.singleShot(0, lambda page=host.loaded_page: deliver(page))
        else:
            host.pageReady.connect(deliver, Qt.ConnectionType.SingleShotConnection)

    def _clear_task_candidate_preview(self) -> None:
        page = self._simulation_page_instance()
        handler = getattr(page, "clear_candidate_preview", None) if page is not None else None
        if callable(handler):
            handler()

    def _sync_rail_for_page(self, key: str) -> None:
        mapping = {
            "home": "engineering",
            "simulation": "simulation",
            "optimization": "research",
            "machine_learning": "research",
            "explainability": "research",
            "tasks": "engineering",
            "teaching": "teaching",
        }
        category = mapping.get(str(key), "")
        if category:
            self.rail.set_current_category(category)
        else:
            self.rail.clear_current_category()

    def _save_project_version(self) -> None:
        try:
            version = self.context.project.save_version()
        except Exception as exc:
            self.footer_notice.setText(f"保存失败：{exc}")
            return
        self.footer_notice.setText(f"已保存 {version}")
        self._refresh_project_meta(self.context.project.project)

    def set_workspace_focus(self, enabled: bool = True) -> None:
        """Prioritize the current canvas without destroying navigation state."""
        if enabled:
            self._close_tool_drawer()
            self.footer_notice.setText("已进入专注视图；左侧图标导航仍可随时使用")
        else:
            self.footer_notice.setText("就绪")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_assistant_button()
        self._position_floating_tools()
        self._reposition_ai_assistant()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._reposition_ai_assistant()

    def closeEvent(self, event) -> None:
        if bool(getattr(self.context.project, "dirty", False)):
            self.recovery_store.flush()
        dialog = getattr(self, "_assistant_dialog", None)
        if dialog is not None:
            dialog.shutdown()
        task_window = getattr(self, "_optimization_task_window", None)
        if task_window is not None:
            task_window.close()
        ml_prediction_window = getattr(self, "_ml_prediction_task_window", None)
        if ml_prediction_window is not None:
            ml_prediction_window.close()
        self.settings.setValue("main/window_geometry", self.saveGeometry())
        self.settings.setValue("main/window_state", self.saveState())
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
