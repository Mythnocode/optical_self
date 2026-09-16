from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox
from frontend_pyside.shared.components.safe_inputs import SafeDoubleSpinBox

from frontend_pyside.shared.utils.units import parse_quantity


class UnitAwareDoubleSpinBox(SafeDoubleSpinBox):
    """QDoubleSpinBox accepting explicit compatible units in free-text input.

    The widget still stores the value in the unit represented by its suffix.
    Plain numbers retain standard QDoubleSpinBox semantics.
    """

    def setDisplayPrecision(self, display_decimals: int = 2, input_decimals: int = 8) -> None:
        """Use a compact default display while preserving higher input precision."""
        self._display_decimals = max(0, int(display_decimals))
        self._input_decimals = max(self._display_decimals, int(input_decimals))
        self.setDecimals(self._input_decimals)
        self.editingFinished.connect(self._compact_display)
        self.lineEdit().textChanged.connect(self._fit_width)
        self._compact_display()

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt virtual name
        super().focusInEvent(event)
        if not hasattr(self, "_display_decimals"):
            return
        self._set_line_edit_text(self.textFromValue(self.value()))
        self.lineEdit().selectAll()
        self._fit_width()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt virtual name
        super().focusOutEvent(event)
        if not hasattr(self, "_display_decimals"):
            return
        self._compact_display()

    def textFromValue(self, value: float) -> str:  # noqa: N802 - Qt virtual name
        """Render a short idle value without changing the stored value."""
        if not hasattr(self, "_display_decimals"):
            return super().textFromValue(value)
        decimals = int(getattr(self, "_display_decimals", self.decimals()))
        return f"{float(value):.{decimals}f}"

    def _compact_display(self) -> None:
        """Show two decimals when idle, without changing the stored value."""
        if self.lineEdit().hasFocus():
            return
        self._set_line_edit_text(self.textFromValue(self.value()))
        self._fit_width()

    def _set_line_edit_text(self, text: str) -> None:
        """Update the visible text without asking the spin box to reparse it."""
        with QSignalBlocker(self.lineEdit()):
            self.lineEdit().setText(str(text))

    def _fit_width(self) -> None:
        """Resize the editor to the current numeric text, with safe bounds."""
        text = self.lineEdit().text() or "0"
        width = self.fontMetrics().horizontalAdvance(text) + 30
        self.setFixedWidth(max(78, min(260, int(width))))

    def setTargetUnit(self, unit: str) -> None:  # noqa: N802 - Qt style
        self._target_unit_override = str(unit or "").strip()

    def targetUnit(self) -> str:
        override = str(getattr(self, "_target_unit_override", "") or "").strip()
        return override or str(self.suffix() or "").strip()

    def valueFromText(self, text: str) -> float:  # noqa: N802 - Qt virtual name
        raw = str(text or "").strip()
        suffix = self.targetUnit()
        # First try the central quantity parser. It also understands suffixes
        # that contain extra explanatory text such as "% 光斑半径".
        try:
            return float(parse_quantity(raw, suffix))
        except (TypeError, ValueError, OverflowError):
            # Preserve native locale parsing for ordinary numeric entries.
            return float(super().valueFromText(text))

    def validate(self, text: str, pos: int):  # noqa: N802 - Qt virtual name
        state, native_text, native_pos = super().validate(text, pos)
        if state == QValidator.State.Acceptable:
            return state, native_text, native_pos
        raw = str(text or "").strip()
        if not raw or raw in {"+", "-", ".", "+.", "-."}:
            return QValidator.State.Intermediate, text, pos
        try:
            value = float(parse_quantity(raw, self.targetUnit()))
            if self.minimum() <= value <= self.maximum():
                return QValidator.State.Acceptable, text, pos
            return QValidator.State.Intermediate, text, pos
        except (TypeError, ValueError, OverflowError):
            # While typing a unit, don't aggressively reject an otherwise valid
            # numeric prefix; editingFinished/valueFromText will decide finally.
            numeric_prefix = raw.split(maxsplit=1)[0]
            try:
                float(numeric_prefix)
                return QValidator.State.Intermediate, text, pos
            except ValueError:
                return QValidator.State.Invalid, text, pos


__all__ = ["UnitAwareDoubleSpinBox"]
