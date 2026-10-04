"""Original plot margins, shared by Qt and headless figure export."""

def apply_safe_plot_margins(figure, data: dict, kind: str) -> None:
    """为嵌入式结果工作区预留稳定的标题和坐标轴标签空间。

    Embedded plots have a fixed visual slot.  A chart must adapt to that slot rather
    than draw labels outside it and rely on clipping.  Composite plots keep their
    own hand-tuned layouts; ordinary 2-D charts use a shared safe margin.
    """
    from shared_presentation.plotting.explain_charts import EXPLAIN_CHART_KINDS, apply_explain_margins
    if kind in EXPLAIN_CHART_KINDS:
        apply_explain_margins(figure, data)
        return
    if kind in {"heatmap_pair", "phase_comparison", "multi_plane_evolution", "before_after", "profile_pair", "adjustment_trajectory", "teaching_scan"}:
        return
    if kind in {"optical_scene_3d", "raytrace3d"}:
        return
    try:
        custom_bottom = data.get("plot_bottom_margin") if isinstance(data, dict) else None
        # Embedded Qt canvases need *inside-the-figure* safety space.  Using
        # tight_layout alone is not enough because the surrounding result card
        # can clip the title/axis labels before Matplotlib gets another resize.
        # Keep a deliberately larger title band and x/y label band instead of
        # shrinking fonts.  This is shared by training diagnostics, research
        # plots, validation plots and ordinary result charts.
        if custom_bottom is not None:
            bottom = min(0.42, max(0.18, float(custom_bottom)))
            figure.subplots_adjust(left=0.15, right=0.965, bottom=bottom, top=0.86)
            return
        if kind == "research_preview":
            figure.subplots_adjust(left=0.145, right=0.965, bottom=0.23, top=0.87)
        elif kind == "correlation_heatmap":
            figure.subplots_adjust(left=0.27, right=0.90, bottom=0.19, top=0.86)
        elif kind in {"candidate_compare", "bar", "bar_grouped", "target_achievement"}:
            figure.subplots_adjust(left=0.15, right=0.965, bottom=0.20, top=0.86)
        elif kind == "histogram":
            figure.subplots_adjust(left=0.14, right=0.965, bottom=0.22, top=0.86)
        elif kind in {"parameter_response", "validation_scatter", "residual", "scatter_formula", "convergence_curve", "line", "line_multi", "scatter"}:
            figure.subplots_adjust(left=0.15, right=0.965, bottom=0.24, top=0.86)
        elif kind in {"beeswarm", "mismatch_budget", "waterfall", "barh"}:
            figure.subplots_adjust(left=0.235, right=0.965, bottom=0.22, top=0.86)
        else:
            figure.subplots_adjust(left=0.155, right=0.96, bottom=0.22, top=0.86)
    except Exception:
        pass
