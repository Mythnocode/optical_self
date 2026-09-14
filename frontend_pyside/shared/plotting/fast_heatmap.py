
from __future__ import annotations

from time import perf_counter
from typing import Any
import numpy as np
from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from frontend_pyside.shared.performance import record_perf

_ANCHOR_X = np.asarray([0.0, 0.25, 0.5, 0.75, 1.0])
_ANCHOR_RGB = np.asarray([[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]], dtype=float)
_LUT = np.stack([
    np.interp(np.linspace(0.0, 1.0, 256), _ANCHOR_X, _ANCHOR_RGB[:, i])
    for i in range(3)
], axis=1).astype(np.uint8)


def _as_2d(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2 or array.size == 0:
        return np.zeros((1, 1), dtype=np.float32)
    return np.asarray(array, dtype=np.float32)


def _qimage(value: Any) -> QImage:
    array = _as_2d(value)
    finite = array[np.isfinite(array)]
    if finite.size:
        
        
        sample = finite[::max(1, finite.size // 65536)]
        lo = float(np.percentile(sample, 0.5)); hi = float(np.percentile(sample, 99.5))
    else:
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + 1.0
    scaled = np.nan_to_num((array - lo)/(hi-lo), nan=0.0, posinf=1.0, neginf=0.0)
    indices = np.clip(np.rint(scaled*255.0), 0, 255).astype(np.uint8)
    rgb = np.ascontiguousarray(_LUT[indices])
    image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
    return image.copy()

def physical_span(data: dict[str, Any], image: QImage | None = None) -> tuple[float, float]:
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

    started = perf_counter()
    axis = np.linspace(-1.0, 1.0, 129, dtype=np.float32)
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    _qimage(np.exp(-4.0 * (xx * xx + yy * yy)))
    return {"elapsed_ms": round((perf_counter() - started) * 1000.0, 3)}


class FastHeatmapWidget(QWidget):
    rendered = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(120, 100)
        self._data: dict[str, Any] = {}
        self._images: list[QImage] = []
        self._render_key = ""
        self.setAutoFillBackground(True)

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._data)

    def set_plot(self, data: dict[str, Any]) -> None:
        started = perf_counter()
        self._data = dict(data or {})
        kind = str(self._data.get("kind", "heatmap"))
        if kind == "heatmap_pair":
            self._images = [_qimage(self._data.get("z1", [])), _qimage(self._data.get("z2", []))]
        else:
            self._images = [_qimage(self._data.get("z", []))]
        self._render_key = str(self._data.get("render_key") or id(data))
        self.update()
        record_perf("plot_update", (perf_counter()-started)*1000.0, kind=kind, mode="qimage")
        self.rendered.emit(self._render_key)

    def reset_view(self) -> None:
        self.update()

    def current_pixmap(self) -> QPixmap:
        return self.grab()

    @staticmethod
    def _profile_path(values: Any, rect: QRect, *, vertical: bool = False) -> QPainterPath:
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
                point = QPointF(rect.right() - float(value) * rect.width(), rect.bottom() - ratio * rect.height())
            else:
                point = QPointF(rect.left() + ratio * rect.width(), rect.bottom() - float(value) * rect.height())
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        return path

    def _draw_beam_match(self, painter: QPainter) -> None:
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
        side = QRect(6, main.top(), max(20, left_profile_w - 12), main.height())
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
        painter.save(); painter.translate(14, main.center().y()); painter.rotate(-90)
        painter.drawText(QRect(-main.height()//2, -12, main.height(), 24), Qt.AlignmentFlag.AlignCenter, str(self._data.get("y_label", "y")))
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if not self._images:
            return
        kind = str(self._data.get("kind", "heatmap"))
        if kind == "beam_match":
            self._draw_beam_match(painter)
            return
        margin_left, margin_right, margin_top, margin_bottom = 52, 24, 14, 42
        plot = self.rect().adjusted(margin_left, margin_top, -margin_right, -margin_bottom)
        count = len(self._images)
        gap = 12 if count > 1 else 0
        width = max(1, (plot.width() - gap * (count - 1)) // count)
        painter.setPen(QPen(QColor("#111827"), 1))
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
        painter.save(); painter.translate(16, plot.center().y()); painter.rotate(-90)
        painter.drawText(QRect(-plot.height()//2, -12, plot.height(), 24), Qt.AlignmentFlag.AlignCenter, str(self._data.get("y_label", "y")))
        painter.restore()


__all__ = ["FastHeatmapWidget", "fitted_physical_rect", "physical_span", "prewarm_fast_heatmap"]
