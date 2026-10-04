"""Compare manually captured original/browser inspector states."""
import json
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
root=Path(__file__).resolve().parents[1]/'tests/golden'
native=root/'ui-baseline/teaching/inspector-states'
web=root/'ui-current/teaching/inspector-states'
expected=json.loads((native/'geometry.json').read_text(encoding='utf-8'))
actual=json.loads((web/'geometry.json').read_text(encoding='utf-8'))
records={}
for name,state in actual.items():
    original=expected[name]
    pairs=list(zip(original['controls'],state['controls']))
    differences=[{'index':index,'native_text':left['text'],'web_text':right['text'],'native_bounds':left['bounds'],'web_bounds':right['bounds']} for index,(left,right) in enumerate(pairs) if left['text'].replace('\n','')!=right['text'].replace('\n','') or any(abs(a-b)>.01 for a,b in zip(left['bounds'],right['bounds']))]
    raster=None
    if original['size']==state['size']:
        diff=ImageChops.difference(Image.open(native/(name+'.png')).convert('RGB'),Image.open(web/(name+'.png')).convert('RGB'))
        raster=sum(ImageStat.Stat(diff).mean)/3
    records[name]={'native_size':original['size'],'web_size':state['size'],'native_controls':len(original['controls']),'web_controls':len(state['controls']), 'maximum_rectangle_difference_px':max((abs(a-b) for left,right in pairs for a,b in zip(left['bounds'],right['bounds'])),default=0),'differences':differences,'mean_absolute_rgb_difference':raster,'native_scrollbar':original.get('scrollbar'),'web_scrollbar':state.get('scrollbar')}
(web/'comparison.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'states':len(records),'controls':sum(item['web_controls'] for item in records.values()),'maximum_rectangle_difference_px':max(item['maximum_rectangle_difference_px'] for item in records.values()),'window_size_mismatches':[name for name,item in records.items() if item['native_size']!=item['web_size']],'control_count_mismatches':[name for name,item in records.items() if item['native_controls']!=item['web_controls']],'text_mismatches':[name for name,item in records.items() if any(d['native_text'].replace('\n','')!=d['web_text'].replace('\n','') for d in item['differences'])]}))
for name,item in records.items():
    if item['maximum_rectangle_difference_px']>.34 or item['native_controls']!=item['web_controls'] or any(d['native_text'].replace('\n','')!=d['web_text'].replace('\n','') for d in item['differences']):print(name,json.dumps(item['differences'][:12],ensure_ascii=False))
