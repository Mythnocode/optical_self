"""Compare measured native and browser controls for captured parameter states."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
baseline=root/'tests/golden/ui-baseline/parameter-explanation'
current=root/'tests/golden/ui-current/parameter-explanation'
native=json.loads((baseline/'geometry.json').read_text(encoding='utf-8'))
browser=json.loads((current/'geometry.json').read_text(encoding='utf-8'))
classes={'explanation-chain-scroll':'ExplainChainScroll','explanation-selection-card':'ExplainSelectionCard',
         'explanation-chain-card':'ExplainChainCard','explanation-feature-picker':'ExplainFeaturePicker',
         'explanation-parameter-list':'ObjectList'}
def key(row):
    kind=row['kind'];text=row.get('text') or ''
    for cls,label in classes.items():
        if cls in row.get('cls','').split():return ('layout',label)
    if kind in ('QScrollArea','QFrame','QListWidget'):return ('layout',text)
    if kind=='FormulaImageLabel' or 'explanation-formula' in row.get('cls','').split():return ('formula','')
    if kind=='QComboBox' or kind=='SELECT':kind='select'
    elif kind=='QLineEdit' or kind=='INPUT':kind='input'
    elif kind=='parameter-row' or kind=='BUTTON' and ' / ' in text:kind='parameter-row'
    elif kind in ('QPushButton','QToolButton','BUTTON'):kind='button'
    elif kind=='PlotCanvas' or 'explainability-result-canvas' in row.get('cls','').split():return ('canvas','')
    elif kind=='ranking-row' or kind=='LABEL' and re.match(r'^\d+\.',text):kind='ranking-row'
    else:kind='text'
    return (kind,re.sub(r'\s+',' ',text).strip())
report={}
for name in ['curve','curve-l1','curve-unavailable','chain-three','chain-bottom','chain-none','chain-one','xgboost-curve','xgboost-chain-three']:
    if name not in browser:continue
    left=native[name];right=browser[name];used=set();differences=[];missing=[]
    for row in left:
        candidates=[(i,other) for i,other in enumerate(right) if i not in used and key(row)==key(other)]
        if not candidates:missing.append({'kind':row['kind'],'text':row['text']});continue
        i,other=min(candidates,key=lambda pair:sum(abs(a-b) for a,b in zip(row['bounds'],pair[1]['bounds'])))
        used.add(i);delta=max(abs(a-b) for a,b in zip(row['bounds'],other['bounds']))
        differences.append({'text':row['text'],'kind':row['kind'],'maximum_difference':delta,'native':row['bounds'],'browser':other['bounds']})
    report[name]={'controls':len(left),'unmatched':missing,'maximum_difference':max((d['maximum_difference'] for d in differences),default=0),'differences':differences}
(current/'layout-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print({name:{'controls':r['controls'],'unmatched':len(r['unmatched']),'max':r['maximum_difference']} for name,r in report.items()})
