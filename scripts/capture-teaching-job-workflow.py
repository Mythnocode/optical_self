"""Record real local API acceptance actions; no mocked optical calculation."""
import copy
import json
from pathlib import Path
import time
import uuid
from urllib.request import Request,urlopen
from urllib.error import HTTPError

root=Path(__file__).resolve().parents[1]
target=root/'tests/golden/ui-current/teaching/analysis'
def call(path,body=None):
    request=Request('http://127.0.0.1:8000/api/v1'+path,
                    data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
                    headers={'Content-Type':'application/json'})
    try:
        with urlopen(request,timeout=30) as response:return response.status,json.load(response)
    except HTTPError as response:return response.code,json.load(response)
def terminal(job):
    for _ in range(100):
        _,response=call('/jobs/'+job)
        if response['data']['status'] in ('completed','failed','cancelled'):return response['data']
        time.sleep(.2)
    raise RuntimeError('Calculation remains live; inspect this job without restarting it: '+job)

ids=json.loads((target/'job-ids.json').read_text(encoding='utf-8'))
job=ids['spot']
_,saved=call('/teaching/jobs/'+job+'/result')
scene=saved['data']['scene']
record={}
for name,change in (
    ('same-scene',lambda s:None),
    ('selection-only',lambda s:s.update(selected_component_id=s['components'][0]['component_id'])),
    ('new-revision',lambda s:s.update(revision=s['revision']+1)),
    ('same-revision-different-pose',lambda s:s['components'][0]['pose'].update(y_mm=1)),
):
    candidate=copy.deepcopy(scene);change(candidate)
    code,response=call('/teaching/jobs/'+job+'/apply',candidate)
    record[name]={'http_status':code,'error':response.get('error')}
    if code==200:
        record[name]['scene_revision']=response['data']['scene']['revision']
        record[name]['result_kinds']=list(response['data']['scene']['results'])
        if name=='same-scene':(target/'applied-spot-scene.json').write_text(json.dumps(response['data']['scene'],ensure_ascii=False,indent=2),encoding='utf-8')

payload={'request_id':uuid.uuid4().hex,'scene':scene,'scene_revision':scene['revision'],'analysis':'raytrace'}
_,first=call('/teaching/jobs',payload);_,second=call('/teaching/jobs',payload)
cancel_id=first['data']['job_id']
cancel_code,cancel_response=call('/jobs/'+cancel_id+'/cancel',{})
record['idempotency-cancel']={'first_id':cancel_id,'repeated_id':second['data']['job_id'],'cancel_http':cancel_code,'terminal':terminal(cancel_id)}

miss=copy.deepcopy(scene)
fiber=next(component for component in miss['components'] if component['kind']=='fiber')
fiber['pose']['y_mm']=100
payload={'request_id':uuid.uuid4().hex,'scene':miss,'scene_revision':miss['revision'],'analysis':'coupling'}
code,response=call('/teaching/jobs',payload)
record['missed-receiver']={'submit_http':code}
if code==202:
    miss_id=response['data']['job_id'];record['missed-receiver']['terminal']=terminal(miss_id)
    _,result=call('/teaching/jobs/'+miss_id+'/result')
    (target/'missed-coupling-job.json').write_text(json.dumps(result['data'],ensure_ascii=False,indent=2),encoding='utf-8')
    _,applied=call('/teaching/jobs/'+miss_id+'/apply',miss)
    _,display=call('/teaching/analysis/presentation',applied['data']['scene'])
    record['missed-receiver']['display']=display['data']
else:record['missed-receiver']['error']=response.get('error')

(target/'job-workflow.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False))
