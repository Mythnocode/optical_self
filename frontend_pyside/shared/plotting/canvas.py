"""Matplotlib 图表画布和绘图类型分发器。

``PlotCanvas`` 是非快速热图结果的统一入口。它不关心仿真页面名称，只根据
绘图载荷中的 ``kind`` 选择 2D 曲线、热图、光路图、3D 场景或诊断图的绘制
分支。具体 2D/3D 绘制实现通过 Mixin 拆分到 ``canvas_parts`` 目录。
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import numpy as np
from matplotlib import rcParams
from cycler import cycler
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QSizePolicy

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.performance import record_perf
from frontend_pyside.shared.components.safe_inputs import forward_wheel_to_page
from frontend_pyside.shared.font_fallback import matplotlib_font_config
from frontend_pyside.shared.plotting.canvas_3d_interaction import (
    Optical3DInteractionController,
)
from frontend_pyside.shared.plotting.canvas_view import (
    apply_optical_scene_3d_zoom,
    fit_optical_scene_3d,
    fit_optical_section_2d,
)
from frontend_pyside.shared.plotting.surface_hover_controller import SurfaceHoverController
from frontend_pyside.shared.plotting.scene_cache import DualQualitySceneCache

# 全局 Matplotlib 样式：字体、颜色、网格和图例的默认值集中在此处。
# 单个图需要特殊样式时，应在具体绘图函数中覆盖，而不是修改业务页面。
rcParams.update(
    {
        **matplotlib_font_config(),
        "font.size": 13.0,
        "axes.titlesize": 17.0,
        "axes.titleweight": "semibold",
        "axes.labelsize": 14.0,
        "xtick.labelsize": 12.0,
        "ytick.labelsize": 12.0,
        "legend.fontsize": 12.0,
        "axes.formatter.useoffset": False,
        "figure.facecolor": theme.CHART_BACKGROUND,
        "savefig.facecolor": theme.CHART_BACKGROUND,
        "axes.facecolor": theme.CHART_BACKGROUND,
        "axes.edgecolor": theme.CHART_AXIS,
        "axes.labelcolor": theme.CHART_AXIS,
        "axes.titlecolor": theme.TEXT_PRIMARY,
        "axes.prop_cycle": cycler(color=theme.CHART_SERIES),
        "text.color": theme.TEXT_PRIMARY,
        "xtick.color": theme.CHART_AXIS,
        "ytick.color": theme.CHART_AXIS,
        "grid.color": theme.CHART_GRID,
        "grid.alpha": 0.72,
        "legend.facecolor": theme.SURFACE,
        "legend.edgecolor": theme.BORDER,
        "legend.framealpha": 0.96,
    }
)


from frontend_pyside.shared.plotting.canvas_parts import Canvas2DMixin, Canvas3DMixin, CanvasInteractionMixin
from frontend_pyside.shared.plotting.canvas_parts.data_utils import _csv_cell, _csv_rows, _numeric_arrays, _scene_static_signature

class PlotCanvas(Canvas2DMixin, Canvas3DMixin, CanvasInteractionMixin, FigureCanvas):
    """承载 2D/3D Matplotlib 图形并负责结果 kind 分发。"""


    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    itemSelected = Signal(str)
    pointSelected = Signal(float, float)
    viewChanged = Signal()

    def __init__(self, parent=None):
        """创建 Figure、交互控制器、场景缓存和可复用绘图对象。"""
        self.figure = Figure(figsize=(5, 4), facecolor=theme.SCENE_BACKGROUND)
        self.figure.subplots_adjust(
            left=0.13,
            right=0.96,
            bottom=0.14,
            top=0.89,
            wspace=0.30,
            hspace=0.30,
        )
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.updateGeometry()
        self._data: dict = {}
        self._axis = None
        self._view_state: dict = {}
        self._scene_static_signature = None
        self._scene_layer_cache = DualQualitySceneCache()
        self._static_scene_artists = None
        self._dynamic_scene_artists = None
        self._interaction = Optical3DInteractionController(
            self,
            on_surface_selected=self.surfaceSelected.emit,
            on_surface_activated=self.surfaceActivated.emit,
        )
        self._hover = SurfaceHoverController(self)
        self._item_artists: list[tuple[object, str]] = []
        self._item_labels: list[str] = []
        self._reusable_2d_artists: list[object] = []
        self._reusable_2d_labels: list[str] = []
        self._heatmap_image = None
        self._heatmap_colorbar = None
        self._raytrace_surface_collection = None
        self._raytrace_rim_collection = None
        self._raytrace_ray_collections: dict[str, object] = {}
        self._raytrace_axis_line = None
        self._raytrace_scale_text = None
        self._raytrace_signature = None
        self.mpl_connect("scroll_event", self._on_scroll)
        self.mpl_connect("button_press_event", self._on_button_press)
        self.mpl_connect("motion_notify_event", self._on_motion)
        self.mpl_connect("button_release_event", self._on_button_release)
        self._pan_start = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        """页面中的普通滚轮只负责页面导航。

        图表缩放必须使用 Ctrl+滚轮；独立科研图窗可通过 freeWheelZoom 属性恢复
        普通滚轮缩放。这样用户滚动长页面时不会无意改变二维/三维结果视图。
        """
        free_zoom = bool(self.property("freeWheelZoom"))
        if free_zoom or bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(event)
            return
        forward_wheel_to_page(self, event)

    @property
    def data(self) -> dict:
        """返回当前绘图载荷的浅拷贝。"""
        return dict(self._data)

    def clear(self) -> None:
        """清空 Figure、交互状态、场景缓存和可复用 artist。"""
        self.figure.clear()
        self._axis = None
        self._scene_static_signature = None
        self._scene_layer_cache.clear()
        self._static_scene_artists = None
        self._dynamic_scene_artists = None
        self._interaction.clear()
        self._hover.clear()
        self._item_artists = []
        self._item_labels = []
        self._reusable_2d_artists = []
        self._reusable_2d_labels = []
        self._heatmap_image = None
        self._heatmap_colorbar = None
        self._raytrace_surface_collection = None
        self._raytrace_rim_collection = None
        self._raytrace_ray_collections: dict[str, object] = {}
        self._raytrace_axis_line = None
        self._raytrace_scale_text = None
        self._raytrace_signature = None
        self.draw_idle()

    @staticmethod
    def _apply_high_contrast_axes(figure: Figure) -> None:
        """统一设置坐标轴、标题、图例和网格的可读性样式。"""
        from matplotlib.ticker import ScalarFormatter

        axes = list(figure.axes)
        for axis in axes:
            axes.extend(child for child in axis.child_axes if child not in axes)
        for axis in axes:
            try:
                compact = bool(getattr(axis, "_compact_diagnostic_inset", False))
                
                axis.tick_params(
                    axis="both",
                    colors="#111827",
                    width=0.9 if compact else 1.3,
                    length=3 if compact else 5,
                    labelsize=7 if compact else 11,
                )
                axis.xaxis.label.set_color("#111827")
                axis.yaxis.label.set_color("#111827")
                axis.xaxis.label.set_fontsize(8 if compact else 13)
                axis.yaxis.label.set_fontsize(8 if compact else 13)
                axis.title.set_color("#111827")
                panel_title_size = getattr(axis, "_panel_title_size", None)
                axis.title.set_fontsize(panel_title_size or (9 if compact else 16))
                axis.title.set_fontweight("semibold")
                for spine in axis.spines.values():
                    spine.set_color("#111827")
                    spine.set_linewidth(1.35)
                for current_axis in (axis.xaxis, axis.yaxis):
                    formatter = current_axis.get_major_formatter()
                    if isinstance(formatter, ScalarFormatter):
                        formatter.set_useOffset(False)
                        formatter.set_scientific(False)
                legend = axis.get_legend()
                if legend is not None:
                    for text in legend.get_texts():
                        text.set_fontsize(11)
                        text.set_color("#111827")
                    legend.get_frame().set_edgecolor("#111827")
                    legend.get_frame().set_linewidth(0.9)
                    legend.get_frame().set_alpha(1.0)
                axis.grid(True, color=theme.CHART_GRID, alpha=0.48, linewidth=0.65)
            except Exception:
                continue

    def set_plot(self, data) -> None:
        """接收结构化绘图载荷并按 ``kind`` 创建或更新图形。

        更新顺序是：可复用 2D artist -> 可增量更新的 3D 场景 -> 完整重建。
        这个顺序兼顾了交互刷新速度和不同图类型之间的正确切换。
        """
        started = perf_counter()
        new_data = dict(data or {})
        new_kind = new_data.get("kind", "empty")
        if new_kind in {"optical_scene_3d", "raytrace3d"}:
            # 3D 场景先经过双质量缓存，降低拖动和重复刷新时的对象创建成本。
            formal = "正式" in str(new_data.get("source", ""))
            changed_layers = self._scene_layer_cache.update(new_data, formal=formal)
            new_data = self._scene_layer_cache.snapshot(formal=formal)
            new_data["_scene_changed_layers"] = sorted(changed_layers)
            new_kind = new_data.get("kind", new_kind)
        if self._try_update_reusable_2d(new_data):
            # 曲线数据变化但图类型不变时，只更新 artist，不清空整个 Figure。
            self._data = new_data
            self.draw_idle()
            record_perf(
                "plot_update",
                (perf_counter() - started) * 1000.0,
                kind=str(new_kind),
                mode="artist_reuse",
            )
            return
        if (
            new_kind in {"optical_scene_3d", "raytrace3d"}
            and self._data.get("kind") in {"optical_scene_3d", "raytrace3d"}
            and self._axis is not None
            and self._scene_static_signature == _scene_static_signature(new_data)
            and self._static_scene_artists is not None
        ):
            # 静态镜头和坐标系不变时，只更新动态光线/标记层。
            self._data = new_data
            self._update_optical_scene_dynamic(new_data)
            self.draw_idle()
            record_perf(
                "plot_update",
                (perf_counter() - started) * 1000.0,
                kind=str(new_kind),
                mode="dynamic",
            )
            return

        self._capture_view_state()
        self._data = new_data
        # 其余情况需要完整重建，并清理旧的轴、交互对象和颜色条引用。
        self.figure.clear()
        
        
        
        self.figure.subplots_adjust(
            left=0.13,
            right=0.96,
            bottom=0.14,
            top=0.89,
            wspace=0.30,
            hspace=0.30,
        )
        self._scene_static_signature = None
        self._static_scene_artists = None
        self._dynamic_scene_artists = None
        self._interaction.clear()
        self._hover.clear()
        self._item_artists = []
        self._item_labels = []
        self._reusable_2d_artists = []
        self._reusable_2d_labels = []
        self._heatmap_image = None
        self._heatmap_colorbar = None
        self._raytrace_surface_collection = None
        self._raytrace_rim_collection = None
        self._raytrace_ray_collections: dict[str, object] = {}
        self._raytrace_axis_line = None
        self._raytrace_scale_text = None
        self._raytrace_signature = None
        self.figure.set_facecolor(theme.SCENE_BACKGROUND)
        kind = self._data.get("kind", "empty")
        if kind == "heatmap_pair":
            # Matplotlib 仍支持双热图；嵌入工作区通常会优先使用快速热图路径。
            self._heatmap_pair(self._data)
            self._axis = None
        elif kind in {"optical_scene_3d", "raytrace3d"}:
            # 两种 3D 光路 kind 共用三维轴和场景绘制实现。
            ax = self.figure.add_subplot(111, projection="3d")
            self._axis = ax
            self._optical_scene_3d(ax, self._data)
        elif kind == "surface3d":
            ax = self.figure.add_subplot(111, projection="3d")
            self._axis = ax
            x = np.asarray(self._data.get("x", []), dtype=float)
            y = np.asarray(self._data.get("y", []), dtype=float)
            z = np.asarray(self._data.get("z", []), dtype=float)
            if z.ndim == 2 and z.size:
                if x.ndim == 1 and y.ndim == 1:
                    x, y = np.meshgrid(x, y)
                ax.plot_surface(x, y, z, linewidth=0, antialiased=True)
                ax.set_title(self._data.get("title", ""), pad=10)
                ax.set_xlabel(self._data.get("x_label", "x"))
                ax.set_ylabel(self._data.get("y_label", "y"))
                ax.set_zlabel(self._data.get("z_label", "强度"))
            else:
                ax.text2D(0.04, 0.92, self._data.get("message", "暂无三维数据"), transform=ax.transAxes)
        else:
            # 普通结果统一进入 Canvas2DMixin 的 kind 分发函数。
            ax = self.figure.add_subplot(111)
            self._axis = ax
            self._plot_2d(ax, self._data)
            if kind in {"line", "line_multi"}:
                self._reusable_2d_artists = list(ax.lines)
            elif kind in {"bar", "barh"}:
                self._reusable_2d_artists = [patch for patch, _label in self._item_artists]
                self._reusable_2d_labels = [label for _patch, label in self._item_artists]
        self._apply_high_contrast_axes(self.figure)
        self._apply_safe_plot_margins(kind)
        self.draw_idle()
        record_perf(
            "plot_update",
            (perf_counter() - started) * 1000.0,
            kind=str(kind),
            mode="rebuild",
        )


    def _apply_safe_plot_margins(self, kind: str) -> None:
        """为嵌入式结果工作区预留稳定的标题和坐标轴标签空间。

        Embedded plots have a fixed visual slot.  A chart must adapt to that slot rather
        than draw labels outside it and rely on clipping.  Composite plots keep their
        own hand-tuned layouts; ordinary 2-D charts use a shared safe margin.
        """
        if kind in {"heatmap_pair", "phase_comparison", "multi_plane_evolution", "before_after", "profile_pair", "adjustment_trajectory", "teaching_scan"}:
            return
        if kind in {"optical_scene_3d", "raytrace3d"}:
            return
        try:
            custom_bottom = self._data.get("plot_bottom_margin") if isinstance(self._data, dict) else None
            # Embedded Qt canvases need *inside-the-figure* safety space.  Using
            # tight_layout alone is not enough because the surrounding result card
            # can clip the title/axis labels before Matplotlib gets another resize.
            # Keep a deliberately larger title band and x/y label band instead of
            # shrinking fonts.  This is shared by training diagnostics, research
            # plots, validation plots and ordinary result charts.
            if custom_bottom is not None:
                bottom = min(0.42, max(0.18, float(custom_bottom)))
                self.figure.subplots_adjust(left=0.15, right=0.965, bottom=bottom, top=0.86)
                return
            if kind == "research_preview":
                self.figure.subplots_adjust(left=0.145, right=0.965, bottom=0.23, top=0.87)
            elif kind == "correlation_heatmap":
                self.figure.subplots_adjust(left=0.27, right=0.90, bottom=0.19, top=0.86)
            elif kind in {"candidate_compare", "bar", "bar_grouped", "target_achievement"}:
                self.figure.subplots_adjust(left=0.15, right=0.965, bottom=0.20, top=0.86)
            elif kind == "histogram":
                self.figure.subplots_adjust(left=0.14, right=0.965, bottom=0.22, top=0.86)
            elif kind in {"parameter_response", "validation_scatter", "residual", "scatter_formula", "convergence_curve", "line", "line_multi", "scatter"}:
                self.figure.subplots_adjust(left=0.15, right=0.965, bottom=0.24, top=0.86)
            elif kind in {"beeswarm", "mismatch_budget", "waterfall", "barh"}:
                self.figure.subplots_adjust(left=0.235, right=0.965, bottom=0.22, top=0.86)
            else:
                self.figure.subplots_adjust(left=0.155, right=0.96, bottom=0.22, top=0.86)
        except Exception:
            pass

    def _try_update_reusable_2d(self, new_data: dict) -> bool:
        """尝试原地更新同类型 2D artist；无法复用时返回 False。"""
        kind = str(new_data.get("kind", "empty"))
        if self._axis is None or kind != str(self._data.get("kind", "empty")):
            return False
        if kind == "line":
            if len(self._reusable_2d_artists) != 1:
                return False
            self._reusable_2d_artists[0].set_data(
                new_data.get("x", []), new_data.get("y", [])
            )
        elif kind == "line_multi":
            series = list(new_data.get("series", []) or [])
            if len(self._reusable_2d_artists) != len(series):
                return False
            x_values = new_data.get("x", [])
            for line, item in zip(self._reusable_2d_artists, series):
                line.set_data(x_values, item.get("y", []))
                line.set_label(str(item.get("label", "")))
            if series:
                self._axis.legend()
        elif kind == "heatmap":
            if self._heatmap_image is None:
                return False
            # 色带或归一化方式变化时必须重建 artist，否则切换光强/相位页会沿用旧色彩。
            if (
                str(new_data.get("color_map", "viridis")) != str(self._data.get("color_map", "viridis"))
                or str(new_data.get("normalization", "linear")) != str(self._data.get("normalization", "linear"))
            ):
                return False
            z, extent = self._prepare_heatmap_data(new_data)
            if not z.size:
                return False
            self._heatmap_image.set_data(z)
            if extent is not None:
                self._heatmap_image.set_extent(extent)
            finite = z[np.isfinite(z)]
            if finite.size:
                self._heatmap_image.set_clim(float(finite.min()), float(finite.max()))
            if self._heatmap_colorbar is not None:
                self._heatmap_colorbar.update_normal(self._heatmap_image)
        elif kind in {"raytrace", "raytrace_section"}:
            if not self._update_raytrace_section(self._axis, new_data):
                return False
        elif kind in {"bar", "barh"}:
            labels = [str(value) for value in new_data.get("labels", [])]
            values = [float(value) for value in new_data.get("values", [])]
            if labels != self._reusable_2d_labels or len(values) != len(self._reusable_2d_artists):
                return False
            colors = list(new_data.get("colors") or [])
            selected = str(new_data.get("selected_label", ""))
            for index, (patch, label, value) in enumerate(zip(self._reusable_2d_artists, labels, values)):
                if kind == "barh":
                    patch.set_width(value)
                else:
                    patch.set_height(value)
                if index < len(colors):
                    patch.set_facecolor(colors[index])
                patch.set_edgecolor("#f97316" if selected and label == selected else "#ffffff")
                patch.set_linewidth(2.2 if selected and label == selected else 0.55)
            
            if bool(new_data.get("show_values")):
                numeric_texts = list(self._axis.texts)
                maximum = max((abs(value) for value in values), default=1.0) or 1.0
                if len(numeric_texts) != len(values):
                    return False
                for text_artist, patch, value in zip(numeric_texts, self._reusable_2d_artists, values):
                    text_artist.set_text(f"{value:.3g}")
                    if kind == "barh":
                        offset = 0.012 * maximum
                        text_artist.set_position((value + offset if value >= 0 else value - offset, patch.get_y() + patch.get_height()/2.0))
                        text_artist.set_ha("left" if value >= 0 else "right")
                    else:
                        offset = 0.018 * maximum
                        text_artist.set_position((patch.get_x() + patch.get_width()/2.0, value + offset if value >= 0 else value - offset))
                        text_artist.set_va("bottom" if value >= 0 else "top")
        else:
            return False
        self._axis.set_title(new_data.get("title", ""), pad=8)
        self._axis.set_xlabel(new_data.get("x_label", ""))
        self._axis.set_ylabel(new_data.get("y_label", ""))
        if kind not in {"raytrace", "raytrace_section"}:
            self._axis.relim()
            self._axis.autoscale_view()
        self._apply_high_contrast_axes(self.figure)
        return True

    def dispose(self) -> None:
        """断开 Matplotlib 信号并释放交互、悬停和场景资源。"""
        try:
            self._interaction.clear()
            self._hover.clear()
        except Exception:
            pass
        self._scene_layer_cache.clear()
        try:
            self.figure.clear()
        except Exception:
            pass
        try:
            from matplotlib import pyplot as plt
            plt.close(self.figure)
        except Exception:
            pass
        self.deleteLater()

    def reset_view(self) -> None:
        """恢复当前 2D 或 3D 图的默认视图范围。"""
        if self._axis is None:
            return
        kind = self._data.get("kind", "empty")
        if kind in {"optical_scene_3d", "raytrace3d"}:
            self._optical_3d_zoom = 1.0
            fit_optical_scene_3d(self._axis, self._data, zoom=self._optical_3d_zoom)
            self._axis.view_init(elev=18, azim=-66)
        elif kind in {"raytrace", "raytrace_section"}:
            fit_optical_section_2d(self._axis, self._data)
        else:
            self._axis.relim()
            self._axis.autoscale_view()
        self.draw_idle()
        self.viewChanged.emit()

    def set_optical_3d_view(self, preset: str = "all") -> bool:
        """将当前光路结果切换到指定的 3D 视角预设。"""
        """Fit the formal Matplotlib 3D optical result to a useful axial region.

        This deliberately changes only the formal simulation plot.  The teaching
        centre uses Qt Quick 3D and has an independent camera controller.
        """
        if self._axis is None or self._data.get("kind") not in {"optical_scene_3d", "raytrace3d"}:
            return False
        preset = str(preset or "all").strip().lower()
        self._optical_3d_zoom = 1.0
        fit_optical_scene_3d(self._axis, self._data, zoom=self._optical_3d_zoom)
        if preset in {"all", "fit", "适应全部", "全部光路"}:
            self._axis.view_init(elev=18, azim=-66)
            self.draw_idle(); self.viewChanged.emit(); return True

        surfaces = [dict(item) for item in self._data.get("surfaces", []) or [] if item.get("visible", True) is not False]
        objects = [dict(item) for item in self._data.get("objects", []) or [] if item.get("visible", True) is not False]
        if not surfaces and not objects:
            return False
        full_left, full_right = map(float, self._axis.get_xlim())
        full_span = max(abs(full_right - full_left), 1e-6)

        groups: list[tuple[str, list[dict]]] = []
        for item in surfaces:
            gid = str(item.get("group_id", "") or item.get("label", "") or "").strip()
            if not gid:
                continue
            for existing_gid, records in groups:
                if existing_gid == gid:
                    records.append(item); break
            else:
                groups.append((gid, [item]))
        groups.sort(key=lambda rec: min(float(x.get("z", 0.0) or 0.0) for x in rec[1]))

        z_values: list[float] = []
        if preset in {"l1-l2", "l1_l2", "front", "前组"}:
            chosen = groups[:2] if groups else []
            z_values = [float(x.get("z", 0.0) or 0.0) for _, recs in chosen for x in recs]
        elif preset in {"l3-l4", "l3_l4", "rear", "后组"}:
            chosen = groups[-2:] if groups else []
            z_values = [float(x.get("z", 0.0) or 0.0) for _, recs in chosen for x in recs]
        elif preset in {"fiber", "fiber_end", "receiver", "光纤端面"}:
            receiver_values = []
            for item in objects:
                text = " ".join(str(item.get(key, "") or "") for key in ("kind", "type", "label", "name", "id")).lower()
                if any(token in text for token in ("fiber", "receiver", "image", "detector", "光纤", "端面")):
                    receiver_values.append(float(item.get("z", 0.0) or 0.0))
            if not receiver_values:
                receiver_values = [float(item.get("z", 0.0) or 0.0) for item in objects]
            if receiver_values:
                centre = max(receiver_values)
                width = max(0.24 * full_span, 1e-3)
                z_values = [centre - 0.82 * width, centre + 0.18 * width]

        if not z_values and surfaces:
            ordered = sorted(float(item.get("z", 0.0) or 0.0) for item in surfaces)
            if preset in {"l1-l2", "l1_l2", "front", "前组"}:
                z_values = ordered[: max(2, len(ordered)//2)]
            elif preset in {"l3-l4", "l3_l4", "rear", "后组"}:
                z_values = ordered[len(ordered)//2 :]
        if not z_values:
            return False
        z_low, z_high = min(z_values), max(z_values)
        region_span = max(z_high - z_low, 0.08 * full_span, 1e-6)
        margin = 0.16 * region_span
        self._axis.set_xlim(z_low - margin, z_high + margin)
        apply_optical_scene_3d_zoom(self._axis, zoom=self._optical_3d_zoom)
        self.draw_idle(); self.viewChanged.emit(); return True

    def save_figure(self, path: str | Path) -> Path:
        """将当前 Figure 保存为图片文件并返回规范化路径。"""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.figure.savefig(output, dpi=220, bbox_inches="tight")
        return output

    def export_data(self, path: str | Path) -> Path:
        """把当前结构化绘图载荷导出为 JSON/CSV 等数据文件。"""

        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        kind = str(self._data.get("kind", "empty"))
        if output.suffix.lower() == ".npz":
            arrays = _numeric_arrays(self._data)
            np.savez_compressed(output, **arrays)
            return output
        rows = _csv_rows(self._data)
        output.write_text("\n".join(",".join(_csv_cell(value) for value in row) for row in rows) + "\n", encoding="utf-8-sig")
        return output
