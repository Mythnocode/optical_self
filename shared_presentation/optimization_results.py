"""Original optimization result labels and chart data, without Qt."""
def status_label(value) -> str:
    labels = {'formal_simulation':'正式评价','surrogate':'代理模型筛选','completed':'已完成','evaluated':'已评估','best':'最佳','failed':'失败'}
    text = str(value or '已评估').strip()
    return labels.get(text.lower(), text)

def candidate_rows(result: dict) -> list[dict]:
    history = list(result.get('candidates') or result.get('history') or [])
    paths = list(result.get('metadata', {}).get('active_variables') or [])
    rows = []
    for index,item in enumerate(history[:100]):
        if not isinstance(item,dict): continue
        metrics = dict(item.get('metrics') or {})
        coupling = metrics.get('total_coupling_efficiency', metrics.get('coupling_efficiency',item.get('coupling_efficiency')))
        spot = metrics.get('rms_spot_radius_um',item.get('rms_spot_radius_um',item.get('spot_radius_um')))
        if coupling is None and spot is None and not item.get('status'): continue
        variables = item.get('variables')
        if isinstance(variables,dict): values = {str(k):float(v) for k,v in variables.items()}
        elif isinstance(variables,(list,tuple)) and len(variables)==len(paths): values = {str(k):float(v) for k,v in zip(paths,variables)}
        else: values = {}
        rows.append(dict(label=str(item.get('label') or item.get('name') or f'候选 {index+1}'),coupling='—' if coupling is None else f'{float(coupling):.4g}',spot='—' if spot is None else f'{float(spot):.4g}',status=status_label(item.get('status') or item.get('verification_status') or '已评估'),variables=values))
    best = dict(result.get('best_metrics') or {})
    if best and not rows:
        rows.append(dict(label='最佳方案',coupling=str(best.get('coupling_efficiency','—')),spot=str(best.get('rms_spot_radius_um','—')),status='最佳',variables={str(k):float(v) for k,v in dict(result.get('best_variables') or {}).items()}))
    return rows

def opt_chart_payload(result: dict, name: str) -> dict | None:
    history = list(result.get('history') or [])
    if name == '候选对照':
        source = list(result.get('candidates') or []) or history
        labels,values = [],[]
        for index,item in enumerate(source[:12]):
            if not isinstance(item,dict): continue
            value = dict(item.get('metrics') or {}).get('coupling_efficiency')
            if value is None: continue
            labels.append(f'候选 {index+1}'); values.append(float(value))
        if not labels: return None
        return dict(kind='bar',labels=labels,values=values,show_values=True,source='正式优化评价',description='候选方案的正式评价结果；过程曲线使用独立的评价历史。')
    xs,ys = [],[]
    for item in history:
        if not isinstance(item,dict): continue
        xs.append(float(item.get('evaluations',item.get('iteration',len(xs))) or len(xs)))
        ys.append(float(item.get('merit',0) or 0))
    if not xs: return None
    return dict(kind='line',x=xs,y=ys,x_label='评价次数',y_label='评价函数',series_label='评价函数',source='正式优化过程')
