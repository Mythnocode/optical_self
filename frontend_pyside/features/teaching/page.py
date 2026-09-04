from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QScrollArea, QSplitter, QVBoxLayout, QWidget

from .exploration_panel import TeachingExplorationPanel
from .spatial_routing_upgrade import FlexibleSpatialTeachingWorkbench


class TeachingPage(QWidget):
    """Free teaching workbench plus a non-linear visual exploration layer."""

    navigateRequested = Signal(str)
    assistantActionRequested = Signal(object)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.setObjectName("teachingPage")
        self.context = context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Teaching is deliberately canvas-first, but its compact header, canvas
        # and status row still have a real minimum height.  On short windows the
        # old direct splitter layout compressed those children into the same
        # geometry: the status buttons could literally sit on top of the optical
        # bench.  The whole teaching workspace now owns one vertical scroll area
        # instead.  This follows the platform-wide rule: if the page does not fit,
        # scroll the page; never squeeze fixed-height controls into overlap.
        self.page_scroll = QScrollArea(self)
        self.page_scroll.setObjectName("teachingPageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_content = QWidget(self.page_scroll)
        self.scroll_content.setObjectName("teachingPageScrollContent")
        scroll_layout = QVBoxLayout(self.scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        # Exploration is a docked, user-resizable workspace rather than an
        # absolute-position overlay.  The previous overlay covered the optical
        # bench and could not be moved, which made the visual explanation fight
        # the experiment it was supposed to explain.
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self.scroll_content)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(7)

        self.workbench = FlexibleSpatialTeachingWorkbench(context)
        self.workbench.navigateRequested.connect(self.navigateRequested)
        self.workbench.phenomenonRequested.connect(self._show_exploration_request)
        self.workspace_splitter.addWidget(self.workbench)

        self.exploration_panel = TeachingExplorationPanel(self.workspace_splitter)
        self.exploration_panel.returnRequested.connect(self.assistantActionRequested)
        self.exploration_panel.closeRequested.connect(self._close_exploration)
        self.workbench.sceneStateChanged.connect(self.exploration_panel.bind_scene)
        self.exploration_panel.bind_scene(self.workbench.model, self.workbench.model.scene_snapshot())
        self.workspace_splitter.addWidget(self.exploration_panel)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.exploration_panel.hide()
        scroll_layout.addWidget(self.workspace_splitter, 1)
        self.page_scroll.setWidget(self.scroll_content)
        layout.addWidget(self.page_scroll, 1)
        QTimer.singleShot(0, self._apply_responsive_workspace)
        QTimer.singleShot(0, self._sync_page_scroll_height)

        # Compatibility alias for older internal callers.  The new panel is no
        # longer a quiz-first "phenomenon lesson"; it is a free exploration lab.
        self.phenomenon_panel = self.exploration_panel


    def _sync_page_scroll_height(self) -> None:
        """Keep a readable teaching canvas and let the outer page scroll if needed."""
        try:
            workbench_hint = max(0, self.workbench.sizeHint().height(), self.workbench.minimumSizeHint().height())
            exploration_hint = max(0, self.exploration_panel.sizeHint().height(), self.exploration_panel.minimumSizeHint().height())
            # 650 px keeps the 520 px experiment canvas plus the compact header and
            # status strip separated at the standard 13.5 pt application font.
            if self.exploration_panel.isVisible() and self.workspace_splitter.orientation() == Qt.Orientation.Vertical:
                required = max(650, workbench_hint) + max(500, exploration_hint) + self.workspace_splitter.handleWidth()
            else:
                required = max(650, workbench_hint, exploration_hint if self.exploration_panel.isVisible() else 0)
            self.scroll_content.setMinimumHeight(required)
            self.workspace_splitter.setMinimumHeight(required)
        except RuntimeError:
            return


    def _apply_responsive_workspace(self) -> None:
        """Keep the teaching inspector readable instead of crushing it beside the canvas."""
        try:
            viewport_width = max(0, self.page_scroll.viewport().width())
            if not self.exploration_panel.isVisible():
                self.workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
                self.exploration_panel.setMinimumWidth(430)
                self.exploration_panel.setMaximumWidth(520)
                return
            if viewport_width < 1080:
                # On compact windows the explanation becomes a second vertical section.
                # The page owns the single vertical scroll, so neither section is squeezed.
                self.workspace_splitter.setOrientation(Qt.Orientation.Vertical)
                self.exploration_panel.setMinimumWidth(0)
                self.exploration_panel.setMaximumWidth(16777215)
                self.workspace_splitter.setSizes([650, max(520, self.exploration_panel.sizeHint().height())])
            else:
                self.workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
                self.exploration_panel.setMinimumWidth(430)
                self.exploration_panel.setMaximumWidth(520)
                total = max(1080, self.workspace_splitter.width())
                panel_width = min(500, max(430, round(total * 0.34)))
                self.workspace_splitter.setSizes([max(620, total - panel_width), panel_width])
        except RuntimeError:
            return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._apply_responsive_workspace)
        QTimer.singleShot(0, self._sync_page_scroll_height)

    def _show_exploration_request(self, request: str = "diagnosis:curve_features") -> None:
        text = str(request or "diagnosis:curve_features")
        if text == "workbench":
            self._close_exploration()
            return
        if ":" in text:
            section, key = text.split(":", 1)
        elif text in {"mismatch", "diagnosis", "concept", "engineering"}:
            section, key = text, ""
        else:
            section, key = "diagnosis", text
        self._show_exploration(section, key)

    def _show_exploration(self, section: str, key: str = "") -> None:
        self.exploration_panel.bind_scene(self.workbench.model, self.workbench.model.scene_snapshot())
        self.exploration_panel.open_section(section, key)
        if not self.exploration_panel.isVisible():
            self.exploration_panel.show()
        self._apply_responsive_workspace()
        self.exploration_panel.setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, self._sync_page_scroll_height)
        QTimer.singleShot(0, self._reposition_shell_assistant)

    def _close_exploration(self) -> None:
        self.exploration_panel.hide()
        self._apply_responsive_workspace()
        self.workbench.setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, self._sync_page_scroll_height)
        QTimer.singleShot(0, self._reposition_shell_assistant)

    def on_activated(self) -> None:
        resume = getattr(self.workbench, "resume_scene_surfaces", None)
        if callable(resume):
            resume()

    def on_deactivated(self) -> None:
        self._close_exploration()
        dismiss = getattr(self.workbench, "dismiss_transient_overlays", None)
        if callable(dismiss):
            dismiss()

    def _reposition_shell_assistant(self) -> None:
        shell = self.window()
        reposition = getattr(shell, "_position_assistant_button", None)
        if callable(reposition):
            reposition()

    def handle_assistant_action(self, action: dict) -> None:
        payload = dict(action or {})
        target = str(payload.get("target") or "")
        extra = dict(payload.get("payload") or {})
        if target == "teaching.workbench":
            self._close_exploration()
        elif target == "teaching.library":
            self._close_exploration()
            if getattr(self.workbench.model, "mode", "free") != "free":
                self.workbench.set_mode("free", force=True)
            opener = getattr(self.workbench, "_open_left_drawer", None)
            if callable(opener):
                opener("library")
        elif target == "teaching.phenomenon":
            self._show_exploration("diagnosis", str(extra.get("phenomenon") or "curve_features"))
        elif target == "teaching.mismatch":
            self._show_exploration("mismatch", str(extra.get("mismatch") or payload.get("mismatch") or "lateral"))
        elif target == "teaching.diagnosis":
            self._show_exploration("diagnosis", str(extra.get("phenomenon") or payload.get("phenomenon") or "curve_features"))
        elif target == "teaching.concept":
            self._show_exploration("concept", str(extra.get("concept") or payload.get("concept") or "gaussian_q"))
        elif target == "teaching.explore":
            self._show_exploration("mismatch", str(extra.get("mismatch") or "lateral"))

    def assistant_action_target_widget(self, action: dict):
        target = str((action or {}).get("target") or "")
        if target == "teaching.library":
            return getattr(self.workbench, "left_drawer", self.workbench)
        if target.startswith("teaching.") and target != "teaching.workbench":
            return self.exploration_panel.assistant_target_widget(dict(action or {}))
        return self.workbench

    def current_profile(self) -> dict:
        return self.workbench.current_profile()

    def assistant_context(self) -> dict:
        model = getattr(self.workbench, "model", None)
        nodes = list(getattr(model, "nodes", {}).values()) if model is not None else []
        edges = list(getattr(model, "edges", {}).values()) if model is not None else []
        selected_id = str(getattr(model, "selected_node_id", "") or "") if model is not None else ""
        selected = getattr(model, "nodes", {}).get(selected_id) if model is not None and selected_id else None
        view_kind = str(getattr(self.workbench, "view_kind", getattr(self.workbench, "_view_kind", "")) or "")
        profile = self.current_profile()
        return {
            "page": "教学中心",
            "current_view": "教学探索" if self.exploration_panel.isVisible() else (view_kind or "自由实验台"),
            "mode": str(getattr(model, "mode", "") or "") if model is not None else "",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "selected_component": {
                "id": selected_id,
                "kind": str(getattr(selected, "kind", "") or "") if selected is not None else "",
                "x": getattr(selected, "x", None) if selected is not None else None,
                "y": getattr(selected, "y", None) if selected is not None else None,
                "rotation_deg": getattr(selected, "rotation_deg", None) if selected is not None else None,
            },
            "latest_cause": str(getattr(model, "latest_cause", "") or "") if model is not None else "",
            "active_experiment": str(getattr(model, "active_experiment_key", "") or "") if model is not None else "",
            "exploration_open": bool(self.exploration_panel.isVisible()),
            "teaching_is_sandbox": True,
            "profile": dict(profile or {}),
        }


__all__ = ["TeachingPage"]
