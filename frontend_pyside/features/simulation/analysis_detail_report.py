from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)

from frontend_pyside.shared.plotting.analysis_metrics import key_metrics


_LABELS = {
    "center_offset_um": "中心偏移",
    "size_ratio_x": "X 尺寸比",
    "size_ratio_y": "Y 尺寸比",
    "ellipticity": "椭圆率",
    "coupling_efficiency_percent": "耦合效率",
    "system_efficiency_percent": "系统效率",
    "mode_overlap_efficiency": "模场效率",
    "fiber_to_x_waist_mm": "端面至 X 束腰",
    "fiber_to_y_waist_mm": "端面至 Y 束腰",
    "facet_spot_x_um": "端面 X 半径",
    "facet_spot_y_um": "端面 Y 半径",
    "target_radius_um": "目标模场半径",
    "rms_spot_radius_um": "RMS 光斑半径",
    "airy_radius_um": "艾里斑半径",
    "strehl_estimate_marechal": "Strehl 估计",
    "propagation_edge_power_fraction": "边缘功率占比",
}

_UNITS = {
    "center_offset_um": "μm",
    "coupling_efficiency_percent": "%",
    "system_efficiency_percent": "%",
    "mode_overlap_efficiency": "%",
    "fiber_to_x_waist_mm": "mm",
    "fiber_to_y_waist_mm": "mm",
    "facet_spot_x_um": "μm",
    "facet_spot_y_um": "μm",
    "target_radius_um": "μm",
    "rms_spot_radius_um": "μm",
    "airy_radius_um": "μm",
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any, unit: str = "") -> str:
    number = _finite(value)
    if number is None:
        text = str(value) if value not in (None, "") else "—"
    else:
        magnitude = abs(number)
        if magnitude and (magnitude >= 1e5 or magnitude < 1e-4):
            text = f"{number:.5e}"
        else:
            text = f"{number:.6g}"
    return f"{text} {unit}".strip() if text != "—" and unit else text


def _as_array(value: Any) -> np.ndarray:
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return np.asarray([], dtype=float)


class _MetricGroup(QFrame):
    def __init__(self, title: str, rows: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisDetailGroup")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)
        heading = QLabel(title, self)
        heading.setObjectName("analysisDetailGroupTitle")
        root.addWidget(heading)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(5)
        for index, (name, value) in enumerate(rows):
            label = QLabel(str(name), self)
            label.setObjectName("analysisDetailName")
            number = QLabel(str(value), self)
            number.setObjectName("analysisDetailValue")
            number.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, index, 0)
            grid.addWidget(number, index, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)


