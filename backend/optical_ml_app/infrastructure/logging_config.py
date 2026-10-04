import datetime
from logging import FileHandler
from pathlib import Path
import json
import logging
import os

from backend.optical_ml_app.infrastructure.log_context import (
    trace_id_var,
    job_id_var,
    request_id_var,
    project_fingerprint_var,
    engine_var,
)


def _set_record_context_default(record, name: str, value: str) -> None:
    current = getattr(record, name, None)
    if current is None or current == "":
        setattr(record, name, str(value or ""))


class ContextFilter(logging.Filter):
    def filter(self, record):
        _set_record_context_default(record, "trace_id", trace_id_var.get())
        _set_record_context_default(record, "job_id", job_id_var.get())
        _set_record_context_default(record, "request_id", request_id_var.get())
        _set_record_context_default(record, "project_fingerprint", project_fingerprint_var.get())
        _set_record_context_default(record, "engine", engine_var.get())
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "job_id": getattr(record, "job_id", ""),
            "request_id": getattr(record, "request_id", ""),
            "project_fingerprint": getattr(record, "project_fingerprint", ""),
            "engine": getattr(record, "engine", ""),
        }
        for key in ("stage", "error_code", "elapsed_ms", "cache_status", "method", "route", "status"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ErrorOnlyFilter(logging.Filter):
    def filter(self, record):
        return record.levelno >= logging.ERROR


class DateRotatingFileHandler(FileHandler):


    def __init__(self, base_filename: str, backup_count: int = 30, encoding: str = "utf-8"):
        self._base_filename = Path(base_filename).resolve()
        self._backup_count = backup_count
        self._current_date: datetime.date | None = None
        
        super().__init__(self._date_stamped_path(), mode="a", encoding=encoding)

    def _date_stamped_path(self, dt: datetime.date | None = None) -> str:
        if dt is None:
            dt = datetime.date.today()
        stem = self._base_filename.stem
        suffix = self._base_filename.suffix
        parent = self._base_filename.parent
        name = f"{stem}.{dt.isoformat()}{suffix}"
        return str(parent / name)

    def _open(self):
        today = datetime.date.today()
        path = self._date_stamped_path(today)

        
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        
        self._current_date = today
        return open(path, self.mode, encoding=self.encoding)

    def emit(self, record):

        today = datetime.date.today()
        if today != self._current_date:
            
            
            
            self.acquire()
            try:
                if self.stream is not None:
                    try:
                        self.flush()
                    finally:
                        self.stream.close()
                self.stream = self._open()
                self._cleanup_old_files()
            finally:
                self.release()
        super().emit(record)

    def _cleanup_old_files(self):

        if self._backup_count <= 0:
            return
        cutoff = datetime.date.today() - datetime.timedelta(days=self._backup_count)
        pattern = f"{self._base_filename.stem}.*{self._base_filename.suffix}"
        for f in self._base_filename.parent.glob(pattern):
            try:
                
                date_str = f.stem.split(".")[-1]
                fd = datetime.date.fromisoformat(date_str)
                if fd < cutoff:
                    f.unlink(missing_ok=True)
            except (ValueError, IndexError):
                pass


def _is_test_env() -> bool:

    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or bool(os.environ.get("CI"))


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    
    
    old_handlers = list(root.handlers)
    root.handlers.clear()
    for handler in old_handlers:
        try:
            handler.close()
        except Exception:
            pass
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    context_filter = ContextFilter()

    
    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    console.addFilter(context_filter)
    root.addHandler(console)

    
    if _is_test_env():
        return

    
    all_file = DateRotatingFileHandler(
        str(log_dir / "application.jsonl"),
        backup_count=30,
    )
    all_file.setFormatter(JsonFormatter())
    all_file.addFilter(context_filter)
    root.addHandler(all_file)

    
    error_file = DateRotatingFileHandler(
        str(log_dir / "error.jsonl"),
        backup_count=90,
    )
    error_file.setFormatter(JsonFormatter())
    error_file.addFilter(context_filter)
    error_file.addFilter(ErrorOnlyFilter())
    root.addHandler(error_file)
