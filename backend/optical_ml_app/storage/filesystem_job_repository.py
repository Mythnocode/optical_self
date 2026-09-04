from __future__ import annotations

from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timezone
import logging
import os
import shutil
import sys
import threading
import time

from shared_contracts.jobs import JobStatus
from shared_contracts.errors import ApplicationError
from backend.optical_ml_app.infrastructure.json_utils import to_storage_value
from backend.optical_ml_app.storage.atomic_files import atomic_write_bytes, atomic_write_text
from backend.optical_ml_app.storage.job_index import JobIndex
from backend.optical_ml_app.storage.job_retention import JobRetentionManager
from backend.optical_ml_app.storage.local_result_transport import create_local_result_view
from backend.optical_ml_app.storage.result_bundle import (
    bundle_size,
    load_result_bundle,
    save_result_bundle,
)


_logger = logging.getLogger(__name__)


def _estimate_cache_bytes(value, *, limit: int, seen: set[int] | None = None) -> int:

    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return int(value.nbytes) + int(sys.getsizeof(value))
    except Exception:
        pass
    total = int(sys.getsizeof(value))
    if total > limit:
        return total
    if isinstance(value, dict):
        iterator = value.items()
        for key, item in iterator:
            total += _estimate_cache_bytes(key, limit=max(0, limit - total), seen=seen)
            if total > limit:
                return total
            total += _estimate_cache_bytes(item, limit=max(0, limit - total), seen=seen)
            if total > limit:
                return total
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            total += _estimate_cache_bytes(item, limit=max(0, limit - total), seen=seen)
            if total > limit:
                return total
    return total


