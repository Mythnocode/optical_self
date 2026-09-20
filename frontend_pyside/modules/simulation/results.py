"""仿真正式结果文档。

本模块把工程上下文中的正式计算结果转换为可显示的结果工作区，并负责：

* 根据页面 ``kind`` 选择指标和绘图数据；
* 在工程修改后标记旧结果，避免用户误把过期结果当成当前结果；
* 对光路图追加用户探测器示意对象；
* 提供文字查看、独立窗口放大和 PNG 导出操作。

具体的光学计算和结果适配仍由 ``features.simulation`` 完成，本模块不重新
计算物理量，只做 Qt 页面生命周期和展示层适配。
"""

from __future__ import annotations

import math

import numpy as np

from frontend_pyside.modules import shared as _shared
from frontend_pyside.shared.plotting.optical_scene_geometry import (
    build_beam_envelope,
    focus_from_envelope,
)

globals().update(
    {
        name: value
        for name, value in vars(_shared).items()
        if not name.startswith("__")
    }
)

# 每种结果类型按照优先级列出可接受的绘图键；前面的键优先使用。
RESULT_PLOT_KEYS: dict[str, tuple[str, ...]] = {
    "ray_layout": ("光路",),
    "layout_3d": ("3D光路",),
    "spot": ("点列图",),
    "coupling": ("端面匹配", "模式重叠", "耦合图", "能量分解"),
    "wavefront": ("波前", "PSF"),
}

# 供工作台或结果查看器使用的正式结果视图名称集合。
FORMAL_RESULT_VIEWS: tuple[str, ...] = (
    "光路", "3D光路", "点列图", "PSF", "波前", "端面匹配"
)

