#!/usr/bin/env python3
"""Merge supplemental YAML chunks into resources/help and rebuild search indexes."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import yaml
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parents[1]
HELP_DIR = ROOT / "resources" / "help"
DB_PATH = HELP_DIR / "help.db"
CHUNKS_PATH = HELP_DIR / "knowledge_chunks.yaml"
METADATA_PATH = HELP_DIR / "chunk_metadata.json"
EMBEDDINGS_PATH = HELP_DIR / "embeddings.npy"
SEMANTIC_PATH = HELP_DIR / "semantic_model.joblib"

ENTRY_COLUMNS = (
    "id",
    "title",
    "module",
    "entry_type",
    "summary",
    "content",
    "keywords",
    "aliases",
    "related",
    "actions",
    "route",
    "anchor",
    "version",
    "sources_json",
    "limitations_json",
    "conflict_key",
    "claim_value",
)


def _load_rows(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM knowledge_entries").fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def _normalize_chunk(raw: dict[str, Any]) -> dict[str, Any]:
    chunk_id = str(raw["id"])
    return {
        "id": chunk_id,
        "title": str(raw["title"]),
        "module": str(raw.get("module", "使用指南")),
        "entry_type": str(raw.get("entry_type", "guide")),
        "summary": str(raw.get("summary", "")),
        "content": str(raw.get("content", "")).strip(),
        "keywords": json.dumps(list(raw.get("keywords") or []), ensure_ascii=False),
        "aliases": json.dumps(list(raw.get("aliases") or []), ensure_ascii=False),
        "related": json.dumps(list(raw.get("related") or []), ensure_ascii=False),
        "actions": json.dumps(list(raw.get("actions") or []), ensure_ascii=False),
        "route": raw.get("route"),
        "anchor": raw.get("anchor"),
        "version": str(raw.get("version", "1.0")),
        "sources_json": json.dumps(
            list(raw.get("sources") or raw.get("sources_json") or []),
            ensure_ascii=False,
        ),
        "limitations_json": json.dumps(
            list(raw.get("limitations") or raw.get("limitations_json") or []),
            ensure_ascii=False,
        ),
        "conflict_key": raw.get("conflict_key"),
        "claim_value": raw.get("claim_value"),
    }


def _merge_chunks(existing: dict[str, dict[str, Any]], supplement: dict[str, Any]) -> dict[str, dict[str, Any]]:
    merged = dict(existing)
    for raw in supplement.get("chunks") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        normalized = _normalize_chunk(raw)
        prior = merged.get(normalized["id"], {})
        if not prior:
            merged[normalized["id"]] = normalized
            continue
        updated = dict(prior)
        for key, value in normalized.items():
            if value in (None, "", "[]", "null"):
                continue
            updated[key] = value
        merged[normalized["id"]] = updated
    return merged


def _document_text(row: dict[str, Any]) -> str:
    keywords = json.loads(row.get("keywords") or "[]")
    aliases = json.loads(row.get("aliases") or "[]")
    return "\n".join(
        [
            str(row.get("title", "")),
            str(row.get("summary", "")),
            str(row.get("content", "")),
            " ".join(keywords),
            " ".join(aliases),
            str(row.get("module", "")),
        ]
    ).strip()


def _rebuild_db(rows: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(rows.values(), key=lambda item: str(item["id"]))
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("DELETE FROM knowledge_entries")
        connection.executemany(
            f"""
            INSERT INTO knowledge_entries ({", ".join(ENTRY_COLUMNS)})
            VALUES ({", ".join("?" for _ in ENTRY_COLUMNS)})
            """,
            [tuple(row[col] for col in ENTRY_COLUMNS) for row in ordered],
        )
        connection.execute("DELETE FROM knowledge_fts")
        connection.executemany(
            """
            INSERT INTO knowledge_fts (id, title, summary, content, keywords, aliases, module)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["title"],
                    row["summary"],
                    row["content"],
                    row["keywords"],
                    row["aliases"],
                    row["module"],
                )
                for row in ordered
            ],
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES ('entry_count', ?)",
            (str(len(ordered)),),
        )
        connection.commit()


def _rebuild_metadata(rows: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(rows.values(), key=lambda item: str(item["id"]))
    payload = [
        {
            "index": index,
            "id": row["id"],
            "title": row["title"],
            "module": row["module"],
            "entry_type": row["entry_type"],
        }
        for index, row in enumerate(ordered)
    ]
    METADATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rebuild_semantic(rows: dict[str, dict[str, Any]], extra_synonyms: dict[str, list[str]]) -> None:
    ordered = sorted(rows.values(), key=lambda item: str(item["id"]))
    documents = [_document_text(row) for row in ordered]
    n_docs = len(documents)
    n_components = min(30, max(2, n_docs - 1))

    vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=(2, 4),
        max_features=8192,
        sublinear_tf=True,
        norm="l2",
    )
    sparse = vectorizer.fit_transform(documents)
    svd = TruncatedSVD(n_components=n_components, random_state=42)
    dense = normalize(svd.fit_transform(sparse), norm="l2")
    embeddings = np.asarray(dense, dtype=np.float32)
    np.save(EMBEDDINGS_PATH, embeddings)

    synonyms: dict[str, list[str]] = {}
    if SEMANTIC_PATH.exists():
        try:
            prior = joblib.load(SEMANTIC_PATH)
            synonyms.update(dict(prior.get("synonyms") or {}))
        except Exception:
            pass
    for key, values in dict(extra_synonyms or {}).items():
        merged = list(dict.fromkeys([*(synonyms.get(key, [])), *list(values or [])]))
        synonyms[str(key)] = merged

    joblib.dump(
        {
            "vectorizer": vectorizer,
            "svd": svd,
            "kind": "tfidf-char-svd",
            "synonyms": synonyms,
        },
        SEMANTIC_PATH,
    )


def rebuild(*, supplement_path: Path | None = None) -> int:
    supplement_path = supplement_path or CHUNKS_PATH
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Missing knowledge database: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as connection:
        existing = _load_rows(connection)

    supplement: dict[str, Any] = {}
    if supplement_path.exists():
        supplement = yaml.safe_load(supplement_path.read_text(encoding="utf-8")) or {}

    merged = _merge_chunks(existing, supplement)
    _rebuild_db(merged)
    _rebuild_metadata(merged)
    _rebuild_semantic(merged, dict(supplement.get("synonyms") or {}))
    return len(merged)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--supplement",
        type=Path,
        default=CHUNKS_PATH,
        help="YAML file with supplemental chunks (default: resources/help/knowledge_chunks.yaml)",
    )
    args = parser.parse_args()
    count = rebuild(supplement_path=args.supplement)
    print(f"Rebuilt help knowledge index with {count} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
