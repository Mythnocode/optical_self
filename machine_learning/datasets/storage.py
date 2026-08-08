from pathlib import Path
from typing import Dict, Iterable
import json
from shared_contracts.datasets import DatasetManifest


class FileDatasetStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def dataset_dir(self, dataset_id: str) -> Path:
        path = self.root / dataset_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def append_sample(self, dataset_id: str, sample: Dict) -> None:
        path = self.dataset_dir(dataset_id) / "samples.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

    def save_manifest(self, manifest: DatasetManifest) -> None:
        path = self.dataset_dir(manifest.dataset_id) / "manifest.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def load_manifest(self, dataset_id: str) -> DatasetManifest:
        text = (self.dataset_dir(dataset_id) / "manifest.json").read_text(encoding="utf-8")
        return DatasetManifest.model_validate_json(text)

    def iter_samples(self, dataset_id: str) -> Iterable[Dict]:
        path = self.dataset_dir(dataset_id) / "samples.jsonl"
        if not path.exists():
            return iter(())
        def iterator():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)
        return iterator()
