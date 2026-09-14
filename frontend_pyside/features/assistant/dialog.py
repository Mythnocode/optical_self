from __future__ import annotations

from typing import Any
from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QMouseEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.assistant.local_bridge import LocalKnowledgeBridge
from frontend_pyside.features.assistant.history import AssistantConversationStore
from frontend_pyside.features.assistant.research_advisor import ResearchAdvisor
from frontend_pyside.features.assistant.actions import normalize_action
from frontend_pyside.features.assistant.guidance_session import GuidanceSession, GuidanceView
from frontend_pyside.shared.icons import icon


_ASSISTANT_QSS = """
QDialog#aiAssistantDialog { background: transparent; color: #111827; }
QFrame#assistantWindowSurface {
    background: #ffffff;
    border: 1px solid #b8c6d9;
    border-radius: 15px;
}
QFrame#assistantHeader {
    background: #f4f7fb;
    border: 0;
    border-bottom: 1px solid #d8e0eb;
    border-top-left-radius: 15px;
    border-top-right-radius: 15px;
}
QLabel#assistantTitle { color: #172033; font-size: 17px; font-weight: 700; }
QLabel#assistantStatus { color: #155eef; font-size: 10.5pt; font-weight: 700; }
QToolButton#assistantHeaderButton {
    background: transparent;
    border: 0;
    border-radius: 14px;
    color: #4b5565;
    font-size: 15px;
    min-width: 28px;
    min-height: 28px;
}
QToolButton#assistantHeaderButton:hover { background: #e3eaf4; color: #111827; }
QScrollArea#assistantMessagesScroll { background: #f8fafc; border: 0; }
QWidget#assistantMessagesHost { background: #f8fafc; }
QFrame#assistantAnswerBubble {
    background: #ffffff;
    border: 1px solid #d8e0eb;
    border-radius: 13px;
}
QFrame#assistantUserBubble {
    background: #1768e5;
    border: 0;
    border-radius: 13px;
}
QLabel#assistantUserMessage {
    color: #ffffff;
    background: transparent;
    border: 0;
    font-size: 11.5pt;
}
QTextBrowser#assistantAnswerText,
QTextBrowser#assistantAnswerText::viewport {
    color: #202938;
    background: transparent;
    border: 0;
    font-size: 11.5pt;
}
QFrame#assistantComposer {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 13px;
}
QPlainTextEdit#assistantInput {
    background: transparent;
    border: 0;
    color: #111827;
    font-size: 12pt;
    padding: 3px;
}
QLabel#assistantInputPlaceholder {
    background: transparent;
    color: #7a8596;
    font-size: 13px;
}
QPushButton#assistantSendButton {
    background: #1768e5;
    color: white;
    border: 0;
    border-radius: 9px;
    padding: 5px 14px;
    min-height: 30px;
    max-height: 36px;
    font-size: 11.5pt;
    font-weight: 700;
}
QPushButton#assistantSendButton:hover { background: #0f57c8; }
QPushButton#assistantSendButton:disabled { background: #9fb7d9; }
QPushButton#assistantQuickButton,
QToolButton#assistantQuickButton {
    background: #f7f8fa;
    color: #1f2937;
    border: 1px solid #98a2b3;
    border-radius: 10px;
    padding: 4px 9px;
    min-height: 28px;
    max-height: 34px;
    font-size: 11pt;
}
QPushButton#assistantQuickButton:hover,
QToolButton#assistantQuickButton:hover {
    background: #d6e4ff;
    color: #0a327a;
    border-color: #155eef;
}
QLabel#assistantHint { color: #667085; font-size: 10.5pt; }
QFrame#assistantHistoryPanel { background:#f7f9fc; border:0; border-right:1px solid #d8e0eb; }
QListWidget#assistantHistoryList { background:transparent; border:0; }
QLabel#assistantStaleBanner { background:#fff7e6; color:#7a4b00; border:1px solid #f0cf91; border-radius:8px; padding:7px; }
QFrame#assistantTaskCard { background:#f8fbff; border:1px solid #b8c6d9; border-radius:10px; }
QLabel#assistantTaskEyebrow { color:#155eef; font-size:10.5pt; font-weight:700; }
QLabel#assistantTaskTitle { color:#101828; font-size:14px; font-weight:700; }
QLabel#assistantTaskBody { color:#344054; font-size:11pt; }
QLabel#assistantTaskMeta { color:#667085; font-size:10pt; }
QPushButton#assistantTaskAction { background:#155eef; color:white; border:0; border-radius:8px; padding:5px 12px; min-height:30px; max-height:36px; font-weight:700; }
QPushButton#assistantTaskAction:hover { background:#004eeb; }
QPushButton#assistantTaskAction:disabled { background:#9fb7d9; }
"""


