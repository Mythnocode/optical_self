from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import time
import zipfile

_logger = logging.getLogger(__name__)


class JobRetentionManager:


    def __init__(self, root: Path, index) -> None:
        self.root = Path(root)
        self.index = index
        self.archive_days = max(1, int(os.getenv("OPTICAL_JOB_ARCHIVE_DAYS", "30")))
        self.max_live = max(50, int(os.getenv("OPTICAL_JOB_MAX_LIVE", "500")))
        self.keep_recent = max(20, int(os.getenv("OPTICAL_JOB_KEEP_RECENT", "200")))
        self._last_run = time.monotonic()

    @staticmethod
    def _timestamp(value: str | None, fallback: float) -> float:
        if not value:
            return fallback
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            return fallback

    @staticmethod
    def _archive_source(source: Path, target_zip: Path) -> None:

        target_zip.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_zip.with_name(f".{target_zip.name}.{os.getpid()}.tmp")
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for item in source.rglob("*"):
                    if not item.is_file():
                        continue
                    relative = item.relative_to(source)
                    if "live_arrays" in relative.parts:
                        continue
                    if item.name.startswith(".") and item.name.endswith(".tmp"):
                        continue
                    archive.write(item, relative.as_posix())
            os.replace(temporary, target_zip)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def run(self, *, force: bool = False) -> list[str]:
        now_mono = time.monotonic()
        if not force and now_mono - self._last_run < 3600.0 and self.index.count() <= self.max_live:
            return []
        self._last_run = now_mono
        candidates = list(self.index.maintenance_candidates())
        if not candidates:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - self.archive_days * 86400.0
        excessive = max(0, self.index.count() - self.keep_recent)
        selected: list[dict] = []
        for record in candidates:
            stamp = self._timestamp(record.get("finished_at"), float(record.get("updated_mtime", 0.0)))
            if stamp < cutoff or len(selected) < excessive:
                selected.append(record)
        archived: list[str] = []
        for record in selected:
            job_id = str(record["job_id"])
            source = self.root / job_id
            if not source.is_dir():
                self.index.delete(job_id)
                continue
            stamp = self._timestamp(record.get("finished_at"), source.stat().st_mtime)
            date = datetime.fromtimestamp(stamp, tz=timezone.utc)
            target_dir = self.root / "_archive" / f"{date.year:04d}-{date.month:02d}"
            target_zip = target_dir / f"{job_id}.zip"
            try:
                self._archive_source(source, target_zip)
                shutil.rmtree(source)
                self.index.delete(job_id)
                archived.append(job_id)
            except OSError:
                
                
                _logger.info("任务归档暂缓，稍后重试: %s", job_id, exc_info=True)
                continue
            except Exception:
                
                _logger.exception("任务归档失败，已跳过: %s", job_id)
                continue
        return archived
