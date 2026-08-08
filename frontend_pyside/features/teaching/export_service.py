
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping


def collect_learning_records(
    modules: Mapping[str, Mapping[str, Any]],
    sessions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for module_key, spec in modules.items():
        session = dict(sessions.get(module_key, {}) or {})
        module_records = list(session.get("records", []) or [])
        score = session.get("score", {}) or {}
        diagnostic = session.get("diagnostic", {}) or {}
        summary.append(
            {
                "module": module_key,
                "title": str(spec.get("title", module_key)),
                "record_count": len(module_records),
                "prediction_correct": bool(session.get("prediction_correct", False)),
                "diagnostic_passed": bool(diagnostic.get("sampling_pass", False)),
                "score": score.get("total", ""),
                "conclusion": str(session.get("conclusion", "")),
            }
        )
        for record in module_records:
            records.append(
                {
                    "module": module_key,
                    "title": str(spec.get("title", module_key)),
                    "time": str(record.get("time", "")),
                    "inputs": dict(record.get("inputs", {}) or {}),
                    "metrics": dict(record.get("metrics", {}) or {}),
                    "note": str(record.get("note", "")),
                }
            )
    return {"summary": summary, "records": records}


def write_learning_records(
    path: str | Path,
    modules: Mapping[str, Mapping[str, Any]],
    sessions: Mapping[str, Mapping[str, Any]],
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = collect_learning_records(modules, sessions)
    if target.suffix.lower() == ".csv":
        fields = [
            "module",
            "title",
            "time",
            "inputs",
            "metrics",
            "note",
        ]
        with target.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for record in payload["records"]:
                row = dict(record)
                row["inputs"] = json.dumps(row["inputs"], ensure_ascii=False)
                row["metrics"] = json.dumps(row["metrics"], ensure_ascii=False)
                writer.writerow(row)
    else:
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return target


__all__ = ["collect_learning_records", "write_learning_records"]
