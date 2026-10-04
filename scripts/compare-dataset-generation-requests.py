"""Compare actual original Workbench requests with the running migration API."""
import json
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'tests/golden'
original = json.loads((root/'ui-baseline/dataset/generation-requests.json').read_text(encoding='utf-8'))
records = []
for captured in original:
    payload = captured['payload']
    options = {'dataset_name':payload['dataset_name'], 'family':'sequence' if payload['dataset_layout']=='sequence_long' else 'tabular', 'lens_count':payload['lens_count'], 'variable_paths':payload['design_variable_paths'], 'sample_count':payload['sample_count'], 'precision':'129×129'}
    request = urllib.request.Request('http://127.0.0.1:8000/api/v1/datasets/generation/prepare', data=json.dumps({'project':payload['base_project'],'options':options}).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request) as response:
        prepared = json.load(response)['data']
    records.append({'layout':payload['dataset_layout'],'equal':payload==prepared,'different_keys':[key for key in set(payload)|set(prepared) if payload.get(key)!=prepared.get(key)],'original':payload,'prepared':prepared})
(root/'ui-current/dataset/generation-request-comparison.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{key:item[key] for key in ('layout','equal','different_keys')} for item in records]))
