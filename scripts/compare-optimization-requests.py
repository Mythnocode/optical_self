"""Compare captured native optimization submission with the running prepare API."""
import json, urllib.request
from pathlib import Path
root = Path(__file__).resolve().parents[1]/'tests/golden'
captured = json.loads((root/'ui-baseline/optimization/requests.json').read_text(encoding='utf-8'))[0]['payload']
simulation = {key:value for key,value in captured.items() if not key.startswith('opt_')}
engineering = captured['opt_options']['engineering_constraints']
config = {**engineering, 'objective':'最大化耦合效率', 'max_iterations':300, 'evaluation_mode':'formal'}
variables = [dict(path=row['path'],label=row['label'],current=str(row['initial_value']),lower=str(row['lower_bound']),upper=str(row['upper_bound'])) for row in captured['opt_variables']]
request = urllib.request.Request('http://127.0.0.1:8000/api/v1/optimization/prepare',data=json.dumps(dict(simulation=simulation,config=config,variables=variables)).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request) as response:
    prepared = json.load(response)['data']
different = [key for key in set(captured)|set(prepared) if captured.get(key)!=prepared.get(key)]
record = dict(equal=not different,different_keys=different,original=captured,prepared=prepared)
target=root/'ui-current/optimization'; target.mkdir(parents=True,exist_ok=True)
(target/'request-comparison.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(equal=not different,different_keys=different)))
