"""Job adapter for the original Teaching formal physics gateway."""
from dataclasses import asdict
import hashlib
import json

from backend.optical_ml_app.jobs.progress import ScaledProgressReporter
from shared_presentation.teaching_model import SceneStore
from shared_presentation.teaching_physics import FormalTeachingGateway, PhysicsRequest
from shared_presentation.teaching_coordinates import transform_from_reference


class TeachingResultStaleError(ValueError):
    pass


def scene_calculation_key(scene: dict) -> str:
    # Selection and prior results do not change the calculation prescription.
    physical = {key: scene.get(key) for key in ('scene_id', 'revision', 'reference', 'components')}
    return hashlib.sha256(json.dumps(physical, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def engineering_calculation_key(request):
    return json.dumps({key:request.get(key) for key in ('project','options','precision')},sort_keys=True,allow_nan=False) if request else None


class _JobEngine:
    """Pass job cancellation/progress to the unchanged runtime's engine calls."""
    def __init__(self, engine, context, analysis):
        self.engine, self.context, self.analysis, self.calls = engine, context, analysis, 0

    def evaluate(self, request):
        self.calls += 1
        start, end = (0.04, 0.32) if self.calls == 1 else (0.34, 0.92)
        return self.engine.evaluate(request, cancellation=self.context.cancellation,
                                    progress=ScaledProgressReporter(self.context.progress, start, end,
                                                                    stage_prefix=f'teaching.{self.analysis}'))


def run_teaching_task(context, payload: dict):
    from optical_runtime import create_optical_simulation_engine
    from teaching_runtime.physical_scene import TeachingOpticalEngineBridge

    store = SceneStore(start_empty=True)
    store.restore_dict(payload['scene'])
    snapshot = store.snapshot()
    engine = context.get_or_create_resource('optical_engine', create_optical_simulation_engine)
    bridge = TeachingOpticalEngineBridge(_JobEngine(engine, context, payload['analysis']))
    engineering = payload.get('engineering_request')
    gateway = FormalTeachingGateway(bridge, engineering_request_provider=(lambda: engineering) if engineering else None)
    context.progress.update(0.03, f"teaching.{payload['analysis']}.starting")
    result = gateway.compute(PhysicsRequest(snapshot, payload['analysis'], transform_from_reference(snapshot.reference)))
    value = asdict(result)
    context.progress.update(0.94, f"teaching.{payload['analysis']}.finished")
    return {
        'status': 'completed' if result.success else 'failed',
        'request_id': payload['request_id'], 'analysis': result.analysis,
        'scene': payload['scene'], 'scene_key': scene_calculation_key(payload['scene']),
        'engineering_request': engineering, 'physics': value, 'artifacts': value['artifacts'],
        'metrics': value['metrics'], 'warnings': list(result.warnings),
        'errors': [{'code': 'TEACHING_CALCULATION_FAILED', 'stage': f'teaching.{result.analysis}',
                    'message': message, 'retryable': False} for message in result.errors],
    }


class TeachingApplicationService:
    def __init__(self, task_manager):
        self.task_manager = task_manager

    def submit(self, payload: dict) -> str:
        identity = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return self.task_manager.submit('teaching', run_teaching_task, payload,
                                        idempotency_key=f"teaching:{payload['request_id']}:{identity}")

    def get_result(self, job_id: str):
        state = self.task_manager.get_status(job_id)
        if state.job_type != 'teaching':
            raise ValueError('所选任务不是教学任务')
        if state.status == 'completed':
            return self.task_manager.get_result(job_id)
        if state.status == 'failed':
            # Failed physics is diagnostic data, never a valid formal result.
            try:
                return self.task_manager.repository.load_result(job_id)
            except FileNotFoundError:
                raise RuntimeError('教学任务没有产生计算结果') from None
        raise RuntimeError('教学任务尚无计算结果')

    def apply_result(self, job_id: str, store: SceneStore, engineering_request=None) -> dict:
        value = self.get_result(job_id)
        if scene_calculation_key(store.to_dict()) != value['scene_key']:
            raise TeachingResultStaleError('这是改场景之前的结果，已丢弃；需要请再点光学计算')
        if value.get('engineering_request') and engineering_calculation_key(engineering_request)!=engineering_calculation_key(value['engineering_request']):
            raise TeachingResultStaleError('仿真工程或数值配置已修改，旧的教学分析结果已丢弃。')
        result = value['physics']
        artifacts = dict(result.get('artifacts') or {})
        rays = [{'start': ray['start_teaching_mm'], 'end': ray['end_teaching_mm'], 'power_fraction': ray['power_fraction']}
                for ray in result['rays']]
        if not artifacts:
            artifacts[result['analysis']] = {key: result[key] for key in ('source', 'status', 'metrics', 'warnings', 'errors')}
            artifacts[result['analysis']]['rays'] = rays
        if rays and 'raytrace' in artifacts and not artifacts['raytrace'].get('rays'):
            artifacts['raytrace']['rays'] = rays
        for kind, artifact in artifacts.items():
            if kind != 'geometry':
                store.apply_result(kind, artifact, source_revision=result['scene_revision'])
        return {'scene': store.to_dict(), 'physics': result, 'job_id': job_id}
