from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import csv
import io
import logging

from shared_contracts.datasets import DatasetManifest
from machine_learning.datasets.storage import FileDatasetStore

from backend.optical_ml_app.domain.error_codes import (
    DATASET_NOT_FOUND,
    DATASET_FILE_NOT_FOUND,
    DATASET_TARGET_COLUMN_MISMATCH,
)
from backend.optical_ml_app.domain.errors import DatasetRegistryError


_logger = logging.getLogger(__name__)


class DatasetRegistryEntry:


    def __init__(
        self,
        dataset_id: str,
        dataset_type: str,
        target_column: str,
        max_surfaces: int,
        sample_count: int,
        output_dir: str,
        manifest_path: str,
        samples_jsonl_path: str,
        samples_flat_csv_path: str,
        created_at: str,
        status: str = "ready",
        metadata: Any = None,
    ) -> None:
        self.dataset_id = dataset_id
        self.dataset_type = dataset_type
        self.target_column = target_column
        self.max_surfaces = max_surfaces
        self.sample_count = sample_count
        self.output_dir = output_dir
        self.manifest_path = manifest_path
        self.samples_jsonl_path = samples_jsonl_path
        self.samples_flat_csv_path = samples_flat_csv_path
        self.created_at = created_at
        self.status = status
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_type": self.dataset_type,
            "target_column": self.target_column,
            "max_surfaces": self.max_surfaces,
            "sample_count": self.sample_count,
            "output_dir": self.output_dir,
            "manifest_path": self.manifest_path,
            "samples_jsonl_path": self.samples_jsonl_path,
            "samples_flat_csv_path": self.samples_flat_csv_path,
            "created_at": self.created_at,
            "status": self.status,
        }

    def to_list_item(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_type": self.dataset_type,
            "target_column": self.target_column,
            "sample_count": self.sample_count,
            "status": self.status,
            "created_at": self.created_at,
        }


