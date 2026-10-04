"""Capture ordinary-project sync from original Git shell and the live API."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from urllib.request import Request, urlopen

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from frontend_pyside.state.project_context import ProjectContext
from frontend_pyside.features.teaching_v2.model import SceneStore
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.api.payloads import serialize_project
app=QApplication([])
legacy=types.ModuleType('frontend_pyside.modules.teaching._lifecycle_original')
legacy.__package__='frontend_pyside.modules.teaching';sys.modules[legacy.__name__]=legacy
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/modules/teaching/shell.py'],cwd=root).decode('utf-8')
exec(compile(source,'original-teaching-lifecycle.py','exec'),legacy.__dict__)
baseline=root/'tests/golden/ui-baseline/teaching/sync/lifecycle';baseline.mkdir(parents=True,exist_ok=True)
current=root/'tests/golden/ui-current/teaching/sync/lifecycle';current.mkdir(parents=True,exist_ok=True)
record={}
for has_contract in (False,True):
    name='submitted-contract' if has_contract else 'before-first-submission'
    context=ProjectContext();project=context.project
    project.name='Lifecycle '+name
    project.wavelength_nm=850.0;project.receiver_mfd_um=9.0
    for index,surface in enumerate(project.surfaces):
        surface.element_id=f'element-lifecycle-{surface.group_id}';surface.surface_id=f'surface-lifecycle-{index+1}'
    state=SimulationFormState()
    state=replace(state,source=replace(state.source,wavelength_nm=850.0),receiver=replace(state.receiver,mode_field_diameter_x_um=9.0,mode_field_diameter_y_um=9.0),
                  calculation=replace(state.calculation,output_grid_size=129,pupil_sample_count=17))
    request={'request_id':'sim-lifecycle-'+name,'project':serialize_project(project,state),
             'options':state.request_options(),'precision':state.calculation.precision,'analyses':list(state.calculation.analyses),'random_seed':42}
    if has_contract:
        stored=dict(request['project']);stored['calculation_contract']={'options':request['options'],'precision':request['precision']}
        context.set_simulation_project_payload(stored)
    store=SceneStore(start_empty=True);initial=store.to_dict();initial['scene_id']='scene-lifecycle-'+name;store.restore_dict(initial)
    statuses=[]
    shell=types.SimpleNamespace(store=store,context=types.SimpleNamespace(project=context),status=types.SimpleNamespace(setText=statuses.append),
          view=types.SimpleNamespace(fit_scene=lambda:None),view3d=types.SimpleNamespace(reset_camera=lambda:None),
          controller=types.SimpleNamespace(request_preview=lambda:None),set_result_origin=lambda value:None,
          _engineering_lens_groups=legacy.TeachingShell._engineering_lens_groups)
    legacy.TeachingShell._sync_scene_from_engineering_project(shell)
    expected=json.loads(json.dumps(store.to_dict()))
    payload={'scene':initial,'simulation':request,'inherit_contract':has_contract}
    with urlopen(Request('http://127.0.0.1:8000/api/v1/teaching/scenes/from-simulation',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=30) as response:
        actual=json.load(response)['data']
    for directory,filename,value in ((baseline,name+'-scene',expected),(baseline,name+'-request',request),(baseline,name+'-initial',initial),(current,name+'-response',actual)):
        (directory/(filename+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    record[name]={'full_scene_equal':expected==actual['scene'],'status_equal':statuses[-1]==actual['status'],'native_contract_inherited':bool(shell._engineering_contract),
                  'components':len(expected['components'])}
(current/'comparison.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record))
