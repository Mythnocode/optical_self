from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import csv
import io
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from shared_contracts.datasets import DatasetManifest
from shared_contracts.metrics import canonical_metric_name, metric_definition
from machine_learning.datasets.storage import FileDatasetStore
from machine_learning.datasets.splitter import split_ids

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
            "dataset_name": str((self.metadata or {}).get("dataset_name", self.dataset_id)),
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
            metadata={**dict(manifest.metadata or {}), "dataset_name": manifest.dataset_name},
        )

    def register(self, manifest: DatasetManifest) -> DatasetRegistryEntry:
        entry = self._build_entry(manifest)
        self._store[manifest.dataset_id] = entry
        self._export_flat_csv(manifest.dataset_id)
        return entry

    def import_tabular_file(
        self,
        source_path: str,
        *,
        dataset_name: str = "",
        target_name: str = "coupling_efficiency",
        random_seed: int = 42,
    ) -> DatasetRegistryEntry:
        """Import a local CSV/JSON/JSONL table into the native training store.

        The desktop client deliberately sends a path rather than pretending that a
        selected file has been uploaded.  This endpoint is therefore for the
        normal same-machine desktop deployment; a remote backend rejects an
        unavailable path instead of silently training another dataset.
        """
        path = Path(str(source_path or "")).expanduser()
        if not path.is_file():
            raise DatasetRegistryError(
                code=DATASET_FILE_NOT_FOUND,
                stage="dataset.import",
                message="Selected dataset file is not available to the backend",
                context={"source_path": str(path)},
            )
        suffix = path.suffix.lower()
        if suffix not in {".csv", ".json", ".jsonl", ".ndjson"}:
            raise DatasetRegistryError(
                code="DATASET_IMPORT_FORMAT_UNSUPPORTED",
                stage="dataset.import",
                message="Only CSV, JSON and JSONL tabular files can be imported",
                context={"source_path": str(path)},
            )
        try:
            if suffix == ".csv":
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    raw_rows = [dict(row) for row in csv.DictReader(handle)]
            elif suffix in {".jsonl", ".ndjson"}:
                with path.open("r", encoding="utf-8") as handle:
                    raw_rows = [json.loads(line) for line in handle if line.strip()]
            else:
                value = json.loads(path.read_text(encoding="utf-8"))
                raw_rows = value.get("rows", value.get("items", value.get("data", []))) if isinstance(value, dict) else value
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
            raise DatasetRegistryError(
                code="DATASET_IMPORT_READ_FAILED",
                stage="dataset.import",
                message=f"Could not read the selected dataset: {exc}",
                context={"source_path": str(path)},
            ) from exc
        if not isinstance(raw_rows, list) or not raw_rows:
            raise DatasetRegistryError(
                code="DATASET_IMPORT_EMPTY",
                stage="dataset.import",
                message="The selected file contains no tabular rows",
                context={"source_path": str(path)},
            )

        desired_target = canonical_metric_name(target_name)
        all_keys = {str(key).strip() for row in raw_rows if isinstance(row, dict) for key in row if str(key).strip()}
        canonical_columns = {canonical_metric_name(key): key for key in all_keys}
        if desired_target not in canonical_columns:
            raise DatasetRegistryError(
                code=DATASET_TARGET_COLUMN_MISMATCH,
                stage="dataset.import",
                message=f"Selected target column {desired_target!r} was not found in the file",
                context={"target": desired_target, "columns": sorted(all_keys)},
            )
        target_columns = {
            canonical: source for canonical, source in canonical_columns.items()
            if metric_definition(canonical) is not None
        }
        if desired_target not in target_columns:
            target_columns[desired_target] = canonical_columns[desired_target]

        records: list[dict[str, Any]] = []
        feature_paths: set[str] = set()
        for index, row in enumerate(raw_rows):
            if not isinstance(row, dict):
                continue
            targets: dict[str, float] = {}
            for canonical, source in target_columns.items():
                try:
                    targets[canonical] = float(row.get(source))
                except (TypeError, ValueError):
                    pass
            if desired_target not in targets:
                continue
            features: dict[str, float] = {}
            for key, value in row.items():
                text = str(key).strip()
                if not text or text in target_columns.values() or text in {"sample_id", "id", "valid", "failure_code"}:
                    continue
                try:
                    features[text] = float(value)
                except (TypeError, ValueError):
                    continue
            if not features:
                continue
            feature_paths.update(features)
            records.append({
                "sample_id": str(row.get("sample_id") or row.get("id") or f"import-{index:06d}"),
                "feature_values": features,
                "target_values": targets,
                "valid": True,
                "failure_code": "",
            })
        if not records or not feature_paths:
            raise DatasetRegistryError(
                code="DATASET_IMPORT_NO_NUMERIC_SAMPLES",
                stage="dataset.import",
                message="No rows contain both the selected numeric target and numeric feature columns",
                context={"target": desired_target},
            )

        dataset_id = "external-" + uuid4().hex[:12]
        ids = [str(record["sample_id"]) for record in records]
        train_ids, validation_ids, test_ids = split_ids(ids, 0.70, 0.15, int(random_seed))
        feature_list = sorted(feature_paths)
        manifest = DatasetManifest(
            dataset_id=dataset_id,
            dataset_name=str(dataset_name or path.stem),
            engine_name="external_tabular_file",
            engine_version="1",
            feature_schema_version="external-tabular-v1",
            created_at=datetime.now(timezone.utc).isoformat(),
            sample_count=len(records), valid_sample_count=len(records), failed_sample_count=max(0, len(raw_rows) - len(records)),
            feature_names=feature_list, feature_paths=feature_list, feature_units=["" for _ in feature_list],
            target_names=sorted(target_columns), train_ids=train_ids, validation_ids=validation_ids, test_ids=test_ids,
            random_seed=int(random_seed), source_project_fingerprint=f"external-file:{path.name}",
            metadata={"source_kind": "external_tabular_file", "source_path": str(path), "selected_target": desired_target},
        )
        self._dataset_store.save_manifest(manifest)
        for record in records:
            self._dataset_store.append_sample(dataset_id, record)
        return self.register(manifest)

    def get(self, dataset_id: str) -> DatasetRegistryEntry:
        self.rehydrate()
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
        self.rehydrate()
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
