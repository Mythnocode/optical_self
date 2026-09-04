from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .badges import Badge
from .buttons import SecondaryButton
from frontend_pyside.shared import layout_tokens as layout

class Card(QFrame):
    def __init__(self, title="", parent=None, *, compact=False):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        padding = layout.COMPACT_CARD_PADDING if compact else layout.CARD_PADDING
        margins = (padding, padding, padding, padding)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(layout.CONTENT_GAP)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("cardTitle")
            self.body.addWidget(self.title_label)

class FeatureCard(Card):
    activated = Signal()

    def __init__(
        self,
        title,
        description,
        button_text="进入",
        parent=None,
        *,
        details: Iterable[str] | None = None,
        status: str = "",
    ):
        super().__init__(title, parent, compact=True)
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setObjectName("mutedText")
        self.body.addWidget(description_label)
        if details:
            detail_label = QLabel("　·　".join(str(x) for x in details))
            detail_label.setWordWrap(True)
            detail_label.setObjectName("helperText")
            self.body.addWidget(detail_label)
        self.body.addStretch()
        footer = QHBoxLayout()
        if status:
            badge = Badge(status, "success" if "可用" in status or "完成" in status else "info")
            footer.addWidget(badge)
        footer.addStretch()
        button = SecondaryButton(button_text)
        button.clicked.connect(self.activated)
        footer.addWidget(button)
        self.body.addLayout(footer)

class CollapsiblePanel(Card):
    """A collapsible card that grows with its contents instead of clipping them.

    The application deliberately uses one outer page scroll for dense engineering
    workflows.  Expanded panels must therefore contribute their real content height
    to that page.  Qt otherwise tends to compress nested forms inside a resizable
    QScrollArea, which can make fixed-height combo/spin controls overlap even though
    the outer page has plenty of scrollable room.
    """

    def __init__(self, title, parent=None, expanded=True):
        super().__init__("", parent, compact=True)
        # Preferred (rather than Maximum) lets the panel report the actual height
        # of an expanded form while still allowing a collapsed panel to be compact.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toggle = QToolButton(text=title, checkable=True, checked=expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.body.addWidget(self.toggle)
        self.content = QWidget()
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, layout.CONTROL_GAP, 0, 0)
        self.content_layout.setSpacing(layout.CONTROL_GAP)
        self.content.setVisible(expanded)
        self.body.addWidget(self.content)
        self.toggle.toggled.connect(self._toggle)
        QTimer.singleShot(0, self._sync_expanded_geometry)

    def _toggle(self, on):
        self.content.setVisible(on)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow
        )
        self._sync_expanded_geometry()
        # Nested panels/lazy pages settle one event-loop turn later.  Recompute
        # once more so the outer page scroll grows instead of squeezing children.
        QTimer.singleShot(0, self._sync_expanded_geometry)

    def _sync_expanded_geometry(self) -> None:
        try:
            expanded = bool(self.toggle.isChecked() and self.content.isVisible())
            self.content_layout.invalidate()
            self.content_layout.activate()
            if expanded:
                content_h = max(0, self.content_layout.sizeHint().height())
                self.content.setMinimumHeight(content_h)
            else:
                self.content.setMinimumHeight(0)
            self.content.updateGeometry()

            self.body.invalidate()
            self.body.activate()
            # Do not hard-fix the height.  A minimum protects controls from
            # compression; the enclosing page remains the sole scroll owner.
            panel_h = max(self.toggle.sizeHint().height(), self.body.sizeHint().height())
            self.setMinimumHeight(panel_h)
            self.updateGeometry()

            # Propagate the new semantic height through nested cards/stacks.
            parent = self.parentWidget()
            while parent is not None:
                if isinstance(parent, CollapsiblePanel) and parent is not self:
                    parent.content_layout.invalidate()
                    parent.content_layout.activate()
                    if parent.toggle.isChecked() and parent.content.isVisible():
                        parent.content.setMinimumHeight(parent.content_layout.sizeHint().height())
                    parent.body.invalidate()
                    parent.body.activate()
                    parent.setMinimumHeight(parent.body.sizeHint().height())
                parent.updateGeometry()
                parent = parent.parentWidget()
        except RuntimeError:
            # A deferred layout pass may run while a temporary task window closes.
            pass

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)
        if self.toggle.isChecked() == bool(expanded):
            self._sync_expanded_geometry()
