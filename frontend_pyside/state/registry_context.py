from __future__ import annotations

from copy import deepcopy
from time import monotonic

from PySide6.QtCore import QObject, Signal


class RegistryContext(QObject):


    datasets_changed = Signal(list)
    models_changed = Signal(list)
    training_tasks_changed = Signal(list)
    current_dataset_changed = Signal(str)
    current_model_changed = Signal(str)
    current_training_task_changed = Signal(str)
    registry_invalidated = Signal(str)

    DEFAULT_TTL_S = 5.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._datasets: list[dict] = []
        self._models: list[dict] = []
        self._training_tasks: list[dict] = []
        self._current_dataset_id = ""
        self._current_model_id = ""
        self._current_training_task_id = ""
        self._refreshed_at = {"datasets": 0.0, "models": 0.0, "training_tasks": 0.0}
        self._refreshing: set[str] = set()

    @property
    def datasets(self) -> list[dict]:
        return deepcopy(self._datasets)

    @property
    def models(self) -> list[dict]:
        return deepcopy(self._models)

    @property
    def training_tasks(self) -> list[dict]:
        return deepcopy(self._training_tasks)

    @property
    def current_dataset_id(self) -> str:
        return self._current_dataset_id

    @property
    def current_model_id(self) -> str:
        return self._current_model_id

    @property
    def current_training_task_id(self) -> str:
        return self._current_training_task_id

    def should_refresh(self, kind: str, *, ttl_s: float | None = None, force: bool = False) -> bool:
        self._require_kind(kind)
        if kind in self._refreshing:
            return False
        ttl = self.DEFAULT_TTL_S if ttl_s is None else max(0.0, float(ttl_s))
        records = self._records(kind)
        fresh = bool(records) and (monotonic() - self._refreshed_at[kind]) < ttl
        if fresh and not force:
            return False
        self._refreshing.add(kind)
        return True

    def refresh_failed(self, kind: str) -> None:
        self._require_kind(kind)
        self._refreshing.discard(kind)

    def invalidate(self, kind: str | None = None) -> None:
        targets = tuple(self._refreshed_at) if kind is None else (kind,)
        for key in targets:
            self._require_kind(key)
            self._refreshed_at[key] = 0.0
            self._refreshing.discard(key)
            self.registry_invalidated.emit(key)

    def cache_age(self, kind: str) -> float:
        self._require_kind(kind)
        value = self._refreshed_at[kind]
        return float("inf") if value <= 0 else max(0.0, monotonic() - value)

    def set_datasets(self, records: list[dict]) -> None:
        self._set_records("datasets", records)

    def merge_dataset(self, record: dict) -> None:
        self._merge_record("datasets", record)

    def set_models(self, records: list[dict]) -> None:
        self._set_records("models", records)

    def merge_model(self, record: dict) -> None:
        self._merge_record("models", record)

    def set_training_tasks(self, records: list[dict]) -> None:
        self._set_records("training_tasks", records)

    def merge_training_task(self, record: dict) -> None:
        self._merge_record("training_tasks", record)

    def set_current_dataset(self, dataset_id: str) -> None:
        value = str(dataset_id or "")
        if value == self._current_dataset_id:
            return
        self._current_dataset_id = value
        self.current_dataset_changed.emit(value)

    def set_current_model(self, model_id: str) -> None:
        value = str(model_id or "")
        if value == self._current_model_id:
            return
        self._current_model_id = value
        self.current_model_changed.emit(value)

    def set_current_training_task(self, task_id: str) -> None:
        value = str(task_id or "")
        if value == self._current_training_task_id:
            return
        self._current_training_task_id = value
        self.current_training_task_changed.emit(value)

    def dataset(self, dataset_id: str) -> dict | None:
        return self._find("datasets", dataset_id)

    def model(self, model_id: str) -> dict | None:
        return self._find("models", model_id)

    def training_task(self, task_id: str) -> dict | None:
        return self._find("training_tasks", task_id)

    def update(self, **values) -> None:

        if "dataset_id" in values:
            self.set_current_dataset(str(values["dataset_id"] or ""))
        if "model_id" in values:
            self.set_current_model(str(values["model_id"] or ""))

    @property
    def current(self) -> dict:
        return {
            "dataset_id": self._current_dataset_id,
            "model_id": self._current_model_id,
            "training_task_id": self._current_training_task_id,
        }

    def _set_records(self, kind: str, records: list[dict]) -> None:
        self._require_kind(kind)
        normalized = [dict(item) for item in records if isinstance(item, dict)]
        existing = self._records(kind)
        changed = normalized != existing
        if kind == "datasets":
            self._datasets = normalized
        elif kind == "models":
            self._models = normalized
        else:
            self._training_tasks = normalized
        self._refreshed_at[kind] = monotonic()
        self._refreshing.discard(kind)
        self._validate_current(kind)
        if changed:
            self._signal(kind).emit(deepcopy(normalized))

    def _merge_record(self, kind: str, record: dict) -> None:
        if not isinstance(record, dict):
            return
        record_id = self._record_id(record, kind)
        if not record_id:
            return
        merged: list[dict] = []
        found = False
        for item in self._records(kind):
            if self._record_id(item, kind) == record_id:
                value = dict(item)
                value.update(record)
                merged.append(value)
                found = True
            else:
                merged.append(dict(item))
        if not found:
            merged.insert(0, dict(record))
        self._set_records(kind, merged)

    def _find(self, kind: str, record_id: str) -> dict | None:
        wanted = str(record_id or "")
        for item in self._records(kind):
            if self._record_id(item, kind) == wanted:
                return deepcopy(item)
        return None

    def _validate_current(self, kind: str) -> None:
        valid_ids = {self._record_id(item, kind) for item in self._records(kind)}
        if kind == "datasets" and self._current_dataset_id and self._current_dataset_id not in valid_ids:
            self.set_current_dataset("")
        elif kind == "models" and self._current_model_id and self._current_model_id not in valid_ids:
            self.set_current_model("")
        elif kind == "training_tasks" and self._current_training_task_id and self._current_training_task_id not in valid_ids:
            self.set_current_training_task("")

    def _records(self, kind: str) -> list[dict]:
        self._require_kind(kind)
        if kind == "datasets":
            return self._datasets
        if kind == "models":
            return self._models
        return self._training_tasks

    def _signal(self, kind: str):
        if kind == "datasets":
            return self.datasets_changed
        if kind == "models":
            return self.models_changed
        return self.training_tasks_changed

    @staticmethod
    def _record_id(record: dict, kind: str) -> str:
        if kind == "datasets":
            return str(record.get("dataset_id", record.get("id", "")) or "")
        if kind == "models":
            return str(record.get("model_id", record.get("id", "")) or "")
        return str(record.get("training_task_id", record.get("job_id", record.get("id", ""))) or "")

    def _require_kind(self, kind: str) -> None:
        if kind not in self._refreshed_at:
            raise ValueError(f"unsupported registry kind: {kind}")


__all__ = ["RegistryContext"]
