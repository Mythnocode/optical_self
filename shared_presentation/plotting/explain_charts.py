"""Original Matplotlib explanation charts shared by Qt and the API."""
import numpy as np
from matplotlib.patches import Patch
from shared_presentation import theme_tokens as theme
EXPLAIN_CHART_KINDS = {"barh", "beeswarm", "waterfall", "dependence_grid", "dependence_fit_ci", "physics_consistency"}

def apply_explain_margins(figure, data):
    custom_bottom = data.get('plot_bottom_margin')
    if custom_bottom is not None:
        figure.subplots_adjust(left=.15, right=.965, bottom=min(.42, max(.18, float(custom_bottom))), top=.86)
    elif data.get('kind') in {'beeswarm', 'waterfall', 'barh'}:
        figure.subplots_adjust(left=.235, right=.965, bottom=.22, top=.86)
    else:
        figure.subplots_adjust(left=.155, right=.96, bottom=.22, top=.86)

class ExplainChartsMixin:
    @staticmethod
    def _readable_category_labels(labels: list[str], *, max_chars: int = 16) -> list[str]:
        """把过长的分类标签拆行或截断，避免坐标轴文字互相覆盖。"""
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
        """根据分类标签长度动态调整左、右、上、下边距。"""
        longest = max((max(len(part) for part in label.split("\n")) for label in labels), default=6)
        left = min(0.34, max(0.22, 0.16 + 0.008 * longest))
        ax.figure.subplots_adjust(left=left, right=0.96, bottom=0.17, top=0.86)

    def _waterfall(self, ax, data: dict) -> None:
        """绘制特征贡献从基准值累加到预测值的瀑布图。"""
        
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
        colors = [theme.CHART_ORANGE if value >= 0 else theme.CHART_CYAN for value in values]
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
        ax.axvline(base, color=theme.CHART_REFERENCE, linestyle=":", linewidth=1.25, label="模型平均基准")
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
        domain_text = "在训练范围内" if domain is True else "超出训练范围" if domain is False else "训练范围未知"
        summary = str(data.get("summary", ""))
        ax.text(0.0, 1.01, f"{summary}   |   {domain_text}", transform=ax.transAxes, ha="left", va="bottom", fontsize=11.0, color=theme.CHART_GRAY)
        handles, legend_labels = ax.get_legend_handles_labels()
        handles.extend([
            Patch(facecolor=theme.CHART_ORANGE, edgecolor="none", label="正向贡献"),
            Patch(facecolor=theme.CHART_CYAN, edgecolor="none", label="负向贡献"),
        ])
        ax.legend(handles=handles, loc="lower right", fontsize=10.5, frameon=True)

    def _register_bar_items(self, bars, labels: list[str], data: dict) -> None:
        """登记柱状图 artist 与标签，供点击选择和交互回调使用。"""
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
        """按配置在柱状图上方或右侧标注数值。"""
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
        """绘制带抖动的样本分布图，避免相同值完全重叠。"""
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
            inset.set_title("平均重要性", fontsize=8, pad=2)
        ax.text(0.0, 1.01, str(data.get("summary", "")), transform=ax.transAxes, ha="left", va="bottom", fontsize=10.8, color=theme.CHART_GRAY)
        ax.text(0.99, 0.015, "参数值：低  ◄───────►  高", transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5, color=theme.CHART_GRAY)

    def _dependence_grid(self, ax, data: dict) -> None:
        """绘制 8 个设计变量的总归因依赖网格（2×4），每格按相关性着色。"""
        ax.remove()
        panels = list(data.get("panels", []) or [])
        if not panels:
            axis = self.figure.add_subplot(111)
            self._empty(axis, data.get("message", "暂无依赖网格数据"))
            return
        axes = np.atleast_1d(self.figure.subplots(2, 4)).ravel()
        for index, axis in enumerate(axes):
            if index >= len(panels):
                axis.axis("off")
                continue
            panel = panels[index]
            x = np.asarray(panel.get("x", []), dtype=float)
            y = np.asarray(panel.get("y", []), dtype=float)
            color = np.asarray(panel.get("color", []), dtype=float)
            count = min(len(x), len(y))
            if count < 1:
                axis.axis("off")
                continue
            x, y = x[:count], y[:count]
            color = color[:count] if len(color) >= count else None
            scatter = axis.scatter(x, y, c=color, cmap="RdBu_r", alpha=0.7, s=18, linewidths=0)
            axis.axhline(0.0, color=theme.CHART_REFERENCE, lw=0.8, alpha=0.6)
            axis.set_title(str(panel.get("label", "")), fontsize=10.5, fontweight="semibold")
            axis.set_xlabel(str(panel.get("label", "")), fontsize=8.5)
            axis.set_ylabel(str(data.get("y_label", "归因值")), fontsize=8.5)
            axis.grid(True, alpha=0.3, linestyle="--")
            if color is not None and color.size and len(np.unique(color)) > 1:
                colorbar = self.figure.colorbar(scatter, ax=axis, shrink=0.88, pad=0.02)
                colorbar.set_label(str(panel.get("color_label", "")), fontsize=7.5)
                colorbar.ax.tick_params(labelsize=7)
        self.figure.suptitle(
            str(data.get("title", "SHAP 特征依赖网格图")), y=1.02, fontsize=15, fontweight="semibold"
        )
        self.figure.subplots_adjust(left=0.07, right=0.97, bottom=0.10, top=0.88, wspace=0.42, hspace=0.52)

    def _dependence_fit_ci(self, ax, data: dict) -> None:
        """绘制 8 个设计变量总归因的单变量依赖趋势（2×4，二次拟合 + 置信带）。"""
        ax.remove()
        panels = list(data.get("panels", []) or [])
        if not panels:
            axis = self.figure.add_subplot(111)
            self._empty(axis, data.get("message", "暂无依赖趋势数据"))
            return
        axes = np.atleast_1d(self.figure.subplots(2, 4)).ravel()
        for index, axis in enumerate(axes):
            if index >= len(panels):
                axis.axis("off")
                continue
            panel = panels[index]
            x = np.asarray(panel.get("x", []), dtype=float)
            y = np.asarray(panel.get("y", []), dtype=float)
            count = min(len(x), len(y))
            if count < 3:
                axis.axis("off")
                continue
            x, y = x[:count], y[:count]
            order = np.argsort(x)
            xs, ys = x[order], y[order]
            axis.scatter(xs, ys, s=16, alpha=0.7, color=theme.CHART_BLUE)
            try:
                coef = np.polyfit(xs, ys, 2)
                xg = np.linspace(float(xs.min()), float(xs.max()), 200)
                yg = np.polyval(coef, xg)
                ypred = np.polyval(coef, xs)
                resid = ys - ypred
                sd = float(resid.std())
                ss_res = float(((ys - ypred) ** 2).sum())
                ss_tot = float(((ys - ys.mean()) ** 2).sum())
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
                axis.plot(xg, yg, color=theme.CHART_ORANGE, lw=1.5)
                axis.fill_between(xg, yg - 1.96 * sd, yg + 1.96 * sd, color=theme.CHART_ORANGE, alpha=0.15)
            except (TypeError, ValueError, np.linalg.LinAlgError):
                r2 = 0.0
            axis.axhline(0.0, color=theme.CHART_REFERENCE, lw=0.8, alpha=0.6)
            axis.set_title(f"{panel.get('label', '')}  (R2={r2:.2f})", fontsize=10.5)
            axis.set_xlabel(str(panel.get("label", "")), fontsize=8.5)
            axis.set_ylabel(str(data.get("y_label", "归因值")), fontsize=8.5)
            axis.grid(True, alpha=0.3, linestyle="--")
        self.figure.suptitle(
            str(data.get("title", "SHAP 单变量依赖趋势图")), y=1.02, fontsize=15, fontweight="semibold"
        )
        self.figure.subplots_adjust(left=0.07, right=0.97, bottom=0.10, top=0.88, wspace=0.34, hspace=0.52)

    def _physics_consistency(self, ax, data: dict) -> None:
        """绘制 SHAP 重要性 vs 物理解析弹性的一致性散点。"""
        x = np.asarray(data.get("x", []), dtype=float)
        y = np.asarray(data.get("y", []), dtype=float)
        labels = [str(value) for value in data.get("labels", [])]
        count = min(len(x), len(y))
        if count < 1:
            self._empty(ax, data.get("message", "暂无物理一致性数据"))
            return
        x, y = x[:count], y[:count]
        ax.scatter(x, y, s=58, color=theme.CHART_BLUE, alpha=0.82, zorder=3, linewidths=0)
        for xi, yi, label in zip(x, y, labels[:count]):
            ax.annotate(
                label,
                (xi, yi),
                textcoords="offset points",
                xytext=(6, 6),
                fontsize=9,
                color=theme.CHART_GRAY,
            )
        # 最小二乘参考线（过原点，量级跨度大时用对数不可靠，故用线性斜率近似）
        if count >= 2 and float(np.sum(x * x)) > 0:
            slope = float(np.sum(x * y) / np.sum(x * x))
            line_x = np.linspace(0.0, float(np.max(x)), 100)
            ax.plot(line_x, slope * line_x, color=theme.CHART_ORANGE, linestyle="--", linewidth=1.4, label="最小二乘参考")
        else:
            ax.plot([0, 1], [0, 1], color=theme.CHART_ORANGE, linestyle="--", linewidth=1.4, label="参考")
        pearson = data.get("pearson")
        spearman = data.get("spearman")
        stats: list[str] = []
        if isinstance(pearson, (int, float)) and np.isfinite(float(pearson)):
            stats.append(f"Pearson r = {float(pearson):+.3f}")
        if isinstance(spearman, (int, float)) and np.isfinite(float(spearman)):
            stats.append(f"Spearman ρ = {float(spearman):+.3f}")
        if stats:
            ax.text(0.985, 0.975, "\n".join(stats), transform=ax.transAxes, ha="right", va="top", fontsize=9.5, color=theme.CHART_GRAY, bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": theme.CHART_REFERENCE, "alpha": 0.92})
        ax.legend(loc="upper left", fontsize=9)
        ax.text(0.0, 1.01, str(data.get("summary", "")), transform=ax.transAxes, ha="left", va="bottom", fontsize=9.2, color=theme.CHART_GRAY)

    @staticmethod
    def _empty(ax, message: str) -> None:
        """在没有有效数据时绘制统一的空结果提示。"""
        ax.axis("off")
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes)

    def draw_explain_chart(self, ax, data):
        kind = data.get("kind")
        if kind == "barh":
            labels = [str(v) for v in data.get("labels", [])]
            values = data.get("values", [])
            bars = ax.barh(labels, values, color=data.get("colors") or None)
            self._register_bar_items(bars, labels, data)
            self._annotate_bars(ax, bars, values, horizontal=True, enabled=bool(data.get("show_values")))
            ax.invert_yaxis()
        else:
            getattr(self, "_" + kind)(ax, data)
        if kind in {"dependence_grid", "dependence_fit_ci"}:
            return
        ax.set_title(data.get("title", "") if kind == "barh" else "", pad=8)
        ax.set_xlabel(data.get("x_label", ""))
        ax.set_ylabel(data.get("y_label", ""), rotation=90, labelpad=28 if kind in {"waterfall", "beeswarm"} else 12, va="center")
        if kind in {"beeswarm", "physics_consistency"}:
            ax.grid(True, alpha=0.72, color=theme.CHART_GRID)
        else:
            ax.grid(False)
