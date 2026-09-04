from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Iterable

from shared_contracts.jobs import JobStatus

_logger = logging.getLogger(__name__)


class JobIndex:


    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "jobs.sqlite3"
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.bootstrap_existing()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT '',
                    completed_items INTEGER NOT NULL DEFAULT 0,
                    total_items INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    result_available INTEGER NOT NULL DEFAULT 0,
                    result_size INTEGER NOT NULL DEFAULT 0,
                    error_json TEXT,
                    updated_mtime REAL NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_mtime DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status_type ON jobs(status, job_type)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_job_idempotency_job ON job_idempotency(job_id)"
            )

    def bootstrap_existing(self) -> None:
        
        
        
        
        with self._connect() as connection:
            known = {str(row[0]): float(row[1] or 0.0) for row in connection.execute(
                "SELECT job_id, updated_mtime FROM jobs"
            )}
        records: list[tuple[JobStatus, float, int]] = []
        for child in self.root.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            status_file = child / "status.json"
            if not status_file.exists():
                continue
            try:
                mtime = status_file.stat().st_mtime
            except OSError:
                continue
            if child.name in known and mtime <= known[child.name] + 1e-6:
                continue
            try:
                status = JobStatus.model_validate_json(status_file.read_text(encoding="utf-8"))
            except Exception:
                _logger.warning("skipping unreadable job status: %s", status_file, exc_info=True)
                continue
            try:
                size = sum(item.stat().st_size for item in child.rglob("*") if item.is_file())
            except OSError:
                size = 0
            records.append((status, mtime, size))
        if records:
            with self._connect() as connection:
                for status, mtime, size in records:
                    self._upsert(connection, status, result_size=size, updated_mtime=mtime)

    @staticmethod
    def _error_json(status: JobStatus) -> str | None:
        if status.error is None:
            return None
        return json.dumps(status.error.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))

    def _upsert(
        self,
        connection: sqlite3.Connection,
        status: JobStatus,
        *,
        result_size: int | None = None,
        updated_mtime: float | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, job_type, status, progress, stage, completed_items,
                total_items, created_at, started_at, finished_at,
                result_available, result_size, error_json, updated_mtime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                job_type=excluded.job_type,
                status=excluded.status,
                progress=excluded.progress,
                stage=excluded.stage,
                completed_items=excluded.completed_items,
                total_items=excluded.total_items,
                created_at=excluded.created_at,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                result_available=excluded.result_available,
                result_size=CASE WHEN excluded.result_size > 0 THEN excluded.result_size ELSE jobs.result_size END,
                error_json=excluded.error_json,
                updated_mtime=excluded.updated_mtime
            """,
            (
                status.job_id,
                status.job_type,
                status.status,
                float(status.progress),
                status.stage,
                int(status.completed_items),
                int(status.total_items),
                status.created_at,
                status.started_at,
                status.finished_at,
                int(status.result_available),
                max(0, int(result_size or 0)),
                self._error_json(status),
                float(updated_mtime or 0.0),
            ),
        )

    def upsert(self, status: JobStatus, *, result_size: int | None = None, updated_mtime: float) -> None:
        with self._connect() as connection:
            self._upsert(
                connection,
                status,
                result_size=result_size,
                updated_mtime=updated_mtime,
            )

    def update_result_size(self, job_id: str, size: int, *, updated_mtime: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET result_size=?, updated_mtime=? WHERE job_id=?",
                (max(0, int(size)), float(updated_mtime), str(job_id)),
            )

    def delete(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM job_idempotency WHERE job_id=?", (str(job_id),)
            )
            connection.execute("DELETE FROM jobs WHERE job_id=?", (str(job_id),))

    def claim_idempotency(self, idempotency_key: str, job_id: str) -> str:
        key = str(idempotency_key or "").strip()
        if not key:
            return str(job_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO job_idempotency(idempotency_key, job_id) VALUES (?, ?)",
                (key, str(job_id)),
            )
            row = connection.execute(
                "SELECT job_id FROM job_idempotency WHERE idempotency_key=?",
                (key,),
            ).fetchone()
        return str(row[0]) if row is not None else str(job_id)

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return int(row[0] if row else 0)

    def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status_filter: str | None = None,
        job_type: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        values: list[object] = []
        if status_filter:
            clauses.append("status=?")
            values.append(status_filter)
        if job_type:
            clauses.append("job_type=?")
            values.append(job_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT job_id, job_type, status, progress, stage, completed_items, total_items, "
            "created_at, started_at, finished_at, result_available, error_json "
            f"FROM jobs{where} ORDER BY updated_mtime DESC LIMIT ? OFFSET ?"
        )
        values.extend([max(1, int(limit)), max(0, int(offset))])
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        items: list[dict] = []
        for row in rows:
            item = dict(row)
            item["result_available"] = bool(item["result_available"])
            error_json = item.pop("error_json", None)
            item["error"] = json.loads(error_json) if error_json else None
            items.append(item)
        return items

    def maintenance_candidates(self, *, terminal_only: bool = True) -> Iterable[dict]:
        where = "WHERE status IN ('completed','failed','cancelled')" if terminal_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT job_id, status, finished_at, updated_mtime FROM jobs {where} ORDER BY updated_mtime ASC"
            ).fetchall()
        return [dict(row) for row in rows]
