"""Record comparison of scene exports captured through the actual browser UI."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'tests/golden'
native=root/'ui-baseline/teaching/sync/lifecycle'
web=root/'ui-current/teaching/sync/lifecycle'
record={}
for scenario,browser_file in [('before-first-submission','browser-before-submission-scene.json'),('submitted-contract','browser-after-submission-scene.json'),('edited-source','browser-edited-source-scene.json')]:
    expected=json.loads((native/(scenario+'-scene.json')).read_text(encoding='utf-8'))
    actual=json.loads((web/browser_file).read_text(encoding='utf-8'))
    record[scenario]={key:expected[key]==actual[key] for key in ['components','reference','baseline_enabled','baseline_x_mm','selected_component_id']}
(web/'browser-comparison.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record))
