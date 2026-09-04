from __future__ import annotations

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QSlider,
    QScrollBar,
    QSpinBox,
    QWidget,
)


def _owner_control(widget: QObject | None) -> QWidget | None:
    current = widget
    for _ in range(8):
        if isinstance(current, QScrollBar):
            return None
        if isinstance(current, (QAbstractSpinBox, QComboBox, QAbstractSlider)):
            return current
        parent = current.parent() if isinstance(current, QObject) else None
        if not isinstance(parent, QObject):
            break
        current = parent
    return None


def _scroll_area_for(widget: QObject | None) -> QAbstractScrollArea | None:
    current = widget
    for _ in range(16):
        parent = current.parent() if isinstance(current, QObject) else None
        if isinstance(parent, QAbstractScrollArea):
            return parent
        if not isinstance(parent, QObject):
            break
        current = parent
    return None


def forward_wheel_to_page(widget: QObject | None, event) -> bool:
    """Forward wheel navigation to the containing page without mutating values."""
    area = _scroll_area_for(widget)
    if area is None:
        event.accept()
        return True
    horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
    bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
    pixel = event.pixelDelta().x() if horizontal else event.pixelDelta().y()
    angle = event.angleDelta().x() if horizontal else event.angleDelta().y()
    if pixel:
        delta = int(pixel)
    elif angle:
        delta = int(round((float(angle) / 120.0) * max(24, bar.singleStep() * 3)))
    else:
        event.accept()
        return True
    bar.setValue(max(bar.minimum(), min(bar.maximum(), bar.value() - delta)))
    event.accept()
    return True


class WheelSafetyFilter(QObject):
    """Application-wide protection against accidental wheel value changes."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        control = _owner_control(watched)
        if control is None:
            return False
        if isinstance(control, QComboBox):
            try:
                if control.view() is not None and control.view().isVisible():
                    return False
            except RuntimeError:
                pass
        return forward_wheel_to_page(control, event)


class _SafeWheelMixin:
    def wheelEvent(self, event):  # noqa: N802
        if isinstance(self, QComboBox):
            try:
                if self.view() is not None and self.view().isVisible():
                    return super().wheelEvent(event)
            except RuntimeError:
                pass
        forward_wheel_to_page(self, event)


class SafeComboBox(_SafeWheelMixin, QComboBox):
    pass


class SafeSpinBox(_SafeWheelMixin, QSpinBox):
    pass


class SafeDoubleSpinBox(_SafeWheelMixin, QDoubleSpinBox):
    pass


class SafeSlider(_SafeWheelMixin, QSlider):
    pass


def install_wheel_safety(app: QApplication) -> WheelSafetyFilter:
    existing = app.property("wheelSafetyFilter")
    if isinstance(existing, WheelSafetyFilter):
        return existing
    guard = WheelSafetyFilter(app)
    app.installEventFilter(guard)
    app.setProperty("wheelSafetyFilter", guard)
    return guard


__all__ = [
    "SafeComboBox", "SafeDoubleSpinBox", "SafeSlider", "SafeSpinBox",
    "WheelSafetyFilter", "forward_wheel_to_page", "install_wheel_safety",
]
