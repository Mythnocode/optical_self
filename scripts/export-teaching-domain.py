"""Export Web teaching manifests from the shared original Python domain."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shared_presentation.teaching_model import PLACEABLE_KINDS, KIND_PARAM_SPECS, SceneStore, default_params_for_kind
from shared_presentation.teaching_assets import housing_spec
from shared_presentation.teaching_inspector import LASER_PRESETS
from shared_presentation.teaching_equipment import EQUIPMENT_PRESETS, equipment_groups

target=ROOT/'frontend_web/src/teaching/domain'
def write(name,value):
    (target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

write('empty-scene.json',SceneStore(start_empty=True).to_dict())
write('parameter-labels.json',KIND_PARAM_SPECS)
write('laser-presets.json',[{'label':label,'params':params} for label,params in LASER_PRESETS])
write('equipment.json',{'groups':[{'title':title,'kinds':[kind for kind,_label in values]} for title,values in equipment_groups()],
                       'presets':{kind:{'title':title,'values':[{'label':label,'params':params} for label,params in values]}
                                  for kind,(title,values) in EQUIPMENT_PRESETS.items()}})
catalog={}
for kind,label in PLACEABLE_KINDS:
    spec=housing_spec(kind)
    catalog[kind]={'label':label,'asset':f'{spec.mesh_key}.glb','housingMm':[spec.length_mm,spec.width_mm,spec.height_mm],
                   'anchor':spec.origin,'defaultParams':default_params_for_kind(kind)}
write('component-catalog.json',catalog)
print('Exported original teaching domain manifests.')
