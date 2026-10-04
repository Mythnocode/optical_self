"""Teaching scene editing through the original shared Python state model."""
import math
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field
from backend.optical_ml_app.api.teaching_models import TeachingJobRequest
from backend.optical_ml_app.application.teaching_service import TeachingResultStaleError

from backend.optical_ml_app.api.responses import failure, success
from shared_presentation.teaching_model import FLOAT_PARAM_NAMES, OPTIONAL_UNSET_PARAM_NAMES, PLACEABLE_KINDS, Pose, SceneStore
from shared_presentation.teaching_physics import inspect_scene, setup_warnings, compute_geometry_preview, ray_segment_to_dict
from shared_presentation.teaching_coordinates import transform_from_reference
from shared_presentation.teaching_canvas import canvas_presentation
from shared_presentation.teaching_analysis import scene_analysis_presentation
from shared_presentation.teaching_sync import scene_from_engineering, publish_parameters
from shared_contracts.simulation import SimulationRequest
from shared_contracts.project import ProjectSnapshot
from backend.optical_ml_app.application.surface_presentation import editor_surfaces
from types import SimpleNamespace

router = APIRouter()


class TeachingEngineeringSync(BaseModel):
    scene: dict
    simulation: SimulationRequest
    inherit_contract: bool = False
    editor_project: ProjectSnapshot | None = None


@router.post('/teaching/scenes/from-simulation')
def scene_from_simulation(payload:TeachingEngineeringSync,request:Request):
    try:
        store=validate_scene(payload.scene)
        raw=payload.simulation.project.model_dump(mode='json')
        receiver=raw.get('receiver') or {}
        authored=payload.editor_project.model_dump(mode='json') if payload.editor_project else raw
        project=SimpleNamespace(surfaces=editor_surfaces(authored),wavelength_nm=authored['source']['wavelength_nm'],
                                receiver_mfd_um=(authored.get('receiver') or {}).get('mode_field_diameter_x_um',5.0))
        # Before Workbench's first formal submission the native context has
        # no serialized form state. serialize_project(project) publishes only
        # wavelength/MFD and the last authored thickness; the Teaching mapper
        # supplies its original preview defaults for waist and receiver NA.
        mapped=raw if payload.inherit_contract else {
            'source':{'wavelength_nm':project.wavelength_nm},
            'receiver':{'mode_field_diameter_x_um':project.receiver_mfd_um},
            'image_distance_mm':max(float(project.surfaces[-1].thickness_mm) if project.surfaces else 0.0,1e-6),
        }
        scene=scene_from_engineering(store,project,mapped)
        validate_scene(scene)
        engineering=payload.simulation.model_dump(mode='json') if payload.inherit_contract else None
        comparison='后续不修改教学台时，成像和耦合将与仿真工程同处方、同数值配置。' if engineering else '已载入工程处方；请先在仿真页完成一次正式计算，再更新教学台以继承数值配置。'
        return success(request,{'scene':scene,'engineering_request':engineering,
                                'status':f'已从仿真更新 {len(scene["components"])-2} 片透镜、波长和光纤模场；{comparison}'})
    except (ValueError,TypeError,OverflowError,KeyError) as exc:
        return failure(request,status_code=422,code='TEACHING_SYNC_INVALID',stage='teaching.sync',message=str(exc))


@router.post('/teaching/scenes/publish')
def publish_scene(request:Request,payload:dict=Body(...)):
    try:
        store=validate_scene(payload)
        return success(request,{'changes':publish_parameters(store),'teaching_snapshot':store.to_publish_dict()})
    except (ValueError,TypeError,OverflowError,KeyError) as exc:
        return failure(request,status_code=422,code='TEACHING_SYNC_INVALID',stage='teaching.publish',message=str(exc))


@router.post('/teaching/analysis/presentation')
def analysis_presentation(request: Request, payload: dict = Body(...)):
    try:
        return success(request, scene_analysis_presentation(validate_scene(payload).to_dict()))
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code='TEACHING_SCENE_INVALID', stage='teaching.presentation', message=str(exc))


@router.post('/teaching/jobs', status_code=202)
def submit_teaching(payload: TeachingJobRequest, request: Request):
    try:
        store = validate_scene(payload.scene)
        if store.revision != payload.scene_revision:
            raise ValueError('教学场景版本与请求不一致')
        report = inspect_scene(store.snapshot(), payload.analysis)
        if not report.allowed:
            return failure(request, status_code=422, code='TEACHING_SCENE_BLOCKED', stage='teaching.inspect',
                           message='；'.join(report.messages))
        data = payload.model_dump(mode='json')
        data['scene'] = store.to_dict()
        job_id = request.app.state.services['teaching_app'].submit(data)
        return success(request, {'job_id':job_id}, status_code=202)
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code='TEACHING_SCENE_INVALID', stage='teaching.submit', message=str(exc))


@router.get('/teaching/jobs/{job_id}/result')
def teaching_result(job_id: str, request: Request):
    try:
        return success(request, request.app.state.services['teaching_app'].get_result(job_id))
    except FileNotFoundError:
        return failure(request, status_code=404, code='JOB_NOT_FOUND', stage='teaching.result', message='未找到教学任务')
    except RuntimeError as exc:
        return failure(request, status_code=409, code='JOB_RESULT_NOT_AVAILABLE', stage='teaching.result', message=str(exc))
    except ValueError as exc:
        return failure(request, status_code=422, code='TEACHING_RESULT_INVALID', stage='teaching.result', message=str(exc))