class AssistantInput(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantInput")
        self.setPlaceholderText("")
        self._placeholder = QLabel("输入问题…", self.viewport())
        self._placeholder.setObjectName("assistantInputPlaceholder")
        self._placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.textChanged.connect(self._sync_placeholder)
        self._sync_placeholder()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._placeholder.setGeometry(8, 7, max(1, self.viewport().width() - 16), 28)

    def _sync_placeholder(self) -> None:
        self._placeholder.setVisible(not self.toPlainText().strip())
        if self._placeholder.isVisible():
            self._placeholder.raise_()


class ChatBubble(QFrame):
    def __init__(self, text: str, *, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantUserBubble" if role == "user" else "assistantAnswerBubble")
        self.setMaximumWidth(760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(0)
        if role == "user":
            body = QLabel(text)
            body.setObjectName("assistantUserMessage")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(body)
            return
        body = QTextBrowser()
        body.setObjectName("assistantAnswerText")
        body.setOpenExternalLinks(False)
        body.setFrameShape(QFrame.Shape.NoFrame)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setHtml(text)
        body.document().setDocumentMargin(0)
        body.setMinimumHeight(24)
        body.setMaximumHeight(900)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body.document().documentLayout().documentSizeChanged.connect(
            lambda size: body.setFixedHeight(max(26, min(900, int(size.height()) + 5)))
        )
        layout.addWidget(body)


class AiAssistantDialog(QDialog):


    visibilityChanged = Signal(bool)
    actionRequested = Signal(object)
    REQUEST_KEY = "assistant.local_query"

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._page_id = "home"
        self._drag_offset: QPoint | None = None
        self._user_moved = False
        self._bridge = LocalKnowledgeBridge(parent=self)
        self._advisor = ResearchAdvisor()
        self._guidance = GuidanceSession()
        self._settings = QSettings("OpticalMLWorkspace", "OpticalFrontend")
        self._history_store = AssistantConversationStore()
        self._conversation_id = ""
        self._history_visible = False
        self._maximized_by_user = False
        self._manual_resize_edges = Qt.Edge(0)
        self._manual_resize_origin = QPoint()
        self._manual_resize_geometry = QRect()
        self._live_action_buttons: list[tuple[QPushButton, dict[str, Any]]] = []

        self.setObjectName("aiAssistantDialog")
        self.setWindowTitle("智能助手")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        # 全局弹窗规范：即使使用无边框外观，也必须保留可缩放语义。
        # 实际拖拽缩放由下方四边/四角 geometry fallback 实现；size grip
        # 同时让 Qt/辅助技术明确知道该窗口不是固定尺寸。
        self.setSizeGripEnabled(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_ASSISTANT_QSS)
        self.setMinimumSize(460, 480)
        self.resize(560, 660)
        self.setMouseTracking(True)
        saved_geometry = self._settings.value("assistant/dialog_geometry")
        if saved_geometry:
            self.restoreGeometry(saved_geometry)
            self._user_moved = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        surface = QFrame()
        surface.setObjectName("assistantWindowSurface")
        outer.addWidget(surface)
        root = QVBoxLayout(surface)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.setHandleWidth(1)
        self.history_panel = self._build_history_panel()
        self.history_panel.hide()
        self.body_splitter.addWidget(self.history_panel)
        self.chat_host = QWidget()
        chat_host = self.chat_host
        chat_layout = QVBoxLayout(chat_host)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        self.task_card = self._build_task_card()
        chat_layout.addWidget(self.task_card)
        self.stale_host = QFrame()
        self.stale_host.setObjectName("assistantStaleHost")
        stale_layout = QHBoxLayout(self.stale_host)
        stale_layout.setContentsMargins(10, 7, 10, 7)
        stale_layout.setSpacing(8)
        self.stale_banner = QLabel("")
        self.stale_banner.setObjectName("assistantStaleBanner")
        self.stale_banner.setWordWrap(True)
        stale_layout.addWidget(self.stale_banner, 1)
        self.stale_continue_button = QPushButton("基于当前状态继续")
        self.stale_continue_button.setObjectName("assistantQuickButton")
        self.stale_continue_button.clicked.connect(self._adopt_current_context_for_chat)
        stale_layout.addWidget(self.stale_continue_button, 0)
        self.stale_host.hide()
        chat_layout.addWidget(self.stale_host)
        chat_layout.addWidget(self._build_messages(), 1)
        chat_layout.addWidget(self._build_composer())
        self.body_splitter.addWidget(chat_host)
        self.body_splitter.setSizes([220, 560])
        root.addWidget(self.body_splitter, 1)

        self._bridge.completed.connect(self._on_completed)
        self._bridge.failed.connect(self._on_failed)
        # AI 顶部状态和动作卡必须跟随研究状态实时变化；历史文字保留，但旧动作
        # 不能继续诱导用户重复执行已经完成的任务。
        self.context.project.formal_result_changed.connect(lambda *_: self._research_state_changed())
        self.context.project.design_revision_changed.connect(lambda *_: self._research_state_changed())
        self.context.project.findings_changed.connect(lambda *_: self._research_state_changed())
        self.context.project.research_journal_changed.connect(lambda *_: self._research_state_changed())
        self.context.registry.current_model_changed.connect(lambda *_: self._research_state_changed())
        self.context.registry.current_dataset_changed.connect(lambda *_: self._research_state_changed())
        self.context.tasks.tasks_changed.connect(self._guidance_tasks_changed)
        self.context.tasks.task_result_changed.connect(lambda *_: self._guidance_tasks_changed(self.context.tasks.tasks))
        self._new_chat(persist=False)
        self._refresh_task_card()
        self._apply_responsive_layout()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("assistantHeader")
        header.installEventFilter(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(6)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("智能助手")
        title.setObjectName("assistantTitle")
        self.status_label = QLabel("当前研究助手")
        self.status_label.setObjectName("assistantStatus")
        title_box.addWidget(title)
        title_box.addWidget(self.status_label)
        layout.addLayout(title_box)
        layout.addStretch(1)

        history_button = QToolButton()
        history_button.setObjectName("assistantHeaderButton")
        history_button.setIcon(icon("history", "#4b5565", 18))
        history_button.setToolTip("历史对话")
        history_button.clicked.connect(self._toggle_history)
        layout.addWidget(history_button)

        new_button = QToolButton()
        new_button.setObjectName("assistantHeaderButton")
        new_button.setIcon(icon("add", "#4b5565", 18))
        new_button.setToolTip("新建对话")
        new_button.clicked.connect(self._new_chat)
        layout.addWidget(new_button)

        hide_button = QToolButton()
        hide_button.setObjectName("assistantHeaderButton")
        hide_button.setIcon(icon("minus", "#4b5565", 18))
        hide_button.setToolTip("收起")
        hide_button.clicked.connect(self.hide)
        layout.addWidget(hide_button)

        close_button = QToolButton()
        close_button.setObjectName("assistantHeaderButton")
        close_button.setIcon(icon("close", "#4b5565", 18))
        close_button.setToolTip("关闭")
        close_button.clicked.connect(self.hide)
        layout.addWidget(close_button)
        return header

    def _build_task_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("assistantTaskCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        self.task_eyebrow = QLabel("当前建议")
        self.task_eyebrow.setObjectName("assistantTaskEyebrow")
        head_row.addWidget(self.task_eyebrow, 1)
        self.task_collapse_button = QToolButton()
        self.task_collapse_button.setText("收起 ▴")
        self.task_collapse_button.setObjectName("assistantQuickButton")
        self.task_collapse_button.clicked.connect(self._toggle_task_card_details)
        head_row.addWidget(self.task_collapse_button)
        layout.addLayout(head_row)
        self.task_title = QLabel("正在读取当前研究状态…")
        self.task_title.setObjectName("assistantTaskTitle")
        self.task_title.setWordWrap(True)
        layout.addWidget(self.task_title)
        self.task_state = QLabel("")
        self.task_state.setObjectName("assistantTaskBody")
        self.task_state.setWordWrap(True)
        layout.addWidget(self.task_state)
        self.task_why = QLabel("")
        self.task_why.setObjectName("assistantTaskMeta")
        self.task_why.setWordWrap(True)
        layout.addWidget(self.task_why)
        self.task_effect = QLabel("")
        self.task_effect.setObjectName("assistantTaskMeta")
        self.task_effect.setWordWrap(True)
        layout.addWidget(self.task_effect)
        row = QHBoxLayout()
        row.addStretch(1)
        self.task_action_button = QPushButton("查看建议")
        self.task_action_button.setObjectName("assistantTaskAction")
        self.task_action_button.clicked.connect(self._dispatch_task_card_action)
        row.addWidget(self.task_action_button)
        layout.addLayout(row)
        self._task_action: dict[str, Any] = {}
        self._task_details_collapsed = bool(self._settings.value("assistant/advice_collapsed", False, type=bool))
        self._apply_task_card_collapsed_state()
        return card

    def _toggle_task_card_details(self) -> None:
        self._task_details_collapsed = not bool(getattr(self, "_task_details_collapsed", False))
        self._settings.setValue("assistant/advice_collapsed", self._task_details_collapsed)
        self._apply_task_card_collapsed_state()
        self._apply_responsive_layout()

    def _apply_task_card_collapsed_state(self) -> None:
        collapsed = bool(getattr(self, "_task_details_collapsed", False))
        for widget in (getattr(self, "task_state", None), getattr(self, "task_why", None), getattr(self, "task_effect", None)):
            if widget is not None:
                widget.setVisible(not collapsed)
        if hasattr(self, "task_collapse_button"):
            self.task_collapse_button.setText("展开 ▾" if collapsed else "收起 ▴")

    def _refresh_task_card(self) -> None:
        if not hasattr(self, "task_title"):
            return
        if self._guidance.active:
            view, _transition = self._guidance.observe(self.context.tasks.tasks)
            if view is not None:
                if view.phase == "completed":
                    view = self._enrich_completed_guidance(view)
                self._apply_guidance_view(view)
                return
        self.task_eyebrow.setText("当前建议")
        try:
            payload = self._project_payload()
            answer = self._advisor.next_step(self._page_id, payload)
        except Exception as exc:
            self.task_title.setText("当前建议暂时不可用")
            self.task_state.setText(f"状态读取失败：{type(exc).__name__}")
            self.task_why.setText("")
            self.task_effect.setText("")
            self.task_action_button.setEnabled(False)
            self._task_action = {}
            return
        findings = [dict(item) for item in (answer.get("findings") or []) if isinstance(item, dict)]
        current = findings[0].get("explanation", "") if findings else str(answer.get("summary") or "")
        meaning = findings[1].get("explanation", "") if len(findings) > 1 else ""
        next_item = findings[2] if len(findings) > 2 else {}
        next_title = str(next_item.get("title") or "建议下一步").replace("下一步：", "")
        why = str(next_item.get("explanation") or "")
        actions = [dict(item) for item in (answer.get("actions") or []) if isinstance(item, dict)]
        action = normalize_action(actions[0] if actions else {}, why=why) if actions else {}
        self._task_action = action
        self.task_title.setText(next_title if actions else "当前状态暂时不需要额外操作")
        state_bits = [str(current).strip(), str(meaning).strip()]
        self.task_state.setText("\n".join(bit for bit in state_bits if bit))
        self.task_why.setText(("为什么：" + why) if why else "")
        effect = str(action.get("expected_effect", "") or "") if action else ""
        next_text = str(action.get("what_happens_next", "") or "") if action else ""
        self.task_effect.setText(("点击后：" + effect + (" " + next_text if next_text else "")) if effect else "")
        self.task_action_button.setText(str(action.get("label") or "查看当前状态"))
        self.task_action_button.setEnabled(bool(action) and not bool(action.get("disabled")))
        self.task_action_button.setVisible(bool(action))
        self._apply_task_card_collapsed_state()
        self._apply_responsive_layout()

    def _enrich_completed_guidance(self, view: GuidanceView) -> GuidanceView:
        """Use the existing evidence-aware advisor to explain the completed step.

        GuidanceSession owns continuity; ResearchAdvisor supplies the current
        scan/model numbers after the page has published them into ProjectContext.
        """
        try:
            answer = self._advisor.next_step(self._page_id, self._project_payload())
        except Exception:
            return view
        findings = [dict(item) for item in (answer.get("findings") or []) if isinstance(item, dict)]
        actions = [dict(item) for item in (answer.get("actions") or []) if isinstance(item, dict)]
        if len(findings) < 3:
            return view
        current = str(findings[0].get("explanation") or "").strip()
        meaning = str(findings[1].get("explanation") or "").strip()
        next_item = findings[2]
        next_title = str(next_item.get("title") or "建议下一步").replace("下一步：", "").strip()
        why = str(next_item.get("explanation") or "").strip()
        action = normalize_action(actions[0], why=why) if actions else dict(view.action)
        return GuidanceView(
            active=True,
            eyebrow="持续指导 · 已完成",
            title=next_title or view.title,
            state="\n".join(bit for bit in (current, meaning) if bit),
            why=why or view.why,
            effect=str(action.get("what_happens_next") or view.effect),
            action=action,
            phase=view.phase,
            job_id=view.job_id,
        )

    def _apply_guidance_view(self, view: GuidanceView) -> None:
        self.task_eyebrow.setText(str(view.eyebrow or "持续指导"))
        self.task_title.setText(str(view.title or "继续当前研究"))
        self.task_state.setText(str(view.state or ""))
        self.task_why.setText(("为什么：" + str(view.why)) if view.why else "")
        self.task_effect.setText(("接下来：" + str(view.effect)) if view.effect else "")
        action = normalize_action(view.action) if view.action else {}
        self._task_action = action
        self.task_action_button.setText(str(action.get("label") or "查看当前状态"))
        self.task_action_button.setEnabled(bool(action) and not bool(action.get("disabled")))
        self.task_action_button.setVisible(bool(action))
        self._apply_responsive_layout()

    @staticmethod
    def _guidance_target_supported(target: str) -> bool:
        return str(target or "") in {
            "simulation.formal",
            "optimization.scan",
            "optimization.tolerance",
            "optimization.variables",
            "optimization.variable_structure",
            "machine_learning.training",
        }

    def _begin_guidance(self, action: dict[str, Any]) -> None:
        target = str(action.get("target", "") or "")
        if not self._guidance_target_supported(target):
            return
        # A completed session can keep following user-initiated refinements.
        # Merely clicking its “查看结果” navigation button must not reset it.
        if self._guidance.active and self._guidance.target == target and self._guidance.phase in {"completed", "running", "await_user"}:
            return
        self._guidance.begin(action, self.context.tasks.tasks)
        self._refresh_task_card()

    def _guidance_tasks_changed(self, _tasks=None) -> None:
        view, transition = self._guidance.observe(self.context.tasks.tasks)
        self._refresh_context_hint()
        if view is not None:
            if view.phase == "completed":
                view = self._enrich_completed_guidance(view)
                if transition is not None:
                    transition = dict(transition)
                    transition["view"] = view
            self._apply_guidance_view(view)
        else:
            self._refresh_task_card()
        self._refresh_live_actions()
        if transition is not None:
            self._append_guidance_transition(transition)

    def _append_guidance_transition(self, transition: dict[str, Any]) -> None:
        if not self.isVisible():
            return
        phase = str(transition.get("phase", "") or "")
        view = transition.get("view")
        if not isinstance(view, GuidanceView):
            return
        if phase == "completed":
            body = (
                f"<p><b>{self._html_text(view.title)}</b></p>"
                f"<p>{self._html_text(view.state)}</p>"
                f"<p><b>下一步：</b>{self._html_text(view.effect)}</p>"
            )
        else:
            body = (
                f"<p><b>{self._html_text(view.title)}</b></p>"
                f"<p>{self._html_text(view.state)}</p>"
                f"<p><b>处理建议：</b>{self._html_text(view.effect)}</p>"
            )
        self._append_assistant(body)
        if view.action:
            self._append_action_buttons([view.action])

    def _dispatch_task_card_action(self) -> None:
        action = normalize_action(self._task_action) if self._task_action else {}
        if not action or action.get("disabled"):
            return
        self._begin_guidance(action)
        self.actionRequested.emit(action)

    def _build_history_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("assistantHistoryPanel")
        panel.setMinimumWidth(190)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        title = QLabel("历史对话")
        title.setObjectName("assistantTitle")
        layout.addWidget(title)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("搜索对话")
        self.history_search.textChanged.connect(self._refresh_history_list)
        layout.addWidget(self.history_search)
        self.history_list = QListWidget()
        self.history_list.setObjectName("assistantHistoryList")
        self.history_list.itemActivated.connect(self._open_history_item)
        self.history_list.currentItemChanged.connect(lambda _a, _b: None)
        layout.addWidget(self.history_list, 1)
        actions = QGridLayout()
        actions.setHorizontalSpacing(5)
        actions.setVerticalSpacing(4)
        rename = QPushButton("重命名"); rename.clicked.connect(self._rename_history)
        pin = QPushButton("固定"); pin.clicked.connect(self._pin_history)
        delete = QPushButton("删除"); delete.clicked.connect(self._delete_history)
        self.history_action_buttons = [rename, pin, delete]
        self.history_actions_layout = actions
        for column, button in enumerate(self.history_action_buttons):
            button.setObjectName("assistantQuickButton")
            actions.addWidget(button, 0, column)
        layout.addLayout(actions)
        return panel

    def _toggle_history(self) -> None:
        self._history_visible = not self._history_visible
        self.history_panel.setVisible(self._history_visible)
        if self._history_visible:
            self._refresh_history_list()
        self._apply_responsive_layout()

    @staticmethod
    def _history_group(updated_at: str) -> str:
        try:
            stamp = datetime.fromisoformat(str(updated_at))
            today = datetime.now().date()
            delta = (today - stamp.date()).days
            return "今天" if delta == 0 else "昨天" if delta == 1 else "更早"
        except Exception:
            return "更早"

    def _refresh_history_list(self, *_args) -> None:
        if not hasattr(self, "history_list"):
            return
        query = self.history_search.text().strip().lower() if hasattr(self, "history_search") else ""
        current_id = self._conversation_id
        self.history_list.clear()
        records = self._history_store.all()
        groups = ("今天", "昨天", "更早")
        for group in groups:
            group_rows = [row for row in records if self._history_group(str(row.get("updated_at", ""))) == group]
            group_rows = [row for row in group_rows if not query or query in str(row.get("title", "")).lower()]
            if not group_rows:
                continue
            header = QListWidgetItem(group)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history_list.addItem(header)
            for row in group_rows:
                prefix = "★ " if row.get("pinned") else ""
                item = QListWidgetItem(prefix + str(row.get("title") or "新对话"))
                item.setData(Qt.ItemDataRole.UserRole, str(row.get("id", "")))
                item.setToolTip(str(row.get("updated_at", "")))
                self.history_list.addItem(item)
                if str(row.get("id", "")) == current_id:
                    self.history_list.setCurrentItem(item)

    def _selected_history_id(self) -> str:
        item = self.history_list.currentItem() if hasattr(self, "history_list") else None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def _open_history_item(self, item: QListWidgetItem) -> None:
        conversation_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not conversation_id:
            return
        record = self._history_store.get(conversation_id)
        if not record:
            return
        self._conversation_id = conversation_id
        self._clear_message_widgets()
        for message in list(record.get("messages", []) or []):
            if not isinstance(message, dict):
                continue
            self._add_bubble(str(message.get("content", "")), str(message.get("role", "assistant")), persist=False, html=bool(message.get("html")))
        if not list(record.get("messages", []) or []):
            self._append_welcome()
        self._update_stale_banner(record)
        self._refresh_history_list()

    def _rename_history(self) -> None:
        conversation_id = self._selected_history_id()
        record = self._history_store.get(conversation_id) if conversation_id else None
        if not record:
            return
        title, ok = QInputDialog.getText(self, "重命名对话", "标题", text=str(record.get("title", "")))
        if ok and title.strip():
            self._history_store.rename(conversation_id, title.strip())
            self._refresh_history_list()

    def _pin_history(self) -> None:
        conversation_id = self._selected_history_id()
        if conversation_id:
            self._history_store.toggle_pin(conversation_id)
            self._refresh_history_list()

    def _delete_history(self) -> None:
        conversation_id = self._selected_history_id()
        if not conversation_id:
            return
        self._history_store.delete(conversation_id)
        if conversation_id == self._conversation_id:
            self._new_chat()
        else:
            self._refresh_history_list()

    def _conversation_snapshot(self) -> dict[str, Any]:
        try:
            payload = self._project_payload()
        except Exception:
            payload = {}
        registry = dict(payload.get("registry", {}) or {})
        findings = [dict(row) for row in list(payload.get("findings", []) or []) if isinstance(row, dict)]
        research = dict(payload.get("research_results", {}) or {})
        tasks_by_id = dict(research.get("tasks_by_id", {}) or {})
        formal = dict(payload.get("formal_result", {}) or {})
        return {
            "design_revision": int(payload.get("design_revision", 0) or 0),
            "model_id": str(registry.get("current_model_id", "") or ""),
            "recent_model_id": str(registry.get("recent_model_id", "") or ""),
            "dataset_id": str(registry.get("current_dataset_id", "") or ""),
            "page": str(dict(payload.get("page_context", {}) or {}).get("page") or self._page_id),
            "page_id": self._page_id,
            "findings": {
                str(row.get("id") or row.get("finding_id") or f"finding-{index}"): {
                    "status": str(row.get("status", "当前")),
                    "source": str(row.get("source", "")),
                    "parameter": str(row.get("display_name") or row.get("parameter") or ""),
                }
                for index, row in enumerate(findings)
            },
            "finding_status_counts": dict(dict(payload.get("assistant_research_snapshot", {}) or {}).get("finding_status_counts", {}) or {}),
            "formal": {
                "status": str(formal.get("status", "") or ""),
                "source": str(formal.get("source", "") or ""),
                "version": str(formal.get("version", "") or ""),
            },
            "tasks": {
                str(task_id): {
                    "status": str(dict(task).get("status", "")),
                    "kind": str(dict(task).get("kind", dict(task).get("type", ""))),
                }
                for task_id, task in tasks_by_id.items() if isinstance(task, dict)
            },
            "journal_tail": [
                {
                    "event_id": str(row.get("event_id", "")),
                    "kind": str(row.get("kind", "")),
                    "design_revision": int(row.get("design_revision", 0) or 0),
                }
                for row in list(payload.get("research_journal", []) or [])[-12:]
                if isinstance(row, dict)
            ],
        }

    def _update_stale_banner(self, record: dict | None = None) -> None:
        if not hasattr(self, "stale_banner"):
            return
        record = record or self._history_store.get(self._conversation_id) or {}
        old = dict(record.get("snapshot", {}) or {})
        now = self._conversation_snapshot()
        differences = []
        if old and int(old.get("design_revision", 0) or 0) != int(now.get("design_revision", 0) or 0):
            differences.append(f"系统版本 {old.get('design_revision', 0)} → {now.get('design_revision', 0)}")
        if old and str(old.get("model_id", "")) != str(now.get("model_id", "")):
            differences.append("当前模型已变化")
        if differences:
            self.stale_banner.setText("⚠ 这段历史对话对应的系统参数已经发生变化：" + "；".join(differences) + "。继续提问时会按现在的当前系统回答，之前的结论不会自动当作当前结果。")
            self.stale_host.show()
        else:
            self.stale_host.hide()

    def _adopt_current_context_for_chat(self) -> None:
        if self._conversation_id:
            self._history_store.update_snapshot(self._conversation_id, self._conversation_snapshot())
            self._update_stale_banner()

    def _resize_edges_at(self, pos: QPoint) -> Qt.Edge:
        margin = 12
        edges = Qt.Edge(0)
        if pos.x() <= margin: edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - margin: edges |= Qt.Edge.RightEdge
        if pos.y() <= margin: edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - margin: edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges: Qt.Edge):
        if edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._maximized_by_user = False
        else:
            self.showMaximized()
            self._maximized_by_user = True

    def _build_messages(self) -> QWidget:
        self.messages_scroll = QScrollArea()
        self.messages_scroll.setObjectName("assistantMessagesScroll")
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_host = QWidget()
        self.messages_host.setObjectName("assistantMessagesHost")
        self.messages_layout = QVBoxLayout(self.messages_host)
        self.messages_layout.setContentsMargins(10, 14, 10, 12)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch(1)
        self.messages_scroll.setWidget(self.messages_host)
        return self.messages_scroll

    def _build_composer(self) -> QWidget:
        host = QWidget()
        self.composer_host = host
        layout = QVBoxLayout(host)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(5)
        quick_grid = QGridLayout()
        self.quick_grid = quick_grid
        quick_grid.setHorizontalSpacing(6)
        quick_grid.setVerticalSpacing(4)
        quick_questions = (
            ("下一步", "我现在应该怎么继续？"),
            ("解释结果", "解释当前结果"),
            ("可靠吗", "当前结果可靠吗？"),
        )
        self.quick_buttons: list[QWidget] = []
        for index, (label, text) in enumerate(quick_questions):
            button = QPushButton(label)
            button.setObjectName("assistantQuickButton")
            button.setToolTip(text)
            button.clicked.connect(lambda checked=False, value=text: self._ask_quick_question(value))
            self.quick_buttons.append(button)
            quick_grid.addWidget(button, 0, index)
        more_button = QToolButton()
        more_button.setText("更多 ▾")
        more_button.setObjectName("assistantQuickButton")
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more_button)
        for label, question in (("我该从哪里开始", "我该从哪里开始？"), ("当前主要问题", "当前主要问题是什么？"), ("总结研究状态", "总结当前研究状态"), ("模型能否用于 SHAP", "模型还能用于 SHAP 吗？"), ("当前依据", "我现在有哪些可用结果？")):
            action = more_menu.addAction(label)
            action.triggered.connect(lambda checked=False, value=question: self._ask_quick_question(value))
        more_button.setMenu(more_menu)
        self.quick_buttons.append(more_button)
        quick_grid.addWidget(more_button, 0, 3)
        quick_grid.setColumnStretch(3, 1)
        layout.addLayout(quick_grid)
        self.context_hint = QLabel("")
        self.context_hint.setObjectName("assistantHint")
        self.context_hint.setWordWrap(True)
        layout.addWidget(self.context_hint)

        composer = QFrame()
        self.composer_frame = composer
        composer.setObjectName("assistantComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(10, 8, 9, 8)
        composer_layout.setSpacing(5)
        self.input = AssistantInput()
        self.input.setFixedHeight(66)
        self.input.installEventFilter(self)
        composer_layout.addWidget(self.input)
        bottom = QHBoxLayout()
        hint = QLabel("回车发送，Shift＋回车换行")
        self.send_hint = hint
        hint.setObjectName("assistantHint")
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("assistantSendButton")
        self.send_button.clicked.connect(self._send_question)
        bottom.addWidget(self.send_button)
        composer_layout.addLayout(bottom)
        layout.addWidget(composer)
        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self))
        layout.addLayout(grip_row)
        return host

    def set_page_context(self, page_id: str) -> None:
        self._page_id = page_id or "home"
        self._refresh_context_hint()
        self._refresh_task_card()

    def show_anchored(self) -> None:
        self._refresh_context_hint()
        self._refresh_task_card()
        if not self._user_moved:
            self.anchor_to_parent()
        else:
            self.clamp_to_parent()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()


    def _refresh_context_hint(self) -> None:
        if not hasattr(self, "context_hint"):
            return
        try:
            payload = self._project_payload()
            findings = [row for row in payload.get("findings", []) if isinstance(row, dict)]
            current = sum(1 for row in findings if str(row.get("status", "当前") or "当前") in {"当前", "已验证"})
            stale = sum(1 for row in findings if str(row.get("status", "")) == "需更新")
            model = dict(dict(payload.get("registry", {}) or {}).get("current_model", {}) or {})
            model_text = "未选模型"
            if model:
                blocks = [dict(model.get(key, {}) or {}) for key in ("test_metrics", "metrics") if isinstance(model.get(key), dict)]
                r2 = next((block.get("r2", block.get("test_r2")) for block in blocks if isinstance(block.get("r2", block.get("test_r2")), (int, float))), None)
                if isinstance(r2, (int, float)):
                    if float(r2) < 0:
                        model_text = f"模型 R²={float(r2):.3f}（不建议 SHAP）"
                    elif float(r2) < 0.6:
                        model_text = f"模型 R²={float(r2):.3f}（仅探索）"
                    else:
                        model_text = f"模型 R²={float(r2):.3f}"
                else:
                    model_text = "已选模型（待评估）"
            page_name = str(dict(payload.get("page_context", {}) or {}).get("page") or self._page_id or "当前页面")
            parts = [f"当前：{page_name}"]
            formal = dict(payload.get("formal_result", {}) or {})
            if formal:
                current_revision = int(payload.get("design_revision", 0) or 0)
                formal_revision = formal.get("design_revision", formal.get("project_revision", formal.get("revision")))
                status = str(formal.get("status", "") or "").lower()
                if isinstance(formal_revision, (int, float)) and current_revision and int(formal_revision) != current_revision:
                    parts.append("完整仿真需要重新计算")
                elif status in {"completed", "success", "done"} and formal.get("converged") is not False:
                    parts.append("完整仿真已完成")
                elif status in {"failed", "cancelled", "error"} or formal.get("converged") is False:
                    parts.append("完整仿真未通过")
                else:
                    parts.append("完整仿真已有结果")
            elif self._page_id in {"simulation", "optimization"}:
                parts.append("还没有完整仿真")
            if current or stale:
                record_text = f"分析记录 {current} 条"
                if stale:
                    record_text += f"，其中 {stale} 条要重算"
                parts.append(record_text)
            parts.append(model_text)
            error_count = len(list(payload.get("context_collection_errors", []) or []))
            if error_count:
                parts.append(f"读取状态异常 {error_count} 项")
            self.context_hint.setText(" · ".join(parts))
        except Exception:
            self.context_hint.setText(f"当前：{self._page_id or '当前页面'}")

    def _apply_responsive_layout(self) -> None:
        """Keep the frameless assistant usable at every advertised size.

        The normal layout keeps all research context visible.  At short/narrow
        sizes, secondary metadata collapses and button rows reflow instead of
        letting Qt squeeze child widgets on top of one another.  Enlarging the
        window restores the complete content.
        """
        if not hasattr(self, "input"):
            return
        compact_h = self.height() < 580
        compact_w = self.width() < 620
        narrow_history = bool(self._history_visible and self.width() < 540)

        # The recommendation title and action are always retained.  Explanatory
        # metadata is secondary at short heights; the current-state paragraph is
        # hidden only when the history rail and chat must share the absolute
        # minimum width.
        state_has_text = bool(self.task_state.text().strip())
        advice_collapsed = bool(getattr(self, "_task_details_collapsed", False))
        self.task_state.setVisible((not advice_collapsed) and state_has_text and not narrow_history)
        self.task_why.setVisible((not advice_collapsed) and (not compact_h) and bool(self.task_why.text().strip()))
        self.task_effect.setVisible((not advice_collapsed) and (not compact_h) and bool(self.task_effect.text().strip()))
        self.context_hint.setVisible(not compact_h)
        self.input.setFixedHeight(48 if compact_h else 66)
        if hasattr(self, "send_hint"):
            self.send_hint.setText("回车发送" if compact_w else "回车发送，Shift＋回车换行")
        # Never allow the composer frame itself to become shorter than the input
        # plus its send row.  QBoxLayout may otherwise compress it by a few pixels
        # at the 460×480 minimum and visually cut the blue send button.
        if hasattr(self, "composer_frame"):
            self.composer_frame.setMinimumHeight(96 if compact_h else 0)
        if hasattr(self, "messages_scroll"):
            self.messages_scroll.setMinimumHeight(34 if compact_h else 0)

        # Preserve enough height for wrapped state text when it is visible.
        # QLabel's sizeHint can underestimate height-for-width during a live
        # frameless resize, so calculate it against the expected chat width.
        if self.task_state.isVisible():
            history_w = 160 if (self._history_visible and compact_w) else 220 if self._history_visible else 0
            label_w = max(120, self.width() - history_w - 46)
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
            needed = self.task_state.fontMetrics().boundingRect(0, 0, label_w, 1000, flags, self.task_state.text()).height()
            self.task_state.setMinimumHeight(max(0, needed + 2))
        else:
            self.task_state.setMinimumHeight(0)
        if hasattr(self, "task_card"):
            # Recompute after visibility changes; this prevents the action button
            # from being laid over a longer wrapped state paragraph.
            self.task_card.setMinimumHeight(0)
            if self.task_card.layout() is not None:
                self.task_card.layout().activate()
            self.task_card.setMinimumHeight(max(96, self.task_card.sizeHint().height()))

        # Reflow the four quick actions into 2x2 only when the actual chat pane
        # is narrow (not merely because the whole dialog is compact).
        if hasattr(self, "quick_grid") and hasattr(self, "quick_buttons"):
            expected_chat_w = self.width() - (160 if self._history_visible and compact_w else 220 if self._history_visible else 0) - 22
            two_rows = expected_chat_w < 390
            for button in self.quick_buttons:
                self.quick_grid.removeWidget(button)
            for index, button in enumerate(self.quick_buttons):
                row, column = (divmod(index, 2) if two_rows else (0, index))
                self.quick_grid.addWidget(button, row, column)
            for column in range(4):
                self.quick_grid.setColumnStretch(column, 1 if (not two_rows or column < 2) else 0)

        # History remains available at narrow widths, but must not starve the
        # chat pane.  Its action row becomes two rows instead of clipping labels.
        if hasattr(self, "history_panel"):
            self.history_panel.setMinimumWidth(150 if compact_w else 190)
            self.history_panel.setMaximumWidth(190 if compact_w else 280)
            if hasattr(self, "history_actions_layout") and hasattr(self, "history_action_buttons"):
                for button in self.history_action_buttons:
                    self.history_actions_layout.removeWidget(button)
                if compact_w:
                    self.history_actions_layout.addWidget(self.history_action_buttons[0], 0, 0)
                    self.history_actions_layout.addWidget(self.history_action_buttons[1], 0, 1)
                    self.history_actions_layout.addWidget(self.history_action_buttons[2], 1, 0, 1, 2)
                else:
                    for column, button in enumerate(self.history_action_buttons):
                        self.history_actions_layout.addWidget(button, 0, column)
            if self._history_visible:
                history_w = 160 if compact_w else 220
                self.body_splitter.setSizes([history_w, max(260, self.width() - history_w)])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_anchored()

    def anchor_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 20
        bottom_right = parent.mapToGlobal(parent.rect().bottomRight())
        self.move(
            bottom_right.x() - self.width() - margin,
            bottom_right.y() - self.height() - margin,
        )

    def clamp_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        top_left = parent.mapToGlobal(parent.rect().topLeft())
        bottom_right = parent.mapToGlobal(parent.rect().bottomRight())
        x = min(max(self.x(), top_left.x()), max(top_left.x(), bottom_right.x() - self.width()))
        y = min(max(self.y(), top_left.y()), max(top_left.y(), bottom_right.y() - self.height()))
        self.move(x, y)

    def eventFilter(self, watched, event) -> bool:
        input_widget = getattr(self, "input", None)
        if watched is input_widget and event.type() == QEvent.Type.KeyPress:
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._send_question()
                return True
        if getattr(watched, "objectName", lambda: "")() == "assistantHeader":
            if event.type() == QEvent.Type.MouseButtonDblClick and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_maximized()
                    return True
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    return True
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(event.globalPosition().toPoint() - self._drag_offset)
                    self._user_moved = True
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                self.clamp_to_parent()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._resize_edges_at(event.position().toPoint())
            if edges:
                # Frameless ToolWindow 在部分 Windows/Qt 组合上 startSystemResize
                # 没有可靠反馈，直接保留一个纯 Qt geometry fallback，保证四边四角都可拖。
                self._manual_resize_edges = edges
                self._manual_resize_origin = event.globalPosition().toPoint()
                self._manual_resize_geometry = QRect(self.geometry())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._manual_resize_edges and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._manual_resize_origin
            base = QRect(self._manual_resize_geometry)
            left, top, right, bottom = base.left(), base.top(), base.right(), base.bottom()
            edges = self._manual_resize_edges
            min_w, min_h = self.minimumWidth(), self.minimumHeight()
            if edges & Qt.Edge.LeftEdge:
                left = min(left + delta.x(), right - min_w + 1)
            if edges & Qt.Edge.RightEdge:
                right = max(right + delta.x(), left + min_w - 1)
            if edges & Qt.Edge.TopEdge:
                top = min(top + delta.y(), bottom - min_h + 1)
            if edges & Qt.Edge.BottomEdge:
                bottom = max(bottom + delta.y(), top + min_h - 1)
            self.setGeometry(QRect(QPoint(left, top), QPoint(right, bottom)))
            self._user_moved = True
            event.accept()
            return
        if not self.isMaximized():
            self.setCursor(self._cursor_for_edges(self._resize_edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._manual_resize_edges:
            self._manual_resize_edges = Qt.Edge(0)
            self.unsetCursor()
            self.clamp_to_parent()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _append_welcome(self) -> None:
        self._append_assistant(
            "<p>我会结合当前页面、当前系统和已有分析回答。新用户可直接点下方快捷问题，不必输入完整问题。</p>"
        )

    def _add_bubble(self, text: str, role: str, *, persist: bool = True, html: bool | None = None) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        bubble = ChatBubble(text, role=role)
        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)
        self.messages_layout.insertWidget(max(0, self.messages_layout.count() - 1), row)
        if persist and self._conversation_id:
            self._history_store.append(self._conversation_id, role, text, html=(role != "user") if html is None else bool(html))
            self._refresh_history_list()
        # New user questions should be visible immediately.  For assistant replies
        # we deliberately do not jump to the bottom: long beginner explanations
        # must start at their first line, not halfway through the answer.
        if role == "user":
            QTimer.singleShot(0, lambda: self.messages_scroll.verticalScrollBar().setValue(self.messages_scroll.verticalScrollBar().maximum()))
        return row

    def _scroll_message_to_top(self, widget: QWidget | None) -> None:
        if widget is None or not widget.parent():
            return
        try:
            top = widget.mapTo(self.messages_host, widget.rect().topLeft()).y()
            self.messages_scroll.verticalScrollBar().setValue(max(0, int(top) - 6))
        except RuntimeError:
            return

    def _append_assistant(self, html: str, *, persist: bool = True) -> None:
        self._last_assistant_row = self._add_bubble(html, "assistant", persist=persist, html=True)
        QTimer.singleShot(0, lambda: self._scroll_message_to_top(getattr(self, "_last_assistant_row", None)))
        QTimer.singleShot(35, lambda: self._scroll_message_to_top(getattr(self, "_last_assistant_row", None)))

    def _clear_message_widgets(self) -> None:
        self._live_action_buttons.clear()
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()

    def _new_chat(self, _checked: bool = False, *, persist: bool = True) -> None:
        if persist:
            self._guidance.stop()
        self._clear_message_widgets()
        snapshot = self._conversation_snapshot()
        record = self._history_store.create(snapshot=snapshot)
        self._conversation_id = str(record.get("id", ""))
        self._append_welcome()
        self.input.clear()
        self._update_stale_banner(record)
        self._refresh_history_list()
        self.input.setFocus()

    def _ask_quick_question(self, question: str) -> None:
        self.input.setPlainText(str(question))
        self._send_question()

    def _send_question(self) -> None:
        question = self.input.toPlainText().strip()
        if not question:
            self.input.setFocus()
            return
        self.input.clear()
        self._add_bubble(question, "user")
        self.status_label.setText("正在结合当前研究上下文…")
        self.send_button.setEnabled(False)
        self.input.setReadOnly(True)
        self._bridge.ask(
            self.REQUEST_KEY,
            question=question,
            page_id=self._page_id,
            project=self._project_payload(),
            audience="beginner",
        )


    @staticmethod
    def _compact_research_value(value: Any, *, depth: int = 0) -> Any:
        """Keep complete *meaningful* research context while summarising dense arrays/plot buffers."""
        if depth > 5:
            return "…"
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                text_key = str(key)
                # Raw images/huge plotting buffers are represented by shape/size, not copied into AI text.
                if text_key.lower() in {"image", "rgba", "rgb", "field_complex", "complex_field"}:
                    result[text_key] = AiAssistantDialog._compact_research_value(item, depth=depth + 1)
                    continue
                result[text_key] = AiAssistantDialog._compact_research_value(item, depth=depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            if len(value) <= 30:
                return [AiAssistantDialog._compact_research_value(item, depth=depth + 1) for item in value]
            # Preserve endpoints and size for long scan vectors.
            return {
                "count": len(value),
                "head": [AiAssistantDialog._compact_research_value(item, depth=depth + 1) for item in value[:5]],
                "tail": [AiAssistantDialog._compact_research_value(item, depth=depth + 1) for item in value[-5:]],
            }
        shape = getattr(value, "shape", None)
        size = getattr(value, "size", None)
        if shape is not None:
            summary = {"shape": tuple(int(x) for x in shape)}
            if size is not None:
                try: summary["size"] = int(size)
                except Exception: pass
            for name in ("min", "max", "mean"):
                fn = getattr(value, name, None)
                if callable(fn):
                    try:
                        number = fn()
                        if hasattr(number, "item"): number = number.item()
                        if isinstance(number, (int, float)): summary[name] = float(number)
                    except Exception:
                        pass
            return summary
        return str(value)[:500]

    def _project_payload(self) -> dict[str, Any]:
        project_context = self.context.project
        project = project_context.project
        formal = getattr(project_context, "formal_result", None)
        formal_summary = self._compact_research_value(formal) if formal is not None else {}
        page_context = {}
        context_collection_errors: list[str] = []
        shell = self.parentWidget()
        try:
            provider = getattr(shell, "assistant_context", None)
            if callable(provider):
                value = provider()
                if isinstance(value, dict):
                    page_context = value
        except Exception as exc:
            page_context = {}
            context_collection_errors.append(f"页面上下文采集失败：{type(exc).__name__}: {exc}")
        task_rows = [dict(task) for task in list(getattr(self.context.tasks, "tasks", []) or []) if isinstance(task, dict)]
        task_results_by_id: dict[str, Any] = {}
        task_records_by_id: dict[str, Any] = {}
        status_counts: dict[str, int] = {}
        for index, task in enumerate(task_rows):
            task_id = str(task.get("id", "") or f"task-{index}")
            status = str(task.get("status", "") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            task_records_by_id[task_id] = {
                key: value for key, value in task.items()
                if key not in {"raw", "payload", "request"}
            }
            try:
                result_value = self.context.tasks.result(str(task.get("id", "")), None)
            except Exception as exc:
                result_value = None
                context_collection_errors.append(f"任务 {task_id} 结果读取失败：{type(exc).__name__}: {exc}")
            if result_value is not None:
                task_results_by_id[task_id] = result_value
        registry = self.context.registry
        current_model_id = str(getattr(registry, "current_model_id", "") or "")
        recent_model_id = str(getattr(registry, "recent_model_id", "") or "")
        current_dataset_id = str(getattr(registry, "current_dataset_id", "") or "")
        try:
            current_model = registry.model(current_model_id) if current_model_id else None
        except Exception as exc:
            current_model = None
            context_collection_errors.append(f"当前模型读取失败：{type(exc).__name__}: {exc}")
        try:
            current_dataset = registry.dataset(current_dataset_id) if current_dataset_id else None
        except Exception as exc:
            current_dataset = None
            context_collection_errors.append(f"当前数据集读取失败：{type(exc).__name__}: {exc}")
        registry_snapshot = {
            "current_model_id": current_model_id,
            "recent_model_id": recent_model_id,
            "current_model": current_model,
            "current_dataset_id": current_dataset_id,
            "current_dataset": current_dataset,
            "model_count": len(getattr(registry, "models", []) or []),
            "dataset_count": len(getattr(registry, "datasets", []) or []),
            "current_training_task_id": str(getattr(registry, "current_training_task_id", "") or ""),
        }
        task_snapshot = self._compact_research_value({
            "task_count": len(task_rows),
            "status_counts": status_counts,
            # Dict keyed by task id avoids dropping middle records when there are >30 tasks.
            "tasks_by_id": task_records_by_id,
            "results_by_task_id": task_results_by_id,
            "latest_page_context": page_context,
        })
        finding_rows = [dict(row) for row in list(getattr(project_context, "findings", []) or []) if isinstance(row, dict)]
        findings_by_id = {
            str(row.get("id") or row.get("finding_id") or f"finding-{index}"): row
            for index, row in enumerate(finding_rows)
        }
        assistant_snapshot = {
            "design_revision": int(getattr(project_context, "design_revision", 0)),
            "formal_result": formal_summary,
            "project_metrics": dict(project.metrics),
            "research_context": dict(getattr(project_context, "research_context", {}) or {}),
            # Keep every structured finding addressable even when the history grows beyond 30 rows.
            "findings_by_id": findings_by_id,
            "finding_count": len(finding_rows),
            "finding_status_counts": {
                state: sum(1 for row in finding_rows if str(row.get("status", "当前") or "当前") == state)
                for state in ("当前", "已验证", "需更新")
            },
            "registry": registry_snapshot,
            "page_context": page_context,
            "research_results": task_snapshot,
            "research_journal": self._compact_research_value(list(getattr(project_context, "research_journal", []) or [])),
            "context_collection_errors": list(context_collection_errors),
        }
        return {
            "name": project.name,
            "version": project.version,
            "wavelength_nm": project.wavelength_nm,
            "receiver_mfd_um": project.receiver_mfd_um,
            "metrics": dict(project.metrics),
            "surface_count": len(project.surfaces),
            "design_revision": int(getattr(project_context, "design_revision", 0)),
            "research_context": dict(getattr(project_context, "research_context", {}) or {}),
            "findings": list(getattr(project_context, "findings", []) or []),
            "research_journal": self._compact_research_value(list(getattr(project_context, "research_journal", []) or [])),
            "formal_result": formal_summary,
            "research_results": task_snapshot,
            "registry": self._compact_research_value(registry_snapshot),
            "assistant_research_snapshot": self._compact_research_value(assistant_snapshot),
            "selected_element_id": str(getattr(project_context, "selected_element_id", "") or ""),
            "selected_surface_id": str(getattr(project_context, "selected_surface_id", "") or ""),
            "page_context": page_context,
            "context_collection_errors": list(context_collection_errors),
        }

    def _on_completed(self, key: str, data: Any) -> None:
        if key != self.REQUEST_KEY:
            return
        self.send_button.setEnabled(True)
        self.input.setReadOnly(False)
        self.input.setFocus()
        self.status_label.setText("当前研究上下文")
        if isinstance(data, dict):
            self._show_answer(data)
        else:
            self._append_assistant("<p>未找到可用答案。</p>")

    def _on_failed(self, key: str, message: str) -> None:
        if key != self.REQUEST_KEY:
            return
        self.send_button.setEnabled(True)
        self.input.setReadOnly(False)
        self.input.setFocus()
        self.status_label.setText("本地知识库不可用")
        detail = self._html_text(message)
        self._append_assistant(f"<p>本地知识库查询失败：{detail}</p>")

    def _append_action_buttons(self, actions: list[dict[str, Any]]) -> None:
        actions = [dict(item) for item in actions if isinstance(item, dict)]
        if not actions:
            return
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for action in actions[:1]:
            payload = normalize_action(action)
            payload.setdefault("created_revision", int(getattr(self.context.project, "design_revision", 0) or 0))
            payload = self._normalized_live_action(payload)
            button = QPushButton(str(payload.get("label") or "去处理"))
            button.setObjectName("assistantQuickButton")
            level = str(payload.get("level") or "navigate")
            button.setToolTip("导航并定位" if level == "navigate" else "导航并预填设置，不会自动启动计算")
            button.setEnabled(not bool(payload.get("disabled")))
            button.clicked.connect(lambda checked=False, current=payload, widget=button: self._dispatch_live_action(current, widget))
            layout.addWidget(button)
            self._live_action_buttons.append((button, payload))
        layout.addStretch(1)
        self.messages_layout.insertWidget(max(0, self.messages_layout.count() - 1), row)
        # Action buttons belong to the answer above them.  Keep the first line of
        # that answer visible instead of scrolling down to the buttons.
        QTimer.singleShot(0, lambda: self._scroll_message_to_top(getattr(self, "_last_assistant_row", None)))
        QTimer.singleShot(35, lambda: self._scroll_message_to_top(getattr(self, "_last_assistant_row", None)))

    def _research_state_changed(self) -> None:
        self._refresh_context_hint()
        self._refresh_task_card()
        self._refresh_live_actions()

    def _formal_action_state(self) -> str:
        formal = getattr(self.context.project, "formal_result", None)
        if not isinstance(formal, dict) or not formal:
            return "missing"
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        formal_revision = formal.get("design_revision", formal.get("project_revision", formal.get("revision")))
        if isinstance(formal_revision, (int, float)) and int(formal_revision) != current_revision:
            return "stale"
        status = str(formal.get("status", "") or "").lower()
        if status and status not in {"completed", "success", "done"}:
            return "failed" if status in {"failed", "cancelled", "error"} else "running"
        if formal.get("converged") is False:
            return "failed"
        return "current"

    def _simulation_task_running(self) -> bool:
        for task in list(getattr(self.context.tasks, "tasks", []) or []):
            if not isinstance(task, dict):
                continue
            kind = str(task.get("kind", task.get("type", task.get("name", ""))) or "").lower()
            status = str(task.get("status", "") or "").lower()
            if any(token in kind for token in ("simulation", "仿真", "formal")) and status in {"运行中", "等待中", "running", "queued", "submitting"}:
                return True
        return False

    def _normalized_live_action(self, action: dict[str, Any]) -> dict[str, Any]:
        payload = dict(action)
        target = str(payload.get("target", "") or "")
        if target == "simulation.formal":
            if self._simulation_task_running():
                payload.update({"label": "正式仿真进行中…", "disabled": True})
                return payload
            state = self._formal_action_state()
            if state == "current":
                payload.update({"label": "查看正式结果", "target": "simulation.current", "level": "navigate", "disabled": False})
            elif state == "stale":
                payload.update({"label": "重新正式仿真", "disabled": False})
            elif state == "failed":
                payload.update({"label": "检查后重新仿真", "disabled": False})
        return payload

    def _refresh_live_actions(self) -> None:
        alive: list[tuple[QPushButton, dict[str, Any]]] = []
        for button, original in list(self._live_action_buttons):
            try:
                if not button or not button.parent():
                    continue
                updated = self._normalized_live_action(original)
                original.clear(); original.update(updated)
                button.setText(str(updated.get("label") or "去处理"))
                button.setEnabled(not bool(updated.get("disabled")))
                alive.append((button, original))
            except RuntimeError:
                continue
        self._live_action_buttons = alive

    def _dispatch_live_action(self, action: dict[str, Any], button: QPushButton) -> None:
        # 点击前再次校验，防止 UI 尚未刷新时执行过期建议。
        updated = self._normalized_live_action(action)
        action.clear(); action.update(updated)
        button.setText(str(updated.get("label") or "去处理"))
        button.setEnabled(not bool(updated.get("disabled")))
        if updated.get("disabled"):
            return
        self._begin_guidance(dict(updated))
        self.actionRequested.emit(dict(updated))

    def _show_answer(self, answer: dict[str, Any]) -> None:
        summary = str(answer.get("summary") or "").strip()
        findings = answer.get("findings") or []
        warnings = answer.get("warnings") or []
        parts: list[str] = []
        if summary:
            parts.append(f"<p>{self._html_text(summary)}</p>")
        for finding in findings:
            title = self._html_text(str(finding.get("title") or "说明"))
            explanation = self._html_text(str(finding.get("explanation") or ""))
            parts.append(f"<p><b>{title}</b><br>{explanation}</p>")
        if warnings:
            parts.append("<p><b>注意：</b>" + "；".join(self._html_text(str(item)) for item in warnings) + "</p>")
        confidence = str(answer.get("confidence") or "").strip().lower()
        if confidence in {"high", "medium", "low"}:
            label = {"high": "把握较高", "medium": "把握一般", "low": "把握较低"}[confidence]
            parts.append(f"<p><span style='color:#667085;font-size:10pt'>这条建议：{label}</span></p>")
        if not parts:
            status = str(answer.get("status") or "")
            parts.append("<p>本地知识库暂无对应内容。</p>" if status != "supported" else "<p>未找到可用答案。</p>")
        self._append_assistant("".join(parts))
        self._append_action_buttons(list(answer.get("actions", []) or []))

    @staticmethod
    def _html_text(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:
        if not self.isMaximized():
            self._settings.setValue("assistant/dialog_geometry", self.saveGeometry())
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def shutdown(self) -> None:
        self._bridge.close()
