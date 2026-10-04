"""Record manual API acceptance against the captured original synchronization."""
import copy
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parents[1]
baseline = root / 'tests/golden/ui-baseline/teaching/sync'
target = root / 'tests/golden/ui-current/teaching/sync'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def post(path, value):
    request = Request('http://127.0.0.1:8000/api/v1' + path,
                      data=json.dumps(value).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)

native = read(baseline / 'original-published-project.json')
web = read(target / 'published-simulation-request.json')
record = {'publish': {name: native['simulation_project'][name] == web['project'][name]
                      for name in ('source', 'receiver', 'surfaces')},
          'research_profile_equal': native['research_profile'] == web['frontend_state']['research_profile']}
engineering = read(root / 'frontend_web/src/teaching/domain/default-engineering-request.json')
engineering['project'].pop('calculation_contract', None)
code, response = post('/teaching/scenes/from-simulation', {
    'scene': read(baseline / 'initial-scene.json'), 'simulation': engineering, 'inherit_contract': True})
(target / 'from-simulation-response.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
record['from_simulation'] = {'status': code, 'full_native_scene_equal': response.get('data', {}).get('scene') == read(baseline / 'original-four-asphere-scene.json')}
job = read(target / 'web-engineering-coupling-job.json')
job_id = read(target / 'engineering-comparison.json')['coupling']['job_id']
cases = {'same': {'scene': job['scene'], 'engineering_request': job['engineering_request']},
         'missing_engineering': {'scene': job['scene']},
         'changed_precision': {'scene': job['scene'], 'engineering_request': copy.deepcopy(job['engineering_request'])},
         'selection_only': {'scene': copy.deepcopy(job['scene']), 'engineering_request': job['engineering_request']}}
cases['changed_precision']['engineering_request']['precision'] = 'preview' if job['engineering_request']['precision'] != 'preview' else 'standard'
cases['selection_only']['scene']['selected_component_id'] = None
record['apply'] = {}
for name, payload in cases.items():
    code, response = post('/teaching/jobs/' + job_id + '/apply', payload)
    record['apply'][name] = {'status': code, 'error': response.get('error')}
    if name == 'same' and code == 200:
        record['geometry_preserved_on_formal_apply'] = response['data']['scene']['results'].get('geometry') == job['scene']['results'].get('geometry')
(target / 'workflow-comparison.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False))
