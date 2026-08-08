from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import joblib


class FileModelRegistry:


    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

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
        return path

    def load(self, model_id):
        path = self.root / model_id
        model = joblib.load(path / "model.joblib")
        preprocessing = joblib.load(path / "preprocessing.joblib")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        return model, preprocessing, manifest

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
