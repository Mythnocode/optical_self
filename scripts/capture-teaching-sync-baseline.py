"""Capture original live shell's engineering synchronization and compare extraction."""
import json
import os
from pathlib import Path
import subprocess
import sys
import types

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from frontend_pyside.state.project_context import ProjectContext
from frontend_pyside.features.teaching_v2.model import SceneStore as QtStore
from shared_presentation.teaching_model import SceneStore
from shared_presentation.teaching_sync import scene_from_engineering
from shared_presentation.teaching_sync import publish_parameters
app=QApplication([])
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/modules/teaching/shell.py'],cwd=root).decode('utf-8')
legacy=types.ModuleType('frontend_pyside.modules.teaching._original_sync_shell')
legacy.__package__='frontend_pyside.modules.teaching';sys.modules[legacy.__name__]=legacy
exec(compile(source,'original-sync-shell.py','exec'),legacy.__dict__)
native_store=QtStore(start_empty=True);initial=native_store.to_dict();initial['scene_id']='scene-migration-engineering-baseline';native_store.restore_dict(initial)
context=ProjectContext()
status=[]
shell=types.SimpleNamespace(store=native_store,context=types.SimpleNamespace(project=context),
    status=types.SimpleNamespace(setText=status.append),view=types.SimpleNamespace(fit_scene=lambda:None),
    view3d=types.SimpleNamespace(reset_camera=lambda:None),controller=types.SimpleNamespace(request_preview=lambda:None),
    set_result_origin=lambda value:None,_engineering_lens_groups=legacy.TeachingShell._engineering_lens_groups)
shell._sync_scene_from_engineering_project=lambda:legacy.TeachingShell._sync_scene_from_engineering_project(shell)
legacy.TeachingShell._apply_scheme(shell,4)
native=native_store.to_dict();project=context.project;serialized=context.simulation_project_payload
# Stabilize only opaque identity fields in the exported fixture, as in the
# existing simulation-default exporter. The optical prescription is unchanged.
for index,surface in enumerate(project.surfaces):
    surface.element_id=f'element-teaching-{surface.group_id}'
    surface.surface_id=f'surface-teaching-{index+1}'
serialized=legacy.serialize_project(project,legacy.SimulationFormState())
serialized['calculation_contract']={'options':shell._engineering_contract['options'],'precision':shell._engineering_contract['precision']}
context.set_simulation_project_payload(serialized);shell._engineering_contract['project']=serialized
pure=SceneStore(start_empty=True);pure.restore_dict(initial)
result=scene_from_engineering(pure,project,serialized)
target=root/'tests/golden/ui-baseline/teaching/sync';target.mkdir(parents=True,exist_ok=True)
for name,value in [('initial-scene',initial),('original-four-asphere-scene',native),('original-engineering-project',serialized)]:
    (target/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
comparison={'full_scene_equal':native==result,'component_count':len(native['components']),
            'native_status':status,'engineering_contract_inherited':bool(shell._engineering_contract)}
(target/'extraction-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf-8')
contract=shell._engineering_contract
request={'request_id':'sim-teaching-four-asphere-default','project':contract['project'],
         'options':contract['options'],'precision':contract['precision'],
         'analyses':list(legacy.SimulationFormState().calculation.analyses),'random_seed':42}
(root/'frontend_web/src/teaching/domain/default-engineering-request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(comparison,ensure_ascii=False))
published=root/'tests/golden/ui-current/teaching/sync/published-teaching-scene.json'
if published.exists():
    native_store.restore_dict(json.loads(published.read_text(encoding='utf-8')))
    shell._flash_tool_button=lambda key:None
    shell._invalidate_engineering_contract=lambda:legacy.TeachingShell._invalidate_engineering_contract(shell)
    legacy.TeachingShell._toolbar_action(shell,'sync_to_simulation')
    expected_publish={'changes':publish_parameters(native_store),
                      'simulation_project':context.simulation_project_payload,'research_profile':context.research_profile,
                      'status':status[-1]}
    (target/'original-published-project.json').write_text(json.dumps(expected_publish,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Captured native mapped parameters and teaching research snapshot.')
