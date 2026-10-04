"""Job orchestration for the existing explanation service."""
from pathlib import Path

from backend.optical_ml_app.domain.errors import BackendApplicationError


def run_design_explanation(context, model_root: str, dataset_root: str, model_id: str, payload: dict):
    return _run_explanation(context, model_root, dataset_root, model_id, payload, 'design_variables')


def run_shap_explanation(context, model_root: str, dataset_root: str, model_id: str, payload: dict):
    return _run_explanation(context, model_root, dataset_root, model_id, payload, 'shap')


def prepare_current_explanation(project, model: dict) -> dict:
    from backend.optical_ml_app.application.project_features import project_features
    paths = list(model.get('feature_paths') or [])
    if not paths:
        raise BackendApplicationError(code='MODEL_FEATURE_SCHEMA_MISSING', stage='model.shap',
                                      message='模型记录没有声明 feature_paths，请刷新模型列表或重新训练。')
    try:
        features = project_features(project, paths)
    except (TypeError, ValueError) as exc:
        raise BackendApplicationError(code='MODEL_FEATURE_MISSING', stage='model.shap',
                                      message=f'当前镜头无法构造模型特征：{exc}') from exc
    return dict(top_k=8, max_samples=80, background_sample_count=80, features=features,
                display_feature_paths=list(model.get('design_variable_paths') or []))


def run_current_explanation(context, model_root: str, dataset_root: str, model_id: str, payload: dict, project: dict):
    result = run_shap_explanation(context, model_root, dataset_root, model_id, payload)
    # Keep the actual submitted sample available for native comparison and restoration.
    return {**result, 'source_project': project, 'explanation_request': payload}


def _run_explanation(context, model_root: str, dataset_root: str, model_id: str, payload: dict, kind: str):
    from backend.optical_ml_app.application.model_extension_service import ModelExtensionService
    from machine_learning.registry.model_registry import FileModelRegistry
    from machine_learning.datasets.storage import FileDatasetStore

    if context.cancellation.is_cancelled:
        return {'status': 'cancelled'}
    context.progress.update(0.05, 'model.shap.preparing', 0, 1)
    service = context.get_or_create_resource(
        'explainability_service',
        lambda: ModelExtensionService(FileModelRegistry(Path(model_root)), FileDatasetStore(Path(dataset_root))),
    )
    try:
        result = service.explain_design_variables(model_id, payload) if kind == 'design_variables' else service.explain_shap(model_id, payload)
    except BackendApplicationError as exc:
        from shared_presentation.explainability import explain_shap_failure
        error = exc.to_dict()
        error['message'] = explain_shap_failure(f'{exc.code}: {exc.message}')
        return {'status': 'failed', 'errors': [error]}
    if context.cancellation.is_cancelled:
        return {'status': 'cancelled'}
    context.progress.update(1.0, 'model.shap.completed', 1, 1)
    return {'status': 'completed', 'explanation_kind': kind, **result}


def design_result_presentation(result: dict, chart: str, width: int, height: int) -> dict:
    from shared_presentation.explainability import design_variable_plot
    return render_explanation_plot(design_variable_plot(result, chart), width, height)


def render_explanation_plot(plot: dict, width: int, height: int) -> dict:
    from io import StringIO
    from matplotlib import rc_context
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from shared_presentation.plotting.explain_charts import ExplainChartsMixin, apply_explain_margins
    from shared_presentation.plotting.basic_charts import chart_style, apply_high_contrast_axes, draw_scatter_chart
    from shared_presentation.plotting.result_summary import result_summary
    from shared_presentation import theme_tokens as theme
    from backend.optical_ml_app.application.optimization_results import _render_lock

    if plot['kind'] == 'empty':
        return {'svg': '', 'summary': '', 'message': plot['message']}
    with _render_lock, rc_context(chart_style()):
        figure = Figure(figsize=(width / 100, height / 100), dpi=100, facecolor=theme.SCENE_BACKGROUND)
        FigureCanvasSVG(figure)
        figure.subplots_adjust(left=.11, right=.94, bottom=.14, top=.89)
        renderer = ExplainChartsMixin()
        renderer.figure = figure
        axis = figure.add_subplot(111)
        if plot['kind'] == 'scatter':
            draw_scatter_chart(axis, plot)
            axis.set_title(plot.get('title', ''), pad=8)
            axis.set_xlabel(plot.get('x_label', ''))
            axis.set_ylabel(plot.get('y_label', ''), rotation=90, labelpad=12, va='center')
            axis.grid(True, alpha=.72, color=theme.CHART_GRID)
        else:
            renderer.draw_explain_chart(axis, plot)
        apply_high_contrast_axes(figure)
        if plot['kind'] == 'scatter':
            figure.subplots_adjust(left=.15, right=.965, bottom=.24, top=.86)
        else:
            apply_explain_margins(figure, plot)
        output = StringIO()
        figure.savefig(output, format='svg', facecolor=theme.SCENE_BACKGROUND, metadata={'Date': None})
    return {'svg': output.getvalue(), 'summary': result_summary(plot), 'message': ''}


def _formula_image(latex: str) -> dict:
    import base64
    import struct
    from shared_presentation.formula_images import render_formula_png
    from backend.optical_ml_app.application.optimization_results import _render_lock
    with _render_lock:
        png = render_formula_png(latex)
    width, height = struct.unpack('>II', png[16:24])
    return {'src': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'), 'width': width, 'height': height}


def parameter_result_presentation(result: dict, selected_keys: list[str] | None, width: int, height: int, parameter: str = '') -> dict:
    from shared_presentation.parameter_explanation import parameter_plot, feature_picker_rows, physical_chain_items, target_display_label
    items = list(result.get('top_features') or result.get('feature_contributions') or result.get('global_importance') or [])
    ranking = feature_picker_rows(items)
    allowed = {row['feature'] for row in ranking}
    keys = [row['feature'] for row in ranking[:3]] if selected_keys is None else list(dict.fromkeys(selected_keys))
    if len(keys) > 3 or any(key not in allowed for key in keys):
        raise BackendApplicationError(code='EXPLANATION_FEATURE_INVALID', stage='model.shap', message='请从贡献排序选择最多3个参数。')
    # Preserve ranking order even when checks were clicked in a different order.
    keys = [row['feature'] for row in ranking if row['feature'] in keys]
    chain = physical_chain_items(keys, target_display_label(result.get('target_name'), result.get('target_unit')))
    for row in chain['rows']:
        for step in row['steps']:
            step['image'] = _formula_image(step['latex'])
    chain['overlap_image'] = _formula_image(chain['overlap_formula']) if chain['overlap_formula'] else None
    return {**render_explanation_plot(parameter_plot(result, parameter), width, height),
            'ranking': ranking, 'selected_keys': keys, 'chain': chain}


def current_result_presentation(result: dict, width: int, height: int, verified: bool = False) -> dict:
    from shared_presentation.current_explanation import current_explanation
    presentation = current_explanation(result, verified=verified)
    summary = presentation['interpretation']
    if summary:
        for step in summary['formula_steps']:
            step['image'] = _formula_image(step['latex'])
    return {**render_explanation_plot(presentation['plot'], width, height), 'interpretation': summary}
