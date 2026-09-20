
"""基于 Qt/QImage 的快速热图渲染器。

这里处理的是已经整理好的绘图载荷，不负责计算光场。它把二维数组转换成
颜色图像，并在 Qt 画布中绘制热图、端面匹配叠加轮廓和 X/Y 剖面。对于大
网格，这条路径比 Matplotlib 更适合嵌入式实时刷新。

主要入口：

* :func:`_qimage`：数值数组 -> 颜色图像；
* :class:`FastHeatmapWidget.set_plot`：接收绘图载荷；
* :class:`FastHeatmapWidget.paintEvent`：把图像和标注绘制到控件。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any
import numpy as np
from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from frontend_pyside.shared.performance import record_perf

# 使用固定颜色查找表，避免每次重绘都创建 Matplotlib 色图。
_ANCHOR_X = np.asarray([0.0, 0.25, 0.5, 0.75, 1.0])
_ANCHOR_RGB = np.asarray([[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]], dtype=float)
_LUT = np.stack([
    np.interp(np.linspace(0.0, 1.0, 256), _ANCHOR_X, _ANCHOR_RGB[:, i])
    for i in range(3)
], axis=1).astype(np.uint8)

# 类似图2的能量分布色带：低能量为深蓝，高能量依次经过青、绿、黄、红。
_ENERGY_ANCHOR_X = np.asarray([0.0, 0.16, 0.34, 0.52, 0.72, 0.88, 1.0])
_ENERGY_ANCHOR_RGB = np.asarray(
    [[5, 8, 72], [0, 45, 190], [0, 190, 255], [0, 220, 90], [255, 238, 0], [255, 65, 0], [145, 0, 0]],
    dtype=float,
)
_ENERGY_LUT = np.stack([
    np.interp(np.linspace(0.0, 1.0, 256), _ENERGY_ANCHOR_X, _ENERGY_ANCHOR_RGB[:, i])
    for i in range(3)
], axis=1).astype(np.uint8)

# 相位使用首尾闭合的彩色环，避免把相位跳变误读成强度突变。
_PHASE_ANCHOR_X = np.asarray([0.0, 0.25, 0.5, 0.75, 1.0])
_PHASE_ANCHOR_RGB = np.asarray(
    [[48, 0, 130], [0, 185, 255], [245, 245, 40], [245, 45, 20], [48, 0, 130]],
    dtype=float,
)
_PHASE_LUT = np.stack([
    np.interp(np.linspace(0.0, 1.0, 256), _PHASE_ANCHOR_X, _PHASE_ANCHOR_RGB[:, i])
    for i in range(3)
], axis=1).astype(np.uint8)


def _as_2d(value: Any) -> np.ndarray:
    """把输入规整为非空二维浮点数组，供 QImage 和绘图计算使用。"""
    array = np.asarray(value)
    if array.ndim != 2 or array.size == 0:
        return np.zeros((1, 1), dtype=np.float32)
    return np.asarray(array, dtype=np.float32)


def _qimage(value: Any, *, color_map: str = "viridis", normalization: str = "linear") -> QImage:
    """将二维数值数组按稳健分位数拉伸后转换为 RGB QImage。

    普通图使用分位数拉伸；能量图使用对数增强，使弱能量环带也能显示；
    相位图按 ``[-π, π]`` 周期映射。原始数据不会被修改。
    """
    array = _as_2d(value)
    mode = str(normalization or "linear").lower()
    if mode == "phase":
        wrapped = np.angle(np.exp(1j * np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)))
        scaled = (wrapped + np.pi) / (2.0 * np.pi)
    elif mode in {"energy", "log"}:
        positive = np.maximum(np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0), 0.0)
        finite = positive[np.isfinite(positive)]
        if finite.size:
            sample = finite[::max(1, finite.size // 65536)]
            positive_values = sample[sample > 0.0]
            peak = float(np.percentile(positive_values, 99.5)) if positive_values.size else 1.0
            peak = max(peak, float(np.max(positive)) * 1.0e-6, 1.0e-12)
        else:
            peak = 1.0
        linear = np.clip(positive / peak, 0.0, 1.0)
        scaled = np.log1p(linear * 1000.0) / np.log1p(1000.0)
    else:
        finite = array[np.isfinite(array)]
        if finite.size:
            # 大数组只抽样计算分位数，限制热图更新的额外开销。
            sample = finite[::max(1, finite.size // 65536)]
            lo = float(np.percentile(sample, 0.5)); hi = float(np.percentile(sample, 99.5))
        else:
            lo, hi = 0.0, 1.0
        if hi <= lo:
            hi = lo + 1.0
        # 非有限值映射到颜色表两端，避免 QImage 接收 NaN/Inf。
        scaled = np.nan_to_num((array - lo)/(hi-lo), nan=0.0, posinf=1.0, neginf=0.0)
    indices = np.clip(np.rint(scaled*255.0), 0, 255).astype(np.uint8)
    palette = _LUT
    if str(color_map).lower() in {"energy", "turbo", "jet"}:
        palette = _ENERGY_LUT
    elif str(color_map).lower() in {"phase", "twilight"}:
        palette = _PHASE_LUT
    rgb = np.ascontiguousarray(palette[indices])
    image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
    return image.copy()

def physical_span(data: dict[str, Any], image: QImage | None = None) -> tuple[float, float]:
    """读取热图的物理 X/Y 范围；缺失坐标时回退到像素尺寸。"""
    x = np.asarray(data.get("x", []), dtype=float).reshape(-1)
    y = np.asarray(data.get("y", []), dtype=float).reshape(-1)
    x = x[np.isfinite(x)]
    y = y[np.isfinite(y)]
    span_x = float(abs(x[-1] - x[0])) if x.size >= 2 else 0.0
    span_y = float(abs(y[-1] - y[0])) if y.size >= 2 else 0.0
    if span_x > 0.0 and span_y > 0.0:
        return span_x, span_y
    if image is not None and not image.isNull():
        return float(max(image.width(), 1)), float(max(image.height(), 1))
    return 1.0, 1.0


def fitted_physical_rect(available: QRect, span_x: float, span_y: float) -> QRect:
    """在可用区域内按物理宽高比居中放置热图，避免图像变形。"""
    width = max(int(available.width()), 1)
    height = max(int(available.height()), 1)
    if span_x <= 0.0 or span_y <= 0.0:
        return QRect(available.x(), available.y(), width, height)
    target = span_x / span_y
    current = width / float(height)
    if current > target:
        fitted_w = max(1, int(round(height * target)))
        fitted_h = height
    else:
        fitted_w = width
        fitted_h = max(1, int(round(width / target)))
    x = available.x() + (width - fitted_w) // 2
    y = available.y() + (height - fitted_h) // 2
    return QRect(x, y, fitted_w, fitted_h)


def prewarm_fast_heatmap() -> dict[str, float]:
    """用小型高斯数组预热 NumPy/QImage 路径并返回耗时。"""
    started = perf_counter()
    axis = np.linspace(-1.0, 1.0, 129, dtype=np.float32)
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    _qimage(np.exp(-4.0 * (xx * xx + yy * yy)))
    return {"elapsed_ms": round((perf_counter() - started) * 1000.0, 3)}


class FastHeatmapWidget(QWidget):
    """绘制热图类载荷的轻量 Qt 控件。"""

    rendered = Signal(str)

    def __init__(self, parent=None) -> None:
        """初始化数据缓存和渲染完成信号。"""
        super().__init__(parent)
        self.setMinimumSize(120, 100)
        self._data: dict[str, Any] = {}
        self._images: list[QImage] = []
        self._render_key = ""
        self.setAutoFillBackground(True)

    @property
    def data(self) -> dict[str, Any]:
        """返回当前绘图载荷的浅拷贝。"""
        return dict(self._data)

    def set_plot(self, data: dict[str, Any]) -> None:
        """接收热图载荷，预先转换 QImage，并请求一次 Qt 重绘。"""
        started = perf_counter()
        self._data = dict(data or {})
        kind = str(self._data.get("kind", "heatmap"))
        color_map = str(self._data.get("color_map", "viridis"))
        normalization = str(self._data.get("normalization", "linear"))
        if kind == "heatmap_pair":
            # 端面匹配通常同时显示入射场和目标模式两张热图。
            self._images = [
                _qimage(self._data.get("z1", []), color_map=color_map, normalization=normalization),
                _qimage(self._data.get("z2", []), color_map=color_map, normalization=normalization),
            ]
        else:
            # heatmap、beam_match 等单图类型使用 z 数组。
            self._images = [_qimage(self._data.get("z", []), color_map=color_map, normalization=normalization)]
        self._render_key = str(self._data.get("render_key") or id(data))
        self.update()
        record_perf("plot_update", (perf_counter()-started)*1000.0, kind=kind, mode="qimage")
        self.rendered.emit(self._render_key)

    def reset_view(self) -> None:
        """请求重绘；快速热图没有 Matplotlib 的缩放状态需要恢复。"""
        self.update()

    def current_pixmap(self) -> QPixmap:
        """抓取当前 Qt 控件画面，用于导出或预览。"""
        return self.grab()

    @staticmethod
    def _profile_path(values: Any, rect: QRect, *, vertical: bool = False) -> QPainterPath:
        """把一维剖面归一化并转换为 Qt 折线路径。"""
        array = np.asarray(values, dtype=float).reshape(-1)
        array = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
        if not array.size:
            return QPainterPath()
        maximum = float(np.max(np.abs(array)))
        if maximum > 0.0:
            array = array / maximum
        path = QPainterPath()
        for index, value in enumerate(array):
            ratio = index / max(array.size - 1, 1)
            if vertical:
                point = QPointF(rect.right() + float(value) * rect.width(), rect.bottom() - ratio * rect.height())
            else:
                point = QPointF(rect.left() + ratio * rect.width(), rect.bottom() - float(value) * rect.height())
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        return path

    def _draw_beam_match(self, painter: QPainter) -> None:
        """绘制端面匹配图：主热图、模式轮廓、X/Y 剖面和图例。"""
        left_profile_w, top_profile_h = 58, 54
        margin_right, margin_bottom = 24, 42
        available = self.rect().adjusted(left_profile_w + 12, top_profile_h + 10, -margin_right, -margin_bottom)
        if available.width() <= 2 or available.height() <= 2:
            return
        span_x, span_y = physical_span(self._data, self._images[0] if self._images else None)
        main = fitted_physical_rect(available, span_x, span_y)
        painter.drawImage(main, self._images[0])
        painter.setPen(QPen(QColor("#111827"), 1))
        painter.drawRect(main)

        # contour 是目标光纤模式的等值线数据，用来叠加在入射场热图上。
        contour = _as_2d(self._data.get("contour", []))
        if contour.size and contour.shape == _as_2d(self._data.get("z", [])).shape:
            maximum = float(np.nanmax(contour)) if contour.size else 0.0
            threshold = maximum * float(self._data.get("contour_fraction", np.exp(-2.0)))
            if threshold > 0.0:
                mask = np.asarray(contour >= threshold)
                rows = np.linspace(0, max(mask.shape[0] - 1, 0), min(mask.shape[0], 180), dtype=int)
                left_path = QPainterPath(); right_path = QPainterPath(); first = True
                for row in rows:
                    columns = np.flatnonzero(mask[row])
                    if not columns.size:
                        continue
                    yy = main.bottom() - (row / max(mask.shape[0] - 1, 1)) * main.height()
                    lx = main.left() + (columns[0] / max(mask.shape[1] - 1, 1)) * main.width()
                    rx = main.left() + (columns[-1] / max(mask.shape[1] - 1, 1)) * main.width()
                    if first:
                        left_path.moveTo(lx, yy); right_path.moveTo(rx, yy); first = False
                    else:
                        left_path.lineTo(lx, yy); right_path.lineTo(rx, yy)
                painter.setPen(QPen(QColor("#ef4444"), 1.5))
                painter.drawPath(left_path); painter.drawPath(right_path)

        top = QRect(main.left(), 8, main.width(), max(20, top_profile_h - 10))
        side = QRect(main.left()+ main.width()-10, main.top(), max(20, left_profile_w - 12), main.height())
        # 上方绘制 X 剖面，左侧绘制 Y 剖面；两组都可包含入射场和光纤模式。
        x_profiles = self._data.get("x_profiles", {}) or {}
        y_profiles = self._data.get("y_profiles", {}) or {}
        profile_colors = [QColor("#2563eb"), QColor("#ef4444")]
        for index, values in enumerate(x_profiles.values()):
            painter.setPen(QPen(profile_colors[index % len(profile_colors)], 1.35))
            painter.drawPath(self._profile_path(values, top))
        for index, values in enumerate(y_profiles.values()):
            painter.setPen(QPen(profile_colors[index % len(profile_colors)], 1.35))
            painter.drawPath(self._profile_path(values, side, vertical=True))
        legend_labels = [str(label) for label in list(x_profiles.keys() or y_profiles.keys()) if str(label).strip()]
        if legend_labels:
            row_height = 18
            legend_width = min(220, max(150, main.width() // 3))
            legend_height = 10 + row_height * len(legend_labels)
            legend = QRect(
                main.left() + 10,
                main.top() + 10,
                legend_width,
                legend_height,
            )
            painter.fillRect(legend, QColor(255, 255, 255, 224))
            painter.setPen(QPen(QColor("#94a3b8"), 1))
            painter.drawRect(legend)
            for index, label in enumerate(legend_labels):
                y_pos = legend.top() + 9 + index * row_height
                painter.setPen(QPen(profile_colors[index % len(profile_colors)], 2.0))
                painter.drawLine(legend.left() + 8, y_pos, legend.left() + 28, y_pos)
                painter.setPen(QPen(QColor("#111827"), 1))
                painter.drawText(
                    QRect(legend.left() + 36, y_pos - 9, legend.width() - 42, 18),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
        painter.setPen(QPen(QColor("#111827"), 1))
        painter.drawText(QRect(main.left(), main.bottom()+8, main.width(), 24), Qt.AlignmentFlag.AlignCenter, str(self._data.get("x_label", "x")))
        painter.save(); painter.translate(main.left()-12, main.center().y()); painter.rotate(-90)
        painter.drawText(QRect(-main.height()//2, -14, main.height(), 24), Qt.AlignmentFlag.AlignCenter, str(self._data.get("y_label", "y")))
        painter.restore()

    def paintEvent(self, _event) -> None:
        """按照载荷 kind 绘制单热图、双热图或端面匹配复合图。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if not self._images:
            return
        kind = str(self._data.get("kind", "heatmap"))
        if kind == "beam_match":
            # beam_match 使用专门布局，包含剖面和轮廓，不能走普通热图布局。
            self._draw_beam_match(painter)
            return
        margin_left, margin_right, margin_top, margin_bottom = 52, 24, 14, 42
        plot = self.rect().adjusted(margin_left, margin_top, -margin_right, -margin_bottom)
        count = len(self._images)
        gap = 12 if count > 1 else 0
        width = max(1, (plot.width() - gap * (count - 1)) // count)
        painter.setPen(QPen(QColor("#111827"), 1))
        # heatmap_pair 的两幅图共享物理坐标，但分别标注入射场和目标模式。
        pair_labels = ("\u5165\u5c04\u573a", "\u76ee\u6807\u6a21\u573a")
        for index, image in enumerate(self._images):
            cell = QRect(plot.left() + index * (width + gap), plot.top(), width, plot.height())
            span_x, span_y = physical_span(self._data, image)
            rect = fitted_physical_rect(cell, span_x, span_y)
            painter.drawImage(rect, image)
            painter.drawRect(rect)
            if count > 1:
                painter.drawText(
                    rect.adjusted(4, 4, -4, -4),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                    pair_labels[index] if index < len(pair_labels) else "",
                )
        painter.drawText(QRect(plot.left(), plot.bottom()+8, plot.width(), 24), Qt.AlignmentFlag.AlignCenter, str(self._data.get("x_label", "x")))
        painter.save(); painter.translate(rect.left()-18, plot.center().y()); painter.rotate(-90)
        painter.drawText(QRect(-plot.height()//2, -12, plot.height(), 24), Qt.AlignmentFlag.AlignCenter, str(self._data.get("y_label", "y")))
        painter.restore()


__all__ = ["FastHeatmapWidget", "fitted_physical_rect", "physical_span", "prewarm_fast_heatmap"]
