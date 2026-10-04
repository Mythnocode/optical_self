"""Original design-variable chart payloads, without UI dependencies."""
from typing import Any
_TARGET_DISPLAY = {"coupling_efficiency": "耦合效率", "coupling_loss_db": "耦合损耗(dB)"}
CHARTS = ("全局特征重要性排名", "蜂群图", "特征依赖网格图", "单变量依赖趋势图", "物理一致性图", "瀑布图")

def design_variable_plot(body, chart='全局特征重要性排名'):
    import numpy as np
    design_paths = [str(p) for p in list(body.get('design_paths') or [])]
    labels = [str(v) for v in list(body.get('design_labels') or [])]
    importance = [dict(item) for item in list(body.get('importance') or []) if isinstance(item, dict)]
    total = np.asarray(body.get('total') or [], dtype=float)
    design_values = np.asarray(body.get('design_values') or [], dtype=float)
    target_label = _TARGET_DISPLAY.get(str(body.get('target_name') or ''), '模型输出')
    if not design_paths or total.ndim != 2 or total.shape[1] != len(design_paths) or (not importance):
        return {'kind': 'empty', 'message': '这次解释没有返回设计变量的贡献值。'}
    n = int(total.shape[0])
    if not labels:
        labels = design_paths
    labels = labels[:len(design_paths)]
    ranked_labels = [str(item.get('label') or item.get('feature') or '') for item in importance]
    ranked_indices = [design_paths.index(str(item.get('feature') or '')) for item in importance if str(item.get('feature') or '') in design_paths]
    ranked_values = [float(item.get('mean_abs') or 0.0) for item in importance]
    total_ranked = total[:, ranked_indices]
    design_ranked = design_values[:, ranked_indices]
    if chart == '蜂群图':
        points: list[dict[str, Any]] = []
        for sample_index in range(n):
            for j, col in enumerate(ranked_indices):
                column = design_values[:, col]
                low = float(column.min())
                high = float(column.max())
                raw = float(design_values[sample_index, col])
                scaled = (raw - low) / (high - low) if high > low else 0.5
                points.append({'feature': ranked_labels[j], 'value': float(total[sample_index, col]), 'sample_index': sample_index, 'color': '#dc2626' if scaled >= 0.5 else '#2563eb'})
        return {'kind': 'beeswarm', 'labels': ranked_labels, 'points': points, 'importance': ranked_values, 'sample_count': n, 'x_label': 'SHAP 值', 'source': '模型解释', 'summary': '红色表示该设计变量取值偏高，蓝色表示偏低；横轴为对模型输出的正负 SHAP 值。', 'description': f'设计变量 SHAP 值分布 · {n} 个样本'}
    if chart == '特征依赖网格图' or chart == '单变量依赖趋势图':
        corr = np.corrcoef(design_values.T) if n >= 2 and design_values.shape[1] >= 2 else np.eye(len(design_paths))
        panels: list[dict[str, Any]] = []
        for j, col in enumerate(range(len(design_paths))):
            x = design_values[:, col]
            y = total[:, col]
            others = [k for k in range(len(design_paths)) if k != col]
            jmax = max(others, key=lambda k: abs(float(corr[col, k]))) if others else col
            panels.append({'label': labels[col], 'x': x.tolist(), 'y': y.tolist(), 'color': design_values[:, jmax].tolist(), 'color_label': labels[jmax]})
        if chart == '特征依赖网格图':
            return {'kind': 'dependence_grid', 'panels': panels, 'title': 'SHAP 特征依赖网格图', 'y_label': 'SHAP Value'}
        else:
            return {'kind': 'dependence_fit_ci', 'panels': panels, 'title': 'SHAP 单变量依赖趋势图', 'y_label': 'SHAP Value'}
    if chart == '物理一致性图':
        consistency = dict(body.get('physics_consistency') or {})
        x = [float(v) for v in list(consistency.get('shap_importance') or [])]
        y = [float(v) for v in list(consistency.get('physics_elasticity') or [])]
        return {'kind': 'physics_consistency', 'x': x, 'y': y, 'labels': labels, 'pearson': consistency.get('pearson'), 'spearman': consistency.get('spearman'), 'x_label': '平均SHAP', 'y_label': '物理解析重要性', 'summary': '横轴为 ML 学到的变量重要性，纵轴为光学理论敏感度；二者共线说明模型与物理一致。'}
    if chart == '瀑布图':
        waterfall = dict(body.get('waterfall') or {})
        wf_values = [float(v) for v in list(waterfall.get('values') or [])]
        if len(wf_values) != len(labels):
            wf_values = total_ranked[0].tolist() if n > 0 else [0.0] * len(labels)
            wf_labels = list(ranked_labels)
        else:
            wf_labels = list(labels)
        order = sorted(range(len(wf_values)), key=lambda index: -abs(wf_values[index]))
        return {'kind': 'waterfall', 'labels': [wf_labels[i] for i in order], 'values': [wf_values[i] for i in order], 'base_value': float(waterfall.get('base_value') or 0.0), 'x_label': target_label, 'summary': f'目标：{target_label}'}
    return {'kind': 'barh', 'labels': ranked_labels, 'values': ranked_values, 'show_values': True, 'source': '模型解释', 'x_label': '平均贡献', 'description': '数值越大表示模型越依赖该设计变量；不等同于物理因果。'}


def explain_shap_failure(message: str) -> str:
    """Turn SHAP service errors into an actionable workbench message."""
    text = str(message or "").strip()
    lowered = text.lower()
    if (
        "schema" in lowered
        or "missing_feature" in lowered
        or "missing one or more trained features" in lowered
    ):
        return "当前镜头组参数和这个模型对不上。请用训练该模型时的镜头组再解释。"
    if "model_not_found" in lowered or "could not be loaded" in lowered:
        return "找不到这个已训练模型。请重新训练后再解释。"
    if "not configured" in lowered or "shap_backend" in lowered:
        return "本机还没装好解释组件，暂时无法计算参数贡献。"
    if "dataset" in lowered and "mismatch" in lowered:
        return "解释用的数据集和训练这个模型时不一致。请改用训练时的数据集。"
    if "internal server error" in lowered:
        return "解释失败：后端解释服务发生内部错误，请查看后端日志或重新训练模型。"
    if not text:
        return "解释失败，请稍后重试。"
    if "学不成" in text or "数据管理" in text:
        return text
    return f"解释失败：{text}"

