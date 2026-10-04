"""Original current-sample waterfall and compact interpretation, without Qt."""
from shared_presentation.parameter_explanation import feature_label, design_short_label, target_display_label
from shared_presentation.explanation_formulas import (
    formula_binding_for_feature, formula_chain_for_feature,
    physical_mechanism_for_feature, suggested_action_for_feature,
)


def feature_summary(feature, importance, direction='', *, verified=False, target_unit=''):
    if not feature:
        return None
    name = feature_label(feature)
    category, item, level, note = formula_binding_for_feature(feature)
    steps = formula_chain_for_feature(feature)
    mechanism = physical_mechanism_for_feature(feature)
    action = suggested_action_for_feature(feature)
    unit = f' {target_unit}' if target_unit else ''
    model_text = f'{name} 的平均 |SHAP| 为 {float(importance):.4g}{unit}。'
    if direction:
        model_text += f'\n{direction}'
    if category and item:
        physics_html = (
            f"<div style='padding:0 2px 4px; color:#465467;'>"
            f'特征映射：{category} · {item}<br>物理联系：{mechanism}<br>关联方式：{level}。{note}<br>'
            'SHAP 仅用于模型贡献排序，箭头表示光学计算依赖，结论须由正式仿真验证。'
            '</div>'
        )
    else:
        physics_html = (
            f"<b>物理联系</b><div style='padding:8px; color:#465467;'>"
            f'{mechanism}<br>当前特征尚无可靠的闭式公式映射，建议通过参数扫描定位。'
            '<br>SHAP 仅用于模型贡献排序，不能单独证明物理因果。</div>'
        )
    next_text = f'{action}，再用正式光学计算复核。'
    next_text += (' 当前项目已有正式仿真结果，可继续做数值对照。' if verified
                  else ' 当前结论仍是模型线索，尚未由本次正式仿真确认。')
    return dict(model_text=model_text, physics_html=physics_html, next_text=next_text,
                formula_steps=[dict(stage=stage, latex=latex) for stage, latex in steps],
                formula_title=f'{name} · 物理公式')


def _summary(model_text, physics_html, next_text):
    return dict(model_text=model_text, physics_html=physics_html, next_text=next_text,
                formula_steps=[], formula_title='物理联系')


def current_explanation(body, *, verified=False):
    target_label = target_display_label(body.get('target_name'), body.get('target_unit'))
    targets = list(body.get('targets') or [])
    rows = list(targets[0].get('sample_shap_values') or []) if targets else []
    sample = dict(rows[0]) if rows else {}
    values = sample.get('shap_values') or sample.get('values') or {}
    if not isinstance(values, dict) or not values:
        contrib = list(body.get('feature_contributions') or body.get('top_features') or [])
        labels = [feature_label(item.get('feature')) for item in contrib]
        shap_values = [float(item.get('shap_value', item.get('mean_shap', 0.0)) or 0.0) for item in contrib]
    else:
        labels = [feature_label(name) for name in values]
        shap_values = [float(values[name] or 0.0) for name in values]
    if not labels:
        return dict(plot=dict(kind='empty', message='这次解释没有返回当前样本的贡献。'), interpretation=None)
    additivity_error = sample.get('additivity_error', body.get('additivity_error'))
    prediction = sample.get('prediction')
    if additivity_error is not None:
        tolerance = 1.0e-6 * max(1.0, abs(float(prediction or 0.0)))
        if abs(float(additivity_error)) > tolerance:
            return dict(plot=dict(kind='empty', message=f'SHAP贡献无法闭合当前预测（加性误差 {float(additivity_error):.4g}），已停止绘图。'),
                        interpretation=_summary('解释结果无效：基准值与各变量贡献之和不等于模型预测值。',
                                                '当前没有可用的物理联系。', '请检查模型特征与当前镜头组是否匹配后重试。'))
    plot = dict(kind='waterfall',
                labels=[design_short_label(label) for label in (values.keys() if isinstance(values, dict) and values else labels)],
                values=shap_values,
                base_value=float((body.get('base_values') or {}).get(str(body.get('target_name') or ''), 0.0) or 0.0),
                summary=f'目标：{target_label}', legend_loc='lower right', value_labels_right=True)
    top_index = max(range(len(shap_values)), key=lambda index: abs(shap_values[index]))
    raw_features = list(values.keys()) if isinstance(values, dict) and values else labels
    top_feature = str(raw_features[top_index])
    if top_feature == '__other_model_features__':
        summary = _summary('当前样本主要受内部物理特征的合并贡献影响，不能直接当作一个可调整参数。',
                           '这些量由设计变量和正式光学计算共同产生，当前没有可靠的一对一闭式公式。',
                           '返回贡献排序或物理链路，选择曲率半径、厚度或圆锥系数继续验证。')
    else:
        summary = feature_summary(top_feature, abs(shap_values[top_index]),
                                  '该变量在当前样本中提高模型输出。' if shap_values[top_index] >= 0 else '该变量在当前样本中降低模型输出。',
                                  verified=verified, target_unit=str(body.get('target_unit') or '').strip())
    return dict(plot=plot, interpretation=summary)
