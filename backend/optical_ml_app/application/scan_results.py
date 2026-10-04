"""Present recorded scan responses using the original line/heatmap display policy."""
from shared_presentation.scan_results import scan_curve_payload
from backend.optical_ml_app.application.optimization_results import chart_presentation


def result_presentation(result: dict, width: int, height: int) -> dict:
    metric = next(iter(result.get('response_metrics') or result.get('response_values') or []), 'coupling_efficiency')
    response = {'coupling_efficiency':'耦合效率','rms_spot_radius_um':'RMS 光斑','strehl_estimate_marechal':'Strehl','edge_power':'边缘功率'}.get(metric,metric)
    plot = scan_curve_payload(result, response)
    if not plot:
        return dict(svg='',plot=None,summary='',message='扫描完成，但没有可绘制的响应曲线。')
    if plot['kind'] == 'empty':
        return dict(svg='',plot=None,summary='',message=plot['message'])
    if plot['kind'] == 'line':
        return dict(plot=None, message='', **chart_presentation(plot,width,height))
    # The original FastHeatmapWidget uses image dimensions when x/y are absent.
    # Its scan payload supplies extent only, so preserve that square pixel aspect.
    return dict(svg='',plot=plot,summary=f"网格：{len(plot['z'])} × {len(plot['z'][0])}　｜　数据来源：{plot.get('source','预览')}",message='')
