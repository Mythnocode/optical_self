from __future__ import annotations

from pathlib import Path
from time import perf_counter

import numpy as np
from matplotlib import rcParams
from cycler import cycler
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QSizePolicy

from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.performance import record_perf
from frontend_pyside.shared.font_fallback import matplotlib_font_config
from frontend_pyside.shared.plotting.canvas_3d_interaction import (
    Optical3DInteractionController,
)
from frontend_pyside.shared.plotting.canvas_view import (
    fit_optical_scene_3d,
    fit_optical_section_2d,
)
from frontend_pyside.shared.plotting.surface_hover_controller import SurfaceHoverController
from frontend_pyside.shared.plotting.scene_cache import DualQualitySceneCache

rcParams.update(
    {
        **matplotlib_font_config(),
        "font.size": 12.0,
        "axes.titlesize": 16.0,
        "axes.titleweight": "semibold",
        "axes.labelsize": 13.0,
        "xtick.labelsize": 11.0,
        "ytick.labelsize": 11.0,
        "legend.fontsize": 11.0,
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


    surfaceSelected = Signal(int)
    surfaceActivated = Signal(int)
    itemSelected = Signal(str)
    viewChanged = Signal()

    def __init__(self, parent=None):
        
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

    @property
    def data(self) -> dict:
        return dict(self._data)

    def clear(self) -> None:
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
        started = perf_counter()
        new_data = dict(data or {})
        new_kind = new_data.get("kind", "empty")
        if new_kind in {"optical_scene_3d", "raytrace3d"}:
            formal = "正式" in str(new_data.get("source", ""))
            changed_layers = self._scene_layer_cache.update(new_data, formal=formal)
            new_data = self._scene_layer_cache.snapshot(formal=formal)
            new_data["_scene_changed_layers"] = sorted(changed_layers)
            new_kind = new_data.get("kind", new_kind)
        if self._try_update_reusable_2d(new_data):
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
            self._heatmap_pair(self._data)
            self._axis = None
        elif kind in {"optical_scene_3d", "raytrace3d"}:
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
            ax = self.figure.add_subplot(111)
            self._axis = ax
            self._plot_2d(ax, self._data)
            if kind in {"line", "line_multi"}:
                self._reusable_2d_artists = list(ax.lines)
            elif kind in {"bar", "barh"}:
                self._reusable_2d_artists = [patch for patch, _label in self._item_artists]
                self._reusable_2d_labels = [label for _patch, label in self._item_artists]
        self._apply_high_contrast_axes(self.figure)
        self.draw_idle()
        record_perf(
            "plot_update",
            (perf_counter() - started) * 1000.0,
            kind=str(kind),
            mode="rebuild",
        )

    def _try_update_reusable_2d(self, new_data: dict) -> bool:
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
        if self._axis is None:
            return
        kind = self._data.get("kind", "empty")
        if kind in {"optical_scene_3d", "raytrace3d"}:
            fit_optical_scene_3d(self._axis, self._data)
            self._axis.view_init(elev=18, azim=-66)
        elif kind in {"raytrace", "raytrace_section"}:
            fit_optical_section_2d(self._axis, self._data)
        else:
            self._axis.relim()
            self._axis.autoscale_view()
        self.draw_idle()
        self.viewChanged.emit()

    def save_figure(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.figure.savefig(output, dpi=220, bbox_inches="tight")
        return output

    def export_data(self, path: str | Path) -> Path:

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
