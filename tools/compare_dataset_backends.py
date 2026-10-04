"""Compare retained benchmark samples, labels, acceptance and data splits."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "tests/golden/dataset-backends"


def main():
    left, right = [json.loads((ROOT / name / "report.json").read_text(encoding="utf-8")) for name in sys.argv[1:3]]
    differences = []
    max_absolute = 0.0
    max_relative = 0.0
    for key in ("sample_count", "valid_sample_count", "failed_sample_count", "train_ids", "validation_ids", "test_ids", "status"):
        if left["manifest"][key] != right["manifest"][key]:
            differences.append(f"manifest.{key}")
    if len(left["samples"]) != len(right["samples"]):
        differences.append("sample count")
    for a, b in zip(left["samples"], right["samples"]):
        for key in ("sample_id", "valid", "failure_code", "feature_values", "converged"):
            if a[key] != b[key]:
                differences.append(f"{a['sample_id']}.{key}")
        if set(a["target_values"]) != set(b["target_values"]):
            differences.append(f"{a['sample_id']}.target names")
        for key, value in a["target_values"].items():
            other = b["target_values"].get(key)
            if other is None:
                continue
            absolute = abs(value - other)
            relative = absolute / max(abs(value), abs(other), 1e-12)
            max_absolute = max(max_absolute, absolute)
            max_relative = max(max_relative, relative)
            if absolute > 1e-9 + 1e-7 * max(abs(value), abs(other)):
                differences.append(f"{a['sample_id']}.target_values.{key}: {value} vs {other}")
    report = {
        "left": sys.argv[1], "right": sys.argv[2], "differences": differences,
        "max_target_absolute_difference": max_absolute, "max_target_relative_difference": max_relative,
        "elapsed_speedup": left["elapsed_seconds"] / right["elapsed_seconds"],
        "trace_speedup": sum(left["trace_seconds"].values()) / sum(right["trace_seconds"].values()),
    }
    (ROOT / f"comparison-{sys.argv[1]}-{sys.argv[2]}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
