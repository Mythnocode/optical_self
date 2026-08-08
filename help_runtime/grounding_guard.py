from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schemas import AssistantAnswer, HelpContext


class GroundingGuard:


    def __init__(self, resources_dir: str | Path) -> None:
        self.db_path = Path(resources_dir) / "help.db"

    def available_knowledge_ids(self) -> set[str]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute("SELECT id FROM knowledge_entries").fetchall()
        return {str(row[0]) for row in rows}

    def _conflict_map(self, ids: set[str]) -> dict[str, set[str]]:
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                f"SELECT conflict_key, claim_value FROM knowledge_entries WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        conflicts: dict[str, set[str]] = {}
        for key, value in rows:
            if key and value is not None:
                conflicts.setdefault(str(key), set()).add(str(value))
        return {key: values for key, values in conflicts.items() if len(values) > 1}

    def validate(self, answer: AssistantAnswer, context: HelpContext) -> AssistantAnswer:
        if answer.status == "unsupported":
            answer.findings = []
            answer.source_ids = []
            answer.action_ids = []
            answer.used_current_result = False
            return answer

        knowledge_ids = self.available_knowledge_ids()
        dynamic_ids = set(context.dynamic_sources)
        available = knowledge_ids | dynamic_ids

        valid_findings = []
        dropped = 0
        for finding in answer.findings:
            source_set = set(finding.source_ids)
            if not source_set or not source_set.issubset(available):
                dropped += 1
                continue
            if finding.kind in {"diagnostic", "warning"} and context.has_current_result:
                if "context.current_report" not in source_set:
                    dropped += 1
                    continue
                if not (source_set & knowledge_ids):
                    dropped += 1
                    continue
            valid_findings.append(finding)

        answer.findings = valid_findings
        answer.source_ids = list(
            dict.fromkeys(source for item in valid_findings for source in item.source_ids)
        )
        answer.action_ids = list(
            dict.fromkeys(action for item in valid_findings for action in item.action_ids)
        )[:3]

        conflicts = self._conflict_map(set(answer.source_ids) & knowledge_ids)
        if conflicts:
            answer.status = "partial"
            answer.confidence = "low"
            answer.warnings.append(
                "来源之间存在未解决的口径冲突："
                + "；".join(f"{key}={sorted(values)}" for key, values in conflicts.items())
            )

        if dropped:
            answer.warnings.append(f"来源校验删除了 {dropped} 条缺少有效依据的结论。")

        if not answer.findings:
            answer.status = "insufficient"
            answer.summary = "当前知识库没有足够证据回答这个问题。"
            answer.confidence = "low"
            answer.source_ids = []
            answer.action_ids = []
            answer.used_current_result = False
        return answer

    def source_catalog(self, context: HelpContext) -> dict[str, dict]:
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, title, module, entry_type, sources_json, route, anchor FROM knowledge_entries"
            ).fetchall()
        catalog = {
            str(row["id"]): {
                "title": row["title"],
                "module": row["module"],
                "entry_type": row["entry_type"],
                "sources": json.loads(row["sources_json"]),
                "route": row["route"],
                "anchor": row["anchor"],
            }
            for row in rows
        }
        catalog.update(context.dynamic_sources)
        return catalog
