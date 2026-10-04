"""Original parameter dependence and formula cards without Qt dependencies."""
from typing import Any
from shared_presentation.feature_labels import display_feature_name
from shared_presentation.explanation_formulas import formula_chain_for_feature, formula_latex
from shared_presentation.explainability import _TARGET_DISPLAY

DESIGN_SHORT = {
    f'surfaces[{2*i}].{field}': f'L{i+1}-{short}'
    for i in range(4) for field, short in [('radius_mm','r'),('distance_to_next_mm','d')]
}

def target_display_label(target_name, target_unit=''):
    name = str(target_name or '模型输出')
    unit = str(target_unit or '').strip()
    return _TARGET_DISPLAY.get(name, f'{name}（{unit}）' if unit else name)

def feature_label(feature):
    key = str(feature or '')
    return '其他模型特征（合并）' if key == '__other_model_features__' else display_feature_name(key)

def design_short_label(feature):
    key = str(feature or '')
    return DESIGN_SHORT.get(key, feature_label(key))

def feature_picker_rows(items):
    rows=[]
    for index, record in enumerate(items):
        feature=str(record.get('feature') or record.get('name') or '')
        value=float(record.get('mean_abs_shap', abs(float(record.get('mean_shap',0.0) or 0.0))) or 0.0)
        rows.append({'feature':feature,'text':f'{index+1}. {feature_label(feature)}    |SHAP| {value:.4g}'})
    return rows

def parameter_plot(body, selected=''):
    items=list(body.get('top_features') or body.get('feature_contributions') or body.get('global_importance') or [])
    if not items:
        return {'kind':'empty','message':'这次解释没有返回可用的 SHAP 参数排名。'}
    selected_feature=selected or str(items[0].get('feature') or items[0].get('name') or '')
    item=shap_dependence_item(body,selected_feature)
    if not item and selected_feature:
        for feature,data in dict(body.get('shap_dependence') or {}).items():
            if shap_feature_key(str(feature),[selected_feature])==selected_feature:
                item=dict(data);break
    xs=list(item.get('feature_value') or item.get('x') or []) if item else []
    ys=list(item.get('shap_value') or item.get('y') or []) if item else []
    if xs and ys:
        unit=str(body.get('target_unit') or '').strip()
        return {'kind':'scatter','x':xs,'y':ys,'x_label':design_short_label(selected_feature),
                'y_label':f'SHAP（{unit}）' if unit else 'SHAP','zero_line':True}
    return {'kind':'empty','message':'已生成物理链路；当前没有返回该参数的单参数依赖曲线。'}

def physical_chain_items(selected_keys, target_label):
    rows=[];has_formula=False
    for feature in selected_keys:
        name=feature_label(feature)
        steps=formula_chain_for_feature(feature)
        has_formula=has_formula or bool(steps)
        if steps:
            path_steps=[f'公式 {index}（{stage}）' for index,(stage,_latex) in enumerate(steps,start=1)]
            path_steps.append('共同输出：复场重叠')
            path=f'{name} → '+' → '.join(path_steps)+f' → {target_label}'
        else:
            path=f'{name} → 暂无专属公式映射 → {target_label}'
        rows.append({'feature':feature,'name':name,'path':path,
                     'steps':[{'stage':stage,'latex':latex} for stage,latex in steps],
                     'note':'' if steps else '该变量尚无可靠的解析公式映射，建议通过正式参数扫描和仿真定位。'})
    overlap=formula_latex('总耦合效率','复场重叠') if has_formula else ''
    return {'title':f'物理链路（已选择 {len(selected_keys)} 个参数）' if selected_keys else '物理链路',
            'rows':rows,'overlap_formula':overlap}


def shap_dependence_item(body: dict[str, Any], selected: str) -> dict[str, Any]:
    dependence = dict(body.get("shap_dependence") or {})
    if selected in dependence and isinstance(dependence.get(selected), dict):
        return dict(dependence[selected])
    for feature, item in dependence.items():
        if not isinstance(item, dict):
            continue
        if str(feature) == str(selected) or str(item.get("feature") or "") == str(selected):
            return dict(item)
    return {}

def shap_feature_key(feature: str, variable_keys: list[str]) -> str | None:
    raw = str(feature or "").strip()
    if not raw:
        return None
    keys = set(variable_keys)
    if raw in keys:
        return raw
    thickness = raw.replace(".thickness_mm", ".distance_to_next_mm")
    if thickness in keys:
        return thickness
    lowered = raw.lower().replace(" ", "")
    aliases = (
        ("receiver.offset_x", "receiver.offset_x_um"),
        ("offset_x", "receiver.offset_x_um"),
        ("x偏移", "receiver.offset_x_um"),
        ("横向", "receiver.offset_x_um"),
        ("receiver.offset_y", "receiver.offset_y_um"),
        ("offset_y", "receiver.offset_y_um"),
        ("y偏移", "receiver.offset_y_um"),
        ("receiver.axial", "receiver.axial_offset_z_um"),
        ("offset_z", "receiver.axial_offset_z_um"),
        ("axial", "receiver.axial_offset_z_um"),
        ("轴向", "receiver.axial_offset_z_um"),
    )
    for needle, key in aliases:
        if needle.replace(" ", "") in lowered and key in keys:
            return key
    return None