class FileJobRepository:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = JobIndex(self.root)
        self.retention = JobRetentionManager(self.root, self.index)
        self._result_cache: OrderedDict[tuple[str, str], tuple[float, object, int]] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_ttl_seconds = max(1.0, float(os.getenv("OPTICAL_RESULT_CACHE_TTL_SECONDS", "90")))
        self._cache_max_entries = max(1, int(os.getenv("OPTICAL_RESULT_CACHE_MAX_ENTRIES", "16")))
        self._cache_max_bytes = max(8 * 1024 * 1024, int(os.getenv("OPTICAL_RESULT_CACHE_MAX_BYTES", str(128 * 1024 * 1024))))
        self._cache_entry_max_bytes = max(1 * 1024 * 1024, int(os.getenv("OPTICAL_RESULT_CACHE_ENTRY_MAX_BYTES", str(48 * 1024 * 1024))))
        self._result_cache_bytes = 0
        self._live_view_ttl_seconds = max(60.0, float(os.getenv("OPTICAL_LIVE_VIEW_TTL_SECONDS", "600")))

    def _dir(self, job_id, *, create: bool = True):
        path = self.root / str(job_id)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def save_status(self, status: JobStatus):
        path = self._dir(status.job_id) / "status.json"
        atomic_write_text(path, status.model_dump_json(), encoding="utf-8")
        try:
            self.index.upsert(status, updated_mtime=path.stat().st_mtime)
        except Exception:
            
            
            _logger.exception("failed to update job index for %s", status.job_id)
        if status.status in {"completed", "failed", "cancelled"}:
            self._run_retention()

    def load_status(self, job_id):
        path = self._dir(job_id, create=False) / "status.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return JobStatus.model_validate_json(path.read_text(encoding="utf-8"))

    def save_retry_payload(self, job_id: str, payload: bytes) -> None:
        atomic_write_bytes(self._dir(job_id) / "retry_payload.bin", bytes(payload))

    def load_retry_payload(self, job_id: str) -> bytes:
        path = self._dir(job_id, create=False) / "retry_payload.bin"
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_bytes()

    def has_retry_payload(self, job_id: str) -> bool:
        try:
            return (self._dir(job_id, create=False) / "retry_payload.bin").exists()
        except FileNotFoundError:
            return False

    def claim_idempotency(self, idempotency_key: str, job_id: str) -> str:
        return self.index.claim_idempotency(idempotency_key, job_id)

    def create_local_result_view(self, job_id, result):
        self._prune_local_result_views()
        return create_local_result_view(self._dir(job_id), result)

    def _prune_local_result_views(self, *, force: bool = False) -> int:
        cutoff = time.time() - self._live_view_ttl_seconds
        removed = 0
        for directory in self.root.glob("*/live_arrays"):
            try:
                modified = directory.stat().st_mtime
            except OSError:
                continue
            if not force and modified >= cutoff:
                continue
            try:
                shutil.rmtree(directory)
                removed += 1
            except OSError:
                continue
        return removed

    def _drop_cache_key_locked(self, key: tuple[str, str]) -> None:
        item = self._result_cache.pop(key, None)
        if item is not None:
            self._result_cache_bytes = max(0, self._result_cache_bytes - int(item[2]))

    def _invalidate_job_cache(self, job_id: str) -> None:
        wanted = str(job_id)
        with self._cache_lock:
            for key in [key for key in self._result_cache if key[0] == wanted]:
                self._drop_cache_key_locked(key)

    def _cached(self, job_id: str, analysis: str = ""):
        key = (str(job_id), str(analysis))
        now = time.monotonic()
        with self._cache_lock:
            item = self._result_cache.get(key)
            if item is None:
                return None
            created, value, _size = item
            if now - created > self._cache_ttl_seconds:
                self._drop_cache_key_locked(key)
                return None
            self._result_cache.move_to_end(key)
            return value

    def _remember(self, job_id: str, value, analysis: str = ""):
        key = (str(job_id), str(analysis))
        size = _estimate_cache_bytes(value, limit=self._cache_entry_max_bytes + 1)
        with self._cache_lock:
            self._drop_cache_key_locked(key)
            if size > self._cache_entry_max_bytes or size > self._cache_max_bytes:
                return value
            self._result_cache[key] = (time.monotonic(), value, int(size))
            self._result_cache_bytes += int(size)
            self._result_cache.move_to_end(key)
            while (
                len(self._result_cache) > self._cache_max_entries
                or self._result_cache_bytes > self._cache_max_bytes
            ):
                oldest = next(iter(self._result_cache))
                self._drop_cache_key_locked(oldest)
        return value

    def save_result(self, job_id, result):
        job_dir = self._dir(job_id)
        payload = to_storage_value(result)
        
        
        self._invalidate_job_cache(str(job_id))
        save_result_bundle(job_dir, payload)
        try:
            self.index.update_result_size(job_id, bundle_size(job_dir), updated_mtime=time.time())
        except Exception:
            _logger.exception("failed to update result size index for %s", job_id)
        self._remember(str(job_id), payload)
        self._prune_local_result_views()
        self._run_retention()

    def load_result(self, job_id):
        cached = self._cached(str(job_id))
        if cached is not None:
            return cached
        return self._remember(str(job_id), load_result_bundle(self._dir(job_id, create=False)))

    def load_result_analysis(self, job_id: str, analysis: str):
        cached = self._cached(str(job_id), str(analysis))
        if cached is not None:
            return cached
        full = self._cached(str(job_id))
        if isinstance(full, dict):
            metadata = full.get("metadata") if isinstance(full.get("metadata"), dict) else {}
            requested = metadata.get("requested_analyses") or []
            if str(analysis) in requested or metadata.get("analysis") == str(analysis):
                return self._remember(str(job_id), full, str(analysis))
        value = load_result_bundle(self._dir(job_id, create=False), analysis=analysis)
        return self._remember(str(job_id), value, str(analysis))

    def load_result_summary(self, job_id: str):
        from backend.optical_ml_app.storage.result_bundle import load_result_summary
        return load_result_summary(self._dir(job_id, create=False))

    def list_jobs(self, limit: int = 20, offset: int = 0, status_filter: str | None = None, job_type: str | None = None) -> list[dict]:
        return self.index.list(limit=limit, offset=offset, status_filter=status_filter, job_type=job_type)

    def _run_retention(self, *, force: bool = False) -> list[str]:
        try:
            archived = self.retention.run(force=force)
        except Exception:
            _logger.exception("job retention maintenance failed")
            return []
        for job_id in archived:
            self._invalidate_job_cache(job_id)
        return archived

    def recover_interrupted_jobs(self) -> list[str]:

        recovered: list[str] = []
        for state in ("queued", "running"):
            for item in self.index.list(limit=1_000_000, status_filter=state):
                job_id = str(item.get("job_id", ""))
                if not job_id:
                    continue
                try:
                    status = self.load_status(job_id)
                except (FileNotFoundError, ValueError, OSError):
                    continue
                if status.status not in {"queued", "running"}:
                    continue
                status.status = "failed"
                status.stage = "backend.restarted"
                status.finished_at = datetime.now(timezone.utc).isoformat()
                status.error = ApplicationError(
                    code="BACKEND_RESTARTED",
                    stage="backend.restarted",
                    message="后端在任务进入终态前发生重启，本次任务没有产生正式结果",
                    retryable=True,
                )
                try:
                    self.save_status(status)
                except OSError:
                    _logger.exception("failed to recover interrupted job %s", job_id)
                    continue
                recovered.append(job_id)
        return recovered

    def run_maintenance(self, *, force: bool = False) -> list[str]:
        self._prune_local_result_views(force=force)
        return self._run_retention(force=force)
