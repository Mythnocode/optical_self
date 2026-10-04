"""Compare actual ordinary-project browser jobs with the original physics gateway."""
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import subprocess
import sys
import types
from urllib.request import urlopen
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from shared_presentation.teaching_model import SceneStore
from shared_presentation.teaching_coordinates import transform_from_reference
from backend.optical_ml_app.infrastructure.json_utils import to_jsonable
legacy=types.ModuleType('frontend_pyside.features.teaching_v2._ordinary_original_physics')
legacy.__package__='frontend_pyside.features.teaching_v2';sys.modules[legacy.__name__]=legacy
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/features/teaching_v2/physics.py'],cwd=root).decode('utf-8')
exec(compile(source,'original-ordinary-physics.py','exec'),legacy.__dict__)
baseline=root/'tests/golden/ui-baseline/teaching/sync/lifecycle';current=root/'tests/golden/ui-current/teaching/sync/lifecycle'
parser=argparse.ArgumentParser()
parser.add_argument('--scenario',choices=['ordinary','edited-source'],default='ordinary')
scenario=parser.parse_args().scenario
def get(path):
    with urlopen('http://127.0.0.1:8000/api/v1'+path,timeout=30) as r:return json.load(r)['data']
exclude={'elapsed_ms','coupling_output_window_plan_cache_hit','GlobalFiberModeCache_misses','GlobalFiberModeCache_size'}
def stable(v):
    if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if k not in exclude}
    if isinstance(v,list):return [stable(x) for x in v]
    return v
chosen={}
for job in get('/jobs?job_type=teaching&limit=12'):
    if job['status']!='completed':continue
    value=get('/teaching/jobs/'+job['job_id']+'/result');request=value.get('engineering_request')
    if request and request['project']['source']['wavelength_nm']==850 and value['analysis'] in ('spot','coupling') and value['analysis'] not in chosen:
        chosen[value['analysis']]=(job['job_id'],value)
if set(chosen)!= {'spot','coupling'}:raise RuntimeError('Actual 850 nm browser pair is not completed yet.')
engineering=json.loads((baseline/('edited-source-submitted.json' if scenario=='edited-source' else 'before-first-submission-request.json')).read_text(encoding='utf-8'))
record={}
for analysis,(job_id,actual) in chosen.items():
    store=SceneStore(start_empty=True);store.restore_dict(actual['scene']);snapshot=store.snapshot()
    gateway=legacy.FormalTeachingGateway(engineering_request_provider=lambda:engineering)
    expected=to_jsonable(asdict(gateway.compute(legacy.PhysicsRequest(snapshot,analysis,transform_from_reference(snapshot.reference)))))
    (baseline/(scenario+'-'+analysis+'-physics.json')).write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
    (current/(scenario+'-'+analysis+'-job.json')).write_text(json.dumps(actual,ensure_ascii=False,indent=2),encoding='utf-8')
    record[analysis]={'job_id':job_id,'physics_equal_excluding_runtime_diagnostics':stable(expected)==stable(actual['physics']),
                      'metrics_equal':expected['metrics']==actual['physics']['metrics'],'metrics':actual['physics']['metrics'],
                      'precision':actual['engineering_request']['precision'],'submitted_grid':actual['engineering_request']['options']['hybrid']['grid_size'],
                      'excluded_runtime_diagnostics':sorted(exclude)}
(current/(scenario+'-formal-comparison.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record))
