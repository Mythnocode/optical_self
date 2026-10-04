
from __future__ import annotations

from functools import lru_cache
from html import escape
from shared_presentation.formula_images import _render_formula_png, render_formula_png

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget






@lru_cache(maxsize=128)
def _render_formula_pixmap(latex: str, font_size: int, color: str) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(_render_formula_png(latex, font_size, color), "PNG")
    return pixmap


class FormulaImageLabel(QWidget):
    """Paint a typeset equation without changing the layout during resize."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._fallback_text = ""
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def set_formula(self, latex: str, *, font_size: int = 19, color: str = "#173a55") -> None:
        try:
            self._source_pixmap = _render_formula_pixmap(str(latex), int(font_size), str(color))
            self._fallback_text = "" if not self._source_pixmap.isNull() else str(latex)
        except Exception:
            # A rendering failure inside a Qt signal handler must not close
            # the desktop application.
            self._source_pixmap = QPixmap()
            self._fallback_text = str(latex)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        if self._source_pixmap.isNull():
            return QSize(300, 34)
        width = min(self._source_pixmap.width(), 900)
        return QSize(width, self.heightForWidth(width))

    def heightForWidth(self, width: int) -> int:
        if self._source_pixmap.isNull():
            return 34
        displayed_width = min(max(1, width), self._source_pixmap.width())
        height = round(self._source_pixmap.height() * displayed_width / self._source_pixmap.width())
        return max(34, height + 6)

    def paintEvent(self, event) -> None:
        if self._source_pixmap.isNull():
            if self._fallback_text:
                painter = QPainter(self)
                painter.drawText(self.rect(), self._fallback_text)
            return
        width = min(self.width(), self._source_pixmap.width())
        height = round(self._source_pixmap.height() * width / self._source_pixmap.width())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(
            QRect(0, max(0, (self.height() - height) // 2), width, height),
            self._source_pixmap,
        )



_FORMULA_PARTS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("总耦合效率", "复场重叠"): (
        "η<sub>overlap</sub>",
        "|∬ E<sub>s</sub>E<sub>f</sub><sup>*</sup> dA|<sup>2</sup>",
        "(∬ |E<sub>s</sub>|<sup>2</sup> dA)(∬ |E<sub>f</sub>|<sup>2</sup> dA)",
    ),
    ("模式失配", "尺寸失配"): (
        "η<sub>size</sub>",
        "4ρ<sup>2</sup>",
        "(1 + ρ<sup>2</sup>)<sup>2</sup>",
    ),
    ("模式失配", "曲率失配"): (
        "η / η<sub>0</sub>",
        "1",
        "1 + u<sub>R</sub><sup>2</sup>",
    ),
}

_FORMULA_LINES: dict[tuple[str, str], str] = {
    ("总耦合效率", "系统传输"): "η<sub>total</sub> = η<sub>transmission</sub> · η<sub>overlap</sub> · η<sub>facet</sub> · η<sub>propagation</sub>",
    ("总耦合效率", "端面效率"): "η<sub>facet</sub> = 1 − R<sub>facet</sub>",
    ("对准误差", "横向偏移"): "u<sub>r</sub> = √(Δx<sup>2</sup> + Δy<sup>2</sup>) / w<sub>f</sub>　　η/η<sub>0</sub> = exp(−u<sub>r</sub><sup>2</sup>)",
    ("对准误差", "角度偏移"): "u<sub>θ</sub> = πw<sub>f</sub>√(θ<sub>x</sub><sup>2</sup> + θ<sub>y</sub><sup>2</sup>) / λ　　η/η<sub>0</sub> = exp(−u<sub>θ</sub><sup>2</sup>)",
    ("对准误差", "轴向离焦"): "u<sub>z</sub> = Δz / z<sub>R</sub>　　z<sub>R</sub> = πw<sub>f</sub><sup>2</sup> / λ",
    ("模式失配", "尺寸失配"): "ρ = w<sub>b</sub> / w<sub>f</sub>",
    ("模式失配", "曲率失配"): "u<sub>R</sub> = kw<sub>f</sub><sup>2</sup>(1/R<sub>b</sub> − 1/R<sub>f</sub>) / 4",
    ("波前质量", "OPD"): "OPD(x,y) = W(x,y) − W̄",
    ("波前质量", "Zernike"): "W(ρ,φ) = Σ a<sub>j</sub>Z<sub>j</sub>(ρ,φ)",
    ("波前质量", "Strehl"): "S ≈ exp[−(2πσ<sub>W</sub>/λ)<sup>2</sup>]",
    ("成像质量", "PSF"): "PSF = |ℱ{P · exp(i2πW/λ)}|<sup>2</sup>",
    ("成像质量", "MTF"): "MTF = |ℱ{PSF}|",
    ("成像质量", "Airy 半径"): "r<sub>Airy</sub> = 1.22λf / D",
    ("结构参数", "曲率半径"): "Φ<sub>s</sub> ≈ (n<sub>2</sub> − n<sub>1</sub>) / R",
    ("结构参数", "厚度与间隔"): "M<sub>t</sub> = [ 1　t/n ; 0　1 ]",
    ("结构参数", "圆锥系数"): "z(r) = cr<sup>2</sup> / [1 + √(1 − (1 + k)c<sup>2</sup>r<sup>2</sup>)]",
}


def formula_compact_text(category: str, item: str) -> str:

    key = (str(category), str(item))
    aliases = {
        ("总耦合效率", "复场重叠"): "ηoverlap：输入复场与光纤模式的归一化重叠",
        ("模式失配", "尺寸失配"): "ηsize：由光斑半径比 ρ 决定",
        ("模式失配", "曲率失配"): "η/η0 = 1/(1+uR²)",
    }
    return aliases.get(key, _strip_html(_FORMULA_LINES.get(key, f"{category} / {item}")))


def formula_html(category: str, item: str, latex_fallback: str = "") -> str:
    key = (str(category), str(item))
    fraction = _FORMULA_PARTS.get(key)
    line = _FORMULA_LINES.get(key, "")
    pieces = [
        "<div style='font-size:20px; font-weight:600; color:#173a55; padding:8px;'>"
    ]
    if fraction:
        lhs, numerator, denominator = fraction
        pieces.append(
            "<table cellspacing='0' cellpadding='3'><tr>"
            f"<td rowspan='2' style='font-size:21px; padding-right:8px;'>{lhs} =</td>"
            f"<td align='center' style='font-size:19px;'>{numerator}</td></tr>"
            f"<tr><td align='center' style='font-size:19px; border-top:1px solid #173a55;'>{denominator}</td></tr></table>"
        )
    if line:
        pieces.append(f"<div style='margin-top:8px; font-size:18px;'>{line}</div>")
    if not fraction and not line:
        pieces.append(f"<div>{escape(latex_fallback or '当前公式暂无可视化表达')}</div>")
    pieces.append("</div>")
    return "".join(pieces)


def _strip_html(text: str) -> str:
    return (
        str(text)
        .replace("<sub>", "_")
        .replace("</sub>", "")
        .replace("<sup>2</sup>", "²")
        .replace("<sup>*</sup>", "*")
        .replace("<sup>", "^")
        .replace("</sup>", "")
    )


__all__ = ["FormulaImageLabel", "formula_compact_text", "formula_html", "render_formula_png"]
