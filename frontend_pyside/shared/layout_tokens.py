"""Shared geometry tokens for the desktop UI.

The UI uses a compact 4/6/12/16 px rhythm.  Pages may use different skeletons,
but ordinary controls should draw from this module rather than inventing local
margins.  Small screens scroll; they do not shrink fonts or overlap widgets.
"""

PAGE_MARGIN = 16
SECTION_GAP = 16
CARD_GAP = 12
CONTENT_GAP = 8
CONTROL_GAP = 6
TIGHT_GAP = 4
CARD_PADDING = 12
COMPACT_CARD_PADDING = 10
CONTROL_HEIGHT = 34
PRIMARY_CONTROL_HEIGHT = 36
FORM_LABEL_WIDTH = 132
FORM_FIELD_MIN_WIDTH = 150
FORM_FIELD_MAX_WIDTH = 230
FORM_UNIT_WIDTH = 64
MAX_CONTENT_WIDTH = 1480
PLOT_MIN_HEIGHT = 320
PLOT_PREFERRED_HEIGHT = 420
SIM_PARAMETER_MIN_WIDTH = 270
SIM_PARAMETER_PREFERRED_WIDTH = 292
SIM_PARAMETER_MAX_WIDTH = 310
TASK_SETTINGS_MIN_WIDTH = 340
TASK_SETTINGS_PREFERRED_WIDTH = 364
TASK_SETTINGS_MAX_WIDTH = 396

__all__ = [name for name in globals() if name.isupper()]
