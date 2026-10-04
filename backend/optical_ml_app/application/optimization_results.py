"""Render the original chart as safe vector presentation, without Qt."""
from io import StringIO
from threading import RLock
from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.backends.backend_svg import FigureCanvasSVG
from shared_presentation.optimization_results import candidate_rows, opt_chart_payload
from shared_presentation.plotting.basic_charts import chart_style, draw_basic_chart, apply_high_contrast_axes
from shared_presentation import theme_tokens as theme

_render_lock = RLock()

def result_presentation(result: dict, chart: str, width: int, height: int) -> dict:
    plot = opt_chart_payload(result, chart)
    return dict(rows=candidate_rows(result), **chart_presentation(plot,width,height), message='' if plot else '优化完成，暂无该图数据。')


def chart_presentation(plot: dict | None, width: int, height: int) -> dict:
    svg = ''
    summary = ''
    if plot:
        summary = plot.get('description') or (f"数据点：{len(plot.get('x',[]))}　｜　横轴：{plot.get('x_label','—')}　｜　纵轴：{plot.get('y_label','—')}　｜　数据来源：{plot.get('source','预览')}" if plot['kind']=='line' else f"项目：{len(plot.get('values',[]))}　｜　数据来源：{plot.get('source','预览')}")
        with _render_lock, rc_context(chart_style()):
            figure = Figure(figsize=(width/100,height/100),dpi=100,facecolor=theme.SCENE_BACKGROUND)
            FigureCanvasSVG(figure)
            axis = figure.add_subplot(111)
            draw_basic_chart(axis,plot)
            axis.set_title(plot.get('title',''),pad=8)
            axis.set_xlabel(plot.get('x_label',''))
            axis.set_ylabel(plot.get('y_label',''),rotation=90,labelpad=12,va='center')
            apply_high_contrast_axes(figure)
            figure.subplots_adjust(left=.15,right=.965,bottom=.24 if plot['kind']=='line' else .20,top=.86)
            output=StringIO()
            figure.savefig(output,format='svg',facecolor=theme.SCENE_BACKGROUND,metadata={'Date':None})
            svg=output.getvalue()
    return dict(svg=svg,summary=summary)
