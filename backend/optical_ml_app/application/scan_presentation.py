"""Native scan form preparation; all responses remain computed by the optical engine."""
from copy import deepcopy
from math import isfinite
from backend.optical_ml_app.application.optimization_presentation import optimization_presentation
from shared_contracts.metrics import analyses_for_metrics
from shared_presentation.workbench_payloads import _augment_payload


def scan_payload(simulation: dict, config: dict, variables: list[dict]) -> dict:
    catalog = {row['path']: row for row in optimization_presentation(simulation['project'])['variables']}
    if not variables:
        raise ValueError('请先在左栏勾选 1～2 个变量。')
    mode = config.get('scan_mode', '一维扫描')
    scale = config.get('scale', '线性采样')
    if scale == '自适应加密':
        raise ValueError('自适应加密尚未实现，请选择线性采样或对数采样。')
    if scale not in {'线性采样','对数采样'}:
        raise ValueError('未知采样尺度。')
    if config.get('response','耦合效率') not in {'耦合效率','RMS 光斑','Strehl','边缘功率'}:
        raise ValueError('未知扫描响应量。')
    if mode == '一维扫描' and len(variables) != 1:
        raise ValueError('一维扫描只能勾选一个变量；如需两个变量请切换到二维扫描。')
    if mode == '二维扫描' and len(variables) != 2:
        raise ValueError('二维扫描需要在左栏勾选两个变量。')
    if mode not in {'一维扫描','二维扫描','多参数采样'}:
        raise ValueError('未知扫描模式。')
    points = int(config.get('points', 21))
    if not 5 <= points <= 401:
        raise ValueError('采样点数必须在 5～401 之间。')
    prepared = {**config, 'points': points}
    for index, row in enumerate(variables):
        path = str(row['path'])
        if path not in catalog:
            raise ValueError('扫描变量已不属于当前镜头结构，请重新选择。')
        low, high = float(row['lower']), float(row['upper'])
        if not all(isfinite(value) for value in (low, high)) or low >= high:
            raise ValueError('扫描范围必须是有限数值，且最小值小于最大值。')
        if scale == '对数采样' and low * high <= 0:
            raise ValueError('对数采样要求范围两端非零且同号。')
        suffix = '' if index == 0 else '2'
        prepared.update({f'param_path{suffix}':path, f'param_label{suffix}':catalog[path]['label'], f'start{suffix}':low, f'stop{suffix}':high, f'points{suffix}':points})
    payload = deepcopy(simulation)
    _augment_payload(payload, 'scan', prepared)
    payload['analyses'] = sorted(analyses_for_metrics(payload['scan_response_metrics']))
    payload['project']['analysis_settings']['requested_analyses'] = list(payload['analyses'])
    payload.pop('validation_options', None)
    payload.pop('frontend_state', None)
    return payload
