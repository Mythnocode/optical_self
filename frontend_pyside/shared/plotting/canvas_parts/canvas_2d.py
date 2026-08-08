from __future__ import annotations

import numpy as np
from matplotlib.collections import LineCollection
from frontend_pyside.resources import theme_tokens as theme
from frontend_pyside.shared.plotting.canvas_view import fit_optical_section_2d
from frontend_pyside.shared.plotting.ray_plot_style import (RAY_ALPHA_2D, RAY_LINEWIDTH_2D, SURFACE_ALPHA_2D, SURFACE_LINEWIDTH_2D)
from .data_utils import _downsample_grid, _field_crop_slices

class Canvas2DMixin:
    @staticmethod
    def _readable_category_labels(labels: list[str], *, max_chars: int = 16) -> list[str]:

        result: list[str] = []
        for raw in labels:
            text = str(raw).strip() or "—"
            if "｜" in text:
                left, right = text.split("｜", 1)
                if len(text) > max_chars:
                    text = f"{left}\n{right}"
            elif len(text) > max_chars:
                split_at = max(6, min(len(text) - 1, max_chars // 2))
                text = f"{text[:split_at]}\n{text[split_at:max_chars - 1]}…"
            result.append(text)
        return result

    def _set_category_plot_layout(self, ax, labels: list[str]) -> None:
        longest = max((max(len(part) for part in label.split("\n")) for label in labels), default=6)
        left = min(0.34, max(0.22, 0.16 + 0.008 * longest))
        ax.figure.subplots_adjust(left=left, right=0.96, bottom=0.17, top=0.86)

    def _plot_2d(self, ax, data: dict) -> None:
        kind = data.get("kind", "empty")
        if kind == "beam_match":
            self._beam_match(ax, data)
        elif kind == "waist_position":
            self._waist_position(ax, data)
        elif kind == "parameter_response":
            self._parameter_response(ax, data)
        elif kind == "validation_scatter":
            self._validation_scatter(ax, data)
        elif kind == "residual":
            self._residual_plot(ax, data)
        elif kind == "waterfall":
            self._waterfall(ax, data)
        elif kind == "mismatch_budget":
            self._mismatch_budget(ax, data)
        elif kind == "phase_comparison":
            self._phase_comparison(ax, data)
        elif kind == "multi_plane_evolution":
            self._multi_plane_evolution(ax, data)
        elif kind == "energy_flow":
            self._energy_flow(ax, data)
        elif kind == "before_after":
            self._before_after(ax, data)
        elif kind == "candidate_compare":
            self._candidate_compare(ax, data)
        elif kind == "convergence_curve":
            self._convergence_curve(ax, data)
        elif kind == "correlation_heatmap":
            self._correlation_heatmap(ax, data)
        elif kind == "adjustment_trajectory":
            self._adjustment_trajectory(ax, data)
        elif kind == "teaching_scan":
            self._teaching_scan(ax, data)
        elif kind == "line":
            ax.plot(data.get("x", []), data.get("y", []), linewidth=1.8)
        elif kind == "line_multi":
            for series in data.get("series", []):
                ax.plot(
                    data.get("x", []),
                    series.get("y", []),
                    label=series.get("label", ""),
                    linewidth=1.7,
                )
            if data.get("series"):
                ax.legend()
        elif kind == "heatmap":
            z, extent = self._prepare_heatmap_data(data)
            if z.size:
                image = ax.imshow(z, origin="lower", aspect="equal", extent=extent)
                self._heatmap_image = image
                self._heatmap_colorbar = self.figure.colorbar(image, ax=ax, shrink=0.78)
        elif kind == "heatmap_contour":
            self._heatmap_contour(ax, data)
        elif kind == "bar":
            labels = [str(value) for value in data.get("labels", [])]
            values = data.get("values", [])
            colors = data.get("colors") or None
            bars = ax.bar(labels, values, color=colors)
            self._register_bar_items(bars, labels, data)
            self._annotate_bars(ax, bars, values, horizontal=False, enabled=bool(data.get("show_values")))
            ax.tick_params(axis="x", rotation=18)
        elif kind == "barh":
            labels = [str(value) for value in data.get("labels", [])]
            values = data.get("values", [])
            colors = data.get("colors") or None
            bars = ax.barh(labels, values, color=colors)
            self._register_bar_items(bars, labels, data)
            self._annotate_bars(ax, bars, values, horizontal=True, enabled=bool(data.get("show_values")))
            ax.invert_yaxis()
        elif kind == "beeswarm":
            self._beeswarm(ax, data)
        elif kind == "scatter_formula":
            self._scatter_formula(ax, data)
        elif kind == "bar_grouped":
            labels = data.get("labels", [])
            series = data.get("series", [])
            positions = np.arange(len(labels), dtype=float)
            count = max(1, len(series))
            width = 0.78 / count
            for index, item in enumerate(series):
                offset = (index - (count - 1) / 2) * width
                ax.bar(
                    positions + offset,
                    item.get("values", []),
                    width,
                    label=item.get("label", ""),
                )
            ax.set_xticks(positions)
            ax.set_xticklabels(labels, rotation=18)
            if series:
                ax.legend()
        elif kind == "donut":
            values = data.get("values", [])
            labels = data.get("labels", [])
            if values and sum(values) > 0:
                ax.pie(
                    values,
                    labels=labels,
                    autopct="%1.0f%%",
                    startangle=90,
                    wedgeprops={"width": 0.42},
                )
                ax.axis("equal")
            else:
                self._empty(ax, data.get("message", "暂无真实统计"))
        elif kind == "scatter":
            ax.scatter(data.get("x", []), data.get("y", []), s=16, alpha=0.72)
            airy = float(data.get("airy_radius_um", 0.0) or 0.0)
            if airy > 0.0:
                from matplotlib.patches import Circle

                circle = Circle((0.0, 0.0), airy, fill=False, linewidth=1.1, linestyle="--")
                ax.add_patch(circle)
                ax.set_aspect("equal", adjustable="box")
        elif kind in {"raytrace", "raytrace_section"}:
            self._raytrace_section(ax, data)
        elif kind == "text":
            ax.axis("off")
            ax.text(
                0.02,
                0.98,
                data.get("text", ""),
                va="top",
                ha="left",
                wrap=True,
                transform=ax.transAxes,
                linespacing=1.45,
            )
        else:
            self._empty(ax, data.get("message", "暂无结果"))

        composite_kinds = {
            "phase_comparison", "multi_plane_evolution", "before_after",
            "adjustment_trajectory", "teaching_scan",
        }
        if kind in composite_kinds:
            return

        diagnostic_titleless_kinds = {
            "waterfall", "mismatch_budget", "beeswarm", "scatter_formula",
            "beam_match", "phase_comparison", "multi_plane_evolution", "before_after",
            "adjustment_trajectory", "teaching_scan",
        }
        if kind in diagnostic_titleless_kinds:
            
            
            ax.set_title("")
        else:
            ax.set_title(data.get("title", ""), pad=8)
        ax.set_xlabel(data.get("x_label", ""))
        if kind in {"waterfall", "mismatch_budget", "beeswarm"}:
            
            
            ax.set_ylabel(data.get("y_label", ""), rotation=90, labelpad=28, va="center")
        else:
            ax.set_ylabel(data.get("y_label", ""), rotation=90, labelpad=12, va="center")
        if kind in (
            "line", "line_multi", "scatter", "beeswarm", "scatter_formula",
            "mismatch_budget", "waist_position", "parameter_response",
            "validation_scatter", "residual", "convergence_curve",
        ):
            ax.grid(True, alpha=0.72, color=theme.CHART_GRID)
        else:
            ax.grid(False)

    def _beam_match(self, ax, data: dict) -> None:
        from matplotlib.patches import Ellipse

        field = np.asarray(data.get("z", []), dtype=float)
        mode = np.asarray(data.get("contour", []), dtype=float)
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        if field.ndim != 2 or not field.size:
            self._empty(ax, data.get("message", "暂无端面复场数据"))
            return
        if len(x) != field.shape[1]:
            x = np.arange(field.shape[1], dtype=float)
        if len(y) != field.shape[0]:
            y = np.arange(field.shape[0], dtype=float)
        rows, columns = _field_crop_slices(
            field, mode if mode.shape == field.shape else np.empty((0, 0)),
            fraction=float(data.get("auto_crop_fraction", np.exp(-2.0)) or np.exp(-2.0)),
        )
        
        
        
        try:
            ic = data.get("incident_center", [0.0, 0.0])
            fc = data.get("fiber_center", [0.0, 0.0])
            ir = data.get("incident_radius", [0.0, 0.0])
            tr = data.get("target_radius", [0.0, 0.0])
            x_radius = max(float(ir[0]), float(tr[0]), abs(float(ic[0]) - float(fc[0])) / 2.0, 1e-12)
            y_radius = max(float(ir[1]), float(tr[1]), abs(float(ic[1]) - float(fc[1])) / 2.0, 1e-12)
            x_center = 0.5 * (float(ic[0]) + float(fc[0]))
            y_center = 0.5 * (float(ic[1]) + float(fc[1]))
            x_mask = np.flatnonzero((x >= x_center - 3.2 * x_radius) & (x <= x_center + 3.2 * x_radius))
            y_mask = np.flatnonzero((y >= y_center - 3.2 * y_radius) & (y <= y_center + 3.2 * y_radius))
            if len(x_mask) >= 8 and len(y_mask) >= 8:
                columns = slice(max(0, int(x_mask[0]) - 2), min(len(x), int(x_mask[-1]) + 3))
                rows = slice(max(0, int(y_mask[0]) - 2), min(len(y), int(y_mask[-1]) + 3))
        except (TypeError, ValueError, IndexError):
            pass
        view = field[rows, columns]
        mode_view = mode[rows, columns] if mode.shape == field.shape else np.empty((0, 0))
        xv, yv = x[columns], y[rows]
        extent = [float(xv[0]), float(xv[-1]), float(yv[0]), float(yv[-1])]
        
        
        
        ax.set_position([0.25, 0.14, 0.54, 0.54])
        self.figure.suptitle(
            str(data.get("title", "端面匹配总览")),
            y=0.975, fontsize=15, fontweight="semibold",
        )
        image = ax.imshow(view, origin="lower", aspect="equal", extent=extent)
        self._heatmap_image = image
        color_axis = self.figure.add_axes([0.84, 0.19, 0.026, 0.43])
        self._heatmap_colorbar = self.figure.colorbar(image, cax=color_axis, label="归一化强度")
        if mode_view.size and float(np.nanmax(mode_view)) > 0.0:
            level = float(np.nanmax(mode_view)) * float(data.get("contour_fraction", np.exp(-2.0)))
            ax.contour(xv, yv, mode_view, levels=[level], colors=[theme.FIBER_CORE], linewidths=1.45)

        incident_center = data.get("incident_center", [0.0, 0.0])
        fiber_center = data.get("fiber_center", [0.0, 0.0])
        ax.scatter([incident_center[0]], [incident_center[1]], marker="+", s=72, linewidths=1.8, color=theme.CHART_CURRENT, label="入射光中心")
        ax.scatter([fiber_center[0]], [fiber_center[1]], marker="x", s=62, linewidths=1.7, color=theme.CHART_TARGET, label="光纤中心")
        incident_radius = data.get("incident_radius", [0.0, 0.0])
        target_radius = data.get("target_radius", [0.0, 0.0])
        if min(incident_radius or [0.0]) > 0.0:
            ax.add_patch(Ellipse(tuple(incident_center), 2 * incident_radius[0], 2 * incident_radius[1], fill=False, linewidth=1.5, linestyle="--", edgecolor=theme.CHART_CURRENT))
        if min(target_radius or [0.0]) > 0.0:
            ax.add_patch(Ellipse(tuple(fiber_center), 2 * target_radius[0], 2 * target_radius[1], fill=False, linewidth=1.5, linestyle=":", edgecolor=theme.CHART_TARGET))
        ax.legend(loc="lower left", fontsize=11)
        ax.set_aspect("equal", adjustable="box")

        top = self.figure.add_axes([0.25, 0.73, 0.54, 0.17], sharex=ax)
        right = self.figure.add_axes([0.06, 0.14, 0.14, 0.54], sharey=ax)
        x_profiles = data.get("x_profiles", {})
        y_profiles = data.get("y_profiles", {})
        for label, values in x_profiles.items():
            values = np.asarray(values, dtype=float)
            if len(values) == len(x):
                top.plot(x, values, linewidth=1.25, label=label)
        for label, values in y_profiles.items():
            values = np.asarray(values, dtype=float)
            if len(values) == len(y):
                right.plot(values, y, linewidth=1.25, label=label)
        top.set_ylabel("X剖面", fontsize=11)
        top.tick_params(labelbottom=False, labelsize=7)
        top.grid(True, alpha=0.72, color=theme.CHART_GRID)
        right.set_xlabel("归一化强度", fontsize=7)
        right.set_ylabel("Y剖面", fontsize=11)
        right.tick_params(labelleft=False, labelsize=7)
        right.grid(True, alpha=0.72, color=theme.CHART_GRID)

        metrics = dict(data.get("metrics", {}) or {})
        summary_lines = []
        efficiency = metrics.get("coupling_efficiency_percent")
        system_efficiency = metrics.get("system_efficiency_percent")
        if isinstance(efficiency, (int, float)) and np.isfinite(float(efficiency)):
            summary_lines.append(f"耦合效率  {float(efficiency):.3f}%")
        if isinstance(system_efficiency, (int, float)) and np.isfinite(float(system_efficiency)):
            summary_lines.append(f"系统效率  {float(system_efficiency):.3f}%")
        center_offset = metrics.get("center_offset_um")
        if isinstance(center_offset, (int, float)) and np.isfinite(float(center_offset)):
            summary_lines.append(f"中心偏移  {float(center_offset):.3g} μm")
        ratio_x = metrics.get("size_ratio_x")
        ratio_y = metrics.get("size_ratio_y")
        if all(isinstance(value, (int, float)) and np.isfinite(float(value)) for value in (ratio_x, ratio_y)):
            summary_lines.append(f"尺寸比  X {float(ratio_x):.3f} / Y {float(ratio_y):.3f}")
        ellipticity = metrics.get("ellipticity")
        if isinstance(ellipticity, (int, float)) and np.isfinite(float(ellipticity)):
            summary_lines.append(f"椭圆率  {float(ellipticity):.3f}")
        if summary_lines:
            self.figure.text(
                0.825, 0.69, "\n".join(summary_lines),
                ha="left", va="top", fontsize=9.2,
                bbox={"boxstyle": "round,pad=0.45", "facecolor": theme.SURFACE,
                      "edgecolor": theme.BORDER_STRONG, "alpha": 0.96},
            )

    def _waist_position(self, ax, data: dict) -> None:
        z = np.asarray(data.get("x", []), dtype=float)
        for series in data.get("series", []):
            values = np.asarray(series.get("y", []), dtype=float)
            if len(z) and len(values) == len(z):
                ax.plot(z, values, linewidth=1.8, label=str(series.get("label", "")))
        fiber_z = float(data.get("fiber_z", 0.0) or 0.0)
        target = float(data.get("target_radius", 0.0) or 0.0)
        ax.axvline(fiber_z, color=theme.CHART_CURRENT, linestyle="--", linewidth=1.5, label="光纤端面")
        if target > 0.0:
            ax.axhline(target, color=theme.CHART_TARGET, linestyle=":", linewidth=1.5, label="目标模场半径")
        for point in data.get("waist_points", []):
            ax.scatter([point.get("z", 0.0)], [point.get("w", 0.0)], s=36, marker=point.get("marker", "o"), label=point.get("label", "束腰"))
        if data.get("series"):
            ax.legend()

    def _parameter_response(self, ax, data: dict) -> None:
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        if len(x) and len(y):
            count = min(len(x), len(y))
            order = np.argsort(x[:count])
            ax.plot(x[:count][order], y[:count][order], color=theme.CHART_BLUE, linewidth=2.0, label="响应曲线")
            ax.scatter(x[:count], y[:count], s=28, color=theme.CHART_BLUE, alpha=0.85, edgecolors=theme.SURFACE, linewidths=0.6, label="采样点")
        high_range = data.get("high_efficiency_range")
        if isinstance(high_range, (list, tuple)) and len(high_range) >= 2:
            low, high = float(high_range[0]), float(high_range[1])
            ax.axvspan(
                min(low, high), max(low, high), alpha=0.12,
                color=theme.CHART_TARGET,
                label=str(data.get("high_efficiency_label", "高效区间")),
                zorder=0,
            )
        marker_specs = (
            ("current_point", "当前参数", "D"),
            ("best_point", "扫描最佳点", "*"),
            ("verified_point", "正式复核", "s"),
        )
        marker_colors = {
            "current_point": theme.CHART_CURRENT,
            "best_point": theme.CHART_ORANGE,
            "verified_point": theme.CHART_TARGET,
        }
        for key, label, marker in marker_specs:
            point = data.get(key)
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                ax.scatter(
                    [point[0]], [point[1]],
                    s=88 if marker == "*" else 58, marker=marker,
                    color=marker_colors[key], edgecolors=theme.SURFACE, linewidths=0.8,
                    label=label, zorder=5,
                )
        if len(x) or any(data.get(item[0]) for item in marker_specs):
            ax.legend()

    @staticmethod
    def _finite_pairs(first, second) -> tuple[np.ndarray, np.ndarray]:

        try:
            first_values = np.asarray(first, dtype=float).reshape(-1)
            second_values = np.asarray(second, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return np.empty(0, dtype=float), np.empty(0, dtype=float)
        count = min(first_values.size, second_values.size)
        if not count:
            return np.empty(0, dtype=float), np.empty(0, dtype=float)
        first_values, second_values = first_values[:count], second_values[:count]
        valid = np.isfinite(first_values) & np.isfinite(second_values)
        return first_values[valid], second_values[valid]

    @staticmethod
    def _diagnostic_tolerance(residual: np.ndarray, configured=None) -> float:

        try:
            tolerance = float(configured)
        except (TypeError, ValueError):
            tolerance = 0.0
        if np.isfinite(tolerance) and tolerance > 0.0:
            return tolerance
        if residual.size:
            mae = float(np.mean(np.abs(residual)))
            if mae > np.finfo(float).eps:
                return 2.0 * mae
            scale = max(float(np.max(np.abs(residual))), 1.0)
            return scale * 0.02
        return 1.0

    @staticmethod
    def _diagnostic_metric_lines(data: dict, actual: np.ndarray, residual: np.ndarray, tolerance: float) -> list[str]:

        if not residual.size:
            return []
        provided = dict(data.get("metrics", {}) or {})
        total_variation = float(np.sum((actual - np.mean(actual)) ** 2))
        r2 = 1.0 - float(np.sum(residual ** 2)) / total_variation if total_variation > np.finfo(float).eps else float("nan")
        mae = float(np.mean(np.abs(residual)))
        bias = float(np.mean(residual))
        p95 = float(np.percentile(np.abs(residual), 95))
        coverage = float(np.mean(np.abs(residual) <= tolerance)) * 100.0
        r2_label = provided.get("R²", f"{r2:.4f}" if np.isfinite(r2) else "—")
        mae_label = provided.get("MAE", f"{mae:.4g}")
        return [
            f"R²  {r2_label}",
            f"MAE  {mae_label}",
            f"Bias  {bias:+.3g}",
            f"P95 |e|  {p95:.3g}",
            f"±2×MAE 内  {coverage:.0f}%",
        ]

    @staticmethod
    def _diagnostic_limits(*arrays: np.ndarray) -> tuple[float, float]:
        values = [array[np.isfinite(array)] for array in arrays if array.size]
        values = [array for array in values if array.size]
        if not values:
            return -1.0, 1.0
        low = float(min(np.min(array) for array in values))
        high = float(max(np.max(array) for array in values))
        span = high - low
        padding = span * 0.08 if span > np.finfo(float).eps else max(abs(low) * 0.08, 1.0)
        return low - padding, high + padding

    @staticmethod
    def _draw_diagnostic_metrics(ax, lines: list[str]) -> None:
        if not lines:
            return
        ax.text(
            0.02,
            0.98,
            "\n".join(lines),
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=10.2,
            linespacing=1.42,
            bbox={"boxstyle": "round,pad=0.42", "facecolor": theme.SURFACE, "edgecolor": theme.BORDER, "alpha": 0.94},
            zorder=8,
        )

    def _validation_scatter(self, ax, data: dict) -> None:

        from matplotlib.patches import Patch

        actual, predicted = self._finite_pairs(
            data.get("actual", data.get("x", [])),
            data.get("predicted", data.get("y", [])),
        )
        residual = predicted - actual
        tolerance = self._diagnostic_tolerance(residual, data.get("tolerance"))
        point = data.get("current_point")
        current_actual = current_predicted = None
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                current_actual, current_predicted = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                current_actual = current_predicted = None
            if current_actual is not None and not (np.isfinite(current_actual) and np.isfinite(current_predicted)):
                current_actual = current_predicted = None

        limit_arrays = [actual, predicted]
        if current_actual is not None:
            limit_arrays.extend((np.asarray([current_actual]), np.asarray([current_predicted])))
        low, high = self._diagnostic_limits(*limit_arrays)
        reference_x = np.linspace(low, high, 160)
        ax.fill_between(
            reference_x,
            reference_x - tolerance,
            reference_x + tolerance,
            color=theme.CHART_BLUE,
            alpha=0.09,
            linewidth=0,
            zorder=0,
        )
        ax.plot([low, high], [low, high], color=theme.CHART_REFERENCE, linestyle="--", linewidth=1.55, label="理想线  y=x", zorder=2)

        if actual.size >= 140:
            ax.hexbin(actual, predicted, gridsize=28, mincnt=1, cmap="Blues", linewidths=0.0, alpha=0.9, label="测试样本密度", zorder=2)
        elif actual.size:
            ax.scatter(actual, predicted, s=31, color=theme.CHART_BLUE, alpha=0.78, edgecolors=theme.SURFACE, linewidths=0.5, label="测试样本", zorder=3)
        if actual.size:
            outliers = np.abs(residual) > tolerance
            if np.any(outliers):
                ax.scatter(actual[outliers], predicted[outliers], s=38, color=theme.CHART_ORANGE, alpha=0.92, edgecolors=theme.SURFACE, linewidths=0.55, label="超出 ±2×MAE", zorder=4)
        if current_actual is not None:
            ax.scatter([current_actual], [current_predicted], marker="*", s=155, color=theme.CHART_CURRENT, edgecolors=theme.SURFACE, linewidths=0.9, label="当前方案", zorder=6)

        ax.set_xlim(low, high)
        ax.set_ylim(low, high)
        ax.set_aspect("equal", adjustable="box")
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            [Patch(facecolor=theme.CHART_BLUE, alpha=0.13, edgecolor="none"), *handles],
            ["诊断带  ±2×MAE", *labels],
            loc="lower right",
            fontsize=9.2,
        )
        self._draw_diagnostic_metrics(ax, self._diagnostic_metric_lines(data, actual, residual, tolerance))

    def _residual_plot(self, ax, data: dict) -> None:

        actual, residual = self._finite_pairs(
            data.get("actual", data.get("predicted", data.get("x", []))),
            data.get("residual", data.get("y", [])),
        )
        tolerance = self._diagnostic_tolerance(residual, data.get("tolerance"))
        point = data.get("current_point")
        current_actual = current_residual = None
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                current_actual, current_residual = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                current_actual = current_residual = None
            if current_actual is not None and not (np.isfinite(current_actual) and np.isfinite(current_residual)):
                current_actual = current_residual = None

        x_low, x_high = self._diagnostic_limits(actual, np.asarray([current_actual]) if current_actual is not None else np.empty(0))
        y_low, y_high = self._diagnostic_limits(
            residual,
            np.asarray([-tolerance, tolerance]),
            np.asarray([current_residual]) if current_residual is not None else np.empty(0),
        )
        ax.fill_between([x_low, x_high], -tolerance, tolerance, color=theme.CHART_BLUE, alpha=0.09, linewidth=0, zorder=0)
        ax.axhline(0.0, color=theme.CHART_REFERENCE, linestyle="--", linewidth=1.55, label="零残差", zorder=2)
        ax.axhline(tolerance, color=theme.CHART_BLUE, linestyle=":", linewidth=1.15, label="诊断带  ±2×MAE", zorder=2)
        ax.axhline(-tolerance, color=theme.CHART_BLUE, linestyle=":", linewidth=1.15, zorder=2)
        if actual.size:
            ax.scatter(actual, residual, s=30, color=theme.CHART_BLUE, alpha=0.74, edgecolors=theme.SURFACE, linewidths=0.5, label="测试样本", zorder=3)
            outliers = np.abs(residual) > tolerance
            if np.any(outliers):
                ax.scatter(actual[outliers], residual[outliers], s=38, color=theme.CHART_ORANGE, alpha=0.92, edgecolors=theme.SURFACE, linewidths=0.55, label="超出诊断带", zorder=4)
            if actual.size >= 4:
                order = np.argsort(actual)
                chunks = np.array_split(order, min(10, max(4, int(np.sqrt(actual.size)))))
                centers, medians, q10, q90 = [], [], [], []
                for chunk in chunks:
                    if not chunk.size:
                        continue
                    values = residual[chunk]
                    centers.append(float(np.median(actual[chunk])))
                    medians.append(float(np.median(values)))
                    q10.append(float(np.percentile(values, 10)))
                    q90.append(float(np.percentile(values, 90)))
                if centers:
                    ax.fill_between(centers, q10, q90, color=theme.CHART_GREEN, alpha=0.12, linewidth=0, zorder=1)
                    ax.plot(centers, medians, color=theme.CHART_GREEN, linewidth=1.8, marker="o", markersize=3.2, label="分箱中位趋势", zorder=5)
        if current_actual is not None:
            ax.scatter([current_actual], [current_residual], marker="*", s=155, color=theme.CHART_CURRENT, edgecolors=theme.SURFACE, linewidths=0.9, label="当前方案", zorder=6)

        ax.set_xlim(x_low, x_high)
        ax.set_ylim(y_low, y_high)
        ax.legend(loc="lower left", fontsize=9.1)
        self._draw_diagnostic_metrics(ax, self._diagnostic_metric_lines(data, actual, residual, tolerance))
        self._residual_distribution_inset(ax, residual, tolerance)

    @staticmethod
    def _residual_distribution_inset(ax, residual: np.ndarray, tolerance: float) -> None:

        inset = ax.inset_axes([0.69, 0.57, 0.28, 0.35])
        inset._compact_diagnostic_inset = True
        inset.set_facecolor(theme.SURFACE)
        if not residual.size:
            inset.text(0.5, 0.5, "无残差数据", ha="center", va="center", transform=inset.transAxes, fontsize=8)
            return
        bins = min(18, max(5, int(np.sqrt(residual.size)) + 2))
        inset.hist(residual, bins=bins, density=True, orientation="horizontal", color=theme.CHART_BLUE, alpha=0.28, edgecolor=theme.SURFACE, linewidth=0.45)
        if residual.size >= 3:
            spread = float(np.std(residual, ddof=1))
            robust_spread = float(np.subtract(*np.percentile(residual, [75, 25]))) / 1.349
            spread = max(spread, robust_spread, np.finfo(float).eps)
            bandwidth = max(1.06 * spread * residual.size ** (-0.2), np.finfo(float).eps)
            low, high = Canvas2DMixin._diagnostic_limits(residual, np.asarray([-tolerance, tolerance]))
            grid = np.linspace(low, high, 160)
            density = np.exp(-0.5 * ((grid[:, None] - residual[None, :]) / bandwidth) ** 2).mean(axis=1)
            density /= bandwidth * np.sqrt(2.0 * np.pi)
            inset.plot(density, grid, color=theme.CHART_BLUE, linewidth=1.35)
            inset.fill_betweenx(grid, 0.0, density, color=theme.CHART_BLUE, alpha=0.1)
        inset.axhline(0.0, color=theme.CHART_REFERENCE, linestyle="--", linewidth=0.9)
        inset.axhline(tolerance, color=theme.CHART_BLUE, linestyle=":", linewidth=0.75)
        inset.axhline(-tolerance, color=theme.CHART_BLUE, linestyle=":", linewidth=0.75)
        inset.set_title("残差分布", fontsize=9, pad=2)
        inset.set_xlabel("密度", fontsize=8, labelpad=1)
        inset.set_ylabel("")
        inset.tick_params(axis="both", labelsize=7, length=2)

    def _waterfall(self, ax, data: dict) -> None:
        
        labels = [str(value) for value in data.get("labels", [])]
        values = [float(value) for value in data.get("values", [])]
        base = float(data.get("base_value", 0.0) or 0.0)
        if not labels or not values:
            self._empty(ax, data.get("message", "暂无单样本解释数据"))
            return
        count = min(len(labels), len(values))
        labels, values = labels[:count], values[:count]
        starts: list[float] = []
        running = base
        for value in values:
            starts.append(running)
            running += value
        positions = np.arange(count)
        colors = [theme.CHART_RED if value >= 0 else theme.CHART_GREEN for value in values]
        bars = ax.barh(positions, values, left=starts, color=colors, height=0.62, zorder=3)
        for index, (start, value) in enumerate(zip(starts, values)):
            endpoint = start + value
            if index < count - 1:
                ax.plot([endpoint, endpoint], [index + 0.31, index + 0.69], color=theme.CHART_REFERENCE, linewidth=1.0, zorder=2)
        display_labels = self._readable_category_labels(labels)
        self._set_category_plot_layout(ax, display_labels)
        ax.set_yticks(positions)
        ax.set_yticklabels(display_labels, rotation=0, ha="right", va="center")
        ax.tick_params(axis="y", labelsize=10, pad=6)
        ax.invert_yaxis()
        ax.axvline(base, color=theme.CHART_REFERENCE, linestyle=":", linewidth=1.25, label="模型基准值")
        ax.axvline(running, color=theme.CHART_BLUE, linestyle="--", linewidth=1.65, label="当前预测值")
        formal = data.get("formal_value")
        if formal is not None:
            ax.axvline(float(formal), color=theme.CHART_GREEN, linewidth=1.65, label="正式仿真值")
        endpoints = [base, running, *starts, *(start + value for start, value in zip(starts, values))]
        if formal is not None:
            endpoints.append(float(formal))
        radius = max((abs(point - base) for point in endpoints), default=1.0)
        if radius <= 0:
            radius = max(abs(base) * 0.05, 1.0)
        ax.set_xlim(base - radius * 1.16, base + radius * 1.16)
        for bar, value in zip(bars, values):
            bar.set_edgecolor(theme.SURFACE)
            bar.set_linewidth(0.55)
            endpoint = bar.get_x() + bar.get_width()
            offset = radius * 0.025
            ax.text(
                endpoint + (offset if value >= 0 else -offset),
                bar.get_y() + bar.get_height() / 2,
                f"{value:+.3g}",
                va="center",
                ha="left" if value >= 0 else "right",
                fontsize=10.5,
                fontweight="semibold",
            )
        domain = data.get("within_training_domain")
        domain_text = "训练域内" if domain is True else "训练域外" if domain is False else "训练域状态未知"
        summary = str(data.get("summary", ""))
        ax.text(0.0, 1.01, f"{summary}   |   {domain_text}", transform=ax.transAxes, ha="left", va="bottom", fontsize=9.5, color=theme.CHART_GRAY)
        ax.legend(loc="lower right", fontsize=9, frameon=True)

    def _mismatch_budget(self, ax, data: dict) -> None:

        labels = [str(value) for value in data.get("labels", [])]
        global_raw = np.asarray(data.get("global_values", []), dtype=float)
        local_raw = np.asarray(data.get("local_values", []), dtype=float)
        count = min(len(labels), len(global_raw), len(local_raw))
        if count <= 0:
            self._empty(ax, data.get("message", "暂无失配贡献预算数据"))
            return
        labels, global_raw, local_raw = labels[:count], global_raw[:count], local_raw[:count]
        global_share = 100.0 * global_raw / (float(np.sum(np.abs(global_raw))) or 1.0)
        local_share = 100.0 * local_raw / (float(np.sum(np.abs(local_raw))) or 1.0)
        positions = np.arange(count, dtype=float)
        global_bars = ax.barh(
            positions + 0.18, global_share, height=0.30, color="#93c5fd", alpha=0.78,
            label="全局平均重要性", zorder=2,
        )
        local_colors = [theme.CHART_RED if value >= 0 else theme.CHART_GREEN for value in local_share]
        local_bars = ax.barh(
            positions - 0.18, local_share, height=0.30, color=local_colors,
            label="当前方案贡献（带符号）", zorder=3,
        )
        ax.axvline(0.0, color=theme.CHART_REFERENCE, linewidth=1.15, linestyle="--", zorder=1)
        display_labels = self._readable_category_labels(labels)
        self._set_category_plot_layout(ax, display_labels)
        ax.set_yticks(positions)
        ax.set_yticklabels(display_labels, rotation=0, ha="right", va="center")
        ax.tick_params(axis="y", labelsize=10, pad=6)
        ax.invert_yaxis()
        extent = max(float(np.max(np.abs(global_share))), float(np.max(np.abs(local_share))), 1.0)
        ax.set_xlim(-extent * 1.28, extent * 1.28)
        for bar, value in zip(global_bars, global_share):
            ax.text(bar.get_width() + extent * 0.025, bar.get_y() + bar.get_height() / 2, f"全局 {value:.0f}%", va="center", fontsize=9, color="#1d4ed8")
        for bar, value in zip(local_bars, local_share):
            x = bar.get_width() + (extent * 0.025 if value >= 0 else -extent * 0.025)
            ax.text(x, bar.get_y() + bar.get_height() / 2, f"当前 {value:+.0f}%", ha="left" if value >= 0 else "right", va="center", fontsize=9, fontweight="semibold")
        ax.text(0.0, 1.01, str(data.get("summary", "")), transform=ax.transAxes, ha="left", va="bottom", fontsize=9.3, color=theme.CHART_GRAY)
        ax.legend(loc="lower right", fontsize=9, frameon=True)


    def _phase_comparison(self, ax, data: dict) -> None:
        ax.remove()
        arrays = [
            np.asarray(data.get("incident", []), dtype=float),
            np.asarray(data.get("target", []), dtype=float),
            np.asarray(data.get("residual", []), dtype=float),
        ]
        labels = list(data.get("labels", ["入射端面相位", "目标模式相位", "相位差"]))
        axes = self.figure.subplots(1, 3)
        maximum = max((float(np.nanmax(np.abs(array))) for array in arrays if array.ndim == 2 and array.size), default=np.pi)
        maximum = max(maximum, 1e-9)
        for index, (axis, array) in enumerate(zip(axes, arrays)):
            if array.ndim != 2 or not array.size:
                axis.axis("off")
                axis.text(0.5, 0.5, "无数据", ha="center", va="center", transform=axis.transAxes)
                continue
            image = axis.imshow(array, origin="lower", aspect="equal", cmap="twilight", vmin=-maximum, vmax=maximum)
            axis._panel_title_size = 12
            axis.set_title(labels[index] if index < len(labels) else f"相位{index + 1}")
            axis.set_xticks([])
            axis.set_yticks([])
        self.figure.subplots_adjust(left=0.04, right=0.875, bottom=0.08, top=0.86, wspace=0.22)
        color_axis = self.figure.add_axes([0.90, 0.18, 0.018, 0.60])
        color_axis._compact_diagnostic_inset = True
        self.figure.colorbar(image, cax=color_axis, label=str(data.get("unit", "rad")))
        if data.get("target_is_reference"):
            self.figure.text(0.5, 0.025, "目标模式采用光纤端面平相位参考", ha="center", fontsize=10)

    def _multi_plane_evolution(self, ax, data: dict) -> None:
        ax.remove()
        planes = list(data.get("planes", []) or [])
        if not planes:
            axis = self.figure.add_subplot(111)
            self._empty(axis, data.get("message", "暂无多平面数据"))
            return
        count = len(planes)
        cols = 3
        rows = int(np.ceil(count / cols))
        axes = np.atleast_1d(self.figure.subplots(rows, cols)).ravel()
        image = None
        for index, axis in enumerate(axes):
            if index >= count:
                axis.axis("off")
                continue
            item = planes[index]
            intensity = np.asarray(item.get("intensity", []), dtype=float)
            if intensity.ndim != 2 or not intensity.size:
                axis.axis("off")
                continue
            image = axis.imshow(intensity, origin="lower", aspect="equal", vmin=0.0, vmax=1.0)
            axis._panel_title_size = 10.5
            axis.set_title(f"z = {float(item.get('z', index)):.3g} mm")
            axis.set_xticks([])
            axis.set_yticks([])
        self.figure.subplots_adjust(left=0.04, right=0.86, bottom=0.07, top=0.90, wspace=0.16, hspace=0.34)
        if image is not None:
            color_axis = self.figure.add_axes([0.89, 0.18, 0.018, 0.62])
            color_axis._compact_diagnostic_inset = True
            self.figure.colorbar(image, cax=color_axis, label="归一化强度")
        if data.get("derived"):
            self.figure.text(0.5, 0.02, "由端面复场与高斯传播拟合外推", ha="center", fontsize=10)

    def _energy_flow(self, ax, data: dict) -> None:
        labels = [str(value) for value in data.get("labels", [])]
        cumulative = np.asarray(data.get("cumulative", []), dtype=float)
        losses = np.asarray(data.get("losses", []), dtype=float)
        if not labels or len(cumulative) != len(labels):
            self._empty(ax, data.get("message", "暂无能量分解数据"))
            return
        x = np.arange(len(labels))
        bars = ax.bar(x, cumulative, width=0.68)
        ax.plot(x, cumulative, marker="o", linewidth=2.0, label="剩余功率")
        for index, (bar, value) in enumerate(zip(bars, cumulative)):
            ax.text(bar.get_x() + bar.get_width()/2, value + max(cumulative.max(), 1.0)*0.018, f"{value:.2f}%", ha="center", va="bottom", fontsize=11)
            if index > 0 and index < len(losses) and losses[index] > 0:
                ax.text(index - 0.5, (cumulative[index-1] + value)/2, f"−{losses[index]:.2f}%", ha="center", va="center", fontsize=9.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=18)
        ax.set_ylim(0, max(105.0, float(cumulative.max()) * 1.12))
        ax.legend()

    def _before_after(self, ax, data: dict) -> None:
        ax.remove()
        before = dict(data.get("before", {}) or {})
        after = dict(data.get("after", {}) or {})
        axes = self.figure.subplots(1, 2)
        for axis, payload in zip(axes, (before, after)):
            coupling = payload.get("coupling_efficiency")
            system = payload.get("system_efficiency")
            names, values = [], []
            if isinstance(coupling, (int, float)):
                names.append("耦合效率")
                values.append(float(coupling))
            if isinstance(system, (int, float)):
                names.append("系统效率")
                values.append(float(system))
            if values:
                bars = axis.bar(names, values, width=0.58)
                self._annotate_bars(axis, bars, values, horizontal=False, enabled=True)
                axis.set_ylim(0, max(100.0, max(values)*1.18))
                axis.set_ylabel("效率 / %")
            else:
                axis.axis("off")
                axis.text(0.5, 0.5, "暂无效率数据", ha="center", va="center", transform=axis.transAxes)
            axis.set_title(str(payload.get("label", "方案")))
        params = list(data.get("parameters", []) or [])
        if params:
            lines = []
            for item in params[:8]:
                name = str(item.get("name", "参数"))
                after_value = item.get("after")
                lines.append(f"{name}：{after_value}")
            self.figure.text(0.5, 0.03, "　｜　".join(lines), ha="center", va="bottom", fontsize=9.5)
        self.figure.subplots_adjust(left=0.08, right=0.97, bottom=0.16, top=0.88, wspace=0.28)

    def _candidate_compare(self, ax, data: dict) -> None:
        candidates = list(data.get("candidates", []) or [])
        if not candidates:
            self._empty(ax, data.get("message", "暂无候选方案数据"))
            return
        labels = [str(item.get("label", f"方案{i+1}")) for i, item in enumerate(candidates)]
        formal = np.asarray([item.get("formal", np.nan) for item in candidates], dtype=float)
        predicted = np.asarray([item.get("predicted", np.nan) for item in candidates], dtype=float)
        x = np.arange(len(labels), dtype=float)
        width = 0.36
        valid_pred = np.isfinite(predicted)
        valid_formal = np.isfinite(formal)
        if np.any(valid_pred):
            ax.bar(x[valid_pred]-width/2, predicted[valid_pred], width, label="模型预测")
        if np.any(valid_formal):
            ax.bar(x[valid_formal]+width/2, formal[valid_formal], width, label="正式复核")
        for index, item in enumerate(candidates):
            if not bool(item.get("feasible", True)):
                ax.scatter([x[index]], [0], marker="x", s=70, linewidths=2, label="约束未通过" if index == 0 else None)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=18)
        ax.legend()

    def _convergence_curve(self, ax, data: dict) -> None:
        x = np.asarray(data.get("x", []), dtype=float)
        current = np.asarray(data.get("current", []), dtype=float)
        best = np.asarray(data.get("best", []), dtype=float)
        count = min(len(x), len(current), len(best))
        if count == 0:
            self._empty(ax, data.get("message", "暂无收敛数据"))
            return
        ax.plot(x[:count], current[:count], marker="o", markersize=3.5, linewidth=1.2, alpha=0.55, label="当前样本")
        ax.plot(x[:count], best[:count], linewidth=2.5, label="当前最佳")
        ax.scatter([x[count-1]], [best[count-1]], marker="*", s=120, zorder=5, label="最终最佳")
        ax.legend()

    def _correlation_heatmap(self, ax, data: dict) -> None:
        labels = [str(value) for value in data.get("labels", [])]
        matrix = np.asarray(data.get("matrix", []), dtype=float)
        if matrix.ndim != 2 or not labels or matrix.shape != (len(labels), len(labels)):
            self._empty(ax, data.get("message", "暂无相关性数据"))
            return
        image = ax.imshow(matrix, origin="upper", cmap="coolwarm", vmin=-1.0, vmax=1.0, aspect="equal")
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_yticklabels(labels)
        for row in range(len(labels)):
            for col in range(len(labels)):
                ax.text(col, row, f"{matrix[row, col]:.2f}", ha="center", va="center", fontsize=8.5)
        self._heatmap_image = image
        self._heatmap_colorbar = self.figure.colorbar(image, ax=ax, shrink=0.78, label="相关系数")


    def _adjustment_trajectory(self, ax, data: dict) -> None:
        ax.remove()
        top, bottom = self.figure.subplots(2, 1, sharex=True)
        x = np.asarray(data.get("x", []), dtype=float)
        efficiency = np.asarray(data.get("efficiency", []), dtype=float)
        count = min(len(x), len(efficiency))
        if count:
            top.plot(x[:count], efficiency[:count], marker="o", linewidth=2.2)
            top.set_ylabel("耦合效率 / %")
            top.set_title("效率提升轨迹")
        series = list(data.get("series", []) or [])
        for item in series:
            values = np.asarray(item.get("y", []), dtype=float)
            n = min(len(x), len(values))
            if n:
                scale = float(np.max(np.abs(values[:n]))) or 1.0
                bottom.plot(x[:n], values[:n]/scale, marker=".", label=str(item.get("label", "参数")))
        bottom.set_xlabel(str(data.get("x_label", "调节步数")))
        bottom.set_ylabel("归一化调节量")
        if series:
            bottom.legend(ncol=min(3, len(series)))
        self.figure.subplots_adjust(left=0.12, right=0.97, bottom=0.12, top=0.90, hspace=0.30)

    def _teaching_scan(self, ax, data: dict) -> None:
        ax.remove()
        top, bottom = self.figure.subplots(2, 1, sharex=True)
        x = np.asarray(data.get("x", []), dtype=float)
        primary = np.asarray(data.get("primary", []), dtype=float)
        n = min(len(x), len(primary))
        if n:
            top.plot(x[:n], primary[:n], linewidth=2.3, label=str(data.get("primary_label", "主要指标")))
            best = data.get("best_point")
            if isinstance(best, (list, tuple)) and len(best) >= 2:
                top.scatter([best[0]], [best[1]], marker="*", s=120, label="最佳点", zorder=5)
            top.legend()
        for item in list(data.get("linked_series", []) or []):
            values = np.asarray(item.get("y", []), dtype=float)
            count = min(len(x), len(values))
            if count:
                bottom.plot(x[:count], values[:count], linewidth=1.8, label=str(item.get("label", "联动量")))
        bottom.set_xlabel(str(data.get("x_label", "参数")))
        top.set_ylabel(str(data.get("y_label", "输出")))
        bottom.set_ylabel("同步变化量")
        if data.get("linked_series"):
            bottom.legend(ncol=min(3, len(data.get("linked_series", []))))
        self.figure.subplots_adjust(left=0.12, right=0.97, bottom=0.12, top=0.90, hspace=0.30)

    def _prepare_heatmap_data(self, data: dict) -> tuple[np.ndarray, list[float] | None]:
        z = np.asarray(data.get("z", []), dtype=float)
        if z.ndim != 2 or not z.size:
            return np.empty((0, 0)), None
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        if len(x) != z.shape[1]:
            x = np.arange(z.shape[1], dtype=float)
        if len(y) != z.shape[0]:
            y = np.arange(z.shape[0], dtype=float)
        fraction = data.get("auto_crop_fraction")
        if fraction is not None:
            rows, columns = _field_crop_slices(z, np.empty((0, 0)), fraction=float(fraction))
            z = z[rows, columns]
            x = x[columns]
            y = y[rows]
        requested = int(data.get("display_max_size", 0) or 0)
        if requested <= 0:
            viewport = max(256, int(getattr(self, "width", lambda: 768)()))
            requested = max(192, min(768, viewport // 2))
        z, x, y, _rows, _cols = _downsample_grid(
            z, x, y, max_rows=requested, max_cols=requested
        )
        extent = [float(x[0]), float(x[-1]), float(y[0]), float(y[-1])]
        return z, extent

    def _register_bar_items(self, bars, labels: list[str], data: dict) -> None:
        selected = str(data.get("selected_label", ""))
        self._item_artists = []
        self._item_labels = list(labels)
        for patch, label in zip(bars, labels):
            self._item_artists.append((patch, label))
            if selected and label == selected:
                patch.set_edgecolor(theme.CHART_ORANGE)
                patch.set_linewidth(2.2)
            else:
                patch.set_edgecolor(theme.SURFACE)
                patch.set_linewidth(0.55)

    @staticmethod
    def _annotate_bars(ax, bars, values, *, horizontal: bool, enabled: bool) -> None:
        if not enabled:
            return
        numeric = [float(value) for value in list(values)] if values is not None else []
        maximum = max((abs(value) for value in numeric), default=1.0) or 1.0
        for patch, value in zip(bars, numeric):
            text = f"{value:.3g}"
            if horizontal:
                offset = 0.012 * maximum
                x = value + offset if value >= 0 else value - offset
                ha = "left" if value >= 0 else "right"
                ax.text(x, patch.get_y() + patch.get_height() / 2.0, text, va="center", ha=ha, fontsize=11.5)
            else:
                offset = 0.018 * maximum
                y = value + offset if value >= 0 else value - offset
                va = "bottom" if value >= 0 else "top"
                ax.text(patch.get_x() + patch.get_width() / 2.0, y, text, ha="center", va=va, fontsize=11.5)

    def _beeswarm(self, ax, data: dict) -> None:
        labels = [str(value) for value in data.get("labels", [])]
        points = list(data.get("points", []) or [])
        if not labels or not points:
            self._empty(ax, data.get("message", "暂无蜂群数据"))
            return
        label_to_index = {label: index for index, label in enumerate(labels)}
        xs: list[float] = []
        ys: list[float] = []
        colors: list[str] = []
        for point_index, point in enumerate(points):
            label = str(point.get("feature", ""))
            if label not in label_to_index:
                continue
            base_y = float(label_to_index[label])
            sample_index = int(point.get("sample_index", point_index))
            jitter = (((sample_index * 37 + label_to_index[label] * 17) % 101) / 100.0 - 0.5) * 0.56
            xs.append(float(point.get("value", 0.0) or 0.0))
            ys.append(base_y + jitter)
            colors.append(str(point.get("color", theme.CHART_GRAY)))
        ax.scatter(xs, ys, s=16, c=colors, alpha=0.70, linewidths=0, zorder=3)
        ax.axvline(0.0, color=theme.CHART_REFERENCE, linewidth=1.2, linestyle="--", zorder=1)
        display_labels = self._readable_category_labels(labels)
        self._set_category_plot_layout(ax, display_labels)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(display_labels, rotation=0, ha="right", va="center")
        ax.tick_params(axis="y", labelsize=9.5, pad=6)
        ax.set_ylim(len(labels) - 0.45, -0.55)
        self._item_labels = labels

        importance = np.asarray(data.get("importance", []), dtype=float)
        if len(importance) >= len(labels):
            inset = ax.inset_axes([0.79, 0.075, 0.19, 0.85])
            inset._compact_diagnostic_inset = True
            maximum = float(np.max(np.abs(importance[:len(labels)]))) or 1.0
            inset.barh(range(len(labels)), importance[:len(labels)] / maximum, color="#93c5fd", height=0.52)
            inset.set_ylim(len(labels) - 0.45, -0.55)
            inset.set_xticks([0.0, 1.0])
            inset.set_xticklabels(["0", "1"])
            inset.set_yticks([])
            inset.set_title("mean(|SHAP|)", fontsize=8, pad=2)
        ax.text(0.0, 1.01, str(data.get("summary", "")), transform=ax.transAxes, ha="left", va="bottom", fontsize=9.3, color=theme.CHART_GRAY)
        ax.text(0.99, 0.015, "参数值：低  ◄───────►  高", transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5, color=theme.CHART_GRAY)

    @staticmethod
    def _rank_correlation(x: np.ndarray, y: np.ndarray) -> float | None:
        if len(x) < 3 or len(y) < 3:
            return None
        x_rank = np.argsort(np.argsort(x)).astype(float)
        y_rank = np.argsort(np.argsort(y)).astype(float)
        coefficient = np.corrcoef(x_rank, y_rank)[0, 1]
        return float(coefficient) if np.isfinite(coefficient) else None

    def _scatter_formula(self, ax, data: dict) -> None:
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        colors = data.get("point_colors") or None
        has_content = False
        count = min(len(x), len(y))
        x, y = x[:count], y[:count]
        if count:
            ax.scatter(x, y, s=25, c=colors[:count] if colors else theme.CHART_BLUE, alpha=0.56, label="SHAP样本", zorder=2)
            has_content = True
            low, high = float(np.min(x)), float(np.max(x))
            if high > low:
                q_low, q_high = np.percentile(x, [5, 95])
                ax.axvspan(q_low, q_high, color=theme.CHART_BLUE, alpha=0.055, zorder=0, label="主要训练区间")
                bins = min(10, max(4, int(np.sqrt(count))))
                edges = np.linspace(low, high, bins + 1)
                centers: list[float] = []
                medians: list[float] = []
                lower: list[float] = []
                upper: list[float] = []
                for index in range(bins):
                    mask = (x >= edges[index]) & (x <= edges[index + 1] if index == bins - 1 else x < edges[index + 1])
                    values = y[mask]
                    if len(values) < 2:
                        continue
                    centers.append(float(np.median(x[mask])))
                    medians.append(float(np.median(values)))
                    lower.append(float(np.percentile(values, 10)))
                    upper.append(float(np.percentile(values, 90)))
                if len(centers) >= 2:
                    centers_array = np.asarray(centers)
                    ax.fill_between(centers_array, lower, upper, color=theme.CHART_BLUE, alpha=0.13, label="10%–90%分散带", zorder=1)
                    ax.plot(centers_array, medians, color=theme.CHART_BLUE, linewidth=2.4, label="分箱中位趋势", zorder=4)

        formula_x = np.asarray(data.get("formula_x", []), dtype=float)
        formula_y = np.asarray(data.get("formula_y", []), dtype=float)
        if formula_x.size and formula_y.size:
            formula_count = min(len(formula_x), len(formula_y))
            order = np.argsort(formula_x[:formula_count])
            ax.plot(formula_x[:formula_count][order], formula_y[:formula_count][order], color="#475569", linewidth=2.0, linestyle="--", label="解析公式", zorder=5)
            has_content = True

        formal_x = np.asarray(data.get("formal_x", []), dtype=float)
        formal_y = np.asarray(data.get("formal_y", []), dtype=float)
        if formal_x.size and formal_y.size:
            formal_count = min(len(formal_x), len(formal_y))
            order = np.argsort(formal_x[:formal_count])
            ax.plot(formal_x[:formal_count][order], formal_y[:formal_count][order], color=theme.CHART_GREEN, linewidth=2.5, marker="s", markersize=3.8, label="正式仿真", zorder=6)
            has_content = True

        current_x = data.get("current_x")
        current_y = data.get("current_y")
        if isinstance(current_x, (int, float)) and isinstance(current_y, (int, float)):
            ax.scatter([float(current_x)], [float(current_y)], s=145, marker="*", color=theme.CHART_RED, edgecolors="#111827", linewidths=0.65, zorder=8, label="当前方案")
            has_content = True
        ax.axhline(0.0, color=theme.CHART_REFERENCE, linestyle="--", linewidth=1.0, zorder=1)

        if has_content:
            correlation = self._rank_correlation(x, y)
            domain = data.get("within_training_domain")
            domain_text = "训练域内" if domain is True else "训练域外" if domain is False else "训练域状态未知"
            rho = f"{correlation:+.2f}" if correlation is not None else "—"
            ax.text(0.985, 0.975, f"n = {count}\nSpearman ρ = {rho}\n{domain_text}", transform=ax.transAxes, ha="right", va="top", fontsize=9, color="#111827", bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": theme.CHART_REFERENCE, "alpha": 0.92})
            ax.legend(loc="lower left", fontsize=8.5, frameon=True, ncol=2)
            ax.text(0.0, 1.01, str(data.get("summary", "")), transform=ax.transAxes, ha="left", va="bottom", fontsize=9.2, color=theme.CHART_GRAY)
        else:
            self._empty(ax, data.get("message", "暂无依赖数据"))

    @staticmethod
    def _empty(ax, message: str) -> None:
        ax.axis("off")
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)

    def _heatmap_contour(self, ax, data: dict) -> None:
        z = np.asarray(data.get("z", []), dtype=float)
        contour = np.asarray(data.get("contour", []), dtype=float)
        if z.ndim != 2 or not z.size:
            self._empty(ax, data.get("message", "暂无场数据"))
            return
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        if len(x) != z.shape[1]:
            x = np.arange(z.shape[1], dtype=float)
        if len(y) != z.shape[0]:
            y = np.arange(z.shape[0], dtype=float)
        fraction = float(data.get("auto_crop_fraction", np.exp(-2.0)) or np.exp(-2.0))
        row_slice, column_slice = _field_crop_slices(z, contour, fraction=fraction)
        z_view = z[row_slice, column_slice]
        contour_view = contour[row_slice, column_slice] if contour.shape == z.shape else np.empty((0, 0))
        x_view = x[column_slice]
        y_view = y[row_slice]
        requested = int(data.get("display_max_size", 0) or 0)
        if requested <= 0:
            requested = max(192, min(768, max(256, int(getattr(self, "width", lambda: 768)())) // 2))
        z_view, x_view, y_view, row_idx, col_idx = _downsample_grid(
            z_view, x_view, y_view, max_rows=requested, max_cols=requested
        )
        if contour_view.size:
            contour_view = contour_view[np.ix_(row_idx, col_idx)]
        extent = [float(x_view[0]), float(x_view[-1]), float(y_view[0]), float(y_view[-1])]
        image = ax.imshow(z_view, origin="lower", aspect="equal", extent=extent)
        self.figure.colorbar(image, ax=ax, shrink=0.78, label="强度")
        if contour_view.size and float(np.nanmax(contour_view)) > 0.0:
            level = float(np.nanmax(contour_view)) * fraction
            ax.contour(
                x_view,
                y_view,
                contour_view,
                levels=[level],
                colors=[theme.FIBER_CORE],
                linewidths=1.25,
            )
        ax.set_aspect("equal", adjustable="box")

    def _heatmap_pair(self, data: dict) -> None:
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        first = np.asarray(data.get("z1", []), dtype=float)
        second = np.asarray(data.get("z2", []), dtype=float)
        shared_low = float(np.nanmin([np.nanmin(first), np.nanmin(second)])) if first.size and second.size else None
        shared_high = float(np.nanmax([np.nanmax(first), np.nanmax(second)])) if first.size and second.size else None
        requested = int(data.get("display_max_size", 0) or 0)
        if requested <= 0:
            requested = max(192, min(768, max(256, int(getattr(self, "width", lambda: 768)())) // 2))
        for index, (key, title) in enumerate((("z1", "入射场"), ("z2", "光纤模式")), 1):
            ax = self.figure.add_subplot(1, 2, index)
            z = np.asarray(data.get(key, []), dtype=float)
            if z.size:
                x_values = x if len(x) == z.shape[1] else np.arange(z.shape[1], dtype=float)
                y_values = y if len(y) == z.shape[0] else np.arange(z.shape[0], dtype=float)
                z, x_values, y_values, _rows, _cols = _downsample_grid(
                    z, x_values, y_values, max_rows=requested, max_cols=requested
                )
                ax.imshow(
                    z,
                    origin="lower",
                    aspect="equal",
                    extent=[float(x_values[0]), float(x_values[-1]), float(y_values[0]), float(y_values[-1])],
                    vmin=shared_low,
                    vmax=shared_high,
                )
                ax.set_title(title)
                ax.set_xlabel("x / μm")
                ax.set_ylabel("y / μm")
        self.figure.suptitle(data.get("title", ""))

    @staticmethod
    def _raytrace_artist_model(data: dict) -> dict:

        surfaces = list(data.get("surfaces", []) or [])
        rays = list(data.get("rays", []) or [])
        selected = data.get("selected_surface_index")

        surface_segments: list[np.ndarray] = []
        surface_colors: list[str] = []
        surface_widths: list[float] = []
        group_rims: dict[str, list[tuple[float, float, float, float]]] = {}
        for surface in surfaces:
            z = float(surface.get("z", 0.0) or 0.0)
            aperture = float(surface.get("aperture", 0.0) or 0.0)
            low = float(surface.get("t_min", -aperture))
            high = float(surface.get("t_max", aperture))
            transverse = np.linspace(low, high, 72)
            centre = 0.5 * (low + high)
            radius = float(surface.get("radius", float("inf")) or float("inf"))
            conic = float(surface.get("conic", 0.0) or 0.0)
            rho = np.abs(transverse - centre)
            if np.isfinite(radius) and 1.0e-12 < abs(radius) < 1.0e12:
                inside = np.maximum(1.0 - (1.0 + conic) * np.square(rho / radius), 0.0)
                denominator = radius * (1.0 + np.sqrt(inside))
                sag = np.divide(
                    np.square(rho),
                    denominator,
                    out=np.zeros_like(rho),
                    where=np.abs(denominator) > 1.0e-12,
                )
            else:
                sag = np.zeros_like(rho)
            segment = np.column_stack((z + sag, transverse))
            surface_segments.append(segment)
            is_selected = int(surface.get("surface_index", -1)) == selected or bool(
                surface.get("selected")
            )
            surface_colors.append(
                theme.SURFACE_SELECTED_EDGE if is_selected else theme.SURFACE_EDGE
            )
            surface_widths.append(2.0 if is_selected else SURFACE_LINEWIDTH_2D)
            group = str(surface.get("group_id", "") or "")
            if group:
                group_rims.setdefault(group, []).append(
                    (float(segment[0, 0]), low, float(segment[-1, 0]), high)
                )

        rim_segments: list[np.ndarray] = []
        for group_surfaces in group_rims.values():
            if len(group_surfaces) < 2:
                continue
            first, second = group_surfaces[0], group_surfaces[-1]
            rim_segments.extend(
                [
                    np.asarray([[first[0], first[1]], [second[0], second[1]]], dtype=float),
                    np.asarray([[first[2], first[3]], [second[2], second[3]]], dtype=float),
                ]
            )

        grouped: dict[str, list[np.ndarray]] = {}
        for ray in rays:
            z_values = np.asarray(ray.get("z", []), dtype=float)
            transverse = np.asarray(ray.get("t", ray.get("y", [])), dtype=float)
            count = min(len(z_values), len(transverse))
            if count >= 2:
                grouped.setdefault(str(ray.get("role", "regular")), []).append(
                    np.column_stack((z_values[:count], transverse[:count]))
                )

        scale_visible = bool(data.get("scale_label")) and data.get("scale_mode") != "physical"
        signature = (
            len(surface_segments),
            len(rim_segments),
            tuple(sorted(grouped)),
            scale_visible,
        )
        return {
            "surface_segments": surface_segments,
            "surface_colors": surface_colors,
            "surface_widths": surface_widths,
            "rim_segments": rim_segments,
            "grouped_rays": grouped,
            "scale_visible": scale_visible,
            "signature": signature,
        }

    @staticmethod
    def _ray_role_style(role: str) -> tuple[str, float, float, str]:
        styles = {
            "chief": (theme.RAY_CHIEF, 1.45, 0.92, "solid"),
            "marginal": (theme.RAY_MARGINAL, 1.0, 0.76, "solid"),
            "regular": (theme.RAY_REGULAR, RAY_LINEWIDTH_2D, RAY_ALPHA_2D, "solid"),
            "failed": (theme.RAY_FAILED, 1.05, 0.95, "dashed"),
        }
        return styles.get(role, styles["regular"])

    def _raytrace_section(self, ax, data: dict) -> None:
        model = self._raytrace_artist_model(data)

        self._raytrace_surface_collection = LineCollection(
            model["surface_segments"],
            colors=model["surface_colors"],
            linewidths=model["surface_widths"],
            alpha=SURFACE_ALPHA_2D,
        )
        ax.add_collection(self._raytrace_surface_collection)

        self._raytrace_rim_collection = LineCollection(
            model["rim_segments"],
            colors=[theme.SURFACE_EDGE],
            linewidths=0.55,
            alpha=0.42,
        )
        ax.add_collection(self._raytrace_rim_collection)

        self._raytrace_ray_collections = {}
        for role, segments in model["grouped_rays"].items():
            color, width, alpha, linestyle = self._ray_role_style(role)
            collection = LineCollection(
                segments,
                colors=[color],
                linewidths=width,
                alpha=alpha,
                linestyles=linestyle,
            )
            ax.add_collection(collection)
            self._raytrace_ray_collections[role] = collection

        self._raytrace_axis_line = ax.axhline(
            0.0, linewidth=0.75, alpha=0.55, color=theme.OPTICAL_AXIS
        )
        self._raytrace_scale_text = None
        if model["scale_visible"]:
            self._raytrace_scale_text = ax.text(
                0.99,
                0.015,
                str(data.get("scale_label", "")),
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=11,
                color=theme.STATUS_STALE,
            )
        self._raytrace_signature = model["signature"]
        fit_optical_section_2d(ax, data)
        ax.set_aspect("auto")

    def _update_raytrace_section(self, ax, data: dict) -> bool:
        model = self._raytrace_artist_model(data)
        if (
            self._raytrace_surface_collection is None
            or self._raytrace_rim_collection is None
            or model["signature"] != self._raytrace_signature
        ):
            return False

        self._raytrace_surface_collection.set_segments(model["surface_segments"])
        self._raytrace_surface_collection.set_color(model["surface_colors"])
        self._raytrace_surface_collection.set_linewidth(model["surface_widths"])
        self._raytrace_rim_collection.set_segments(model["rim_segments"])

        for role, segments in model["grouped_rays"].items():
            collection = self._raytrace_ray_collections.get(role)
            if collection is None:
                return False
            color, width, alpha, linestyle = self._ray_role_style(role)
            collection.set_segments(segments)
            collection.set_color([color])
            collection.set_linewidth(width)
            collection.set_alpha(alpha)
            collection.set_linestyle(linestyle)

        if self._raytrace_scale_text is not None:
            self._raytrace_scale_text.set_text(str(data.get("scale_label", "")))
        fit_optical_section_2d(ax, data)
        ax.set_aspect("auto")
        return True
