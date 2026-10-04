"""Native line and bar chart drawing shared by Qt and API presentation."""
import numpy as np
from cycler import cycler
from matplotlib.figure import Figure
from shared_presentation import theme_tokens as theme

def font_config() -> dict:
    from matplotlib import font_manager
    known = {str(item.name) for item in font_manager.fontManager.ttflist}
    def choose(candidates, fallback):
        return next((name for name in candidates if name in known),fallback)
    latin = choose(('Times New Roman','Liberation Serif','Noto Serif','DejaVu Serif'),'DejaVu Serif')
    cjk = choose(('Microsoft YaHei','Noto Sans CJK SC','Source Han Sans SC','Noto Sans CJK JP','Noto Serif CJK JP','WenQuanYi Micro Hei'),'DejaVu Sans')
    families = list(dict.fromkeys([latin,cjk,'DejaVu Sans']))
    return {'font.family':families,'font.serif':families,'font.sans-serif':[cjk,'Noto Sans','DejaVu Sans'],'mathtext.fontset':'dejavuserif','axes.unicode_minus':False}

def chart_style() -> dict:
    return {**font_config(),'font.size':13.,'axes.titlesize':17.,'axes.titleweight':'semibold','axes.labelsize':14.,'xtick.labelsize':12.,'ytick.labelsize':12.,'legend.fontsize':12.,'axes.formatter.useoffset':False,'figure.facecolor':theme.CHART_BACKGROUND,'savefig.facecolor':theme.CHART_BACKGROUND,'axes.facecolor':theme.CHART_BACKGROUND,'axes.edgecolor':theme.CHART_AXIS,'axes.labelcolor':theme.CHART_AXIS,'axes.titlecolor':theme.TEXT_PRIMARY,'axes.prop_cycle':cycler(color=theme.CHART_SERIES),'text.color':theme.TEXT_PRIMARY,'xtick.color':theme.CHART_AXIS,'ytick.color':theme.CHART_AXIS,'grid.color':theme.CHART_GRID,'grid.alpha':.72,'legend.facecolor':theme.SURFACE,'legend.edgecolor':theme.BORDER,'legend.framealpha':.96}

def category_labels(labels, max_chars=14):
    result=[]
    for raw in labels:
        text=str(raw).strip() or '—'
        if '｜' in text:
            left,right=text.split('｜',1)
            if len(text)>max_chars: text=f'{left}\n{right}'
        elif len(text)>max_chars:
            split_at=max(6,min(len(text)-1,max_chars//2))
            text=f'{text[:split_at]}\n{text[split_at:max_chars-1]}…'
        result.append(text)
    return result

def draw_basic_chart(ax,data):
    """Draw only the native line/bar branch; Qt retains its interaction registry."""
    if data['kind']=='line':
        label=str(data.get('series_label') or data.get('label') or '').strip()
        ax.plot(data.get('x',[]),data.get('y',[]),linewidth=1.8,label=label or None)
        reference=data.get('reference_y')
        if isinstance(reference,(int,float)) and np.isfinite(float(reference)):
            ax.axhline(float(reference),color=theme.CHART_REFERENCE,linestyle='--',linewidth=1.2,label=str(data.get('reference_label') or '测试集 RMSE').strip())
        if label or isinstance(reference,(int,float)): ax.legend()
        return None
    labels=category_labels(data.get('labels',[]))
    values=data.get('values',[])
    bars=ax.bar(labels,values,color=data.get('colors') or None)
    if data.get('show_values'):
        numeric=[float(value) for value in values]
        maximum=max((abs(value) for value in numeric),default=1.) or 1.
        for patch,value in zip(bars,numeric):
            offset=.018*maximum
            ax.text(patch.get_x()+patch.get_width()/2,value+offset if value>=0 else value-offset,f'{value:.3g}',ha='center',va='bottom' if value>=0 else 'top',fontsize=11.5)
    ax.tick_params(axis='x',rotation=0)
    return bars


def draw_scatter_chart(ax, data):
    """Native scatter points and zero line; other native overlays remain in Qt."""
    label = str(data.get('series_label') or data.get('label') or '').strip()
    ax.scatter(data.get('x', []), data.get('y', []), s=16, alpha=.72, label=label or None)
    if bool(data.get('zero_line', False)):
        ax.axhline(0.0, color=theme.CHART_REFERENCE, linestyle='--', linewidth=1.0)
    if label:
        ax.legend()


def apply_high_contrast_axes(figure: Figure) -> None:
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
