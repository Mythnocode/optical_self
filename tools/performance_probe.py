from __future__ import annotations

"""Small reproducible performance probe for a running backend.

It measures actual HTTP/runtime behaviour; it does not assert the estimates from the
performance plan.  Run against an external USER_DATA_DIR so probe jobs do not pollute
user projects.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend_pyside.api.payloads import serialize_project
from frontend_pyside.state.project_context import default_project
from frontend_pyside.features.simulation.form_state import SimulationFormState


def unwrap(response: requests.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "OK":
        raise RuntimeError(body)
    return body.get("data")


def wait(base: str, job_id: str, timeout=180.0):
    history=[]; t0=time.perf_counter(); last=None
    while True:
        st=unwrap(requests.get(f"{base}/jobs/{job_id}",timeout=10))
        marker=(st.get('status'), round(float(st.get('progress',0) or 0),4), st.get('completed_items'), st.get('total_items'))
        if marker!=last: history.append(marker); last=marker
        if st.get('status')=='completed':
            return time.perf_counter()-t0, history, unwrap(requests.get(f"{base}/jobs/{job_id}/result",timeout=30))
        if st.get('status') in {'failed','cancelled'}: raise RuntimeError(st)
        if time.perf_counter()-t0>timeout: raise TimeoutError(job_id)
        time.sleep(.3)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--base-url',default='http://127.0.0.1:8000/api/v1')
    ap.add_argument('--out',default='')
    args=ap.parse_args(); b=args.base_url.rstrip('/')
    report={}
    t=time.perf_counter(); report['health']=unwrap(requests.get(b+'/health',timeout=10)); report['health_http_s']=time.perf_counter()-t

    project=serialize_project(default_project(), SimulationFormState())
    assert float(project["source"]["wavelength_nm"]) == 780.0
    scan={
        'request_id':'performance-probe-scan', 'project':project, 'analyses':['coupling'], 'precision':'preview', 'engine':'headless',
        'scan_mode':'line_1d',
        'scan_parameters':[{'path':'surfaces[1].distance_to_next_mm','label':'L1-L2 厚度','unit':'mm','start':14.70,'stop':15.00,'points':5}],
        'scan_response_metrics':['coupling_efficiency'],
    }
    jid=unwrap(requests.post(b+'/scan/jobs',json=scan,timeout=20))['job_id']
    elapsed,hist,res=wait(b,jid)
    report['scan_5']={'elapsed_s':elapsed,'progress_history':hist,'values':res.get('response_values',{})}

    models=unwrap(requests.get(b+'/models',timeout=10)).get('models',[])
    datasets=unwrap(requests.get(b+'/headless-datasets',timeout=10)).get('items',[])
    bundle_path = ROOT / 'resources' / 'demo_assets' / 'quick_real_780nm' / 'bundle.json'
    bundle = json.loads(bundle_path.read_text(encoding='utf-8')) if bundle_path.exists() else {}
    demo_dataset_id = str((bundle.get('datasets') or [''])[0])
    demo_model_id = str((bundle.get('models') or [''])[0])
    demo_model=next((m for m in models if str(m.get('model_id','')) == demo_model_id),None)
    if demo_model and demo_dataset_id:
        # Packaged assets are registered through the same API as user datasets;
        # the probe discovers IDs from bundle.json instead of hard-coding an old bundle.
        raw=requests.get(f"{b}/headless-datasets/{demo_dataset_id}/files/samples-jsonl",timeout=10)
        raw.raise_for_status()
        row=json.loads(raw.text.splitlines()[0])
        p={'model_id':demo_model['model_id'],'features':row['feature_values']}
        pred=[]
        for _ in range(2):
            t=time.perf_counter(); value=unwrap(requests.post(f"{b}/models/{demo_model['model_id']}/predict",json=p,timeout=20)); pred.append({'elapsed_s':time.perf_counter()-t,'result':value})
        report['prediction']=pred
        sample_count = int(bundle.get('dataset_sample_count') or 64)
        sp={'dataset_id':demo_dataset_id,'target_name':'coupling_efficiency','top_k':12,'max_samples':min(100,sample_count),'background_sample_count':min(64,max(16,sample_count//3)),'random_seed':42}
        shap=[]
        for _ in range(2):
            t=time.perf_counter(); value=unwrap(requests.post(f"{b}/models/{demo_model['model_id']}/shap/explain",json=sp,timeout=60)); shap.append({'elapsed_s':time.perf_counter()-t,'cache_hit':value.get('cache_hit'),'elapsed_ms':value.get('elapsed_ms')})
        report['shap']=shap
    report['demo_dataset_registered']=any(str(x.get('dataset_id',''))==demo_dataset_id for x in datasets)
    report['demo_model_registered']=any(str(x.get('model_id',''))==demo_model_id for x in models)
    report['demo_dataset_id']=demo_dataset_id
    report['demo_model_id']=demo_model_id
    text=json.dumps(report,ensure_ascii=False,indent=2); print(text)
    if args.out:
        Path(args.out).write_text(text+'\n',encoding='utf-8')
    return 0


if __name__=='__main__': raise SystemExit(main())
