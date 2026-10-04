"""Summarize saved manual browser/Qt observations; this does not launch a test suite."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'tests/golden'
current = root / 'ui-current/navigation'
web = json.loads((current / 'geometry.json').read_text(encoding='utf-8'))

def identity(row):
    name = row['name']
    if name in ('PrimaryBar', 'SecondaryBar'):
        return name
    return name + ':' + (row['tooltip'] if name == 'PrimaryActionButton' and 'tooltip' in row else row['text'])

report = {}
for width, height, suffix in [(1280, 800, 'after'), (1440, 900, '1440')]:
    directory = root / 'ui-baseline/navigation' / f'scale-1-{width}x{height}'
    native = json.loads((directory / 'geometry.json').read_text(encoding='utf-8'))
    for module in ['model', 'simulation', 'optimization', 'explainability']:
        if module == 'explainability' and height == 800:
            # Qt's shared stacked layout remembers previously opened optimization documents.
            # This comparison uses the direct-open explanation baseline, as previous captures do.
            explanation = json.loads((root / 'ui-baseline/navigation' / 'scale-1-1280x800-explainability/geometry.json').read_text(encoding='utf-8'))
            rows = explanation['explainability-populated']
        else:
            rows = native[module]
        expected = {identity(row): row for row in rows}
        actual = {identity(row): row for row in web[f'{module}-{suffix}']}
        compared = []
        for key in expected.keys() & actual.keys():
            original, migrated = expected[key], actual[key]
            compared.append(dict(control=key, native=original['bounds'], web=migrated['bounds'],
                                 max_difference_px=max(abs(a-b) for a, b in zip(original['bounds'], migrated['bounds'])),
                                 selected_equal=original['checked'] == migrated['checked'],
                                 icon_size_equal=original['icon_size'] == migrated['icon_size'] if original['name'] in ('PrimaryActionButton', 'SecondaryFunctionButton') else None))
        report[f'{width}x{height}/{module}'] = dict(
            controls=sorted(compared, key=lambda row: row['control']),
            count=len(compared), max_difference_px=max(row['max_difference_px'] for row in compared),
            missing=sorted(expected.keys()-actual.keys()), extra=sorted(actual.keys()-expected.keys()))
(current / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({name: {key: value for key, value in state.items() if key != 'controls'} for name, state in report.items()}, ensure_ascii=True))
