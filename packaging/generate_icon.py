from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
LOGO_SVG = REPO_ROOT / "frontend_pyside" / "resources" / "icons" / "logo.svg"
OUTPUT_ICO = PACKAGING_DIR / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
CANVAS = 512
BACKGROUND = "#155EEF"
BORDER = "#0A327A"


def render_logo(canvas_size: int = 256) -> Image.Image:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(LOGO_SVG))
    image = QImage(canvas_size, canvas_size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, canvas_size, canvas_size))
    painter.end()

    buffer = image.bits().tobytes()
    return Image.frombytes("RGBA", (canvas_size, canvas_size), buffer, "raw", "BGRA")


def make_icon() -> Image.Image:
    logo = render_logo(CANVAS)
    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    radius = CANVAS // 7
    draw.rounded_rectangle([0, 0, CANVAS - 1, CANVAS - 1], radius=radius, fill=BACKGROUND)
    draw.rounded_rectangle(
        [0, 0, CANVAS - 1, CANVAS - 1],
        radius=radius,
        outline=BORDER,
        width=max(4, CANVAS // 80),
    )
    margin = int(CANVAS * 0.12)
    content = CANVAS - margin * 2
    icon.alpha_composite(logo.resize((content, content), Image.Resampling.LANCZOS), (margin, margin))
    return icon


def main() -> int:
    icon = make_icon()
    icon.save(OUTPUT_ICO, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"written: {OUTPUT_ICO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())