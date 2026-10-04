"""Arrange existing native/browser captures for manual visual inspection.

The native raw capture is retained. Its 150% raster is normalized with LANCZOS
only for this contact sheet, since the browser tool emits logical-size PNGs.
These derived images are not evidence of pixel identity.
"""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / 'tests/golden'
groups = [
    ['import-collapsed', 'import-expanded', 'sequence-import'],
    ['sequence-training-expanded', 'sequence-generation-collapsed', 'sequence-generation-expanded'],
    ['sequence-variables-expanded', 'fixed-generation-expanded', 'fixed-generation-collapsed'],
]
for width, height in [(1280, 800), (1440, 900)]:
    native = root / f'ui-baseline/dataset-controls/scale-1.5-{width}x{height}'
    web = root / f'ui-current/dataset-controls/{width}x{height}'
    target = web / 'visual-pairs'
    target.mkdir(exist_ok=True)
    box = (293, 152, width - 1, height)
    crop_width, crop_height = box[2]-box[0], box[3]-box[1]
    for index, names in enumerate(groups, 1):
        sheet = Image.new('RGB', (crop_width * 2, (crop_height+30)*len(names)), '#FFFFFF')
        draw = ImageDraw.Draw(sheet)
        for row, name in enumerate(names):
            y = row*(crop_height+30)
            draw.text((8, y+8), f'Original Qt (150%, normalized): {name}', fill='#101828')
            draw.text((crop_width+8, y+8), f'Browser (DPR 1.5, logical PNG): {name}', fill='#101828')
            left = Image.open(native/(name+'.png')).convert('RGB').resize((width,height), Image.Resampling.LANCZOS)
            right = Image.open(web/(name+'.png')).convert('RGB')
            sheet.paste(left.crop(box), (0,y+30))
            sheet.paste(right.crop(box), (crop_width,y+30))
        sheet.save(target/f'group-{index}.png')
        print(target/f'group-{index}.png')
