
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


_LATIN_CANDIDATES = (
    "Times New Roman",
    "Liberation Serif",
    "Noto Serif",
    "DejaVu Serif",
)
_CJK_CANDIDATES = (
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "PingFang SC",
    "SimSun",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK JP",
    "Noto Sans",
    "Droid Sans Fallback",
    "DejaVu Sans",
)


def register_embedded_fonts() -> tuple[int, ...]:
    """Register the bundled fallback font before choosing the application font."""
    font_path = Path(__file__).resolve().parents[1] / "resources" / "fonts" / "DroidSansFallback.ttf"
    if not font_path.exists():
        return ()
    try:
        font_id = int(QFontDatabase.addApplicationFont(str(font_path)))
    except Exception:
        return ()
    available_families.cache_clear()
    return (font_id,) if font_id >= 0 else ()


@lru_cache(maxsize=1)
def available_families() -> frozenset[str]:
    try:
        return frozenset(str(name) for name in QFontDatabase.families())
    except Exception:
        return frozenset()


def _first_available(candidates: tuple[str, ...], fallback: str) -> str:
    families = available_families()
    for family in candidates:
        if family in families:
            return family
    return fallback


def preferred_latin_family() -> str:
    return _first_available(_LATIN_CANDIDATES, "DejaVu Serif")


def preferred_cjk_family() -> str:
    return _first_available(_CJK_CANDIDATES, "DejaVu Sans")


def qt_font_families() -> list[str]:
    ordered = [preferred_latin_family(), preferred_cjk_family(), "DejaVu Sans"]
    return list(dict.fromkeys(ordered))


def configure_qt_font(app: QApplication, *, point_size: float | None = None) -> QFont:
    register_embedded_fonts()
    font = QFont(app.font())
    families = qt_font_families()
    if hasattr(font, "setFamilies"):
        font.setFamilies(families)
    else:  
        font.setFamily(families[0])
    if point_size is not None:
        font.setPointSizeF(float(point_size))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    return font


def matplotlib_font_config() -> dict[str, object]:


    try:
        from matplotlib import font_manager

        known = {str(item.name) for item in font_manager.fontManager.ttflist}
    except Exception:
        known = set()

    def choose(candidates: tuple[str, ...], fallback: str) -> str:
        for family in candidates:
            if family in known:
                return family
        return fallback

    latin = choose(_LATIN_CANDIDATES, "DejaVu Serif")
    cjk = choose(
        (
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "Noto Sans CJK JP",
            "Noto Serif CJK JP",
            "WenQuanYi Micro Hei",
        ),
        "DejaVu Sans",
    )
    families = list(dict.fromkeys([latin, cjk, "DejaVu Sans"]))
    return {
        "font.family": families,
        "font.serif": families,
        "font.sans-serif": [cjk, "Noto Sans", "DejaVu Sans"],
        "mathtext.fontset": "dejavuserif",
        "axes.unicode_minus": False,
    }


__all__ = [
    "available_families",
    "configure_qt_font",
    "matplotlib_font_config",
    "preferred_cjk_family",
    "preferred_latin_family",
    "register_embedded_fonts",
    "qt_font_families",
]
