"""Record restored browser complex fields and compare original Teaching physics."""
from dataclasses import asdict
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
import numpy as np
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from backend.optical_ml_app.application.complex_fields import load_complex_field
from backend.optical_ml_app.infrastructure.json_utils import to_jsonable
from shared_contracts.simulation import SimulationRequest
from shared_presentation.teaching_model import SceneStore
from shared_presentation.teaching_coordinates import transform_from_reference

baseline = root / 'tests/golden/ui-baseline/teaching/sync/lifecycle'
current = root / 'tests/golden/ui-current/teaching/sync/lifecycle'
parser = argparse.ArgumentParser()
parser.add_argument('--spot', default='job-55fae3ffe5f8')
parser.add_argument('--coupling', default='job-3a985d9f833b')
parser.add_argument('--scenario', default='imported')
parser.add_argument('--refresh-field-hash-only', action='store_true')
args = parser.parse_args()
def field_hash(values):
    samples = np.asarray([values['real'], values['imag']], dtype='<f8')
    samples[samples == 0] = 0.0
    return hashlib.sha256(samples.tobytes()).hexdigest()
if args.refresh_field_hash_only:
    original_field = load_complex_field(root/'tests/golden/simulation/imported-mode-513.npz')
    digest = field_hash({'real': original_field.real, 'imag': original_field.imag})
    for scenario in ('imported', 'field-replacement'):
        file = current / (scenario + '-formal-comparison.json')
        evidence = json.loads(file.read_text(encoding='utf-8'))
        # Existing complete array equality permits a canonical numeric digest.
        for item in evidence.values():
            if not item['request_checks']['real_equals_original_loader'] or not item['request_checks']['imag_equals_original_loader']:
                raise ValueError('Full array equality is required before refreshing the numeric digest.')
            item['field_sha256'] = digest
            item['field_hash_encoding'] = 'little-endian float64 [real,imag], signed zero normalized'
        file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Recorded canonical numeric field digests; full-array equality evidence is preserved.')
    sys.exit(0)
fixture = json.loads((baseline / 'imported-513-project.json').read_text(encoding='utf-8'))
field = load_complex_field(root / 'tests/golden/simulation/imported-mode-513.npz', expected_grid_size=513)
expected_request = copy.deepcopy(fixture)
expected_request['options']['hybrid']['imported_mode_values'] = {
    'real': [list(row) for row in field.real], 'imag': [list(row) for row in field.imag],
}
expected_request = SimulationRequest.model_validate(expected_request).model_dump(mode='json')
legacy = types.ModuleType('frontend_pyside.features.teaching_v2._imported_original_physics')
legacy.__package__ = 'frontend_pyside.features.teaching_v2'
sys.modules[legacy.__name__] = legacy
source = subprocess.check_output(['git', 'show', 'HEAD:frontend_pyside/features/teaching_v2/physics.py'], cwd=root).decode('utf-8')
exec(compile(source, 'original-imported-physics.py', 'exec'), legacy.__dict__)
excluded = {'elapsed_ms', 'coupling_output_window_plan_cache_hit', 'GlobalFiberModeCache_misses', 'GlobalFiberModeCache_size'}

def stable(value):
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value

def get(path):
    with urlopen('http://127.0.0.1:8000/api/v1' + path, timeout=60) as response:
        return json.load(response)['data']

def differences(expected, actual, path=''):
    if expected == actual:
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        return [item for key in sorted(expected.keys() | actual.keys()) for item in differences(expected.get(key), actual.get(key), path + '/' + key)]
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        return [item for index, (left, right) in enumerate(zip(expected, actual)) for item in differences(left, right, path + '/' + str(index))]
    return [{'path': path, 'expected': expected, 'actual': actual}]

record = {}
for analysis, job_id in [('spot', args.spot), ('coupling', args.coupling)]:
    actual = get('/teaching/jobs/' + job_id + '/result')
    submitted = actual['engineering_request']
    values = submitted['options']['hybrid']['imported_mode_values']
    request_checks = {
        'real_equals_original_loader': values['real'] == expected_request['options']['hybrid']['imported_mode_values']['real'],
        'imag_equals_original_loader': values['imag'] == expected_request['options']['hybrid']['imported_mode_values']['imag'],
        'options_equal': submitted['options'] == expected_request['options'],
        'precision_equal': submitted['precision'] == expected_request['precision'],
        'project_equal_except_fingerprint': {k:v for k,v in submitted['project'].items() if k != 'fingerprint'} == {k:v for k,v in expected_request['project'].items() if k != 'fingerprint'},
    }
    store = SceneStore(start_empty=True)
    store.restore_dict(actual['scene'])
    snapshot = store.snapshot()
    gateway = legacy.FormalTeachingGateway(engineering_request_provider=lambda: expected_request)
    expected = to_jsonable(asdict(gateway.compute(legacy.PhysicsRequest(snapshot, analysis, transform_from_reference(snapshot.reference)))))
    (baseline / (args.scenario + '-' + analysis + '-physics.json')).write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding='utf-8')
    # Keep scene/result evidence without duplicating the 513-by-513 arrays.
    compact_actual = {key:value for key,value in actual.items() if key != 'engineering_request'}
    (current / (args.scenario + '-' + analysis + '-job.json')).write_text(json.dumps(compact_actual, ensure_ascii=False, indent=2), encoding='utf-8')
    record[analysis] = {
        'job_id': job_id, 'request_checks': request_checks,
        'physics_equal_excluding_runtime_diagnostics': stable(expected) == stable(actual['physics']),
        'metrics_equal': expected['metrics'] == actual['physics']['metrics'], 'metrics': actual['physics']['metrics'],
        'grid_size': submitted['options']['hybrid']['grid_size'],
        'field_sha256': field_hash(values),
        'field_hash_encoding': 'little-endian float64 [real,imag], signed zero normalized',
        'request_differences': differences(expected_request['project'], submitted['project'], 'project') + differences(expected_request['options'], submitted['options'], 'options'),
        'excluded_runtime_diagnostics': sorted(excluded),
        'job': get('/jobs/' + job_id),
    }
    print(analysis, json.dumps({key:value for key,value in record[analysis].items() if key not in {'metrics', 'job', 'request_differences'}}), flush=True)
(current / (args.scenario + '-formal-comparison.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
