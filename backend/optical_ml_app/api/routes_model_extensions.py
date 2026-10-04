

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, Field

from backend.optical_ml_app.api.responses import failure, success
from backend.optical_ml_app.domain.errors import BackendApplicationError
from shared_contracts.project import ProjectSnapshot

router = APIRouter()




class ShapExplainRequest(BaseModel):
    dataset_id: str | None = None
    features: dict[str, float] | None = None
    target_name: str | None = None
    target_names: list[str] = Field(default_factory=list)
    sample_ids: list[str] = Field(default_factory=list)
    display_feature_paths: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=100)
    max_samples: int = Field(default=100, ge=1, le=1000)
    background_sample_count: int = Field(default=100, ge=1, le=2000)
    random_seed: int = 42


class DesignVariableExplainRequest(BaseModel):
    sample_ids: list[str] = Field(default_factory=list)
    max_samples: int = Field(default=80, ge=1, le=1000)
    background_sample_count: int = Field(default=80, ge=1, le=2000)
    random_seed: int = 42


class CurrentSystemExplainRequest(BaseModel):
    project: ProjectSnapshot


@router.post('/models/{model_id}/shap/current-system/jobs')
def submit_current_explanation(model_id: str, payload: CurrentSystemExplainRequest, request: Request):
    from backend.optical_ml_app.application.explainability_service import prepare_current_explanation, run_current_explanation
    services = request.app.state.services
    ext = services['model_extension_app']
    if model_id not in ext.model_registry.list_model_ids():
        return failure(request, status_code=404, code='MODEL_NOT_FOUND', stage='model.shap', message='解释模型不存在。')
    try:
        prepared = ShapExplainRequest(**prepare_current_explanation(payload.project, ext.model_registry.describe(model_id))).model_dump()
    except BackendApplicationError as exc:
        return failure(request, status_code=422, **exc.to_dict())
    job_id = services['task_manager'].submit(
        'explainability', run_current_explanation,
        str(ext.model_registry.root), str(ext.dataset_store.root), model_id, prepared, payload.project.model_dump(),
    )
    return success(request, {'job_id': job_id}, status_code=202)


@router.get('/explainability/jobs/{job_id}/current-presentation')
def read_current_presentation(job_id: str, request: Request, verified: bool = False,
                             width: int = Query(default=900, ge=160, le=4096), height: int = Query(default=400, ge=100, le=4096)):
    from backend.optical_ml_app.application.explainability_service import current_result_presentation
    manager = request.app.state.services['task_manager']
    try:
        job = manager.get_status(job_id)
    except (KeyError, FileNotFoundError):
        return failure(request, status_code=404, code='JOB_NOT_FOUND', stage='model.shap', message='解释任务不存在。')
    if job.job_type != 'explainability' or job.status != 'completed':
        return failure(request, status_code=409, code='EXPLANATION_NOT_READY', stage='model.shap', message='解释任务尚未完成。')
    result = manager.get_result(job_id)
    if result.get('explanation_kind') != 'shap' or result.get('data_source') != 'request_features':
        return failure(request, status_code=422, code='EXPLANATION_KIND_INVALID', stage='model.shap', message='该任务没有当前系统解释结果。')
    return success(request, current_result_presentation(result, width, height, verified))


@router.post('/models/{model_id}/shap/jobs')
def submit_shap_explanation(model_id: str, payload: ShapExplainRequest, request: Request):
    from backend.optical_ml_app.application.explainability_service import run_shap_explanation
    services = request.app.state.services
    ext = services['model_extension_app']
    job_id = services['task_manager'].submit(
        'explainability', run_shap_explanation,
        str(ext.model_registry.root), str(ext.dataset_store.root), model_id, payload.model_dump(),
    )
    return success(request, {'job_id': job_id}, status_code=202)


