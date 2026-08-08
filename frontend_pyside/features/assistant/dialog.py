from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QMouseEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frontend_pyside.features.assistant.local_bridge import LocalKnowledgeBridge


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
QLabel#assistantStatus { color: #1768e5; font-size: 11px; font-weight: 600; }
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
    font-size: 13px;
}
QTextBrowser#assistantAnswerText,
QTextBrowser#assistantAnswerText::viewport {
    color: #202938;
    background: transparent;
    border: 0;
    font-size: 13px;
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
    font-size: 14px;
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
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#assistantSendButton:hover { background: #0f57c8; }
QPushButton#assistantSendButton:disabled { background: #9fb7d9; }
QLabel#assistantHint { color: #7a8596; font-size: 10px; }
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
        self.setMaximumWidth(390)
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
    REQUEST_KEY = "assistant.local_query"

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._page_id = "home"
        self._drag_offset: QPoint | None = None
        self._user_moved = False
        self._bridge = LocalKnowledgeBridge(parent=self)

        self.setObjectName("aiAssistantDialog")
        self.setWindowTitle("AI助手")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_ASSISTANT_QSS)
        self.setMinimumSize(380, 460)
        self.resize(440, 610)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        surface = QFrame()
        surface.setObjectName("assistantWindowSurface")
        outer.addWidget(surface)
        root = QVBoxLayout(surface)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_messages(), 1)
        root.addWidget(self._build_composer())

        self._bridge.completed.connect(self._on_completed)
        self._bridge.failed.connect(self._on_failed)
        self._append_welcome()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("assistantHeader")
        header.installEventFilter(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(6)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("AI助手")
        title.setObjectName("assistantTitle")
        self.status_label = QLabel("本地知识库")
        self.status_label.setObjectName("assistantStatus")
        title_box.addWidget(title)
        title_box.addWidget(self.status_label)
        layout.addLayout(title_box)
        layout.addStretch(1)

        new_button = QToolButton()
        new_button.setObjectName("assistantHeaderButton")
        new_button.setText("＋")
        new_button.setToolTip("新建对话")
        new_button.clicked.connect(self._new_chat)
        layout.addWidget(new_button)

        hide_button = QToolButton()
        hide_button.setObjectName("assistantHeaderButton")
        hide_button.setText("—")
        hide_button.setToolTip("收起")
        hide_button.clicked.connect(self.hide)
        layout.addWidget(hide_button)

        close_button = QToolButton()
        close_button.setObjectName("assistantHeaderButton")
        close_button.setText("×")
        close_button.setToolTip("关闭")
        close_button.clicked.connect(self.hide)
        layout.addWidget(close_button)
        return header

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
        layout = QVBoxLayout(host)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(5)
        composer = QFrame()
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

    def show_anchored(self) -> None:
        if not self._user_moved:
            self.anchor_to_parent()
        else:
            self.clamp_to_parent()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

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

    def _append_welcome(self) -> None:
        self._append_assistant(
            "<p>可询问软件操作、参数含义、结果判断和光学设计问题。回答仅使用本地知识库。</p>"
        )

    def _add_bubble(self, text: str, role: str) -> None:
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
        self.messages_scroll.verticalScrollBar().rangeChanged.connect(
            lambda _minimum, maximum: self.messages_scroll.verticalScrollBar().setValue(maximum)
        )

    def _append_assistant(self, html: str) -> None:
        self._add_bubble(html, "assistant")

    def _new_chat(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if widget := item.widget():
                widget.deleteLater()
        self._append_welcome()
        self.input.clear()
        self.input.setFocus()

    def _send_question(self) -> None:
        question = self.input.toPlainText().strip()
        if not question:
            self.input.setFocus()
            return
        self.input.clear()
        self._add_bubble(question, "user")
        self.status_label.setText("正在检索本地知识库…")
        self.send_button.setEnabled(False)
        self.input.setReadOnly(True)
        self._bridge.ask(
            self.REQUEST_KEY,
            question=question,
            page_id=self._page_id,
            project=self._project_payload(),
            audience="beginner",
        )

    def _project_payload(self) -> dict[str, Any]:
        project = self.context.project.project
        return {
            "name": project.name,
            "version": project.version,
            "wavelength_nm": project.wavelength_nm,
            "receiver_mfd_um": project.receiver_mfd_um,
            "metrics": dict(project.metrics),
            "surface_count": len(project.surfaces),
        }

    def _on_completed(self, key: str, data: Any) -> None:
        if key != self.REQUEST_KEY:
            return
        self.send_button.setEnabled(True)
        self.input.setReadOnly(False)
        self.input.setFocus()
        self.status_label.setText("本地知识库")
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
        if not parts:
            status = str(answer.get("status") or "")
            parts.append("<p>本地知识库暂无对应内容。</p>" if status != "supported" else "<p>未找到可用答案。</p>")
        self._append_assistant("".join(parts))

    @staticmethod
    def _html_text(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def shutdown(self) -> None:
        self._bridge.close()
