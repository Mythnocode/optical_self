from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from collections import OrderedDict
import json
import joblib
import os
import threading


class FileModelRegistry:


    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache_lock = threading.RLock()
        self._load_cache: OrderedDict[
            tuple[str, int, int, int], tuple[object, object, dict]
        ] = OrderedDict()
        self._cache_size = max(1, int(os.getenv("MODEL_LOAD_CACHE_SIZE", "4")))

    @staticmethod
    def _mtime_ns(path: Path) -> int:
        try:
            return int(path.stat().st_mtime_ns)
        except OSError:
            return -1

    def _load_key(self, model_id: str) -> tuple[str, int, int, int]:
        path = self.root / model_id
        return (
            str(model_id),
            self._mtime_ns(path / "model.joblib"),
            self._mtime_ns(path / "preprocessing.joblib"),
            self._mtime_ns(path / "manifest.json"),
        )

    def artifact_signature(self, model_id: str) -> tuple[str, int, int, int]:
        """Stable cache signature that changes whenever model artifacts change."""

        return self._load_key(str(model_id))

    def _invalidate_model_cache(self, model_id: str) -> None:
        model_id = str(model_id)
        with self._cache_lock:
            for key in tuple(self._load_cache):
                if key[0] == model_id:
                    self._load_cache.pop(key, None)

    def save(self, model_id, model, preprocessing, manifest):
        path = self.root / model_id
        path.mkdir(parents=True, exist_ok=True)
        manifest = dict(manifest)
        manifest.setdefault("model_id", str(model_id))
        manifest.setdefault("name", str(model_id))
        manifest.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        joblib.dump(model, path / "model.joblib")
        joblib.dump(preprocessing, path / "preprocessing.joblib")
        (path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._invalidate_model_cache(str(model_id))
        return path

    def load(self, model_id):
        key = self._load_key(str(model_id))
        with self._cache_lock:
            cached = self._load_cache.pop(key, None)
            if cached is not None:
                self._load_cache[key] = cached
                return cached
        path = self.root / model_id
        model = joblib.load(path / "model.joblib")
        preprocessing = joblib.load(path / "preprocessing.joblib")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        loaded = (model, preprocessing, manifest)
        with self._cache_lock:
            # Drop older signatures for this model before inserting the current
            # one.  A file update therefore invalidates the cache naturally.
            for old_key in tuple(self._load_cache):
                if old_key[0] == str(model_id) and old_key != key:
                    self._load_cache.pop(old_key, None)
            self._load_cache[key] = loaded
            while len(self._load_cache) > self._cache_size:
                self._load_cache.popitem(last=False)
        return loaded

    def cache_info(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "items": len(self._load_cache),
                "capacity": self._cache_size,
            }

    def list_model_ids(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def describe(self, model_id: str) -> dict:
        path = self.root / model_id
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            return {
                "model_id": model_id,
                "name": model_id,
                "status": "incomplete",
                "feature_paths": [],
                "target_names": [],
            }
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "model_id": model_id,
                "name": model_id,
                "status": "invalid_manifest",
                "manifest_error": str(exc),
                "feature_paths": [],
                "target_names": [],
            }
        record = dict(manifest)
        record.setdefault("model_id", model_id)
        record.setdefault("name", model_id)
        record.setdefault("feature_paths", [])
        record.setdefault("feature_names", list(record.get("feature_paths", [])))
        record.setdefault("target_names", [])
        record.setdefault("status", "available")
        if not record.get("created_at"):
            try:
                record["created_at"] = datetime.fromtimestamp(
                    manifest_path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
            except OSError:
                record["created_at"] = ""
        return record

    def list_models(self) -> list[dict]:

        return [self.describe(model_id) for model_id in self.list_model_ids()]
