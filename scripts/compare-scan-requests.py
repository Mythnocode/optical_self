"""Compare captured native line/grid submissions with the running prepare API."""
import json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'tests/golden'
captured=json.loads((root/'ui-baseline/scan/requests.json').read_text(encoding='utf-8'))
reports=[]
for item in captured:
    native=item['payload']; simulation={k:v for k,v in native.items() if not k.startswith('scan_')}
    config=dict(scan_mode={'line_1d':'一维扫描','grid_2d':'二维扫描'}[native['scan_mode']],response='耦合效率',scale='线性采样',points=21)
    variables=[dict(path=p['path'],lower=str(p['start']),upper=str(p['stop'])) for p in native['scan_parameters']]
    req=urllib.request.Request('http://127.0.0.1:8000/api/v1/scan/prepare',data=json.dumps(dict(simulation=simulation,config=config,variables=variables)).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as response: prepared=json.load(response)['data']
    different=[k for k in set(native)|set(prepared) if native.get(k)!=prepared.get(k)]
    reports.append(dict(mode=native['scan_mode'],equal=not different,different_keys=different,native=native,prepared=prepared))
target=root/'ui-current/scan';target.mkdir(exist_ok=True,parents=True)
(target/'request-comparison.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
print([{k:r[k] for k in ('mode','equal','different_keys')} for r in reports])
