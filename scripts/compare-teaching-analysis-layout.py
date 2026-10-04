"""Compare recorded Qt and browser analysis controls after manual UI actions."""
import json
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
root=Path(__file__).resolve().parents[1]/'tests/golden'
native=root/'ui-baseline/teaching/analysis'
web=root/'ui-current/teaching/analysis'
qt=json.loads((native/'geometry.json').read_text(encoding='utf-8'))
js=json.loads((web/'geometry.json').read_text(encoding='utf-8'))
record={}
for name in ('completed','stale','blocked','running-update-spot','engineering-completed','ordinary-completed','imported-completed','edited-source-completed'):
    if name not in js or name not in qt:
        continue
    original=qt[name]['controls'];migrated=js[name]
    pairs=list(zip(original,migrated))
    difference=max(abs(a-b) for left,right in pairs for a,b in zip(left['bounds'],right['bounds']))
    diff=ImageChops.difference(Image.open(native/f'{name}.png').convert('RGB'),Image.open(web/f'{name}.png').convert('RGB'))
    record[name]={'native_controls':len(original),'web_controls':len(migrated),
                  'maximum_rectangle_difference_px':difference,
                  'text_equal':all(left['text']==(right['text'].strip() if right['class']!='teaching-analysis-spot' else '') for left,right in pairs),
                  'mean_absolute_rgb_difference':sum(ImageStat.Stat(diff).mean)/3}
(web/'comparison.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record))
