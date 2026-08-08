

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared_contracts.project import ProjectSnapshot
from backend.optical_ml_app.storage.atomic_files import atomic_write_text


class ProjectNotFoundError(KeyError):
    pass


class ProjectRepository:


    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def save(self, project: ProjectSnapshot) -> Path:

        path = self._path_for(project.project_id)
        data = project.model_dump(mode="json")
        data["_stored_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, project_id: str) -> ProjectSnapshot:

        path = self._path_for(project_id)
        if not path.exists():
            raise ProjectNotFoundError(project_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("_stored_at", None)
        return ProjectSnapshot.model_validate(raw)

    def delete(self, project_id: str) -> None:

        path = self._path_for(project_id)
        if path.exists():
            path.unlink()

    def list_ids(self) -> list[str]:

        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [f.stem for f in files]

    def exists(self, project_id: str) -> bool:
        return self._path_for(project_id).exists()

    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------

    def _path_for(self, project_id: str) -> Path:
        name = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in project_id)
        return self.root / f"{name}.json"
