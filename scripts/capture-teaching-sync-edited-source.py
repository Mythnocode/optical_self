"""Compare original live editor plus last submitted numerical contract mapping."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from urllib.request import Request, urlopen
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from frontend_pyside.state.project_context import ProjectContext
from frontend_pyside.features.teaching_v2.model import SceneStore
from frontend_pyside.features.simulation.form_state import SimulationFormState
from frontend_pyside.api.payloads import serialize_project
app = QApplication([])
legacy = types.ModuleType('frontend_pyside.modules.teaching._edited_original')
legacy.__package__ = 'frontend_pyside.modules.teaching'
sys.modules[legacy.__name__] = legacy
source = subprocess.check_output(['git','show','HEAD:frontend_pyside/modules/teaching/shell.py'], cwd=root).decode('utf-8')
exec(compile(source, 'original-teaching-edited-source.py', 'exec'), legacy.__dict__)
baseline = root/'tests/golden/ui-baseline/teaching/sync/lifecycle'
current = root/'tests/golden/ui-current/teaching/sync/lifecycle'
context = ProjectContext()
project = context.project
project.name = 'Lifecycle before-first-submission'
project.wavelength_nm = 850.0
project.receiver_mfd_um = 9.0
for index, surface in enumerate(project.surfaces):
    surface.element_id = f'element-lifecycle-{surface.group_id}'
    surface.surface_id = f'surface-lifecycle-{index+1}'
state = SimulationFormState()
state = replace(state, source=replace(state.source, wavelength_nm=850.0), receiver=replace(state.receiver, mode_field_diameter_x_um=9.0, mode_field_diameter_y_um=9.0), calculation=replace(state.calculation, output_grid_size=129, pupil_sample_count=17))
submitted = {'request_id':'sim-lifecycle-edited-source', 'project':serialize_project(project,state), 'options':state.request_options(), 'precision':state.calculation.precision, 'analyses':list(state.calculation.analyses), 'random_seed':42}
stored = dict(submitted['project'])
stored['calculation_contract'] = {'options':submitted['options'], 'precision':submitted['precision']}
context.set_simulation_project_payload(stored)
project.surfaces[0].radius_mm = 6.2
project.wavelength_nm = 940.0
state = replace(state, source=replace(state.source, wavelength_nm=940.0), calculation=replace(state.calculation, output_grid_size=257))
editor = serialize_project(project,state)
store = SceneStore(start_empty=True)
initial = store.to_dict()
initial['scene_id'] = 'scene-lifecycle-edited-source'
store.restore_dict(initial)
statuses = []
shell = types.SimpleNamespace(store=store, context=types.SimpleNamespace(project=context), status=types.SimpleNamespace(setText=statuses.append), view=types.SimpleNamespace(fit_scene=lambda:None), view3d=types.SimpleNamespace(reset_camera=lambda:None), controller=types.SimpleNamespace(request_preview=lambda:None), set_result_origin=lambda _:None, _engineering_lens_groups=legacy.TeachingShell._engineering_lens_groups)
legacy.TeachingShell._sync_scene_from_engineering_project(shell)
expected = json.loads(json.dumps(store.to_dict()))
with urlopen(Request('http://127.0.0.1:8000/api/v1/teaching/scenes/from-simulation', data=json.dumps({'scene':initial, 'simulation':submitted, 'editor_project':editor, 'inherit_contract':True}).encode(), headers={'Content-Type':'application/json'}), timeout=30) as response:
    actual = json.load(response)['data']
for directory, name, value in [(baseline,'edited-source-scene',expected), (baseline,'edited-source-editor',editor), (baseline,'edited-source-submitted',submitted), (current,'edited-source-response',actual)]:
    (directory/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
record = {'full_scene_equal':expected==actual['scene'], 'status_equal':statuses[-1]==actual['status'], 'editor_wavelength_nm':editor['source']['wavelength_nm'], 'mapped_wavelength_nm':actual['scene']['components'][0]['params']['wavelength_nm'], 'mapped_first_radius_mm':actual['scene']['components'][1]['params']['radius1_mm'], 'contract_grid_size':actual['engineering_request']['options']['hybrid']['grid_size']}
(current/'edited-source-comparison.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps(record))
