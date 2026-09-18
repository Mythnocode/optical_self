from pathlib import Path

from machine_learning.datasets.sequence_export import (
    SEQUENCE_NUMERIC_COLUMNS,
    export_sequence_long_table,
)
from machine_learning.datasets.storage import FileDatasetStore
from shared_contracts.datasets import DatasetManifest


def _manifest() -> DatasetManifest:
    return DatasetManifest(
        dataset_id="dataset-sequence-test",
        dataset_name="数据集1",
        engine_name="test",
        engine_version="1",
        feature_schema_version="1",
        created_at="2026-01-01T00:00:00+00:00",
        sample_count=10,
        valid_sample_count=10,
        failed_sample_count=0,
        feature_names=[], feature_paths=[], feature_units=[],
        target_names=["coupling_efficiency"],
        train_ids=[], validation_ids=[], test_ids=[], random_seed=42,
        source_project_fingerprint="test",
        metadata={"source_project": {"surfaces": [
            {"surface_type": "sphere", "material_after": "N-BK7", "radius_mm": 10.0, "distance_to_next_mm": 4.0, "conic": 0.0},
            {"surface_type": "sphere", "material_after": "AIR", "radius_mm": -10.0, "distance_to_next_mm": 8.0, "conic": 0.0},
        ]}},
    )


def test_sequence_export_writes_one_row_per_lens_and_system(tmp_path: Path):
    store = FileDatasetStore(tmp_path)
    manifest = _manifest()
    for index in range(10):
        store.append_sample(manifest.dataset_id, {
            "sample_id": f"sample-{index}", "valid": True,
            "feature_values": {"surfaces[0].radius_mm": 10.0 + index},
            "target_values": {"coupling_efficiency": 0.9},
        })

    details = export_sequence_long_table(manifest, store)

    rows = details["sequence_dataset_path"]
    assert Path(rows).is_file()
    assert details["valid_system_count"] == 10
    assert details["element_count"] == 1
    assert details["numeric_feature_columns"] == list(SEQUENCE_NUMERIC_COLUMNS)
    text = Path(rows).read_text(encoding="utf-8-sig")
    assert text.count("sample-") == 10
    assert "front_radius_mm" in text
