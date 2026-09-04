from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from frontend_pyside.shared import layout_tokens as layout


class FormGrid(QWidget):
    """Three-column form: label | field | unit/help.

    It keeps engineering forms aligned across pages and deliberately avoids an
    inner scroll area.  Long help text may wrap in the third column while the
    editable field keeps a stable width.
    """

    def __init__(self, parent=None, *, label_width: int | None = None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(layout.CONTROL_GAP)
        self.grid.setVerticalSpacing(layout.CONTROL_GAP)
        self.grid.setColumnStretch(1, 0)
        self.grid.setColumnStretch(2, 1)
        self._row = 0
        self._label_width = int(label_width or layout.FORM_LABEL_WIDTH)

    def add_row(self, label: str, field: QWidget, unit_or_help: str | QWidget = "") -> QWidget:
        key = QLabel(str(label))
        key.setObjectName("propertyFieldLabel")
        key.setMinimumWidth(self._label_width)
        key.setMaximumWidth(self._label_width)
        self.grid.addWidget(key, self._row, 0)

        field.setMinimumWidth(layout.FORM_FIELD_MIN_WIDTH)
        if field.maximumWidth() >= 16_000_000:
            field.setMaximumWidth(layout.FORM_FIELD_MAX_WIDTH)
        field.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.grid.addWidget(field, self._row, 1)

        if isinstance(unit_or_help, QWidget):
            helper = unit_or_help
        else:
            helper = QLabel(str(unit_or_help or ""))
            helper.setObjectName("helperText")
            helper.setWordWrap(True)
        self.grid.addWidget(helper, self._row, 2)
        self._row += 1
        return key

    def add_full_width(self, widget: QWidget) -> None:
        self.grid.addWidget(widget, self._row, 0, 1, 3)
        self._row += 1
