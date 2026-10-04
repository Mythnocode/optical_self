"""Compare actual browser engineering analyses with the original Git gateway."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import types
from urllib.request import urlopen

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
target=root/'tests/golden/ui-current/teaching/sync';target.mkdir(parents=True,exist_ok=True)
baseline=root/'tests/golden/ui-baseline/teaching/sync'
from shared_presentation.teaching_model import SceneStore
from shared_presentation.teaching_coordinates import transform_from_reference
from backend.optical_ml_app.infrastructure.json_utils import to_jsonable
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/features/teaching_v2/physics.py'],cwd=root).decode('utf-8')
legacy=types.ModuleType('frontend_pyside.features.teaching_v2._original_engineering_physics')
legacy.__package__='frontend_pyside.features.teaching_v2';sys.modules[legacy.__name__]=legacy
exec(compile(source,'original-engineering-physics.py','exec'),legacy.__dict__)
def get(path):
    with urlopen('http://127.0.0.1:8000/api/v1'+path,timeout=30) as response:return json.load(response)['data']
operational_keys={'elapsed_ms','coupling_output_window_plan_cache_hit','GlobalFiberModeCache_misses','GlobalFiberModeCache_size'}
def stable(value, operational=False):
    if isinstance(value,dict):return {key:stable(item,operational) for key,item in value.items() if key not in (operational_keys if operational else {'elapsed_ms'})}
    if isinstance(value,list):return [stable(item,operational) for item in value]
    return value
jobs=get('/jobs?job_type=teaching&limit=12');chosen={}
for job in jobs:
    if job['status']!='completed':continue
    value=get('/teaching/jobs/'+job['job_id']+'/result')
    if value.get('engineering_request') and value['analysis'] in ('spot','coupling') and value['analysis'] not in chosen:
        chosen[value['analysis']]=(job['job_id'],value)
record={}
for analysis,(job_id,actual) in chosen.items():
    store=SceneStore(start_empty=True);store.restore_dict(actual['scene']);snapshot=store.snapshot()
    engineering=json.loads((baseline/'original-engineering-project.json').read_text(encoding='utf-8'))
    contract=engineering['calculation_contract']
    gateway=legacy.FormalTeachingGateway(engineering_request_provider=lambda:{'project':engineering,'options':contract['options'],'precision':contract['precision']})
    expected=to_jsonable(asdict(gateway.compute(legacy.PhysicsRequest(snapshot,analysis,transform_from_reference(snapshot.reference)))))
    (baseline/f'original-engineering-{analysis}.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
    (target/f'web-engineering-{analysis}-job.json').write_text(json.dumps(actual,ensure_ascii=False,indent=2),encoding='utf-8')
    record[analysis]={'job_id':job_id,'physics_equal_excluding_elapsed_ms':stable(expected)==stable(actual['physics']),
                      'physics_equal_excluding_runtime_diagnostics':stable(expected,True)==stable(actual['physics'],True),
                      'excluded_runtime_diagnostics':sorted(operational_keys),
                      'metrics':actual['physics']['metrics'],'calculation_scope':actual['physics']['artifacts'][analysis].get('calculation_scope')}
native=json.loads((baseline/'original-four-asphere-scene.json').read_text(encoding='utf-8'))
web=json.loads((target/'four-asphere-scene.json').read_text(encoding='utf-8'))
for value in (native,web):
    for key in ('scene_id','revision','results','active_result_revision'):value.pop(key,None)
record['prescription']={'original_live_menu_equal':native==web}
(target/'engineering-comparison.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False))
