from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from frontend_pyside.resources import theme_tokens as theme


FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "PingFang SC",
    "Arial",
)


def _available_font_family() -> str:
    try:
        available = set(QFontDatabase.families())
    except Exception:
        available = set()
    for family in FONT_CANDIDATES:
        if family in available:
            return family
    return QApplication.font().family()


@lru_cache(maxsize=1)
def _application_qss() -> str:
    qss = Path(__file__).resolve().parents[1] / "resources" / "qss" / "light.qss"
    return qss.read_text(encoding="utf-8") if qss.exists() else ""


def _application_palette() -> QPalette:

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.PAGE_BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.SURFACE_MUTED))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(theme.TEXT_INVERSE))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.TEXT_INVERSE))
    palette.setColor(QPalette.ColorRole.Link, QColor(theme.PRIMARY))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(theme.TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(theme.SURFACE_SECONDARY))
    return palette


def apply_application_theme(app: QApplication) -> None:

    app.setStyle("Fusion")
    app.setPalette(_application_palette())
    font = QFont(_available_font_family())
    try:
        point_size = float(os.environ.get("OPTICAL_UI_FONT_PT", "12.5"))
    except ValueError:
        point_size = 12.5
    font.setPointSizeF(max(10.5, min(point_size, 15.0)))
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)

    qss = _application_qss()
    if qss and app.styleSheet() != qss:
        app.setStyleSheet(qss)
