"""Record an actual UI dataset task's input provenance and scalar sample results."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import cloudpickle
import numpy as np
from backend.optical_ml_app.application.complex_fields import load_complex_field
from machine_learning.datasets.generator import dataset_simulation_options

parser = argparse.ArgumentParser()
parser.add_argument('job_id')
args = parser.parse_args()
data_root = Path(os.environ['TEMP']) / 'optical-js-training-20260930'
destination = root / 'tests/golden/ui-current/dataset/imported-mode'
destination.mkdir(parents=True, exist_ok=True)

def get(path):
    with urlopen('http://127.0.0.1:8000/api/v1' + path, timeout=60) as response:
        return json.load(response)['data']

status = get('/jobs/' + args.job_id)
if status['status'] != 'completed':
    raise RuntimeError('The actual task must complete before recording results.')
result = get('/jobs/' + args.job_id + '/result')
# This is our own locally generated task retry file, never an external pickle.
retry = cloudpickle.loads((data_root/'jobs'/args.job_id/'retry_payload.bin').read_bytes())
request = retry['args'][0]
if request.imported_mode is None:
    raise ValueError('This task did not use an imported receiving mode.')
mode = request.imported_mode.model_dump()
original = load_complex_field(root/'tests/golden/simulation/imported-mode-513.npz')
values = np.asarray([mode['real'], mode['imag']], dtype='<f8')
values[values == 0] = 0.0
samples = [json.loads(row) for row in (data_root/'datasets'/result['dataset_id']/'samples.jsonl').read_text(encoding='utf-8').splitlines() if row]
profiles = {}
for precision in ('preview', 'standard', 'high'):
    options = dataset_simulation_options(request.base_project, precision, imported_mode=mode)
    hybrid = options['hybrid']
    profiles[precision] = {key: value for key, value in hybrid.items() if key != 'imported_mode_values'}
    profiles[precision]['shared_arrays'] = hybrid['imported_mode_values']['real'] is mode['real'] and hybrid['imported_mode_values']['imag'] is mode['imag']
evidence = {
    'job_id': args.job_id, 'dataset_id': result['dataset_id'],
    'original_real_equal': mode['real'] == [list(row) for row in original.real],
    'original_imag_equal': mode['imag'] == [list(row) for row in original.imag],
    'sha256': hashlib.sha256(values.tobytes()).hexdigest(),
    'manifest_hash_matches': hashlib.sha256(values.tobytes()).hexdigest() == result['metadata']['imported_mode']['sha256'],
    'grid_size': len(mode['real']), 'mode_model': request.base_project.receiver.mode_model,
    'sample_count': result['sample_count'], 'valid_sample_count': result['valid_sample_count'],
    'failed_sample_count': result['failed_sample_count'],
    'failure_counts': dict(Counter(row['failure_code'] for row in samples if not row['valid'])),
    'trace_backend_sample_counts': result['metadata']['trace_backend_sample_counts'],
    'sample_trace_backends': dict(Counter(backend for row in samples for backend in set(row['metadata'].get('trace_backends', [])))),
    'precision_profiles': profiles,
}
compact_request = request.model_dump(exclude={'imported_mode'})
compact_request['imported_mode'] = {key: value for key, value in mode.items() if key not in ('real', 'imag')}
compact_request['imported_mode'].update(grid_size=len(mode['real']), sha256=evidence['sha256'])
for name, body in [('job', status), ('result', result), ('input-summary', compact_request), ('samples', samples), ('provenance', evidence)]:
    (destination/(name+'.json')).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in evidence.items() if key != 'precision_profiles'}, ensure_ascii=True))
