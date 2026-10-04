"""Original analysis formatting and spot illustration data without Qt."""
import math


def format_teaching_metric(key, value, unit=''):
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return '是' if value else '否'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return '无效'
    if unit == '%':
        return f'{number * 100:.4g}%'
    if unit == '条':
        return f'{int(number)} 条'
    if unit:
        return f'{number:.6g} {unit}'
    return f'{number:.6g}'


def spot_illustration(metrics):
    rms = 0.0
    for key in ('rms_spot_radius_um', 'rms_um'):
        try:
            value = float(metrics.get(key))
            if math.isfinite(value):
                rms = value
                break
        except (TypeError, ValueError):
            continue
    radius = max(20, min(68, 22 + rms * 1.4))
    return {'rings': [{'radius':int(radius*factor),'color':color}
                      for factor,color in ((2.0,'#7F1D1D'),(1.45,'#DC2626'),(.9,'#F97316'),(.42,'#FEF3C7'))],
            'caption': f'接收面光斑 · RMS 半径 {rms:.3g} μm'}


def scene_analysis_presentation(scene):
    def metrics(kind):
        result = scene.get('results',{}).get(kind) or {}
        valid = result.get('status')=='completed' and not result.get('stale') and result.get('scene_revision')==scene['revision']
        return dict(result.get('metrics') or {}) if valid else None
    spot, coupling = metrics('spot'), metrics('coupling')
    total = next((coupling[key] for key in ('total_coupling_efficiency','coupling_efficiency')
                  if coupling.get(key) is not None),None) if coupling is not None else None
    detail = '耦合损耗 '+format_teaching_metric('coupling_loss_db',coupling['coupling_loss_db'],'dB') if coupling and coupling.get('coupling_loss_db') is not None else ''
    return {'imaging_available':spot is not None,
            'imaging_summary':'RMS 光斑半径  '+format_teaching_metric('rms_spot_radius_um',spot.get('rms_spot_radius_um',spot.get('rms_um')),'μm') if spot is not None else '',
            'spot':spot_illustration(spot) if spot is not None else None,
            'coupling_pill':'总耦合效率：'+format_teaching_metric('total_coupling_efficiency',total,'%'),
            'coupling_detail':detail}
