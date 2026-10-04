"""Compare manually captured original and browser dataset controls."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

root = Path(__file__).resolve().parents[1] / 'tests/golden'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--native', type=Path, default=root / 'ui-baseline/dataset')
parser.add_argument('--web', type=Path, default=root / 'ui-current/dataset')
args = parser.parse_args()
native, web = args.native, args.web
expected = json.loads((native / 'geometry.json').read_text(encoding='utf-8'))
actual = json.loads((web / 'geometry.json').read_text(encoding='utf-8'))
if not actual:
    raise ValueError('Browser geometry is empty; no comparison was performed')
unknown_states = set(actual) - set(expected)
if unknown_states:
    raise ValueError(f'Missing original states: {sorted(unknown_states)}')

def key(control):
    kind = control['kind']
    if kind in ('QPushButton', 'QToolButton'):
        kind = 'button'
    if kind in ('QDoubleSpinBox', 'UnitAwareDoubleSpinBox'):
        kind = 'number'
    return kind, control['text'].replace('›', '').replace('⌄', '').strip()

records = {}
for name, current in actual.items():
    original = expected[name]
    remaining = list(current['controls'])
    differences, missing, maximum, font_differences = [], [], 0, []
    for left in original['controls']:
        candidates = [right for right in remaining if key(left) == key(right)]
        if not candidates:
            missing.append(left)
            continue
        right = min(candidates, key=lambda c: sum(abs(a-b) for a,b in zip(left['bounds'][:2], c['bounds'][:2])))
        remaining.remove(right)
        error = max(abs(a-b) for a,b in zip(left['bounds'], right['bounds']))
        maximum = max(maximum, error)
        if error > .34:
            differences.append({'text':left['text'], 'native':left['bounds'], 'web':right['bounds'], 'error':error})
        if left.get('font') and right.get('font'):
            expected_font, actual_font = left['font'], right['font']
            family = actual_font['family'].split(',')[0].strip(' "\'')
            if (expected_font['family'] != family
                    or abs(expected_font['pixel_size'] - actual_font['pixel_size']) > .01
                    or expected_font['weight'] != actual_font['weight']):
                font_differences.append({'text':left['text'], 'native':expected_font, 'web':actual_font})
    original_image = Image.open(native / (name+'.png')).convert('RGB')
    current_image = Image.open(web / (name+'.png')).convert('RGB')
    original_size = original_image.size
    if original_image.size != current_image.size:
        original_image = original_image.resize(current_image.size, Image.Resampling.LANCZOS)
    diff = ImageChops.difference(original_image, current_image)
    form_frames = [frame['bounds'] for frame in original.get('frames', []) if frame['name'] == 'FieldGroup']
    form_box = None
    if form_frames:
        form_box = [min(f[0] for f in form_frames), min(f[1] for f in form_frames),
                    min(current_image.width, max(f[0]+f[2] for f in form_frames)),
                    min(current_image.height, max(f[1]+f[3] for f in form_frames))]
    remaining_frames = list(current.get('frames', []))
    frame_differences = []
    for frame in original.get('frames', []):
        candidates = [f for f in remaining_frames if f['name'] == frame['name'] and f.get('bounds')]
        if not candidates:
            frame_differences.append({'name':frame['name'], 'missing':True})
            continue
        counterpart = min(candidates, key=lambda f:sum(abs(a-b) for a,b in zip(f['bounds'],frame['bounds'])))
        remaining_frames.remove(counterpart)
        frame_differences.append({'name':frame['name'], 'native':frame['bounds'], 'web':counterpart['bounds'], 'error':max(abs(a-b) for a,b in zip(frame['bounds'],counterpart['bounds']))})
    records[name] = {'native_controls':len(original['controls']), 'web_controls':len(current['controls']), 'maximum_rectangle_difference_px':maximum, 'missing':missing, 'extra':remaining, 'differences':differences, 'font_differences':font_differences, 'mean_absolute_rgb_difference':sum(ImageStat.Stat(diff).mean)/3,
                     'frame_differences':frame_differences,
                     'form_box':form_box, 'form_mean_absolute_rgb_difference':sum(ImageStat.Stat(diff.crop(form_box)).mean)/3 if form_box else None,
                     'image_comparison':{'native_png_size':original_size, 'web_png_size':current_image.size, 'native_dpr':original.get('device_pixel_ratio'), 'web_dpr':current.get('device_pixel_ratio'),
                                         'resampling':'native LANCZOS to web PNG size' if original_size != current_image.size else 'none',
                                         'limitation':'Resampled raster diagnostic only; not pixel identity. Full image includes different dataset lists.'}}
(web / 'comparison.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
for name, state in records.items():
    print(name, state['native_controls'], state['web_controls'], 'max', round(state['maximum_rectangle_difference_px'],3), 'missing',len(state['missing']), 'extra',len(state['extra']), 'font_differences',len(state['font_differences']))
    for item in state['differences']:
        print(json.dumps(item, ensure_ascii=False))
    if state['missing'] or state['extra']:
        print(json.dumps({'missing':state['missing'],'extra':state['extra']},ensure_ascii=False))