@router.get('/explainability/jobs/{job_id}/parameter-presentation')
def read_parameter_presentation(job_id: str, request: Request, feature: list[str] | None = Query(default=None),
                               empty_selection: bool = False, parameter: str = '',
                               width: int = Query(default=900, ge=160, le=4096), height: int = Query(default=400, ge=100, le=4096)):
    from backend.optical_ml_app.application.explainability_service import parameter_result_presentation
    manager = request.app.state.services['task_manager']
    try:
        job = manager.get_status(job_id)
    except (KeyError, FileNotFoundError):
        return failure(request, status_code=404, code='JOB_NOT_FOUND', stage='model.shap', message='解释任务不存在。')
    if job.job_type != 'explainability' or job.status != 'completed':
        return failure(request, status_code=409, code='EXPLANATION_NOT_READY', stage='model.shap', message='解释任务尚未完成。')
    result = manager.get_result(job_id)
    if result.get('explanation_kind') != 'shap' or result.get('data_source') != 'registered_dataset':
        return failure(request, status_code=422, code='EXPLANATION_KIND_INVALID', stage='model.shap', message='该任务没有数据集参数解释结果。')
    try:
        presentation = parameter_result_presentation(result, [] if empty_selection else feature, width, height, parameter)
    except BackendApplicationError as exc:
        return failure(request, status_code=422, **exc.to_dict())
    return success(request, presentation)


@router.post('/models/{model_id}/shap/design-variables/jobs')
def submit_design_explanation(model_id: str, payload: DesignVariableExplainRequest, request: Request):
    from backend.optical_ml_app.application.explainability_service import run_design_explanation
    services = request.app.state.services
    ext = services['model_extension_app']
    job_id = services['task_manager'].submit(
        'explainability', run_design_explanation,
        str(ext.model_registry.root), str(ext.dataset_store.root), model_id, payload.model_dump(),
    )
    return success(request, {'job_id': job_id}, status_code=202)


@router.get('/explainability/jobs/{job_id}/presentation')
def read_design_presentation(job_id: str, request: Request, chart: str = '全局特征重要性排名', width: int = Query(default=900, ge=160, le=4096), height: int = Query(default=400, ge=100, le=4096)):
    from shared_presentation.explainability import CHARTS
    from backend.optical_ml_app.application.explainability_service import design_result_presentation
    if chart not in CHARTS:
        return failure(request, status_code=422, code='EXPLANATION_CHART_INVALID', stage='model.shap', message='请选择有效的解释图表。')
    manager = request.app.state.services['task_manager']
    try:
        job = manager.get_status(job_id)
    except (KeyError, FileNotFoundError):
        return failure(request, status_code=404, code='JOB_NOT_FOUND', stage='model.shap', message='解释任务不存在。')
    if job.job_type != 'explainability' or job.status != 'completed':
        return failure(request, status_code=409, code='EXPLANATION_NOT_READY', stage='model.shap', message='解释任务尚未完成。')
    result = manager.get_result(job_id)
    if result.get('explanation_kind') != 'design_variables':
        return failure(request, status_code=422, code='EXPLANATION_KIND_INVALID', stage='model.shap', message='该任务没有设计变量解释结果。')
    return success(request, design_result_presentation(result, chart, width, height))


def _get_ext(request: Request) -> Any:
    ext = request.app.state.services.get("model_extension_app")
    if ext is None:
        return None
    return ext


@router.post("/models/{model_id}/shap/explain")
def shap_explain(model_id: str, payload: ShapExplainRequest, request: Request):

    ext = _get_ext(request)
    if ext is None:
        return failure(request, status_code=501, code="MODEL_EXTENSION_NOT_CONFIGURED",
                       stage="model.shap", message="model extension service not configured")

    try:
        result = ext.explain_shap(model_id, payload)
    except BackendApplicationError as exc:
        status_code = 501 if exc.code == "SHAP_BACKEND_NOT_CONFIGURED" else 422
        return failure(request, status_code=status_code, **exc.to_dict())
    return success(request, result)


@router.post("/models/{model_id}/shap/design-variables")
def shap_design_variables(model_id: str, payload: DesignVariableExplainRequest, request: Request):

    ext = _get_ext(request)
    if ext is None:
        return failure(request, status_code=501, code="MODEL_EXTENSION_NOT_CONFIGURED",
                       stage="model.shap", message="model extension service not configured")

    try:
        result = ext.explain_design_variables(model_id, payload)
    except BackendApplicationError as exc:
        status_code = 501 if exc.code == "SHAP_BACKEND_NOT_CONFIGURED" else 422
        return failure(request, status_code=status_code, **exc.to_dict())
    return success(request, result)
