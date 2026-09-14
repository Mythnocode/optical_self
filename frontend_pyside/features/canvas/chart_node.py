"""分析图 view 节点：只读图表，数据来自引擎回传的真实仿真数组。

从 demo.ChartNode 迁移到 CanvasNode(spec) 基类：
- 脏状态由数据源经 scene 传播；「立即更新 / 实时更新（700ms 防抖）/ 忽略」；
- 折叠态摘要行显示关键指标（MTF50 / η / RMS / 光线数 / PV / MFD）；
- 展开态自绘（黑白灰主调）：
  mtf 曲线 / intensity·psf·mode 灰度热图 / phase 相位图 /
  spot 点列 / layout 光路截面(x-z) / propagation 径向光扇(r-z) /
  catalogue 指标目录。
"""

from __future__ import annotations

import math

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QImage, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QMenu

from frontend_pyside.features.canvas.node import CanvasNode, find_view
from frontend_pyside.features.canvas.theme import C


def _font(px: int, bold: bool = False):
    from PySide6.QtGui import QFont

    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _as_2d(value) -> np.ndarray | None:
    if value is None:
        return None
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return arr if arr.ndim == 2 and arr.size > 0 else None


def _as_1d(value) -> np.ndarray | None:
    if value is None:
        return None
    try:
        arr = np.asarray(value, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    return arr if arr.size > 0 else None


def _heatmap_image(arr: np.ndarray, log_scale: bool = False) -> QPixmap | None:
    """numpy 2D → 灰度 QPixmap（黑白灰主题天然契合热图）。"""
    data = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    data = np.abs(data)
    if log_scale:
        peak = float(data.max()) or 1.0
        data = np.log1p(data / peak * 1e3)
    peak = float(data.max())
    if peak <= 0.0:
        return None
    gray = (data / peak * 255.0).astype(np.uint8)
    height, width = gray.shape
    # QImage(data, ...) only borrows the buffer.  ``gray.tobytes()`` is a
    # temporary object, so the pixmap could later paint from freed memory and
    # appear blank.  Detach the image before returning it.
    image = QImage(gray.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    return QPixmap.fromImage(image)


def _phase_image(arr: np.ndarray) -> QPixmap | None:
    """相位（-π..π 缠绕）→ 灰度 QPixmap：-π=黑，+π=白。"""
    data = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    norm = (data + math.pi) / (2.0 * math.pi)
    gray = (np.clip(norm, 0.0, 1.0) * 255.0).astype(np.uint8)
    height, width = gray.shape
    image = QImage(gray.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    return QPixmap.fromImage(image)


def _parse_ray_segments(arrays: dict) -> list[np.ndarray]:
    """raytrace 路径数组 → 每条光线的 (x, y, z) 点列（累积边界语义）。"""
    paths = _as_2d(arrays.get("raytrace_path_points_mm"))
    offsets = _as_1d(arrays.get("raytrace_path_offsets"))
    if paths is None or offsets is None or paths.shape[1] < 3:
        return []
    bounds = offsets.astype(int)
    if not (bounds.size >= 2 and bounds[0] == 0 and bounds[-1] == paths.shape[0]):
        return []
    return [
        paths[bounds[i] : bounds[i + 1], :]
        for i in range(bounds.size - 1)
        if bounds[i + 1] - bounds[i] >= 2
    ]


def _mode_metric(arr: np.ndarray, grid_x: np.ndarray | None, grid_y: np.ndarray | None) -> str:
    """模场 1/e² 直径（高斯近似 4σ 二阶矩，经网格换算为物理 µm）。"""
    data = np.nan_to_num(np.abs(arr), nan=0.0, posinf=0.0, neginf=0.0)
    total = float(data.sum())
    if total <= 0.0 or min(data.shape) < 2:
        return "模场 —"
    rows, cols = np.indices(data.shape)
    cx = float((data * cols).sum() / total)
    sig_px = math.sqrt(max(0.0, float((data * (cols - cx) ** 2).sum() / total)))

    def _span_mm(grid: np.ndarray | None, count: int) -> float | None:
        if grid is None or grid.size < 2 or count < 2:
            return None
        values = np.asarray(grid, dtype=float).ravel()
        return abs(float(values[-1]) - float(values[0]))

    span = _span_mm(grid_x, data.shape[1])
    if span is not None and span > 0.0:
        pitch_mm = span / (data.shape[1] - 1)
        mfd_um = 4.0 * sig_px * pitch_mm * 1000.0
        return f"MFD≈{mfd_um:.1f}µm"
    return "模场已载入"


# catalogue 展示的核心指标（键 → 显示名），按重要度排序
_CATALOGUE_KEYS = (
    ("coupling_efficiency", "耦合效率 η"),
    ("system_efficiency", "系统效率"),
    ("psf_rms_radius_mm", "PSF RMS 半径"),
    ("rms_spot_radius_um", "点列 RMS 半径"),
    ("spot_valid_ray_count", "有效光线"),
    ("spot_total_ray_count", "总光线"),
    ("ray_count", "追迹光线数"),
    ("valid_ray_ratio", "有效光线占比"),
    ("converged", "收敛"),
    ("coupling_breakdown_mode_overlap", "模场重叠"),
    ("coupling_breakdown_phase", "相位匹配"),
    ("coupling_breakdown_transmission", "透射"),
    ("strehl_ratio", "斯特列尔比"),
)


def _catalogue_rows(metrics: dict) -> list[tuple[str, str]]:
    """metrics → 展示行（核心指标优先，其余标量按序补充）。"""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, label in _CATALOGUE_KEYS:
        if key in metrics:
            rows.append((label, _format_metric(metrics[key])))
            seen.add(key)
    for key, value in metrics.items():
        if key in seen or key.startswith(("stage_", "timing")) or len(key) > 40:
            continue
        text = _format_metric(value)
        if text is None:
            continue
        rows.append((key, text))
    return rows[:18]


def _format_metric(value) -> str | None:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return f"{value:.6g}"
    if isinstance(value, str) and len(value) <= 24:
        return value
    return None


class ChartNode(CanvasNode):
    """只读分析图节点。chart_kind ∈ {mtf, intensity, psf, spot, layout, ...}。"""

    REALTIME_DEBOUNCE_MS = 700

    def __init__(self, node_id: str, spec, chart_kind: str, parent=None):
        super().__init__(node_id, spec, parent)
        self.chart_kind = str(chart_kind)
        self._has_result = False
        # 按种类缓存的真实数据
        self._mtf: dict = {}
        self._image: QPixmap | None = None  # intensity / psf / phase / mode 热图缓存
        self._points: np.ndarray | None = None  # spot 数据
        self._segments: list[np.ndarray] = []  # layout / propagation 光线段
        self._metrics_rows: list[tuple[str, str]] = []  # catalogue 指标行
        self._summary_metric = "—"

        self._rt_timer = QTimer(self)
        self._rt_timer.setSingleShot(True)
        self._rt_timer.setInterval(self.REALTIME_DEBOUNCE_MS)
        self._rt_timer.timeout.connect(self.do_refresh)

    # ---- 结果注入 ----------------------------------------------------------

    @property
    def engine_analyses(self) -> frozenset[str] | None:
        """本节点所需引擎分析集合；None = 依赖全量（节点级增量刷新的请求范围）。"""
        from .refresh_controller import chart_analyses

        return chart_analyses(self.chart_kind)

    def set_result(self, arrays: dict, metrics: dict) -> None:
        """引擎结果到达：提取本种类数据并重绘。"""
        try:
            if self.scene() is None:
                return
        except RuntimeError:
            return
        self._image = None
        self._points = None
        self._mtf = {}
        self._segments = []
        self._metrics_rows = []
        kind = self.chart_kind
        if kind == "mtf":
            freqs = _as_1d(arrays.get("mtf_fx_cycles_per_mm"))
            cut_x = _as_1d(arrays.get("mtf_x_cut"))
            cut_y = _as_1d(arrays.get("mtf_y_cut"))
            if freqs is not None and cut_x is not None and freqs.size == cut_x.size:
                half = freqs >= 0.0  # 频率轴为 ±Nyquist、DC 居中 → 取正半轴
                freqs, cut_x = freqs[half], cut_x[half]
                cut_y = cut_y[half] if cut_y is not None and cut_y.size == half.size else cut_x
                self._mtf = {"freqs": freqs, "x": cut_x, "y": cut_y}
                self._summary_metric = self._mtf50(freqs, cut_x)
        elif kind in ("intensity", "psf", "mode"):
            key = {
                "intensity": "coupling_field_intensity",
                "psf": "psf_intensity",
                "mode": "coupling_mode_intensity",
            }[kind]
            arr = _as_2d(arrays.get(key))
            if arr is not None:
                pixmap = _heatmap_image(arr, log_scale=(kind == "psf"))
                if pixmap is not None:
                    self._image = pixmap
                    if kind == "intensity":
                        eta = metrics.get("coupling_efficiency")
                        self._summary_metric = f"η={float(eta):.3f}" if eta is not None else "η=—"
                    elif kind == "psf":
                        rms = metrics.get("psf_rms_radius_mm")
                        self._summary_metric = f"RMS={float(rms) * 1000.0:.1f}µm" if rms is not None else "RMS=—"
                    else:
                        self._summary_metric = _mode_metric(
                            arr,
                            _as_1d(arrays.get("coupling_grid_x_mm")),
                            _as_1d(arrays.get("coupling_grid_y_mm")),
                        )
        elif kind == "phase":
            arr = _as_2d(arrays.get("coupling_field_phase_rad"))
            if arr is not None:
                pixmap = _phase_image(arr)
                if pixmap is not None:
                    self._image = pixmap
                    finite = arr[np.isfinite(arr)]
                    pv = float(np.ptp(finite)) if finite.size else 0.0
                    self._summary_metric = f"PV={pv:.2f} rad"
        elif kind == "spot":
            xs = _as_1d(arrays.get("spot_x_um"))
            ys = _as_1d(arrays.get("spot_y_um"))
            mask = _as_1d(arrays.get("spot_valid_mask"))
            if xs is not None and ys is not None and xs.size == ys.size:
                if mask is not None and mask.size == xs.size:
                    keep = mask > 0
                    xs, ys = xs[keep], ys[keep]
                if xs.size:
                    self._points = np.stack([xs, ys], axis=1)
                    rms = metrics.get("rms_spot_radius_um")
                    self._summary_metric = f"RMS={float(rms):.2f}µm" if rms is not None else "RMS=—"
        elif kind in ("layout", "propagation"):
            segments = _parse_ray_segments(arrays)
            if segments:
                if kind == "layout":
                    # 光路截面：横轴 x（垂轴），纵轴 z（传播）
                    self._segments = [seg[:, [0, 2]] for seg in segments]
                else:
                    # 径向光扇：r = √(x²+y²)，横轴 z（传播），纵轴 r
                    self._segments = [
                        np.stack(
                            [seg[:, 2], np.hypot(seg[:, 0], seg[:, 1])], axis=1
                        )
                        for seg in segments
                    ]
                valid = metrics.get("spot_valid_ray_count")
                total = metrics.get("spot_total_ray_count")
                if valid is not None and total is not None:
                    self._summary_metric = f"光线 {int(valid)}/{int(total)}"
                else:
                    self._summary_metric = "光线 —"
        elif kind == "catalogue":
            rows = _catalogue_rows(metrics)
            self._metrics_rows = rows
            self._summary_metric = f"指标 {len(rows)} 项"
        self._has_result = True
        self.set_refreshing(False)
        self.set_stale(False)
        self.update()

    @staticmethod
    def _mtf50(freqs: np.ndarray, cut: np.ndarray) -> str:
        n = min(freqs.size, cut.size)
        f, c = freqs[:n], np.clip(cut[:n], 0.0, 1.0)
        if c.size == 0:
            return "MTF50=—"
        if float(c[-1]) >= 0.5:
            return f"MTF50>{f[-1]:.0f} lp/mm"
        for i in range(c.size - 1):  # 下穿 0.5 的采样区间内线性插值
            if c[i] >= 0.5 > c[i + 1]:
                t = (float(c[i]) - 0.5) / (float(c[i]) - float(c[i + 1]))
                return f"MTF50≈{float(f[i]) + t * (float(f[i + 1]) - float(f[i])):.0f} lp/mm"
        return "MTF50<首采样"

    # ---- 脏传播 ------------------------------------------------------------

    def apply_source_change(self, reason: str) -> None:
        self.setToolTip(reason)
        self.set_stale(True, reason)
        if self._realtime:
            self._rt_timer.start()

    def do_refresh(self) -> None:
        self._rt_timer.stop()
        self.refreshRequested.emit(self.node_id)

    # ---- 徽标菜单 ----------------------------------------------------------

    def _open_badge_menu(self, pos) -> bool:
        if not (self._stale or self._ignored):
            return False
        view = find_view(self)
        menu = QMenu(view)
        act_now = menu.addAction("立即更新（真实引擎）")
        act_rt = menu.addAction("实时更新（跟随修改）")
        act_rt.setCheckable(True)
        act_rt.setChecked(self._realtime)
        act_ignore = menu.addAction("忽略此版本")
        chosen = menu.exec(QCursor.pos())
        if chosen is act_now:
            self.do_refresh()
        elif chosen is act_rt:
            self._realtime = not self._realtime
            if self._realtime and self._stale:
                self._rt_timer.start()
        elif chosen is act_ignore:
            self.set_ignored()
        return True

    def summary_text(self) -> str:
        if not self._has_result:
            return "等待首次计算"
        return self._summary_metric

    # ---- 绘制 ----------------------------------------------------------

    def _paint_content(self, painter, rect: QRectF) -> None:
        painter.setClipRect(rect)
        if not self._has_result:
            painter.setPen(QColor(C["text_muted"]))
            painter.setFont(_font(12))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "等待引擎首次计算…")
        elif self.chart_kind == "mtf":
            self._paint_mtf(painter, rect)
        elif self.chart_kind in ("intensity", "psf", "phase", "mode"):
            self._paint_heatmap(painter, rect)
        elif self.chart_kind == "spot":
            self._paint_spot(painter, rect)
        elif self.chart_kind == "catalogue":
            self._paint_catalogue(painter, rect)
        elif self.chart_kind == "propagation":
            self._paint_propagation(painter, rect)
        else:
            self._paint_layout(painter, rect)
        painter.setClipping(False)
        if self._refreshing:
            self._paint_refreshing_overlay(painter, rect)

    def _axes(self, painter, rect: QRectF) -> None:
        pen = QPen(QColor(C["grid_dot"]))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()))
        painter.drawLine(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))

    def _paint_mtf(self, painter, rect: QRectF) -> None:
        self._axes(painter, rect)
        if not self._mtf:
            self._paint_no_data(painter, rect)
            return
        freqs, cut_x, cut_y = self._mtf["freqs"], self._mtf["x"], self._mtf["y"]
        n = min(freqs.size, cut_x.size, cut_y.size)
        freqs, cut_x, cut_y = freqs[:n], cut_x[:n], cut_y[:n]
        # 限制到 MTF 跌破 0.02 的频率范围，避免长尾压扁曲线
        active = (cut_x > 0.02) | (cut_y > 0.02)
        if active.any():
            last = int(np.nonzero(active)[0][-1]) + 1
            last = max(last, 8)
            freqs, cut_x, cut_y = freqs[:last], cut_x[:last], cut_y[:last]
        fmax = float(freqs.max()) or 1.0
        step = max(1, n // 96)

        def polyline(cut: np.ndarray) -> QPolygonF:
            pts = QPolygonF()
            for i in range(0, cut.size, step):
                x = rect.left() + (rect.width() - 8.0) * float(freqs[i]) / fmax
                y = rect.bottom() - 4.0 - (rect.height() - 10.0) * float(np.clip(cut[i], 0.0, 1.0))
                pts.append(QPointF(x, y))
            return pts

        pen = QPen(QColor(C["text_muted"]))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPolyline(polyline(cut_y))  # 弧矢
        pen = QPen(QColor(C["text"]))
        pen.setWidthF(1.8)
        painter.setPen(pen)
        painter.drawPolyline(polyline(cut_x))  # 子午

    def _paint_heatmap(self, painter, rect: QRectF) -> None:
        if self._image is None:
            if self._has_result:
                self._paint_no_data(painter, rect)
            return
        scaled = self._image.scaled(
            int(rect.width()), int(rect.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = rect.left() + (rect.width() - scaled.width()) / 2.0
        y = rect.top() + (rect.height() - scaled.height()) / 2.0
        painter.drawPixmap(QPointF(x, y), scaled)

    def _paint_spot(self, painter, rect: QRectF) -> None:
        self._axes(painter, rect)
        if self._points is None or not len(self._points):
            self._paint_no_data(painter, rect)
            return
        pts = self._points
        if pts.shape[0] > 700:  # 降采样避免绘制过载
            idx = np.linspace(0, pts.shape[0] - 1, 700).astype(int)
            pts = pts[idx]
        xs, ys = pts[:, 0], pts[:, 1]
        span = max(float(np.ptp(xs)), float(np.ptp(ys)), 1e-9) * 1.1
        cx, cy = float(xs.mean()), float(ys.mean())
        side = min(rect.width(), rect.height()) - 8.0
        painter.setPen(QPen(QColor(C["text"])))
        painter.setBrush(QColor(C["text"]))
        for x, y in zip(xs, ys):
            px = rect.center().x() + (x - cx) / span * side
            py = rect.center().y() - (y - cy) / span * side
            painter.drawEllipse(QPointF(px, py), 1.2, 1.2)

    def _paint_layout(self, painter, rect: QRectF) -> None:
        self._axes(painter, rect)
        segments = self._segments
        if not segments:
            self._paint_no_data(painter, rect)
            return
        all_pts = np.concatenate(segments, axis=0)
        x_min, x_max = float(all_pts[:, 0].min()), float(all_pts[:, 0].max())
        z_min, z_max = float(all_pts[:, 1].min()), float(all_pts[:, 1].max())
        span_x = max(x_max - x_min, 1e-9)
        span_z = max(z_max - z_min, 1e-9)
        # 抽稀：最多画 14 条光线
        draw = segments if len(segments) <= 14 else [segments[i] for i in np.linspace(0, len(segments) - 1, 14).astype(int)]

        def to_px(x: float, z: float) -> QPointF:
            px = rect.left() + 4.0 + (x - x_min) / span_x * (rect.width() - 8.0)
            py = rect.bottom() - 4.0 - (z - z_min) / span_z * (rect.height() - 8.0)
            return QPointF(px, py)

        painter.setPen(QPen(QColor(C["text"]), 1.0))
        for seg in draw:
            pts = QPolygonF([to_px(float(x), float(z)) for x, z in seg])
            painter.drawPolyline(pts)
        # 光轴
        pen = QPen(QColor(C["text_muted"]))
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(to_px(x_min, 0.0), to_px(x_max, 0.0))

    def _paint_propagation(self, painter, rect: QRectF) -> None:
        """径向光扇：z 横轴（传播方向），r = √(x²+y²) 纵轴。"""
        self._axes(painter, rect)
        segments = self._segments
        if not segments:
            self._paint_no_data(painter, rect)
            return
        all_pts = np.concatenate(segments, axis=0)
        z_min, z_max = float(all_pts[:, 0].min()), float(all_pts[:, 0].max())
        r_max = max(float(all_pts[:, 1].max()), 1e-9)
        span_z = max(z_max - z_min, 1e-9)
        draw = segments if len(segments) <= 14 else [segments[i] for i in np.linspace(0, len(segments) - 1, 14).astype(int)]

        def to_px(z: float, r: float) -> QPointF:
            px = rect.left() + 4.0 + (z - z_min) / span_z * (rect.width() - 8.0)
            py = rect.center().y() - r / r_max * (rect.height() / 2.0 - 6.0)
            return QPointF(px, py)

        painter.setPen(QPen(QColor(C["text"]), 1.0))
        for seg in draw:
            pts = QPolygonF([to_px(float(z), float(r)) for z, r in seg])
            painter.drawPolyline(pts)
        # 光轴（r=0）
        pen = QPen(QColor(C["text_muted"]))
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(to_px(z_min, 0.0), to_px(z_max, 0.0))

    def _paint_catalogue(self, painter, rect: QRectF) -> None:
        """指标目录：核心 metrics 键值两栏文本。"""
        rows = self._metrics_rows
        if not rows:
            self._paint_no_data(painter, rect)
            return
        line_h = 16.0
        top = rect.top() + 4.0
        visible = int((rect.height() - 8.0) // line_h)
        value_w = rect.width() * 0.42
        painter.setFont(_font(11))
        for index, (label, value) in enumerate(rows[:visible]):
            y = top + index * line_h
            painter.setPen(QColor(C["text"]))
            painter.drawText(
                QRectF(rect.left() + 6.0, y, rect.width() - value_w - 12.0, line_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                str(label),
            )
            painter.setPen(QColor(C["text_muted"]))
            painter.drawText(
                QRectF(rect.right() - value_w - 6.0, y, value_w, line_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                value,
            )
        if len(rows) > visible:
            painter.setPen(QColor(C["text_muted"]))
            painter.setFont(_font(10))
            painter.drawText(
                QRectF(rect.left() + 6.0, rect.bottom() - 14.0, rect.width() - 12.0, 14.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"… 其余 {len(rows) - visible} 项（展开节点查看）",
            )

    def _paint_no_data(self, painter, rect: QRectF) -> None:
        painter.setPen(QColor(C["text_muted"]))
        painter.setFont(_font(11))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "该分析无数据")


__all__ = ["ChartNode"]