class DatasetRegistryService:
    def __init__(self, dataset_store: FileDatasetStore) -> None:
        self._store: Dict[str, DatasetRegistryEntry] = {}
        self._dataset_store = dataset_store
        self.rehydrate()

    def rehydrate(self) -> None:

        root = self._dataset_store.root
        if not root.exists():
            return
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not (child / "manifest.json").exists():
                continue
            try:
                manifest = self._dataset_store.load_manifest(child.name)
                self._store[manifest.dataset_id] = self._build_entry(manifest)
                
                if not (child / "samples_flat.csv").exists():
                    self._export_flat_csv(manifest.dataset_id)
            except Exception:
                
                
                
                _logger.warning(
                    "跳过损坏或未完整写入的数据集目录：%s",
                    child,
                    exc_info=True,
                )
                continue

    def _build_entry(self, manifest: DatasetManifest) -> DatasetRegistryEntry:
        max_surfaces = 0
        for fp in manifest.feature_paths:
            if fp.startswith("surface."):
                try:
                    idx = int(fp.split(".")[1])
                    max_surfaces = max(max_surfaces, idx + 1)
                except (IndexError, ValueError):
                    pass
        if max_surfaces == 0:
            max_surfaces = 20

        dataset_dir = self._dataset_store.dataset_dir(manifest.dataset_id)
        return DatasetRegistryEntry(
            dataset_id=manifest.dataset_id,
            dataset_type=f"headless_lens{max_surfaces}_coupling",
            target_column=manifest.target_names[0] if manifest.target_names else "coupling_efficiency",
            max_surfaces=max_surfaces,
            sample_count=manifest.valid_sample_count,
            output_dir=str(dataset_dir),
            manifest_path=str(dataset_dir / "manifest.json"),
            samples_jsonl_path=str(dataset_dir / "samples.jsonl"),
            samples_flat_csv_path=str(dataset_dir / "samples_flat.csv"),
            created_at=manifest.created_at,
        )

    def register(self, manifest: DatasetManifest) -> DatasetRegistryEntry:
        entry = self._build_entry(manifest)
        self._store[manifest.dataset_id] = entry
        self._export_flat_csv(manifest.dataset_id)
        return entry

    def get(self, dataset_id: str) -> DatasetRegistryEntry:
        entry = self._store.get(dataset_id)
        if entry is None:
            raise DatasetRegistryError(
                code=DATASET_NOT_FOUND,
                stage="dataset.registry",
                message=f"Dataset {dataset_id} not found in registry",
                context={"dataset_id": dataset_id},
            )
        return entry

    def list(
        self,
        dataset_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        items = list(self._store.values())
        if dataset_type:
            items = [e for e in items if e.dataset_type == dataset_type]
        items.sort(key=lambda e: e.created_at, reverse=True)
        total = len(items)
        page = items[offset : offset + limit]
        return {
            "items": [e.to_list_item() for e in page],
            "total": total,
        }

    def read_manifest_json(self, dataset_id: str) -> str:
        entry = self.get(dataset_id)
        path = Path(entry.manifest_path)
        if not path.exists():
            raise DatasetRegistryError(
                code=DATASET_FILE_NOT_FOUND,
                stage="dataset.download",
                message=f"manifest.json not found for dataset {dataset_id}",
                context={"dataset_id": dataset_id, "file": "manifest.json"},
            )
        return path.read_text(encoding="utf-8")

    def read_samples_flat_csv(self, dataset_id: str) -> str:
        entry = self.get(dataset_id)
        path = Path(entry.samples_flat_csv_path)
        if not path.exists():
            raise DatasetRegistryError(
                code=DATASET_FILE_NOT_FOUND,
                stage="dataset.download",
                message=f"samples_flat.csv not found for dataset {dataset_id}",
                context={"dataset_id": dataset_id, "file": "samples_flat.csv"},
            )
        return path.read_text(encoding="utf-8")

    def read_samples_jsonl(self, dataset_id: str) -> str:
        entry = self.get(dataset_id)
        path = Path(entry.samples_jsonl_path)
        if not path.exists():
            raise DatasetRegistryError(
                code=DATASET_FILE_NOT_FOUND,
                stage="dataset.download",
                message=f"samples.jsonl not found for dataset {dataset_id}",
                context={"dataset_id": dataset_id, "file": "samples.jsonl"},
            )
        return path.read_text(encoding="utf-8")

    def validate_for_training(self, dataset_id: str, target_names: List[str]) -> str:
        entry = self.get(dataset_id)
        if target_names and entry.target_column not in target_names:
            raise DatasetRegistryError(
                code=DATASET_TARGET_COLUMN_MISMATCH,
                stage="dataset.training",
                message=f"Target column mismatch: expected {target_names}, got {entry.target_column}",
                context={
                    "dataset_id": dataset_id,
                    "expected": list(target_names),
                    "actual": entry.target_column,
                },
            )
        csv_path = Path(entry.samples_flat_csv_path)
        if not csv_path.exists():
            raise DatasetRegistryError(
                code=DATASET_FILE_NOT_FOUND,
                stage="dataset.training",
                message=f"Flat CSV not found for dataset {dataset_id}",
                context={"dataset_id": dataset_id, "file": "samples_flat.csv"},
            )
        return str(csv_path)

    def _export_flat_csv(self, dataset_id: str) -> None:
        manifest = self._dataset_store.load_manifest(dataset_id)
        output_dir = self._dataset_store.dataset_dir(dataset_id)
        csv_path = output_dir / "samples_flat.csv"

        samples = [r for r in self._dataset_store.iter_samples(dataset_id)
                   if isinstance(r, dict) and r.get("valid", False)]

        if not samples:
            csv_path.write_text("sample_id\n", encoding="utf-8")
            return

        feature_paths = sorted(manifest.feature_paths)
        target_names = manifest.target_names

        all_columns: List[str] = []
        seen: set = set()

        for fpath in feature_paths:
            if fpath not in seen:
                seen.add(fpath)
                all_columns.append(fpath)
            parts = fpath.split(".")
            if len(parts) >= 2 and parts[0] == "surface":
                try:
                    idx = int(parts[1])
                    suffix = ".".join(parts[2:])
                    n = idx + 1
                    while n <= 19:
                        np = f"surface.{n}.{suffix}"
                        if np in feature_paths:
                            break
                        if np not in seen:
                            seen.add(np)
                            all_columns.append(np)
                        n += 1
                except ValueError:
                    pass

        cols = ["sample_id"] + all_columns + target_names + ["valid", "failure_code"]

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)

        for sample in samples:
            fv = sample.get("feature_values", {})
            tv = sample.get("target_values", {})
            row = [sample.get("sample_id", "")]
            for col in all_columns:
                val = fv.get(col)
                row.append(str(val) if val is not None else "")
            for tcol in target_names:
                row.append(str(tv.get(tcol, "")))
            row.append(str(sample.get("valid", False)))
            row.append(sample.get("failure_code", ""))
            writer.writerow(row)

        csv_path.write_text(buf.getvalue(), encoding="utf-8")
