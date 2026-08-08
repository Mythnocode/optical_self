from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
from sklearn.preprocessing import normalize

from .schemas import HelpContext, SearchHit

_TOKEN_RE = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)


def _minmax(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if math.isclose(lo, hi):
        return {key: 1.0 for key in values}
    return {key: (value - lo) / (hi - lo) for key, value in values.items()}


def _safe_fts_query(text: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(text) if token]
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:24])


class HybridRetriever:


    def __init__(
        self,
        resources_dir: str | Path,
        *,
        keyword_weight: float = 0.45,
        semantic_weight: float = 0.45,
        context_weight: float = 0.10,
    ) -> None:
        total = keyword_weight + semantic_weight + context_weight
        if total <= 0:
            raise ValueError("Retriever weights must sum to a positive value")
        self.keyword_weight = keyword_weight / total
        self.semantic_weight = semantic_weight / total
        self.context_weight = context_weight / total

        self.root = Path(resources_dir)
        self.db_path = self.root / "help.db"
        self.embeddings = np.load(self.root / "embeddings.npy")
        self.semantic_bundle = joblib.load(self.root / "semantic_model.joblib")
        self.chunk_metadata = json.loads(
            (self.root / "chunk_metadata.json").read_text(encoding="utf-8")
        )
        self.id_to_index = {item["id"]: int(item["index"]) for item in self.chunk_metadata}
        self.synonyms: dict[str, list[str]] = dict(self.semantic_bundle.get("synonyms", {}))

    def _expand_query(self, question: str) -> str:
        additions: list[str] = []
        lowered = question.lower()
        for canonical, variants in self.synonyms.items():
            group = [canonical, *variants]
            if any(term.lower() in lowered for term in group):
                additions.extend(group)
        if not additions:
            return question
        unique = list(dict.fromkeys(additions))
        return f"{question} {' '.join(unique)}"

    def _keyword_scores(self, query: str, limit: int) -> dict[str, float]:
        fts_query = _safe_fts_query(query)
        if not fts_query:
            return {}
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT id, bm25(knowledge_fts, 0.0, 3.0, 2.0, 1.0, 2.5, 2.0, 0.5) AS rank
                FROM knowledge_fts
                WHERE knowledge_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, max(limit, 10)),
            ).fetchall()
        
        return {str(entry_id): -float(rank) for entry_id, rank in rows}

    def _semantic_scores(self, query: str) -> dict[str, float]:
        vectorizer = self.semantic_bundle["vectorizer"]
        svd = self.semantic_bundle.get("svd")
        sparse = vectorizer.transform([query])
        if svd is not None:
            query_vector = normalize(svd.transform(sparse), norm="l2")
        else:
            query_vector = normalize(sparse, norm="l2").toarray()
        scores = np.asarray(self.embeddings @ query_vector[0], dtype=float)
        return {
            item["id"]: float(scores[int(item["index"])])
            for item in self.chunk_metadata
        }

    def _context_score(self, row: dict, context: HelpContext | None) -> float:
        if context is None:
            return 0.0
        score = 0.0
        module = str(row.get("module", "")).lower()
        route = str(row.get("route") or "").lower()
        page = str(context.page_id or "").lower()
        control = str(context.selected_control_id or "").lower()
        analysis = str(context.analysis_type or "").lower()
        if page and (page in module or page in route or module in page):
            score += 0.55
        if analysis and (analysis in row.get("content", "").lower() or analysis in row.get("title", "").lower()):
            score += 0.30
        if control and control in row.get("content", "").lower():
            score += 0.15
        return min(score, 1.0)

    def _load_rows(self, ids: Iterable[str]) -> dict[str, dict]:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM knowledge_entries WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        return {str(row["id"]): dict(row) for row in rows}

    def search(
        self,
        question: str,
        *,
        context: HelpContext | None = None,
        limit: int = 8,
        min_score: float = 0.08,
    ) -> list[SearchHit]:
        expanded = self._expand_query(question.strip())
        keyword_raw = self._keyword_scores(expanded, limit * 3)
        semantic_raw = self._semantic_scores(expanded)
        keyword = _minmax(keyword_raw)
        
        semantic = _minmax({key: max(value, 0.0) for key, value in semantic_raw.items()})
        candidate_ids = set(keyword) | set(
            sorted(semantic, key=semantic.get, reverse=True)[: max(limit * 3, 12)]
        )
        rows = self._load_rows(candidate_ids)

        hits: list[SearchHit] = []
        for entry_id, row in rows.items():
            context_score = self._context_score(row, context)
            final = (
                self.keyword_weight * keyword.get(entry_id, 0.0)
                + self.semantic_weight * semantic.get(entry_id, 0.0)
                + self.context_weight * context_score
            )
            if final < min_score:
                continue
            sources = json.loads(row["sources_json"])
            hits.append(
                SearchHit(
                    id=entry_id,
                    title=row["title"],
                    module=row["module"],
                    entry_type=row["entry_type"],
                    summary=row["summary"],
                    content=row["content"],
                    route=row["route"],
                    anchor=row["anchor"],
                    action_ids=json.loads(row["actions"]),
                    source_ids=[str(item["source_id"]) for item in sources],
                    keyword_score=keyword.get(entry_id, 0.0),
                    semantic_score=semantic.get(entry_id, 0.0),
                    context_score=context_score,
                    final_score=final,
                )
            )
        hits.sort(key=lambda item: item.final_score, reverse=True)
        return hits[:limit]

    def get_entry(self, entry_id: str) -> SearchHit | None:
        rows = self._load_rows([entry_id])
        row = rows.get(entry_id)
        if row is None:
            return None
        sources = json.loads(row["sources_json"])
        return SearchHit(
            id=entry_id,
            title=row["title"],
            module=row["module"],
            entry_type=row["entry_type"],
            summary=row["summary"],
            content=row["content"],
            route=row["route"],
            anchor=row["anchor"],
            action_ids=json.loads(row["actions"]),
            source_ids=[str(item["source_id"]) for item in sources],
            final_score=1.0,
        )