class AnalysisDetailReport(QScrollArea):
    """Zemax-style data report for one analysis result.

    The overview canvas and this report are deliberately separate views.  The
    report never embeds the main plot.  It only presents real values already in
    the result payload plus deterministic statistics derived from those values.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisDetailReport")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget(self)
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(2, 2, 6, 14)
        self._layout.setSpacing(10)
        self._group_grid: QGridLayout | None = None
        self._group_grid_count = 0
        self.setWidget(self._content)
        self.set_data({})

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater() alone can leave the old report visible for one
                # event turn while the new report is already inserted, producing
                # doubled/overlapping titles during rapid result refreshes.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._group_grid = None
        self._group_grid_count = 0

    def _ensure_group_grid(self) -> QGridLayout:
        if self._group_grid is not None:
            return self._group_grid
        host = QWidget(self._content)
        host.setObjectName("analysisDetailSummaryGrid")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        self._layout.addWidget(host)
        self._group_grid = grid
        self._group_grid_count = 0
        return grid

    def _add_group(self, title: str, rows: Sequence[tuple[str, Any]]) -> None:
        clean = [(str(name), str(value)) for name, value in rows if str(name).strip() and str(value).strip()]
        if not clean:
            return
        grid = self._ensure_group_grid()
        index = self._group_grid_count
        grid.addWidget(_MetricGroup(title, clean, self._content), index // 3, index % 3)
        self._group_grid_count += 1

    def _add_note(self, text: str) -> None:
        value = str(text or "").strip()
        if not value:
            return
        # Notes are provenance/context, not a peer metric card. Keep them as one
        # compact line so the summary grid can devote its height to real data.
        note = QLabel(value, self._content)
        note.setObjectName("analysisDetailHint")
        note.setWordWrap(True)
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(note)

    def _add_table(self, title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]], *, note: str = "") -> None:
        if not rows:
            return
        # Tables are page-level result data. End the current compact summary grid
        # so dense metric groups stay beside one another while wide tabular data
        # can use the full report width.
        self._group_grid = None
        self._group_grid_count = 0
        frame = QFrame(self._content)
        frame.setObjectName("analysisDetailGroup")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        heading = QLabel(title, frame)
        heading.setObjectName("analysisDetailGroupTitle")
        layout.addWidget(heading)
        table = QTableWidget(len(rows), len(headers), frame)
        table.setObjectName("analysisDetailTable")
        table.setHorizontalHeaderLabels([str(value) for value in headers])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setDefaultSectionSize(29)
        for r, row in enumerate(rows):
            for c, value in enumerate(row[: len(headers)]):
                item = QTableWidgetItem(str(value))
                if c > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c, item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        if headers:
            header.setStretchLastSection(True)
        # Let the outer report own vertical scrolling.  Large raw arrays are
        # intentionally summarized/capped before this point.
        height = table.horizontalHeader().sizeHint().height() + 2 + len(rows) * 29
        table.setFixedHeight(max(86, min(height, 3000)))
        layout.addWidget(table)
        if note:
            hint = QLabel(note, frame)
            hint.setObjectName("analysisDetailHint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self._layout.addWidget(frame)

    def set_data(self, data: Mapping[str, Any] | None) -> None:
        self._clear()
        payload = dict(data or {})
        kind = str(payload.get("kind", "empty") or "empty")
        title = str(payload.get("title", "详细数据") or "详细数据")
        source = str(payload.get("source", "待计算") or "待计算")

        header = QFrame(self._content)
        header.setObjectName("analysisDetailHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 9, 12, 9)
        h.setSpacing(10)
        name = QLabel(title, header)
        name.setObjectName("analysisDetailTitle")
        h.addWidget(name)
        h.addStretch(1)
        provenance = QLabel(f"数据来源：{source}", header)
        provenance.setObjectName("analysisDetailSource")
        provenance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(provenance)
        self._layout.addWidget(header)

        if kind == "empty":
            # Empty detailed views should not look like a giant blank report.
            # Keep one compact status card near the top/center while preserving
            # the rule that detailed mode never repeats the overview plot.
            wrapper = QWidget(self._content)
            row = QHBoxLayout(wrapper)
            row.setContentsMargins(24, 18, 24, 0)
            row.addStretch(1)
            card = QFrame(wrapper)
            card.setObjectName("analysisDetailGroup")
            card.setMaximumWidth(560)
            card.setMinimumWidth(360)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(7)
            empty_title = QLabel("当前没有可显示的详细数据", card)
            empty_title.setObjectName("analysisDetailGroupTitle")
            card_layout.addWidget(empty_title)
            message = QLabel(str(payload.get("message", "当前结果尚未计算。") or "当前结果尚未计算。"), card)
            message.setObjectName("analysisDetailEmpty")
            message.setWordWrap(True)
            card_layout.addWidget(message)
            hint = QLabel("完成对应分析后，这里会显示专业指标、统计信息和完整数值数据。", card)
            hint.setObjectName("analysisDetailHint")
            hint.setWordWrap(True)
            card_layout.addWidget(hint)
            row.addWidget(card)
            row.addStretch(1)
            self._layout.addWidget(wrapper)
            self._layout.addStretch(1)
            return

        description = str(payload.get("description", "") or "").strip()
        if description:
            self._add_note(description)

        explicit = key_metrics(payload)
        if explicit:
            self._add_group("关键指标", explicit)

        if kind in {"raytrace", "raytrace3d", "optical_scene_3d"}:
            self._raytrace_report(payload)
        elif kind == "scatter":
            self._scatter_report(payload)
        elif kind in {"heatmap", "heatmap_pair"}:
            self._heatmap_report(payload)
        elif kind in {"line", "line_multi"}:
            self._line_report(payload)
        elif kind == "profile_pair":
            self._profile_report(payload)
        elif kind == "beam_match":
            self._beam_match_report(payload)
        elif kind == "waist_position":
            self._waist_report(payload)
        elif kind in {"bar", "barh"}:
            self._bar_report(payload)
        else:
            self._generic_report(payload)

        self._layout.addStretch(1)

    def _raytrace_report(self, data: Mapping[str, Any]) -> None:
        rays = [dict(item) for item in list(data.get("rays", []) or []) if isinstance(item, Mapping)]
        surfaces = [dict(item) for item in list(data.get("surfaces", []) or []) if isinstance(item, Mapping)]
        path_points = sum(min(len(list(ray.get("x", []) or [])), len(list(ray.get("y", []) or [])), len(list(ray.get("z", []) or []))) for ray in rays)
        self._add_group("追迹统计", [("有效光线", str(len(rays))), ("启用表面", str(len(surfaces))), ("路径采样点", str(path_points))])
        surface_rows = []
        for index, surface in enumerate(surfaces[:100], 1):
            surface_rows.append([
                index,
                _fmt(surface.get("z"), "mm"),
                _fmt(surface.get("aperture"), "mm"),
                _fmt(surface.get("decenter_x"), "mm"),
                _fmt(surface.get("decenter_y"), "mm"),
            ])
        self._add_table("表面几何", ["序号", "Z", "半口径", "X 偏心", "Y 偏心"], surface_rows)
        ray_rows = []
        for index, ray in enumerate(rays[:100], 1):
            xs = list(ray.get("x", []) or []); ys = list(ray.get("y", []) or []); zs = list(ray.get("z", []) or [])
            count = min(len(xs), len(ys), len(zs))
            if count <= 0:
                continue
            ray_rows.append([index, count, _fmt(xs[0], "mm"), _fmt(ys[0], "mm"), _fmt(zs[0], "mm"), _fmt(xs[count-1], "mm"), _fmt(ys[count-1], "mm"), _fmt(zs[count-1], "mm")])
        note = "仅列出前 100 条光线；完整光线数据请使用“导出数据”。" if len(rays) > 100 else ""
        self._add_table("逐光线摘要", ["光线", "点数", "X 起", "Y 起", "Z 起", "X 终", "Y 终", "Z 终"], ray_rows, note=note)

    def _scatter_report(self, data: Mapping[str, Any]) -> None:
        x = _as_array(data.get("x", [])).reshape(-1); y = _as_array(data.get("y", [])).reshape(-1)
        n = min(len(x), len(y)); x = x[:n]; y = y[:n]
        finite = np.isfinite(x) & np.isfinite(y)
        x = x[finite]; y = y[finite]
        if not len(x):
            return
        cx = float(np.mean(x)); cy = float(np.mean(y)); radius = np.hypot(x-cx, y-cy)
        self._add_group("点列统计", [("有效点数", str(len(x))), ("质心 X", _fmt(cx)), ("质心 Y", _fmt(cy)), ("RMS 半径", _fmt(float(np.sqrt(np.mean(radius**2))))), ("最大半径", _fmt(float(np.max(radius))))])
        rows = [[i+1, _fmt(xx), _fmt(yy), _fmt(rr)] for i, (xx, yy, rr) in enumerate(zip(x[:100], y[:100], radius[:100]))]
        self._add_table("逐点数据", ["序号", "X", "Y", "半径"], rows, note="仅列出前 100 个有效点。" if len(x) > 100 else "")

    def _heatmap_report(self, data: Mapping[str, Any]) -> None:
        z = _as_array(data.get("z", []))
        if z.ndim == 2 and z.size:
            finite = z[np.isfinite(z)]
            rows = [("网格", f"{z.shape[0]} × {z.shape[1]}")]
            if finite.size:
                rows += [("最小值", _fmt(float(np.min(finite)))), ("最大值", _fmt(float(np.max(finite)))), ("均值", _fmt(float(np.mean(finite)))), ("RMS", _fmt(float(np.sqrt(np.mean(finite**2)))))]
            x = _as_array(data.get("x", [])).reshape(-1); y = _as_array(data.get("y", [])).reshape(-1)
            if len(x): rows.append(("X 范围", f"{_fmt(x[0])} ～ {_fmt(x[-1])}"))
            if len(y): rows.append(("Y 范围", f"{_fmt(y[0])} ～ {_fmt(y[-1])}"))
            self._add_group("二维数据统计", rows)
            center_row = z[z.shape[0] // 2]
            sample_x = x if len(x) == len(center_row) else np.arange(len(center_row), dtype=float)
            table_rows = [[_fmt(xx), _fmt(zz)] for xx, zz in zip(sample_x[:100], center_row[:100])]
            self._add_table("中心行数值", [str(data.get("x_label", "X")), "数值"], table_rows, note="中心行超过 100 点时仅显示前 100 点；完整二维数组请使用导出数据。" if len(center_row) > 100 else "")
        if str(data.get("kind")) == "heatmap_pair":
            z2 = _as_array(data.get("z2", []))
            if z2.ndim == 2 and z2.size:
                finite2 = z2[np.isfinite(z2)]
                self._add_group("第二数据场", [("网格", f"{z2.shape[0]} × {z2.shape[1]}"), ("最小值", _fmt(float(np.min(finite2))) if finite2.size else "—"), ("最大值", _fmt(float(np.max(finite2))) if finite2.size else "—")])

    def _line_report(self, data: Mapping[str, Any]) -> None:
        x = _as_array(data.get("x", [])).reshape(-1)
        series: list[tuple[str, np.ndarray]] = []
        if str(data.get("kind")) == "line":
            series.append((str(data.get("y_label", "Y")), _as_array(data.get("y", [])).reshape(-1)))
        else:
            for item in list(data.get("series", []) or []):
                if isinstance(item, Mapping):
                    series.append((str(item.get("label", "序列")), _as_array(item.get("y", [])).reshape(-1)))
        stats = [("采样点", str(len(x)))]
        if len(x): stats.append(("X 范围", f"{_fmt(x[0])} ～ {_fmt(x[-1])}"))
        for label, values in series[:6]:
            finite = values[np.isfinite(values)]
            if finite.size:
                stats.append((f"{label} 范围", f"{_fmt(float(np.min(finite)))} ～ {_fmt(float(np.max(finite)))}"))
        self._add_group("曲线数据统计", stats)
        if len(x) and series:
            max_n = min([len(x), *(len(values) for _, values in series)])
            headers = [str(data.get("x_label", "X"))] + [label for label, _ in series]
            rows = []
            for i in range(min(max_n, 100)):
                rows.append([_fmt(x[i])] + [_fmt(values[i]) for _, values in series])
            self._add_table("采样数据", headers, rows, note="仅显示前 100 个采样点；完整曲线可直接导出。" if max_n > 100 else "")

    def _profile_report(self, data: Mapping[str, Any]) -> None:
        x_axis = _as_array(data.get("x_axis", [])).reshape(-1); y_axis = _as_array(data.get("y_axis", [])).reshape(-1)
        rows = [("X 截面采样", str(len(x_axis))), ("Y 截面采样", str(len(y_axis)))]
        self._add_group("截面数据", rows)
        for title, axis, key in (("X 截面", x_axis, "x_series"), ("Y 截面", y_axis, "y_series")):
            series = [item for item in list(data.get(key, []) or []) if isinstance(item, Mapping)]
            if not series or not len(axis):
                continue
            headers = ["位置"] + [str(item.get("label", "序列")) for item in series]
            values = [_as_array(item.get("y", [])).reshape(-1) for item in series]
            n = min([len(axis), *(len(v) for v in values)])
            table = [[_fmt(axis[i])] + [_fmt(v[i]) for v in values] for i in range(min(n, 80))]
            self._add_table(title, headers, table, note="仅显示前 80 点。" if n > 80 else "")

    def _beam_match_report(self, data: Mapping[str, Any]) -> None:
        metrics = dict(data.get("metrics", {}) or {})
        metric_rows = []
        for key, value in metrics.items():
            number = _finite(value)
            if number is None:
                continue
            unit = _UNITS.get(str(key), "")
            if unit == "%" and 0.0 <= number <= 1.0:
                number *= 100.0
            metric_rows.append((_LABELS.get(str(key), str(key)), _fmt(number, unit)))
        self._add_group("匹配指标", metric_rows)
        incident = list(data.get("incident_center", []) or []); fiber = list(data.get("fiber_center", []) or [])
        ir = list(data.get("incident_radius", []) or []); tr = list(data.get("target_radius", []) or [])
        geometry = []
        if len(incident) >= 2: geometry += [("入射中心 X", _fmt(incident[0], "μm")), ("入射中心 Y", _fmt(incident[1], "μm"))]
        if len(fiber) >= 2: geometry += [("光纤中心 X", _fmt(fiber[0], "μm")), ("光纤中心 Y", _fmt(fiber[1], "μm"))]
        if len(ir) >= 2: geometry += [("入射半径 X", _fmt(ir[0], "μm")), ("入射半径 Y", _fmt(ir[1], "μm"))]
        if len(tr) >= 2: geometry += [("目标半径 X", _fmt(tr[0], "μm")), ("目标半径 Y", _fmt(tr[1], "μm"))]
        self._add_group("几何与尺寸", geometry)
        original = list(data.get("original_shape", []) or []); preview = list(data.get("preview_shape", []) or [])
        sampling = []
        if len(original) >= 2: sampling.append(("原始网格", f"{original[0]} × {original[1]}"))
        if len(preview) >= 2: sampling.append(("显示网格", f"{preview[0]} × {preview[1]}"))
        self._add_group("采样信息", sampling)

    def _waist_report(self, data: Mapping[str, Any]) -> None:
        metrics = dict(data.get("metrics", {}) or {})
        rows = [(_LABELS.get(str(k), str(k)), _fmt(v, _UNITS.get(str(k), ""))) for k, v in metrics.items() if _finite(v) is not None]
        self._add_group("束腰参数", rows)
        points = []
        for item in list(data.get("waist_points", []) or []):
            if isinstance(item, Mapping):
                points.append([str(item.get("label", "束腰")), _fmt(item.get("z"), "mm"), _fmt(item.get("w"), "μm")])
        self._add_table("束腰位置", ["方向", "Z", "半径"], points)
        self._line_report(data)

    def _bar_report(self, data: Mapping[str, Any]) -> None:
        labels = list(data.get("labels", []) or []); values = list(data.get("values", []) or [])
        rows = [[str(label), _fmt(value)] for label, value in zip(labels, values)]
        self._add_table("数值明细", ["项目", "数值"], rows)

    def _generic_report(self, data: Mapping[str, Any]) -> None:
        rows = []
        ignored = {"x", "y", "z", "z1", "z2", "series", "x_series", "y_series", "rays", "surfaces", "contour", "x_profiles", "y_profiles"}
        for key, value in data.items():
            if key in ignored or isinstance(value, (Mapping, list, tuple, np.ndarray)):
                continue
            if value in (None, ""):
                continue
            rows.append((str(key), str(value)))
        self._add_group("结果字段", rows[:40])


__all__ = ["AnalysisDetailReport"]
