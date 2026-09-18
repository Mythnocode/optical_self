"""Application window for the two-shell optical research platform.

The main window is deliberately small.  It routes between three shell modes:

* 首页: a clickable workflow map;
* ordinary modules: :class:`WorkbenchShell`;
* 教学: :class:`TeachingShell`.

This class never mounts a legacy ``*Page`` inside a document tab.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QSettings, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QToolTip

from frontend_pyside.app.main_window_layout import MainWindowWidgets, build_main_window_layout
from frontend_pyside.app.shell_controller import ShellController
from frontend_pyside.core.constants import APP_NAME
from frontend_pyside.features.assistant.dialog import AiAssistantDialog
from frontend_pyside.features.assistant.floating import AssistantFloatingButton
from frontend_pyside.modules.simulation.settings import CombinedSettingsDialog
from frontend_pyside.shared.font_fallback import configure_qt_font
from frontend_pyside.state.session_recovery import SessionRecoveryStore


def _automated_ui() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or str(os.environ.get("QT_QPA_PLATFORM", "")).lower() == "offscreen"


class MainWindow(QMainWindow):
    """Top-level router for the refactored workbench.

    The only stack in this class is a mode router containing the three new
    shells.  Document tabs are owned by ``WorkbenchShell``; teaching has none.
    """

    MODULE_ALIASES = {
        "machine_learning": "model",
        "surrogate": "model",
        "explainability": "explainability",
        "optimization": "optimization",
        "simulation": "simulation",
        "analysis": "simulation",
        "teaching": "teaching",
        "home": "home",
        "tasks": "home",
    }
    DEFAULT_DOCUMENTS = {
        "simulation": "lens_data",
        "model": "dataset",
        "optimization": "opt_vars",
        "explainability": "global_contrib",
    }
    ORDINARY_MODULES = {"simulation", "model", "optimization", "explainability"}

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.settings = QSettings()
        self.preferences = getattr(context.services, "ui_preferences", None)
        self._current_module = "home"
        self._last_notice = ""
        self._connection_status = ""
        self._shell_controller = ShellController(context, self)
        self.recovery_store = SessionRecoveryStore(context.project, self)

        self.setObjectName("mainWindow")
        self.setWindowTitle(APP_NAME)
        # Keep the workbench usable on compact laptops and portrait displays;
        # the document/rail splitters provide the remaining adaptation.
        self.setMinimumSize(720, 560)

        app = QApplication.instance()
        if app is not None:
            configure_qt_font(app, point_size=13.5)

        widgets: MainWindowWidgets = build_main_window_layout(self, context)
        self._layout_widgets = widgets
        self.central_root = widgets.central
        self.primary = widgets.primary
        self.mode_stack = widgets.mode_stack
        self.home = widgets.home
        self.workbench = widgets.workbench
        self.teaching = widgets.teaching

        # These aliases are descriptive, not alternate UI containers.  They
        # make the shell easy to inspect in a debugger and keep all ordinary
        # pages on one object rail and one document workspace.
        self.object_rail = self.workbench.object_rail

        self.primary.moduleRequested.connect(self.navigate)
        self.primary.actionRequested.connect(self._primary_action)
        self.home.nodeRequested.connect(self._open_workflow_node)
        self.home.homeActionRequested.connect(self._home_action)
        self.workbench.taskRequested.connect(self._notify)
        self.workbench.navigateRequested.connect(
            lambda module: self.navigate(module, update_document=False)
        )
        self._shell_controller.connectionChanged.connect(self._backend_status)

        context.project.project_changed.connect(lambda _project: self._refresh_window_title())
        context.project.dirty_changed.connect(lambda _dirty: self._refresh_window_title())
        self._refresh_window_title()

        # Apply persisted display preferences without introducing another
        # permanent bar.  The preference object is optional in lightweight tests.
        if self.preferences is not None:
            signal = getattr(self.preferences, "display_mode_changed", None)
            if signal is not None:
                signal.connect(self._apply_display_mode)
            self._apply_display_mode(str(getattr(self.preferences, "display_mode", "标准")))

        self._install_assistant()
        self.navigate("home")
        QTimer.singleShot(0, self._offer_workspace_recovery)
        QTimer.singleShot(0, self._position_assistant_button)
        QTimer.singleShot(350, self._shell_controller.check_backend_health)

    @property
    def document_workspace(self):
        """Return the document pool for the currently selected ordinary module."""
        return self.workbench.workspace

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate(self, key: str, *, update_document: bool = True) -> None:
        """Switch a primary module without creating a legacy feature page."""
        module = self.MODULE_ALIASES.get(str(key or "home"), str(key or "home"))
        if module == "home":
            self._current_module = "home"
            self.primary.set_module("home")
            self.mode_stack.setCurrentWidget(self.home)
            self._shell_controller.record_page_view("home")
            self._sync_assistant_page()
            return
        if module == "teaching":
            self._current_module = "teaching"
            self.primary.set_module("teaching")
            self.mode_stack.setCurrentWidget(self.teaching)
            self._shell_controller.record_page_view("teaching")
            self._sync_assistant_page()
            return
        if module not in self.ORDINARY_MODULES:
            return

        self._current_module = module
        self.primary.set_module(module)
        self.mode_stack.setCurrentWidget(self.workbench)
        self.workbench.set_module(module)
        # Re-entering a module restores its document pool instead of reopening
        # the default tab and losing the user's active document.
        if update_document and not self.workbench.has_documents(module):
            kind = self.DEFAULT_DOCUMENTS.get(module)
            if kind:
                self.workbench.open_document(module, kind)
        self._shell_controller.record_page_view(module)
        self._sync_assistant_page()

    def open_document(self, module: str, kind: str, *, split: bool = False, id_suffix: str = "") -> None:
        """Open one approved document kind from the home workflow or an action."""
        module = self.MODULE_ALIASES.get(str(module), str(module))
        if module == "teaching":
            self.navigate("teaching")
            return
        self.navigate(module, update_document=False)
        self.workbench.open_document(module, kind, split=split, id_suffix=id_suffix)

    def _open_workflow_node(self, module: str, kind: str) -> None:
        if module == "teaching":
            self.navigate("teaching")
            # 教学没有文档页签，卡片上的 kind 直接对应教学台的一个动作
            # （"teaching" 只表示进入实验台本身）。
            action = str(kind or "")
            if action and action != "teaching":
                self.teaching._toolbar_action(action)
            return
        self.open_document(module, kind)

    def _home_action(self, action: str) -> None:
        action = str(action or "")
        if action == "quick_start":
            self.open_document("simulation", "lens_data")
        elif action == "help":
            QMessageBox.information(
                self,
                "平台工作流",
                "首页只负责进入工作流。普通页面使用左侧对象栏和中央页签；\n"
                "教学页面使用中央大画布和悬浮器材库，不切换成结果页。",
            )

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
        """Translate old action names into the new module/document vocabulary.

        This compatibility entry point does not re-open old task windows.  A
        long-running action is represented by an approved document and its own
        in-document button.
        """
        del payload, document_key, document_title, document_icon
        page_key = self.MODULE_ALIASES.get(str(page_key), str(page_key))
        target = str(target or "")
        routes = {
            "simulation.result": ("simulation", "coupling"),
            "simulation.current": ("simulation", "coupling"),
            "simulation.ray_layout": ("simulation", "ray_layout"),
            "simulation.spot": ("simulation", "spot"),
            "optimization.scan": ("optimization", "scan"),
            "optimization.variables": ("optimization", "opt_vars"),
            "optimization.variable_structure": ("optimization", "opt_vars"),
            "optimization.goal": ("optimization", "opt_vars"),
            "optimization.current": ("optimization", "opt_vars"),
            "optimization.result": ("optimization", "opt_result"),
            "optimization.tolerance": ("optimization", "opt_vars"),
            "machine_learning.dataset": ("model", "dataset"),
            "machine_learning.training": ("model", "train_result"),
            "machine_learning.prediction": ("model", "predict"),
            "machine_learning.evaluation": ("model", "train_result"),
            "machine_learning.current": ("model", "predict"),
            "machine_learning.current_model": ("model", "train_result"),
            "explainability.importance": ("explainability", "global_contrib"),
            "explainability.reason": ("explainability", "current_system"),
            "explainability.current": ("explainability", "current_system"),
            "explainability.global": ("explainability", "global_contrib"),
            "explainability.trend": ("explainability", "param_trend"),
        }
        module, kind = routes.get(target, (page_key, target))
        if module in self.ORDINARY_MODULES and kind:
            self.open_document(module, kind)
        else:
            self.navigate(module, update_document=update_document)

    # ------------------------------------------------------------------
    # Primary actions and window state
    # ------------------------------------------------------------------

    def _primary_action(self, action: str) -> None:
        action = str(action or "")
        if action == "save":
            self._save_project_version()
        elif action == "compute":
            self.workbench.run_formal_calculation()
        elif action == "settings":
            dialog = CombinedSettingsDialog(
                self.context,
                self,
                calculation=self.workbench._calculation_state,
                alignment=self.workbench._alignment_state,
            )
            if dialog.exec():
                self.workbench._apply_engineering(dialog.compute, run=False)

    def _save_project_version(self) -> None:
        try:
            version = self.context.project.save_version()
        except Exception as exc:
            self._notify(f"保存失败：{exc}")
            return
        self.recovery_store.clear()
        self._refresh_window_title()
        self._notify(f"已保存 {version}")

    def _offer_workspace_recovery(self) -> None:
        if _automated_ui() or not self.recovery_store.has_recovery():
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
                self._notify("已恢复上次未保存的工作状态")
            else:
                QMessageBox.warning(self, "恢复失败", "恢复文件无法读取，已保留当前默认项目。")
                self.recovery_store.clear()
        else:
            self.recovery_store.clear()

    def restore_saved_window_state(self) -> None:
        """Restore only geometry/state; page selection starts at the workflow home."""
        geometry = self.settings.value("main_window/geometry")
        state = self.settings.value("main_window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def set_workspace_focus(self, enabled: bool = True) -> None:
        self.workbench.object_rail.setVisible(not bool(enabled))
        self._notify("已进入专注视图" if enabled else "已恢复对象栏")

    def _apply_display_mode(self, mode: str) -> None:
        # The preference is software-level and changes only the application font;
        # it does not introduce another page footer or parameter form.
        app = self.window().windowHandle()
        del app
        self.setProperty("displayMode", str(mode or "标准"))
        self.style().unpolish(self)
        self.style().polish(self)

    def _backend_status(self, text: str, tone: str) -> None:
        del tone
        self._connection_status = str(text or "").strip()
        self.setToolTip("")
        self._refresh_window_title()

    def _notify(self, message: str) -> None:
        self._last_notice = str(message or "")
        QToolTip.showText(self.mapToGlobal(self.rect().topRight()), self._last_notice, self)

    def _refresh_window_title(self) -> None:
        self.setWindowTitle(APP_NAME)

    # ------------------------------------------------------------------
    # AI assistant
    # ------------------------------------------------------------------

    def _install_assistant(self) -> None:
        self.assistant_dialog = AiAssistantDialog(self.context, self)
        self.assistant_dialog.actionRequested.connect(self._handle_assistant_action)
        self.assistant_dialog.visibilityChanged.connect(self._assistant_visibility_changed)
        self.assistant_button = AssistantFloatingButton(self.central_root)
        self.assistant_button.clicked.connect(self._toggle_assistant)
        self.assistant_button.dragFinished.connect(self._assistant_drag_finished)
        saved = self.settings.value("main_window/assistant_pos")
        if isinstance(saved, QPoint):
            self.assistant_button.move(saved)
            self.assistant_button._user_moved = True
        self.assistant_button.show()
        self.assistant_button.raise_()

    def assistant_context(self) -> dict:
        module = self._current_module
        if module == "teaching":
            host = self.teaching
        elif module == "home":
            host = self.home
        else:
            host = self.workbench
        provider = getattr(host, "assistant_context", None)
        data = dict(provider()) if callable(provider) else {}
        data.setdefault("page", module)
        data.setdefault("current_view", module)
        return data

    def _sync_assistant_page(self) -> None:
        dialog = getattr(self, "assistant_dialog", None)
        if dialog is not None:
            dialog.set_page_context(self._current_module)

    def _toggle_assistant(self) -> None:
        if getattr(self.assistant_button, "_dragging", False):
            return
        dialog = self.assistant_dialog
        if dialog.isVisible():
            dialog.hide()
            return
        dialog.set_page_context(self._current_module)
        dialog.show_anchored()

    def _assistant_visibility_changed(self, visible: bool) -> None:
        self.assistant_button.set_active(bool(visible))

    def _assistant_drag_finished(self, pos: QPoint) -> None:
        self.settings.setValue("main_window/assistant_pos", pos)
        self._position_assistant_button()

    def _position_floating_tools(self) -> None:
        self._position_assistant_button()

    def _position_assistant_button(self) -> None:
        button = getattr(self, "assistant_button", None)
        if button is None:
            return
        root = self.central_root
        margin = 18
        max_x = max(0, root.width() - button.width())
        max_y = max(0, root.height() - button.height())
        if not getattr(button, "_user_moved", False):
            button.move(max(0, max_x - margin), max(0, max_y - margin))
        else:
            button.move(min(max(button.x(), 0), max_x), min(max(button.y(), 0), max_y))
        button.raise_()

    def _handle_assistant_action(self, action) -> None:
        payload = dict(action or {})
        target = str(payload.get("target") or "")
        level = str(payload.get("level") or "navigate")
        if level == "execute" and bool(payload.get("starts_job")):
            self._notify("该操作需要在页面内确认后执行。")
            return
        if target == "simulation.formal":
            self.navigate("simulation", update_document=False)
            self.workbench._open_engineering("compute")
            return
        if target in {"simulation.current", "simulation.result", "simulation.focus"}:
            self.open_document("simulation", "coupling")
            return
        if target == "teaching" or target.startswith("teaching."):
            self.navigate("teaching")
            return
        if target in {"tasks.current", "home"}:
            self.navigate("home")
            return
        page = str(payload.get("target_page") or "")
        self.navigate_action(page or self._current_module, target, payload)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_assistant_button()
        dialog = getattr(self, "assistant_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.clamp_to_parent()

    def closeEvent(self, event) -> None:
        if bool(getattr(self.context.project, "dirty", False)) and not _automated_ui():
            answer = QMessageBox.question(
                self,
                "保存当前工程",
                "当前工程有未保存修改，是否保存后退出？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                self._save_project_version()
        dialog = getattr(self, "assistant_dialog", None)
        if dialog is not None:
            dialog.shutdown()
        self.settings.setValue("main_window/geometry", self.saveGeometry())
        self.settings.setValue("main_window/state", self.saveState())
        self.recovery_store.clear()
        try:
            usage = getattr(self.context.services, "usage", None)
            if usage is not None:
                usage.close()
        except Exception:
            pass
        super().closeEvent(event)


__all__ = ["MainWindow"]
