"""Original mathtext equation rendering without a Qt import."""
from __future__ import annotations
from functools import lru_cache

@lru_cache(maxsize=128)
def _render_formula_png(latex: str, font_size: int, color: str) -> bytes:
    """Render TeX math with Matplotlib's mathtext engine at high resolution."""
    from io import BytesIO

    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from shared_presentation.plotting.basic_charts import font_config

    width = max(3.0, min(16.0, len(latex) * 0.17))
    figure = Figure(figsize=(width, 0.68), dpi=144)
    FigureCanvasAgg(figure)
    # Qt configures these fonts globally when it creates a plot canvas. Set them
    # explicitly so a headless request has the same equation bounds and glyphs.
    with rc_context({**font_config(), "mathtext.fontset": "stix", "mathtext.default": "it"}):
        figure.text(0.015, 0.5, f"${latex}$", fontsize=font_size, color=color, va="center")
        output = BytesIO()
        try:
            figure.savefig(
                output,
                format="png",
                transparent=True,
                bbox_inches="tight",
                pad_inches=0.08,
            )
        except (ValueError, RuntimeError):
            # Keep a readable fallback if an unusual symbol is outside the
            # supported TeX subset. The formulas used in this view use standard
            # mathtext commands, so this path should be rare.
            output = BytesIO()
            figure.clear()
            figure.text(0.015, 0.5, latex, fontsize=font_size, color=color, va="center")
            figure.savefig(
                output,
                format="png",
                transparent=True,
                bbox_inches="tight",
                pad_inches=0.08,
            )
    return output.getvalue()


def render_formula_png(latex: str, *, font_size: int = 19, color: str = "#173a55") -> bytes:
    """Return a reusable PNG for the same typeset formula shown in the UI."""
    return _render_formula_png(str(latex), int(font_size), str(color))