@router.post('/teaching/jobs/{job_id}/apply')
def apply_teaching_result(job_id: str, request: Request, payload: dict = Body(...)):
    try:
        wrapped='scene' in payload
        engineering=payload.get('engineering_request') if wrapped else None
        if engineering:engineering=SimulationRequest.model_validate(engineering).model_dump(mode='json')
        return success(request, request.app.state.services['teaching_app'].apply_result(job_id, validate_scene(payload['scene'] if wrapped else payload),engineering))
    except FileNotFoundError:
        return failure(request, status_code=404, code='JOB_NOT_FOUND', stage='teaching.result', message='未找到教学任务')
    except TeachingResultStaleError as exc:
        return failure(request, status_code=409, code='TEACHING_RESULT_STALE', stage='teaching.result', message=str(exc))
    except RuntimeError as exc:
        return failure(request, status_code=409, code='JOB_RESULT_NOT_AVAILABLE', stage='teaching.result', message=str(exc))
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code='TEACHING_RESULT_INVALID', stage='teaching.result', message=str(exc))


@router.post("/teaching/scenes/inspect")
def scene_inspection(request: Request, payload: dict = Body(...)):
    try:
        store = validate_scene(payload)
        snapshot = store.snapshot()
        preview = compute_geometry_preview(snapshot, transform_from_reference(snapshot.reference))
        store.apply_result('geometry', {'source':preview.source,'status':preview.status,'metrics':preview.metrics,
                                       'rays':[ray_segment_to_dict(ray) for ray in preview.rays]}, source_revision=snapshot.revision)
        return success(request, {"report": asdict(inspect_scene(snapshot)), "warnings": setup_warnings(snapshot), "canvas2d": canvas_presentation(snapshot),
                                 "preview": asdict(preview), "geometry":store.to_dict()['results']['geometry']})
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code="TEACHING_SCENE_INVALID", stage="teaching.inspect", message=str(exc))


def validate_scene(data: dict) -> SceneStore:
    def finite(value, depth=0):
        if depth > 40:
            raise ValueError("教学场景数据嵌套过深")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("教学场景包含无效数值")
        if isinstance(value, dict):
            for child in value.values():
                finite(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                finite(child, depth + 1)
    finite(data)
    components = data.get("components")
    if not isinstance(components, list) or len(components) > 4096:
        raise ValueError("教学场景器件列表无效")
    kinds = dict(PLACEABLE_KINDS)
    for component in components:
        if not isinstance(component, dict) or component.get("kind") not in kinds:
            raise ValueError("教学场景包含不支持的器件类型")
        if not isinstance(component.get("pose", {}), dict) or not isinstance(component.get("params", {}), dict):
            raise ValueError("教学器件的位置或参数无效")
        for key, value in component.get("params", {}).items():
            if key in FLOAT_PARAM_NAMES:
                if value in (None, "") and key in OPTIONAL_UNSET_PARAM_NAMES:
                    continue
                if not math.isfinite(float(value)):
                    raise ValueError("教学器件参数包含无效数值")
    store = SceneStore(start_empty=True)
    store.restore_dict(data)
    # Normalization can convert numeric strings, so validate its output too.
    finite(store.to_dict())
    return store


@router.get("/teaching/scenes/default")
def default_scene(request: Request):
    return success(request, {"scene": SceneStore(start_empty=True).to_dict()})


@router.post("/teaching/scenes/normalize")
def normalize_scene(request: Request, payload: dict = Body(...)):
    try:
        return success(request, {"scene": validate_scene(payload).to_dict()})
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code="TEACHING_SCENE_INVALID", stage="teaching.scene", message=str(exc))


class SceneEdit(BaseModel):
    scene: dict
    action: Literal["add", "pose", "remove", "clear", "scheme", "params", "enabled", "baseline"]
    component_id: str | None = Field(default=None, max_length=256)
    kind: str | None = Field(default=None, max_length=128)
    pose: dict | None = None
    params: dict | None = None
    enabled: bool = True
    baseline_x_mm: float | None = Field(default=None, allow_inf_nan=False)
    lens_count: int = Field(default=1, ge=1, le=4)


def edit_pose(data: dict) -> Pose:
    if set(data) != set(Pose.__dataclass_fields__):
        raise ValueError("教学器件位置参数不完整")
    values = {key: float(value) for key, value in data.items()}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("教学器件位置包含无效数值")
    return Pose(**values)


@router.post("/teaching/scenes/edit")
def edit_scene(payload: SceneEdit, request: Request):
    try:
        store = validate_scene(payload.scene)
        if payload.action == "add":
            if payload.kind not in dict(PLACEABLE_KINDS):
                raise ValueError("不支持的教学器件类型")
            kwargs = {"pose": edit_pose(payload.pose)} if payload.pose is not None else {}
            store.add_component(payload.kind, **kwargs)
        elif payload.action == "scheme":
            store.apply_optical_scheme(payload.lens_count)
        elif payload.action == "clear":
            store.clear_scene()
        elif payload.action == "baseline":
            store.set_baseline(payload.enabled, payload.baseline_x_mm)
        else:
            if payload.component_id not in store.components:
                raise ValueError("教学器件不存在")
            if payload.action == "remove":
                store.remove_component(payload.component_id)
            elif payload.action == "pose":
                if payload.pose is None:
                    raise ValueError("教学器件位置参数不完整")
                store.update_pose(payload.component_id, edit_pose(payload.pose))
            elif payload.action == "params":
                if not store.update_params(payload.component_id, payload.params or {}):
                    raise ValueError("教学器件参数无效")
            elif payload.action == "enabled":
                store.set_enabled(payload.component_id, payload.enabled)
        scene = store.to_dict()
        validate_scene(scene)
        return success(request, {"scene": scene})
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return failure(request, status_code=422, code="TEACHING_SCENE_INVALID", stage="teaching.edit", message=str(exc))
