"""Record scoped geometry comparisons from the manually captured Qt/web views."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
native=json.loads((root/'tests/golden/ui-baseline/explainability/geometry.json').read_text(encoding='utf-8'))
web=json.loads((root/'tests/golden/ui-current/explainability/geometry.json').read_text(encoding='utf-8'))
report={}
for name,rows in web.items():
    if not name.startswith('chart-') or name not in native:continue
    comparisons=[]
    for row in rows:
        kind={'SELECT':'QComboBox','BUTTON':'QPushButton','DIV':'PlotCanvas'}.get(row['kind'],'QLabel')
        matches=[other for other in native[name] if other['kind']==kind and other['text']==row['text']]
        if len(matches)!=1:
            comparisons.append({'kind':kind,'text':row['text'],'matching_native_controls':len(matches)})
            continue
        delta=[float(a)-float(b) for a,b in zip(row['bounds'],matches[0]['bounds'])]
        comparisons.append({'kind':kind,'text':row['text'],'delta':delta,'max_absolute_difference':max(abs(v) for v in delta)})
    report[name]={'controls':len(comparisons),'unmatched':sum('delta' not in x for x in comparisons),'max_rectangle_difference':max((x.get('max_absolute_difference',0) for x in comparisons),default=0),'comparisons':comparisons}
target=root/'tests/golden/ui-current/explainability/layout-comparison.json'
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print({name:{k:v for k,v in value.items() if k!='comparisons'} for name,value in report.items()})
