"""Export original UI parameter descriptors for the web frontend."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared_presentation.surface_registry import SURFACE_TYPES, extra_header_label
from shared_presentation.surface_payloads import _surface_type

baseline = ROOT / "tests/golden/ui-baseline/surfaces/geometry.json"
widths = {}
if baseline.exists():
    for capture in json.loads(baseline.read_text(encoding="utf-8")).values():
        for column in capture.get("columns", []):
            if column.get("preferred_width", column["width"]) > 0:
                widths[column["text"]] = column.get("preferred_width", column["width"])
rows = []
for spec in SURFACE_TYPES:
    row = {"key": _surface_type(spec.name), **asdict(spec)}
    for parameter, original in zip(row["parameters"], spec.parameters):
        parameter["column_width"] = widths.get(extra_header_label(original), 120)
    rows.append(row)
target = ROOT / "frontend_web/src/domain/surface-registry.json"
target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
