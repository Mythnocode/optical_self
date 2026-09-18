"""单色图标加载与重新着色。

资源目录：``frontend_pyside/resources/icons/``
查找顺序：``<name>.svg`` → ``<name>.png``

两种格式都只画**单色图形**，颜色一律由调用方通过 ``color`` 参数决定，
所以原图本身是什么颜色无所谓——换成自己画的图时，建议：

* SVG：用纯白描边（``stroke="#FFFFFF"`` / ``fill="#FFFFFF"``），
  代码会把源码里的 ``#FFFFFF`` 直接替换成目标色；
* PNG：透明背景 + 任意单色前景，代码会把整张图当遮罩刷成目标色，
  只保留 alpha 通道（所以画得糙一点也没关系，但必须是单色，
  彩色插画会被刷成一整块色）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:
    QSvgRenderer = None


_ICON_ROOT = Path(__file__).resolve().parents[1] / "resources" / "icons"

# 下面两个开关只影响 PNG，不影响内置 SVG。
#
# TRIM_PNG_ICONS —— 是否裁掉四周透明留白。
#   False（默认）：整张画布等比缩放进图标框。源图是正方形画布时，
#                  每个图标都会得到同样大小的框，高度天然对齐。
#   True         ：裁到图形包围盒后再缩放。图形更大更醒目，但长宽比
#                  不同的图会被装进正方形框，结果是高矮参差——除非
#                  所有源图的长宽比一致，否则别开。
TRIM_PNG_ICONS = False
#
# TINT_PNG_ICONS —— 是否按调用方给的颜色重新着色。
#   False（默认）：原样使用，保留图里的原色，color 参数被忽略。
#   True         ：把图当遮罩，只保留 alpha，刷成统一色，
#                  于是能和选中态联动（见 workbench_shell._secondary_icon）。
TINT_PNG_ICONS = False
#
# 图标要按这几个显示缩放比各烘一张位图。屏幕缩放大致是这几个之一，
# Qt 就能一直选到尺寸刚好的那张，不会放大绘制。多烘几张的开销只在每个
# 图标第一次用到时发生（结果有缓存）。
_ICON_PIXEL_RATIOS = (1.0, 1.25, 1.5, 2.0)


@lru_cache(maxsize=128)
def _svg_text(name: str) -> str:
    path = _ICON_ROOT / f"{name}.svg"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _resolve(name: str) -> tuple[str, Path] | None:
    """返回 (格式, 路径)；两种格式都没有时返回 None（矢量优先）。"""
    svg_path = _ICON_ROOT / f"{name}.svg"
    if svg_path.exists():
        return "svg", svg_path
    png_path = _ICON_ROOT / f"{name}.png"
    if png_path.exists():
        return "png", png_path
    return None


def _render_svg(name: str, color: str, size: int) -> QPixmap:
    svg = _svg_text(name).replace("#FFFFFF", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(QSize(int(size), int(size)))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def _downscale(image: QImage, size: int) -> QImage:
    """逐级减半地缩小到 size。

    位图图标常是上千像素的方图（本项目是 1254×1254），一次性缩到几十像素是
    几十倍降采样，Qt 的平滑缩放会漏采样、细线条容易断。逐级减半每次只降 2 倍，
    等效于低通滤波，线条能保住。

    循环条件是 ``> size * 2`` 而不是 ``// 2 >= size``：后者在目标尺寸较大时
    （例如 size=100）会一路减到 78 才发现停，最后一步 78→100 变成**放大**，
    比不处理还糊。
    """
    while image.width() > size * 2:
        image = image.scaled(
            image.width() // 2,
            image.height() // 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


@lru_cache(maxsize=128)
def _trimmed(path_str: str) -> QImage:
    """裁掉四周全透明的留白，只保留图形本身。

    这一步不能省：设计稿的图形往往只占画布的一部分（本项目的图是 1254×1254
    画布、内容只占 78%~91%，而且各图长宽比还不一样）。不裁的话按整张画布
    等比缩放到 22px，图形本身只剩十几个像素，又小又细，几张图大小还对不齐。
    """
    image = QImage(path_str).convertToFormat(QImage.Format.Format_RGBA8888)
    bounds = _alpha_bounds(image)
    return image.copy(bounds) if bounds is not None else image


def _alpha_bounds(image: QImage) -> QRect | None:
    """用 alpha 通道求内容的包围盒；numpy 不可用时返回 None（退回不裁）。"""
    try:
        import numpy as np
    except ImportError:
        return None
    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return None
    # bytesPerLine 会带行尾填充，先按行取出再切掉填充部分。
    raw = np.frombuffer(image.constBits(), dtype=np.uint8)
    raw = raw.reshape(height, image.bytesPerLine())[:, : width * 4].reshape(height, width, 4)
    alpha = raw[:, :, 3]
    rows = np.flatnonzero(alpha.any(axis=1))
    cols = np.flatnonzero(alpha.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    return QRect(
        int(cols[0]),
        int(rows[0]),
        int(cols[-1] - cols[0] + 1),
        int(rows[-1] - rows[0] + 1),
    )


def _png_source(path: Path) -> QImage:
    """位图源图；TRIM 打开时裁掉透明留白（``_trimmed`` 自带缓存）。

    单独抽出来是为了让一次 ``icon_pixmaps`` 里的几个缩放比共用同一份解码结果：
    原来 ``QImage(str(path))`` 写在按比例循环里面，一张图要重复解码 4 次，
    而 1254×1254 的 PNG 解码一次就要 ~9ms。
    """
    return _trimmed(str(path)) if TRIM_PNG_ICONS else QImage(str(path))


def _render_png(source: QImage, color: str | None, size: int) -> QPixmap:
    """把已解码的源图按 size 缩放；color 为 None 时保留原色，否则刷成该颜色。"""
    target = _downscale(source, int(size))
    if color is None:
        return QPixmap.fromImage(target)
    # SourceIn：只在新颜色与原图不透明区域相交处落笔，等于「用 alpha 当模板上色」。
    pixmap = QPixmap(target.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.drawImage(0, 0, target)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return pixmap


@lru_cache(maxsize=256)
def icon_pixmaps(name: str, color: str = "#FFFFFF", size: int = 24) -> tuple[QPixmap, ...]:
    """按常见显示缩放比各烘一张位图，供需要自己组装 QIcon 的调用方使用。

    为什么不能只烘一张：位图不像 SVG 能按需重绘。只烘一张 size×size 的话，
    在 Windows 常见的 125% / 150% 显示缩放下，Qt 需要 1.25×/1.5× 的物理像素，
    只能把这张放大绘制，边缘就糊了。这里每个比例各烘一张并标好各自的
    devicePixelRatio，Qt 会挑尺寸最合适的那张，全程不发生缩放。

    结果带缓存，而且返回的是元组：二级栏切一次一级标题就会重建所有按钮，
    没有缓存的话每张图都要重新解码 + 缩放出 4 个比例，实测切一次「仿真」
    要 516ms，其中 234ms 花在这里。缓存的都是几十像素的小位图
    （一组约 100KB），代价可以忽略。缓存的是不可变对象，调用方只遍历，
    不要就地改它。

    注意：和 ``icon()`` 一样，缓存里的 QPixmap 属于创建它的 QGuiApplication。
    进程内反复销毁重建 QApplication 的测试要留意这一点。
    """
    resolved = _resolve(str(name))
    if resolved is None:
        return ()
    kind, path = resolved
    tint = color if (kind != "png" or TINT_PNG_ICONS) else None
    pixmaps: list[QPixmap] = []
    try:
        if kind == "png":
            # 解码一次，下面几个缩放比共用
            source = _png_source(path)
        for ratio in _ICON_PIXEL_RATIOS:
            physical = max(1, int(round(int(size) * ratio)))
            if kind == "svg":
                if QSvgRenderer is None:
                    return ()
                pixmap = _render_svg(str(name), str(tint), physical)
            else:
                pixmap = _render_png(source, tint, physical)
            pixmap.setDevicePixelRatio(ratio)
            pixmaps.append(pixmap)
    except Exception:
        return ()
    return tuple(pixmaps)


@lru_cache(maxsize=512)
def icon(name: str, color: str = "#FFFFFF", size: int = 24) -> QIcon:
    pixmaps = icon_pixmaps(name, color, size)
    if not pixmaps:
        # 交回给 Qt 自己按文件加载（例如 SVG 渲染器不可用时）。
        resolved = _resolve(str(name))
        return QIcon(str(resolved[1])) if resolved is not None else QIcon()
    result = QIcon()
    for pixmap in pixmaps:
        result.addPixmap(pixmap)
    return result


@lru_cache(maxsize=128)
def icon_path(name: str) -> str:
    resolved = _resolve(str(name))
    return str(resolved[1]) if resolved is not None else ""


__all__ = ["icon", "icon_path", "icon_pixmaps"]
