"""Compare scoped measured native/browser current-explanation controls."""
import json,re
from html import unescape
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'tests/golden'
native=json.loads((root/'ui-baseline/current-explanation/geometry.json').read_text(encoding='utf-8'))
browser=json.loads((root/'ui-current/current-explanation/geometry.json').read_text(encoding='utf-8'))
def key(row):
    kind=row['kind'];text=row.get('text') or '';classes=row.get('cls','').split();name=row.get('name','')
    pairs={'current-explanation-summary':'ExplainSummaryPanel','current-explanation-stack':'ExplainSummaryStack','current-explanation-physics':'ExplainFormulaCard'}
    for cls,label in pairs.items():
        if cls in classes:return ('layout',label)
    if kind in ('QFrame','QStackedWidget'):return ('layout',name)
    if kind=='FormulaImageLabel' or 'explanation-formula' in classes:return ('formula','')
    if kind=='PlotCanvas' or 'explainability-result-canvas' in classes:return ('canvas','')
    if 'current-explanation-details' in classes or kind=='QLabel' and text.startswith('<div'):return ('details','')
    if kind=='QComboBox' or kind=='SELECT':kind='select'
    elif kind in ('QPushButton','QToolButton','BUTTON'):kind='button'
    else:kind='text'
    return (kind,re.sub(r'\s+',' ',unescape(text)).strip())
report={}
for name in ['selected-uncomputed','rf-analysis','rf-physics','rf-next','xgboost-analysis','xgboost-physics','xgboost-next']:
    if name not in browser:continue
    used=set();differences=[];missing=[]
    for row in native[name]:
        options=[(i,other) for i,other in enumerate(browser[name]) if i not in used and key(row)==key(other)]
        if not options:missing.append({'kind':row['kind'],'text':row['text']});continue
        i,other=min(options,key=lambda pair:sum(abs(a-b) for a,b in zip(row['bounds'],pair[1]['bounds'])))
        used.add(i);delta=max(abs(a-b) for a,b in zip(row['bounds'],other['bounds']))
        differences.append(dict(kind=row['kind'],text=row['text'],maximum_difference=delta,native=row['bounds'],browser=other['bounds']))
    report[name]=dict(controls=len(native[name]),unmatched=missing,maximum_difference=max((row['maximum_difference'] for row in differences),default=0),differences=differences)
(root/'ui-current/current-explanation/layout-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print({name:dict(controls=row['controls'],unmatched=len(row['unmatched']),max=row['maximum_difference']) for name,row in report.items()})
