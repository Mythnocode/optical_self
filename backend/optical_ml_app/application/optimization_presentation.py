"""Optimization form presentation and native request preparation."""
from copy import deepcopy
from math import isfinite
from types import SimpleNamespace
from backend.optical_ml_app.application.surface_presentation import editor_surfaces
from shared_presentation.variable_rows import variable_rows
from shared_presentation.optimization_variables import current_value, variable_range
from shared_presentation.workbench_payloads import _augment_payload
from shared_contracts.metrics import analyses_for_metrics

def optimization_presentation(project: dict) -> dict:
    authored = SimpleNamespace(surfaces=editor_surfaces(project))
    variables = []
    for path, group, face, parameter in variable_rows(authored):
        value = current_value(authored, path)
        lower, upper = variable_range(value)
        variables.append(dict(path=path, group=group, label=f'{group} / {face} / {parameter}', current=value, lower=lower, upper=upper))
    return {'variables': variables, 'surfaces': [{'value': str(i), 'label': f'S{i+1} · {s.name}'} for i,s in enumerate(authored.surfaces)]}

def optimization_payload(simulation: dict, config: dict, variables: list[dict]) -> dict:
    available = {row['path'] for row in optimization_presentation(simulation['project'])['variables']}
    if not variables:
        raise ValueError('请先在左栏勾选优化变量。')
    prepared = []
    for variable in variables:
        path = str(variable['path'])
        if path not in available:
            raise ValueError('优化变量已不属于当前镜头结构，请重新选择。')
        initial, lower, upper = (float(variable[key]) for key in ('current', 'lower', 'upper'))
        if not all(isfinite(value) for value in (initial, lower, upper)) or lower >= upper:
            raise ValueError('参数范围必须是有限数值，且最小值小于最大值。')
        prepared.append(dict(path=path, label=str(variable['label']), unit='mm', lower_bound=lower, upper_bound=upper, initial_value=initial, enabled=True))
    payload = deepcopy(simulation)
    metrics = {'最小化 RMS 光斑': ['rms_spot_radius_um'], '多目标加权': ['coupling_efficiency','rms_spot_radius_um']}.get(config.get('objective'), ['coupling_efficiency'])
    payload['analyses'] = sorted({'coupling', *analyses_for_metrics(metrics)})
    payload['project']['analysis_settings']['requested_analyses'] = list(payload['analyses'])
    first = prepared[0]
    config = {**config, 'algorithm':'智能全局搜索', 'param_path':first['path'], 'param_label':first['label'], 'lower':first['lower_bound'], 'upper':first['upper_bound'], 'initial':first['initial_value']}
    _augment_payload(payload, 'optimize', config)
    payload['opt_variables'] = prepared
    payload.pop('validation_options', None)
    payload.pop('frontend_state', None)
    if config.get('evaluation_mode') == 'surrogate':
        model_id = str(config.get('surrogate_model_id') or '')
        if not model_id:
            raise ValueError('请先训练并选择模型。')
        payload['opt_options'].update(mode='ml_inverse_prediction', surrogate_model_id=model_id, coarse_fraction=.88)
    return payload
