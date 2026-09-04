from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import uuid

from PySide6.QtCore import QSettings


class AssistantConversationStore:
    """Small QSettings-backed conversation store for the in-app research assistant."""

    KEY = "assistant/conversations_v2"
    MAX_CONVERSATIONS = 120

    def __init__(self) -> None:
        self.settings = QSettings("OpticalMLWorkspace", "OpticalFrontend")
        self._records = self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _load(self) -> list[dict]:
        raw = self.settings.value(self.KEY, "")
        if not raw:
            return []
        try:
            rows = json.loads(str(raw))
        except Exception:
            return []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _save(self) -> None:
        rows = sorted(
            self._records,
            key=lambda row: (bool(row.get("pinned")), str(row.get("updated_at", ""))),
            reverse=True,
        )[: self.MAX_CONVERSATIONS]
        self._records = rows
        self.settings.setValue(self.KEY, json.dumps(rows, ensure_ascii=False, default=str))

    def all(self) -> list[dict]:
        return deepcopy(self._records)

    def get(self, conversation_id: str) -> dict | None:
        row = next((item for item in self._records if str(item.get("id")) == str(conversation_id)), None)
        return deepcopy(row) if row else None

    def create(self, *, snapshot: dict | None = None, title: str = "新对话") -> dict:
        now = self._now()
        row = {
            "id": uuid.uuid4().hex,
            "title": str(title or "新对话"),
            "created_at": now,
            "updated_at": now,
            "pinned": False,
            "snapshot": deepcopy(snapshot or {}),
            "messages": [],
        }
        self._records.insert(0, row)
        self._save()
        return deepcopy(row)

    def append(self, conversation_id: str, role: str, content: str, *, html: bool = False) -> None:
        row = next((item for item in self._records if str(item.get("id")) == str(conversation_id)), None)
        if row is None:
            return
        row.setdefault("messages", []).append({
            "role": str(role), "content": str(content), "html": bool(html), "time": self._now()
        })
        if role == "user" and str(row.get("title", "")) in {"", "新对话"}:
            compact = " ".join(str(content).split())
            row["title"] = compact[:26] + ("…" if len(compact) > 26 else "")
        row["updated_at"] = self._now()
        self._save()

    def update_snapshot(self, conversation_id: str, snapshot: dict) -> None:
        row = next((item for item in self._records if str(item.get("id")) == str(conversation_id)), None)
        if row is None:
            return
        row["snapshot"] = deepcopy(snapshot or {})
        row["updated_at"] = self._now()
        self._save()

    def rename(self, conversation_id: str, title: str) -> None:
        row = next((item for item in self._records if str(item.get("id")) == str(conversation_id)), None)
        if row is None or not str(title).strip():
            return
        row["title"] = str(title).strip()
        row["updated_at"] = self._now()
        self._save()

    def toggle_pin(self, conversation_id: str) -> bool:
        row = next((item for item in self._records if str(item.get("id")) == str(conversation_id)), None)
        if row is None:
            return False
        row["pinned"] = not bool(row.get("pinned"))
        row["updated_at"] = self._now()
        self._save()
        return bool(row["pinned"])

    def delete(self, conversation_id: str) -> None:
        self._records = [item for item in self._records if str(item.get("id")) != str(conversation_id)]
        self._save()


__all__ = ["AssistantConversationStore"]