class ResultDocument(QWidget):
    """一个正式分析结果文档，外层工作台不再重复创建结果工具栏。"""

    relatedRequested = Signal(str)

    def __init__(self, context, kind: str, parent=None) -> None:
        """创建结果页，并订阅正式结果和指标变化信号。"""
        super().__init__(parent)
        self.context = context
        self.kind = kind
        self._result_revision = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        # 页眉只显示结果来源和必要的关联视图入口。
        header = QHBoxLayout()
        # 三个效率标签放在左侧，正式结果到达后由指标信号实时刷新。
        self.sys_coup = QLabel("系统效率：—")
        self.sys_coup.setObjectName("coup")
        self.rec_coup = QLabel("端面接收效率：—")
        self.rec_coup.setObjectName("coup")
        self.tot_coup = QLabel("总耦合效率：—")
        self.tot_coup.setObjectName("coup")
        for label in (self.sys_coup, self.rec_coup, self.tot_coup):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.addWidget(label)

        source = QLabel("光学仿真结果未生成")
        source.setObjectName("ResultSource")
        # 让三个效率标签和右侧“已计算”状态标签保持相同高度。
        status_height = source.sizeHint().height()
        source.setFixedHeight(status_height)
        for label in (self.sys_coup, self.rec_coup, self.tot_coup):
            label.setFixedHeight(status_height)
        header.addStretch(1)
        header.addWidget(source)
        if kind == "ray_layout":
            # 3D 光路与 2D 光路共用同一份正式结果，因此只作为关联视图打开。
            view3d = QToolButton()
            view3d.setText("3D 视图")
            view3d.setToolTip("系统三维光路；仿真示意图不画镜头")
            view3d.clicked.connect(lambda: self.relatedRequested.emit("layout_3d"))
            header.addWidget(view3d)
        root.addLayout(header)
        # 隐藏通用工作区的多余工具栏，把页面控制权收敛到本模块底部按钮。
        self.workspace = LazyResultWorkspace(self)
        self.workspace.set_single_view_only(True)
        self.workspace.set_toolbar_visible(False)
        self.workspace.set_pane_header_visible(False)
        self.workspace.set_pane_source_visible(False)
        self.workspace.set_plot_tools_visible(False)
        self.workspace.set_maximize_controls_visible(False)
        self.workspace.set_footer_visible(False)
        root.addWidget(self.workspace, 1)
        action_row = QHBoxLayout()
        self.text_button = QPushButton("文字")
        self.zoom_button = QPushButton("放大")
        self.export_button = QPushButton("导出")
        action_row.addStretch(1)
        action_row.addWidget(self.text_button)
        action_row.addWidget(self.zoom_button)
        action_row.addWidget(self.export_button)
        root.addLayout(action_row)
        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._text.setObjectName("DocumentText")
        self._text.hide()
        root.addWidget(self._text)
        self.text_button.clicked.connect(lambda: self._text.setVisible(not self._text.isVisible()))
        self.zoom_button.clicked.connect(self._open_plot_window)
        self.export_button.clicked.connect(self._export_plot)
        # 保存最近一次绘图载荷，供放大窗口和导出操作复用。
        self._last_plot: dict[str, Any] = {"kind": "empty", "message": ""}
        self._sync_export_enabled()
        # 正式结果到达时刷新图表；工程指标变化时刷新页内摘要。
        context.project.formal_result_changed.connect(self._result_changed)
        context.project.metrics_changed.connect(lambda _metrics: self._refresh_metrics())
        self._refresh_metrics()
        existing = getattr(context.project, "formal_result", None)
        if isinstance(existing, dict) and existing:
            self._result_changed(existing)
        else:
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        """在尚未生成正式结果时显示占位信息。"""
        self._set_source("等待计算结果")
        self._update_header_metrics({})
        self._last_plot = {"kind": "empty", "message": "提交计算后，这里显示对应结果。"}
        self.workspace.set_result(0, "等待结果", self._last_plot)
        self._sync_export_enabled()

    def _result_changed(self, result: object) -> None:
        """接收新的正式结果，并更新指标、图表和文字详情。"""
        if not isinstance(result, dict) or not result:
            # 空结果代表计算被清空或尚未完成，回到统一占位状态。
            self._show_placeholder()
            return
        metrics = dict(result.get("metrics") or {})
        arrays = dict(result.get("arrays") or {})
        self._result_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        self._set_source("已计算")
        self._update_header_metrics(metrics, arrays=arrays)
        # 先把后端结果转换为绘图载荷，再交给懒加载工作区渲染。
        data = self._result_plot(result)
        self._last_plot = data
        self.workspace.set_result(0, _kind_titles("simulation", self.kind)[0], data)
        self._text.setText(self._detail_text(result))
        self._sync_export_enabled()

    def refresh(self) -> None:
        """刷新指标，并在工程修改后标记正式结果过期。"""
        self._refresh_metrics()
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        if self._result_revision and current_revision != self._result_revision:
            self.mark_stale()

    def mark_stale(self) -> None:
        """当结果对应的设计版本落后于当前工程时更新过期提示。"""
        current_revision = int(getattr(self.context.project, "design_revision", 0) or 0)
        if not self._result_revision or current_revision == self._result_revision:
            return
        self._set_source("当前系统已修改 · 需重新计算")

    def _set_source(self, text: str) -> None:
        """更新页眉中的结果来源，并刷新其过期状态样式。"""
        source = self.findChild(QLabel, "ResultSource")
        if source is not None:
            source.setText(text)
            source.setProperty("stale", str(text).startswith("当前系统已修改"))
            source.style().unpolish(source)
            source.style().polish(source)

    def _refresh_metrics(self) -> None:
        """从项目上下文读取当前指标并更新指标标签。"""
        formal_result = getattr(self.context.project, "formal_result", None)
        if isinstance(formal_result, dict) and formal_result:
            metrics = dict(formal_result.get("metrics") or {})
            arrays = dict(formal_result.get("arrays") or {})
            self._update_header_metrics(metrics, arrays=arrays)
            return
        metrics = dict(getattr(self.context.project.project, "metrics", {}) or {})
        self._update_header_metrics(metrics)

    def _result_plot(self, result: dict[str, Any]) -> dict[str, Any]:
        """根据页面 kind 选择并生成第一个可用的绘图载荷。"""
        keys = RESULT_PLOT_KEYS.get(self.kind, ())
        try:
            project = serialize_project(self.context.project.project)
        except Exception:
            project = {}
        # The active calculation settings are stored in the submitted project
        # snapshot.  Merge them back here because the result document is opened
        # after submission and otherwise serialize_project() has no form state.
        stored_payload = getattr(self.context.project, "simulation_project_payload", {})
        if callable(stored_payload):
            stored_payload = stored_payload()
        if isinstance(stored_payload, dict):
            stored_settings = stored_payload.get("analysis_settings")
            if isinstance(stored_settings, dict):
                project["analysis_settings"] = {
                    **dict(project.get("analysis_settings") or {}),
                    **stored_settings,
                }
        # 结果适配器负责处理后端格式差异，本页面只指定需要的绘图类别。
        plots = formal_result_to_plots(result, project, requested_keys=set(keys))
        for key in keys:
            payload = plots.get(key)
            if isinstance(payload, dict) and str(payload.get("kind", "empty")) != "empty":
                # 只使用当前页面的第一份有效图表，保持工作区单视图模式。
                return self._apply_detector_overlay(payload)
        message = "正式结果已返回，但当前页暂未找到可绘制的数据。"
        diagnostics = formal_result_diagnostics(result)
        if diagnostics:
            message = f"{message}\n{diagnostics}"
        return {"kind": "empty", "message": message}

    def _apply_detector_overlay(self, payload: dict[str, Any]) -> dict[str, Any]:
        """为光路类结果追加用户探测器示意对象，不修改原始载荷。"""
        if self.kind not in {"ray_layout", "layout_3d"}:
            return payload
        overlay = _user_detector_object(self, payload)
        # 复制字典和对象列表，避免污染缓存中的后端结果。
        copied = dict(payload)
        objects = [
            dict(item)
            for item in payload.get("objects") or []
            if isinstance(item, dict) and not dict(item.get("metadata") or {}).get("user_detector")
        ]
        if overlay is not None:
            # 用户探测器只作为显示覆盖层，不参与已经完成的正式计算。
            objects.append(overlay)
        copied["objects"] = objects
        return copied

    def _detail_text(self, result: dict[str, Any]) -> str:
        """组织结果来源、状态和诊断信息，供“文字”按钮查看。"""
        lines = [
            f"结果来源：{result.get('source', '正式计算')}",
            f"状态：{result.get('status', '—')}",
            formal_result_diagnostics(result),
        ]
        return "\n".join(item for item in lines if item)

    def _open_plot_window(self) -> None:
        """在独立窗口中打开当前图表，便于放大查看。"""
        window = QWidget(self, Qt.WindowType.Window)
        window.setWindowTitle(f"{_kind_titles('simulation', self.kind)[0]} · 独立窗口")
        window.resize(900, 620)
        layout = QVBoxLayout(window)
        # 独立窗口只读取当前缓存载荷，不重新触发计算或后端请求。
        view = LazyResultWorkspace(window)
        view.set_single_view_only(True)
        view.set_result(0, _kind_titles("simulation", self.kind)[0], self._last_plot)
        layout.addWidget(view, 1)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.show()
        self._plot_window = window

    def _sync_export_enabled(self) -> None:
        """仅在存在有效绘图载荷时启用导出按钮。"""
        plot = dict(getattr(self, "_last_plot", {}) or {})
        self.export_button.setEnabled(str(plot.get("kind") or "empty") != "empty")

    def _export_plot(self) -> None:
        """将当前工作区图表导出为用户选择路径下的 PNG 文件。"""
        figure = getattr(self.workspace, "figure", None)
        if figure is None or str((self._last_plot or {}).get("kind") or "empty") == "empty":
            # 没有有效结果时禁止导出，避免生成空白文件或抛出绘图库异常。
            self.export_button.setEnabled(False)
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出结果", "analysis_result.png", "PNG 图像 (*.png)")
        if not path:
            # 用户取消保存对话框时不改变当前页面状态。
            return
        figure.savefig(path, dpi=220, bbox_inches="tight")
    @staticmethod
    def _format_efficiency(value: Any) -> str:
        try:
            return f"{float(value) * 100:.2f}%"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _format_number(value: Any, *, suffix: str = "", digits: int = 2) -> str:
        """Format optional result metrics without applying numeric formatting to placeholders."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        if not math.isfinite(number):
            return "—"
        return f"{number:.{digits}f}{suffix}"

    @staticmethod
    def _metric_value(metrics: dict[str, Any], *names: str) -> Any:
        """Read a metric from both flat and analysis-namespaced result payloads."""
        for name in names:
            if name in metrics and metrics[name] is not None:
                return metrics[name]
            suffix = f".{name}"
            matches = [
                value
                for key, value in metrics.items()
                if str(key).endswith(suffix) and value is not None
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    @staticmethod
    def _numeric_array(value: Any, *, ndim: int | None = None) -> np.ndarray | None:
        """Return a numeric array while treating lazy descriptors as unavailable."""
        if value is None or isinstance(value, dict):
            return None
        try:
            array = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            return None
        if not array.size or (ndim is not None and array.ndim != ndim):
            return None
        return array

    @classmethod
    def _peak_position_text(cls, metrics: dict[str, Any], arrays: dict[str, Any]) -> str:
        """Read or derive the PSF peak coordinate for the spot header."""
        direct = cls._metric_value(metrics, "peak_position", "psf_peak_position")
        if isinstance(direct, dict):
            x_value = direct.get("x_um", direct.get("x_mm"))
            y_value = direct.get("y_um", direct.get("y_mm"))
            try:
                x = float(x_value)
                y = float(y_value)
                if "x_mm" in direct:
                    x *= 1000.0
                if "y_mm" in direct:
                    y *= 1000.0
                if math.isfinite(x) and math.isfinite(y):
                    return f"x={x:.2f} μm, y={y:.2f} μm"
            except (TypeError, ValueError):
                pass
        elif direct is not None:
            text = str(direct).strip()
            if text:
                return text

        peak_x = cls._metric_value(metrics, "psf_peak_x_um", "peak_x_um")
        peak_y = cls._metric_value(metrics, "psf_peak_y_um", "peak_y_um")
        try:
            x = float(peak_x)
            y = float(peak_y)
            if math.isfinite(x) and math.isfinite(y):
                return f"x={x:.2f} μm, y={y:.2f} μm"
        except (TypeError, ValueError):
            pass

        intensity = None
        for name in ("hybrid_psf_intensity", "psf_intensity", "diffraction_intensity"):
            candidate = cls._numeric_array(arrays.get(name), ndim=2)
            if candidate is not None:
                intensity = candidate
                break
        if intensity is None:
            # Spot-only results may not contain a PSF grid. Estimate the
            # densest spot cell so the header remains useful in that mode.
            points = cls._numeric_array(arrays.get("spot_points_um"), ndim=2)
            if points is None:
                x_points = cls._numeric_array(arrays.get("spot_x_um"), ndim=1)
                y_points = cls._numeric_array(arrays.get("spot_y_um"), ndim=1)
                if x_points is not None and y_points is not None and len(x_points) == len(y_points):
                    points = np.column_stack((x_points, y_points))
            if points is None or points.shape[1] != 2:
                return "—"
            points = points[np.all(np.isfinite(points), axis=1)]
            if not len(points):
                return "—"
            if len(points) == 1:
                x, y = (float(value) for value in points[0])
                return f"x={x:.2f} μm, y={y:.2f} μm"
            bins = max(8, min(32, int(np.sqrt(len(points)) * 2.0)))
            weights = cls._numeric_array(arrays.get("spot_integration_weights"), ndim=1)
            if weights is not None and len(weights) == len(points):
                weights = np.maximum(np.nan_to_num(weights, nan=0.0), 0.0)
            else:
                weights = None
            try:
                histogram, x_edges, y_edges = np.histogram2d(
                    points[:, 0], points[:, 1], bins=bins, weights=weights
                )
                cell_x, cell_y = np.unravel_index(int(np.argmax(histogram)), histogram.shape)
                in_cell = (
                    (points[:, 0] >= x_edges[cell_x])
                    & (points[:, 0] <= x_edges[cell_x + 1])
                    & (points[:, 1] >= y_edges[cell_y])
                    & (points[:, 1] <= y_edges[cell_y + 1])
                )
                selected = points[in_cell]
                if not len(selected):
                    selected = points
                x = float(np.mean(selected[:, 0]))
                y = float(np.mean(selected[:, 1]))
                return f"x={x:.2f} μm, y={y:.2f} μm"
            except (TypeError, ValueError):
                return "—"

        x_candidates = [
            cls._numeric_array(arrays.get(name), ndim=1)
            for name in ("detector_grid_x_mm", "coupling_grid_x_mm", "psf_x_mm")
        ]
        y_candidates = [
            cls._numeric_array(arrays.get(name), ndim=1)
            for name in ("detector_grid_y_mm", "coupling_grid_y_mm", "psf_y_mm")
        ]
        axis_x = next(
            (axis for axis in x_candidates if axis is not None and len(axis) == intensity.shape[1]),
            None,
        )
        axis_y = next(
            (axis for axis in y_candidates if axis is not None and len(axis) == intensity.shape[0]),
            None,
        )
        if axis_x is None or axis_y is None:
            return "—"

        finite = np.isfinite(intensity)
        if not np.any(finite):
            return "—"
        safe_intensity = np.where(finite, intensity, -np.inf)
        row, column = np.unravel_index(int(np.argmax(safe_intensity)), intensity.shape)
        x = float(axis_x[column]) * 1000.0
        y = float(axis_y[row]) * 1000.0
        if not (math.isfinite(x) and math.isfinite(y)):
            return "—"
        return f"x={x:.2f} μm, y={y:.2f} μm"

    @classmethod
    def _focus_position_text(cls, metrics: dict[str, Any], arrays: dict[str, Any]) -> str:
        """Read a focus-search result or derive focus from ray data."""
        direct = cls._metric_value(
            metrics,
            "best_focus_z_mm",
            "focus_position_z_mm",
            "focus_z_mm",
            "focus_position",
        )
        if isinstance(direct, dict):
            direct = direct.get("z_mm", direct.get("z"))
        try:
            z = float(direct)
            if math.isfinite(z):
                return f"z={z:.2f} mm"
        except (TypeError, ValueError):
            if direct is not None and str(direct).strip():
                return str(direct).strip()

        path_points = cls._numeric_array(arrays.get("raytrace_path_points_mm"), ndim=2)
        offsets = cls._numeric_array(arrays.get("raytrace_path_offsets"), ndim=1)
        if (
            path_points is not None
            and path_points.shape[1] == 3
            and offsets is not None
            and len(offsets) >= 3
        ):
            statuses = cls._numeric_array(arrays.get("raytrace_status_codes"), ndim=1)
            rays: list[dict[str, Any]] = []
            integer_offsets = offsets.astype(int)
            for index, (start, end) in enumerate(zip(integer_offsets[:-1], integer_offsets[1:])):
                if not (0 <= start < end <= len(path_points)):
                    continue
                status = int(statuses[index]) if statuses is not None and index < len(statuses) else 0
                rays.append({"points": path_points[start:end], "role": "failed" if status else ""})
            focus = focus_from_envelope(build_beam_envelope(rays))
            if isinstance(focus, dict):
                try:
                    z = float(focus.get("z"))
                    if math.isfinite(z):
                        return f"z={z:.2f} mm"
                except (TypeError, ValueError):
                    pass

        # Reduced result policies may omit full paths but retain final ray lines.
        positions = cls._numeric_array(arrays.get("raytrace_final_positions_mm"), ndim=2)
        directions = cls._numeric_array(arrays.get("raytrace_final_directions"), ndim=2)
        if (
            positions is None
            or directions is None
            or positions.shape != directions.shape
            or positions.shape[1] != 3
        ):
            return "—"
        valid_mask = cls._numeric_array(arrays.get("raytrace_valid_mask"), ndim=1)
        matrix = np.zeros((3, 3), dtype=float)
        vector = np.zeros(3, dtype=float)
        valid_count = 0
        for index, (position, direction) in enumerate(zip(positions, directions)):
            if valid_mask is not None and (index >= len(valid_mask) or valid_mask[index] <= 0.5):
                continue
            if not np.all(np.isfinite(position)) or not np.all(np.isfinite(direction)):
                continue
            norm = float(np.linalg.norm(direction))
            if norm <= 1.0e-12:
                continue
            unit = direction / norm
            projection = np.eye(3) - np.outer(unit, unit)
            matrix += projection
            vector += projection @ position
            valid_count += 1
        if valid_count < 2:
            return "—"
        try:
            focus = np.linalg.lstsq(matrix, vector, rcond=None)[0]
            z = float(focus[2])
        except (np.linalg.LinAlgError, TypeError, ValueError):
            return "—"
        return f"z={z:.2f} mm" if math.isfinite(z) else "—"

    def _update_header_metrics(
        self,
        metrics: dict[str, Any],
        *,
        arrays: dict[str, Any] | None = None,
    ) -> None:
        """Update the compact metric header, including array-derived positions."""
        arrays = dict(arrays or {})
        if self.kind == "coupling":
            system_value = metrics.get("system_efficiency")
            if system_value is None:
                system_value = metrics.get("transmission_efficiency")
            receiver_value = metrics.get("receiver_efficiency")
            if receiver_value is None:
                receiver_value = metrics.get("receiving_efficiency")
            if receiver_value is None:
                receiver_value = metrics.get("fiber_interface_efficiency")
            total_value = metrics.get("total_coupling_efficiency")
            if total_value is None:
                total_value = metrics.get("total_efficiency")
            if total_value is None:
                total_value = metrics.get("coupling_efficiency")
            values = (
                f"系统效率：{self._format_efficiency(system_value)}",
                f"端面接收效率：{self._format_efficiency(receiver_value)}",
                f"总耦合效率：{self._format_efficiency(total_value)}",
            )
        elif self.kind == "spot":
            values = (
                f"光斑半径：{self._format_number(metrics.get('rms_spot_radius_um', metrics.get('rms_um')), suffix=' μm')}",
                f"峰值位置：{self._peak_position_text(metrics, arrays)}",
                None,
            )
        elif self.kind == "ray_layout":
            values = (
                f"光线数量：{metrics.get('ray_count', '—')}",
                f"聚焦位置：{self._focus_position_text(metrics, arrays)}",
                None,
            )
        elif self.kind == "wavefront":
            values = (
                f"波前 RMS：{self._format_number(self._metric_value(metrics, 'wavefront_rms_nm', 'wavefront_rms'), suffix=' nm')}",
                f"斯特列尔：{self._format_number(self._metric_value(metrics, 'strehl_estimate_marechal', 'strehl', 'strehl_ratio', 'wavefront_strehl'))}",
                None,
            )
        elif self.kind == "layout_3d":
            values = ("三维视图", None, None)
        else:
            values = ("—", None, None)

        labels = (self.sys_coup, self.rec_coup, self.tot_coup)
        for label, value in zip(labels, values):
            if value is None:
                label.hide()
            else:
                label.setText(value)
                label.show()


__all__ = ["ResultDocument"]
