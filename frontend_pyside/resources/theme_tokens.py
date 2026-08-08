
from __future__ import annotations

from math import pow

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
PAGE_BACKGROUND = "#EEF1F5"
SURFACE = "#FFFFFF"
SURFACE_SECONDARY = "#E6EAF0"
SURFACE_MUTED = "#F7F8FA"
SURFACE_INVERSE = "#17202D"

TEXT_PRIMARY = "#101828"
TEXT_SECONDARY = "#344054"
TEXT_MUTED = "#667085"
TEXT_DISABLED = "#8A94A3"
TEXT_INVERSE = "#FFFFFF"

BORDER = "#98A2B3"
BORDER_STRONG = "#667085"
DIVIDER = "#C7CDD6"
FOCUS_RING = "#155EEF"

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
NAV_BACKGROUND = "#17202D"
NAV_BACKGROUND_HOVER = "#263548"
NAV_BACKGROUND_ACTIVE = "#155EEF"
NAV_BORDER = "#0F1722"
NAV_TEXT = "#E4E7EC"
NAV_TEXT_MUTED = "#98A2B3"
NAV_ICON = "#F2F4F7"

PRIMARY = "#155EEF"
PRIMARY_HOVER = "#004EEB"
PRIMARY_PRESSED = "#0040C1"
PRIMARY_DARK = "#0A327A"
PRIMARY_TINT = "#D6E4FF"

SUCCESS = "#087A41"
SUCCESS_BACKGROUND = "#DDF5E8"
WARNING = "#A65300"
WARNING_BACKGROUND = "#FFF0D5"
ERROR = "#C5221F"
ERROR_BACKGROUND = "#FDE3E2"
INFO = PRIMARY
INFO_BACKGROUND = PRIMARY_TINT

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
CHART_BLUE = PRIMARY
CHART_ORANGE = "#D97706"
CHART_GREEN = SUCCESS
CHART_RED = ERROR
CHART_PURPLE = "#6D28D9"
CHART_CYAN = "#007C91"
CHART_GRAY = "#475467"
CHART_GRID = "#CBD5E1"
CHART_AXIS = TEXT_SECONDARY
CHART_BACKGROUND = SURFACE
CHART_REFERENCE = "#475467"
CHART_TARGET = SUCCESS
CHART_CURRENT = ERROR
CHART_SERIES = (
    CHART_BLUE,
    CHART_ORANGE,
    CHART_GREEN,
    CHART_RED,
    CHART_PURPLE,
    CHART_CYAN,
)

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
SCENE_BACKGROUND = "#F8FAFC"
OPTICAL_AXIS = "#475467"
SURFACE_FILL = "#36BFFA"
SURFACE_FILL_SECONDARY = "#0BA5EC"
SURFACE_EDGE = "#075985"
SURFACE_GRID = "#0284C7"
SURFACE_SELECTED_FILL = "#F79009"
SURFACE_SELECTED_EDGE = "#B54708"
SURFACE_DISABLED = TEXT_DISABLED

RAY_CHIEF = "#B42318"
RAY_MARGINAL = "#D92D20"
RAY_REGULAR = "#F04438"
RAY_FAILED = "#7A271A"
RAY_SECONDARY = "#007C91"

APERTURE_COLOR = TEXT_PRIMARY
IMAGE_PLANE_COLOR = SUCCESS
DETECTOR_FILL = "#12B76A"
DETECTOR_EDGE = "#05603A"
FIBER_CLADDING = "#1D4ED8"
FIBER_CORE = "#06B6D4"
SECTION_PLANE = "#0284C7"
SELECTION_HALO = "#F79009"

BEAM_ENVELOPE_FILL = "#7DD3FC"
BEAM_ENVELOPE_EDGE = "#0284C7"
BEAM_WAIST = "#D97706"
LENS_BODY_FILL = "#BAE6FD"
LENS_BODY_EDGE = "#0369A1"
FOCUS_PLANE_FILL = "#FDE68A"
FOCUS_PLANE_EDGE = "#B45309"



COMPONENT_LASER = "#C5221F"
COMPONENT_LENS = "#0284C7"
COMPONENT_MIRROR = "#475467"
COMPONENT_DETECTOR = SUCCESS
COMPONENT_FIBER = "#D97706"
COMPONENT_INACTIVE = "#98A2B3"
COMPONENT_SELECTED = PRIMARY


STATUS_VALID = SUCCESS
STATUS_STALE = WARNING
STATUS_ERROR = ERROR
STATUS_INFO = INFO


def _linear_channel(value: int) -> float:
    channel = value / 255.0
    return channel / 12.92 if channel <= 0.04045 else pow((channel + 0.055) / 1.055, 2.4)


def relative_luminance(color: str) -> float:

    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB, got {color!r}")
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * _linear_channel(red) + 0.7152 * _linear_channel(green) + 0.0722 * _linear_channel(blue)


def contrast_ratio(foreground: str, background: str) -> float:

    lighter, darker = sorted(
        (relative_luminance(foreground), relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


__all__ = [name for name in globals() if name.isupper()] + [
    "contrast_ratio",
    "relative_luminance",
]
