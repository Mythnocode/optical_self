"""Capture original Git-version Teaching gateway results for manual migration QA."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import types

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
source=subprocess.check_output(['git','show','HEAD:frontend_pyside/features/teaching_v2/physics.py'],cwd=root).decode('utf-8')
legacy=types.ModuleType('frontend_pyside.features.teaching_v2._original_physics')
legacy.__package__='frontend_pyside.features.teaching_v2'
sys.modules[legacy.__name__]=legacy
exec(compile(source,'original-physics.py','exec'),legacy.__dict__)
from frontend_pyside.features.teaching_v2.model import SceneStore
from frontend_pyside.features.teaching_v2.coordinates import transform_from_reference
from backend.optical_ml_app.infrastructure.json_utils import to_jsonable

store=SceneStore(start_empty=True)
store.restore_dict(json.loads((root/'tests/golden/ui-current/teaching/original-four-lens.json').read_text(encoding='utf-8')))
snapshot=store.snapshot()
target=root/'tests/golden/ui-baseline/teaching/analysis'
target.mkdir(parents=True,exist_ok=True)
gateway=legacy.FormalTeachingGateway()
for analysis in ('raytrace','spot','coupling','field','wavefront'):
    result=gateway.compute(legacy.PhysicsRequest(snapshot,analysis,transform_from_reference(snapshot.reference)))
    (target/f'original-{analysis}.json').write_text(json.dumps(to_jsonable(asdict(result)),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{analysis}: {result.status}, rays={len(result.rays)}, metrics={result.metrics}',flush=True)
