from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton
from frontend_pyside.shared import layout_tokens as layout


class PrimaryButton(QPushButton):
    """Primary action with consistent submitted/running/success/error feedback.

    Existing pages can keep using ``PrimaryButton`` normally.  Long-running pages
    may call ``set_task_state`` without introducing their own spinner/timer.
    """

    _SPINNER = ("◴", "◷", "◶", "◵")

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("kind", "primary")
        self.setProperty("taskState", "idle")
        self.setMinimumHeight(layout.PRIMARY_CONTROL_HEIGHT)
        self._idle_text = str(text)
        self._state_text = ""
        self._spinner_index = 0
        self._task_base_min_width: int | None = None
        self._task_base_icon: QIcon | None = None
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(150)
        self._spinner_timer.timeout.connect(self._advance_spinner)

    def setText(self, text):  # noqa: N802 - Qt API compatibility
        super().setText(text)
        if not getattr(self, "_spinner_timer", None) or not self._spinner_timer.isActive():
            self._idle_text = str(text)

    def _fit_task_text(self, text: str, *, running: bool = False) -> None:
        if self._task_base_min_width is None:
            self._task_base_min_width = int(self.minimumWidth())
        # Reserve room for the animated glyph and horizontal button padding.
        extra = 34 if running else 26
        needed = self.fontMetrics().horizontalAdvance(str(text or "")) + extra
        self.setMinimumWidth(max(int(self._task_base_min_width or 0), needed))

    def set_task_state(self, state: str = "idle", text: str | None = None, *, disable_running: bool = True) -> None:
        state = str(state or "idle").lower()
        if self._task_base_icon is None:
            self._task_base_icon = QIcon(self.icon())
        self.setProperty("taskState", state)
        if text is not None:
            self._state_text = str(text)
        elif state == "idle":
            self._state_text = self._idle_text
        if state in {"submitted", "running"}:
            if not self._state_text:
                self._state_text = "正在处理"
            self._spinner_index = 0
            # Do not combine a permanent action icon (for example the check on
            # “开始计算”) with the animated spinner; the two glyphs look like
            # overlapping states.  Running/submitted owns the button face.
            self.setIcon(QIcon())
            self._fit_task_text(self._state_text, running=True)
            self._spinner_timer.start()
            if disable_running:
                self.setEnabled(False)
            self._advance_spinner()
        else:
            self._spinner_timer.stop()
            self.setEnabled(True)
            label = self._state_text or self._idle_text
            if state == "idle":
                if self._task_base_min_width is not None:
                    self.setMinimumWidth(int(self._task_base_min_width))
                if self._task_base_icon is not None:
                    self.setIcon(QIcon(self._task_base_icon))
            else:
                self.setIcon(QIcon())
                self._fit_task_text(label, running=False)
            if state == "success" and not label.startswith("✓"):
                label = f"✓ {label}"
            elif state == "error" and not label.startswith("!"):
                label = f"! {label}"
            super().setText(label)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def reset_task_state(self, text: str | None = None) -> None:
        if text is not None:
            self._idle_text = str(text)
        self._state_text = self._idle_text
        self.set_task_state("idle", self._idle_text)

    def _advance_spinner(self) -> None:
        if not self._spinner_timer.isActive():
            return
        glyph = self._SPINNER[self._spinner_index % len(self._SPINNER)]
        self._spinner_index += 1
        super().setText(f"{glyph} {self._state_text or '正在处理'}")


class SecondaryButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("kind", "secondary")
        self.setMinimumHeight(layout.CONTROL_HEIGHT)
